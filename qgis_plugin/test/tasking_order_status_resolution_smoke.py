#!/usr/bin/env python3
"""Smoke checks for tasking order status resolution rules."""

from __future__ import annotations

from pathlib import Path
import sys


def _repo_plugin_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected={expected!r} actual={actual!r}")


class _FakeSatClient:
    def __init__(self, deliverables_by_order: dict[str, dict]):
        self._deliverables_by_order = {
            str(key): dict(value or {}) for key, value in (deliverables_by_order or {}).items()
        }

    def list_order_deliverables(self, order_id: str, contract_id: str | None = None) -> dict:
        _ = contract_id
        return dict(self._deliverables_by_order.get(str(order_id), {"results": []}))


def main() -> int:
    plugin_root = _repo_plugin_root()
    sys.path.insert(0, str(plugin_root))

    from image_mate_qgis_plugin.services.source_service import SourceService  # noqa: PLC0415

    service = SourceService.__new__(SourceService)
    fake_client = _FakeSatClient(
        {
            "ord-completed": {"results": [{"status": "DELIVERED"}]},
            "ord-failed-empty": {"results": []},
            "ord-failed-explicit": {"results": [{"status": "FAILED"}]},
        }
    )
    service._tasking_client = lambda: fake_client
    service._normalize_contract_candidate = lambda value: str(value or "").strip()
    service.default_contract_id = lambda: "contract-test"

    status_from_report = service.resolve_tasking_order_status(
        order={
            "id": "ord-report",
            "status": "closed",
            "lifecycle_status": "closed",
            "status_report": {"status": "Completed"},
        },
        order_id="ord-report",
        contract_id="contract-test",
    )
    _assert_equal(status_from_report, "Completed", "status_report_priority")

    completed = service.resolve_tasking_order_status(
        order={
            "id": "ord-completed",
            "status": "closed",
            "lifecycle_status": "closed",
            "status_report": None,
        },
        order_id="ord-completed",
        contract_id="contract-test",
    )
    _assert_equal(completed, "Completed", "closed_with_deliverable")

    failed_empty = service.resolve_tasking_order_status(
        order={
            "id": "ord-failed-empty",
            "status": "closed",
            "lifecycle_status": "closed",
            "status_report": None,
        },
        order_id="ord-failed-empty",
        contract_id="contract-test",
    )
    _assert_equal(failed_empty, "Failed", "closed_no_deliverables")

    failed_explicit = service.resolve_tasking_order_status(
        order={
            "id": "ord-failed-explicit",
            "status": "closed",
            "lifecycle_status": "closed",
            "status_report": None,
        },
        order_id="ord-failed-explicit",
        contract_id="contract-test",
    )
    _assert_equal(failed_explicit, "Failed", "closed_failed_deliverable")

    in_progress = service.resolve_tasking_order_status(
        order={
            "id": "ord-open",
            "status": "in_progress",
            "lifecycle_status": "in_progress",
            "status_report": None,
        },
        order_id="ord-open",
        contract_id="contract-test",
    )
    _assert_equal(in_progress, "in_progress", "non_closed_passthrough")

    print("tasking_order_status_resolution_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
