from datetime import datetime, timezone

from ..db.models import Capture, CellOrder, Deliverable, Operation, OrderEvent
from ..domain.status import operational_status, remote_rollup


def _items(body: dict) -> list[dict]:
    return body.get("results") or body.get("features") or []


def _entity_id(item: dict, names: tuple[str, ...]) -> str | None:
    props = item.get("properties", item)
    return next((str(props[name]) for name in names if props.get(name)), None)


def sync_order(db, order: CellOrder, client: SatellogicClient, contract_id: str) -> None:
    try:
        details = client.order(contract_id, order.remote_order_id)
        events = _items(client.events(contract_id, order.remote_order_id))
        captures = _items(client.captures(contract_id, order.remote_order_id))
        deliverables = _items(client.deliverables(contract_id, order.remote_order_id))
        props = details.get("properties", details)
        order.remote_status = props.get("status")
        remote_parameters = props.get("parameters")
        if isinstance(remote_parameters, dict):
            order.parameters = remote_parameters
            order.start = remote_parameters.get("start", order.start)
            order.end = remote_parameters.get("end", order.end)
        for item in events:
            remote_id = _entity_id(item, ("id", "event_id"))
            if remote_id and not next((x for x in order.events if x.remote_id == remote_id), None):
                event_props = item.get("properties", item)
                order.events.append(
                    OrderEvent(
                        remote_id=remote_id,
                        event_type=event_props.get("type", "Unknown"),
                        timestamp=event_props.get("timestamp"),
                        message=event_props.get("message"),
                        source=item,
                    )
                )
        for item in captures:
            remote_id = _entity_id(item, ("capture_id", "id"))
            if not remote_id:
                continue
            model = next((x for x in order.captures if x.remote_id == remote_id), None)
            props = item.get("properties", item)
            if not model:
                model = Capture(remote_id=remote_id, source=item)
                order.captures.append(model)
            model.status = props.get("status") or props.get("state")
            model.source = item
        for item in deliverables:
            remote_id = _entity_id(item, ("deliverable_id", "id"))
            if not remote_id:
                continue
            model = next((x for x in order.deliverables if x.remote_id == remote_id), None)
            props = item.get("properties", item)
            if not model:
                model = Deliverable(remote_id=remote_id, source=item)
                order.deliverables.append(model)
            model.status = props.get("status") or props.get("state")
            model.source = item
        db.flush()
        event_types = [(item.get("properties", item)).get("type", "Unknown") for item in events]
        latest = max(
            events,
            key=lambda item: (item.get("properties", item)).get("timestamp", ""),
            default=None,
        )
        order.latest_event = (latest.get("properties", latest)).get("type") if latest else None
        order.remote_rollup_status = remote_rollup(
            order.remote_status,
            event_types,
            [
                (item.get("properties", item)).get("status")
                for item in captures
                if (item.get("properties", item)).get("status")
            ],
            [
                (item.get("properties", item)).get("status") or (item.get("properties", item)).get("state")
                for item in deliverables
                if (item.get("properties", item)).get("status") or (item.get("properties", item)).get("state")
            ],
        )
        active = next((d.disposition for d in order.cell.dispositions if d.active), None)
        order.cell.operational_status = operational_status(
            [cycle.remote_rollup_status for cycle in order.cell.orders], active
        )
        order.last_sync_at = datetime.now(timezone.utc)
        order.last_sync_error = None
    except Exception as exc:
        order.last_sync_error = str(exc)


def execute_sync(operation_id: str, client: SatellogicClient) -> None:
    db = SessionLocal()
    operation = db.get(Operation, operation_id)
    try:
        operation.status = "running"
        operation.started_at = datetime.now(timezone.utc)
        orders = db.query(CellOrder).join(CellOrder.cell).filter(CellOrder.remote_order_id.is_not(None)).all()
        if operation.campaign_id:
            orders = [o for o in orders if o.cell.plan.campaign_id == operation.campaign_id]
        operation.progress_total = len(orders)
        db.commit()
        for index, order in enumerate(orders, 1):
            sync_order(db, order, client, order.cell.plan.campaign.contract_id)
            operation.progress_current = index
            db.commit()
        operation.status = "succeeded"
        operation.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        db.rollback()
        operation = db.get(Operation, operation_id)
        operation.status = "failed"
        operation.error = str(exc)
        operation.completed_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()
