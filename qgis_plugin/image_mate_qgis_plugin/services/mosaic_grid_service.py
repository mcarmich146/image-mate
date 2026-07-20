# -*- coding: utf-8 -*-
"""AOI tiling and pricing helpers for Mosaic collection workflow."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
)

from .mosaic_contracts import GRID_EQUAL_AREA_EPSG, GRID_SIZE_M, PRICE_USD_PER_KM2


@dataclass(frozen=True)
class MosaicTileRow:
    tile_id: str
    grid_x: int
    grid_y: int
    clipped_area_km2: float
    geometry_wkt: str
    geometry_geojson: dict[str, Any]


class MosaicGridService:
    """Build deterministic clipped tile plans and pricing from AOI."""

    def __init__(self, *, grid_size_m: float = GRID_SIZE_M, price_per_km2: float = PRICE_USD_PER_KM2):
        self._grid_size_m = float(grid_size_m or GRID_SIZE_M)
        self._price_per_km2 = float(price_per_km2 or PRICE_USD_PER_KM2)
        if self._grid_size_m <= 0:
            self._grid_size_m = GRID_SIZE_M
        if self._price_per_km2 < 0:
            self._price_per_km2 = PRICE_USD_PER_KM2

    def build_breakdown(self, aoi_geojson: dict[str, Any]) -> dict[str, Any]:
        aoi_wgs84 = self._geometry_from_geojson(aoi_geojson)
        if aoi_wgs84 is None or aoi_wgs84.isEmpty():
            raise RuntimeError("AOI geometry is invalid or empty.")

        crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        crs_equal = QgsCoordinateReferenceSystem(GRID_EQUAL_AREA_EPSG)
        if not crs_wgs84.isValid() or not crs_equal.isValid():
            raise RuntimeError("Failed to resolve required CRS for Mosaic tiling.")

        transform_context = QgsProject.instance().transformContext()
        to_equal = QgsCoordinateTransform(crs_wgs84, crs_equal, transform_context)
        to_wgs84 = QgsCoordinateTransform(crs_equal, crs_wgs84, transform_context)

        aoi_equal = QgsGeometry(aoi_wgs84)
        try:
            aoi_equal.transform(to_equal)
        except Exception as exc:
            raise RuntimeError(f"Failed to project AOI to equal-area CRS: {exc}") from exc

        if aoi_equal is None or aoi_equal.isEmpty():
            raise RuntimeError("AOI is empty after projection to equal-area CRS.")

        extent = aoi_equal.boundingBox()
        min_x = float(extent.xMinimum())
        min_y = float(extent.yMinimum())
        max_x = float(extent.xMaximum())
        max_y = float(extent.yMaximum())
        if max_x <= min_x or max_y <= min_y:
            raise RuntimeError("AOI extent is invalid after projection.")

        start_x = int(math.floor(min_x / self._grid_size_m))
        end_x = int(math.floor((max_x - 1e-9) / self._grid_size_m))
        start_y = int(math.floor(min_y / self._grid_size_m))
        end_y = int(math.floor((max_y - 1e-9) / self._grid_size_m))

        rows: list[MosaicTileRow] = []
        for grid_x in range(start_x, end_x + 1):
            cell_min_x = float(grid_x) * self._grid_size_m
            cell_max_x = float(grid_x + 1) * self._grid_size_m
            for grid_y in range(start_y, end_y + 1):
                cell_min_y = float(grid_y) * self._grid_size_m
                cell_max_y = float(grid_y + 1) * self._grid_size_m
                cell_equal = self._square_polygon(cell_min_x, cell_min_y, cell_max_x, cell_max_y)
                clipped_equal = aoi_equal.intersection(cell_equal)
                if clipped_equal is None or clipped_equal.isEmpty():
                    continue
                area_m2 = float(clipped_equal.area() or 0.0)
                if area_m2 <= 0.0:
                    continue
                clipped_wgs84 = QgsGeometry(clipped_equal)
                try:
                    clipped_wgs84.transform(to_wgs84)
                except Exception:
                    continue
                if clipped_wgs84.isEmpty():
                    continue
                try:
                    geom_geojson = json.loads(clipped_wgs84.asJson())
                except Exception:
                    geom_geojson = {}
                rows.append(
                    MosaicTileRow(
                        tile_id=self._tile_id(grid_x, grid_y),
                        grid_x=grid_x,
                        grid_y=grid_y,
                        clipped_area_km2=max(0.0, area_m2 / 1_000_000.0),
                        geometry_wkt=clipped_wgs84.asWkt(),
                        geometry_geojson=geom_geojson if isinstance(geom_geojson, dict) else {},
                    )
                )

        rows.sort(key=lambda row: (row.grid_x, row.grid_y))
        total_area_km2 = sum(float(row.clipped_area_km2 or 0.0) for row in rows)
        estimated_price_usd = total_area_km2 * self._price_per_km2

        return {
            "grid_size_m": self._grid_size_m,
            "price_per_km2": self._price_per_km2,
            "tile_count": len(rows),
            "total_area_km2": float(total_area_km2),
            "estimated_price_usd": float(estimated_price_usd),
            "tiles": [
                {
                    "tile_id": row.tile_id,
                    "grid_x": int(row.grid_x),
                    "grid_y": int(row.grid_y),
                    "clipped_area_km2": float(row.clipped_area_km2),
                    "geometry_wkt": str(row.geometry_wkt),
                    "geometry": dict(row.geometry_geojson),
                }
                for row in rows
            ],
        }

    @staticmethod
    def estimate_price_usd(total_area_km2: float) -> float:
        return max(0.0, float(total_area_km2 or 0.0) * PRICE_USD_PER_KM2)

    @staticmethod
    def _tile_id(grid_x: int, grid_y: int) -> str:
        return f"tile_{int(grid_x)}_{int(grid_y)}"

    @staticmethod
    def _square_polygon(min_x: float, min_y: float, max_x: float, max_y: float) -> QgsGeometry:
        ring = [
            QgsPointXY(float(min_x), float(min_y)),
            QgsPointXY(float(max_x), float(min_y)),
            QgsPointXY(float(max_x), float(max_y)),
            QgsPointXY(float(min_x), float(max_y)),
            QgsPointXY(float(min_x), float(min_y)),
        ]
        return QgsGeometry.fromPolygonXY([ring])

    @staticmethod
    def _geometry_from_geojson(geometry_payload: dict[str, Any] | None) -> QgsGeometry | None:
        if not isinstance(geometry_payload, dict):
            return None
        try:
            if hasattr(QgsGeometry, "fromGeoJson"):
                parsed = QgsGeometry.fromGeoJson(json.dumps(geometry_payload))
                if parsed is not None and not parsed.isEmpty():
                    return parsed
        except Exception:
            pass

        geom_type = str(geometry_payload.get("type") or "").strip()
        coords = geometry_payload.get("coordinates")

        def to_point(pair):
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                return None
            try:
                return QgsPointXY(float(pair[0]), float(pair[1]))
            except Exception:
                return None

        try:
            if geom_type == "Point":
                point = to_point(coords)
                return QgsGeometry.fromPointXY(point) if point is not None else None
            if geom_type == "Polygon" and isinstance(coords, list):
                rings = []
                for ring in coords:
                    if not isinstance(ring, list):
                        continue
                    pts = [pt for pt in (to_point(pair) for pair in ring) if pt is not None]
                    if len(pts) >= 4:
                        rings.append(pts)
                return QgsGeometry.fromPolygonXY(rings) if rings else None
            if geom_type == "MultiPolygon" and isinstance(coords, list):
                polys = []
                for poly in coords:
                    if not isinstance(poly, list):
                        continue
                    rings = []
                    for ring in poly:
                        if not isinstance(ring, list):
                            continue
                        pts = [pt for pt in (to_point(pair) for pair in ring) if pt is not None]
                        if len(pts) >= 4:
                            rings.append(pts)
                    if rings:
                        polys.append(rings)
                return QgsGeometry.fromMultiPolygonXY(polys) if polys else None
        except Exception:
            return None
        return None
