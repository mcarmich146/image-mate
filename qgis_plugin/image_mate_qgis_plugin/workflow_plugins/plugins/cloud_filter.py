"""Cloud filter workflow function plugin."""

from ..types import WorkflowFunctionSpec


def get_function_spec():
    return WorkflowFunctionSpec(
        function_id="cloud_filter",
        display_name="Cloud Filter",
        description="Apply cloud masking or cloud threshold filtering.",
        default_payload={"max_cloud_cover": 40},
    )
