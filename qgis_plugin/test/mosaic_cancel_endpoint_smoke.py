#!/usr/bin/env python3
"""Smoke checks for Mosaic cancel endpoint selection and fallback."""

from __future__ import annotations

from pathlib import Path
import sys


def _repo_plugin_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected={expected!r} actual={actual!r}")


class _FakeSatClient:
    def __init__(self):
        self.cancel_task_calls = []
        self.cancel_order_calls = []
        self.order_with_task = {
            "type": "Feature",
            "properties": {
                "order_id": "013163",
                "status": "received",
                "parameters": {"task_id": 347586},
            },
        }
        self.order_without_task = {
            "type": "Feature",
            "properties": {
                "order_id": "013164",
                "status": "received",
                "parameters": {},
            },
        }

    def get_order(self, order_id: str, contract_id: str | None = None) -> dict:
        _ = contract_id
        if str(order_id) == "013163":
            return dict(self.order_with_task)
        return dict(self.order_without_task)

    def cancel_task(self, task_id: str | int, contract_id: str | None = None) -> dict:
        self.cancel_task_calls.append((str(task_id), str(contract_id or "")))
        return {"task_id": int(task_id), "status": "canceled"}

    def cancel_order(self, order_id: str, contract_id: str | None = None) -> dict:
        self.cancel_order_calls.append((str(order_id), str(contract_id or "")))
        return {"id": str(order_id), "status": "cancelled"}


def main() -> int:
    plugin_root = _repo_plugin_root()
    sys.path.insert(0, str(plugin_root))

    from image_mate_qgis_plugin.services.source_service import SourceService  # noqa: PLC0415

    client_text = (plugin_root / "image_mate_qgis_plugin" / "clients" / "satellogic_client.py").read_text(
        encoding="utf-8"
    )
    if "/tasking/tasks/" not in client_text or "/cancel/" not in client_text or "requests.patch(" not in client_text:
        raise AssertionError("client_cancel_task_endpoint_missing")
    if "api_url" not in client_text:
        raise AssertionError("client_cancel_task_api_url_query_missing")

    fake_client = _FakeSatClient()
    service = SourceService.__new__(SourceService)
    service._tasking_client = lambda: fake_client
    service._normalize_contract_candidate = lambda value: str(value or "").strip()
    service.default_contract_id = lambda: "cont.eac744cc-2afe-4012-9621-35623feeb7a7"

    result_task = service.cancel_tasking_order("013163", contract_id="cont.eac744cc-2afe-4012-9621-35623feeb7a7")
    order_task = result_task.get("order") if isinstance(result_task, dict) else {}
    _assert_equal(bool(order_task), True, "task_cancel_order_payload_present")
    _assert_equal(str(order_task.get("status") or ""), "canceled", "task_cancel_status")
    _assert_equal(str(order_task.get("task_id") or ""), "347586", "task_cancel_task_id")
    _assert_equal(len(fake_client.cancel_task_calls), 1, "task_cancel_called_once")
    _assert_equal(len(fake_client.cancel_order_calls), 0, "legacy_cancel_not_called_when_task_present")

    result_fallback = service.cancel_tasking_order("013164", contract_id="cont.eac744cc-2afe-4012-9621-35623feeb7a7")
    order_fallback = result_fallback.get("order") if isinstance(result_fallback, dict) else {}
    _assert_equal(str(order_fallback.get("status") or ""), "cancelled", "legacy_cancel_status")
    _assert_equal(len(fake_client.cancel_order_calls), 1, "legacy_cancel_called_when_no_task_id")

    print("mosaic_cancel_endpoint_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
