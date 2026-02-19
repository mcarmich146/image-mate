"""Loader and runtime helpers for workflow function plugins."""

import importlib
import pkgutil
from typing import Any

from . import plugins as plugins_package
from .types import WorkflowFunctionSpec


class WorkflowPluginManager:
    """Discovers workflow function plugins from the local `plugins` package."""

    def __init__(self):
        self._specs: list[WorkflowFunctionSpec] = []
        self._by_id: dict[str, WorkflowFunctionSpec] = {}
        self.reload()

    def specs(self):
        return list(self._specs)

    def get(self, function_id):
        key = str(function_id or "").strip()
        if not key:
            return None
        return self._by_id.get(key)

    def reload(self):
        loaded: list[WorkflowFunctionSpec] = []
        seen_ids: set[str] = set()
        package_name = plugins_package.__name__

        for mod_info in pkgutil.iter_modules(plugins_package.__path__):
            if mod_info.name.startswith("_"):
                continue
            full_name = f"{package_name}.{mod_info.name}"
            try:
                module = importlib.import_module(full_name)
                module = importlib.reload(module)
            except Exception:
                continue

            spec_factory = getattr(module, "get_function_spec", None)
            if spec_factory is None or not callable(spec_factory):
                continue
            try:
                raw_spec = spec_factory()
            except Exception:
                continue

            spec = self._coerce_spec(raw_spec)
            if spec is None:
                continue
            if spec.function_id in seen_ids:
                continue
            loaded.append(spec)
            seen_ids.add(spec.function_id)

        loaded.sort(key=lambda row: row.display_name.lower())
        self._specs = loaded
        self._by_id = {row.function_id: row for row in self._specs}
        return self.specs()

    @staticmethod
    def _coerce_spec(raw):
        if isinstance(raw, WorkflowFunctionSpec):
            return raw
        if not isinstance(raw, dict):
            return None

        function_id = str(raw.get("function_id") or "").strip()
        display_name = str(raw.get("display_name") or function_id).strip()
        if not function_id:
            return None

        description = str(raw.get("description") or "").strip()
        default_payload = raw.get("default_payload")
        if not isinstance(default_payload, dict):
            default_payload = {}
        on_node_double_click = raw.get("on_node_double_click")
        if on_node_double_click is not None and not callable(on_node_double_click):
            on_node_double_click = None

        return WorkflowFunctionSpec(
            function_id=function_id,
            display_name=display_name,
            description=description,
            default_payload=dict(default_payload),
            on_node_double_click=on_node_double_click,
        )

    def run_node_double_click_callback(self, function_id, node_payload, dock):
        spec = self.get(function_id)
        if spec is None or spec.on_node_double_click is None:
            return None
        payload = dict(node_payload or {})
        result = spec.on_node_double_click(
            dock=dock,
            node_payload=payload,
            function_spec=spec,
        )
        if result is None:
            return None
        if not isinstance(result, dict):
            return None
        return result
