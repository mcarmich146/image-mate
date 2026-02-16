from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import logging
import re

import requests

from .config import settings

logger = logging.getLogger(__name__)


def _normalize_longitude(value: Any) -> Any:
    try:
        lon = float(value)
    except (TypeError, ValueError):
        return value
    return ((lon + 180.0) % 360.0) - 180.0


def _normalize_geometry_longitudes(geometry: Any) -> Any:
    if not isinstance(geometry, dict):
        return geometry

    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")

    def normalize_pair(pair: Any) -> Any:
        if not isinstance(pair, list) or len(pair) < 2:
            return pair
        out = list(pair)
        out[0] = _normalize_longitude(out[0])
        return out

    if geometry_type == "Point" and isinstance(coordinates, list):
        return {**geometry, "coordinates": normalize_pair(coordinates)}

    if geometry_type in {"MultiPoint", "LineString"} and isinstance(coordinates, list):
        return {**geometry, "coordinates": [normalize_pair(pair) for pair in coordinates]}

    if geometry_type in {"MultiLineString", "Polygon"} and isinstance(coordinates, list):
        return {
            **geometry,
            "coordinates": [
                [normalize_pair(pair) for pair in line] if isinstance(line, list) else line
                for line in coordinates
            ],
        }

    if geometry_type == "MultiPolygon" and isinstance(coordinates, list):
        return {
            **geometry,
            "coordinates": [
                [
                    [normalize_pair(pair) for pair in line] if isinstance(line, list) else line
                    for line in poly
                ] if isinstance(poly, list) else poly
                for poly in coordinates
            ],
        }

    if geometry_type == "GeometryCollection" and isinstance(geometry.get("geometries"), list):
        return {
            **geometry,
            "geometries": [_normalize_geometry_longitudes(g) for g in geometry["geometries"]],
        }

    return geometry


