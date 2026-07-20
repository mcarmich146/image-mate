# -*- coding: utf-8 -*-
"""Layer-tree snapshot and layer-order helpers for side-by-side map mode."""

from __future__ import annotations

from typing import Any

from qgis.core import QgsLayerTreeGroup
from qgis.core import QgsLayerTreeLayer
from qgis.core import QgsProject


def _unique_layer_ids(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        layer_id = str(value or "").strip()
        if not layer_id or layer_id in seen:
            continue
        seen.add(layer_id)
        out.append(layer_id)
    return out


def _layer_node_payload(node: QgsLayerTreeLayer, *, index: int, parent_key: str) -> dict[str, Any] | None:
    layer = node.layer()
    layer_id = str(node.layerId() or (layer.id() if layer is not None else "")).strip()
    if not layer_id:
        return None
    layer_name = str(node.name() or (layer.name() if layer is not None else layer_id)).strip() or layer_id
    key = f"{parent_key}/layer:{index}:{layer_id}" if parent_key else f"layer:{index}:{layer_id}"
    return {
        "type": "layer",
        "name": layer_name,
        "layer_id": layer_id,
        "key": key,
    }


def _group_node_payload(node: QgsLayerTreeGroup, *, index: int, parent_key: str) -> dict[str, Any]:
    group_name = str(node.name() or "Group").strip() or "Group"
    key = f"{parent_key}/group:{index}:{group_name}" if parent_key else f"group:{index}:{group_name}"
    children = _children_payload(node=node, parent_key=key)
    return {
        "type": "group",
        "name": group_name,
        "key": key,
        "children": children,
    }


def _children_payload(*, node: QgsLayerTreeGroup, parent_key: str) -> list[dict[str, Any]]:
    children: list[dict[str, Any]] = []
    for idx, child in enumerate(list(node.children() or [])):
        if isinstance(child, QgsLayerTreeGroup):
            children.append(_group_node_payload(child, index=idx, parent_key=parent_key))
            continue
        if isinstance(child, QgsLayerTreeLayer):
            layer_payload = _layer_node_payload(child, index=idx, parent_key=parent_key)
            if layer_payload is not None:
                children.append(layer_payload)
    return children


def build_project_layer_tree_snapshot(*, project: QgsProject | None = None) -> dict[str, Any]:
    """Build a deterministic, grouped tree payload matching the current project layer panel order."""
    active_project = project if project is not None else QgsProject.instance()
    root = active_project.layerTreeRoot() if active_project is not None else None
    if root is None:
        return {"nodes": []}
    return {
        "nodes": _children_payload(node=root, parent_key=""),
    }


def resolve_selected_layers_for_canvas(*, selected_layer_ids: Any, project: QgsProject | None = None) -> list[Any]:
    """Resolve selected layer ids to layer objects in project render order."""
    requested_ids = _unique_layer_ids(selected_layer_ids)
    if not requested_ids:
        return []

    active_project = project if project is not None else QgsProject.instance()
    if active_project is None:
        return []

    requested_set: set[str] = set(requested_ids)
    ordered_layers: list[Any] = []

    root = active_project.layerTreeRoot()
    render_order_layers = list(root.layerOrder() or []) if root is not None else []
    for layer in render_order_layers:
        layer_id = str(getattr(layer, "id", lambda: "")() or "").strip()
        if not layer_id or layer_id not in requested_set:
            continue
        ordered_layers.append(layer)
        requested_set.remove(layer_id)

    if requested_set:
        for layer_id in requested_ids:
            if layer_id not in requested_set:
                continue
            layer = active_project.mapLayer(layer_id)
            if layer is None:
                continue
            ordered_layers.append(layer)
            requested_set.remove(layer_id)

    return ordered_layers
