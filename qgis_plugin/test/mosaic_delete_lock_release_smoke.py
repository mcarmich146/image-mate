#!/usr/bin/env python3
"""Static smoke checks for Mosaic delete lock-release behavior."""

from __future__ import annotations

from pathlib import Path


def _assert_contains(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label}: missing snippet {needle!r}")


def _assert_ordered(text: str, first: str, second: str, label: str) -> None:
    idx_first = text.find(first)
    idx_second = text.find(second)
    if idx_first < 0 or idx_second < 0 or idx_first >= idx_second:
        raise AssertionError(f"{label}: expected {first!r} before {second!r}")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    store_text = (
        repo_root / "qgis_plugin" / "image_mate_qgis_plugin" / "services" / "mosaic_tracking_store.py"
    ).read_text(encoding="utf-8")
    storage_text = (
        repo_root / "qgis_plugin" / "image_mate_qgis_plugin" / "services" / "campaign_storage_service.py"
    ).read_text(encoding="utf-8")
    plugin_text = (repo_root / "qgis_plugin" / "image_mate_qgis_plugin" / "plugin.py").read_text(encoding="utf-8")

    _assert_contains(store_text, "@contextmanager", "store_contextmanager_decorator")
    _assert_contains(store_text, "conn.close()", "store_connection_close")

    _assert_contains(storage_text, "for attempt in range(attempt_count):", "delete_retry_loop")
    _assert_contains(storage_text, "int(winerror or 0) == 32", "delete_windows_lock_detection")
    _assert_contains(storage_text, "if callable(on_lock_retry):", "delete_retry_callback_hook")

    _assert_ordered(
        plugin_text,
        "self._clear_mosaic_tiling_layer()",
        "deleted = self.campaign_storage.delete_mosaic_project(",
        "plugin_releases_layers_before_delete",
    )
    _assert_contains(
        plugin_text,
        "self._release_mosaic_project_layers(",
        "plugin_project_layer_sweep_invoked",
    )
    _assert_contains(
        plugin_text,
        "layer.customProperty(\"image_mate/mosaic_project_id\")",
        "plugin_project_layer_sweep_custom_property",
    )
    _assert_ordered(
        plugin_text,
        "self._release_mosaic_project_layers(",
        "deleted = self.campaign_storage.delete_mosaic_project(",
        "plugin_sweep_runs_before_delete",
    )
    _assert_contains(
        plugin_text,
        "delete_lock_retry project=",
        "plugin_logs_lock_retries",
    )
    _assert_contains(
        plugin_text,
        "max_attempts=12",
        "plugin_extends_delete_retry_budget",
    )

    print("mosaic_delete_lock_release_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
