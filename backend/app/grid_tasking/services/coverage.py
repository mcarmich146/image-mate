from datetime import datetime, timedelta, timezone

from pyproj import Transformer
from shapely.errors import GEOSException
from shapely.geometry import GeometryCollection, mapping, shape
from shapely.ops import transform as shp_transform
from shapely.ops import unary_union
from shapely.validation import make_valid

from ..domain.status import DELIVERED_STATUSES


def _repair(geometry):
    if geometry.is_empty or geometry.is_valid:
        return geometry
    repaired = make_valid(geometry)
    return repaired if not repaired.is_empty else geometry.buffer(0)


def _polygonal(geometry):
    geometry = _repair(geometry)
    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return geometry
    if geometry.geom_type == "GeometryCollection":
        polygons = [item for item in geometry.geoms if item.geom_type in {"Polygon", "MultiPolygon"}]
        return _repair(unary_union(polygons)) if polygons else GeometryCollection()
    return GeometryCollection()


def _source_geometry(source: dict | None):
    if not isinstance(source, dict):
        return None
    geometry = source.get("footprint") or source.get("geometry")
    if not isinstance(geometry, dict):
        return None
    if geometry.get("type") == "Feature":
        geometry = geometry.get("geometry")
    if not isinstance(geometry, dict):
        return None
    try:
        return _polygonal(shape(geometry))
    except (GEOSException, TypeError, ValueError):
        return None


def _source_datetime(source: dict | None) -> datetime | None:
    if not isinstance(source, dict):
        return None
    props = source.get("properties") if isinstance(source.get("properties"), dict) else source
    values = [
        props.get("datetime"),
        props.get("delivered_at"),
        props.get("acquired_at"),
        props.get("acquisition_time"),
    ]
    latest_event = props.get("latest_event")
    if isinstance(latest_event, dict):
        values.append(latest_event.get("timestamp"))
    values.extend([props.get("updated_at"), props.get("created_at")])
    for value in values:
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            continue
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    return None


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _campaign_aoi(campaign):
    source = campaign.aoi_geojson or {}
    geometry = source.get("geometry") if source.get("type") == "Feature" else source
    try:
        return _polygonal(shape(geometry))
    except (GEOSException, TypeError, ValueError):
        return GeometryCollection()


def _project_coverage(geometry, transformer, aoi_projected):
    projected = _polygonal(shp_transform(transformer, geometry))
    return _polygonal(projected.intersection(aoi_projected)) if not projected.is_empty else projected


def _coverage_percent(geometry, aoi_area: float) -> tuple[float, float]:
    area = geometry.area
    if aoi_area <= 0:
        return 0.0, 0.0
    return area / 1_000_000, max(0.0, min(100.0, area / aoi_area * 100))


