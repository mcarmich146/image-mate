from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def default_start() -> datetime:
    return (utc_now() + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)


def default_end() -> datetime:
    return default_start() + timedelta(days=60)


class CampaignParameters(BaseModel):
    cell_size_km: float = Field(default=20, gt=0)
    clip_mode: Literal["intersect", "square"] = "intersect"
    min_area_km2: float = Field(default=25, ge=0)
    start: datetime = Field(default_factory=default_start)
    end: datetime = Field(default_factory=default_end)
    sku: Literal["TSKARE-M"] = "TSKARE-M"
    max_ona: float = Field(default=25, ge=0, le=45)
    min_ona: float = Field(default=0, ge=0, le=45)
    min_sun_elevation: float = Field(default=10, ge=-90, le=90)
    max_sun_elevation: float = Field(default=90, ge=-90, le=90)
    processing_level: Literal["L1D", "L1D_SR"] = "L1D_SR"
    remapping_period: str | None = None
    remapping_mode: Literal["piecewise", "batch"] = "piecewise"
    request_delay: float = Field(default=0.5, ge=0)

    @model_validator(mode="after")
    def validate_ranges(self) -> "CampaignParameters":
        if self.min_ona > self.max_ona:
            raise ValueError("Minimum off-nadir angle cannot exceed maximum")
        if self.min_sun_elevation > self.max_sun_elevation:
            raise ValueError("Minimum sun elevation cannot exceed maximum")
        if self.end <= self.start:
            raise ValueError("End must be after start")
        if self.min_area_km2 > self.cell_size_km**2:
            raise ValueError("Minimum area cannot exceed a full grid cell")
        return self

    def api_parameters(self) -> dict:
        data = {
            "start": self.start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "end": self.end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "min_ona": self.min_ona,
            "max_ona": self.max_ona,
            "min_sun_elevation": self.min_sun_elevation,
            "max_sun_elevation": self.max_sun_elevation,
            "processing_level": self.processing_level,
            "remapping_mode": self.remapping_mode,
        }
        if self.remapping_period:
            data["remapping_period"] = self.remapping_period
        return data


class ArchiveCoverageParameters(BaseModel):
    enabled: bool = True
    collection_id: str = "all"
    start: datetime = Field(default_factory=lambda: utc_now() - timedelta(days=365))
    end: datetime = Field(default_factory=lambda: utc_now() + timedelta(days=1))
    limit: int = Field(default=100000, ge=1, le=100000)
    max_cloud_cover: float = Field(default=20, ge=0, le=100)
    min_ona: float = Field(default=0, ge=0, le=45)
    max_ona: float = Field(default=25, ge=0, le=45)
    min_sun_elevation: float = Field(default=0, ge=-90, le=90)
    max_sun_elevation: float = Field(default=90, ge=-90, le=90)
    processing_level: str = "L1D_SR"

    @model_validator(mode="after")
    def validate_archive_ranges(self) -> "ArchiveCoverageParameters":
        if self.end <= self.start:
            raise ValueError("Archive end must be after archive start")
        if self.min_ona > self.max_ona:
            raise ValueError("Archive minimum off-nadir angle cannot exceed maximum")
        if self.min_sun_elevation > self.max_sun_elevation:
            raise ValueError("Archive minimum sun elevation cannot exceed maximum")
        return self
