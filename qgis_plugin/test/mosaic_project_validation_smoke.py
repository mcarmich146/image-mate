#!/usr/bin/env python3
"""Smoke checks for Mosaic project id validation and campaign uniqueness."""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile


def _repo_plugin_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _assert_true(condition: bool, label: str) -> None:
    if not bool(condition):
        raise AssertionError(label)


def main() -> int:
    plugin_root = _repo_plugin_root()
    sys.path.insert(0, str(plugin_root))

    from image_mate_qgis_plugin.services.campaign_storage_service import CampaignStorageService  # noqa: PLC0415
    from image_mate_qgis_plugin.services.mosaic_contracts import validate_project_id  # noqa: PLC0415

    valid_ids = ["alpha", "A1._-", "proj_001", "Z" * 64]
    invalid_ids = ["", ".", "..", "bad id", "bad/slash", "x" * 65]

    for value in valid_ids:
        ok, _ = validate_project_id(value)
        _assert_true(ok, f"expected valid project id: {value}")

    for value in invalid_ids:
        ok, _ = validate_project_id(value)
        _assert_true(not ok, f"expected invalid project id: {value}")

    temp_root = Path(tempfile.mkdtemp(prefix="image_mate_mosaic_validation_"))
    try:
        storage = CampaignStorageService(base_dir=str(temp_root), managed_storage_enabled=True)
        campaign_uid = "campaign-a"
        storage.ensure_campaign_tree(campaign_uid, campaign_name="Campaign A")
        _assert_true(not storage.mosaic_project_exists(campaign_uid, "proj1"), "project should not exist yet")

        project_dir = storage.campaign_mosaic_project_dir(campaign_uid, "proj1")
        _assert_true(project_dir.exists(), "project dir should exist")
        _assert_true(storage.mosaic_project_exists(campaign_uid, "proj1"), "project should exist")

        projects = storage.list_mosaic_projects(campaign_uid)
        _assert_true("proj1" in projects, "project should be listed")

        deleted = storage.delete_mosaic_project(campaign_uid, "proj1")
        _assert_true(deleted, "project should be deleted")
        _assert_true(not storage.mosaic_project_exists(campaign_uid, "proj1"), "project should not exist after delete")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    print("mosaic_project_validation_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
