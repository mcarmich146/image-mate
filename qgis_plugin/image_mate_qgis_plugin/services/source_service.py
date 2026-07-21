# -*- coding: utf-8 -*-
"""Source service backed by local provider clients."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import importlib
import logging
import os
import sys
import time
import types
from urllib.parse import quote, urlparse

from ..clients.merlin_sentinel2_client import MerlinSentinel2Client
from ..clients.satellogic_client import SatellogicClient
from ..clients.source_manager import SourceManager
from ..clients.config import settings as backend_settings

logger = logging.getLogger(__name__)

TASKING_PRODUCTS = [
    {
        "sku": "TSKPOI-M",
        "label": "Point Target (single attempt)",
        "target_types": ["point"],
        "notes": "Single point-target acquisition attempt.",
    },
    {
        "sku": "TSKRSH-M.15.01",
        "label": "Point Revisit 15-day (1 revisit)",
        "target_types": ["point"],
        "notes": "Point target with revisit schedule.",
    },
    {
        "sku": "TSKRSH-M.15.15",
        "label": "Point Revisit 15-day (15 revisits)",
        "target_types": ["point"],
        "notes": "Point target with revisit schedule.",
    },
    {
        "sku": "TSKRSH-M.30.30",
        "label": "Point Revisit 30-day (30 revisits)",
        "target_types": ["point"],
        "notes": "Point target with revisit schedule.",
    },
    {
        "sku": "TSKARE-M",
        "label": "Area Tasking (single attempt)",
        "target_types": ["area"],
        "notes": "Single area tasking request.",
    },
    {
        "sku": "TSKRRD-M.15.01",
        "label": "Area Revisit 15-day (1 revisit)",
        "target_types": ["area"],
        "notes": "Area tasking with remapping schedule.",
    },
    {
        "sku": "TSKRRD-M.15.15",
        "label": "Area Revisit 15-day (15 revisits)",
        "target_types": ["area"],
        "notes": "Area tasking with remapping schedule.",
    },
    {
        "sku": "TSKRRD-M.30.30",
        "label": "Area Revisit 30-day (30 revisits)",
        "target_types": ["area"],
        "notes": "Area tasking with remapping schedule.",
    },
]
TASKING_ORDER_SEARCH_LIMIT = 500


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
            # Keep Sentinel-2 available in plugin-only mode; request failures surface credential errors at runtime.
            merlin_client.enabled = True
            if str(self._cfg.cdse_stac_url or "").strip():
                merlin_client.stac_url = str(self._cfg.cdse_stac_url).strip().rstrip("/")
            if str(self._cfg.cdse_client_id or "").strip():
                merlin_client.client_id = str(self._cfg.cdse_client_id).strip()
            if str(self._cfg.cdse_client_secret or "").strip():
                merlin_client.client_secret = str(self._cfg.cdse_client_secret).strip()
            # Keep .env credentials as source of truth; only explicit contract override is applied.
            if str(self._cfg.satellogic_contract_id or "").strip():
                sat_client.contract_id = str(self._cfg.satellogic_contract_id).strip()
            if str(self._cfg.cdse_stac_url or "").strip():
                backend_settings.cdse_stac_url = str(self._cfg.cdse_stac_url).strip().rstrip("/")
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
            logger.exception("source_service init failed error=%s", exc)
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
                rows = self._manager.list_sources()
                by_source = {}
                for row in rows or []:
                    if not isinstance(row, dict):
                        continue
                    sid = str(row.get("source_id") or "").strip().lower()
                    if not sid:
                        continue
                    by_source[sid] = dict(row)
                if "satellogic" not in by_source:
                    by_source["satellogic"] = {
                        "source_id": "satellogic",
                        "title": "NewSat Constellation",
                        "enabled": True,
                        "supports_contracts": True,
                        "default_collection_id": "l1d-sr",
                    }
                if "merlin-s2" not in by_source:
                    by_source["merlin-s2"] = {
                        "source_id": "merlin-s2",
                        "title": "Merlin (Sentinel-2)",
                        "enabled": True,
                        "supports_contracts": False,
                        "default_collection_id": "sentinel-2-l2a",
                    }
                by_source["merlin-s2"]["enabled"] = True
                ordered = [
                    by_source.get("satellogic", {}),
                    by_source.get("merlin-s2", {}),
                ]
                logger.info(
                    "plugin_source_list source_tags=%s",
                    ",".join(
                        f"{str(row.get('source_id') or '')}:{'on' if bool(row.get('enabled')) else 'off'}"
                        for row in ordered
                        if isinstance(row, dict) and str(row.get("source_id") or "").strip()
                    ),
                )
                return ordered
            except Exception as exc:
                logger.warning("plugin_source_list fallback reason=%s", exc)
        fallback = [
            {
                "source_id": "satellogic",
                "title": "NewSat Constellation",
                "enabled": True,
                "supports_contracts": True,
                "default_collection_id": "l1d-sr",
            },
            {
                "source_id": "merlin-s2",
                "title": "Merlin (Sentinel-2)",
                "enabled": True,
                "supports_contracts": False,
                "default_collection_id": "sentinel-2-l2a",
            },
        ]
        logger.info(
            "plugin_source_list fallback source_tags=%s",
            ",".join(f"{row['source_id']}:{'on' if row['enabled'] else 'off'}" for row in fallback),
        )
        return fallback

    def list_collections(self, source_id):
        sid = str(source_id or "").strip().lower()
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
                    logger.info(
                        "plugin_collection_list source=%s count=%s first=%s",
                        sid or "unknown",
                        len(out),
                        out[0].get("id") if out else "",
                    )
                    return out
                if sid == "merlin-s2":
                    logger.warning("plugin_collection_list source=merlin-s2 empty_manager_result=true")
            except Exception as exc:
                logger.warning("plugin_collection_list source=%s fallback reason=%s", sid or "unknown", exc)
        fallback = self.default_collections(sid)
        if sid == "merlin-s2":
            logger.info(
                "plugin_collection_list source=merlin-s2 count=%s first=%s fallback=sentinel_default_only",
                len(fallback),
                fallback[0]["id"],
            )
            return fallback
        logger.info(
            "plugin_collection_list source=%s count=%s first=%s fallback=satellogic_default",
            sid or "unknown",
            len(fallback),
            fallback[0]["id"],
        )
        return fallback

    def default_collections(self, source_id):
        """Return local collection choices without authentication or network access."""
        sid = str(source_id or "").strip().lower()
        if sid == "merlin-s2":
            default_collection = "sentinel-2-l2a"
            if self._manager is not None:
                merlin_client = getattr(self._manager, "merlin_client", None)
                defaults = getattr(merlin_client, "default_collections", None)
                if isinstance(defaults, list) and defaults:
                    candidate = str(defaults[0] or "").strip()
                    if candidate:
                        default_collection = candidate
            return [{"id": default_collection, "title": default_collection}]
        return [
            {"id": "l1d-sr", "title": "L1D Surface Reflectance"},
            {"id": "quickview-visual", "title": "Quickview Visual"},
            {"id": "quickview-visual-thumb", "title": "Quickview Visual Thumb"},
        ]

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
        collection_id = str(request.get("collection_id") or "").strip()
        logger.info(
            "plugin_search_request source=%s collection=%s limit=%s contract=%s",
            source_id,
            collection_id or "",
            int(request.get("limit") or 250),
            "set" if contract_id else "missing",
        )
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
                        "No NewSat Constellation credentials were detected from .env. "
                        f"Set SATELLOGIC_BEARER_TOKEN or SATELLOGIC_KEY_ID/SATELLOGIC_KEY_SECRET.{diag_msg}"
                    )
                effective_contract = contract_id or str(getattr(sat_client, "contract_id", "") or "").strip() or None
                if not effective_contract:
                    effective_contract = str(os.getenv("SATELLOGIC_CONTRACT_ID", "")).strip() or None
                if not effective_contract:
                    effective_contract = self.default_contract_id() or None
                if not contract_id and effective_contract:
                    contract_id = effective_contract

        try:
            items = self._manager.search(
                source_id=source_id,
                geometry=request["geometry"],
                start_date=str(request["start_date"]),
                end_date=str(request["end_date"]),
                collection_id=collection_id,
                contract_id=contract_id,
                limit=int(request.get("limit") or 250),
                max_cloud_cover=request.get("max_cloud_cover"),
                satellite_name=(str(request.get("satellite_name") or "").strip() or None),
                min_gsd=request.get("min_gsd"),
                max_gsd=request.get("max_gsd"),
            )
            logger.info(
                "plugin_search_result source=%s collection=%s count=%s",
                source_id,
                collection_id or "",
                len(items or []),
            )
            return items
        except Exception as exc:
            logger.warning(
                "plugin_search_failed source=%s collection=%s error=%s",
                source_id,
                collection_id or "",
                exc,
            )
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
                    "NewSat Constellation returned 401 Unauthorized "
                    f"(auth_mode={auth_mode or 'unknown'}, contract={'set' if effective_contract else 'missing'}). "
                    "Verify the bearer token has access to the configured access profile and STAC endpoint."
                ) from exc
            if source_id == "satellogic" and not contract_id and self._is_contract_required_error(exc):
                raise RuntimeError(
                    "NewSat Constellation search requires an Access Profile. "
                    "Set SATELLOGIC_CONTRACT_ID in .env, configure Access Profile in Integrations, "
                    "or enter Access Profile in Collection Search."
                ) from exc
            if source_id == "merlin-s2" and "CDSE credentials are missing" in str(exc):
                raise RuntimeError(
                    "CDSE credentials are missing. Configure Client ID and Client Secret under "
                    "Integrations -> Merlin / CDSE, or set CDSE_CLIENT_ID/CDSE_CLIENT_SECRET in environment."
                ) from exc
            raise

    def item_by_id(
        self,
        item_id: str,
        *,
        source_id: str = "satellogic",
        contract_id: str | None = None,
        collection_id: str | None = None,
    ) -> dict[str, Any] | None:
        if not self._manager:
            raise RuntimeError(self._init_error or "Source manager unavailable")
        item_key = str(item_id or "").strip()
        if not item_key:
            raise RuntimeError("Item id is required")
        return self._manager.item_by_id(
            item_key,
            source_id=str(source_id or "").strip() or "satellogic",
            contract_id=str(contract_id or "").strip() or None,
            collection_id=str(collection_id or "").strip() or None,
        )

    @staticmethod
    def _normalize_tasking_order(raw: dict[str, Any]) -> dict[str, Any]:
        feature = raw.get("feature") if isinstance(raw.get("feature"), dict) else raw
        props = raw.get("properties")
        if not isinstance(props, dict):
            props = feature.get("properties") if isinstance(feature, dict) else None
        properties = props if isinstance(props, dict) else {}
        params = properties.get("parameters")
        if not isinstance(params, dict):
            params = feature.get("parameters") if isinstance(feature, dict) else None
        parameters = params if isinstance(params, dict) else {}
        geometry = raw.get("geometry")
        if not isinstance(geometry, dict):
            geometry = feature.get("geometry") if isinstance(feature, dict) else None
        geometry_obj = geometry if isinstance(geometry, dict) else {}
        order_id = (
            raw.get("id")
            or (feature.get("id") if isinstance(feature, dict) else None)
            or properties.get("order_id")
            or properties.get("id")
        )
        sku = (
            properties.get("sku")
            or properties.get("product")
            or properties.get("product_name")
            or properties.get("product_id")
            or raw.get("sku")
            or (feature.get("sku") if isinstance(feature, dict) else None)
        )
        status_raw = str(properties.get("status") or raw.get("status") or "unknown").strip() or "unknown"
        return {
            "id": order_id,
            "status": status_raw,
            "lifecycle_status": status_raw,
            "order_name": properties.get("order_name") or properties.get("name") or "",
            "project_name": properties.get("project_name") or "",
            "sku": sku,
            "created_at": (
                properties.get("created_at")
                or properties.get("created")
                or raw.get("created_at")
                or raw.get("created")
            ),
            "updated_at": (
                properties.get("updated_at")
                or raw.get("updated_at")
                or raw.get("updated")
            ),
            "start": parameters.get("start") or parameters.get("from"),
            "end": parameters.get("end") or parameters.get("to"),
            "revisit_period": parameters.get("revisit_period"),
            "remapping_period": parameters.get("remapping_period"),
            "geometry_type": geometry_obj.get("type"),
            "geometry": geometry_obj,
            "parameters": parameters,
            "status_report": properties.get("status_report") or raw.get("status_report"),
            "latest_event": properties.get("latest_event") if isinstance(properties.get("latest_event"), dict) else {},
            "raw": raw,
        }

    @staticmethod
    def _status_from_report_value(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        normalized = text.lower()
        if normalized in {"completed", "complete", "delivered", "success", "succeeded"}:
            return "Completed"
        if normalized in {"failed", "failure", "rejected", "expired", "cancelled", "canceled"}:
            return "Failed"
        return text

    @classmethod
    def _status_from_status_report(cls, status_report: Any) -> str:
        if isinstance(status_report, str):
            return cls._status_from_report_value(status_report)
        if isinstance(status_report, dict):
            for key in (
                "status",
                "outcome",
                "result",
                "task_status",
                "order_status",
                "final_status",
                "delivery_status",
                "acquisition_status",
            ):
                resolved = cls._status_from_report_value(status_report.get(key))
                if resolved:
                    return resolved
        return ""

    @staticmethod
    def _is_tasking_sku(value: Any) -> bool:
        return str(value or "").strip().upper().startswith("TSK")

    @staticmethod
    def _tasking_rows_from_payload(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict):
            features = payload.get("features")
            if isinstance(features, list):
                return [row for row in features if isinstance(row, dict)]
            results = payload.get("results")
            if isinstance(results, list):
                return [row for row in results if isinstance(row, dict)]
            orders = payload.get("orders")
            if isinstance(orders, list):
                return [row for row in orders if isinstance(row, dict)]
            if isinstance(payload.get("id"), str):
                return [payload]
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        return []

    def _tasking_client(self):
        if not self._manager:
            raise RuntimeError(self._init_error or "Source manager unavailable")
        sat_client = getattr(self._manager, "satellogic_client", None)
        if sat_client is None:
            raise RuntimeError("Satellogic client unavailable")
        return sat_client

    def _collect_tasking_orders(self, *, contract_id: str | None, limit: int) -> list[dict[str, Any]]:
        sat_client = self._tasking_client()
        rows: list[dict[str, Any]] = []
        next_url: str | None = None
        pages = 0
        capped_limit = max(1, min(int(limit or TASKING_ORDER_SEARCH_LIMIT), TASKING_ORDER_SEARCH_LIMIT))
        while len(rows) < capped_limit and pages < 6:
            page_limit = min(TASKING_ORDER_SEARCH_LIMIT, max(1, capped_limit - len(rows)))
            payload = sat_client.list_orders(contract_id=contract_id, limit=page_limit, next_url=next_url)
            page_rows = self._tasking_rows_from_payload(payload)
            if not page_rows:
                break
            for row in page_rows:
                normalized = self._normalize_tasking_order(row)
                if self._is_tasking_sku(normalized.get("sku")):
                    rows.append(normalized)
                    if len(rows) >= capped_limit:
                        break
            next_val = payload.get("next") if isinstance(payload, dict) else None
            next_url = str(next_val).strip() if next_val else None
            pages += 1
            if not next_url:
                break
        rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        return rows[:capped_limit]

    def list_tasking_products(self) -> list[dict[str, Any]]:
        return [dict(row) for row in TASKING_PRODUCTS]

    def list_tasking_orders(
        self,
        *,
        contract_id: str | None = None,
        limit: int = TASKING_ORDER_SEARCH_LIMIT,
    ) -> list[dict[str, Any]]:
        effective_contract = self._normalize_contract_candidate(contract_id) or self.default_contract_id() or None
        return self._collect_tasking_orders(contract_id=effective_contract, limit=limit)

    def list_tasking_projects(
        self,
        *,
        contract_id: str | None = None,
        limit: int = TASKING_ORDER_SEARCH_LIMIT,
    ) -> list[str]:
        rows = self.list_tasking_orders(contract_id=contract_id, limit=limit)
        projects = sorted({
            str(row.get("project_name") or "").strip()
            for row in rows
            if str(row.get("project_name") or "").strip()
        })
        return projects

    def resolve_tasking_order_status(
        self,
        *,
        order: dict[str, Any] | None,
        order_id: str,
        contract_id: str | None = None,
    ) -> str:
        row = order if isinstance(order, dict) else {}
        lifecycle_status = (
            str(row.get("lifecycle_status") or row.get("status") or "").strip()
            or "unknown"
        )
        report_status = self._status_from_status_report(row.get("status_report"))
        if report_status:
            return report_status
        if lifecycle_status.lower() != "closed":
            return lifecycle_status

        order_key = str(order_id or row.get("id") or "").strip()
        if not order_key:
            return lifecycle_status
        try:
            sat_client = self._tasking_client()
            list_deliverables = getattr(sat_client, "list_order_deliverables", None)
            if not callable(list_deliverables):
                return lifecycle_status
            effective_contract = self._normalize_contract_candidate(contract_id) or self.default_contract_id() or None
            payload = list_deliverables(order_key, contract_id=effective_contract)
            results = payload.get("results") if isinstance(payload, dict) else []
            rows = [entry for entry in (results or []) if isinstance(entry, dict)]
            statuses = [str(entry.get("status") or "").strip().upper() for entry in rows]
        except Exception:
            return lifecycle_status

        if any(value in {"DELIVERED", "COMPLETED", "SUCCESS", "SUCCEEDED"} for value in statuses):
            return "Completed"
        if not statuses:
            return "Failed"
        if all(value in {"FAILED", "FAILURE", "REJECTED", "EXPIRED", "CANCELLED", "CANCELED"} for value in statuses):
            return "Failed"
        return "Failed"

    def get_tasking_order(self, order_id: str, *, contract_id: str | None = None) -> dict[str, Any]:
        order_key = str(order_id or "").strip()
        if not order_key:
            raise RuntimeError("Tasking order id is required")
        sat_client = self._tasking_client()
        effective_contract = self._normalize_contract_candidate(contract_id) or self.default_contract_id() or None
        row = sat_client.get_order(order_key, contract_id=effective_contract)
        normalized = self._normalize_tasking_order(row)
        normalized["status"] = self.resolve_tasking_order_status(
            order=normalized,
            order_id=order_key,
            contract_id=effective_contract,
        )
        return {"order": normalized, "raw": row}

    def list_tasking_order_deliverables(self, order_id: str, *, contract_id: str | None = None) -> dict[str, Any]:
        order_key = str(order_id or "").strip()
        if not order_key:
            raise RuntimeError("Tasking order id is required")
        sat_client = self._tasking_client()
        effective_contract = self._normalize_contract_candidate(contract_id) or self.default_contract_id() or None
        payload = sat_client.list_order_deliverables(order_key, contract_id=effective_contract)
        results = payload.get("results") if isinstance(payload, dict) else []
        deliverables = [row for row in (results or []) if isinstance(row, dict)]
        return {
            "order_id": order_key,
            "deliverables": deliverables,
            "raw": payload,
        }

    def cancel_tasking_order(self, order_id: str, *, contract_id: str | None = None) -> dict[str, Any]:
        order_key = str(order_id or "").strip()
        if not order_key:
            raise RuntimeError("Tasking order id is required")
        sat_client = self._tasking_client()
        effective_contract = self._normalize_contract_candidate(contract_id) or self.default_contract_id() or None
        get_order = getattr(sat_client, "get_order", None)
        cancel_task = getattr(sat_client, "cancel_task", None)

        order_payload: dict[str, Any] = {}
        if callable(get_order):
            try:
                row = get_order(order_key, contract_id=effective_contract)
                if isinstance(row, dict):
                    order_payload = row
            except Exception:
                order_payload = {}

        task_id = ""
        if order_payload:
            props = order_payload.get("properties") if isinstance(order_payload.get("properties"), dict) else {}
            params = props.get("parameters") if isinstance(props.get("parameters"), dict) else {}
            task_candidate = params.get("task_id") or props.get("task_id")
            task_id = str(task_candidate or "").strip()

        if task_id and callable(cancel_task):
            cancel_payload = cancel_task(task_id, contract_id=effective_contract)
            order_normalized = self._normalize_tasking_order(order_payload) if order_payload else {}
            if not order_normalized:
                order_normalized = {
                    "id": order_key,
                    "status": str(cancel_payload.get("status") or "canceled").strip() or "canceled",
                    "task_id": task_id,
                }
            else:
                order_normalized["status"] = (
                    str(cancel_payload.get("status") or order_normalized.get("status") or "canceled").strip() or "canceled"
                )
                order_normalized["task_id"] = task_id
            return {
                "order": order_normalized,
                "raw": {
                    "order": order_payload,
                    "cancel": cancel_payload,
                },
            }

        row = sat_client.cancel_order(order_key, contract_id=effective_contract)
        return {"order": self._normalize_tasking_order(row), "raw": row}

    def create_tasking_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        sat_client = self._tasking_client()
        target_type = str(payload.get("target_type") or "").strip().lower()
        if target_type not in {"point", "area"}:
            raise RuntimeError("Tasking target_type must be 'point' or 'area'")

        geometry = payload.get("geometry")
        if not isinstance(geometry, dict):
            raise RuntimeError("Tasking geometry is required")
        geometry_type = str(geometry.get("type") or "").strip()
        if target_type == "point" and geometry_type != "Point":
            raise RuntimeError("Point target requires Point geometry")
        if target_type == "area" and geometry_type != "Polygon":
            raise RuntimeError("Area target requires Polygon geometry")

        order_name = str(payload.get("order_name") or "").strip()
        sku = str(payload.get("sku") or "").strip()
        start_date = str(payload.get("start_date") or "").strip()
        end_date = str(payload.get("end_date") or "").strip()
        if not order_name:
            raise RuntimeError("Tasking order_name is required")
        if not sku:
            raise RuntimeError("Tasking sku is required")
        if not start_date or not end_date:
            raise RuntimeError("Tasking start_date and end_date are required")

        parameters: dict[str, Any] = {
            "start": start_date,
            "end": end_date,
        }
        revisit_period = str(payload.get("revisit_period") or "").strip()
        remapping_period = str(payload.get("remapping_period") or "").strip()
        if target_type == "point" and revisit_period:
            parameters["revisit_period"] = revisit_period
        if target_type == "area" and remapping_period:
            parameters["remapping_period"] = remapping_period

        additional_parameters = payload.get("additional_parameters")
        if isinstance(additional_parameters, dict):
            for key, value in additional_parameters.items():
                if value is None:
                    continue
                parameters[str(key)] = value

        feature = {
            "type": "Feature",
            "geometry": geometry,
            "properties": {
                "order_name": order_name,
                "sku": sku,
                "parameters": parameters,
            },
        }
        project_name = str(payload.get("project_name") or "").strip()
        if project_name:
            feature["properties"]["project_name"] = project_name

        requested_contract = str(payload.get("contract_id") or "").strip()
        effective_contract = (
            self._normalize_contract_candidate(requested_contract) or self.default_contract_id() or None
        )
        created = sat_client.create_order(feature, contract_id=effective_contract)
        rows = self._tasking_rows_from_payload(created)
        if rows:
            normalized = [self._normalize_tasking_order(row) for row in rows]
            return {
                "accepted": bool(normalized),
                "count": len(normalized),
                "order": normalized[0],
                "orders": normalized,
                "raw": created,
            }
        return {"accepted": True, "order": self._normalize_tasking_order(created), "raw": created}

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

    def fetch_satellogic_telluric_tile(
        self,
        *,
        z: int,
        x: int,
        y: int,
        scene_id: str,
        raster_name: str,
        contract_id: str | None = None,
        max_attempts: int = 3,
        request_timeout: int = 75,
    ) -> tuple[int, bytes, str]:
        if not self._manager:
            raise RuntimeError(self._init_error or "Source manager unavailable")
        sat_client = getattr(self._manager, "satellogic_client", None)
        if sat_client is None:
            raise RuntimeError("Satellogic client unavailable")

        scene_key = str(scene_id or "").strip()
        raster_key = str(raster_name or "").strip()
        if not scene_key:
            raise RuntimeError("Telluric scene_id is required")
        if not raster_key:
            raise RuntimeError("Telluric raster_name is required")

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
            raise RuntimeError("Satellogic auth headers are unavailable for Telluric tile proxy")

        upstream_url = (
            "https://api.satellogic.com/telluric/scenes/"
            f"{quote(scene_key, safe='')}/rasters/{quote(raster_key, safe='')}/get_tile/"
        )
        params = {
            "x": int(x),
            "y": int(y),
            "z": int(z),
        }

        try:
            import requests
        except Exception as exc:
            raise RuntimeError(f"'requests' is required for tile proxying: {exc}") from exc

        attempts = max(1, int(max_attempts or 1))
        timeout = max(10, int(request_timeout or 75))
        retryable_codes = {429, 500, 502, 503, 504}
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                response = requests.get(upstream_url, headers=headers, params=params, timeout=timeout)
                status = int(response.status_code)
                if status == 401 and (attempt + 1) < attempts:
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
                media_type = (
                    str(response.headers.get("Content-Type") or "image/png").split(";")[0].strip() or "image/png"
                )
                return status, response.content or b"", media_type
            except Exception as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(0.35 * (attempt + 1))
                    continue

        if last_error is not None:
            raise RuntimeError(f"Telluric tile request failed after {attempts} attempt(s): {last_error}") from last_error
        raise RuntimeError("Telluric tile request failed")

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

    @staticmethod
    def _is_contract_required_error(exc: Exception) -> bool:
        text = str(exc or "").strip().lower()
        if not text:
            return False
        needles = (
            "contract",
            "x-satellogic-contract-id",
            "contract id",
            "access profile",
            "missing required header",
        )
        return any(token in text for token in needles)

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
                str(getattr(self._cfg, "cdse_client_id", "") or "").strip()
                and str(getattr(self._cfg, "cdse_client_secret", "") or "").strip()
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
            "cdse_wmts_use_backend_proxy": bool(getattr(self._cfg, "cdse_wmts_use_backend_proxy", True)),
            "cdse_credentials_detected": cdse_credential_detected,
            "cdse_authcfg_configured": bool(self._cfg.cdse_authcfg_id.strip()),
            "clients_ready": bool(self._manager is not None),
            "init_error": self._init_error,
        }
