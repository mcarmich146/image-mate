# -*- coding: utf-8 -*-
"""Embedded local HTTP tile proxy for streamed XYZ layers."""

from __future__ import annotations

from collections import OrderedDict
import io
import json
import math
import re
import struct
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

_TRANSPARENT_TILE_CACHE: dict[int, bytes] = {}

try:
    from PIL import Image

    _HAS_PIL = True
except Exception:
    Image = None
    _HAS_PIL = False

try:
    from qgis.PyQt.QtCore import QBuffer, QIODevice
    from qgis.PyQt.QtGui import QImage, QPainter

    _HAS_QIMAGE = True
except Exception:
    QBuffer = None
    QIODevice = None
    QImage = None
    QPainter = None
    _HAS_QIMAGE = False


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    chunk_type = bytes(tag or b"")
    payload = bytes(data or b"")
    checksum = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    return struct.pack("!I", len(payload)) + chunk_type + payload + struct.pack("!I", checksum)


def _transparent_png(size: int) -> bytes:
    tile_size = max(1, int(size or 256))
    cached = _TRANSPARENT_TILE_CACHE.get(tile_size)
    if cached is not None:
        return cached

    # PNG filter byte per row + RGBA pixels.
    row = b"\x00" + (b"\x00\x00\x00\x00" * tile_size)
    raw = row * tile_size
    compressed = zlib.compress(raw, level=9)
    ihdr = struct.pack("!IIBBBBB", tile_size, tile_size, 8, 6, 0, 0, 0)
    payload = b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", ihdr),
            _png_chunk(b"IDAT", compressed),
            _png_chunk(b"IEND", b""),
        ]
    )
    _TRANSPARENT_TILE_CACHE[tile_size] = payload
    return payload


def _is_valid_png(payload: bytes) -> bool:
    data = bytes(payload or b"")
    if len(data) < 33:
        return False
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    ihdr_len = struct.unpack("!I", data[8:12])[0]
    if ihdr_len != 13:
        return False
    return data[12:16] == b"IHDR"


def _alpha_composite_png_payloads(png_payloads: list[bytes]) -> bytes | None:
    layers = [bytes(payload or b"") for payload in (png_payloads or []) if payload]
    if not layers:
        return None
    if len(layers) == 1 and _is_valid_png(layers[0]):
        return layers[0]

    if _HAS_PIL:
        try:
            composed = None
            for payload in layers:
                layer = Image.open(io.BytesIO(payload)).convert("RGBA")
                if composed is None:
                    composed = layer
                else:
                    composed = Image.alpha_composite(composed, layer)
            if composed is None:
                return None
            out = io.BytesIO()
            composed.save(out, format="PNG")
            encoded = out.getvalue()
            if _is_valid_png(encoded):
                return encoded
        except Exception:
            pass

    if _HAS_QIMAGE:
        try:
            composed_img = None
            for payload in layers:
                layer = QImage.fromData(payload, "PNG")
                if layer.isNull():
                    continue
                if layer.format() != QImage.Format_ARGB32:
                    layer = layer.convertToFormat(QImage.Format_ARGB32)
                if composed_img is None:
                    composed_img = QImage(layer)
                    continue
                painter = QPainter(composed_img)
                try:
                    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
                    painter.drawImage(0, 0, layer)
                finally:
                    painter.end()
            if composed_img is None or composed_img.isNull():
                return None
            buffer = QBuffer()
            buffer.open(QIODevice.WriteOnly)
            try:
                if not composed_img.save(buffer, "PNG"):
                    return None
                encoded = bytes(buffer.data())
            finally:
                buffer.close()
            if _is_valid_png(encoded):
                return encoded
        except Exception:
            pass

    return None


def _png_alpha_extrema(payload: bytes) -> tuple[int, int] | None:
    raw = bytes(payload or b"")
    if not raw or not _is_valid_png(raw):
        return None

    if _HAS_PIL:
        try:
            image = Image.open(io.BytesIO(raw)).convert("RGBA")
            alpha = image.getchannel("A")
            extrema = alpha.getextrema()
            if isinstance(extrema, tuple) and len(extrema) == 2:
                return int(extrema[0]), int(extrema[1])
        except Exception:
            pass

    if _HAS_QIMAGE:
        try:
            image = QImage.fromData(raw, "PNG")
            if image.isNull():
                return None
            if image.format() != QImage.Format_ARGB32:
                image = image.convertToFormat(QImage.Format_ARGB32)
            width = max(0, int(image.width()))
            height = max(0, int(image.height()))
            if width <= 0 or height <= 0:
                return None
            min_alpha = 255
            max_alpha = 0
            for row in range(height):
                for col in range(width):
                    alpha_value = (int(image.pixel(col, row)) >> 24) & 0xFF
                    if alpha_value < min_alpha:
                        min_alpha = alpha_value
                    if alpha_value > max_alpha:
                        max_alpha = alpha_value
                    if min_alpha == 0 and max_alpha == 255:
                        return 0, 255
            return int(min_alpha), int(max_alpha)
        except Exception:
            pass

    return None


def _extract_embedded_tile_options(url_value: str) -> tuple[str, dict[str, list[str]]]:
    value = str(url_value or "").strip()
    if not value or "&" not in value or "=" not in value:
        return value, {}

    base_url, sep, tail = value.partition("&")
    if not sep or not tail or "=" not in tail:
        return value, {}

    parsed = parse_qs(tail, keep_blank_values=False)
    if not parsed:
        return value, {}

    recognized = {
        "tileMatrixSetId",
        "format",
        "scale",
        "buffer",
        "bidx",
        "contract_id",
    }
    embedded: dict[str, list[str]] = {}
    for key in recognized:
        values = parsed.get(key) or []
        cleaned = [str(item).strip() for item in values if str(item).strip()]
        if cleaned:
            embedded[key] = cleaned

    if not embedded:
        return value, {}
    return base_url, embedded


def _parse_bbox_token(value: str) -> tuple[float, float, float, float] | None:
    raw = str(value or "").strip()
    if not raw or raw == "-":
        return None
    parts = [str(piece).strip() for piece in raw.split(",")]
    if len(parts) != 4:
        return None
    try:
        minx = float(parts[0])
        miny = float(parts[1])
        maxx = float(parts[2])
        maxy = float(parts[3])
    except Exception:
        return None
    if not all(math.isfinite(v) for v in (minx, miny, maxx, maxy)):
        return None
    lo_x = min(minx, maxx)
    hi_x = max(minx, maxx)
    lo_y = min(miny, maxy)
    hi_y = max(miny, maxy)
    return lo_x, lo_y, hi_x, hi_y


