# -*- coding: utf-8 -*-
"""Campaign-aware filesystem management for managed plugin storage."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import re
import shutil
from typing import Any


class CampaignStorageService:
    """Resolves deterministic campaign paths and ensures campaign folder trees."""

    def __init__(self, *, base_dir: str, managed_storage_enabled: bool = True):
        self._base_dir = Path(str(base_dir or "").strip()).expanduser()
        self._managed_storage_enabled = bool(managed_storage_enabled)

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    @property
    def managed_storage_enabled(self) -> bool:
        return self._managed_storage_enabled

    def set_base_dir(self, base_dir: str) -> None:
        value = str(base_dir or "").strip()
        if not value:
            raise RuntimeError("Campaign base directory is required")
        self._base_dir = Path(value).expanduser()

    def set_managed_storage_enabled(self, enabled: bool) -> None:
        self._managed_storage_enabled = bool(enabled)

    @classmethod
    def normalize_campaign_uid(cls, value: str, *, fallback: str = "default-campaign") -> str:
        text = str(value or "").strip().lower()
        text = re.sub(r"[^0-9a-z._-]+", "-", text)
        text = re.sub(r"-{2,}", "-", text).strip("-.")
        if not text:
            text = str(fallback or "default-campaign").strip().lower()
            text = re.sub(r"[^0-9a-z._-]+", "-", text)
            text = re.sub(r"-{2,}", "-", text).strip("-.")
        if not text:
            text = "default-campaign"
        return text[:96]

    @classmethod
    def sanitize_component(cls, value: str, *, fallback: str = "artifact") -> str:
        text = str(value or "").strip()
        text = re.sub(r"[^0-9A-Za-z._-]+", "_", text).strip("._-")
        if not text:
            text = str(fallback or "artifact").strip() or "artifact"
        return text[:120]

    @property
    def campaigns_dir(self) -> Path:
        return self.base_dir / "campaigns"

    def campaign_root(self, campaign_uid: str) -> Path:
        uid = self.normalize_campaign_uid(campaign_uid)
        return self.campaigns_dir / uid

    def campaign_project_path(self, campaign_uid: str) -> Path:
        return self.campaign_root(campaign_uid) / "campaign" / "campaign.qgs"

    def campaign_manifest_path(self, campaign_uid: str) -> Path:
        return self.campaign_root(campaign_uid) / "campaign" / "campaign_manifest.json"

    def campaign_logs_dir(self, campaign_uid: str) -> Path:
        return self.campaign_root(campaign_uid) / "logs"

    def campaign_temp_dir(self, campaign_uid: str) -> Path:
        return self.campaign_root(campaign_uid) / "temp"

    def campaign_workflow_definitions_dir(self, campaign_uid: str) -> Path:
        return self.campaign_root(campaign_uid) / "exploitation" / "workflows"

    def campaign_collections_dir(self, campaign_uid: str) -> Path:
        path = self.campaign_root(campaign_uid) / "collections"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def campaign_mosaic_root(self, campaign_uid: str) -> Path:
        path = self.campaign_collections_dir(campaign_uid) / "mosaic"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def campaign_mosaic_project_dir(self, campaign_uid: str, project_id: str) -> Path:
        project_key = str(project_id or "").strip()
        if not project_key:
            raise RuntimeError("Mosaic project id is required")
        path = self.campaign_mosaic_root(campaign_uid) / project_key
        path.mkdir(parents=True, exist_ok=True)
        return path

    def campaign_mosaic_project_shapefile_path(self, campaign_uid: str, project_id: str) -> Path:
        return self.campaign_mosaic_project_dir(campaign_uid, project_id) / "tiles.shp"

    def campaign_mosaic_project_db_path(self, campaign_uid: str, project_id: str) -> Path:
        return self.campaign_mosaic_project_dir(campaign_uid, project_id) / "mosaic_tracking.sqlite3"

    def campaign_mosaic_project_meta_path(self, campaign_uid: str, project_id: str) -> Path:
        return self.campaign_mosaic_project_dir(campaign_uid, project_id) / "project_meta.json"

    def list_mosaic_projects(self, campaign_uid: str) -> list[str]:
        root = self.campaign_mosaic_root(campaign_uid)
        if not root.exists() or not root.is_dir():
            return []
        rows = []
        for path in root.iterdir():
            if not path.is_dir():
                continue
            rows.append(str(path.name or "").strip())
        return sorted([row for row in rows if row], key=lambda value: value.lower())

    def mosaic_project_exists(self, campaign_uid: str, project_id: str) -> bool:
        project_key = str(project_id or "").strip()
        if not project_key:
            return False
        root = self.campaign_mosaic_root(campaign_uid)
        return (root / project_key).exists()

    def delete_mosaic_project(self, campaign_uid: str, project_id: str) -> bool:
        project_key = str(project_id or "").strip()
        if not project_key:
            return False
        root = self.campaign_mosaic_root(campaign_uid)
        target = root / project_key
        if not target.exists():
            return False
        if not target.is_dir():
            raise RuntimeError(f"Mosaic project path is not a directory: {target}")
        shutil.rmtree(target)
        return True

    def campaign_vessel_ml_root(self, campaign_uid: str) -> Path:
        path = self.campaign_root(campaign_uid) / "ml" / "vessel"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def campaign_vessel_dataset_dir(self, campaign_uid: str, dataset_id: str) -> Path:
        dataset_key = self.sanitize_component(dataset_id or "dataset", fallback="dataset")
        path = self.campaign_vessel_ml_root(campaign_uid) / "datasets" / dataset_key
        path.mkdir(parents=True, exist_ok=True)
        return path

    def campaign_vessel_runs_dir(self, campaign_uid: str) -> Path:
        path = self.campaign_vessel_ml_root(campaign_uid) / "runs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def campaign_vessel_models_dir(self, campaign_uid: str) -> Path:
        path = self.campaign_vessel_ml_root(campaign_uid) / "models"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def campaign_vessel_qa_export_dir(self, campaign_uid: str, batch_id: str) -> Path:
        batch_key = self.sanitize_component(batch_id or "batch", fallback="batch")
        path = self.campaign_vessel_ml_root(campaign_uid) / "qa_exports" / batch_key
        path.mkdir(parents=True, exist_ok=True)
        return path

    def campaign_vessel_eval_dir(self, campaign_uid: str) -> Path:
        path = self.campaign_vessel_ml_root(campaign_uid) / "eval"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def campaign_imagery_cache_dir(
        self,
        campaign_uid: str,
        *,
        source_id: str,
        item_id: str,
        workflow: bool = False,
    ) -> Path:
        source_key = self.sanitize_component(source_id or "unknown-source", fallback="unknown-source")
        item_key = self.sanitize_component(item_id or "item", fallback="item")
        branch = "workflow" if workflow else "search"
        path = self.campaign_root(campaign_uid) / "imagery" / "raw" / source_key / branch / item_key
        path.mkdir(parents=True, exist_ok=True)
        return path

    def campaign_workflow_source_cache_dir(self, campaign_uid: str) -> Path:
        path = self.campaign_root(campaign_uid) / "imagery" / "raw" / "workflow_sources"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def campaign_geoprocessing_output_path(
        self,
        campaign_uid: str,
        *,
        operation: str,
        suffix: str,
        hint: str = "",
    ) -> Path:
        output_dir = self.campaign_root(campaign_uid) / "geoprocessing" / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        normalized_suffix = str(suffix or "").strip() or ".bin"
        if not normalized_suffix.startswith("."):
            normalized_suffix = f".{normalized_suffix}"
        op = self.sanitize_component(operation or "artifact", fallback="artifact")
        human_hint = self.sanitize_component(hint, fallback=op)
        stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        candidate = output_dir / f"{op}_{human_hint}_{stamp}{normalized_suffix}"
        return self._dedupe_path(candidate)

    def campaign_workflow_run_paths(self, campaign_uid: str, run_id: str) -> dict[str, Path]:
        safe_run_id = self.sanitize_component(run_id or "run", fallback="run")
        run_root = self.campaign_root(campaign_uid) / "exploitation" / "runs" / safe_run_id
        paths = {
            "run_root": run_root,
            "inputs": run_root / "inputs",
            "intermediate": run_root / "intermediate",
            "outputs": run_root / "outputs",
            "logs": run_root / "logs",
        }
        for path in paths.values():
            path.mkdir(parents=True, exist_ok=True)
        return paths

    def campaign_workflow_output_template(
        self,
        campaign_uid: str,
        *,
        run_id: str,
        node_id: str,
        function_id: str,
        suffix: str,
        hint: str = "",
        include_index_token: bool = False,
    ) -> Path:
        run_paths = self.campaign_workflow_run_paths(campaign_uid, run_id)
        output_dir = run_paths["outputs"]
        normalized_suffix = str(suffix or "").strip() or ".bin"
        if not normalized_suffix.startswith("."):
            normalized_suffix = f".{normalized_suffix}"
        node_key = self.sanitize_component(node_id or "node", fallback="node")
        function_key = self.sanitize_component(function_id or "function", fallback="function")
        hint_key = self.sanitize_component(hint, fallback=f"{function_key}_output")
        if include_index_token:
            file_name = f"{node_key}_{function_key}_{hint_key}" + "_{index_03}" + normalized_suffix
        else:
            file_name = f"{node_key}_{function_key}_{hint_key}{normalized_suffix}"
        return output_dir / file_name

    def list_campaigns(self) -> list[dict[str, Any]]:
        campaigns: list[dict[str, Any]] = []
        root = self.campaigns_dir
        if not root.exists() or not root.is_dir():
            return campaigns

        for path in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if not path.is_dir():
                continue
            uid = self.normalize_campaign_uid(path.name, fallback=path.name)
            manifest_path = self.campaign_manifest_path(uid)
            name = uid
            last_opened_utc = ""
            created_utc = ""
            if manifest_path.exists():
                try:
                    raw = manifest_path.read_text(encoding="utf-8")
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        name = str(parsed.get("name") or uid).strip() or uid
                        last_opened_utc = str(parsed.get("last_opened_utc") or "").strip()
                        created_utc = str(parsed.get("created_utc") or "").strip()
                except Exception:
                    pass
            campaigns.append(
                {
                    "uid": uid,
                    "name": name,
                    "last_opened_utc": last_opened_utc,
                    "created_utc": created_utc,
                    "path": str(path),
                }
            )

        campaigns.sort(
            key=lambda row: (
                str(row.get("last_opened_utc") or row.get("created_utc") or ""),
                str(row.get("uid") or ""),
            ),
            reverse=True,
        )
        return campaigns

    def ensure_campaign_tree(self, campaign_uid: str, *, campaign_name: str = "") -> Path:
        uid = self.normalize_campaign_uid(campaign_uid)
        root = self.campaign_root(uid)
        dirs = [
            root / "campaign",
            root / "imagery" / "raw",
            root / "imagery" / "browse",
            root / "imagery" / "derived",
            root / "requests" / "submissions",
            root / "requests" / "responses",
            root / "watch" / "subscriptions",
            root / "watch" / "alerts",
            root / "watch" / "cues",
            root / "collections" / "mosaic",
            root / "exploitation" / "runs",
            root / "exploitation" / "workflows",
            root / "geoprocessing" / "outputs",
            root / "exports",
            root / "logs",
            root / "temp",
        ]
        for path in dirs:
            path.mkdir(parents=True, exist_ok=True)
        self._ensure_campaign_manifest(uid, campaign_name=campaign_name)
        return root

    def _ensure_campaign_manifest(self, campaign_uid: str, *, campaign_name: str = "") -> None:
        manifest_path = self.campaign_manifest_path(campaign_uid)
        manifest: dict[str, Any] = {}
        if manifest_path.exists():
            try:
                raw = manifest_path.read_text(encoding="utf-8")
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    manifest = parsed
            except Exception:
                manifest = {}
        now_utc = datetime.now(tz=timezone.utc).isoformat()
        manifest["schema_version"] = 1
        manifest["campaign_id"] = campaign_uid
        if campaign_name:
            manifest["name"] = str(campaign_name).strip()
        elif not str(manifest.get("name") or "").strip():
            manifest["name"] = campaign_uid
        manifest["last_opened_utc"] = now_utc
        manifest.setdefault("created_utc", now_utc)
        manifest["paths"] = {
            "project": "campaign/campaign.qgs",
            "logs": "logs/",
            "geoprocessing_outputs": "geoprocessing/outputs/",
            "workflow_runs": "exploitation/runs/",
            "imagery_raw": "imagery/raw/",
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    @staticmethod
    def _dedupe_path(path_obj: Path) -> Path:
        candidate = Path(path_obj)
        if not candidate.exists():
            return candidate
        stem = candidate.stem or "artifact"
        suffix = candidate.suffix
        parent = candidate.parent
        serial = 2
        while True:
            retry = parent / f"{stem}_{serial:03d}{suffix}"
            if not retry.exists():
                return retry
            serial += 1
