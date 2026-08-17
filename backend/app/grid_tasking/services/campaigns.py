import hashlib
import json
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from pyproj import Transformer
from shapely.errors import GEOSException
from shapely.geometry import mapping, shape
from shapely.ops import transform as shp_transform
from shapely.ops import unary_union
from shapely.validation import make_valid
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ...config import settings as image_mate_settings
from ..db.models import (
    AuditEvent,
    Campaign,
    Capture,
    CellDisposition,
    CellOrder,
    Deliverable,
    GridCell,
    Operation,
    OrderEvent,
    PlanRevision,
    SubmissionAttempt,
)
from app.domain.schemas import ArchiveCoverageParameters, CampaignParameters
from app.services.geometry import normalize_aoi
from app.services.planning import build_grid, build_order_feature, repair_multipolygon_cell
from app.services.satellogic import SatellogicClient

CAMPAIGN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DELETE_BATCH_SIZE = 2000
_plan_locks: defaultdict[str, Lock] = defaultdict(Lock)


def validate_campaign_id(value: str) -> str:
    value = value.strip()
    if not CAMPAIGN_ID.fullmatch(value) or ".." in value:
        raise ValueError("Campaign ID must use 1–64 letters, digits, underscores, or hyphens")
    return value


def create_campaign(
    db: Session,
    settings: Settings,
    campaign_id: str,
    filename: str,
    content: bytes,
    contract_id: str | None,
    archive_parameters: ArchiveCoverageParameters | None = None,
    archive_coverage_geojson: dict | None = None,
) -> Campaign:
    campaign_id = validate_campaign_id(campaign_id)
    if len(content) > settings.max_upload_bytes:
        raise ValueError("AOI upload exceeds the 25 MB limit")
    if Path(filename).suffix.lower() not in {".json", ".geojson"}:
        raise ValueError("AOI must be a .json or .geojson file")
    existing = db.scalar(select(Campaign).where(Campaign.campaign_id_normalized == campaign_id.casefold()))
    if existing:
        raise ValueError("Campaign ID already exists")
    data = json.loads(content.decode("utf-8"))
    normalized = normalize_aoi(data)
    campaign_dir = (settings.data_dir / campaign_id).resolve()
    if settings.data_dir not in campaign_dir.parents:
        raise ValueError("Invalid campaign path")
    inputs = campaign_dir / "inputs"
    outputs = campaign_dir / "outputs"
    inputs.mkdir(parents=True, exist_ok=False)
    outputs.mkdir(parents=True, exist_ok=True)
    safe_original = f"original_{Path(filename).name}"
    try:
        (inputs / safe_original).write_bytes(content)
        (inputs / "aoi.geojson").write_text(json.dumps(normalized.geojson, indent=2), encoding="utf-8")
        if archive_coverage_geojson:
            (inputs / "archive_coverage.geojson").write_text(
                json.dumps(archive_coverage_geojson, indent=2), encoding="utf-8"
            )
        archive_params = archive_parameters or ArchiveCoverageParameters(enabled=False)
        campaign = Campaign(
            campaign_id=campaign_id,
            campaign_id_normalized=campaign_id.casefold(),
            state="draft",
            contract_id=contract_id,
            project_name=campaign_id,
            order_prefix=f"{campaign_id}_",
            aoi_geojson=normalized.geojson,
            archive_enabled=archive_params.enabled,
            archive_parameters=archive_params.model_dump(mode="json"),
            archive_coverage_geojson=archive_coverage_geojson,
            original_filename=Path(filename).name,
            aoi_sha256=hashlib.sha256(content).hexdigest(),
        )
        db.add(campaign)
        db.flush()
        db.add(
            AuditEvent(
                campaign_id=campaign.id,
                event_type="campaign_created",
                details={"warnings": normalized.warnings, "feature_count": normalized.feature_count},
            )
        )
        db.commit()
        return campaign
    except Exception:
        db.rollback()
        for item in inputs.glob("*"):
            item.unlink(missing_ok=True)
        inputs.rmdir()
        outputs.rmdir()
        campaign_dir.rmdir()
        raise


def empty_archive_coverage() -> dict:
    return {"type": "FeatureCollection", "features": []}


def normalize_archive_coverage(data: dict) -> dict:
    kind = data.get("type")
    if kind == "FeatureCollection":
        features = data.get("features", [])
    elif kind == "Feature":
        features = [data]
    else:
        features = [{"type": "Feature", "properties": {}, "geometry": data}]
    if not isinstance(features, list):
        raise ValueError("Archive coverage must be valid GeoJSON")
    normalized_features = []
    for feature in features:
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        if not geometry:
            continue
        geom = normalize_aoi({"type": "Feature", "properties": {}, "geometry": geometry}).geojson["geometry"]
        normalized_features.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": feature.get("properties", {}) if isinstance(feature.get("properties"), dict) else {},
            }
        )
    return {"type": "FeatureCollection", "features": normalized_features}


