# -*- coding: utf-8 -*-
"""Helpers to ensure QGIS Processing is ready before running algorithms."""

from __future__ import annotations

from pathlib import Path
import importlib
import sys

from qgis.core import Qgis
from qgis.core import QgsApplication


DEFAULT_REQUIRED_ALGORITHMS = (
    "gdal:cliprasterbymasklayer",
    "gdal:buildvirtualraster",
    "native:savefeatures",
)


def ensure_processing_runtime(*, required_algorithms=None, log_callback=None):
    """Ensure QGIS Processing providers/algorithms are available.

    Returns a diagnostics dictionary with provider/algorithm readiness.
    Raises RuntimeError when Processing cannot be initialized or required
    algorithms are still unavailable after initialization.
    """

    app = QgsApplication.instance()
    if app is None:
        raise RuntimeError("QGIS runtime is not initialized (QgsApplication instance is missing).")

    required = _normalize_required_algorithms(required_algorithms)
    registry = QgsApplication.processingRegistry()
    providers_before = _provider_ids(registry)
    missing_before = _missing_required_algorithms(registry, required)
    _emit(
        log_callback,
        "Processing runtime check: "
        f"providers_before={','.join(providers_before) if providers_before else '(none)'} "
        f"required={','.join(required) if required else '(none)'} "
        f"missing_before={','.join(missing_before) if missing_before else '(none)'}",
        level=Qgis.Info,
    )
    if not missing_before:
        return {
            "ready": True,
            "initialized_processing": False,
            "providers_before": providers_before,
            "providers_after": providers_before,
            "missing_before": missing_before,
            "missing_after": [],
        }

    plugin_dir = _processing_plugin_dir()
    plugin_dir_added = _ensure_plugin_dir_on_sys_path(plugin_dir)
    if plugin_dir_added:
        _emit(log_callback, f"Added QGIS processing plugin path to sys.path: {plugin_dir}", level=Qgis.Info)

    _initialize_processing_framework(log_callback=log_callback)

    providers_after = _provider_ids(registry)
    missing_after = _missing_required_algorithms(registry, required)
    if missing_after:
        raise RuntimeError(
            "QGIS Processing is initialized but required algorithm(s) are unavailable: "
            + ", ".join(missing_after)
        )
    _emit(
        log_callback,
        "Processing runtime ready: "
        f"providers_after={','.join(providers_after) if providers_after else '(none)'}",
        level=Qgis.Info,
    )
    return {
        "ready": True,
        "initialized_processing": True,
        "providers_before": providers_before,
        "providers_after": providers_after,
        "missing_before": missing_before,
        "missing_after": [],
    }


def _normalize_required_algorithms(required_algorithms):
    values = (
        required_algorithms
        if isinstance(required_algorithms, (list, tuple, set))
        else DEFAULT_REQUIRED_ALGORITHMS
    )
    out = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _provider_ids(registry):
    out = []
    try:
        for provider in registry.providers() or []:
            provider_id = str(provider.id() or "").strip()
            if provider_id and provider_id not in out:
                out.append(provider_id)
    except Exception:
        return []
    return sorted(out)


def _missing_required_algorithms(registry, required_algorithms):
    missing = []
    for alg_id in required_algorithms or []:
        try:
            algorithm = registry.algorithmById(str(alg_id))
        except Exception:
            algorithm = None
        if algorithm is None:
            missing.append(str(alg_id))
    return missing


def _processing_plugin_dir():
    candidates = []
    prefix = str(QgsApplication.prefixPath() or "").strip()
    if prefix:
        candidates.append(Path(prefix) / "python" / "plugins")
    pkg_data = str(QgsApplication.pkgDataPath() or "").strip()
    if pkg_data:
        candidates.append(Path(pkg_data).parent / "python" / "plugins")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else Path("processing")


def _ensure_plugin_dir_on_sys_path(plugin_dir):
    text = str(plugin_dir or "").strip()
    if not text:
        return False
    norm = text.lower()
    for value in sys.path:
        if str(value or "").strip().lower() == norm:
            return False
    sys.path.insert(0, text)
    return True


def _initialize_processing_framework(*, log_callback=None):
    try:
        processing_module = importlib.import_module("processing.core.Processing")
        processing_cls = getattr(processing_module, "Processing", None)
        if processing_cls is None:
            raise RuntimeError("processing.core.Processing module does not expose Processing class")
        processing_cls.initialize()
        _emit(log_callback, "Processing framework initialized via processing.core.Processing.initialize()", level=Qgis.Info)
    except Exception as exc:
        raise RuntimeError(
            "QGIS Processing plugin is not available. Ensure the Processing plugin is installed/enabled."
        ) from exc


def _emit(callback, message, *, level=Qgis.Info):
    if callback is None:
        return
    text = str(message or "").strip()
    if not text:
        return
    try:
        callback(text, level)
    except TypeError:
        callback(text)
