"""GeoTIFF export workflow function plugin."""

from ..types import WorkflowFunctionSpec


def get_function_spec():
    return WorkflowFunctionSpec(
        function_id="export_geotiff",
        display_name="Export GeoTIFF",
        description="Export downstream result as GeoTIFF.",
        default_payload={"compression": "LZW"},
    )