def _tile_bounds_wgs84(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    n = float(2 ** max(0, int(z)))
    x0 = float(x)
    y0 = float(y)
    min_lon = (x0 / n) * 360.0 - 180.0
    max_lon = ((x0 + 1.0) / n) * 360.0 - 180.0
    lat_top = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * (y0 / n)))))
    lat_bottom = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * ((y0 + 1.0) / n)))))
    min_lat = min(lat_top, lat_bottom)
    max_lat = max(lat_top, lat_bottom)
    return min_lon, min_lat, max_lon, max_lat


def _expand_bbox_wgs84(
    bbox: tuple[float, float, float, float],
    *,
    lon_pad: float,
    lat_pad: float,
) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = bbox
    return (
        max(-180.0, float(minx) - float(max(0.0, lon_pad))),
        max(-85.05112878, float(miny) - float(max(0.0, lat_pad))),
        min(180.0, float(maxx) + float(max(0.0, lon_pad))),
        min(85.05112878, float(maxy) + float(max(0.0, lat_pad))),
    )


def _bbox_intersects(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    a_minx, a_miny, a_maxx, a_maxy = a
    b_minx, b_miny, b_maxx, b_maxy = b
    return not (
        float(a_maxx) < float(b_minx)
        or float(b_maxx) < float(a_minx)
        or float(a_maxy) < float(b_miny)
        or float(b_maxy) < float(a_miny)
    )


def _is_l1d_sr_source(source_url: str) -> bool:
    value = str(source_url or "").strip().lower()
    if not value:
        return False
    return "/l1d_sr/" in value or "/l1d-sr/" in value


class LocalTileProxy:
    def __init__(self, source_service, event_logger=None):
        self._source_service = source_service
        self._event_logger = event_logger
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._source_lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._cache_max_entries = 1400
        self._cache_ttl_seconds = 300
        self._stale_ttl_seconds = 3600
        self._inflight_tile_lock = threading.Lock()
        self._inflight_tile_events: dict[str, threading.Event] = {}
        self._coalesce_wait_seconds = 18.0
        self._probe_failure_lock = threading.Lock()
        self._probe_failure_cache: OrderedDict[str, dict] = OrderedDict()
        self._probe_failure_cache_max_entries = 8000
        self._probe_failure_ttl_seconds = 240
        # Keep local proxy responsive for large AOIs:
        # cap sibling-strip fanout and fail fast per tile request.
        self._max_sources_per_request = 8
        self._max_sources_per_request_l1d_sr = 256
        # Increased timeout to 2 minutes for large tiles on slow connections
        self._upstream_timeout_seconds = 120
        self._upstream_max_attempts = 1
        # Increased time budget to allow trying multiple sources with longer timeouts
        self._upstream_time_budget_seconds = 150.0
        self._fallback_target_success_layers = 1
        self._fallback_max_probes = 6
        self._fallback_max_probes_l1d_sr = 13
        self._perf_log_slow_tile_ms = 3000.0
        self._perf_log_summary_every = 25
        self._perf_log_every_tile = False
        self._source_priority_lock = threading.Lock()
        self._source_probe_success: dict[str, int] = {}
        self._source_probe_seen: dict[str, int] = {}
        self._source_probe_cap = 2048
        self._stats = {
            "requests_total": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "served_success": 0,
            "served_empty": 0,
            "served_stale": 0,
            "upstream_errors": 0,
            "inflight": 0,
            "last_status": 0,
            "last_error": "",
            "perf_samples": 0,
            "perf_total_ms": 0.0,
            "perf_max_ms": 0.0,
            "perf_cache_hit_tiles": 0,
            "perf_mosaic_tiles": 0,
            "perf_fallback_tiles": 0,
            "perf_composite_tiles": 0,
            "perf_empty_tiles": 0,
            "perf_stale_tiles": 0,
            "perf_exception_tiles": 0,
            "started_at": time.time(),
        }

    def set_source_service(self, source_service) -> None:
        with self._source_lock:
            self._source_service = source_service

    def set_event_logger(self, event_logger) -> None:
        self._event_logger = event_logger

    def _emit_event(self, message: str, *, level: str = "info") -> None:
        callback = self._event_logger
        if callback is None:
            return
        try:
            callback(str(message or "").strip(), str(level or "info"))
        except Exception:
            return

    def start(self) -> None:
        if self._server is not None:
            return
        server = ThreadingHTTPServer(("127.0.0.1", 0), self._make_handler())
        thread = threading.Thread(target=server.serve_forever, daemon=True, name="ImageMateTileProxy")
        thread.start()
        self._server = server
        self._thread = thread
        self._emit_event(
            (
                "tile perf config "
                f"max_sources={int(self._max_sources_per_request or 0)} "
                f"max_sources_l1d_sr={int(self._max_sources_per_request_l1d_sr or 0)} "
                f"upstream_timeout_s={int(self._upstream_timeout_seconds or 0)} "
                f"upstream_budget_s={float(self._upstream_time_budget_seconds or 0.0):.1f} "
                f"fallback_target_layers={int(self._fallback_target_success_layers or 0)} "
                f"fallback_probe_cap={int(self._fallback_max_probes or 0)} "
                f"fallback_probe_cap_l1d_sr={int(self._fallback_max_probes_l1d_sr or 0)} "
                f"coalesce_wait_s={float(self._coalesce_wait_seconds or 0.0):.1f} "
                f"probe_fail_ttl_s={int(self._probe_failure_ttl_seconds or 0)} "
                f"slow_tile_ms={float(self._perf_log_slow_tile_ms or 0.0):.1f} "
                f"summary_every={int(self._perf_log_summary_every or 0)}"
            ),
            level="info",
        )

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
        telluric_tile_path_rx = re.compile(r"^/satellogic/telluric/tiles/(?P<z>\d+)/(?P<x>\d+)/(?P<y>\d+)$")

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                tile_started = time.perf_counter()
                cache_lookup_ms = 0.0
                mosaic_ms = 0.0
                fallback_ms = 0.0
                compose_ms = 0.0
                probes = 0
                successful_layers_count = 0
                attempted_statuses: list[str] = []
                source_count_used = 0
                source_count_total = 0
                parsed = urlparse(self.path)
                if parsed.path == "/health":
                    body = {"status": "ok", "running": proxy.is_running()}
                    self._write(200, json.dumps(body).encode("utf-8"), "application/json")
                    return
                if parsed.path == "/stats":
                    self._write(200, json.dumps(proxy.stats_snapshot()).encode("utf-8"), "application/json")
                    return

                telluric_match = telluric_tile_path_rx.match(parsed.path or "")
                if telluric_match is not None:
                    self._handle_telluric_tile_request(parsed=parsed, match=telluric_match)
                    return

                match = tile_path_rx.match(parsed.path or "")
                if not match:
                    self._write(404, b'{"detail":"not found"}', "application/json")
                    return

                qs = parse_qs(parsed.query or "", keep_blank_values=False)
                raw_source_urls = [str(value).strip() for value in (qs.get("url") or []) if str(value).strip()]
                raw_source_bboxes = [str(value).strip() for value in (qs.get("source_bbox") or [])]
                if not raw_source_urls:
                    self._write(400, b'{"detail":"url query param is required"}', "application/json")
                    return

                query_keys = set(qs.keys())
                source_urls = []
                seen_sources = set()
                source_bbox_by_url: dict[str, tuple[float, float, float, float]] = {}
                for idx, raw_source in enumerate(raw_source_urls):
                    extracted_url, embedded_options = _extract_embedded_tile_options(raw_source)
                    source_url = str(extracted_url or "").strip()
                    if source_url and source_url not in seen_sources:
                        seen_sources.add(source_url)
                        source_urls.append(source_url)
                        if idx < len(raw_source_bboxes):
                            bbox = _parse_bbox_token(raw_source_bboxes[idx])
                            if bbox is not None:
                                source_bbox_by_url[source_url] = bbox
                    if embedded_options:
                        if "contract_id" not in query_keys:
                            contract_vals = embedded_options.get("contract_id") or []
                            if contract_vals:
                                qs["contract_id"] = [contract_vals[0]]
                        if "scale" not in query_keys:
                            scale_vals = embedded_options.get("scale") or []
                            if scale_vals:
                                qs["scale"] = [scale_vals[0]]
                        if "buffer" not in query_keys:
                            buffer_vals = embedded_options.get("buffer") or []
                            if buffer_vals:
                                qs["buffer"] = [buffer_vals[0]]
                        if "tileMatrixSetId" not in query_keys:
                            matrix_vals = embedded_options.get("tileMatrixSetId") or []
                            if matrix_vals:
                                qs["tileMatrixSetId"] = [matrix_vals[0]]
                        if "format" not in query_keys:
                            format_vals = embedded_options.get("format") or []
                            if format_vals:
                                qs["format"] = [format_vals[0]]
                        if "bidx" not in query_keys and (embedded_options.get("bidx") or []):
                            qs["bidx"] = list(embedded_options.get("bidx") or [])

                if not source_urls:
                    self._write(400, b'{"detail":"url query param is required"}', "application/json")
                    return
                source_count_total = len(source_urls)
                max_sources = max(1, int(proxy._max_sources_per_request or 1))
                is_l1d_sr_request = any(_is_l1d_sr_source(url_value) for url_value in source_urls)
                if is_l1d_sr_request:
                    max_sources = max(max_sources, int(proxy._max_sources_per_request_l1d_sr or max_sources))
                if source_count_total > max_sources:
                    source_urls = source_urls[:max_sources]
                source_count_used = len(source_urls)
                source_count_dropped = max(0, int(source_count_total) - int(source_count_used))
                source_count_label = (
                    f"{source_count_used}/{source_count_total}" if source_count_dropped > 0 else str(source_count_used)
                )

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
                source_urls_for_key = sorted([str(value) for value in (source_urls or [])])
                cache_key = proxy._cache_key(
                    z=z,
                    x=x,
                    y=y,
                    source_urls=source_urls_for_key,
                    contract_id=contract_id,
                    scale=scale,
                    buffer=buffer,
                    tile_matrix_set_id=tile_matrix_set_id,
                    image_format=image_format,
                    bands=bands,
                )

                proxy._request_started()
                owns_inflight_slot = False
                inflight_event: threading.Event | None = None
                try:
                    cache_started = time.perf_counter()
                    cached = proxy._cache_get(cache_key, allow_stale=False)
                    cache_lookup_ms = (time.perf_counter() - cache_started) * 1000.0
                    if cached is not None:
                        proxy._stat_inc("cache_hits")
                        proxy._stat_inc("served_success")
                        proxy._set_last(status=200)
                        proxy._record_perf_sample(
                            z=z,
                            x=x,
                            y=y,
                            path="cache_hit",
                            total_ms=(time.perf_counter() - tile_started) * 1000.0,
                            source_count_used=source_count_used,
                            source_count_total=source_count_total,
                            cache_lookup_ms=cache_lookup_ms,
                            attempted_statuses=attempted_statuses,
                        )
                        headers = {"Cache-Control": "public, max-age=300", "X-Proxy-Cache": "hit"}
                        self._write(200, cached["content"], cached["media_type"], headers=headers)
                        return
                    proxy._stat_inc("cache_misses")

                    owns_inflight_slot, inflight_event = proxy._acquire_inflight_tile(cache_key)
                    if not owns_inflight_slot:
                        wait_timeout = max(2.0, float(proxy._coalesce_wait_seconds or 2.0))
                        wait_started = time.perf_counter()
                        try:
                            inflight_event.wait(timeout=wait_timeout)
                        except Exception:
                            pass
                        wait_ms = (time.perf_counter() - wait_started) * 1000.0
                        attempted_statuses.append(f"coalesced_wait:{wait_ms:.0f}")
                        cached_after_wait = proxy._cache_get(cache_key, allow_stale=False)
                        if cached_after_wait is not None:
                            proxy._stat_inc("cache_hits")
                            proxy._stat_inc("served_success")
                            proxy._set_last(status=200)
                            proxy._record_perf_sample(
                                z=z,
                                x=x,
                                y=y,
                                path="coalesced_hit",
                                total_ms=(time.perf_counter() - tile_started) * 1000.0,
                                source_count_used=source_count_used,
                                source_count_total=source_count_total,
                                cache_lookup_ms=cache_lookup_ms,
                                attempted_statuses=attempted_statuses,
                            )
                            headers = {"Cache-Control": "public, max-age=300", "X-Proxy-Cache": "coalesced"}
                            self._write(200, cached_after_wait["content"], cached_after_wait["media_type"], headers=headers)
                            return
                        owns_inflight_slot, inflight_event = proxy._acquire_inflight_tile(cache_key)
                        if not owns_inflight_slot:
                            attempted_statuses.append("coalesce_busy")

                    with proxy._source_lock:
                        service = proxy._source_service
                    selected_source_url = ""
                    selected_content = b""
                    selected_media_type = "image/png"
                    fallback_status = 404
                    fallback_content = b""
                    fallback_source = source_urls[0]

                    # Request mosaic first so strip boundaries are blended upstream.
                    mosaic_started = time.perf_counter()
                    try:
                        status, content, media_type = service.fetch_satellogic_cog_tile(
                            z=z,
                            x=x,
                            y=y,
                            source_urls=source_urls,
                            contract_id=contract_id,
                            scale=scale,
                            buffer=buffer,
                            tile_matrix_set_id=tile_matrix_set_id,
                            image_format=image_format,
                            bidx=bands,
                            max_attempts=max(1, int(proxy._upstream_max_attempts or 1)),
                            request_timeout=max(8, int(proxy._upstream_timeout_seconds or 8)),
                        )
                    except Exception as exc:
                        status = 502
                        content = str(exc).encode("utf-8", errors="replace")
                        media_type = "application/json"
                        attempted_statuses.append(f"mosaic_exc:{exc.__class__.__name__}")
                    mosaic_ms = (time.perf_counter() - mosaic_started) * 1000.0

                    status = int(status)
                    media_type = str(media_type or "image/png").split(";")[0].strip() or "image/png"
                    if status < 400 and media_type.lower() == "image/png" and not _is_valid_png(content):
                        status = 502
                        content = b'{"detail":"invalid PNG from upstream"}'

                    if status < 400:
                        selected_source_url = f"mosaic:{source_count_used}"
                        selected_content = content
                        selected_media_type = media_type
                    else:
                        attempted_statuses.append(f"mosaic:{status}")
                        fallback_status = status
                        fallback_content = content

                    # Fallback path: probe individual sources to avoid full-tile failures if
                    # the upstream mosaic request fails for this tile.
                    if not selected_source_url and source_count_used > 1:
                        upstream_started = time.time()
                        fallback_started = time.perf_counter()
                        successful_layers: list[tuple[str, bytes]] = []
                        composed_during_probe: bytes | None = None
                        candidate_sources = list(source_urls)
                        if source_bbox_by_url:
                            try:
                                tile_bbox = _tile_bounds_wgs84(z=z, x=x, y=y)
                                lon_span = max(0.0, float(tile_bbox[2]) - float(tile_bbox[0]))
                                lat_span = max(0.0, float(tile_bbox[3]) - float(tile_bbox[1]))
                                pad_fraction = float(max(0, int(buffer or 0))) / float(256 * max(1, int(scale or 1)))
                                if pad_fraction > 0.0:
                                    tile_bbox = _expand_bbox_wgs84(
                                        tile_bbox,
                                        lon_pad=lon_span * pad_fraction,
                                        lat_pad=lat_span * pad_fraction,
                                    )
                                prefiltered_sources = []
                                for source_url in source_urls:
                                    source_bbox = source_bbox_by_url.get(source_url)
                                    if source_bbox is None or _bbox_intersects(tile_bbox, source_bbox):
                                        prefiltered_sources.append(source_url)
                                if prefiltered_sources and len(prefiltered_sources) < len(source_urls):
                                    candidate_sources = prefiltered_sources
                                    attempted_statuses.append(
                                        f"bbox_prefilter:{len(candidate_sources)}/{len(source_urls)}"
                                    )
                            except Exception:
                                attempted_statuses.append("bbox_prefilter_err")

                        ordered_sources = proxy._prioritize_sources_for_fallback(candidate_sources)
                        if ordered_sources != candidate_sources:
                            attempted_statuses.append("reordered")
                        target_layers = max(1, int(proxy._fallback_target_success_layers or 1))
                        max_probes_allowed = max(1, int(proxy._fallback_max_probes or 1))
                        if is_l1d_sr_request:
                            max_probes_allowed = max(
                                max_probes_allowed,
                                int(proxy._fallback_max_probes_l1d_sr or max_probes_allowed),
                            )
                        for source_url in ordered_sources:
                            if probes >= max_probes_allowed:
                                attempted_statuses.append(f"probe_cap:{max_probes_allowed}")
                                break
                            probes += 1
                            if (
                                float(proxy._upstream_time_budget_seconds or 0.0) > 0.0
                                and (time.time() - upstream_started) > float(proxy._upstream_time_budget_seconds)
                            ):
                                attempted_statuses.append("budget")
                                break
                            probe_key = proxy._probe_failure_key(
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
                            cached_failure = proxy._probe_failure_get(probe_key)
                            if cached_failure is not None:
                                status, content, media_type = cached_failure
                                attempted_statuses.append(f"cached:{int(status)}")
                                proxy._record_source_probe_result(source_url, success=False)
                                if fallback_status == 404 and int(status) != 404:
                                    fallback_status = int(status)
                                    fallback_content = bytes(content or b"")
                                    fallback_source = source_url
                                elif not fallback_content:
                                    fallback_status = int(status)
                                    fallback_content = bytes(content or b"")
                                    fallback_source = source_url
                                continue
                            try:
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
                                    max_attempts=max(1, int(proxy._upstream_max_attempts or 1)),
                                    request_timeout=max(8, int(proxy._upstream_timeout_seconds or 8)),
                                )
                            except Exception as exc:
                                attempted_statuses.append(f"exc:{exc.__class__.__name__}")
                                proxy._record_source_probe_result(source_url, success=False)
                                proxy._probe_failure_put(
                                    key=probe_key,
                                    status=502,
                                    content=str(exc).encode("utf-8", errors="replace"),
                                    media_type="application/json",
                                    ttl_seconds=90,
                                )
                                if fallback_status == 404:
                                    fallback_status = 502
                                    fallback_content = str(exc).encode("utf-8", errors="replace")
                                    fallback_source = source_url
                                continue
                            status = int(status)
                            media_type = str(media_type or "image/png").split(";")[0].strip() or "image/png"
                            if status < 400 and media_type.lower() == "image/png" and not _is_valid_png(content):
                                status = 502
                                content = b'{"detail":"invalid PNG from upstream"}'
                            if status >= 400:
                                proxy._record_source_probe_result(source_url, success=False)
                                proxy._probe_failure_put(
                                    key=probe_key,
                                    status=int(status),
                                    content=bytes(content or b""),
                                    media_type=media_type,
                                )
                                attempted_statuses.append(str(status))
                                if fallback_status == 404 and status != 404:
                                    fallback_status = status
                                    fallback_content = content
                                    fallback_source = source_url
                                elif not fallback_content:
                                    fallback_status = status
                                    fallback_content = content
                                fallback_source = source_url
                                continue
                            payload = bytes(content or b"")
                            proxy._record_source_probe_result(source_url, success=True)
                            proxy._probe_failure_delete(probe_key)
                            successful_layers.append((source_url, payload))

                            if composed_during_probe is None:
                                composed_during_probe = payload
                            else:
                                step_composed = _alpha_composite_png_payloads([composed_during_probe, payload])
                                if step_composed is not None:
                                    composed_during_probe = step_composed
                                else:
                                    composed_during_probe = None

                            # If the composed fallback is already fully opaque after enough hits,
                            # stop probing additional sibling strips for this tile.
                            if (
                                composed_during_probe is not None
                                and len(successful_layers) >= target_layers
                            ):
                                alpha_extrema = _png_alpha_extrema(composed_during_probe)
                                if alpha_extrema is not None and int(alpha_extrema[0]) >= 255:
                                    attempted_statuses.append(f"opaque_stop:{len(successful_layers)}")
                                    break

                        fallback_ms = (time.perf_counter() - fallback_started) * 1000.0
                        successful_layers_count = len(successful_layers)
                        if successful_layers:
                            if len(successful_layers) == 1:
                                selected_source_url = successful_layers[0][0]
                                selected_content = successful_layers[0][1]
                                selected_media_type = "image/png"
                            else:
                                compose_started = time.perf_counter()
                                composed = composed_during_probe
                                if composed is None:
                                    composed = _alpha_composite_png_payloads(
                                        [payload for _source, payload in successful_layers]
                                    )
                                compose_ms = (time.perf_counter() - compose_started) * 1000.0
                                if composed is not None:
                                    selected_source_url = f"composite:{len(successful_layers)}"
                                    selected_content = composed
                                    selected_media_type = "image/png"
                                    attempted_statuses.append(f"composed:{len(successful_layers)}")
                                else:
                                    selected_source_url = successful_layers[0][0]
                                    selected_content = successful_layers[0][1]
                                    selected_media_type = "image/png"
                                    attempted_statuses.append("compose_unavailable")

                    if not selected_source_url:
                        status = int(fallback_status)
                        content = bytes(fallback_content or b"")
                        stale = proxy._cache_get(cache_key, allow_stale=True)
                        if stale is not None:
                            proxy._stat_inc("served_stale")
                            proxy._set_last(status=200, error=f"served_stale_from_{status}")
                            proxy._emit_event(
                                (
                                    f"served stale tile zxy={z}/{x}/{y} upstream_status={int(status)} "
                                    f"sources={source_count_label} source={_short_source_url(fallback_source)} "
                                    f"scale={scale} buffer={buffer} tms={tile_matrix_set_id} bands={bands}"
                                ),
                                level="warning",
                            )
                            headers = {"Cache-Control": "public, max-age=120", "X-Proxy-Cache": "stale"}
                            proxy._record_perf_sample(
                                z=z,
                                x=x,
                                y=y,
                                path="stale",
                                total_ms=(time.perf_counter() - tile_started) * 1000.0,
                                source_count_used=source_count_used,
                                source_count_total=source_count_total,
                                cache_lookup_ms=cache_lookup_ms,
                                mosaic_ms=mosaic_ms,
                                fallback_ms=fallback_ms,
                                compose_ms=compose_ms,
                                probes=probes,
                                successful_layers=successful_layers_count,
                                attempted_statuses=attempted_statuses,
                            )
                            self._write(200, stale["content"], stale["media_type"], headers=headers)
                            return

                        # Always serve a valid transparent tile on upstream failures so QGIS does not
                        # retry indefinitely due malformed/error payloads for XYZ image requests.
                        tile_size = 256 * max(1, int(scale or 1))
                        empty_tile = _transparent_png(tile_size)
                        fallback_ttl = 60 if int(status) == 404 else 20
                        fallback_stale_ttl = max(120, fallback_ttl)
                        proxy._cache_put(
                            cache_key,
                            empty_tile,
                            "image/png",
                            ttl_seconds=fallback_ttl,
                            stale_ttl_seconds=fallback_stale_ttl,
                        )
                        proxy._stat_inc("served_success")
                        proxy._stat_inc("served_empty")
                        if int(status) != 404:
                            proxy._stat_inc("upstream_errors")
                        proxy._set_last(status=200, error=f"upstream_status_{status}_empty")
                        detail = _payload_snippet(content)
                        attempts = ",".join(attempted_statuses[:8])
                        if len(attempted_statuses) > 8:
                            attempts = f"{attempts},+{len(attempted_statuses) - 8}"
                        proxy._emit_event(
                            (
                                f"served empty tile zxy={z}/{x}/{y} upstream_status={int(status)} "
                                f"sources={source_count_label} source={_short_source_url(fallback_source)} "
                                f"dropped={source_count_dropped} "
                                f"scale={scale} buffer={buffer} tms={tile_matrix_set_id} bands={bands} "
                                f"attempts=[{attempts}] detail={detail}"
                            ),
                            level="warning",
                        )
                        headers = {
                            "Cache-Control": f"public, max-age={fallback_ttl}",
                            "X-Proxy-Cache": "empty",
                            "X-Tile-Empty": "1",
                            "X-Tile-Size": str(tile_size),
                            "X-Upstream-Status": str(int(status)),
                            "X-Upstream-Sources": str(source_count_label),
                        }
                        proxy._record_perf_sample(
                            z=z,
                            x=x,
                            y=y,
                            path="empty",
                            total_ms=(time.perf_counter() - tile_started) * 1000.0,
                            source_count_used=source_count_used,
                            source_count_total=source_count_total,
                            cache_lookup_ms=cache_lookup_ms,
                            mosaic_ms=mosaic_ms,
                            fallback_ms=fallback_ms,
                            compose_ms=compose_ms,
                            probes=probes,
                            successful_layers=successful_layers_count,
                            attempted_statuses=attempted_statuses,
                        )
                        self._write(200, empty_tile, "image/png", headers=headers)
                        return

                    proxy._cache_put(cache_key, selected_content, selected_media_type)
                    proxy._stat_inc("served_success")
                    proxy._set_last(status=200)
                    path = "mosaic"
                    if selected_source_url.startswith("composite:"):
                        path = "composite"
                    elif selected_source_url.startswith("mosaic:"):
                        path = "mosaic"
                    elif fallback_ms > 0.0:
                        path = "fallback_single"
                    proxy._record_perf_sample(
                        z=z,
                        x=x,
                        y=y,
                        path=path,
                        total_ms=(time.perf_counter() - tile_started) * 1000.0,
                        source_count_used=source_count_used,
                        source_count_total=source_count_total,
                        cache_lookup_ms=cache_lookup_ms,
                        mosaic_ms=mosaic_ms,
                        fallback_ms=fallback_ms,
                        compose_ms=compose_ms,
                        probes=probes,
                        successful_layers=successful_layers_count,
                        attempted_statuses=attempted_statuses,
                    )
                    headers = {"Cache-Control": "public, max-age=300", "X-Proxy-Cache": "miss"}
                    self._write(200, selected_content, selected_media_type, headers=headers)
                except Exception as exc:
                    proxy._stat_inc("upstream_errors")
                    proxy._set_last(status=502, error=str(exc))
                    proxy._record_perf_sample(
                        z=z,
                        x=x,
                        y=y,
                        path="exception",
                        total_ms=(time.perf_counter() - tile_started) * 1000.0,
                        source_count_used=source_count_used,
                        source_count_total=source_count_total,
                        cache_lookup_ms=cache_lookup_ms,
                        mosaic_ms=mosaic_ms,
                        fallback_ms=fallback_ms,
                        compose_ms=compose_ms,
                        probes=probes,
                        successful_layers=successful_layers_count,
                        attempted_statuses=attempted_statuses,
                    )
                    proxy._emit_event(
                        (
                            f"tile proxy exception zxy={z}/{x}/{y} sources={source_count_label} "
                            f"source={_short_source_url(source_urls[0])} "
                            f"scale={scale} buffer={buffer} tms={tile_matrix_set_id} bands={bands} "
                            f"error={exc}"
                        ),
                        level="warning",
                    )
                    detail = {"detail": f"Tile proxy failed: {exc}"}
                    self._write(502, json.dumps(detail).encode("utf-8"), "application/json")
                finally:
                    if owns_inflight_slot and inflight_event is not None:
                        proxy._release_inflight_tile(cache_key, inflight_event)
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

            def _handle_telluric_tile_request(self, *, parsed, match):
                tile_started = time.perf_counter()
                z = int(match.group("z"))
                x = int(match.group("x"))
                y = int(match.group("y"))
                qs = parse_qs(parsed.query or "", keep_blank_values=False)
                scene_id = str((qs.get("scene_id") or [""])[0]).strip()
                raster_name = str((qs.get("raster_name") or qs.get("raster") or [""])[0]).strip()
                contract_id = str((qs.get("contract_id") or [""])[0]).strip() or None
                if not scene_id:
                    self._write(400, b'{"detail":"scene_id query param is required"}', "application/json")
                    return
                if not raster_name:
                    self._write(400, b'{"detail":"raster_name query param is required"}', "application/json")
                    return

                cache_key = proxy._cache_key(
                    z=z,
                    x=x,
                    y=y,
                    source_urls=[f"telluric://{scene_id}/{raster_name}"],
                    contract_id=contract_id,
                    scale=1,
                    buffer=0,
                    tile_matrix_set_id="Telluric",
                    image_format="png",
                    bands=[1, 2, 3],
                )

                proxy._request_started()
                owns_inflight_slot = False
                inflight_event: threading.Event | None = None
                try:
                    cached = proxy._cache_get(cache_key, allow_stale=False)
                    if cached is not None:
                        proxy._stat_inc("cache_hits")
                        proxy._stat_inc("served_success")
                        proxy._set_last(status=200)
                        proxy._record_perf_sample(
                            z=z,
                            x=x,
                            y=y,
                            path="cache_hit",
                            total_ms=(time.perf_counter() - tile_started) * 1000.0,
                            source_count_used=1,
                            source_count_total=1,
                        )
                        self._write(
                            200,
                            cached["content"],
                            cached["media_type"],
                            headers={"Cache-Control": "public, max-age=300", "X-Proxy-Cache": "hit"},
                        )
                        return
                    proxy._stat_inc("cache_misses")

                    owns_inflight_slot, inflight_event = proxy._acquire_inflight_tile(cache_key)
                    if not owns_inflight_slot:
                        wait_timeout = max(2.0, float(proxy._coalesce_wait_seconds or 2.0))
                        try:
                            inflight_event.wait(timeout=wait_timeout)
                        except Exception:
                            pass
                        cached_after_wait = proxy._cache_get(cache_key, allow_stale=False)
                        if cached_after_wait is not None:
                            proxy._stat_inc("cache_hits")
                            proxy._stat_inc("served_success")
                            proxy._set_last(status=200)
                            proxy._record_perf_sample(
                                z=z,
                                x=x,
                                y=y,
                                path="coalesced_hit",
                                total_ms=(time.perf_counter() - tile_started) * 1000.0,
                                source_count_used=1,
                                source_count_total=1,
                            )
                            self._write(
                                200,
                                cached_after_wait["content"],
                                cached_after_wait["media_type"],
                                headers={"Cache-Control": "public, max-age=300", "X-Proxy-Cache": "coalesced"},
                            )
                            return
                        owns_inflight_slot, inflight_event = proxy._acquire_inflight_tile(cache_key)

                    with proxy._source_lock:
                        service = proxy._source_service
                    status, content, media_type = service.fetch_satellogic_telluric_tile(
                        z=z,
                        x=x,
                        y=y,
                        scene_id=scene_id,
                        raster_name=raster_name,
                        contract_id=contract_id,
                        max_attempts=max(1, int(proxy._upstream_max_attempts or 1)),
                        request_timeout=max(8, int(proxy._upstream_timeout_seconds or 8)),
                    )
                    status = int(status)
                    media_type = str(media_type or "image/png").split(";")[0].strip() or "image/png"
                    if status < 400 and media_type.lower() == "image/png" and not _is_valid_png(content):
                        status = 502
                        content = b'{"detail":"invalid PNG from telluric upstream"}'

                    if status < 400:
                        proxy._cache_put(cache_key, bytes(content or b""), media_type)
                        proxy._stat_inc("served_success")
                        proxy._set_last(status=200)
                        proxy._record_perf_sample(
                            z=z,
                            x=x,
                            y=y,
                            path="mosaic",
                            total_ms=(time.perf_counter() - tile_started) * 1000.0,
                            source_count_used=1,
                            source_count_total=1,
                        )
                        self._write(
                            200,
                            bytes(content or b""),
                            media_type,
                            headers={"Cache-Control": "public, max-age=300", "X-Proxy-Cache": "miss"},
                        )
                        return

                    stale = proxy._cache_get(cache_key, allow_stale=True)
                    if stale is not None:
                        proxy._stat_inc("served_stale")
                        proxy._set_last(status=200, error=f"telluric_stale_from_{status}")
                        proxy._record_perf_sample(
                            z=z,
                            x=x,
                            y=y,
                            path="stale",
                            total_ms=(time.perf_counter() - tile_started) * 1000.0,
                            source_count_used=1,
                            source_count_total=1,
                        )
                        self._write(
                            200,
                            stale["content"],
                            stale["media_type"],
                            headers={"Cache-Control": "public, max-age=120", "X-Proxy-Cache": "stale"},
                        )
                        return

                    fallback_ttl = 60 if status == 404 else 20
                    empty_tile = _transparent_png(256)
                    proxy._cache_put(
                        cache_key,
                        empty_tile,
                        "image/png",
                        ttl_seconds=fallback_ttl,
                        stale_ttl_seconds=max(120, fallback_ttl),
                    )
                    proxy._stat_inc("served_success")
                    proxy._stat_inc("served_empty")
                    if status != 404:
                        proxy._stat_inc("upstream_errors")
                    proxy._set_last(status=200, error=f"telluric_upstream_status_{status}_empty")
                    proxy._emit_event(
                        (
                            f"served empty telluric tile zxy={z}/{x}/{y} status={status} "
                            f"scene={scene_id} raster={raster_name} detail={_payload_snippet(content)}"
                        ),
                        level="warning",
                    )
                    proxy._record_perf_sample(
                        z=z,
                        x=x,
                        y=y,
                        path="empty",
                        total_ms=(time.perf_counter() - tile_started) * 1000.0,
                        source_count_used=1,
                        source_count_total=1,
                    )
                    self._write(
                        200,
                        empty_tile,
                        "image/png",
                        headers={
                            "Cache-Control": f"public, max-age={fallback_ttl}",
                            "X-Proxy-Cache": "empty",
                            "X-Tile-Empty": "1",
                            "X-Upstream-Status": str(int(status)),
                        },
                    )
                except Exception as exc:
                    proxy._stat_inc("upstream_errors")
                    proxy._set_last(status=502, error=str(exc))
                    proxy._record_perf_sample(
                        z=z,
                        x=x,
                        y=y,
                        path="exception",
                        total_ms=(time.perf_counter() - tile_started) * 1000.0,
                        source_count_used=1,
                        source_count_total=1,
                    )
                    proxy._emit_event(
                        f"telluric tile proxy exception zxy={z}/{x}/{y} scene={scene_id} raster={raster_name} error={exc}",
                        level="warning",
                    )
                    detail = {"detail": f"Telluric tile proxy failed: {exc}"}
                    self._write(502, json.dumps(detail).encode("utf-8"), "application/json")
                finally:
                    if owns_inflight_slot and inflight_event is not None:
                        proxy._release_inflight_tile(cache_key, inflight_event)
                    proxy._request_finished()

        return Handler

    def _cache_key(
        self,
        *,
        z: int,
        x: int,
        y: int,
        source_urls: list[str],
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
                ",".join([str(value) for value in (source_urls or [])]),
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

    def _cache_put(
        self,
        key: str,
        content: bytes,
        media_type: str,
        *,
        ttl_seconds: int | None = None,
        stale_ttl_seconds: int | None = None,
    ) -> None:
        now = time.time()
        ttl = float(ttl_seconds) if ttl_seconds is not None else float(self._cache_ttl_seconds)
        stale_ttl = float(stale_ttl_seconds) if stale_ttl_seconds is not None else float(self._stale_ttl_seconds)
        ttl = max(1.0, ttl)
        stale_ttl = max(ttl, stale_ttl)
        entry = {
            "content": bytes(content or b""),
            "media_type": str(media_type or "image/png"),
            "expires_at": now + ttl,
            "stale_until": now + stale_ttl,
        }
        with self._cache_lock:
            self._cache[key] = entry
            self._cache.move_to_end(key)
            while len(self._cache) > int(self._cache_max_entries):
                self._cache.popitem(last=False)

    def _acquire_inflight_tile(self, cache_key: str) -> tuple[bool, threading.Event]:
        key = str(cache_key or "")
        with self._inflight_tile_lock:
            existing = self._inflight_tile_events.get(key)
            if existing is not None:
                return False, existing
            created = threading.Event()
            self._inflight_tile_events[key] = created
            return True, created

    def _release_inflight_tile(self, cache_key: str, event: threading.Event | None) -> None:
        key = str(cache_key or "")
        if not key:
            return
        with self._inflight_tile_lock:
            existing = self._inflight_tile_events.get(key)
            if existing is event:
                self._inflight_tile_events.pop(key, None)
        if event is not None:
            try:
                event.set()
            except Exception:
                pass

    def _probe_failure_key(
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
                str(int(z)),
                str(int(x)),
                str(int(y)),
                str(source_url or ""),
                str(contract_id or ""),
                str(int(scale)),
                str(int(buffer)),
                str(tile_matrix_set_id or ""),
                str(image_format or ""),
                ",".join([str(int(v)) for v in (bands or [])]),
            ]
        )

    def _probe_failure_get(self, key: str) -> tuple[int, bytes, str] | None:
        now = time.time()
        with self._probe_failure_lock:
            entry = self._probe_failure_cache.get(str(key or ""))
            if entry is None:
                return None
            expires_at = float(entry.get("expires_at") or 0.0)
            if expires_at <= now:
                self._probe_failure_cache.pop(str(key or ""), None)
                return None
            self._probe_failure_cache.move_to_end(str(key or ""))
            return (
                int(entry.get("status") or 0),
                bytes(entry.get("content") or b""),
                str(entry.get("media_type") or "application/json"),
            )

    def _probe_failure_put(
        self,
        *,
        key: str,
        status: int,
        content: bytes,
        media_type: str,
        ttl_seconds: int | None = None,
    ) -> None:
        cache_key = str(key or "")
        if not cache_key:
            return
        ttl = float(ttl_seconds) if ttl_seconds is not None else float(self._probe_failure_ttl_seconds)
        ttl = max(5.0, ttl)
        now = time.time()
        entry = {
            "status": int(status),
            "content": bytes(content or b""),
            "media_type": str(media_type or "application/json"),
            "expires_at": now + ttl,
        }
        with self._probe_failure_lock:
            self._probe_failure_cache[cache_key] = entry
            self._probe_failure_cache.move_to_end(cache_key)
            while len(self._probe_failure_cache) > int(self._probe_failure_cache_max_entries):
                self._probe_failure_cache.popitem(last=False)

    def _probe_failure_delete(self, key: str) -> None:
        cache_key = str(key or "")
        if not cache_key:
            return
        with self._probe_failure_lock:
            self._probe_failure_cache.pop(cache_key, None)

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

    def _prioritize_sources_for_fallback(self, source_urls: list[str]) -> list[str]:
        candidates = [str(value or "").strip() for value in (source_urls or []) if str(value or "").strip()]
        if len(candidates) <= 1:
            return candidates
        with self._source_priority_lock:
            seen_map = dict(self._source_probe_seen)
            success_map = dict(self._source_probe_success)
        scored = []
        for idx, value in enumerate(candidates):
            seen = max(1, int(seen_map.get(value) or 0))
            success = int(success_map.get(value) or 0)
            ratio = float(success) / float(seen)
            # Favor URLs that recently/consistently returned successful tiles.
            score = ratio * 1000.0 + float(success)
            scored.append((-score, idx, value))
        scored.sort()
        return [value for _score, _idx, value in scored]

    def _record_source_probe_result(self, source_url: str, *, success: bool) -> None:
        key = str(source_url or "").strip()
        if not key:
            return
        with self._source_priority_lock:
            self._source_probe_seen[key] = int(self._source_probe_seen.get(key) or 0) + 1
            if success:
                self._source_probe_success[key] = int(self._source_probe_success.get(key) or 0) + 1
            # Keep maps bounded so long sessions do not grow unbounded.
            if len(self._source_probe_seen) > int(self._source_probe_cap or 2048):
                stale_by_seen = sorted(self._source_probe_seen.items(), key=lambda item: int(item[1] or 0))
                drop_count = max(1, len(self._source_probe_seen) - int(self._source_probe_cap or 2048))
                for stale_key, _count in stale_by_seen[:drop_count]:
                    self._source_probe_seen.pop(stale_key, None)
                    self._source_probe_success.pop(stale_key, None)

    def _record_perf_sample(
        self,
        *,
        z: int,
        x: int,
        y: int,
        path: str,
        total_ms: float,
        source_count_used: int,
        source_count_total: int,
        cache_lookup_ms: float = 0.0,
        mosaic_ms: float = 0.0,
        fallback_ms: float = 0.0,
        compose_ms: float = 0.0,
        probes: int = 0,
        successful_layers: int = 0,
        attempted_statuses: list[str] | None = None,
    ) -> None:
        path_value = str(path or "unknown").strip() or "unknown"
        sample_idx = 0
        avg_ms = 0.0
        max_ms = 0.0
        perf_cache_hits = 0
        perf_mosaic = 0
        perf_fallback = 0
        perf_composite = 0
        perf_empty = 0
        perf_stale = 0
        perf_exception = 0
        with self._stats_lock:
            self._stats["perf_samples"] = int(self._stats.get("perf_samples") or 0) + 1
            self._stats["perf_total_ms"] = float(self._stats.get("perf_total_ms") or 0.0) + float(total_ms or 0.0)
            self._stats["perf_max_ms"] = max(
                float(self._stats.get("perf_max_ms") or 0.0),
                float(total_ms or 0.0),
            )
            if path_value == "cache_hit":
                self._stats["perf_cache_hit_tiles"] = int(self._stats.get("perf_cache_hit_tiles") or 0) + 1
            elif path_value == "mosaic":
                self._stats["perf_mosaic_tiles"] = int(self._stats.get("perf_mosaic_tiles") or 0) + 1
            elif path_value in {"fallback_single", "composite"}:
                self._stats["perf_fallback_tiles"] = int(self._stats.get("perf_fallback_tiles") or 0) + 1
            if path_value == "composite":
                self._stats["perf_composite_tiles"] = int(self._stats.get("perf_composite_tiles") or 0) + 1
            if path_value == "empty":
                self._stats["perf_empty_tiles"] = int(self._stats.get("perf_empty_tiles") or 0) + 1
            if path_value == "stale":
                self._stats["perf_stale_tiles"] = int(self._stats.get("perf_stale_tiles") or 0) + 1
            if path_value == "exception":
                self._stats["perf_exception_tiles"] = int(self._stats.get("perf_exception_tiles") or 0) + 1
            sample_idx = int(self._stats.get("perf_samples") or 0)
            total_seen = float(self._stats.get("perf_total_ms") or 0.0)
            avg_ms = total_seen / float(sample_idx or 1)
            max_ms = float(self._stats.get("perf_max_ms") or 0.0)
            perf_cache_hits = int(self._stats.get("perf_cache_hit_tiles") or 0)
            perf_mosaic = int(self._stats.get("perf_mosaic_tiles") or 0)
            perf_fallback = int(self._stats.get("perf_fallback_tiles") or 0)
            perf_composite = int(self._stats.get("perf_composite_tiles") or 0)
            perf_empty = int(self._stats.get("perf_empty_tiles") or 0)
            perf_stale = int(self._stats.get("perf_stale_tiles") or 0)
            perf_exception = int(self._stats.get("perf_exception_tiles") or 0)

        statuses = [str(value).strip() for value in (attempted_statuses or []) if str(value).strip()]
        attempts = ",".join(statuses[:6])
        if len(statuses) > 6:
            attempts = f"{attempts},+{len(statuses) - 6}"

        should_log = bool(self._perf_log_every_tile)
        if not should_log:
            should_log = (
                float(total_ms or 0.0) >= float(self._perf_log_slow_tile_ms or 0.0)
                or float(fallback_ms or 0.0) > 0.0
                or path_value in {"empty", "stale", "exception"}
            )
        if should_log:
            level = "info"
            if path_value in {"empty", "exception"}:
                level = "warning"
            elif float(total_ms or 0.0) >= float(self._perf_log_slow_tile_ms or 0.0) * 2.0:
                level = "warning"
            self._emit_event(
                (
                    f"tile perf zxy={z}/{x}/{y} path={path_value} "
                    f"ms(total={float(total_ms):.1f},cache={float(cache_lookup_ms):.1f},"
                    f"mosaic={float(mosaic_ms):.1f},fallback={float(fallback_ms):.1f},compose={float(compose_ms):.1f}) "
                    f"sources={int(source_count_used)}/{int(source_count_total)} "
                    f"probes={int(probes)} layers={int(successful_layers)} "
                    f"attempts=[{attempts}]"
                ),
                level=level,
            )

        summary_every = max(0, int(self._perf_log_summary_every or 0))
        if summary_every > 0 and sample_idx > 0 and sample_idx % summary_every == 0:
            self._emit_event(
                (
                    f"tile perf summary samples={sample_idx} avg_ms={avg_ms:.1f} max_ms={max_ms:.1f} "
                    f"paths(cache_hit={perf_cache_hits},mosaic={perf_mosaic},fallback={perf_fallback},"
                    f"composite={perf_composite},stale={perf_stale},empty={perf_empty},exception={perf_exception})"
                ),
                level="info",
            )


def _to_int(value, fallback: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(fallback)


def _short_source_url(url: str) -> str:
    value = str(url or "").strip()
    if len(value) <= 180:
        return value
    return f"{value[:180]}..."


def _payload_snippet(payload: bytes) -> str:
    raw = bytes(payload or b"")
    if not raw:
        return ""
    try:
        text = raw.decode("utf-8", errors="replace").strip().replace("\n", " ")
    except Exception:
        text = ""
    if not text:
        return f"{len(raw)} bytes"
    if len(text) > 220:
        return f"{text[:220]}..."
    return text
