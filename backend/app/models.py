from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    geometry: dict[str, Any]
    start_date: str
    end_date: str
    collection_id: str = "l1d-sr"
    contract_id: str | None = None
    limit: int = 300
    max_cloud_cover: float | None = Field(default=40, ge=0, le=100)
    satellite_name: str | None = None
    min_gsd: float | None = Field(default=None, ge=0)
    max_gsd: float | None = Field(default=None, ge=0)


class SearchResultItem(BaseModel):
    id: str
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


class CompareRequest(BaseModel):
    before_item_id: str
    after_item_id: str
    contract_id: str | None = None


class AnnotationRecord(BaseModel):
    id: str | None = None
    aoi_name: str = "default"
    note: str
    geometry: dict[str, Any]
    label: str = "observation"
    created_at: str | None = None


class GeoAgentRequest(BaseModel):
    geometry: dict[str, Any]
    start_date: str
    end_date: str
    prompt: str
    latest_item_id: str | None = None
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


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class AnimationSearchRequest(BaseModel):
    geometry: dict[str, Any]
    start_date: str
    end_date: str
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
