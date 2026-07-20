"""Radiometric normalization workflow function plugin."""

from ..types import WorkflowFunctionSpec


def get_function_spec():
    return WorkflowFunctionSpec(
        function_id="radiometric_normalize",
        display_name="Radiometric Normalize",
        description="Normalize radiometry across scenes for visual consistency.",
        default_payload={},
    )
