import math
from dataclasses import dataclass, field

from pyproj import CRS, Transformer
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box, mapping
from shapely.ops import transform as shp_transform
from shapely.ops import unary_union

from ..domain.schemas import CampaignParameters


@dataclass
class PlannedCell:
    row: int
    col: int
    geometry: object
    area_km2: float
    submittable: bool = True
    warning: str | None = None


@dataclass
class PlanResult:
    cells: list[PlannedCell]
    utm_epsg: int
    discarded_count: int = 0
    discarded_area_km2: float = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class GridEstimate:
    rows: int
    cols: int
    candidate_count: int
    utm_epsg: int


def utm_crs_for(lon: float, lat: float) -> CRS:
    zone = int(math.floor((lon + 180) / 6) % 60) + 1
    return CRS.from_epsg((32600 if lat >= 0 else 32700) + zone)


def grid_context(aoi, params: CampaignParameters):
    centroid = aoi.centroid
    utm = utm_crs_for(centroid.x, centroid.y)
    to_utm = Transformer.from_crs(4326, utm, always_xy=True).transform
    to_wgs = Transformer.from_crs(utm, 4326, always_xy=True).transform
    aoi_utm = shp_transform(to_utm, aoi)
    minx, miny, _, _ = aoi_utm.bounds
    cell_m = params.cell_size_km * 1000
    origin_x = math.floor(minx / cell_m) * cell_m
    origin_y = math.floor(miny / cell_m) * cell_m
    return utm, to_utm, to_wgs, cell_m, origin_x, origin_y


def grid_square(row: int, col: int, cell_m: float, origin_x: float, origin_y: float):
    return box(
        origin_x + col * cell_m,
        origin_y + row * cell_m,
        origin_x + (col + 1) * cell_m,
        origin_y + (row + 1) * cell_m,
    )


def estimate_grid(aoi, params: CampaignParameters) -> GridEstimate:
    utm, to_utm, _, cell_m, origin_x, origin_y = grid_context(aoi, params)
    aoi_utm = shp_transform(to_utm, aoi)
    _, _, maxx, maxy = aoi_utm.bounds
    cols = math.ceil((maxx - origin_x) / cell_m)
    rows = math.ceil((maxy - origin_y) / cell_m)
    return GridEstimate(rows=rows, cols=cols, candidate_count=rows * cols, utm_epsg=int(utm.to_epsg() or 0))


def polygon_parts(geom) -> list[Polygon]:
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    if isinstance(geom, GeometryCollection):
        return [part for item in geom.geoms for part in polygon_parts(item)]
    return []


def single_polygon(geom) -> Polygon | None:
    parts = polygon_parts(geom)
    return parts[0] if len(parts) == 1 else None


def repair_multipolygon_cell(aoi, params: CampaignParameters, row: int, col: int, geometry):
    _, to_utm, to_wgs, cell_m, origin_x, origin_y = grid_context(aoi, params)
    geom_utm = shp_transform(to_utm, geometry)
    square = grid_square(row, col, cell_m, origin_x, origin_y)
    if not isinstance(geom_utm, MultiPolygon):
        return None
    distances = [1, 2, 5, 10, 25, 50, 100, 200, 500, 1000, 2000, 5000, cell_m / 2]
    for distance in distances:
        inflated = unary_union([part.buffer(distance) for part in polygon_parts(geom_utm)])
        clipped = inflated.intersection(square)
        polygon = single_polygon(clipped)
        if polygon and not polygon.is_empty:
            repaired = shp_transform(to_wgs, polygon)
            return PlannedCell(
                row=row,
                col=col,
                geometry=repaired,
                area_km2=round(polygon.area / 1_000_000, 4),
                submittable=True,
                warning=f"Repaired from MultiPolygon by buffering {distance:g} m within grid cell.",
            )
    return None


def build_grid(aoi, params: CampaignParameters, progress_callback=None) -> PlanResult:
    utm, _, to_wgs, cell_m, origin_x, origin_y = grid_context(aoi, params)
    to_utm = Transformer.from_crs(4326, utm, always_xy=True).transform
    aoi_utm = shp_transform(to_utm, aoi)
    minx, miny, maxx, maxy = aoi_utm.bounds
    cols = math.ceil((maxx - origin_x) / cell_m)
    rows = math.ceil((maxy - origin_y) / cell_m)
    result = PlanResult([], int(utm.to_epsg() or 0))
    processed = 0
    for row in range(rows):
        for col in range(cols):
            processed += 1
            if progress_callback and (processed == 1 or processed % 1000 == 0):
                progress_callback(processed, rows * cols, len(result.cells), "evaluating grid")
            square = grid_square(row, col, cell_m, origin_x, origin_y)
            if not square.intersects(aoi_utm):
                continue
            geom = square.intersection(aoi_utm) if params.clip_mode == "intersect" else square
            if geom.is_empty:
                continue
            area = geom.area / 1_000_000
            if area < params.min_area_km2:
                result.discarded_count += 1
                result.discarded_area_km2 += area
                continue
            wgs_geom = shp_transform(to_wgs, geom)
            submittable = wgs_geom.geom_type == "Polygon"
            warning = None if submittable else f"Unsupported order geometry: {wgs_geom.geom_type}"
            result.cells.append(PlannedCell(row, col, wgs_geom, round(area, 4), submittable, warning))
    if progress_callback:
        progress_callback(rows * cols, rows * cols, len(result.cells), "grid evaluation complete")
    return result


def build_order_feature(
    cell: PlannedCell, params: CampaignParameters, project_name: str, order_name: str
) -> dict:
    return {
        "type": "Feature",
        "geometry": mapping(cell.geometry),
        "properties": {
            "order_name": order_name,
            "project_name": project_name,
            "sku": params.sku,
            "parameters": params.api_parameters(),
        },
    }
