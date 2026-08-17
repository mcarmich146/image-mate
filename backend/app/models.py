from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator


class SearchRequest(BaseModel):
    geometry: dict[str, Any]
    start_date: str
    end_date: str
    source_id: str = "satellogic"
    collection_id: str = "l1d-sr"
    contract_id: str | None = None
    limit: int = 300
    max_cloud_cover: float | None = Field(default=40, ge=0, le=100)
    satellite_name: str | None = None
    min_gsd: float | None = Field(default=None, ge=0)
    max_gsd: float | None = Field(default=None, ge=0)


class SearchResultItem(BaseModel):
    id: str
    source_id: str | None = None
    collection: str | None = None
    datetime: str | None = None
    outcome_id: str | None = None
    satellite_name: str | None = None
    gsd: float | None = None
    cloud_cover: float | None = None
    valid_pixel_percent: float | None = None
    geometry: dict[str, Any]
    assets: dict[str, str]


class SearchResponse(BaseModel):
    count: int
    items: list[SearchResultItem]


class AnimationRequest(BaseModel):
    item_ids: list[str] = Field(default_factory=list)
    contract_id: str | None = None
    seconds_per_frame: float = Field(default=0.8, gt=0, le=10)
    max_frames: int = Field(default=30, ge=2, le=200)


class GeoAgentRequest(BaseModel):
    geometry: dict[str, Any]
    start_date: str
    end_date: str
    prompt: str
    latest_item_id: str | None = None
    source_id: str = "satellogic"
    collection_id: str = "l1d-sr"
    contract_id: str | None = None
    satellite_name: str | None = None
    min_gsd: float | None = Field(default=None, ge=0)
    max_gsd: float | None = Field(default=None, ge=0)
    max_frames: int = Field(default=12, ge=3, le=24)


class GeoAgentResponse(BaseModel):
    report_markdown: str
    latest_item_id: str | None = None
    frame_count: int = 0
    insights: list[dict[str, Any]] = Field(default_factory=list)


class AircraftDetectorRequest(BaseModel):
    """One L1D-SR image tile or one authenticated COG tile request."""

    image_base64: str | None = Field(default=None, description="Base64-encoded PNG/JPEG tile")
    source_url: str | None = Field(default=None, description="Satellogic COG source for a z/x/y tile")
    z: int | None = Field(default=None, ge=0, le=24)
    x: int | None = Field(default=None, ge=0)
    y: int | None = Field(default=None, ge=0)
    scale: int = Field(default=4, ge=1, le=4)
    tile_matrix_set: str = Field(default="WebMercatorQuad", max_length=64)
    source_id: str = Field(default="satellogic", max_length=64)
    collection_id: str = Field(default="l1d-sr", max_length=120)
    item_id: str | None = Field(default=None, max_length=240)
    asset_key: str = Field(default="visual", max_length=120)
    bounds: list[float] | None = Field(default=None, min_length=4, max_length=4)
    crs: str = Field(default="EPSG:4326", max_length=64)
    contract_id: str | None = Field(default=None, max_length=240)
    confidence: float | None = Field(default=None, ge=0.01, le=1.0)
    iou: float | None = Field(default=None, ge=0.01, le=1.0)
    max_detections: int | None = Field(default=None, ge=1, le=500)

    @model_validator(mode="after")
    def validate_input(self):
        has_image = bool(str(self.image_base64 or "").strip())
        has_cog = bool(str(self.source_url or "").strip()) or bool(str(self.item_id or "").strip())
        if not has_image and not has_cog:
            raise ValueError("Provide image_base64 or an item_id for a COG tile")
        if has_image and self.source_url:
            raise ValueError("Do not combine image_base64 with source_url")
        if not has_image and has_cog and (self.z is None or self.x is None or self.y is None):
            raise ValueError("COG input requires z, x, and y tile coordinates")
        return self