class SatellogicClient:
    def __init__(self):
        self.api_base_url = settings.satellogic_api_base_url.rstrip("/")
        self.stac_url = settings.satellogic_stac_url.rstrip("/")
        self.token_url = settings.satellogic_token_url
        self.bearer_token = settings.satellogic_bearer_token
        self.key_id = settings.satellogic_key_id
        self.key_secret = settings.satellogic_key_secret
        self.auth_mode = (settings.satellogic_auth_mode or "oauth_client_credentials").strip().lower()
        self.contract_id = settings.satellogic_contract_id

        self._access_token: str | None = None
        self._access_token_expiry: datetime | None = None

    def _get_access_token(self) -> str | None:
        if self._access_token and self._access_token_expiry and datetime.now(timezone.utc) < self._access_token_expiry:
            return self._access_token

        if not self.key_id or not self.key_secret:
            return None

        payload = {
            "client_id": self.key_id,
            "client_secret": self.key_secret,
            "audience": "https://api.satellogic.com/",
            "grant_type": "client_credentials",
        }

        response = requests.post(self.token_url, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError("OAuth token response missing access_token")

        expires_in = int(data.get("expires_in", 3600))
        self._access_token = token
        self._access_token_expiry = datetime.now(timezone.utc) + timedelta(seconds=max(60, expires_in - 60))
        return token

    def auth_headers(
        self,
        contract_id: str | None = None,
        include_contract: bool = True,
        prefer_key_secret: bool = False,
        prefer_oauth: bool = False,
        ignore_static_bearer: bool = False,
    ) -> dict[str, str]:
        headers: dict[str, str] = {}
        mode = self.auth_mode
        if prefer_key_secret:
            mode = "key_secret"
        elif prefer_oauth:
            mode = "oauth_client_credentials"

        if mode in {"key_secret", "client_credentials_plain"}:
            if self.key_id and self.key_secret:
                headers["authorizationToken"] = f"Key,Secret {self.key_id},{self.key_secret}"
        elif mode in {"bearer", "static_bearer"} and self.bearer_token and not ignore_static_bearer:
            headers["authorizationToken"] = f"Bearer {self.bearer_token}"
        elif mode in {"oauth", "oauth_client_credentials"}:
            token = None
            try:
                token = self._get_access_token()
            except Exception as exc:
                logger.warning("OAuth token fetch failed; trying key/secret auth fallback: %s", exc)

            if token:
                headers["authorizationToken"] = f"Bearer {token}"
            elif self.key_id and self.key_secret:
                headers["authorizationToken"] = f"Key,Secret {self.key_id},{self.key_secret}"
        elif mode == "auto":
            if self.bearer_token and not ignore_static_bearer:
                headers["authorizationToken"] = f"Bearer {self.bearer_token}"
            else:
                token = None
                try:
                    token = self._get_access_token()
                except Exception as exc:
                    logger.warning("OAuth token fetch failed; trying key/secret auth fallback: %s", exc)
                if token:
                    headers["authorizationToken"] = f"Bearer {token}"
                elif self.key_id and self.key_secret:
                    headers["authorizationToken"] = f"Key,Secret {self.key_id},{self.key_secret}"
        else:
            logger.warning("Unknown SATELLOGIC_AUTH_MODE '%s'; defaulting to oauth_client_credentials", mode)
            token = None
            try:
                token = self._get_access_token()
            except Exception as exc:
                logger.warning("OAuth token fetch failed; trying key/secret auth fallback: %s", exc)
            if token:
                headers["authorizationToken"] = f"Bearer {token}"
            elif self.key_id and self.key_secret:
                headers["authorizationToken"] = f"Key,Secret {self.key_id},{self.key_secret}"

        effective_contract_id = contract_id if contract_id is not None else self.contract_id
        if include_contract and effective_contract_id:
            headers["X-Satellogic-Contract-Id"] = effective_contract_id

        return headers

    def refresh_access_token(self) -> tuple[bool, datetime | None]:
        self._access_token = None
        self._access_token_expiry = None
        token = self._get_access_token()
        return bool(token), self._access_token_expiry

    def list_contracts(self) -> list[dict[str, Any]]:
        """
        Return contracts available to the authenticated account.
        This endpoint must be called without `X-Satellogic-Contract-Id`.
        """
        url = "https://api.satellogic.com/contracts"
        response = requests.get(url, headers=self.auth_headers(include_contract=False), timeout=60)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and "results" in payload and isinstance(payload["results"], list):
            return payload["results"]
        return []

    def list_collections(self, contract_id: str | None = None) -> list[dict[str, Any]]:
        """
        Return STAC collections available to the authenticated account.
        """
        url = f"{self.stac_url}/collections"
        response = requests.get(url, headers=self.auth_headers(contract_id=contract_id), timeout=60)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            collections = payload.get("collections")
            if isinstance(collections, list):
                return collections
            results = payload.get("results")
            if isinstance(results, list):
                return results
        if isinstance(payload, list):
            return payload
        return []

    def list_orders(
        self,
        contract_id: str | None = None,
        *,
        limit: int = 100,
        query: str | None = None,
        next_url: str | None = None,
    ) -> dict[str, Any]:
        """
        Return v2 orders from Satellogic Order Management API.
        """
        if next_url:
            url = next_url if next_url.startswith("http") else f"{self.api_base_url}{next_url}"
            response = requests.get(url, headers=self.auth_headers(contract_id=contract_id), timeout=60)
        else:
            url = f"{self.api_base_url}/v2/orders/"
            params: dict[str, Any] = {"limit": int(max(1, min(limit, 500)))}
            if query:
                params["query"] = query
            response = requests.get(
                url,
                headers=self.auth_headers(contract_id=contract_id),
                params=params,
                timeout=60,
            )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            return payload
        return {"results": []}

    def create_order(self, feature: dict[str, Any], contract_id: str | None = None) -> dict[str, Any]:
        """
        Create a new v2 tasking order.
        """
        url = f"{self.api_base_url}/v2/orders/"
        response = requests.post(
            url,
            headers=self.auth_headers(contract_id=contract_id),
            json=feature,
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            return payload
        return {"result": payload}

    def search(
        self,
        geometry: dict[str, Any],
        start_date: str,
        end_date: str,
        collection_id: str,
        contract_id: str | None,
        limit: int,
        max_cloud_cover: float | None,
        satellite_name: str | None = None,
        min_gsd: float | None = None,
        max_gsd: float | None = None,
    ) -> list[dict[str, Any]]:
        url = f"{self.stac_url}/search"
        normalized_geometry = _normalize_geometry_longitudes(geometry)
        body: dict[str, Any] = {
            "collections": [collection_id],
            "intersects": normalized_geometry,
            "datetime": f"{start_date}/{end_date}",
            "limit": limit,
            "sortby": [{"field": "datetime", "direction": "desc"}],
        }
        # NOTE:
        # This STAC endpoint does not support the Query extension and returns 403
        # when `query` is provided. We apply cloud/satellite/gsd filters client-side.

        response = requests.post(url, headers=self.auth_headers(contract_id=contract_id), json=body, timeout=60)
        response.raise_for_status()
        payload = response.json()
        features = payload.get("features", [])
        return self._filter_features(
            features,
            collection_id=collection_id,
            max_cloud_cover=max_cloud_cover,
            satellite_name=satellite_name,
            min_gsd=min_gsd,
            max_gsd=max_gsd,
        )

    def item_by_id(self, item_id: str, contract_id: str | None = None) -> dict[str, Any] | None:
        # STAC core supports searching by explicit IDs.
        url = f"{self.stac_url}/search"
        body = {
            "collections": [settings.satellogic_collection_id],
            "ids": [item_id],
            "limit": 1,
        }
        response = requests.post(url, headers=self.auth_headers(contract_id=contract_id), json=body, timeout=60)
        response.raise_for_status()
        features = response.json().get("features", [])
        return features[0] if features else None

    def download_bytes(self, url: str, contract_id: str | None = None) -> bytes:
        response = requests.get(url, headers=self.auth_headers(contract_id=contract_id), timeout=45)
        response.raise_for_status()
        return response.content

    def _filter_features(
        self,
        features: list[dict[str, Any]],
        collection_id: str | None = None,
        max_cloud_cover: float | None = None,
        satellite_name: str | None = None,
        min_gsd: float | None = None,
        max_gsd: float | None = None,
    ) -> list[dict[str, Any]]:
        if not features:
            return []

        sat_filter = (satellite_name or "").strip().lower()
        out = []
        for feature in features:
            props = feature.get("properties", {})
            item_id = feature.get("id", "")
            sat_name = _extract_satellite_name(props, item_id) or ""
            gsd = _extract_gsd(props)
            if sat_filter and sat_filter not in sat_name.lower() and sat_filter not in item_id.lower():
                continue
            if min_gsd is not None and (gsd is None or gsd < min_gsd):
                continue
            if max_gsd is not None and (gsd is None or gsd > max_gsd):
                continue
            out.append(feature)

        if max_cloud_cover is None:
            return out

        normalized_collection = (collection_id or "").strip().lower().replace("_", "-")
        if normalized_collection == "l1d-sr":
            # For l1d-sr, apply cloud threshold at capture level using average cloud across tiles.
            # This avoids partial-strip holes where only cloudier tiles are dropped.
            return _filter_l1d_sr_by_average_cloud(out, max_cloud_cover)

        # For non-l1d-sr collections, keep per-feature cloud filtering behavior.
        per_feature = []
        for feature in out:
            cloud = _extract_cloud_cover(feature.get("properties", {}))
            if cloud is None or cloud > max_cloud_cover:
                continue
            per_feature.append(feature)
        return per_feature


def normalize_item(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties", {})
    assets = feature.get("assets", {})

    def asset_url(*names: str) -> str | None:
        for name in names:
            asset = assets.get(name)
            href = asset.get("href") if isinstance(asset, dict) else None
            if href:
                return href
        return None

    def asset_url_by_key_regex(pattern: str) -> str | None:
        rx = re.compile(pattern, flags=re.IGNORECASE)
        for key, asset in assets.items():
            href = asset.get("href") if isinstance(asset, dict) else None
            if not href:
                continue
            key_s = (key or "").strip()
            title_s = ""
            if isinstance(asset, dict):
                title_s = (asset.get("title") or "").strip()
            if rx.search(key_s) or (title_s and rx.search(title_s)):
                return href
        return None

    outcome = props.get("satl:outcome_id") or props.get("outcome_id") or feature.get("id")
    gsd = _extract_gsd(props)
    satellite_name = _extract_satellite_name(props, feature.get("id", ""))

    return {
        "id": feature.get("id"),
        "collection": feature.get("collection"),
        "datetime": props.get("datetime"),
        "outcome_id": outcome,
        "satellite_name": satellite_name,
        "gsd": gsd,
        "cloud_cover": props.get("eo:cloud_cover"),
        "valid_pixel_percent": props.get("satl:valid_pixel") or props.get("satl:valid_pixel_percent"),
        "geometry": feature.get("geometry"),
        "assets": {
            "visual": asset_url("visual", "analytic", "preview", "thumbnail") or "",
            "analytic": asset_url("analytic", "visual", "preview", "thumbnail") or "",
            "preview": asset_url("preview", "thumbnail", "visual", "analytic") or "",
            "thumbnail": asset_url("thumbnail", "preview", "visual", "analytic") or "",
            "cloud_mask": (
                asset_url("cloud_mask", "cloudmask", "cloud-mask", "cmask", "clm")
                or asset_url_by_key_regex(r"(cloud.*mask|mask.*cloud|cmask|cloudmask|clm)")
                or ""
            ),
        },
        "raw": feature,
    }


def _extract_gsd(props: dict[str, Any]) -> float | None:
    for key in ("satl:gsd", "gsd", "eo:gsd"):
        value = props.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _extract_cloud_cover(props: dict[str, Any]) -> float | None:
    for key in ("eo:cloud_cover", "satl:cloud_cover"):
        value = props.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _extract_satellite_name(props: dict[str, Any], item_id: str) -> str | None:
    for key in ("satl:satellite_name", "platform", "sat:platform_international_designator", "constellation"):
        value = props.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    if item_id:
        match = re.search(r"_SN\\d+_", item_id)
        if match:
            return match.group(0).strip("_")
    return None


def _capture_group_key(feature: dict[str, Any]) -> str:
    props = feature.get("properties", {})
    outcome = props.get("satl:outcome_id") or props.get("outcome_id")
    if outcome:
        return f"outcome:{outcome}"

    item_id = feature.get("id", "") or ""
    match = re.search(r"(\\d{8}_\\d{6}_\\d+_SN\\d+)", item_id)
    if match:
        return f"capture:{match.group(1)}"

    # Last-resort grouping key if outcome/capture key is missing.
    return f"fallback:{props.get('datetime') or item_id}"


def _filter_l1d_sr_by_average_cloud(features: list[dict[str, Any]], max_cloud_cover: float) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for feature in features:
        key = _capture_group_key(feature)
        groups.setdefault(key, []).append(feature)

    out: list[dict[str, Any]] = []
    for group_items in groups.values():
        clouds = []
        for feature in group_items:
            cloud = _extract_cloud_cover(feature.get("properties", {}))
            if cloud is not None:
                clouds.append(cloud)
        if not clouds:
            # Keep groups with unknown cloud to avoid unexpectedly dropping valid strips.
            out.extend(group_items)
            continue
        avg_cloud = sum(clouds) / len(clouds)
        if avg_cloud <= max_cloud_cover:
            out.extend(group_items)
    return out
