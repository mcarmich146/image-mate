"""Mosaic workflow function plugin."""

from ..types import WorkflowFunctionSpec


def get_function_spec():
    return WorkflowFunctionSpec(
        function_id="mosaic",
        display_name="Mosaic",
        description="Combine multiple input rasters into a mosaic output.",
        default_payload={},
    )