def collection_coverage_timeline(campaign, plan, start: datetime, end: datetime) -> list[dict]:
    """Return dated cumulative coverage and a rate-based projection for a window."""
    start = _utc(start)
    end = _utc(end)
    aoi = _campaign_aoi(campaign)
    if aoi.is_empty or end <= start:
        return [
            {"timestamp": _iso(start), "covered_percent": 0.0, "covered_area_km2": 0.0, "projected": False},
            {"timestamp": _iso(end), "covered_percent": 0.0, "covered_area_km2": 0.0, "projected": False},
        ]

    transformer = Transformer.from_crs(4326, 6933, always_xy=True).transform
    aoi_projected = _polygonal(shp_transform(transformer, aoi))
    if aoi_projected.is_empty or aoi_projected.area <= 0:
        return [
            {"timestamp": _iso(start), "covered_percent": 0.0, "covered_area_km2": 0.0, "projected": False},
            {"timestamp": _iso(end), "covered_percent": 0.0, "covered_area_km2": 0.0, "projected": False},
        ]

    initial_raw = []
    timed_raw_by_day = {}
    for feature in (campaign.archive_coverage_geojson or {}).get("features", []):
        geometry = _source_geometry(feature)
        if geometry is None or geometry.is_empty:
            continue
        timestamp = _source_datetime(feature)
        if timestamp is None:
            initial_raw.append(geometry)
        elif timestamp <= end:
            timed_raw_by_day.setdefault(timestamp.date(), []).append((timestamp, geometry))

    for cell in plan.cells:
        for order in cell.orders:
            for deliverable in order.deliverables:
                status = str(deliverable.status or "").strip().lower()
                if status not in DELIVERED_STATUSES:
                    continue
                timestamp = _source_datetime(deliverable.source)
                geometry = _source_geometry(deliverable.source)
                if timestamp is None or geometry is None or geometry.is_empty:
                    continue
                if timestamp <= end:
                    timed_raw_by_day.setdefault(timestamp.date(), []).append((timestamp, geometry))

    aoi_area = aoi_projected.area
    daily_coverages = {}
    initial = []
    if initial_raw:
        initial_source = _polygonal(unary_union(initial_raw))
        initial_projected = _project_coverage(initial_source, transformer, aoi_projected)
        if not initial_projected.is_empty:
            initial.append(initial_projected)
    for day, geometries in timed_raw_by_day.items():
        daily_source = _polygonal(unary_union([geometry for _, geometry in geometries]))
        projected = _project_coverage(daily_source, transformer, aoi_projected)
        if not projected.is_empty:
            daily_coverages[day] = projected
            if day < start.date():
                initial.append(projected)
            elif day == start.date():
                before_start = [geometry for timestamp, geometry in geometries if timestamp <= start]
                if before_start:
                    initial_source = _polygonal(unary_union(before_start))
                    initial_projected = _project_coverage(initial_source, transformer, aoi_projected)
                    if not initial_projected.is_empty:
                        initial.append(initial_projected)
    covered = _polygonal(unary_union(initial)) if initial else GeometryCollection()

    history_covered = GeometryCollection()
    history_points = []
    for day in sorted(daily_coverages):
        daily_coverage = daily_coverages[day]
        history_covered = _polygonal(unary_union([history_covered, daily_coverage]))
        history_timestamp = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).replace(
            hour=23, minute=59, second=59
        )
        history_points.append((history_timestamp, history_covered.area))

    historical_rate_km2_per_day = 0.0
    if len(history_points) >= 2:
        first_timestamp = history_points[0][0]
        last_timestamp, last_area = history_points[-1]
        elapsed_days = (last_timestamp - first_timestamp).total_seconds() / 86_400
        if elapsed_days > 0:
            historical_rate_km2_per_day = max(0.0, last_area / 1_000_000 / elapsed_days)

    def point(timestamp: datetime, area: float, projected: bool = False) -> dict:
        if projected:
            area_km2 = area / 1_000_000
            percent = max(0.0, min(100.0, area / aoi_area * 100)) if aoi_area else 0.0
        else:
            area_km2, percent = _coverage_percent(covered, aoi_area)
        return {
            "timestamp": _iso(timestamp),
            "covered_percent": round(percent, 3),
            "covered_area_km2": round(area_km2, 3),
            "projected": projected,
        }

    points = [point(start, covered.area)]
    last_event_timestamp = start
    for day in sorted(daily_coverages):
        timestamp = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).replace(
            hour=23, minute=59, second=59
        )
        if timestamp <= start:
            continue
        covered = _polygonal(unary_union([covered, daily_coverages[day]]))
        if timestamp <= end and timestamp > start:
            last_event_timestamp = timestamp
            if covered.area > points[-1]["covered_area_km2"] * 1_000_000 + 1:
                points.append(point(timestamp, covered.area))

    if last_event_timestamp > start and points[-1]["timestamp"] != _iso(last_event_timestamp):
        points.append(point(last_event_timestamp, covered.area))

    projection_start = min(last_event_timestamp, end)
    if projection_start < end:
        points.append(point(projection_start, covered.area, projected=True))
        cursor = projection_start
        while cursor < end:
            cursor = min(cursor + timedelta(days=1), end)
            elapsed_days = (cursor - projection_start).total_seconds() / 86_400
            projected_area = min(
                aoi_area,
                covered.area + historical_rate_km2_per_day * elapsed_days * 1_000_000,
            )
            points.append(point(cursor, projected_area, projected=True))
    elif points[-1]["timestamp"] != _iso(end):
        points.append(point(end, covered.area))
    return points


