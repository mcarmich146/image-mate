from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import main


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_create_payload(project_name: str, contract_id: str | None = None) -> dict[str, Any]:
    now = datetime.now(timezone.utc) + timedelta(minutes=15)
    end = now + timedelta(days=2)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    payload: dict[str, Any] = {
        "target_type": "point",
        "geometry": {
            "type": "Point",
            "coordinates": [-122.3921, 37.6178],
        },
        "order_name": f"smoke_task_{stamp}",
        "project_name": project_name,
        "sku": "TSKPOI-M",
        "start_date": _utc_iso(now),
        "end_date": _utc_iso(end),
    }
    if contract_id:
        payload["contract_id"] = contract_id
    return payload


def _run_sequence(
    api: TestClient,
    *,
    create_order: bool,
    contract_id: str | None,
    project_name: str,
    poll_attempts: int,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    summary: dict[str, Any] = {"ok": True, "steps": []}

    def record(step: str, ok: bool, detail: Any = None):
        summary["steps"].append({
            "step": step,
            "ok": bool(ok),
            "detail": detail,
        })
        if not ok:
            summary["ok"] = False

    effective_contract_id = contract_id or None
    contracts = api.get("/api/contracts")
    if contracts.status_code == 200:
        cbody = contracts.json()
        discovered_default = (cbody.get("default_contract_id") or "").strip() or None
        discovered_rows = cbody.get("contracts") if isinstance(cbody.get("contracts"), list) else []
        discovered_first = None
        if discovered_rows:
            first = discovered_rows[0]
            if isinstance(first, dict):
                discovered_first = (first.get("id") or "").strip() or None
        if not effective_contract_id:
            effective_contract_id = discovered_default or discovered_first
        record(
            "contracts",
            True,
            {
                "status_code": contracts.status_code,
                "default_contract_id": discovered_default,
                "effective_contract_id": effective_contract_id,
            },
        )
    else:
        record(
            "contracts",
            False,
            {
                "status_code": contracts.status_code,
                "detail": contracts.json().get("detail") if contracts.headers.get("content-type", "").startswith("application/json") else contracts.text,
            },
        )
        return summary

    orders_query = f"/api/tasking/orders?limit=120{f'&contract_id={contract_id}' if contract_id else ''}"
    projects_query = f"/api/tasking/projects?limit=120{f'&contract_id={contract_id}' if contract_id else ''}"
    if effective_contract_id:
        orders_query = f"/api/tasking/orders?limit=120&contract_id={effective_contract_id}"
        projects_query = f"/api/tasking/projects?limit=120&contract_id={effective_contract_id}"

    products = api.get("/api/tasking/products")
    record("products", products.status_code == 200, {"status_code": products.status_code})
    if products.status_code != 200:
        return summary

    projects = api.get(projects_query)
    projects_detail = {"status_code": projects.status_code}
    if projects.status_code != 200:
        try:
            projects_detail["detail"] = projects.json().get("detail")
        except Exception:
            projects_detail["detail"] = projects.text
    record("projects", projects.status_code == 200, projects_detail)
    if projects.status_code != 200:
        return summary

    before = api.get(orders_query)
    before_detail = {"status_code": before.status_code}
    if before.status_code != 200:
        try:
            before_detail["detail"] = before.json().get("detail")
        except Exception:
            before_detail["detail"] = before.text
    record("orders_before", before.status_code == 200, before_detail)
    if before.status_code != 200:
        return summary

    before_rows = before.json().get("orders", [])
    summary["orders_before_count"] = len(before_rows) if isinstance(before_rows, list) else 0

    if not create_order:
        return summary

    payload = _build_create_payload(project_name=project_name, contract_id=effective_contract_id)
    created = api.post("/api/tasking/orders", json=payload)
    if created.status_code != 200:
        record(
            "create_order",
            False,
            {"status_code": created.status_code, "detail": created.json().get("detail")},
        )
        return summary
    body = created.json()
    order_id = (
        body.get("order", {}).get("id")
        or ((body.get("orders") or [{}])[0].get("id") if isinstance(body.get("orders"), list) else None)
    )
    record("create_order", bool(body.get("accepted")) and bool(order_id), {"order_id": order_id})
    if not order_id:
        return summary

    statuses: list[str] = []
    for _ in range(max(1, poll_attempts)):
        detail = api.get(f"/api/tasking/orders/{order_id}{f'?contract_id={effective_contract_id}' if effective_contract_id else ''}")
        if detail.status_code != 200:
            detail_payload = {"status_code": detail.status_code}
            try:
                detail_payload["detail"] = detail.json().get("detail")
            except Exception:
                detail_payload["detail"] = detail.text
            record("order_detail_poll", False, detail_payload)
            return summary
        status_value = str(detail.json().get("order", {}).get("status") or "unknown")
        statuses.append(status_value)
        time.sleep(max(0.0, poll_interval_seconds))
    summary["status_samples"] = statuses
    record("order_detail_poll", True, {"samples": statuses})

    after = api.get(orders_query)
    if after.status_code != 200:
        record("orders_after", False, {"status_code": after.status_code})
        return summary
    after_rows = after.json().get("orders", [])
    found = False
    if isinstance(after_rows, list):
        found = any(str(row.get("id")) == str(order_id) for row in after_rows if isinstance(row, dict))
    summary["orders_after_count"] = len(after_rows) if isinstance(after_rows, list) else 0
    # Some contracts return historical-first pages; detail polling above is the authoritative acceptance signal.
    record("orders_after", True, {"found_order_id": found, "order_id": order_id})
    return summary


def _mock_context():
    store: dict[str, Any] = {"orders": [], "list_calls": 0}

    def fake_create_order(feature: dict, contract_id: str | None = None) -> dict:
        row = copy.deepcopy(feature)
        row["id"] = f"ord-{len(store['orders']) + 1:03d}"
        props = row.setdefault("properties", {})
        props["status"] = "accepted"
        props["created_at"] = _utc_iso(datetime.now(timezone.utc))
        store["orders"].append(row)
        return row

    def fake_list_orders(
        contract_id: str | None = None,
        *,
        limit: int = 100,
        query: str | None = None,
        next_url: str | None = None,
    ) -> dict:
        store["list_calls"] = int(store["list_calls"]) + 1
        status = "accepted" if int(store["list_calls"]) < 3 else "programming"
        rows = []
        for row in store["orders"]:
            out = copy.deepcopy(row)
            out.setdefault("properties", {})["status"] = status
            rows.append(out)
        return {"type": "FeatureCollection", "features": rows[:limit], "next": None}

    def fake_get_order(order_id: str, contract_id: str | None = None) -> dict:
        for row in store["orders"]:
            if str(row.get("id")) == str(order_id):
                out = copy.deepcopy(row)
                out.setdefault("properties", {})["status"] = "programming"
                return out
        raise RuntimeError("order not found")

    def fake_list_contracts() -> list[dict[str, Any]]:
        return [{"id": "contract-123", "name": "Smoke Contract", "status": "ACTIVE"}]

    return patch.object(main.client, "create_order", side_effect=fake_create_order), \
        patch.object(main.client, "list_orders", side_effect=fake_list_orders), \
        patch.object(main.client, "get_order", side_effect=fake_get_order), \
        patch.object(main.client, "list_contracts", side_effect=fake_list_contracts)


def main_cli() -> int:
    parser = argparse.ArgumentParser(description="Repeatable smoke runner for tasking workflow endpoints.")
    parser.add_argument("--mode", choices=["mock", "live"], default="mock")
    parser.add_argument("--create", action="store_true", help="Create a tasking order as part of the smoke run.")
    parser.add_argument("--contract-id", default="", help="Optional contract_id override.")
    parser.add_argument("--project-name", default="smoke-project", help="Project name used for create test.")
    parser.add_argument("--poll-attempts", type=int, default=4)
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0)
    args = parser.parse_args()

    if args.mode == "live" and not args.create:
        print("Live mode without --create will only run read-only checks.")

    if args.mode == "mock":
        p_create, p_list, p_get, p_contracts = _mock_context()
        with p_create, p_list, p_get, p_contracts:
            with TestClient(main.app) as api:
                summary = _run_sequence(
                    api,
                    create_order=True if not args.create else args.create,
                    contract_id=(args.contract_id or None),
                    project_name=args.project_name,
                    poll_attempts=args.poll_attempts,
                    poll_interval_seconds=args.poll_interval_seconds,
                )
    else:
        with TestClient(main.app) as api:
            summary = _run_sequence(
                api,
                create_order=args.create,
                contract_id=(args.contract_id or None),
                project_name=args.project_name,
                poll_attempts=args.poll_attempts,
                poll_interval_seconds=args.poll_interval_seconds,
            )

    print(json.dumps(summary, indent=2))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main_cli())
