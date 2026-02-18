# -*- coding: utf-8 -*-
"""Source service backed by local provider clients."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import importlib
import os
import sys
import time
import types
from urllib.parse import urlparse

from ..clients.merlin_sentinel2_client import MerlinSentinel2Client
from ..clients.satellogic_client import SatellogicClient
from ..clients.source_manager import SourceManager
from ..clients.config import settings as backend_settings


class SourceService:
    """Provider/search facade that reuses backend clients and source manager."""

    def __init__(self, provider_settings):
        self._cfg = provider_settings
        self._manager = None
        self._init_error = ""
        self._backend_settings = None
        self._contracts_cache: list[dict[str, Any]] = []
        self._init_clients()

    def _init_clients(self) -> None:
        try:
            sat_client = SatellogicClient()
            merlin_client = MerlinSentinel2Client()
            self._apply_env_overrides_to_clients(sat_client, merlin_client)
            # Keep .env credentials as source of truth; only explicit contract override is applied.
            if str(self._cfg.satellogic_contract_id or "").strip():
                sat_client.contract_id = str(self._cfg.satellogic_contract_id).strip()
            if str(self._cfg.cdse_wmts_base_url or "").strip():
                backend_settings.cdse_wmts_base_url = str(self._cfg.cdse_wmts_base_url).strip()
            if str(self._cfg.cdse_wmts_instance_id or "").strip():
                backend_settings.cdse_wmts_instance_id = str(self._cfg.cdse_wmts_instance_id).strip()
            if str(self._cfg.cdse_wmts_layer_id or "").strip():
                backend_settings.cdse_wmts_layer_id = str(self._cfg.cdse_wmts_layer_id).strip()
            self._manager = SourceManager(sat_client, merlin_client)
            self._backend_settings = backend_settings
            self._init_error = ""
        except Exception as exc:
            self._manager = None
            self._backend_settings = None
            self._init_error = f"Client initialization failed: {exc}"

    @staticmethod
    def _reload_client_modules() -> None:
        # Reload client modules to pick up any changes during development
        for name in (
            "image_mate_qgis_plugin.clients.config",
            "image_mate_qgis_plugin.clients.satellogic_client",
            "image_mate_qgis_plugin.clients.merlin_sentinel2_client",
            "image_mate_qgis_plugin.clients.source_manager",
        ):
            module = sys.modules.get(name)
            if module is not None:
                importlib.reload(module)

    @staticmethod
    def _apply_env_overrides_to_clients(sat_client, merlin_client) -> None:
        sat_client.bearer_token = str(getattr(sat_client, "bearer_token", "") or os.getenv("SATELLOGIC_BEARER_TOKEN", "")).strip()
        sat_client.key_id = str(getattr(sat_client, "key_id", "") or os.getenv("SATELLOGIC_KEY_ID", "")).strip()
        sat_client.key_secret = str(getattr(sat_client, "key_secret", "") or os.getenv("SATELLOGIC_KEY_SECRET", "")).strip()
        sat_client.contract_id = str(getattr(sat_client, "contract_id", "") or os.getenv("SATELLOGIC_CONTRACT_ID", "")).strip()
        sat_client.stac_url = str(getattr(sat_client, "stac_url", "") or os.getenv("SATELLOGIC_STAC_URL", "")).strip().rstrip("/")
        sat_client.token_url = str(getattr(sat_client, "token_url", "") or os.getenv("SATELLOGIC_TOKEN_URL", "")).strip()

        merlin_client.client_id = str(getattr(merlin_client, "client_id", "") or os.getenv("CDSE_CLIENT_ID", "")).strip()
        merlin_client.client_secret = str(getattr(merlin_client, "client_secret", "") or os.getenv("CDSE_CLIENT_SECRET", "")).strip()
        merlin_client.enabled = bool(
            getattr(merlin_client, "enabled", False)
            or str(os.getenv("MERLIN_S2_ENABLED", "")).strip().lower() in {"1", "true", "yes", "on"}
        )

    def list_sources(self):
        if self._manager:
            try:
                return self._manager.list_sources()
            except Exception:
                pass
        return [
            {
                "source_id": "satellogic",
                "title": "Satellogic",
                "enabled": True,
                "supports_contracts": True,
                "default_collection_id": "l1d-sr",
            },
            {
                "source_id": "merlin-s2",
                "title": "Merlin (Sentinel-2)",
                "enabled": bool(self._cfg.cdse_enabled),
                "supports_contracts": False,
                "default_collection_id": "sentinel-2-l2a",
            },
        ]

    def list_collections(self, source_id):
        if self._manager:
            try:
                contract_id = str(self._cfg.satellogic_contract_id or "").strip() or None
                rows = self._manager.list_collections(source_id, contract_id=contract_id)
                out = []
                for row in rows or []:
                    if isinstance(row, dict):
                        out.append(
                            {
                                "id": str(row.get("id") or "").strip(),
                                "title": str(row.get("title") or row.get("id") or "").strip(),
                            }
                        )
                if out:
                    return out
            except Exception:
                pass
        sid = str(source_id or "").strip().lower()
        return (
            [
                {"id": "sentinel-2-l2a", "title": "Sentinel-2 L2A"},
                {"id": "sentinel-2-l1c", "title": "Sentinel-2 L1C"},
            ]
            if sid == "merlin-s2"
            else [
                {"id": "l1d-sr", "title": "L1D Surface Reflectance"},
                {"id": "quickview-visual", "title": "Quickview Visual"},
                {"id": "quickview-visual-thumb", "title": "Quickview Visual Thumb"},
            ]
        )

    def list_contracts(self, source_id: str) -> list[dict[str, Any]]:
        if not self._manager:
            return []
        sid = str(source_id or "").strip().lower()
        if sid != "satellogic":
            return []
        if self._contracts_cache:
            return list(self._contracts_cache)
        try:
            rows = self._manager.list_contracts(sid)
            out = []
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                cid = str(row.get("id") or row.get("contract_id") or "").strip()
                if not cid:
                    continue
                out.append({"id": cid, "name": str(row.get("name") or cid).strip()})
            self._contracts_cache = out
            return list(out)
        except Exception:
            return []

    def search(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        if not self._manager:
            raise RuntimeError(self._init_error or "Source manager unavailable")
        contract_id = str(request.get("contract_id") or self._cfg.satellogic_contract_id or "").strip() or None
        source_id = str(request.get("source_id") or "").strip() or "satellogic"
        if source_id == "satellogic":
            sat_client = getattr(self._manager, "satellogic_client", None)
            if sat_client is not None:
                has_credentials = bool(
                    str(getattr(sat_client, "bearer_token", "") or "").strip()
                    or (
                        str(getattr(sat_client, "key_id", "") or "").strip()
                        and str(getattr(sat_client, "key_secret", "") or "").strip()
                    )
                )
                if not has_credentials:
                    has_credentials = bool(
                        str(os.getenv("SATELLOGIC_BEARER_TOKEN", "")).strip()
                        or (
                            str(os.getenv("SATELLOGIC_KEY_ID", "")).strip()
                            and str(os.getenv("SATELLOGIC_KEY_SECRET", "")).strip()
                        )
                    )
                if not has_credentials:
                    # Get diagnostic info to help debug
                    try:
                        from ..clients.config import get_config_diagnostics
                        diag = get_config_diagnostics()
                        diag_msg = f" [Debug: env_file={diag.get('env_file_loaded')}, " \
                                   f"bearer_in_env={diag.get('bearer_token_in_env')}, " \
                                   f"key_in_env={diag.get('key_id_in_env')}]"
                    except Exception:
                        diag_msg = ""
                    
                    raise RuntimeError(
                        "No Satellogic credentials were detected from .env. "
                        f"Set SATELLOGIC_BEARER_TOKEN or SATELLOGIC_KEY_ID/SATELLOGIC_KEY_SECRET.{diag_msg}"
                    )
                effective_contract = contract_id or str(getattr(sat_client, "contract_id", "") or "").strip() or None
                if not effective_contract:
                    effective_contract = str(os.getenv("SATELLOGIC_CONTRACT_ID", "")).strip() or None
                if not effective_contract:
                    effective_contract = self.default_contract_id() or None
                if not effective_contract:
                    raise RuntimeError(
                        "No Satellogic contract is configured. Set SATELLOGIC_CONTRACT_ID in .env "
                        "or provide Contract ID in the Explore form."
                    )
                if not contract_id:
                    contract_id = effective_contract

        try:
            return self._manager.search(
                source_id=source_id,
                geometry=request["geometry"],
                start_date=str(request["start_date"]),
                end_date=str(request["end_date"]),
                collection_id=str(request["collection_id"]),
                contract_id=contract_id,
                limit=int(request.get("limit") or 250),
                max_cloud_cover=request.get("max_cloud_cover"),
                satellite_name=(str(request.get("satellite_name") or "").strip() or None),
                min_gsd=request.get("min_gsd"),
                max_gsd=request.get("max_gsd"),
            )
        except Exception as exc:
            if source_id == "satellogic" and self._is_unauthorized_error(exc):
                fallback = self._search_satellogic_with_oauth_fallback(request, contract_id=contract_id)
                if fallback is not None:
                    return fallback
                sat_client = getattr(self._manager, "satellogic_client", None)
                auth_mode = str(getattr(sat_client, "auth_mode", "") or "").strip() if sat_client else ""
                effective_contract = contract_id or (
                    str(getattr(sat_client, "contract_id", "") or "").strip() if sat_client else ""
                )
                raise RuntimeError(
                    "Satellogic returned 401 Unauthorized "
                    f"(auth_mode={auth_mode or 'unknown'}, contract={'set' if effective_contract else 'missing'}). "
                    "Verify the bearer token has access to the configured contract and STAC endpoint."
                ) from exc
            raise

    def download_asset(
        self,
        url: str,
        *,
        source_hint: str | None = None,
        contract_id: str | None = None,
    ) -> bytes:
        if not self._manager:
            raise RuntimeError(self._init_error or "Source manager unavailable")
        contract = contract_id or (str(self._cfg.satellogic_contract_id or "").strip() or None)
        return self._manager.download_bytes(url, contract_id=contract, source_hint=source_hint)

    def _normalize_contract_candidate(self, value: str | None) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        contracts = self.list_contracts("satellogic")
        if not contracts:
            return raw

        by_id = {str(row.get("id") or "").strip().lower(): str(row.get("id") or "").strip() for row in contracts}
        if raw.lower() in by_id and by_id[raw.lower()]:
            return by_id[raw.lower()]

        by_name = {
            str(row.get("name") or "").strip().lower(): str(row.get("id") or "").strip()
            for row in contracts
            if str(row.get("name") or "").strip() and str(row.get("id") or "").strip()
        }
        mapped = by_name.get(raw.lower())
        if mapped:
            return mapped
        return raw

    def fetch_satellogic_cog_tile(
        self,
        *,
        z: int,
        x: int,
        y: int,
        source_url: str | None = None,
        source_urls: list[str] | None = None,
        contract_id: str | None = None,
        scale: int = 2,
        buffer: int = 1,
        tile_matrix_set_id: str = "WebMercatorQuad",
        image_format: str = "png",
        bidx: list[int] | None = None,
        max_attempts: int = 3,
        request_timeout: int = 75,
    ) -> tuple[int, bytes, str]:
        if not self._manager:
            raise RuntimeError(self._init_error or "Source manager unavailable")
        sat_client = getattr(self._manager, "satellogic_client", None)
        if sat_client is None:
            raise RuntimeError("Satellogic client unavailable")

        source_candidates: list[str] = []
        seen_sources: set[str] = set()
        for raw_value in list(source_urls or []):
            value = str(raw_value or "").strip()
            if value and value not in seen_sources:
                seen_sources.add(value)
                source_candidates.append(value)
        single_source = str(source_url or "").strip()
        if single_source and single_source not in seen_sources:
            seen_sources.add(single_source)
            source_candidates.append(single_source)
        if not source_candidates:
            raise RuntimeError("COG source URL must be provided")

        for value in source_candidates:
            parsed = urlparse(value)
            if parsed.scheme not in {"s3", "http", "https"}:
                raise RuntimeError("COG source URL must use s3/http/https")

        requested_contract_id = self._normalize_contract_candidate(contract_id) or None
        effective_contract_id = (
            requested_contract_id
            or self._normalize_contract_candidate(str(getattr(sat_client, "contract_id", "") or "").strip())
            or str(self.default_contract_id() or "").strip()
            or None
        )
        if effective_contract_id:
            try:
                sat_client.contract_id = effective_contract_id
            except Exception:
                pass

        headers = sat_client.auth_headers(
            contract_id=effective_contract_id,
            prefer_oauth=True,
            ignore_static_bearer=True,
        )
        auth_header = str(headers.get("authorizationToken") or "")
        if not auth_header.startswith("Bearer ") and "Key,Secret" not in auth_header:
            raise RuntimeError("Satellogic auth headers are unavailable for tile proxy")

        params: list[tuple[str, str]] = [
            ("scale", str(max(1, int(scale or 1)))),
            ("buffer", str(max(0, int(buffer or 0)))),
            ("tileMatrixSetId", str(tile_matrix_set_id or "WebMercatorQuad")),
            ("format", str(image_format or "png")),
        ]
        for value in source_candidates:
            params.append(("url", str(value)))
        bands = [int(value) for value in (bidx or [1, 2, 3])]
        for band in bands:
            params.append(("bidx", str(band)))

        try:
            import requests
        except Exception as exc:
            raise RuntimeError(f"'requests' is required for tile proxying: {exc}") from exc

        upstream_url = f"https://api.satellogic.com/raster/cog/tiles/{int(z)}/{int(x)}/{int(y)}"
        attempts = max(1, int(max_attempts or 1))
        timeout = max(10, int(request_timeout or 75))
        retryable_codes = {429, 500, 502, 503, 504}
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                response = requests.get(upstream_url, headers=headers, params=params, timeout=timeout)
                if response.status_code == 400 and int(buffer or 0) > 0:
                    retry_params = [entry for entry in params if entry[0] != "buffer"]
                    response = requests.get(upstream_url, headers=headers, params=retry_params, timeout=timeout)
                status = int(response.status_code)
                if (
                    status == 401
                    and (attempt + 1) < attempts
                ):
                    detail = str(getattr(response, "text", "") or "").lower()
                    if "contract" in detail:
                        fallback_contract = self._normalize_contract_candidate(self.default_contract_id()) or None
                        if fallback_contract and fallback_contract != effective_contract_id:
                            effective_contract_id = fallback_contract
                            try:
                                sat_client.contract_id = fallback_contract
                            except Exception:
                                pass
                            headers = sat_client.auth_headers(
                                contract_id=effective_contract_id,
                                prefer_oauth=True,
                                ignore_static_bearer=True,
                            )
                            time.sleep(0.2)
                            continue
                if status in retryable_codes and attempt + 1 < attempts:
                    time.sleep(0.35 * (attempt + 1))
                    continue
                media_type = str(response.headers.get("Content-Type") or "image/png").split(";")[0].strip() or "image/png"
                return status, response.content or b"", media_type
            except Exception as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(0.35 * (attempt + 1))
                    continue

        if last_error is not None:
            raise RuntimeError(f"Upstream tile request failed after {attempts} attempt(s): {last_error}") from last_error
        raise RuntimeError("Upstream tile request failed")

    def _search_satellogic_with_oauth_fallback(
        self,
        request: dict[str, Any],
        *,
        contract_id: str | None,
    ) -> list[dict[str, Any]] | None:
        sat_client = getattr(self._manager, "satellogic_client", None) if self._manager else None
        if sat_client is None:
            return None
        has_key_credentials = bool(
            str(getattr(sat_client, "key_id", "") or "").strip()
            and str(getattr(sat_client, "key_secret", "") or "").strip()
        )
        if not has_key_credentials:
            return None

        original_mode = str(getattr(sat_client, "auth_mode", "") or "").strip()
        try:
            sat_client.auth_mode = "oauth_client_credentials"
            sat_client._access_token = None
            sat_client._access_token_expiry = None
            features = sat_client.search(
                geometry=request["geometry"],
                start_date=str(request["start_date"]),
                end_date=str(request["end_date"]),
                collection_id=str(request["collection_id"]),
                contract_id=contract_id,
                limit=int(request.get("limit") or 250),
                max_cloud_cover=request.get("max_cloud_cover"),
                satellite_name=(str(request.get("satellite_name") or "").strip() or None),
                min_gsd=request.get("min_gsd"),
                max_gsd=request.get("max_gsd"),
            )
            from ..clients.satellogic_client import normalize_item

            items = [normalize_item(feature) for feature in features or []]
            for row in items:
                row["source_id"] = "satellogic"
            return items
        except Exception:
            sat_client.auth_mode = original_mode
            return None

    @staticmethod
    def _is_unauthorized_error(exc: Exception) -> bool:
        resp = getattr(exc, "response", None)
        code = getattr(resp, "status_code", None)
        if int(code or 0) == 401:
            return True
        return "401" in str(exc)

    def default_contract_id(self) -> str:
        sat_client = getattr(self._manager, "satellogic_client", None) if self._manager else None
        cfg_value = str(self._cfg.satellogic_contract_id or "").strip()
        env_value = str(os.getenv("SATELLOGIC_CONTRACT_ID", "")).strip()

        # Try configured/runtime values first, but normalize names -> ids when contract discovery is available.
        for candidate in (
            str(getattr(sat_client, "contract_id", "") or "").strip() if sat_client is not None else "",
            env_value,
            cfg_value,
        ):
            normalized = self._normalize_contract_candidate(candidate)
            if normalized:
                if sat_client is not None:
                    sat_client.contract_id = normalized
                return normalized

        contracts = self.list_contracts("satellogic")
        if contracts:
            value = self._normalize_contract_candidate(str(contracts[0].get("id") or "").strip())
            if value:
                if sat_client is not None:
                    sat_client.contract_id = value
                return value

        # Last fallback if discovery is unavailable.
        if sat_client is not None:
            value = str(getattr(sat_client, "contract_id", "") or "").strip()
            if value:
                return value
        if env_value:
            if sat_client is not None:
                sat_client.contract_id = env_value
            return env_value
        return cfg_value

    def resolve_contract_id(self, contract_id: str | None) -> str:
        return self._normalize_contract_candidate(contract_id)

    def runtime_summary(self):
        sat_auth_mode = str(self._cfg.satellogic_auth_mode or "").strip()
        sat_contract = str(self._cfg.satellogic_contract_id or "").strip()
        cdse_enabled = bool(self._cfg.cdse_enabled)
        sat_credential_detected = False
        cdse_credential_detected = False
        if self._manager:
            sat_client = getattr(self._manager, "satellogic_client", None)
            merlin_client = getattr(self._manager, "merlin_client", None)
            if sat_client is not None:
                sat_auth_mode = str(getattr(sat_client, "auth_mode", "") or sat_auth_mode)
                sat_contract = str(getattr(sat_client, "contract_id", "") or sat_contract)
                sat_credential_detected = bool(
                    str(getattr(sat_client, "bearer_token", "") or "").strip()
                    or (
                        str(getattr(sat_client, "key_id", "") or "").strip()
                        and str(getattr(sat_client, "key_secret", "") or "").strip()
                    )
                )
            if merlin_client is not None:
                cdse_enabled = bool(getattr(merlin_client, "enabled", cdse_enabled))
                cdse_credential_detected = bool(
                    str(getattr(merlin_client, "client_id", "") or "").strip()
                    and str(getattr(merlin_client, "client_secret", "") or "").strip()
                )
        if not sat_credential_detected:
            sat_credential_detected = bool(
                str(os.getenv("SATELLOGIC_BEARER_TOKEN", "")).strip()
                or (
                    str(os.getenv("SATELLOGIC_KEY_ID", "")).strip()
                    and str(os.getenv("SATELLOGIC_KEY_SECRET", "")).strip()
                )
            )
        if not cdse_credential_detected:
            cdse_credential_detected = bool(
                str(os.getenv("CDSE_CLIENT_ID", "")).strip() and str(os.getenv("CDSE_CLIENT_SECRET", "")).strip()
            )
        if not sat_contract:
            sat_contract = str(os.getenv("SATELLOGIC_CONTRACT_ID", "")).strip() or sat_contract
        wmts_configured = bool(self._cfg.cdse_wmts_instance_id.strip())
        if self._backend_settings is not None:
            wmts_configured = bool(str(getattr(self._backend_settings, "cdse_wmts_instance_id", "") or "").strip())
        return {
            "satellogic_auth_mode": sat_auth_mode,
            "satellogic_contract_configured": bool(sat_contract.strip()),
            "satellogic_credentials_detected": sat_credential_detected,
            "satellogic_authcfg_configured": bool(self._cfg.satellogic_authcfg_id.strip()),
            "cdse_enabled": cdse_enabled,
            "cdse_wmts_configured": wmts_configured,
            "cdse_credentials_detected": cdse_credential_detected,
            "cdse_authcfg_configured": bool(self._cfg.cdse_authcfg_id.strip()),
            "clients_ready": bool(self._manager is not None),
            "init_error": self._init_error,
        }
