#!/usr/bin/env python3
"""Static smoke checks for Mosaic Tracking Telluric preview tile wiring."""

from __future__ import annotations

from pathlib import Path


def _assert_contains(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label}: missing snippet {needle!r}")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    streaming = (
        repo_root / "qgis_plugin" / "image_mate_qgis_plugin" / "mixins" / "search_streaming.py"
    ).read_text(encoding="utf-8")
    source_service = (
        repo_root / "qgis_plugin" / "image_mate_qgis_plugin" / "services" / "source_service.py"
    ).read_text(encoding="utf-8")
    local_proxy = (
        repo_root / "qgis_plugin" / "image_mate_qgis_plugin" / "services" / "local_tile_proxy.py"
    ).read_text(encoding="utf-8")

    _assert_contains(streaming, "def _satellogic_telluric_scene_raster_from_item(", "streaming_scene_raster_helper")
    _assert_contains(
        streaming,
        "re.match(r\"^(?P<base>.+)_\\d+_\\d+_\\d+$\", text)",
        "streaming_scene_id_suffix_normalization",
    )
    _assert_contains(
        streaming,
        "def _satellogic_scene_id_from_tif_name(",
        "streaming_scene_id_from_tif",
    )
    _assert_contains(
        streaming,
        "def _satellogic_scene_id_from_asset_href(",
        "streaming_scene_id_from_asset_href",
    )
    _assert_contains(streaming, "def _build_satellogic_telluric_stream_layer(", "streaming_telluric_layer_builder")
    _assert_contains(
        streaming,
        "/satellogic/telluric/tiles/{{z}}/{{x}}/{{y}}?",
        "streaming_telluric_xyz_url",
    )
    _assert_contains(
        streaming,
        "layer = self._build_satellogic_telluric_stream_layer(item)",
        "streaming_prefers_telluric_when_requested",
    )

    _assert_contains(
        source_service,
        "def fetch_satellogic_telluric_tile(",
        "source_service_telluric_fetch",
    )
    _assert_contains(
        source_service,
        "/telluric/scenes/",
        "source_service_telluric_endpoint",
    )
    _assert_contains(
        source_service,
        "/rasters/",
        "source_service_telluric_raster_endpoint",
    )

    _assert_contains(
        local_proxy,
        "^/satellogic/telluric/tiles/",
        "local_proxy_telluric_route_regex",
    )
    _assert_contains(
        local_proxy,
        "def _handle_telluric_tile_request(",
        "local_proxy_telluric_handler",
    )
    _assert_contains(
        local_proxy,
        "service.fetch_satellogic_telluric_tile(",
        "local_proxy_calls_source_service_telluric",
    )

    print("mosaic_tracking_preview_telluric_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
