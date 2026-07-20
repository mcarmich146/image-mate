#!/usr/bin/env python3
"""Smoke check that manual Asset Intel units survive schema sync validation."""

from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import uuid


def _repo_plugin_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _assert_true(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)


def main() -> int:
    plugin_root = _repo_plugin_root()
    sys.path.insert(0, str(plugin_root))

    from image_mate_qgis_plugin.services.asset_intel_service import AssetIntelService  # noqa: PLC0415

    source_db = plugin_root / "test" / "playground" / "vessel_db_prototype.sqlite"
    _assert_true(source_db.exists(), f"missing fixture DB: {source_db}")

    with tempfile.TemporaryDirectory(
        prefix="asset_intel_manual_unit_",
        ignore_cleanup_errors=True,
    ) as temp_dir:
        db_path = Path(temp_dir) / "asset_intel.sqlite"
        shutil.copy2(source_db, db_path)

        service = AssetIntelService(str(db_path))
        state = service.validate()
        _assert_true(bool(state.get("ok")), f"initial validate failed: {state}")

        asset_id = f"manual_unit_{uuid.uuid4().hex}"
        created_asset_id = service.create_asset(
            {
                "asset_id": asset_id,
                "title": "Manual Unit Persistence Smoke Asset",
            }
        )
        _assert_true(created_asset_id == asset_id, "asset create returned unexpected ID")

        unit_id = int(
            service.create_unit(
                {
                    "asset_id": asset_id,
                    "display_name": "Smoke Unit",
                    "status": "active",
                    "source": "manual",
                }
            )
            or 0
        )
        _assert_true(unit_id > 0, "create_unit returned invalid id")

        with sqlite3.connect(str(db_path)) as conn:
            before = int(conn.execute("SELECT COUNT(*) FROM fleet_unit WHERE id = ?", (unit_id,)).fetchone()[0])
        _assert_true(before == 1, "manual unit missing before follow-up validate")

        state = service.validate()
        _assert_true(bool(state.get("ok")), f"follow-up validate failed: {state}")

        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute(
                "SELECT id, source FROM fleet_unit WHERE id = ?",
                (unit_id,),
            ).fetchone()

        _assert_true(row is not None, "manual unit was removed during follow-up validate")
        _assert_true(str(row[1] or "").strip().lower() == "manual", "manual unit source changed unexpectedly")
        service = None

    print("asset_intel_manual_unit_persistence_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
