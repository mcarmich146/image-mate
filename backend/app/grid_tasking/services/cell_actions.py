from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..db.models import AuditEvent, CellDisposition, CellOrder, GridCell
from ..domain.status import MANUAL_STAGE_DISPOSITIONS


def set_disposition(db: Session, cell: GridCell, disposition: str, reason: str) -> CellDisposition:
    if disposition not in MANUAL_STAGE_DISPOSITIONS | {"accepted_delivered", "cleared"}:
        raise ValueError("Invalid disposition")
    for previous in cell.dispositions:
        previous.active = False
    model = CellDisposition(
        cell_order_id=cell.orders[-1].id if cell.orders else None,
        disposition=disposition,
        reason=reason.strip(),
        active=disposition != "cleared",
    )
    cell.dispositions.append(model)
    if disposition in MANUAL_STAGE_DISPOSITIONS:
        cell.operational_status = disposition.removeprefix("manual_")
    elif disposition == "accepted_delivered":
        cell.operational_status = "delivered"
    else:
        cell.operational_status = cell.orders[-1].remote_rollup_status if cell.orders else "planned"
    db.add(
        AuditEvent(
            campaign_id=cell.plan.campaign_id,
            cell_id=cell.id,
            event_type="cell_disposition_changed",
            details={"disposition": disposition, "reason": reason.strip()},
        )
    )
    db.commit()
    return model


def create_successor(
    db: Session,
    cell: GridCell,
    action_type: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> CellOrder:
    if action_type not in {"retask", "extension"}:
        raise ValueError("Invalid successor type")
    parent = cell.orders[-1] if cell.orders else None
    if not parent:
        raise ValueError("Submit the initial order before creating a successor")
    now = datetime.now(timezone.utc)
    if action_type == "retask":
        start = start or now
        end = end or start + timedelta(days=60)
        suffix = "rt"
    else:
        parent_end = datetime.fromisoformat(parent.end.replace("Z", "+00:00"))
        start = start or max(now, parent_end + timedelta(seconds=1))
        end = end or start + timedelta(days=60)
        suffix = "ext"
    if end <= start:
        raise ValueError("Successor end must be after start")
    number = 1 + sum(1 for order in cell.orders if order.action_type == action_type)
    order_name = f"{cell.base_order_name}_{suffix}{number:02d}"
    payload = {
        **parent.payload,
        "properties": {
            **parent.payload["properties"],
            "order_name": order_name,
            "parameters": {
                **parent.payload["properties"]["parameters"],
                "start": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "end": end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        },
    }
    order = CellOrder(
        cycle=max(o.cycle for o in cell.orders) + 1,
        action_type=action_type,
        parent_order_id=parent.id,
        order_name=order_name,
        payload=payload,
        parameters=payload["properties"]["parameters"],
        start=payload["properties"]["parameters"]["start"],
        end=payload["properties"]["parameters"]["end"],
    )
    cell.orders.append(order)
    db.flush()
    db.add(
        AuditEvent(
            campaign_id=cell.plan.campaign_id,
            cell_id=cell.id,
            event_type=f"{action_type}_draft_created",
            details={"order_name": order_name, "parent": parent.order_name},
        )
    )
    db.commit()
    return order