def _float_prop(props: dict, *names: str) -> float | None:
    for name in names:
        value = props.get(name)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _archive_feature_passes_filters(feature: dict, params: ArchiveCoverageParameters) -> bool:
    props = feature.get("properties", {}) if isinstance(feature.get("properties"), dict) else {}
    cloud = _float_prop(props, "eo:cloud_cover", "satl:cloud_cover", "cloud_cover")
    if cloud is not None and cloud > params.max_cloud_cover:
        return False
    ona = _float_prop(
        props, "view:off_nadir", "satl:ona", "satl:off_nadir", "ona", "off_nadir", "off_nadir_angle"
    )
    if ona is not None and not (params.min_ona <= ona <= params.max_ona):
        return False
    sun = _float_prop(props, "view:sun_elevation", "satl:sun_elevation", "sun_elevation")
    if sun is not None and not (params.min_sun_elevation <= sun <= params.max_sun_elevation):
        return False
    return True


def _archive_collection_ids(collection_id: str) -> list[str]:
    value = (collection_id or "").strip().lower().replace("_", "-")
    aliases = {
        "visual": "quickview-visual",
        "thumbnail": "quickview-visual-thumb",
        "thumb": "quickview-visual-thumb",
        "quickview-thumbnail": "quickview-visual-thumb",
    }
    value = aliases.get(value, value)
    if value in {"", "all", "*", "auto"}:
        return ["quickview-visual", "quickview-visual-thumb", "l1d-sr"]
    return [value]


def _feature_intersects_aoi(feature: dict, aoi_geom) -> bool:
    try:
        return shape(feature["geometry"]).intersects(aoi_geom)
    except Exception:
        return False


def normalize_archive_search_results(
    payload: dict, params: ArchiveCoverageParameters, exact_aoi_geojson: dict | None = None
) -> dict:
    features = payload.get("features", []) if isinstance(payload, dict) else []
    aoi_geom = shape(exact_aoi_geojson) if exact_aoi_geojson else None
    normalized_features = []
    for feature in features:
        if not isinstance(feature, dict) or not feature.get("geometry"):
            continue
        if not _archive_feature_passes_filters(feature, params):
            continue
        if aoi_geom is not None and not _feature_intersects_aoi(feature, aoi_geom):
            continue
        props = feature.get("properties", {}) if isinstance(feature.get("properties"), dict) else {}
        assets = feature.get("assets", {}) if isinstance(feature.get("assets"), dict) else {}
        geometry = normalize_aoi(
            {"type": "Feature", "properties": {}, "geometry": feature["geometry"]}
        ).geojson["geometry"]
        normalized_features.append(
            {
                "type": "Feature",
                "id": feature.get("id"),
                "geometry": geometry,
                "properties": {
                    **props,
                    "archive_id": feature.get("id"),
                    "collection": feature.get("collection"),
                    "cloud_cover": _float_prop(props, "eo:cloud_cover", "satl:cloud_cover", "cloud_cover"),
                    "ona": _float_prop(
                        props,
                        "view:off_nadir",
                        "satl:ona",
                        "satl:off_nadir",
                        "ona",
                        "off_nadir",
                        "off_nadir_angle",
                    ),
                    "sun_elevation": _float_prop(
                        props, "view:sun_elevation", "satl:sun_elevation", "sun_elevation"
                    ),
                    "preview_url": _asset_href(assets, "preview", "thumbnail", "visual", "analytic"),
                },
            }
        )
    return {"type": "FeatureCollection", "features": normalized_features}


def _asset_href(assets: dict, *names: str) -> str:
    for name in names:
        asset = assets.get(name)
        if isinstance(asset, dict) and asset.get("href"):
            return str(asset["href"])
    return ""


def _next_archive_link(payload: dict) -> dict | None:
    links = payload.get("links", []) if isinstance(payload, dict) else []
    for link in links:
        if isinstance(link, dict) and link.get("rel") == "next":
            return link
    return None


def _archive_feature_sort_key(feature: dict) -> str:
    props = feature.get("properties", {}) if isinstance(feature.get("properties"), dict) else {}
    return str(props.get("datetime") or props.get("acquired") or "")


