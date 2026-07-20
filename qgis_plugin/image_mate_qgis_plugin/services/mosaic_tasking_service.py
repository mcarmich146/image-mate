# -*- coding: utf-8 -*-
"""Tasking orchestration helpers for Mosaic tile lifecycle."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
from typing import Any

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

from .mosaic_contracts import (
    API_STATUS_NOT_SUBMITTED,
    API_STATUS_SUBMISSION_FAILED,
    ATTEMPT_STATUS_FAILED,
    ATTEMPT_STATUS_SKIPPED,
    ATTEMPT_STATUS_SUBMITTED,
    GRID_EQUAL_AREA_EPSG,
    GRID_SIZE_M,
    TASKING_DEFAULT_DURATION_HOURS,
    TASKING_DEFAULT_SKU,
    TASKING_DEFAULT_TARGET_TYPE,
    utc_now_iso,
)
from .mosaic_tracking_store import MosaicTrackingStore


class MosaicTaskingService:
    """Build tasking payloads and orchestrate per-tile submit/refresh/re-task flows."""

    def write_tiles_shapefile(self, *, tile_rows: list[dict[str, Any]], shapefile_path: str) -> str:
        rows = [row for row in (tile_rows or []) if isinstance(row, dict)]
        if not rows:
            raise RuntimeError("Cannot write shapefile for empty tile set.")

        output_path = Path(str(shapefile_path)).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "mosaic_tiles", "memory")
        if not layer.isValid():
            raise RuntimeError("Failed to create memory layer for Mosaic shapefile export.")

        provider = layer.dataProvider()
        provider.addAttributes(
            [
                QgsField("tile_id", QVariant.String),
                QgsField("area_km2", QVariant.Double),
            ]
        )
        layer.updateFields()

        features: list[QgsFeature] = []
        for row in rows:
            tile_id = str(row.get("tile_id") or "").strip()
            if not tile_id:
                continue
            geom = self._geometry_from_tile_row(row)
            if geom is None or geom.isEmpty():
                continue
            feature = QgsFeature(layer.fields())
            feature.setGeometry(geom)
            feature["tile_id"] = tile_id
            feature["area_km2"] = float(row.get("clipped_area_km2") or 0.0)
            features.append(feature)

        if not features:
            raise RuntimeError("No valid tile geometries available for shapefile export.")

        provider.addFeatures(features)
        layer.updateExtents()

        # Remove stale shapefile sidecars before writing new output.
        for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix"):
            stale = output_path.with_suffix(suffix)
            if stale.exists():
                try:
                    stale.unlink()
                except Exception:
                    pass

        write_result = QgsVectorFileWriter.writeAsVectorFormat(
            layer,
            str(output_path),
            "utf-8",
            layer.crs(),
            "ESRI Shapefile",
        )
        if isinstance(write_result, tuple):
            err_code = int(write_result[0])
            err_text = str(write_result[1] if len(write_result) > 1 else "")
        else:
            err_code = int(write_result)
            err_text = ""
        if err_code != QgsVectorFileWriter.NoError:
            raise RuntimeError(f"Failed to write Mosaic shapefile: {err_text or err_code}")

        return str(output_path)

    def submit_tiles(
        self,
        *,
        store: MosaicTrackingStore,
        source_service,
        project_id: str,
        tile_rows: list[dict[str, Any]],
        contract_id: str,
        source_id: str,
        sku: str = TASKING_DEFAULT_SKU,
    ) -> list[dict[str, Any]]:
        rows = [row for row in (tile_rows or []) if isinstance(row, dict)]
        results: list[dict[str, Any]] = []
        for row in rows:
            tile_id = str(row.get("tile_id") or "").strip()
            if not tile_id:
                continue
            result = self.submit_single_tile(
                store=store,
                source_service=source_service,
                project_id=project_id,
                tile_id=tile_id,
                tile_row=row,
                contract_id=contract_id,
                source_id=source_id,
                sku=sku,
                mutation_source="create",
            )
            results.append(result)
        return results

    def submit_single_tile(
        self,
        *,
        store: MosaicTrackingStore,
        source_service,
        project_id: str,
        tile_id: str,
        tile_row: dict[str, Any],
        contract_id: str,
        source_id: str,
        sku: str = TASKING_DEFAULT_SKU,
        mutation_source: str,
    ) -> dict[str, Any]:
        next_attempt = store.next_attempt_no(project_id=project_id, tile_id=tile_id)
        point_payload = self._tile_tasking_point_geojson(tile_row=tile_row, tile_id=tile_id)
        if not isinstance(point_payload, dict):
            raise RuntimeError(f"Tile center point is missing or invalid for {tile_id}")

        request_payload = self._build_order_payload(
            project_id=project_id,
            tile_id=tile_id,
            attempt_no=next_attempt,
            geometry=point_payload,
            contract_id=contract_id,
            sku=sku,
        )

        if str(source_id or "").strip().lower() != "satellogic":
            api_status = API_STATUS_NOT_SUBMITTED
            store.append_attempt(
                project_id=project_id,
                tile_id=tile_id,
                attempt_no=next_attempt,
                collection_id=None,
                attempt_status=ATTEMPT_STATUS_SKIPPED,
                api_status=api_status,
                request_payload=request_payload,
                response_payload={},
                error_text="source_not_satellogic",
                mutation_source=mutation_source,
            )
            return {
                "tile_id": tile_id,
                "attempt_no": next_attempt,
                "success": False,
                "attempt_status": ATTEMPT_STATUS_SKIPPED,
                "api_status": api_status,
                "collection_id": "",
                "error": "source_not_satellogic",
            }

        try:
            response = source_service.create_tasking_order(request_payload)
            order = response.get("order") if isinstance(response, dict) else None
            order = order if isinstance(order, dict) else {}
            collection_id = str(order.get("id") or "").strip()
            api_status = str(order.get("status") or "submitted").strip() or "submitted"
            store.append_attempt(
                project_id=project_id,
                tile_id=tile_id,
                attempt_no=next_attempt,
                collection_id=collection_id or None,
                attempt_status=ATTEMPT_STATUS_SUBMITTED,
                api_status=api_status,
                request_payload=request_payload,
                response_payload=response if isinstance(response, dict) else {"value": response},
                error_text="",
                mutation_source=mutation_source,
            )
            return {
                "tile_id": tile_id,
                "attempt_no": next_attempt,
                "success": True,
                "attempt_status": ATTEMPT_STATUS_SUBMITTED,
                "api_status": api_status,
                "collection_id": collection_id,
                "error": "",
            }
        except Exception as exc:
            err_text = str(exc)
            store.append_attempt(
                project_id=project_id,
                tile_id=tile_id,
                attempt_no=next_attempt,
                collection_id=None,
                attempt_status=ATTEMPT_STATUS_FAILED,
                api_status=API_STATUS_SUBMISSION_FAILED,
                request_payload=request_payload,
                response_payload={},
                error_text=err_text,
                mutation_source=mutation_source,
            )
            return {
                "tile_id": tile_id,
                "attempt_no": next_attempt,
                "success": False,
                "attempt_status": ATTEMPT_STATUS_FAILED,
                "api_status": API_STATUS_SUBMISSION_FAILED,
                "collection_id": "",
                "error": err_text,
            }

    def refresh_non_accepted_statuses(
        self,
        *,
        store: MosaicTrackingStore,
        source_service,
        project_id: str,
        contract_id: str,
        source_id: str,
        tile_ids: list[str] | None = None,
        skip_failed: bool = True,
    ) -> list[dict[str, Any]]:
        rows = store.non_accepted_tiles(project_id)
        requested_tile_ids = {
            str(tile_id or "").strip()
            for tile_id in (tile_ids or [])
            if str(tile_id or "").strip()
        }
        if requested_tile_ids:
            rows = [
                row
                for row in rows
                if str((row if isinstance(row, dict) else {}).get("tile_id") or "").strip()
                in requested_tile_ids
            ]
        if str(source_id or "").strip().lower() != "satellogic":
            return [
                {
                    "tile_id": str(row.get("tile_id") or "").strip(),
                    "skipped": True,
                    "reason": "source_not_satellogic",
                }
                for row in rows
            ]

        updates: list[dict[str, Any]] = []
        for row in rows:
            tile_id = str(row.get("tile_id") or "").strip()
            collection_id = str(row.get("latest_collection_id") or "").strip()
            api_status = str(row.get("api_status") or "").strip()
            if not tile_id:
                continue
            if bool(skip_failed):
                if self._is_terminal_failed_status(api_status):
                    updates.append(
                        {
                            "tile_id": tile_id,
                            "skipped": True,
                            "reason": "terminal_failed",
                            "api_status": api_status,
                        }
                    )
                    continue
                if self._is_terminal_canceled_status(api_status):
                    updates.append(
                        {
                            "tile_id": tile_id,
                            "skipped": True,
                            "reason": "terminal_canceled",
                            "api_status": api_status,
                        }
                    )
                    continue
            if not collection_id:
                updates.append({"tile_id": tile_id, "skipped": True, "reason": "missing_collection_id"})
                continue
            try:
                detail = source_service.get_tasking_order(collection_id, contract_id=contract_id or None)
                order = detail.get("order") if isinstance(detail, dict) else None
                order = order if isinstance(order, dict) else {}
                api_status = str(order.get("status") or "unknown").strip() or "unknown"
                changed = store.update_tile_api_status(
                    project_id=project_id,
                    tile_id=tile_id,
                    api_status=api_status,
                    mutation_source="refresh_status",
                    note="api_refresh",
                )
                updates.append(
                    {
                        "tile_id": tile_id,
                        "skipped": False,
                        "changed": bool(changed),
                        "api_status": api_status,
                    }
                )
            except Exception as exc:
                updates.append(
                    {
                        "tile_id": tile_id,
                        "skipped": False,
                        "changed": False,
                        "api_status": str(row.get("api_status") or ""),
                        "error": str(exc),
                    }
                )
        return updates

    @staticmethod
    def _is_terminal_failed_status(status: str | None) -> bool:
        status_key = re.sub(r"[\s-]+", "_", str(status or "").strip().lower())
        if not status_key:
            return False
        return status_key == "failed" or status_key.endswith("_failed")

    @staticmethod
    def _is_terminal_canceled_status(status: str | None) -> bool:
        status_key = re.sub(r"[\s-]+", "_", str(status or "").strip().lower())
        if not status_key:
            return False
        return status_key in {"canceled", "cancelled"}

    @staticmethod
    def _build_order_payload(
        *,
        project_id: str,
        tile_id: str,
        attempt_no: int,
        geometry: dict[str, Any],
        contract_id: str,
        sku: str,
    ) -> dict[str, Any]:
        start_dt = datetime.now(timezone.utc)
        end_dt = start_dt + timedelta(hours=TASKING_DEFAULT_DURATION_HOURS)
        project_key = str(project_id or "").strip()
        tile_key = str(tile_id or "").strip()
        order_name = f"mosaic-{project_key}-{tile_key}-a{int(attempt_no)}"
        return {
            "target_type": TASKING_DEFAULT_TARGET_TYPE,
            "geometry": geometry,
            "order_name": order_name,
            "project_name": project_key,
            "sku": str(sku or TASKING_DEFAULT_SKU),
            "start_date": start_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "end_date": end_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "revisit_period": None,
            "remapping_period": None,
            "contract_id": str(contract_id or "").strip() or None,
            "additional_parameters": {},
        }

    @staticmethod
    def _tile_tasking_point_geojson(*, tile_row: dict[str, Any], tile_id: str) -> dict[str, Any] | None:
        point = MosaicTaskingService._point_from_grid_center(tile_row=tile_row, tile_id=tile_id)
        if isinstance(point, dict):
            return point

        # Fallback for older persisted rows without grid indices/tile_id format.
        geom = MosaicTaskingService._geometry_from_tile_row(tile_row)
        if geom is None or geom.isEmpty():
            return None
        centroid = geom.centroid()
        if centroid is None or centroid.isEmpty():
            return None
        centroid_point = centroid.asPoint()
        lon = float(centroid_point.x())
        lat = float(centroid_point.y())
        if not math.isfinite(lon) or not math.isfinite(lat):
            return None
        return {"type": "Point", "coordinates": [lon, lat]}

    @staticmethod
    def _point_from_grid_center(*, tile_row: dict[str, Any], tile_id: str) -> dict[str, Any] | None:
        row = tile_row if isinstance(tile_row, dict) else {}
        grid_x = MosaicTaskingService._safe_int(row.get("grid_x"))
        grid_y = MosaicTaskingService._safe_int(row.get("grid_y"))
        if grid_x is None or grid_y is None:
            parsed = MosaicTaskingService._grid_indices_from_tile_id(tile_id)
            if parsed is None:
                return None
            grid_x, grid_y = parsed

        src_crs = QgsCoordinateReferenceSystem(GRID_EQUAL_AREA_EPSG)
        dst_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        if not src_crs.isValid() or not dst_crs.isValid():
            return None

        center_x = (float(grid_x) + 0.5) * float(GRID_SIZE_M)
        center_y = (float(grid_y) + 0.5) * float(GRID_SIZE_M)
        try:
            transform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance().transformContext())
            pt = transform.transform(QgsPointXY(center_x, center_y))
            lon = float(pt.x())
            lat = float(pt.y())
        except Exception:
            return None
        if not math.isfinite(lon) or not math.isfinite(lat):
            return None
        return {"type": "Point", "coordinates": [lon, lat]}

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            return int(value)
        except Exception:
            return None

    @staticmethod
    def _grid_indices_from_tile_id(tile_id: str) -> tuple[int, int] | None:
        tile_key = str(tile_id or "").strip()
        match = re.fullmatch(r"tile_(-?\d+)_(-?\d+)", tile_key)
        if not match:
            return None
        try:
            return int(match.group(1)), int(match.group(2))
        except Exception:
            return None

    @staticmethod
    def _geometry_from_tile_row(tile_row: dict[str, Any]) -> QgsGeometry | None:
        row = tile_row if isinstance(tile_row, dict) else {}
        geom_payload = row.get("geometry")
        if isinstance(geom_payload, dict):
            try:
                parsed = QgsGeometry.fromGeoJson(json.dumps(geom_payload))
                if parsed is not None and not parsed.isEmpty():
                    return parsed
            except Exception:
                pass
        geom_wkt = str(row.get("geometry_wkt") or "").strip()
        if not geom_wkt:
            return None
        try:
            parsed = QgsGeometry.fromWkt(geom_wkt)
        except Exception:
            parsed = None
        if parsed is None or parsed.isEmpty():
            return None
        return parsed
