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


class DownloadAssetEntry(BaseModel):
    url: str
    filename: str | None = None
    item_id: str | None = None
    outcome_id: str | None = None


class DownloadBundleRequest(BaseModel):
    assets: list[DownloadAssetEntry] = Field(default_factory=list)
    contract_id: str | None = None
    bundle_name: str = "tiles_download"