class AircraftLabAnnotationRequest(BaseModel):
    """One analyst label for a detector tile or a manually drawn polygon."""

    item_id: str = Field(min_length=1, max_length=240)
    source_id: Literal["satellogic"] = "satellogic"
    collection_id: str = Field(default="l1d-sr", max_length=120)
    asset_key: str = Field(default="visual", max_length=120)
    z: int = Field(ge=0, le=24)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    scale: int = Field(default=4, ge=1, le=4)
    bounds_wgs84: list[float] = Field(min_length=4, max_length=4)
    source_width_px: int = Field(gt=0, le=8192)
    source_height_px: int = Field(gt=0, le=8192)
    geometry_px: list[list[float]] = Field(min_length=4, max_length=64)
    label: Literal["plane", "helicopter", "background"]
    detection_id: str | None = Field(default=None, max_length=120)
    confidence: float | None = Field(default=None, ge=0, le=1)
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_aircraft_annotation(self):
        normalized_collection = str(self.collection_id or "").strip().lower().replace("_", "-")
        if normalized_collection != "l1d-sr":
            raise ValueError("Aircraft lab annotations accept only Satellogic l1d-sr tiles")
        if str(self.asset_key or "").strip().lower() not in {"visual", "visual_fullres", "visual-fullres"}:
            raise ValueError("Aircraft lab annotations require the visual L1D asset")
        west, south, east, north = [float(value) for value in self.bounds_wgs84]
        if not (west < east and south < north):
            raise ValueError("bounds_wgs84 must be [west, south, east, north]")
        if len(self.geometry_px) < 4:
            raise ValueError("geometry_px must contain at least four points")
        for point in self.geometry_px:
            if len(point) < 2:
                raise ValueError("each geometry_px point must contain x and y")
            x, y = float(point[0]), float(point[1])
            if not (0 <= x <= self.source_width_px and 0 <= y <= self.source_height_px):
                raise ValueError("geometry_px points must stay within the source tile")
        return self


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class AnimationSearchRequest(BaseModel):
    geometry: dict[str, Any]
    start_date: str
    end_date: str
    source_id: str = "satellogic"
    collection_id: str = "l1d-sr"
    contract_id: str | None = None
    max_cloud_cover: float | None = Field(default=40, ge=0, le=100)
    satellite_name: str | None = None
    min_gsd: float | None = Field(default=None, ge=0)
    max_gsd: float | None = Field(default=None, ge=0)
    max_frames: int = Field(default=20, ge=2, le=80)
    seconds_per_frame: float = Field(default=0.8, gt=0, le=10)


class Mp4AnimationTile(BaseModel):
    url: str
    geometry: dict[str, Any]
    item_id: str | None = None


class Mp4AnimationFrame(BaseModel):
    frame_id: str | None = None
    datetime: str | None = None
    tiles: list[Mp4AnimationTile] = Field(default_factory=list)


class Mp4AnimationJobRequest(BaseModel):
    frames: list[Mp4AnimationFrame] = Field(default_factory=list)
    viewport_geometry: dict[str, Any]
    contract_id: str | None = None
    seconds_per_frame: float = Field(default=0.8, gt=0, le=10)
    filename_prefix: str = Field(default="selected_extent_animation", max_length=80)


class DownloadAssetEntry(BaseModel):
    url: str
    filename: str | None = None
    item_id: str | None = None
    outcome_id: str | None = None


class DownloadBundleRequest(BaseModel):
    assets: list[DownloadAssetEntry] = Field(default_factory=list)
    contract_id: str | None = None
    bundle_name: str = "tiles_download"


class WorkflowDefinitionPayload(BaseModel):
    workflow_id: str
    version: str
    graph_json: dict[str, Any] = Field(default_factory=dict)
    default_params: dict[str, Any] = Field(default_factory=dict)


class RunCreateRequest(BaseModel):
    workflow_id: str | None = None
    workflow_version: str | None = None
    trigger_id: str | None = None
    idempotency_key: str | None = None
    inputs_payload: dict[str, Any] = Field(default_factory=dict)


class ScheduleCreateRequest(BaseModel):
    type: Literal["MANUAL", "CRON", "IMAGERY_ARRIVAL", "STACK_ARRIVAL"] = "MANUAL"
    workflow_id: str | None = None
    workflow_version: str | None = None
    scope: dict[str, Any] = Field(default_factory=dict)
    filters: dict[str, Any] = Field(default_factory=dict)
    batching: dict[str, Any] = Field(default_factory=dict)
    caps: dict[str, Any] = Field(default_factory=dict)
    subscription_id: str | None = None
    cron: str | None = None
    interval_seconds: int | None = Field(default=None, ge=0)
    enabled: bool = True


