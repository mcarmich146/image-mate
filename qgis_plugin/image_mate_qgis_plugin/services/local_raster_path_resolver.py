# -*- coding: utf-8 -*-
"""Resolve local raster filesystem paths from QGIS-style source strings."""

from __future__ import annotations

from pathlib import Path
import os
import re
from urllib.parse import parse_qsl, unquote, urlparse


_REMOTE_PREFIXES = (
    "http://",
    "https://",
    "wms:",
    "wmts:",
    "xyz:",
)

_URI_PATH_KEYS = {
    "path",
    "file",
    "filename",
    "source",
    "datasource",
    "uri",
    "url",
}


def resolve_local_raster_path(*, source_candidates, project_dirs=None) -> str:
    """Return the first existing local raster path from source candidates.

    Args:
        source_candidates: Iterable of QGIS layer source strings.
        project_dirs: Optional iterable of project base directories used to
            resolve relative paths.
    """

    sources = []
    for value in source_candidates or []:
        text = str(value or "").strip()
        if text and text not in sources:
            sources.append(text)
    if not sources:
        return ""

    project_roots = _normalized_project_roots(project_dirs)

    for source in sources:
        resolved = _resolve_local_path_from_source(source, project_roots)
        if resolved:
            return resolved
    return ""


def _resolve_local_path_from_source(source: str, project_roots: list[Path]) -> str:
    text = str(source or "").strip()
    if not text:
        return ""

    base_text = text.split("|", 1)[0].strip()
    segments = [base_text]
    if base_text != text:
        segments.append(text)

    for segment in segments:
        if _looks_remote_source(segment):
            continue
        for candidate in _path_candidates(segment):
            resolved = _resolve_existing_path(candidate, project_roots)
            if resolved:
                return resolved
    return ""


def _path_candidates(segment: str) -> list[str]:
    out = []

    def _append(value: str) -> None:
        text = str(value or "").strip().strip('"').strip("'")
        if not text:
            return
        text = unquote(text)
        if text not in out:
            out.append(text)

    raw = str(segment or "").strip()
    _append(raw)

    if raw.upper().startswith(("NETCDF:", "HDF5:")):
        quoted_match = re.search(r'"([^"]+)"', raw)
        if quoted_match:
            _append(quoted_match.group(1))

    parsed = urlparse(raw)
    scheme = str(parsed.scheme or "").strip().lower()
    if scheme == "file":
        _append(_file_uri_to_path(raw))
    elif scheme in {"http", "https", "wms", "wmts", "xyz"}:
        return out

    if "=" in raw:
        normalized = raw.replace(";", "&")
        try:
            for key, value in parse_qsl(normalized, keep_blank_values=False):
                if str(key or "").strip().lower() in _URI_PATH_KEYS:
                    _append(value)
        except Exception:
            pass
        for token in raw.split("&"):
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            if str(key or "").strip().lower() in _URI_PATH_KEYS:
                _append(value)

    for match in re.findall(r'([A-Za-z]:[\\/][^|?&;]+)', raw):
        _append(match)

    if raw.startswith("/"):
        _append(raw.split("?", 1)[0].split("&", 1)[0].split(";", 1)[0])

    return out


def _resolve_existing_path(candidate: str, project_roots: list[Path]) -> str:
    text = str(candidate or "").strip().strip('"').strip("'")
    if not text:
        return ""
    if _looks_remote_source(text):
        return ""
    if text.lower().startswith("file:"):
        text = _file_uri_to_path(text)
        if not text:
            return ""

    path = Path(text)
    if path.exists():
        return str(path)
    if path.is_absolute():
        return ""

    for root in project_roots:
        combined = root / path
        if combined.exists():
            return str(combined)
    return ""


def _normalized_project_roots(project_dirs) -> list[Path]:
    roots = []
    seen = set()
    for value in project_dirs or []:
        text = str(value or "").strip().strip('"').strip("'")
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        roots.append(Path(text))
    return roots


def _looks_remote_source(value: str) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    if text.startswith(_REMOTE_PREFIXES):
        return True
    if text.startswith(("type=xyz", "type=wms", "type=wmts")):
        return True
    if "url=http://" in text or "url=https://" in text:
        return True
    return False


def _file_uri_to_path(uri: str) -> str:
    parsed = urlparse(str(uri or "").strip())
    if str(parsed.scheme or "").strip().lower() != "file":
        return str(uri or "").strip()

    netloc = unquote(str(parsed.netloc or "").strip())
    path = unquote(str(parsed.path or "").strip())
    if netloc:
        if path:
            path = f"//{netloc}{path}"
        else:
            path = netloc
    if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]
    return path