def _archive_api_filter(params: ArchiveCoverageParameters) -> dict:
    return {
        "op": "and",
        "args": [
            {"op": "<=", "args": [{"property": "eo:cloud_cover"}, params.max_cloud_cover]},
            {"op": ">=", "args": [{"property": "view:off_nadir"}, params.min_ona]},
            {"op": "<=", "args": [{"property": "view:off_nadir"}, params.max_ona]},
            {"op": ">=", "args": [{"property": "view:sun_elevation"}, params.min_sun_elevation]},
            {"op": "<=", "args": [{"property": "view:sun_elevation"}, params.max_sun_elevation]},
        ],
    }


def _dedupe_and_limit_archive_features(features: list[dict], limit: int) -> list[dict]:
    deduped = {}
    for feature in features:
        props = feature.get("properties", {}) if isinstance(feature.get("properties"), dict) else {}
        key = props.get("archive_id") or feature.get("id") or json.dumps(feature.get("geometry", {}), sort_keys=True)
        deduped[str(key)] = feature
    ordered = sorted(deduped.values(), key=_archive_feature_sort_key, reverse=True)
    return ordered[:limit]


def update_archive_coverage(
    db: Session,
    settings: Settings,
    campaign: Campaign,
    params: ArchiveCoverageParameters,
    archive_coverage_geojson: dict | None = None,
) -> Campaign:
    campaign.archive_enabled = params.enabled
    campaign.archive_parameters = params.model_dump(mode="json")
    if archive_coverage_geojson is not None:
        campaign.archive_coverage_geojson = archive_coverage_geojson
        out = settings.data_dir / campaign.campaign_id / "inputs" / "archive_coverage.geojson"
        out.write_text(json.dumps(archive_coverage_geojson, indent=2), encoding="utf-8")
    db.add(
        AuditEvent(
            campaign_id=campaign.id,
            event_type="archive_coverage_updated",
            details={
                "enabled": params.enabled,
                "footprint_count": len((campaign.archive_coverage_geojson or empty_archive_coverage())["features"]),
            },
        )
    )
    db.commit()
    return campaign


