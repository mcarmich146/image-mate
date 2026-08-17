FAILURE_EVENTS = {
    "OrderAnalysisFailed",
    "OrderForceClosed",
}
CANCELLATION_EVENTS = {"OrderCancellationAccepted"}
ACTIVE_COLLECTION_STATUSES = {"submitted", "active", "collecting", "processing", "acquired"}
OPERATIONAL_STAGES = (
    "planned",
    "submitted",
    "active",
    "collecting",
    "processing",
    "acquired",
    "delivered",
    "failed",
    "canceled",
    "closed",
)
MANUAL_STAGE_DISPOSITIONS = {f"manual_{stage}" for stage in OPERATIONAL_STAGES}
DELIVERED_STATUSES = {"delivered", "complete", "completed"}
FAILED_DELIVERABLE_STATUSES = {"failed", "not_delivered", "not delivered", "rejected", "error"}


def is_active_collection(status: str | None) -> bool:
    return status in ACTIVE_COLLECTION_STATUSES


def remote_rollup(
    order_status: str | None,
    event_types: list[str],
    capture_statuses: list[str],
    deliverable_statuses: list[str],
) -> str:
    lowered_deliverables = {str(x).lower() for x in deliverable_statuses}
    lowered_captures = {str(x).lower() for x in capture_statuses}
    if CANCELLATION_EVENTS.intersection(event_types):
        return "canceled"
    if (
        FAILURE_EVENTS.intersection(event_types)
        or "failed" in lowered_captures
        or FAILED_DELIVERABLE_STATUSES.intersection(lowered_deliverables)
    ):
        return "failed"
    # An order can produce several deliverables for several image strips. One
    # successful strip is not enough to declare the complete grid cell delivered.
    if lowered_deliverables and lowered_deliverables.issubset(DELIVERED_STATUSES):
        return "delivered"
    if lowered_deliverables.intersection({"processing", "queued"}):
        return "processing"
    if "acquired" in lowered_captures:
        return "acquired"
    if lowered_captures.intersection({"collecting", "queued", "scheduled"}):
        return "collecting"
    if order_status == "in_progress":
        return "active"
    if order_status in {"received", "submitted"}:
        return "submitted"
    if order_status == "closed":
        return "closed"
    return "planned"


def operational_status(remote_statuses: list[str], disposition: str | None) -> str:
    if disposition in MANUAL_STAGE_DISPOSITIONS:
        return disposition.removeprefix("manual_")
    if disposition in {"manual_delivered", "accepted_delivered"}:
        return "delivered"
    return remote_statuses[-1] if remote_statuses else "planned"