def coverage_timeline_chart_data(timeline: list[dict]) -> dict:
    """Map timeline values into a responsive 1000x300 SVG chart coordinate space."""
    if not timeline:
        return {
            "points": [],
            "line": "",
            "actual_line": "",
            "projected_line": "",
            "actual_area": "",
            "projected_area": "",
            "area": "",
        }
    first = datetime.fromisoformat(timeline[0]["timestamp"].replace("Z", "+00:00"))
    last = datetime.fromisoformat(timeline[-1]["timestamp"].replace("Z", "+00:00"))
    date_range = max(1.0, (last - first).total_seconds())
    left, right, top, bottom = 56, 976, 18, 258
    points = []
    for point in timeline:
        timestamp = datetime.fromisoformat(point["timestamp"].replace("Z", "+00:00"))
        fraction = max(0.0, min(1.0, (timestamp - first).total_seconds() / date_range))
        percent = max(0.0, min(100.0, float(point["covered_percent"])))
        x = left + fraction * (right - left)
        y = bottom - percent / 100 * (bottom - top)
        points.append({**point, "x": round(x, 2), "y": round(y, 2), "plot": f"{x:.2f},{y:.2f}"})
    line = " ".join(point["plot"] for point in points)
    actual_points = [point for point in points if not point.get("projected")]
    projected_points = [point for point in points if point.get("projected")]
    actual_line = " ".join(point["plot"] for point in actual_points)
    projected_line = " ".join(point["plot"] for point in projected_points)
    actual_area = ""
    if actual_points:
        actual_area = f"{actual_line} {actual_points[-1]['x']:.2f},{bottom} {actual_points[0]['x']:.2f},{bottom}"
    projected_area = ""
    if projected_points:
        projected_area = f"{projected_line} {projected_points[-1]['x']:.2f},{bottom} {projected_points[0]['x']:.2f},{bottom}"
    area = f"{line} {right},{bottom} {left},{bottom}"
    return {
        "points": points,
        "line": line,
        "actual_line": actual_line,
        "projected_line": projected_line,
        "actual_area": actual_area,
        "projected_area": projected_area,
        "area": area,
    }


def _archive_geometries(campaign):
    for feature in (campaign.archive_coverage_geojson or {}).get("features", []):
        geometry = _source_geometry(feature)
        if geometry is not None and not geometry.is_empty:
            yield geometry


def _delivered_geometries(cell):
    for order in cell.orders:
        for deliverable in order.deliverables:
            status = str(deliverable.status or "").strip().lower()
            if status not in DELIVERED_STATUSES:
                continue
            geometry = _source_geometry(deliverable.source)
            if geometry is not None and not geometry.is_empty:
                yield geometry


def remaining_cell_geometry(cell, campaign, plan):
    """Return the cell AOI minus archive and successful-deliverable footprints in WGS84."""
    cell_geometry = _polygonal(shape(cell.geometry_geojson))
    if cell_geometry.is_empty or cell_geometry.area <= 0:
        return GeometryCollection()

    transformer = Transformer.from_crs(4326, plan.utm_epsg, always_xy=True).transform
    inverse = Transformer.from_crs(plan.utm_epsg, 4326, always_xy=True).transform
    cell_projected = _polygonal(shp_transform(transformer, cell_geometry))
    covered = []
    for geometry in (*_archive_geometries(campaign), *_delivered_geometries(cell)):
        projected = _polygonal(shp_transform(transformer, geometry))
        if not projected.is_empty:
            covered.append(projected)
    if covered:
        covered_union = _polygonal(unary_union(covered))
        remaining = _polygonal(cell_projected.difference(covered_union))
    else:
        remaining = cell_projected
    # Overlay operations can leave sub-square-metre numerical slivers at shared edges.
    remaining_parts = [part for part in polygon_parts(remaining) if part.area >= 1]
    remaining = _polygonal(unary_union(remaining_parts)) if remaining_parts else GeometryCollection()
    return _polygonal(shp_transform(inverse, remaining))


def remaining_cell_area(cell, campaign, plan) -> tuple[float, float]:
    cell_projected = _project_cell_geometry(cell, plan)
    remaining = remaining_cell_geometry(cell, campaign, plan)
    if cell_projected.is_empty or cell_projected.area <= 0:
        return 0.0, 0.0
    transformer = Transformer.from_crs(4326, plan.utm_epsg, always_xy=True).transform
    remaining_area = _polygonal(shp_transform(transformer, remaining)).area
    return remaining_area / 1_000_000, max(0.0, min(1.0, remaining_area / cell_projected.area))


def _project_cell_geometry(cell, plan):
    transformer = Transformer.from_crs(4326, plan.utm_epsg, always_xy=True).transform
    return _polygonal(shp_transform(transformer, _polygonal(shape(cell.geometry_geojson))))


def polygon_parts(geometry):
    geometry = _repair(geometry)
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type == "MultiPolygon":
        return list(geometry.geoms)
    if geometry.geom_type == "GeometryCollection":
        return [part for item in geometry.geoms for part in polygon_parts(item)]
    return []


def remaining_cell_features(cell, campaign, plan) -> list[dict]:
    return [mapping(part) for part in polygon_parts(remaining_cell_geometry(cell, campaign, plan)) if part.area > 0]
