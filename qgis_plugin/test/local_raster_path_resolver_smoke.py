#!/usr/bin/env python3
"""Smoke checks for local raster source path resolution logic."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile


def _repo_plugin_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _assert_equal(actual: str, expected: str, label: str) -> None:
    if str(actual) != str(expected):
        raise AssertionError(f"{label}: expected={expected} actual={actual}")


def main() -> int:
    plugin_root = _repo_plugin_root()
    sys.path.insert(0, str(plugin_root))

    from image_mate_qgis_plugin.services.local_raster_path_resolver import (  # noqa: PLC0415
        resolve_local_raster_path,
    )

    with tempfile.TemporaryDirectory(prefix="image_mate_resolver_") as temp_dir:
        temp_root = Path(temp_dir)
        vrt_path = temp_root / "sample.vrt"
        vrt_path.write_text("<VRTDataset/>", encoding="utf-8")

        nested_dir = temp_root / "nested"
        nested_dir.mkdir(parents=True, exist_ok=True)
        rel_vrt = nested_dir / "relative.vrt"
        rel_vrt.write_text("<VRTDataset/>", encoding="utf-8")

        direct = resolve_local_raster_path(
            source_candidates=[str(vrt_path)],
            project_dirs=[],
        )
        _assert_equal(direct, str(vrt_path), "direct_path")

        uri = resolve_local_raster_path(
            source_candidates=[vrt_path.as_uri()],
            project_dirs=[],
        )
        _assert_equal(uri, str(vrt_path), "file_uri")

        with_pipe = resolve_local_raster_path(
            source_candidates=[f"{vrt_path}|layerid=0"],
            project_dirs=[],
        )
        _assert_equal(with_pipe, str(vrt_path), "path_with_pipe_suffix")

        relative = resolve_local_raster_path(
            source_candidates=["nested/relative.vrt"],
            project_dirs=[str(temp_root)],
        )
        _assert_equal(relative, str(rel_vrt), "relative_path_resolution")

        remote = resolve_local_raster_path(
            source_candidates=["type=xyz&url=http://127.0.0.1:57777/tiles/{z}/{x}/{y}.png"],
            project_dirs=[str(temp_root)],
        )
        _assert_equal(remote, "", "remote_source_rejected")

    print("local_raster_path_resolver_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
