from __future__ import annotations

from datetime import datetime, timedelta, timezone
import ipaddress
from typing import Any
import logging
import re
from urllib.parse import urlparse, urlunparse

import requests

from .config import settings

logger = logging.getLogger(__name__)


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_cloud_cover(props: dict[str, Any]) -> float | None:
    for key in ("eo:cloud_cover", "cloudCover", "s2:cloud_cover"):
        value = _to_float(props.get(key))
        if value is not None:
            return value
    return None


def _extract_gsd(props: dict[str, Any]) -> float | None:
    for key in ("eo:gsd", "gsd"):
        value = _to_float(props.get(key))
        if value is not None:
            return value
    return None


def _extract_satellite_name(props: dict[str, Any], item_id: str) -> str | None:
    for key in ("platform", "constellation", "sat:platform_international_designator"):
        value = props.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    match = re.search(r"S2[AB]", item_id or "", flags=re.IGNORECASE)
    if match:
        return match.group(0).upper()
    return None


def _http_origin(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return ""


def _normalize_asset_href(raw_href: Any) -> str:
    href = str(raw_href or "").strip()
    if not href:
        return ""
    if href.startswith("//"):
        return f"https:{href}"
    if href.startswith("/"):
        base = _http_origin(settings.cdse_stac_url)
        return f"{base}{href}" if base else href
    if href.startswith("s3://"):
        # Common CDSE pattern: s3://eodata/<path> -> https://eodata.dataspace.copernicus.eu/<path>
        rest = href[len("s3://") :]
        if "/" in rest:
            bucket, path = rest.split("/", 1)
            if bucket.strip().lower() == "eodata":
                return f"https://eodata.dataspace.copernicus.eu/{path}"
    parsed = urlparse(href)
    host = (parsed.hostname or "").strip().lower()
    if host.endswith(".svc.cluster.local"):
        # CDSE occasionally emits internal catalogue hostnames that are not reachable externally.
        return urlunparse((
            parsed.scheme or "https",
            "catalogue.dataspace.copernicus.eu",
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        ))
    return href


def _is_private_or_internal_http_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return True
    if host in {"localhost"} or host.endswith(".local") or host.endswith(".cluster.local"):
        return True
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


def _looks_like_image_asset(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    path = (parsed.path or "").lower()
    if not path:
        return False
    if ".xml" in path:
        return False
    if any(path.endswith(ext) for ext in (".tif", ".tiff", ".jp2", ".jpg", ".jpeg", ".png", ".webp")):
        return True
    if "/assets(" in path and path.endswith("/$value"):
        return True
    if "quicklook" in path or "preview" in path or "thumbnail" in path:
        return True
    return False


def _looks_like_previewish_url(url: str) -> bool:
    lower = str(url or "").lower()
    return any(token in lower for token in ("preview", "thumbnail", "quicklook", "rendered_preview", "rendered-preview"))


def _best_asset_candidate(candidates: list[str], *, require_image: bool = False) -> str:
    cleaned: list[str] = []
    seen: set[str] = set()
    for href in candidates:
        value = str(href or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    if not cleaned:
        return ""

    def score(url: str) -> tuple[int, int, int]:
        parsed = urlparse(url)
        is_http = int(parsed.scheme in {"http", "https"} and bool(parsed.netloc))
        not_private = int(not _is_private_or_internal_http_url(url))
        image_like = int(_looks_like_image_asset(url))
        return (is_http, not_private, image_like)

    if require_image:
        filtered = [href for href in cleaned if _looks_like_image_asset(href)]
        if not filtered:
            return ""
        cleaned = filtered
    return max(cleaned, key=score)


def normalize_merlin_item(feature: dict[str, Any], source_id: str = "merlin-s2") -> dict[str, Any]:
    props = feature.get("properties") or {}
    assets = feature.get("assets") or {}
    native_id = str(feature.get("id") or "")
    canonical_id = f"{source_id}:{native_id}" if native_id else native_id

    def _is_http_url(value: str | None) -> bool:
        if not value:
            return False
        parsed = urlparse(str(value))
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def _asset_href_candidates(asset: dict[str, Any]) -> list[str]:
        candidates: list[str] = []
        raw_primary = asset.get("href") if isinstance(asset, dict) else None
        primary_href = str(raw_primary or "").strip() if isinstance(raw_primary, str) else ""
        primary_is_http = _is_http_url(primary_href)
        alternate = asset.get("alternate") if isinstance(asset, dict) else None
        if isinstance(alternate, dict):
            for alt in alternate.values():
                if isinstance(alt, dict):
                    alt_href = alt.get("href")
                    if isinstance(alt_href, str) and alt_href.strip():
                        candidates.append(_normalize_asset_href(alt_href.strip()))
        if primary_href:
            normalized_primary = _normalize_asset_href(primary_href)
            if primary_is_http:
                candidates.insert(0, normalized_primary)
            else:
                candidates.append(normalized_primary)
        return candidates

    def asset_url(*names: str, require_image: bool = False) -> str | None:
        candidates: list[str] = []
        for name in names:
            asset = assets.get(name)
            if not isinstance(asset, dict):
                continue
            for href in _asset_href_candidates(asset):
                candidates.append(href)
        return _best_asset_candidate(candidates, require_image=require_image)

    def asset_url_by_key_regex(pattern: str, *, require_image: bool = False) -> str | None:
        rx = re.compile(pattern, flags=re.IGNORECASE)
        candidates: list[str] = []
        for key, asset in assets.items():
            if not isinstance(asset, dict):
                continue
            key_s = str(key or "").strip()
            title_s = str((asset or {}).get("title") or "").strip() if isinstance(asset, dict) else ""
            if rx.search(key_s) or (title_s and rx.search(title_s)):
                for href in _asset_href_candidates(asset):
                    candidates.append(href)
        return _best_asset_candidate(candidates, require_image=require_image)

    def link_url_by_rel_regex(pattern: str, *, require_image: bool = False) -> str | None:
        links = feature.get("links")
        if not isinstance(links, list):
            return ""
        rx = re.compile(pattern, flags=re.IGNORECASE)
        candidates: list[str] = []
        for row in links:
            if not isinstance(row, dict):
                continue
            href = _normalize_asset_href(row.get("href"))
            if not href:
                continue
            rel = str(row.get("rel") or "")
            title = str(row.get("title") or "")
            typ = str(row.get("type") or "")
            if rx.search(rel) or rx.search(title) or rx.search(typ):
                candidates.append(href)
        return _best_asset_candidate(candidates, require_image=require_image)

    def _asset_roles(asset: dict[str, Any]) -> list[str]:
        raw_roles = asset.get("roles")
        if not isinstance(raw_roles, list):
            return []
        return [str(row or "").strip().lower() for row in raw_roles if str(row or "").strip()]

    def _asset_text_blob(key: str, asset: dict[str, Any]) -> str:
        title = str(asset.get("title") or "")
        typ = str(asset.get("type") or "")
        roles = " ".join(_asset_roles(asset))
        return f"{key} {title} {typ} {roles}".strip().lower()

    def _fullres_visual_candidates() -> list[str]:
        # Prefer non-preview visual/data assets (e.g., TCI true color), avoid auxiliary AOT/WVP/SCL-like layers.
        scored: list[tuple[int, str]] = []
        for key, asset in assets.items():
            if not isinstance(asset, dict):
                continue
            blob = _asset_text_blob(str(key or ""), asset)
            roles = _asset_roles(asset)
            is_previewish_meta = bool(re.search(r"(preview|thumbnail|quicklook|rendered)", blob))
            is_visualish_meta = bool(re.search(r"(tci|true[_ -]?colou?r|visual)", blob))
            is_data_role = "data" in roles
            if not (is_visualish_meta or is_data_role):
                continue
            for href in _asset_href_candidates(asset):
                lower_href = href.lower()
                if ".xml" in lower_href:
                    continue
                if is_previewish_meta or _looks_like_previewish_url(href):
                    continue
                rank = 0
                if re.search(r"(tci|true[_ -]?colou?r)", blob) or re.search(r"(tci|true[_ -]?colou?r)", lower_href):
                    rank += 120
                if "visual" in roles:
                    rank += 35
                if "data" in roles:
                    rank += 15
                if re.search(r"(10m)", blob) or re.search(r"(10m)", lower_href):
                    rank += 12
                if re.search(r"(aot|wvp|scl|cld|snw|mask|cloud)", blob) or re.search(r"(aot|wvp|scl|cld|snw|mask|cloud)", lower_href):
                    rank -= 180
                if re.search(r"(metadata|manifest|inspire)", blob):
                    rank -= 220
                scored.append((rank, href))
        scored.sort(key=lambda row: row[0], reverse=True)
        return [href for _, href in scored]

    cloud_cover = _extract_cloud_cover(props)
    preview_href = (
        asset_url("preview", "thumbnail", "rendered_preview", require_image=True)
        or asset_url_by_key_regex(r"(preview|thumbnail|quicklook|rendered)", require_image=True)
        or link_url_by_rel_regex(r"(preview|thumbnail|quicklook)", require_image=True)
        or ""
    )
    fullres_visual_href = _best_asset_candidate(_fullres_visual_candidates(), require_image=True) or ""
    visual_href = (
        fullres_visual_href
        or asset_url("visual", "analytic", "data", require_image=True)
        or asset_url_by_key_regex(r"(visual|true[_-]?color|analytic|data)", require_image=True)
        or link_url_by_rel_regex(r"(enclosure|item|data|download)", require_image=True)
        or preview_href
        or ""
    )
    analytic_href = (
        asset_url("analytic", "data", "visual", require_image=True)
        or asset_url_by_key_regex(r"(analytic|data|visual)", require_image=True)
        or visual_href
        or ""
    )
    thumbnail_href = (
        asset_url("thumbnail", "preview", "rendered_preview", require_image=True)
        or asset_url_by_key_regex(r"(thumbnail|preview|quicklook|rendered)", require_image=True)
        or link_url_by_rel_regex(r"(thumbnail|preview|quicklook)", require_image=True)
        or preview_href
        or ""
    )
    return {
        "id": canonical_id,
        "source_id": source_id,
        "native_item_id": native_id,
        "collection": feature.get("collection"),
        "datetime": props.get("datetime"),
        "outcome_id": native_id,
        "satellite_name": _extract_satellite_name(props, native_id),
        "gsd": _extract_gsd(props),
        "cloud_cover": cloud_cover,
        "valid_pixel_percent": props.get("s2:nodata_pixel_percentage"),
        "geometry": feature.get("geometry"),
        "assets": {
            "visual": visual_href,
            "visual_fullres": fullres_visual_href or visual_href,
            "analytic": analytic_href,
            "preview": preview_href or visual_href,
            "thumbnail": thumbnail_href or preview_href or visual_href,
            "cloud_mask": (
                asset_url("cloud_mask", "scl", "SCL", "mask")
                or asset_url_by_key_regex(r"(cloud.*mask|mask.*cloud|scl)")
                or ""
            ),
        },
        "raw": feature,
    }


class MerlinSentinel2Client:
    def __init__(self):
        self.enabled = bool(settings.merlin_s2_enabled)
        self.client_id = settings.cdse_client_id
        self.client_secret = settings.cdse_client_secret
        self.download_client_id = settings.cdse_download_client_id or "cdse-public"
        self.download_username = settings.cdse_download_username
        self.download_password = settings.cdse_download_password
        self.download_totp = settings.cdse_download_totp
        self.token_url = settings.cdse_token_url
        self.stac_url = settings.cdse_stac_url.rstrip("/")
        self.legacy_stac_urls = [
            "https://stac.dataspace.copernicus.eu/v1",
            "https://catalogue.dataspace.copernicus.eu/stac",
        ]
        self.default_collections = settings.cdse_sentinel2_collections or ["sentinel-2-l2a"]
        self.timeout_seconds = max(5, int(settings.cdse_request_timeout_seconds))

        self._access_token: str | None = None
        self._access_token_expiry: datetime | None = None
        self._download_access_token: str | None = None
        self._download_access_token_expiry: datetime | None = None
        self._warned_download_fallback = False

    def _get_access_token(self) -> str:
        now = datetime.now(timezone.utc)
        if self._access_token and self._access_token_expiry and now < self._access_token_expiry:
            return self._access_token

        if not self.client_id or not self.client_secret:
            raise RuntimeError("CDSE credentials are missing (CDSE_CLIENT_ID/CDSE_CLIENT_SECRET)")

        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        response = requests.post(self.token_url, data=payload, timeout=self.timeout_seconds)
        response.raise_for_status()
        data = response.json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError("CDSE token response missing access_token")
        expires_in = int(data.get("expires_in", 3600))
        self._access_token = str(token)
        self._access_token_expiry = now + timedelta(seconds=max(60, expires_in - 60))
        return self._access_token

    def _has_download_credentials(self) -> bool:
        return bool((self.download_username or "").strip() and (self.download_password or "").strip())

    def _get_download_access_token(self) -> str:
        now = datetime.now(timezone.utc)
        if self._download_access_token and self._download_access_token_expiry and now < self._download_access_token_expiry:
            return self._download_access_token

        if not self._has_download_credentials():
            if not self._warned_download_fallback:
                logger.warning(
                    "CDSE download credentials missing (CDSE_DOWNLOAD_USERNAME/CDSE_DOWNLOAD_PASSWORD); "
                    "falling back to client-credentials token for download URLs",
                )
                self._warned_download_fallback = True
            return self._get_access_token()

        payload: dict[str, str] = {
            "grant_type": "password",
            "client_id": (self.download_client_id or "cdse-public").strip() or "cdse-public",
            "username": (self.download_username or "").strip(),
            "password": (self.download_password or "").strip(),
        }
        if (self.download_totp or "").strip():
            payload["totp"] = self.download_totp.strip()

        response = requests.post(self.token_url, data=payload, timeout=self.timeout_seconds)
        response.raise_for_status()
        data = response.json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError("CDSE download token response missing access_token")
        expires_in = int(data.get("expires_in", 3600))
        self._download_access_token = str(token)
        self._download_access_token_expiry = now + timedelta(seconds=max(60, expires_in - 60))
        return self._download_access_token

    def _requires_download_token_for_url(self, url: str) -> bool:
        parsed = urlparse(str(url or ""))
        host = (parsed.hostname or "").strip().lower()
        path = (parsed.path or "").strip().lower()
        if not host:
            return False
        if host == "zipper.dataspace.copernicus.eu":
            return True
        if host in {"catalogue.dataspace.copernicus.eu", "download.dataspace.copernicus.eu", "eodata.dataspace.copernicus.eu"}:
            if "/odata/" in path or "/download/" in path:
                return True
        return False

    def auth_headers(self, *, download: bool = False) -> dict[str, str]:
        if not self.enabled:
            return {}
        token = self._get_download_access_token() if download else self._get_access_token()
        return {"Authorization": f"Bearer {token}"}

    def auth_headers_for_url(self, url: str) -> dict[str, str]:
        use_download = self._requires_download_token_for_url(url)
        return self.auth_headers(download=use_download)

    def refresh_access_token(self) -> tuple[bool, datetime | None]:
        if not self.enabled:
            return False, None
        self._access_token = None
        self._access_token_expiry = None
        token = self._get_access_token()
        return bool(token), self._access_token_expiry

    def list_contracts(self) -> list[dict[str, Any]]:
        # CDSE integration does not use the Satellogic contract model.
        return []

    def list_collections(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        payload = self._request_stac_json("GET", "/collections")
        if isinstance(payload, dict):
            rows = payload.get("collections")
            if isinstance(rows, list):
                return rows
        if isinstance(payload, list):
            return payload
        return []

    def _collection_candidates(self, collection_id: str | None) -> list[str]:
        requested = (collection_id or "").strip()
        if requested and requested not in {"*", "all", "auto"}:
            return [requested]
        return [value for value in self.default_collections if value]

    def search(
        self,
        geometry: dict[str, Any],
        start_date: str,
        end_date: str,
        collection_id: str | None,
        limit: int,
        max_cloud_cover: float | None,
        satellite_name: str | None = None,
        min_gsd: float | None = None,
        max_gsd: float | None = None,
    ) -> list[dict[str, Any]]:
        if not self.enabled:
            raise RuntimeError("Merlin Sentinel-2 source is disabled")
        collections = self._collection_candidates(collection_id)
        body: dict[str, Any] = {
            "collections": collections,
            "intersects": geometry,
            "datetime": f"{start_date}/{end_date}",
            "limit": int(max(1, min(limit, 2000))),
            "sortby": [{"field": "datetime", "direction": "desc"}],
        }
        payload = self._request_stac_json("POST", "/search", json=body)
        features = payload.get("features") if isinstance(payload, dict) else []
        if not isinstance(features, list):
            return []
        return self._filter_features(
            features,
            max_cloud_cover=max_cloud_cover,
            satellite_name=satellite_name,
            min_gsd=min_gsd,
            max_gsd=max_gsd,
        )

    def item_by_id(self, item_id: str, collection_id: str | None = None) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        body: dict[str, Any] = {
            "ids": [item_id],
            "limit": 1,
        }
        collections = self._collection_candidates(collection_id)
        if collections:
            body["collections"] = collections
        payload = self._request_stac_json("POST", "/search", json=body)
        features = payload.get("features", []) if isinstance(payload, dict) else []
        return features[0] if isinstance(features, list) and features else None

    def download_bytes(self, url: str) -> bytes:
        if not self.enabled:
            raise RuntimeError("Merlin Sentinel-2 source is disabled")
        response = requests.get(url, headers=self.auth_headers_for_url(url), timeout=self.timeout_seconds)
        response.raise_for_status()
        return response.content

    def _filter_features(
        self,
        features: list[dict[str, Any]],
        max_cloud_cover: float | None,
        satellite_name: str | None,
        min_gsd: float | None,
        max_gsd: float | None,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        sat_filter = (satellite_name or "").strip().lower()

        for feature in features:
            props = feature.get("properties") or {}
            item_id = str(feature.get("id") or "")
            sat_name = _extract_satellite_name(props, item_id) or ""
            if sat_filter and sat_filter not in sat_name.lower() and sat_filter not in item_id.lower():
                continue
            gsd = _extract_gsd(props)
            if min_gsd is not None and (gsd is None or gsd < min_gsd):
                continue
            if max_gsd is not None and (gsd is None or gsd > max_gsd):
                continue
            cloud = _extract_cloud_cover(props)
            if max_cloud_cover is not None and cloud is not None and cloud > max_cloud_cover:
                continue
            out.append(feature)
        return out

    def _stac_base_candidates(self) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for base in [self.stac_url, *self.legacy_stac_urls]:
            value = str(base or "").strip().rstrip("/")
            if not value:
                continue
            if value in seen:
                continue
            seen.add(value)
            out.append(value)
        return out

    def _request_stac_json(self, method: str, path: str, json: dict[str, Any] | None = None) -> Any:
        last_exc: Exception | None = None
        method_upper = method.upper().strip()
        normalized_path = path if path.startswith("/") else f"/{path}"
        bases = self._stac_base_candidates()
        headers = self.auth_headers()

        for idx, base in enumerate(bases):
            url = f"{base}{normalized_path}"
            try:
                response = requests.request(
                    method_upper,
                    url,
                    headers=headers,
                    json=json,
                    timeout=self.timeout_seconds,
                )
                if response.status_code >= 400:
                    if idx < len(bases) - 1 and response.status_code in {400, 404, 405, 410, 422}:
                        logger.warning(
                            "CDSE STAC fallback: method=%s url=%s status=%s -> trying next base",
                            method_upper,
                            url,
                            response.status_code,
                        )
                        continue
                    response.raise_for_status()
                return response.json()
            except Exception as exc:
                last_exc = exc
                if idx < len(bases) - 1:
                    logger.warning(
                        "CDSE STAC request failed: method=%s url=%s error=%s -> trying next base",
                        method_upper,
                        url,
                        exc,
                    )
                    continue
                break
        if last_exc:
            raise last_exc
        raise RuntimeError(f"CDSE STAC request failed for path={normalized_path}")