def search_archive_coverage(
    db: Session,
    settings: Settings,
    campaign: Campaign,
    params: ArchiveCoverageParameters,
    client: SatellogicClient,
    operation: Operation | None = None,
) -> Campaign:
    if not campaign.contract_id:
        raise ValueError("Select a contract before searching archive imagery.")
    params.enabled = True
    aoi_geom = shape(campaign.aoi_geojson["geometry"])
    bbox = [float(value) for value in aoi_geom.bounds]
    merged_features = []
    collection_counts = {}
    filtered_counts = {}
    server_limit = 500
    max_pages = max(20, (params.limit // server_limit) + 5)
    api_filter = _archive_api_filter(params)
    collection_ids = _archive_collection_ids(params.collection_id)
    if operation:
        operation.progress_total = len(collection_ids) * max_pages
        operation.result = {
            "current_collection": "",
            "pages_scanned": 0,
            "raw_count": 0,
            "filtered_count": 0,
            "stored_count": 0,
            "collection_counts": {},
            "filtered_counts": {},
            "message": "Starting archive search",
        }
        db.commit()
    for collection_id in collection_ids:
        collection_counts[collection_id] = 0
        filtered_counts[collection_id] = 0
        next_link = None
        for page in range(max_pages):
            if operation:
                db.refresh(operation)
                if operation.status == "cancel_requested":
                    operation.result = {
                        **(operation.result or {}),
                        "message": "Archive search cancelled",
                    }
                    db.commit()
                    return campaign
            if next_link:
                payload = client.search_archive_next(campaign.contract_id, next_link)
            else:
                payload = client.search_archive(
                    campaign.contract_id,
                    None,
                    collection_id,
                    params.start.isoformat().replace("+00:00", "Z"),
                    params.end.isoformat().replace("+00:00", "Z"),
                    server_limit,
                    bbox=bbox,
                    cql2_filter=api_filter,
                )
            features = payload.get("features", []) if isinstance(payload, dict) else []
            collection_counts[collection_id] += len(features)
            page_coverage = normalize_archive_search_results(
                {"type": "FeatureCollection", "features": features}, params, campaign.aoi_geojson["geometry"]
            )
            filtered_counts[collection_id] += len(page_coverage["features"])
            merged_features.extend(page_coverage["features"])
            if operation:
                operation.progress_current += 1
                operation.result = {
                    "current_collection": collection_id,
                    "pages_scanned": operation.progress_current,
                    "raw_count": sum(collection_counts.values()),
                    "filtered_count": sum(filtered_counts.values()),
                    "stored_count": min(len(merged_features), params.limit),
                    "collection_counts": collection_counts,
                    "filtered_counts": filtered_counts,
                    "message": (
                        f"{collection_id}: page {page + 1}, "
                        f"{len(features)} raw item(s), {len(page_coverage['features'])} AOI match(es)"
                    ),
                }
                db.commit()
            next_link = _next_archive_link(payload)
            if not next_link or not features:
                break
            if filtered_counts[collection_id] >= params.limit and page >= 1:
                break
    coverage = {
        "type": "FeatureCollection",
        "features": _dedupe_and_limit_archive_features(merged_features, params.limit),
    }
    params.collection_id = ",".join(_archive_collection_ids(params.collection_id))
    update_archive_coverage(db, settings, campaign, params, coverage)
    if operation:
        operation.result = {
            "current_collection": "",
            "pages_scanned": operation.progress_current,
            "raw_count": sum(collection_counts.values()),
            "filtered_count": sum(filtered_counts.values()),
            "stored_count": len(coverage["features"]),
            "collection_counts": collection_counts,
            "filtered_counts": filtered_counts,
            "message": f"Stored {len(coverage['features'])} archive footprint(s)",
        }
    db.add(
        AuditEvent(
            campaign_id=campaign.id,
            event_type="archive_search_completed",
            details={
                "collection_id": params.collection_id,
                "raw_count": sum(collection_counts.values()),
                "filtered_count": len(coverage["features"]),
                "collection_counts": collection_counts,
                "filtered_counts": filtered_counts,
                "search_mode": "bbox_with_local_aoi_intersection",
            },
        )
    )
    db.commit()
    return campaign


def execute_archive_search(operation_id: str, client: SatellogicClient) -> None:
    from app.db.session import SessionLocal

    db = SessionLocal()
    operation = db.get(Operation, operation_id)
    try:
        if not operation:
            return
        campaign = db.get(Campaign, operation.campaign_id)
        if not campaign:
            raise ValueError("Campaign not found")
        operation.status = "running"
        operation.started_at = datetime.now(timezone.utc)
        db.commit()
        params = ArchiveCoverageParameters.model_validate(operation.input)
        search_archive_coverage(
            db,
            settings=get_settings(),
            campaign=campaign,
            params=params,
            client=client,
            operation=operation,
        )
        operation.status = "cancelled" if operation.status == "cancel_requested" else "succeeded"
        operation.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        db.rollback()
        operation = db.get(Operation, operation_id)
        if operation:
            operation.status = "failed"
            operation.error = str(exc)
            operation.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


def create_plan(
    db: Session, settings: Settings, campaign: Campaign, params: CampaignParameters, operation: Operation | None = None
) -> PlanRevision:
    with _plan_locks[campaign.id]:
        db.expire(campaign, ["plans"])
        normalized_params = params.model_dump(mode="json")
        if any(plan.state == "committed" for plan in campaign.plans):
            raise ValueError("Committed plans cannot be replanned.")
        if any(order.remote_order_id for plan in campaign.plans for cell in plan.cells for order in cell.orders):
            raise ValueError("Submitted campaigns cannot be replanned")
        active_plan = next((plan for plan in campaign.plans if plan.state in {"draft", "committed"}), None)
        if active_plan and active_plan.parameters == normalized_params:
            campaign.active_plan_id = active_plan.id
            campaign.state = "planned"
            db.commit()
            return active_plan
        for plan in list(campaign.plans):
            db.delete(plan)
        db.flush()
        revision = (
            db.scalar(select(func.max(PlanRevision.revision)).where(PlanRevision.campaign_id == campaign.id))
            or 0
        ) + 1
        aoi = normalize_aoi(campaign.aoi_geojson).geometry

        def report_grid_progress(current: int, total: int, retained: int, message: str) -> None:
            if not operation:
                return
            operation.progress_current = current
            operation.progress_total = total
            operation.result = {
                "message": message,
                "phase": "planning",
                "candidate_cells": total,
                "processed_cells": current,
                "retained_cells": retained,
            }
            db.commit()

        result = build_grid(aoi, params, progress_callback=report_grid_progress)
        if not result.cells:
            raise ValueError("Planning produced no retained grid cells")
        if operation:
            operation.progress_current = 0
            operation.progress_total = len(result.cells)
            operation.result = {
                "message": f"Writing {len(result.cells)} retained cells",
                "phase": "writing",
                "candidate_cells": operation.result.get("candidate_cells") if operation.result else None,
                "retained_cells": len(result.cells),
            }
            db.commit()
        plan = PlanRevision(
            campaign_id=campaign.id,
            revision=revision,
            state="draft",
            parameters=normalized_params,
            utm_epsg=result.utm_epsg,
            total_area_km2=sum(cell.area_km2 for cell in result.cells),
            discarded_count=result.discarded_count,
            discarded_area_km2=result.discarded_area_km2,
        )
        db.add(plan)
        db.flush()
        features = []
        order_payloads = []
        for index, cell in enumerate(result.cells, 1):
            order_name = f"{campaign.order_prefix}r{cell.row:03d}_c{cell.col:03d}"
            geometry = cell.geometry.__geo_interface__
            model = GridCell(
                plan_id=plan.id,
                row=cell.row,
                col=cell.col,
                geometry_geojson=geometry,
                area_km2=cell.area_km2,
                base_order_name=order_name,
                submittable=cell.submittable,
                warning=cell.warning,
            )
            db.add(model)
            order_payloads.append(build_order_feature(cell, params, campaign.project_name, order_name))
            features.append(
                {
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": {
                        "row": cell.row,
                        "col": cell.col,
                        "area_km2": cell.area_km2,
                        "order_name": order_name,
                        "submittable": cell.submittable,
                    },
                }
            )
            if operation and (index == 1 or index % 1000 == 0):
                operation.progress_current = index
                operation.result = {
                    **(operation.result or {}),
                    "message": f"Writing retained cell {index} of {len(result.cells)}",
                    "written_cells": index,
                }
                db.commit()
        campaign.active_plan_id = plan.id
        campaign.state = "planned"
        db.add(AuditEvent(campaign_id=campaign.id, event_type="plan_created", details={"revision": revision}))
        if operation:
            operation.progress_current = operation.progress_total
            operation.result = {
                **(operation.result or {}),
                "message": f"Plan revision {revision} created with {len(result.cells)} cells",
                "revision": revision,
                "retained_cells": len(result.cells),
            }
        db.commit()
    out = settings.data_dir / campaign.campaign_id / "outputs" / "plans" / f"{revision:04d}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "grid_cells.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, indent=2), encoding="utf-8"
    )
    (out / "plan_summary.json").write_text(
        json.dumps(
            {
                "revision": revision,
                "utm_epsg": result.utm_epsg,
                "cell_count": len(result.cells),
                "total_area_km2": plan.total_area_km2,
                "discarded_count": result.discarded_count,
                "parameters": plan.parameters,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (out / "order_payloads.json").write_text(json.dumps(order_payloads, indent=2), encoding="utf-8")
    return plan


def execute_plan(operation_id: str, _client: SatellogicClient | None = None) -> None:
    from app.db.session import SessionLocal

    db = SessionLocal()
    operation = db.get(Operation, operation_id)
    try:
        if not operation:
            return
        campaign = db.get(Campaign, operation.campaign_id)
        if not campaign:
            raise ValueError("Campaign not found")
        operation.status = "running"
        operation.started_at = datetime.now(timezone.utc)
        db.commit()
        payload = operation.input or {}
        if payload.get("project_name"):
            campaign.project_name = str(payload["project_name"]).strip()
        if payload.get("order_prefix"):
            campaign.order_prefix = str(payload["order_prefix"]).strip()
        params = CampaignParameters.model_validate(payload["parameters"])
        create_plan(db, get_settings(), campaign, params, operation=operation)
        operation.status = "succeeded"
        operation.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        db.rollback()
        operation = db.get(Operation, operation_id)
        if operation:
            operation.status = "failed"
            operation.error = str(exc)
            operation.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


def fix_multipolygon_cells(db: Session, campaign: Campaign) -> dict:
    plan = db.get(PlanRevision, campaign.active_plan_id) if campaign.active_plan_id else None
    if not plan:
        raise ValueError("Plan the AOI before fixing cells.")
    params = CampaignParameters.model_validate(plan.parameters)
    aoi = normalize_aoi(campaign.aoi_geojson).geometry
    fixed = 0
    skipped_with_orders = 0
    failed = 0
    area_delta_km2 = 0.0
    failed_examples = []

    for cell in plan.cells:
        if cell.submittable or cell.geometry_geojson.get("type") != "MultiPolygon":
            continue
        if cell.orders:
            skipped_with_orders += 1
            continue
        original_geometry = cell.original_geometry_geojson or cell.geometry_geojson
        repaired = repair_multipolygon_cell(aoi, params, cell.row, cell.col, shape(cell.geometry_geojson))
        if not repaired:
            failed += 1
            if len(failed_examples) < 5:
                failed_examples.append(cell.base_order_name)
            continue

        old_area = cell.area_km2
        fixed_geometry = mapping(repaired.geometry)
        cell.original_geometry_geojson = original_geometry
        cell.fixed_geometry_geojson = fixed_geometry
        cell.geometry_geojson = fixed_geometry
        cell.area_km2 = repaired.area_km2
        cell.submittable = True
        cell.warning = repaired.warning
        area_delta_km2 += repaired.area_km2 - old_area
        fixed += 1

    plan.total_area_km2 = sum(cell.area_km2 for cell in plan.cells)
    details = {
        "fixed": fixed,
        "skipped_with_orders": skipped_with_orders,
        "failed": failed,
        "area_delta_km2": round(area_delta_km2, 4),
        "failed_examples": failed_examples,
    }
    db.add(AuditEvent(campaign_id=campaign.id, event_type="multipolygon_cells_fixed", details=details))
    db.commit()
    return details


def _repair_overlay_geometry(geometry):
    if geometry.is_empty:
        return geometry
    repaired = make_valid(geometry) if not geometry.is_valid else geometry
    if not repaired.is_valid:
        repaired = repaired.buffer(0)
    return repaired


def mark_archive_covered_complete(db: Session, campaign: Campaign, coverage_threshold: float = 0.999999) -> dict:
    plan = db.get(PlanRevision, campaign.active_plan_id) if campaign.active_plan_id else None
    if not plan:
        raise ValueError("Plan the AOI before marking archive-covered cells complete.")
    archive_features = (campaign.archive_coverage_geojson or {}).get("features", [])
    archive_geometries = []
    skipped_invalid_archive = 0
    for feature in archive_features:
        if not feature.get("geometry"):
            continue
        try:
            geometry = _repair_overlay_geometry(shape(feature["geometry"]))
            if not geometry.is_empty:
                archive_geometries.append(geometry)
        except (GEOSException, ValueError):
            skipped_invalid_archive += 1
    if not archive_geometries:
        raise ValueError("Search or upload archive coverage before marking archive-covered cells complete.")

    archive_union = _repair_overlay_geometry(unary_union(archive_geometries))
    transformer = None
    if plan.utm_epsg:
        transformer = Transformer.from_crs(4326, plan.utm_epsg, always_xy=True).transform
        archive_union = _repair_overlay_geometry(shp_transform(transformer, archive_union))

    today = datetime.now(timezone.utc).date().isoformat()
    reason = f"Covered By Archive. Mark as closed on {today}."
    marked = 0
    skipped_completed = 0
    skipped_not_covered = 0
    for cell in plan.cells:
        if cell.operational_status == "delivered" or any(
            disposition.active and disposition.disposition in {"manual_delivered", "accepted_delivered"}
            for disposition in cell.dispositions
        ):
            skipped_completed += 1
            continue
        try:
            cell_geom = _repair_overlay_geometry(shape(cell.geometry_geojson))
            if transformer:
                cell_geom = _repair_overlay_geometry(shp_transform(transformer, cell_geom))
        except (GEOSException, ValueError):
            skipped_not_covered += 1
            continue
        if cell_geom.is_empty or cell_geom.area <= 0:
            skipped_not_covered += 1
            continue
        try:
            coverage_ratio = _repair_overlay_geometry(archive_union.intersection(cell_geom)).area / cell_geom.area
        except GEOSException:
            coverage_ratio = _repair_overlay_geometry(
                _repair_overlay_geometry(archive_union).buffer(0).intersection(_repair_overlay_geometry(cell_geom).buffer(0))
            ).area / cell_geom.area
        if coverage_ratio < coverage_threshold:
            skipped_not_covered += 1
            continue
        for previous in cell.dispositions:
            previous.active = False
        cell.dispositions.append(
            CellDisposition(
                cell_order_id=cell.orders[-1].id if cell.orders else None,
                disposition="manual_delivered",
                reason=reason,
                active=True,
            )
        )
        cell.operational_status = "delivered"
        db.add(
            AuditEvent(
                campaign_id=campaign.id,
                cell_id=cell.id,
                event_type="cell_disposition_changed",
                details={
                    "disposition": "manual_delivered",
                    "reason": reason,
                    "source": "archive_bulk_complete",
                    "coverage_ratio": round(coverage_ratio, 4),
                },
            )
        )
        marked += 1
    details = {
        "marked": marked,
        "skipped_completed": skipped_completed,
        "skipped_not_covered": skipped_not_covered,
        "skipped_invalid_archive": skipped_invalid_archive,
        "coverage_threshold": coverage_threshold,
        "reason": reason,
    }
    db.add(AuditEvent(campaign_id=campaign.id, event_type="archive_covered_cells_completed", details=details))
    db.commit()
    return details


def commit_plan(db: Session, campaign: Campaign) -> PlanRevision:
    plan = db.get(PlanRevision, campaign.active_plan_id) if campaign.active_plan_id else None
    if not plan:
        raise ValueError("Plan the AOI before committing.")
    if any(order.remote_order_id for cell in plan.cells for order in cell.orders):
        raise ValueError("This plan already has submitted collections.")
    plan.state = "committed"
    campaign.state = "plan_committed"
    db.add(AuditEvent(campaign_id=campaign.id, event_type="plan_committed", details={"revision": plan.revision}))
    db.commit()
    return plan


def update_plan_window(db: Session, campaign: Campaign, start: datetime, end: datetime) -> PlanRevision:
    plan = db.get(PlanRevision, campaign.active_plan_id) if campaign.active_plan_id else None
    if not plan:
        raise ValueError("Plan the AOI before updating the collection window.")
    current = CampaignParameters.model_validate(plan.parameters)
    updated = current.model_copy(update={"start": start, "end": end})
    params = updated.model_dump(mode="json")
    plan.parameters = params
    updated_orders = 0
    for cell in plan.cells:
        for order in cell.orders:
            if order.remote_order_id:
                continue
            order_params = {**(order.parameters or {}), "start": params["start"], "end": params["end"]}
            payload = {**(order.payload or {})}
            properties = {**payload.get("properties", {})}
            properties["parameters"] = {**properties.get("parameters", {}), "start": params["start"], "end": params["end"]}
            payload["properties"] = properties
            order.parameters = order_params
            order.payload = payload
            order.start = params["start"]
            order.end = params["end"]
            updated_orders += 1
    db.add(
        AuditEvent(
            campaign_id=campaign.id,
            event_type="plan_window_updated",
            details={"plan_id": plan.id, "start": params["start"], "end": params["end"], "orders_updated": updated_orders},
        )
    )
    db.commit()
    return plan


def _chunks(values: list[str], size: int = 500):
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _select_ids_in_chunks(db: Session, column, filter_column, values: list[str]) -> list[str]:
    ids = []
    for chunk in _chunks(values):
        ids.extend(db.scalars(select(column).where(filter_column.in_(chunk))).all())
    return ids


def _delete_in_chunks(db: Session, model, column, values: list[str], progress_callback=None) -> None:
    for chunk in _chunks(values):
        db.execute(delete(model).where(column.in_(chunk)))
        if progress_callback:
            progress_callback(len(chunk))


def _set_delete_progress(
    db: Session,
    operation: Operation | None,
    current: int,
    total: int,
    message: str,
    campaign_id: str | None = None,
) -> None:
    if not operation:
        return
    operation.progress_current = current
    operation.progress_total = max(total, 1)
    operation.result = {
        **(operation.result or {}),
        "message": message,
        "campaign_id": campaign_id or "",
        "percent": round(current / max(total, 1) * 100, 1),
    }
    db.commit()


def delete_campaign(
    db: Session,
    settings: Settings,
    campaign: Campaign,
    confirmation: str,
    operation: Operation | None = None,
    progress_offset: int = 0,
    progress_total: int | None = None,
) -> Path:
    if confirmation != campaign.campaign_id:
        raise ValueError("Confirmation must match the Campaign ID.")
    campaign_dir = (settings.data_dir / campaign.campaign_id).resolve()
    if campaign_dir == settings.data_dir or settings.data_dir not in campaign_dir.parents:
        raise ValueError("Refusing to delete an unsafe campaign directory.")
    plan_ids = db.scalars(select(PlanRevision.id).where(PlanRevision.campaign_id == campaign.id)).all()
    cell_total = (
        db.scalar(select(func.count(GridCell.id)).where(GridCell.plan_id.in_(plan_ids))) if plan_ids else 0
    ) or 0
    total = progress_total or max(cell_total + len(plan_ids) + 4, 1)
    current = progress_offset

    def report(message: str) -> None:
        _set_delete_progress(db, operation, current, total, message, campaign.campaign_id)

    def advance(count: int, message: str) -> None:
        nonlocal current
        current += count
        report(message)

    lock = _plan_locks[campaign.id]
    while not lock.acquire(timeout=5):
        report(f"Waiting for existing campaign operation to finish for {campaign.campaign_id}")
    try:
        report(f"Preparing removal for {campaign.campaign_id} ({cell_total} cells)")
        operation_ids = db.scalars(select(Operation.id).where(Operation.campaign_id == campaign.id)).all()
        if operation_ids:
            report(f"Removing operation history for {campaign.campaign_id}")
            _delete_in_chunks(db, Operation, Operation.id, operation_ids)
        db.execute(delete(AuditEvent).where(AuditEvent.campaign_id == campaign.id))
        advance(1, f"Removed campaign audit history for {campaign.campaign_id}")

        for plan_id in plan_ids:
            while True:
                cell_ids = db.scalars(
                    select(GridCell.id).where(GridCell.plan_id == plan_id).limit(DELETE_BATCH_SIZE)
                ).all()
                if not cell_ids:
                    break
                report(
                    f"Removing grid cells for {campaign.campaign_id}: "
                    f"{min(current - progress_offset, cell_total)} of {cell_total}"
                )
                order_ids = _select_ids_in_chunks(db, CellOrder.id, CellOrder.cell_id, cell_ids)
                if order_ids:
                    report(f"Removing order records for {campaign.campaign_id}")
                    _delete_in_chunks(db, SubmissionAttempt, SubmissionAttempt.cell_order_id, order_ids)
                    _delete_in_chunks(db, OrderEvent, OrderEvent.cell_order_id, order_ids)
                    _delete_in_chunks(db, Capture, Capture.cell_order_id, order_ids)
                    _delete_in_chunks(db, Deliverable, Deliverable.cell_order_id, order_ids)
                    _delete_in_chunks(db, CellOrder, CellOrder.id, order_ids)
                _delete_in_chunks(db, CellDisposition, CellDisposition.cell_id, cell_ids)
                _delete_in_chunks(db, AuditEvent, AuditEvent.cell_id, cell_ids)
                _delete_in_chunks(db, GridCell, GridCell.id, cell_ids)
                advance(len(cell_ids), f"Removing grid cells for {campaign.campaign_id}")

        if plan_ids:
            _delete_in_chunks(db, PlanRevision, PlanRevision.id, plan_ids)
            advance(len(plan_ids), f"Removed plan revisions for {campaign.campaign_id}")
        db.execute(delete(Campaign).where(Campaign.id == campaign.id))
        advance(1, f"Removing campaign record for {campaign.campaign_id}")
        db.commit()
    finally:
        lock.release()

    if campaign_dir.exists():
        shutil.rmtree(campaign_dir)
    _set_delete_progress(db, operation, min(current, total), total, f"Removed {campaign.campaign_id}", campaign.campaign_id)
    return campaign_dir


def execute_campaign_delete(operation_id: str, _client: SatellogicClient | None = None) -> None:
    from app.db.session import SessionLocal

    db = SessionLocal()
    operation = db.get(Operation, operation_id)
    if not operation:
        db.close()
        return
    try:
        operation.status = "running"
        operation.started_at = datetime.now(timezone.utc)
        operation.progress_current = 0
        operation.progress_total = 1
        operation.result = {"message": "Preparing campaign removal", "percent": 0}
        db.commit()
        campaign_ids = operation.input.get("campaign_ids", [])
        if not campaign_ids:
            raise ValueError("No campaigns were selected for deletion.")

        campaigns = [
            campaign
            for campaign_id in campaign_ids
            if (
                campaign := db.scalar(
                    select(Campaign).where(Campaign.campaign_id_normalized == str(campaign_id).casefold())
                )
            )
        ]
        if not campaigns:
            raise ValueError("No selected campaigns exist.")

        totals = {}
        total_work = 0
        for campaign in campaigns:
            operation.result = {
                **(operation.result or {}),
                "message": f"Counting records for {campaign.campaign_id}",
            }
            db.commit()
            plan_ids = db.scalars(select(PlanRevision.id).where(PlanRevision.campaign_id == campaign.id)).all()
            cell_count = (
                db.scalar(select(func.count(GridCell.id)).where(GridCell.plan_id.in_(plan_ids))) if plan_ids else 0
            ) or 0
            work = max(cell_count + len(plan_ids) + 4, 1)
            totals[campaign.id] = work
            total_work += work

        operation.progress_total = max(total_work, 1)
        operation.result = {"message": "Starting campaign removal", "percent": 0}
        db.commit()
        offset = 0
        deleted = []
        for campaign in campaigns:
            if operation.status == "cancel_requested":
                operation.result = {
                    **(operation.result or {}),
                    "message": "Campaign removal cancelled",
                    "deleted": deleted,
                }
                db.commit()
                return
            delete_campaign(
                db,
                get_settings(),
                campaign,
                campaign.campaign_id,
                operation=operation,
                progress_offset=offset,
                progress_total=max(total_work, 1),
            )
            offset += totals[campaign.id]
            deleted.append(campaign.campaign_id)
        operation.status = "succeeded"
        operation.completed_at = datetime.now(timezone.utc)
        operation.progress_current = operation.progress_total
        operation.result = {
            "message": f"Deleted {len(deleted)} campaign(s)",
            "deleted": deleted,
            "percent": 100,
        }
        db.commit()
    except Exception as exc:
        operation.status = "failed"
        operation.completed_at = datetime.now(timezone.utc)
        operation.error = str(exc)
        operation.result = {"message": f"Campaign removal failed: {exc}"}
        db.commit()
    finally:
        db.close()
