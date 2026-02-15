# -*- coding: utf-8 -*-
"""Embedded local HTTP tile proxy for streamed XYZ layers."""

from __future__ import annotations

from collections import OrderedDict
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class LocalTileProxy:
    def __init__(self, source_service):
        self._source_service = source_service
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._source_lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._cache_max_entries = 1400
        self._cache_ttl_seconds = 300
        self._stale_ttl_seconds = 3600
        self._stats = {
            "requests_total": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "served_success": 0,
            "served_stale": 0,
            "upstream_errors": 0,
            "inflight": 0,
            "last_status": 0,
            "last_error": "",
            "started_at": time.time(),
        }

    def set_source_service(self, source_service) -> None:
        with self._source_lock:
            self._source_service = source_service

    def start(self) -> None:
        if self._server is not None:
            return
        server = ThreadingHTTPServer(("127.0.0.1", 0), self._make_handler())
        thread = threading.Thread(target=server.serve_forever, daemon=True, name="ImageMateTileProxy")
        thread.start()
        self._server = server
        self._thread = thread

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        if server is None:
            return
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass
        if thread is not None and thread.is_alive():
            try:
                thread.join(timeout=1.5)
            except Exception:
                pass

    @property
    def base_url(self) -> str:
        server = self._server
        if server is None:
            return ""
        host, port = server.server_address
        return f"http://{host}:{int(port)}"

    def is_running(self) -> bool:
        return self._server is not None and bool(self._thread and self._thread.is_alive())

    def stats_snapshot(self) -> dict:
        with self._stats_lock:
            out = dict(self._stats)
        with self._cache_lock:
            out["cache_entries"] = len(self._cache)
        out["uptime_seconds"] = max(0, int(time.time() - float(out.get("started_at") or time.time())))
        return out

    def _make_handler(self):
        proxy = self
        tile_path_rx = re.compile(r"^/satellogic/cog/tiles/(?P<z>\d+)/(?P<x>\d+)/(?P<y>\d+)$")

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path == "/health":
                    body = {"status": "ok", "running": proxy.is_running()}
                    self._write(200, json.dumps(body).encode("utf-8"), "application/json")
                    return
                if parsed.path == "/stats":
                    self._write(200, json.dumps(proxy.stats_snapshot()).encode("utf-8"), "application/json")
                    return

                match = tile_path_rx.match(parsed.path or "")
                if not match:
                    self._write(404, b'{"detail":"not found"}', "application/json")
                    return

                qs = parse_qs(parsed.query or "", keep_blank_values=False)
                source_url = str((qs.get("url") or [""])[0]).strip()
                if not source_url:
                    self._write(400, b'{"detail":"url query param is required"}', "application/json")
                    return

                contract_id = str((qs.get("contract_id") or [""])[0]).strip() or None
                scale = _to_int((qs.get("scale") or ["2"])[0], 2)
                buffer = _to_int((qs.get("buffer") or ["1"])[0], 1)
                tile_matrix_set_id = str((qs.get("tileMatrixSetId") or ["WebMercatorQuad"])[0]).strip() or "WebMercatorQuad"
                image_format = str((qs.get("format") or ["png"])[0]).strip() or "png"
                bands_raw = qs.get("bidx") or ["1", "2", "3"]
                bands = [_to_int(value, 1) for value in bands_raw if str(value).strip()]
                if not bands:
                    bands = [1, 2, 3]
                z = int(match.group("z"))
                x = int(match.group("x"))
                y = int(match.group("y"))
                cache_key = proxy._cache_key(
                    z=z,
                    x=x,
                    y=y,
                    source_url=source_url,
                    contract_id=contract_id,
                    scale=scale,
                    buffer=buffer,
                    tile_matrix_set_id=tile_matrix_set_id,
                    image_format=image_format,
                    bands=bands,
                )

                proxy._request_started()
                try:
                    cached = proxy._cache_get(cache_key, allow_stale=False)
                    if cached is not None:
                        proxy._stat_inc("cache_hits")
                        proxy._stat_inc("served_success")
                        proxy._set_last(status=200)
                        headers = {"Cache-Control": "public, max-age=300", "X-Proxy-Cache": "hit"}
                        self._write(200, cached["content"], cached["media_type"], headers=headers)
                        return
                    proxy._stat_inc("cache_misses")

                    with proxy._source_lock:
                        service = proxy._source_service
                    status, content, media_type = service.fetch_satellogic_cog_tile(
                        z=z,
                        x=x,
                        y=y,
                        source_url=source_url,
                        contract_id=contract_id,
                        scale=scale,
                        buffer=buffer,
                        tile_matrix_set_id=tile_matrix_set_id,
                        image_format=image_format,
                        bidx=bands,
                        max_attempts=3,
                        request_timeout=75,
                    )
                    if int(status) >= 400:
                        stale = proxy._cache_get(cache_key, allow_stale=True)
                        if stale is not None:
                            proxy._stat_inc("served_stale")
                            proxy._set_last(status=200, error=f"served_stale_from_{status}")
                            headers = {"Cache-Control": "public, max-age=120", "X-Proxy-Cache": "stale"}
                            self._write(200, stale["content"], stale["media_type"], headers=headers)
                            return
                        proxy._stat_inc("upstream_errors")
                        proxy._set_last(status=int(status), error=f"upstream_status_{status}")
                        detail = {"detail": f"Upstream tile fetch failed ({status})"}
                        self._write(int(status), json.dumps(detail).encode("utf-8"), "application/json")
                        return

                    proxy._cache_put(cache_key, content, media_type)
                    proxy._stat_inc("served_success")
                    proxy._set_last(status=200)
                    headers = {"Cache-Control": "public, max-age=300", "X-Proxy-Cache": "miss"}
                    self._write(200, content, media_type, headers=headers)
                except Exception as exc:
                    proxy._stat_inc("upstream_errors")
                    proxy._set_last(status=502, error=str(exc))
                    detail = {"detail": f"Tile proxy failed: {exc}"}
                    self._write(502, json.dumps(detail).encode("utf-8"), "application/json")
                finally:
                    proxy._request_finished()

            def log_message(self, _fmt, *_args):  # noqa: D401
                # QGIS plugin local tile traffic is noisy; suppress per-request logs.
                return

            def _write(self, code: int, body: bytes, media_type: str, headers: dict[str, str] | None = None) -> None:
                payload = body if isinstance(body, (bytes, bytearray)) else bytes(body or b"")
                self.send_response(int(code))
                self.send_header("Content-Type", str(media_type or "application/octet-stream"))
                self.send_header("Content-Length", str(len(payload)))
                if headers:
                    for key, value in headers.items():
                        self.send_header(str(key), str(value))
                self.end_headers()
                if payload:
                    self.wfile.write(payload)

        return Handler

    def _cache_key(
        self,
        *,
        z: int,
        x: int,
        y: int,
        source_url: str,
        contract_id: str | None,
        scale: int,
        buffer: int,
        tile_matrix_set_id: str,
        image_format: str,
        bands: list[int],
    ) -> str:
        return "|".join(
            [
                str(z),
                str(x),
                str(y),
                str(source_url),
                str(contract_id or ""),
                str(scale),
                str(buffer),
                str(tile_matrix_set_id),
                str(image_format),
                ",".join([str(int(v)) for v in bands]),
            ]
        )

    def _cache_get(self, key: str, *, allow_stale: bool) -> dict | None:
        now = time.time()
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            expires_at = float(entry.get("expires_at") or 0.0)
            stale_until = float(entry.get("stale_until") or 0.0)
            if expires_at > now:
                self._cache.move_to_end(key)
                return entry
            if allow_stale and stale_until > now:
                self._cache.move_to_end(key)
                return entry
            self._cache.pop(key, None)
            return None

    def _cache_put(self, key: str, content: bytes, media_type: str) -> None:
        now = time.time()
        entry = {
            "content": bytes(content or b""),
            "media_type": str(media_type or "image/png"),
            "expires_at": now + float(self._cache_ttl_seconds),
            "stale_until": now + float(self._stale_ttl_seconds),
        }
        with self._cache_lock:
            self._cache[key] = entry
            self._cache.move_to_end(key)
            while len(self._cache) > int(self._cache_max_entries):
                self._cache.popitem(last=False)

    def _request_started(self) -> None:
        with self._stats_lock:
            self._stats["requests_total"] = int(self._stats.get("requests_total") or 0) + 1
            self._stats["inflight"] = int(self._stats.get("inflight") or 0) + 1

    def _request_finished(self) -> None:
        with self._stats_lock:
            self._stats["inflight"] = max(0, int(self._stats.get("inflight") or 0) - 1)

    def _stat_inc(self, key: str, delta: int = 1) -> None:
        with self._stats_lock:
            self._stats[key] = int(self._stats.get(key) or 0) + int(delta)

    def _set_last(self, *, status: int, error: str = "") -> None:
        with self._stats_lock:
            self._stats["last_status"] = int(status or 0)
            self._stats["last_error"] = str(error or "")


def _to_int(value, fallback: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(fallback)
