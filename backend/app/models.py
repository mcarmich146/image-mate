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
    sensor_generation: str | None = Field(default=None, max_length=32)
    min_gsd: float | None = Field(default=None, ge=0)
    max_gsd: float | None = Field(default=None, ge=0)


class SearchResultItem(BaseModel):
    id: str
    source_id: str | None = None
    collection: str | None = None
    datetime: str | None = None
    outcome_id: str | None = None
    satellite_name: str | None = None
    sensor_generation: str | None = None
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
    sensor_generation: str | None = None
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
    model_id: str = Field(default="active", max_length=300)
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
    contract_id: str | None = Field(default=None, max_length=240)
    bounds_wgs84: list[float] = Field(min_length=4, max_length=4)
    source_width_px: int = Field(gt=0, le=8192)
    source_height_px: int = Field(gt=0, le=8192)
    geometry_px: list[list[float]] = Field(min_length=4, max_length=64)
    label: Literal["plane", "helicopter", "background"]
    detection_id: str | None = Field(default=None, max_length=120)
    confidence: float | None = Field(default=None, ge=0, le=1)
    note: str | None = Field(default=None, max_length=1000)
    model_id: str = Field(default="active", max_length=300)

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


class AircraftDatasetBuildRequest(BaseModel):
    """Build a scene-separated training bundle from Model Lab annotations."""

    name: str = Field(min_length=1, max_length=80)
    train_item_ids: list[str] = Field(min_length=1, max_length=100)
    validation_item_ids: list[str] = Field(default_factory=list, max_length=100)
    allow_single_scene: bool = False

    @model_validator(mode="after")
    def validate_scene_split(self):
        train = {str(value).strip() for value in self.train_item_ids if str(value).strip()}
        validation = {str(value).strip() for value in self.validation_item_ids if str(value).strip()}
        if not train:
            raise ValueError("Select at least one training scene")
        if train.intersection(validation):
            raise ValueError("A scene cannot be both training and validation data")
        self.train_item_ids = sorted(train)
        self.validation_item_ids = sorted(validation)
        return self


class AircraftTrainingJobRequest(BaseModel):
    dataset_id: str = Field(min_length=1, max_length=300)
    model_id: str = Field(default="active", max_length=300)
    device: Literal["mps", "cuda", "cpu"] = "mps"
    epochs: int = Field(default=10, ge=1, le=500)
    imgsz: int = Field(default=1024, ge=128, le=4096)
    batch: int = Field(default=1, ge=1, le=64)
    workers: int = Field(default=0, ge=0, le=32)
    allow_single_scene: bool = False
    export_onnx: bool = True


class AircraftEvaluationJobRequest(BaseModel):
    dataset_id: str = Field(min_length=1, max_length=300)
    model_id: str = Field(default="active", max_length=300)
    device: Literal["mps", "cuda", "cpu"] = "mps"


class AircraftModelActivateRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=300)


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


class MosaicInputRequest(BaseModel):
    item_id: str = Field(min_length=1, max_length=240)
    source_id: str = Field(default="satellogic", max_length=64)
    collection_id: str = Field(default="l1d-sr", max_length=120)
    asset_key: str = Field(default="visual", max_length=64)
    sensor_generation: str | None = Field(default=None, max_length=32)


class MosaicPreflightRequest(BaseModel):
    inputs: list[MosaicInputRequest] = Field(min_length=2, max_length=200)
    mode: Literal["whole_strip", "polygon"] = "whole_strip"
    aoi: dict[str, Any] | None = None
    sensor_generation: str | None = Field(default=None, max_length=32)
    output_resolution_m: float | None = Field(default=None, gt=0, le=100)
    output_bands: Literal["rgb", "rgb_nir"] = "rgb"
    accelerator: Literal["auto", "cpu", "mps", "cuda", "opencl"] = "auto"
    contract_id: str | None = Field(default=None, max_length=240)


class MosaicJobRequest(MosaicPreflightRequest):
    overwrite: bool = False
    project_id: str | None = Field(default=None, max_length=120)


class MosaicJobProgressRequest(BaseModel):
    status: Literal[
        "awaiting_product_request", "awaiting_products", "queued", "downloading", "running", "processing", "color_balancing",
        "seam_optimization", "qc_required", "repairing", "succeeded", "finalized",
        "failed", "canceled"
    ] = "running"
    progress: float = Field(default=0, ge=0, le=100)
    message: str = Field(default="", max_length=2000)
    error: str = Field(default="", max_length=4000)
    result: dict[str, Any] | None = None


