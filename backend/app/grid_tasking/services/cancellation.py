from datetime import datetime, timezone

from ..db.models import AuditEvent, Campaign, CellOrder, Operation
from ..domain.status import is_active_collection, operational_status


def cancelable_orders_for_operation(db, operation: Operation) -> list[CellOrder]:
    query = db.query(CellOrder).join(CellOrder.cell).filter(CellOrder.remote_order_id.is_not(None))
    if operation.cell_order_id:
        order = db.get(CellOrder, operation.cell_order_id)
        orders = [order] if order else []
    elif operation.cell_id:
        orders = [order for order in query.all() if order.cell_id == operation.cell_id]
    elif operation.campaign_id:
        orders = [order for order in query.all() if order.cell.plan.campaign_id == operation.campaign_id]
    else:
        orders = []
    return [order for order in orders if is_active_collection(order.remote_rollup_status)]


def execute_cancellation(operation_id: str, client: SatellogicClient) -> None:
    db = SessionLocal()
    operation = db.get(Operation, operation_id)
    try:
        operation.status = "running"
        operation.started_at = datetime.now(timezone.utc)
        orders = cancelable_orders_for_operation(db, operation)
        operation.progress_total = len(orders)
        db.commit()
        failures = []
        for index, order in enumerate(orders, 1):
            db.refresh(operation)
            if operation.status == "cancel_requested":
                break
            try:
                response = client.cancel_order(order.cell.plan.campaign.contract_id, order.remote_order_id)
                order.remote_rollup_status = "canceled"
                order.remote_status = response.get("status") or response.get("properties", {}).get("status")
                order.latest_event = "OrderCancellationRequested"
                order.last_sync_error = None
                active = next((d.disposition for d in order.cell.dispositions if d.active), None)
                order.cell.operational_status = operational_status(
                    [cycle.remote_rollup_status for cycle in order.cell.orders], active
                )
                db.add(
                    AuditEvent(
                        campaign_id=order.cell.plan.campaign_id,
                        cell_id=order.cell_id,
                        event_type="remote_order_cancel_requested",
                        details={"order_name": order.order_name, "remote_order_id": order.remote_order_id},
                    )
                )
            except SatellogicError as exc:
                failures.append(order.order_name)
                order.last_sync_error = str(exc)
            operation.progress_current = index
            db.commit()
        if operation.campaign_id:
            campaign = db.get(Campaign, operation.campaign_id)
            remaining_active = any(
                is_active_collection(order.remote_rollup_status)
                for plan in campaign.plans
                for cell in plan.cells
                for order in cell.orders
            )
            if not remaining_active and campaign.state == "active":
                campaign.state = "plan_committed"
        operation.status = "failed" if failures else "succeeded"
        operation.error = f"Cancellation failed for {len(failures)} order(s): {', '.join(failures[:5])}" if failures else None
        operation.completed_at = datetime.now(timezone.utc)
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
