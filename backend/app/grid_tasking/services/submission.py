from datetime import datetime, timezone

from shapely.geometry import shape

from app.db.models import (
    AuditEvent,
    Campaign,
    CellOrder,
    GridCell,
    Operation,
    PlanRevision,
    SubmissionAttempt,
)
from app.db.session import SessionLocal
from app.domain.schemas import CampaignParameters
from app.domain.status import is_active_collection
from app.services.cell_actions import create_successor
from app.services.coverage import polygon_parts, remaining_cell_geometry
from app.services.planning import PlannedCell, build_order_feature
from app.services.satellogic import SatellogicClient, SatellogicError
from app.tasking_names import normalize_tasking_name


def _remote_id(body: dict) -> str | None:
    return body.get("properties", {}).get("order_id") or body.get("order_id")


def _matches_expected(remote: dict, expected: dict) -> bool:
    remote_props = remote.get("properties", {})
    expected_props = expected.get("properties", {})
    try:
        geometry_matches = shape(remote["geometry"]).equals(shape(expected["geometry"]))
    except Exception:
        geometry_matches = False
    return (
        remote_props.get("order_name") == expected_props.get("order_name")
        and remote_props.get("sku") == expected_props.get("sku")
        and geometry_matches
    )


def order_has_active_collection(order: CellOrder | None) -> bool:
    return bool(order and is_active_collection(order.remote_rollup_status))


def cell_has_active_collection(cell: GridCell) -> bool:
    return any(order_has_active_collection(order) for order in cell.orders)


def _new_initial_order(campaign: Campaign, cell: GridCell, params: CampaignParameters) -> CellOrder:
    planned = PlannedCell(
        cell.row,
        cell.col,
        type("Geometry", (), {"__geo_interface__": cell.geometry_geojson})(),
        cell.area_km2,
    )
    payload = build_order_feature(planned, params, campaign.project_name, cell.base_order_name)
    order = CellOrder(
        cycle=0,
        action_type="initial",
        order_name=cell.base_order_name,
        payload=payload,
        parameters=payload["properties"]["parameters"],
        start=payload["properties"]["parameters"]["start"],
        end=payload["properties"]["parameters"]["end"],
    )
    cell.orders.append(order)
    return order


def _geometry_order(
    campaign: Campaign,
    cell: GridCell,
    params: CampaignParameters,
    geometry,
    order_name: str,
    cycle: int,
    action_type: str,
    parent_order_id: str | None = None,
) -> CellOrder:
    planned = PlannedCell(
        cell.row,
        cell.col,
        type("Geometry", (), {"__geo_interface__": geometry.__geo_interface__})(),
        0,
    )
    final_order_name = normalize_tasking_name(order_name)
    payload = build_order_feature(planned, params, campaign.project_name, final_order_name)
    return CellOrder(
        cycle=cycle,
        action_type=action_type,
        parent_order_id=parent_order_id,
        order_name=final_order_name,
        payload=payload,
        parameters=payload["properties"]["parameters"],
        start=payload["properties"]["parameters"]["start"],
        end=payload["properties"]["parameters"]["end"],
    )


def _next_remaining_name(cell: GridCell, index: int) -> str:
    existing = {order.order_name for order in cell.orders}
    if not existing and index == 0:
        return normalize_tasking_name(cell.base_order_name)
    suffix = index + 1
    while normalize_tasking_name(f"{cell.base_order_name}_rem{suffix:02d}") in existing:
        suffix += 1
    return normalize_tasking_name(f"{cell.base_order_name}_rem{suffix:02d}")