class MosaicCloudRepairRequest(BaseModel):
    job_id: str = Field(min_length=1, max_length=120)
    geometry: dict[str, Any]
    preferred_item_id: str | None = Field(default=None, max_length=240)
    contract_id: str | None = Field(default=None, max_length=240)


class MosaicProductRequestConfirmation(BaseModel):
    confirmation: str = Field(min_length=1, max_length=120)


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
    analysis_recipe_id: str | None = Field(default=None, max_length=120)
    monitoring_project_id: str | None = Field(default=None, max_length=120)
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


class ArchiveWatchCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    geometry: dict[str, Any]
    source_id: str = "satellogic"
    collection_id: str = "quickview-visual-thumb"
    contract_id: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    email_to: str | None = Field(default=None, max_length=1000)
    poll_interval_seconds: int | None = Field(default=None, ge=15, le=86400)
    enabled: bool = True


class ArchiveWatchPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    filters: dict[str, Any] | None = None
    email_to: str | None = Field(default=None, max_length=1000)
    poll_interval_seconds: int | None = Field(default=None, ge=15, le=86400)
    enabled: bool | None = None


class ArchiveWatchCheckRequest(BaseModel):
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


class AnalysisRecipeCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    version: str = Field(default="1.0.0", min_length=1, max_length=40)
    description: str = Field(default="", max_length=2000)
    models: list[dict[str, Any]] = Field(default_factory=list)
    compatibility: dict[str, Any] = Field(default_factory=dict)
    thresholds: dict[str, Any] = Field(default_factory=dict)
    classes: list[str] = Field(default_factory=list)
    alert_rules: dict[str, Any] = Field(default_factory=dict)
    actions: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class AnalysisRecipePatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    version: str | None = Field(default=None, min_length=1, max_length=40)
    description: str | None = Field(default=None, max_length=2000)
    models: list[dict[str, Any]] | None = None
    compatibility: dict[str, Any] | None = None
    thresholds: dict[str, Any] | None = None
    classes: list[str] | None = None
    alert_rules: dict[str, Any] | None = None
    actions: dict[str, Any] | None = None
    enabled: bool | None = None


class MonitoringProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    geometry: dict[str, Any]
    sources: list[dict[str, Any]] = Field(default_factory=list)
    cadence_seconds: int = Field(default=3600, ge=60, le=31_536_000)
    quality_filters: dict[str, Any] = Field(default_factory=dict)
    analysis_recipe_id: str | None = Field(default=None, max_length=120)
    alert_policy: dict[str, Any] = Field(default_factory=dict)
    actions: dict[str, Any] = Field(default_factory=dict)
    status: Literal["draft", "approved", "active", "paused", "archived"] = "active"
    enabled: bool = True


class MonitoringProjectPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    sources: list[dict[str, Any]] | None = None
    cadence_seconds: int | None = Field(default=None, ge=60, le=31_536_000)
    quality_filters: dict[str, Any] | None = None
    analysis_recipe_id: str | None = Field(default=None, max_length=120)
    alert_policy: dict[str, Any] | None = None
    actions: dict[str, Any] | None = None
    status: Literal["draft", "approved", "active", "paused", "archived"] | None = None
    enabled: bool | None = None


class AlertDispositionRequest(BaseModel):
    status: Literal["New", "Acknowledged", "Dismissed", "Escalated", "Actioned"]
    note: str | None = Field(default=None, max_length=2000)


class ProposedActionDecisionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class MosaicProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    source_item_ids: list[str] = Field(default_factory=list, min_length=0, max_length=200)
    output_bands: Literal["rgb", "rgb_nir"] = "rgb"
    output_resolution_m: float | None = Field(default=None, gt=0, le=100)
    sensor_generation: Literal["mark-iv", "mark-v", "mixed", "unknown"] = "unknown"
    geometry: dict[str, Any] | None = None
    status: str = Field(default="Draft", max_length=40)


class MosaicProjectPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    output_bands: Literal["rgb", "rgb_nir"] | None = None
    output_resolution_m: float | None = Field(default=None, gt=0, le=100)
    status: str | None = Field(default=None, max_length=40)
    geometry: dict[str, Any] | None = None
