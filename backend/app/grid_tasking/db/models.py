import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def uid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Campaign(Base, TimestampMixin):
    __tablename__ = "campaigns"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    campaign_id: Mapped[str] = mapped_column(String(64))
    campaign_id_normalized: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    state: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    contract_id: Mapped[str | None] = mapped_column(String(80))
    project_name: Mapped[str] = mapped_column(String(160))
    order_prefix: Mapped[str] = mapped_column(String(100))
    aoi_geojson: Mapped[dict] = mapped_column(JSON)
    archive_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    archive_parameters: Mapped[dict | None] = mapped_column(JSON)
    archive_coverage_geojson: Mapped[dict | None] = mapped_column(JSON)
    original_filename: Mapped[str] = mapped_column(String(255))
    aoi_sha256: Mapped[str] = mapped_column(String(64))
    active_plan_id: Mapped[str | None] = mapped_column(String(36))
    plans: Mapped[list["PlanRevision"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )


class PlanRevision(Base, TimestampMixin):
    __tablename__ = "plan_revisions"
    __table_args__ = (UniqueConstraint("campaign_id", "revision", name="uq_campaign_revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20), default="active")
    parameters: Mapped[dict] = mapped_column(JSON)
    utm_epsg: Mapped[int] = mapped_column(Integer)
    total_area_km2: Mapped[float] = mapped_column(Float)
    discarded_count: Mapped[int] = mapped_column(Integer, default=0)
    discarded_area_km2: Mapped[float] = mapped_column(Float, default=0)
    campaign: Mapped[Campaign] = relationship(back_populates="plans")
    cells: Mapped[list["GridCell"]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class GridCell(Base, TimestampMixin):
    __tablename__ = "grid_cells"
    __table_args__ = (UniqueConstraint("plan_id", "row", "col", name="uq_plan_cell"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plan_revisions.id"), index=True)
    row: Mapped[int] = mapped_column(Integer)
    col: Mapped[int] = mapped_column(Integer)
    geometry_geojson: Mapped[dict] = mapped_column(JSON)
    original_geometry_geojson: Mapped[dict | None] = mapped_column(JSON)
    fixed_geometry_geojson: Mapped[dict | None] = mapped_column(JSON)
    area_km2: Mapped[float] = mapped_column(Float)
    base_order_name: Mapped[str] = mapped_column(String(180), unique=True)
    operational_status: Mapped[str] = mapped_column(String(32), default="planned", index=True)
    submittable: Mapped[bool] = mapped_column(Boolean, default=True)
    warning: Mapped[str | None] = mapped_column(Text)
    plan: Mapped[PlanRevision] = relationship(back_populates="cells")
    orders: Mapped[list["CellOrder"]] = relationship(back_populates="cell", cascade="all, delete-orphan")
    dispositions: Mapped[list["CellDisposition"]] = relationship(
        back_populates="cell", cascade="all, delete-orphan"
    )


class CellOrder(Base, TimestampMixin):
    __tablename__ = "cell_orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    cell_id: Mapped[str] = mapped_column(ForeignKey("grid_cells.id"), index=True)
    cycle: Mapped[int] = mapped_column(Integer)
    action_type: Mapped[str] = mapped_column(String(20))
    parent_order_id: Mapped[str | None] = mapped_column(ForeignKey("cell_orders.id"))
    order_name: Mapped[str] = mapped_column(String(200), unique=True)
    payload: Mapped[dict] = mapped_column(JSON)
    parameters: Mapped[dict] = mapped_column(JSON)
    start: Mapped[str] = mapped_column(String(40))
    end: Mapped[str] = mapped_column(String(40))
    remote_order_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    remote_status: Mapped[str | None] = mapped_column(String(40))
    remote_rollup_status: Mapped[str] = mapped_column(String(40), default="planned")
    latest_event: Mapped[str | None] = mapped_column(String(100))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_error: Mapped[str | None] = mapped_column(Text)
    cell: Mapped[GridCell] = relationship(back_populates="orders")
    attempts: Mapped[list["SubmissionAttempt"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    events: Mapped[list["OrderEvent"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    captures: Mapped[list["Capture"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    deliverables: Mapped[list["Deliverable"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class SubmissionAttempt(Base):
    __tablename__ = "submission_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    cell_order_id: Mapped[str] = mapped_column(ForeignKey("cell_orders.id"), index=True)
    attempt: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(30), default="started")
    http_status: Mapped[int | None] = mapped_column(Integer)
    response: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    order: Mapped[CellOrder] = relationship(back_populates="attempts")


class OrderEvent(Base):
    __tablename__ = "order_events"
    __table_args__ = (UniqueConstraint("cell_order_id", "remote_id", name="uq_order_event"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    cell_order_id: Mapped[str] = mapped_column(ForeignKey("cell_orders.id"), index=True)
    remote_id: Mapped[str] = mapped_column(String(100))
    event_type: Mapped[str] = mapped_column(String(100))
    timestamp: Mapped[str | None] = mapped_column(String(50))
    message: Mapped[str | None] = mapped_column(Text)
    source: Mapped[dict] = mapped_column(JSON)
    order: Mapped[CellOrder] = relationship(back_populates="events")


class Capture(Base):
    __tablename__ = "captures"
    __table_args__ = (UniqueConstraint("cell_order_id", "remote_id", name="uq_capture"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    cell_order_id: Mapped[str] = mapped_column(ForeignKey("cell_orders.id"), index=True)
    remote_id: Mapped[str] = mapped_column(String(100))
    status: Mapped[str | None] = mapped_column(String(40))
    source: Mapped[dict] = mapped_column(JSON)
    order: Mapped[CellOrder] = relationship(back_populates="captures")


class Deliverable(Base):
    __tablename__ = "deliverables"
    __table_args__ = (UniqueConstraint("cell_order_id", "remote_id", name="uq_deliverable"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    cell_order_id: Mapped[str] = mapped_column(ForeignKey("cell_orders.id"), index=True)
    remote_id: Mapped[str] = mapped_column(String(100))
    status: Mapped[str | None] = mapped_column(String(40))
    source: Mapped[dict] = mapped_column(JSON)
    order: Mapped[CellOrder] = relationship(back_populates="deliverables")


class CellDisposition(Base):
    __tablename__ = "cell_dispositions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    cell_id: Mapped[str] = mapped_column(ForeignKey("grid_cells.id"), index=True)
    cell_order_id: Mapped[str | None] = mapped_column(ForeignKey("cell_orders.id"))
    disposition: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    cell: Mapped[GridCell] = relationship(back_populates="dispositions")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    campaign_id: Mapped[str | None] = mapped_column(ForeignKey("campaigns.id"), index=True)
    cell_id: Mapped[str | None] = mapped_column(ForeignKey("grid_cells.id"))
    event_type: Mapped[str] = mapped_column(String(80))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Operation(Base, TimestampMixin):
    __tablename__ = "operations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    operation_type: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    campaign_id: Mapped[str | None] = mapped_column(ForeignKey("campaigns.id"), index=True)
    cell_id: Mapped[str | None] = mapped_column(ForeignKey("grid_cells.id"))
    cell_order_id: Mapped[str | None] = mapped_column(ForeignKey("cell_orders.id"))
    progress_current: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str] = mapped_column(String(36), default=uid)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