def prepare_remaining_task_orders(db, campaign: Campaign, cell: GridCell) -> list[CellOrder]:
    if cell_has_active_collection(cell):
        return []
    pending = [order for order in cell.orders if not order.remote_order_id]
    if pending:
        if all(order.action_type == "remaining" for order in pending):
            return pending
        raise ValueError("This cell has an unsubmitted full-cell task. Submit or remove it before tasking remaining AOI.")
    plan = db.get(PlanRevision, campaign.active_plan_id)
    if not plan:
        raise ValueError("Campaign has no active plan")
    params = CampaignParameters.model_validate(plan.parameters)
    remaining = remaining_cell_geometry(cell, campaign, plan)
    parts = [part for part in polygon_parts(remaining) if not part.is_empty and part.area > 0]
    if not parts:
        raise ValueError("This cell has no uncovered AOI remaining to task.")

    parent = cell.orders[-1] if cell.orders else None
    cycle = max((order.cycle for order in cell.orders), default=-1) + 1
    orders = []
    for index, part in enumerate(parts):
        order = _geometry_order(
            campaign,
            cell,
            params,
            part,
            _next_remaining_name(cell, index),
            cycle + index,
            "remaining",
            parent.id if parent else None,
        )
        cell.orders.append(order)
        orders.append(order)
    db.flush()
    return orders


def prepare_cell_task_order(db, campaign: Campaign, cell: GridCell) -> CellOrder | None:
    if not cell.submittable or cell_has_active_collection(cell):
        return None
    plan = db.get(PlanRevision, campaign.active_plan_id)
    if not plan:
        raise ValueError("Campaign has no active plan")
    params = CampaignParameters.model_validate(plan.parameters)
    latest = cell.orders[-1] if cell.orders else None
    if latest and not latest.remote_order_id:
        return latest
    if latest:
        return create_successor(db, cell, "retask")
    order = _new_initial_order(campaign, cell, params)
    db.flush()
    return order


def prepare_initial_orders(db, campaign: Campaign) -> list[CellOrder]:
    plan = db.get(PlanRevision, campaign.active_plan_id)
    if not plan:
        raise ValueError("Campaign has no active plan")
    pending = []
    for cell in plan.cells:
        order = prepare_cell_task_order(db, campaign, cell)
        if order:
            pending.append(order)
    db.flush()
    return pending


def execute_submission(operation_id: str, client: SatellogicClient) -> None:
    db = SessionLocal()
    try:
        operation = db.get(Operation, operation_id)
        campaign = db.get(Campaign, operation.campaign_id)
        operation.status = "running"
        operation.started_at = datetime.now(timezone.utc)
        orders = (
            prepare_initial_orders(db, campaign)
            if operation.operation_type == "submit_campaign"
            else [db.get(CellOrder, operation.cell_order_id)]
        )
        operation.progress_total = len(orders)
        db.commit()
        for index, order in enumerate(orders, 1):
            db.refresh(operation)
            if operation.status == "cancel_requested":
                break
            attempt = SubmissionAttempt(
                cell_order_id=order.id,
                attempt=len(order.attempts) + 1,
                outcome="started",
            )
            db.add(attempt)
            db.commit()
            try:
                found = client.find_order(campaign.contract_id, order.order_name)
                if len(found) == 1:
                    body = found[0]
                    if not _matches_expected(body, order.payload):
                        raise SatellogicError(
                            "A remote order uses this name but does not match the planned geometry/product"
                        )
                    attempt.outcome = "reconciled"
                elif len(found) > 1:
                    raise SatellogicError("Multiple remote orders share this order name")
                else:
                    body = client.submit_order(campaign.contract_id, order.payload)
                    attempt.outcome = "succeeded"
                order.remote_order_id = _remote_id(body)
                order.remote_status = body.get("properties", {}).get("status")
                order.remote_rollup_status = "submitted"
                order.cell.operational_status = "submitted"
                attempt.response = body
                campaign.state = "active"
            except SatellogicError as exc:
                attempt.outcome = "ambiguous" if exc.ambiguous else "failed"
                attempt.http_status = exc.status_code
                attempt.error = str(exc)
                order.last_sync_error = str(exc)
                order.cell.operational_status = "failed"
            attempt.completed_at = datetime.now(timezone.utc)
            operation.progress_current = index
            db.commit()
        operation.status = "succeeded" if operation.status != "cancel_requested" else "cancelled"
        operation.completed_at = datetime.now(timezone.utc)
        db.add(
            AuditEvent(
                campaign_id=campaign.id,
                event_type="submission_completed",
                details={"operation": operation.id},
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        operation = db.get(Operation, operation_id)
        if operation:
            operation.status = "failed"
            operation.error = str(exc)
            operation.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()