class SchedulePatchRequest(BaseModel):
    enabled: bool | None = None
    cron: str | None = None
    interval_seconds: int | None = Field(default=None, ge=0)
    scope: dict[str, Any] | None = None
    filters: dict[str, Any] | None = None
    batching: dict[str, Any] | None = None
    caps: dict[str, Any] | None = None
    subscription_id: str | None = None


class PoiSetCreateRequest(BaseModel):
    name: str = "poi_set"
    geometry: dict[str, Any] | None = None
    features: list[dict[str, Any]] = Field(default_factory=list)


class SubscriptionCreateRequest(BaseModel):
    geometry: dict[str, Any] | None = None
    poi_set_id: str | None = None
    matching_rules: dict[str, Any] = Field(default_factory=dict)
    filters: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class TaskingOrderCreateRequest(BaseModel):
    target_type: Literal["point", "area"]
    geometry: dict[str, Any]
    order_name: str = Field(min_length=1, max_length=120)
    project_name: str | None = Field(default=None, max_length=120)
    sku: str = Field(min_length=1, max_length=80)
    start_date: str = Field(min_length=1, max_length=80)
    end_date: str = Field(min_length=1, max_length=80)
    revisit_period: str | None = Field(default=None, max_length=64)
    remapping_period: str | None = Field(default=None, max_length=64)
    contract_id: str | None = None
    additional_parameters: dict[str, Any] = Field(default_factory=dict)
    confirmation: str | None = Field(default=None, max_length=120)


class TaskingOpportunityRequest(TaskingOrderCreateRequest):
    """Read-only feasibility request using the same tasking shape as an order."""

    confirmation: str | None = None


class TaskingOrderCancelRequest(BaseModel):
    confirmation: str = Field(min_length=1, max_length=160)
    contract_id: str | None = None


class GridPlanRequest(BaseModel):
    campaign_name: str = Field(min_length=1, max_length=120)
    project_name: str = Field(min_length=1, max_length=120)
    order_prefix: str | None = Field(default=None, max_length=120)
    geometry: dict[str, Any]
    parameters: dict[str, Any] = Field(default_factory=dict)
    contract_id: str | None = None


class GridSubmitRequest(BaseModel):
    plan_id: str = Field(min_length=1, max_length=120)
    confirmation: str = Field(min_length=1, max_length=120)
    contract_id: str | None = None


class TaskingConfirmationRequest(BaseModel):
    confirmation: str = Field(min_length=1, max_length=120)


class RecollectionMonitorPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    expected_revisit_days: float | None = Field(default=None, gt=0, le=3650)
    filters: dict[str, Any] | None = None
    linked_order_id: str | None = Field(default=None, max_length=120)
    enabled: bool | None = None


class MonitoringSubscriptionCreateRequest(BaseModel):
    source_id: str = "merlin-s2"
    name: str | None = Field(default=None, max_length=120)
    collection_ids: list[str] = Field(default_factory=list)
    geometry: dict[str, Any]
    filters: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    external_subscription_id: str | None = None
    cursor: str | None = None


class RecollectionMonitorCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    geometry: dict[str, Any]
    source_id: str = "satellogic"
    collection_id: str = "quickview-visual-thumb"
    contract_id: str | None = None
    expected_revisit_days: float | None = Field(default=None, gt=0, le=3650)
    filters: dict[str, Any] = Field(default_factory=dict)
    linked_order_id: str | None = Field(default=None, max_length=120)
    enabled: bool = True


class RecollectionRefreshRequest(BaseModel):
    start_date: str | None = None
    end_date: str | None = None
    limit: int = Field(default=300, ge=1, le=1000)


class MonitoringEventCreateRequest(BaseModel):
    subscription_id: str
    source_id: str = "merlin-s2"
    scene_id: str | None = None
    event_type: str = "change.candidate"
    status: str = "open"
    payload: dict[str, Any] = Field(default_factory=dict)


class MonitoringEventAckRequest(BaseModel):
    status: str = "acked"


class CueCreateRequest(BaseModel):
    event_id: str | None = None
    source_id: str = "merlin-s2"
    status: str = "queued_review"
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    geometry: dict[str, Any]
    payload: dict[str, Any] = Field(default_factory=dict)
