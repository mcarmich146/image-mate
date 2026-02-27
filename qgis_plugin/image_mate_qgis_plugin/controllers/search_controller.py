# -*- coding: utf-8 -*-
"""Search request assembly for Explore workflows."""

from datetime import date, timedelta


class SearchController:
    def default_dates(self):
        today = date.today()
        return {
            "start_date": (today - timedelta(days=30)).isoformat(),
            "end_date": today.isoformat(),
        }

    @staticmethod
    def extent_to_geometry(extent):
        x_min = float(extent.xMinimum())
        y_min = float(extent.yMinimum())
        x_max = float(extent.xMaximum())
        y_max = float(extent.yMaximum())
        return {
            "type": "Polygon",
            "coordinates": [[
                [x_min, y_min],
                [x_max, y_min],
                [x_max, y_max],
                [x_min, y_max],
                [x_min, y_min],
            ]],
        }

    def build_search_request(self, payload, extent_geometry):
        max_cloud_cover = payload.get("max_cloud_cover")
        limit = payload.get("limit")
        start_date = str(payload.get("start_date") or "").strip()
        end_date = str(payload.get("end_date") or "").strip()
        if len(start_date) == 10:
            start_date = f"{start_date}T00:00:00Z"
        if len(end_date) == 10:
            end_date = f"{end_date}T23:59:59Z"

        return {
            "source_id": payload.get("source_id"),
            "collection_id": payload.get("collection_id"),
            "start_date": start_date,
            "end_date": end_date,
            "max_cloud_cover": float(max_cloud_cover) if max_cloud_cover is not None else None,
            "limit": int(limit) if limit is not None else 250,
            "contract_id": str(payload.get("contract_id") or "").strip() or None,
            "satellite_name": str(payload.get("satellite_name") or "").strip() or None,
            "min_gsd": payload.get("min_gsd"),
            "max_gsd": payload.get("max_gsd"),
            "require_full_aoi_overlap": bool(payload.get("require_full_aoi_overlap", False)),
            "geometry": extent_geometry,
        }
