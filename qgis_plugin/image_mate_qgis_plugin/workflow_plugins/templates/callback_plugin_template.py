"""Callback-enabled workflow function plugin template.

This template demonstrates the callback workflow:
1. User double-clicks a function node in the workflow canvas.
2. Plugin callback opens custom UI or file selection.
3. Callback returns updated payload dict.
4. Node payload is persisted to workflow JSON.
"""

from ..types import WorkflowFunctionSpec


def on_node_double_click(*, dock, node_payload, function_spec):
    """Return updated payload dict or None.

    API contract:
    - `dock`: `ImageMateMainDock`
      - Can call `dock.prompt_layer_selection(include_project_layers=True)` to allow
        existing QGIS project layers as plugin inputs.
    - `node_payload`: `dict[str, Any]`
    - `function_spec`: `WorkflowFunctionSpec`
    """
    updated = dict(node_payload or {})
    updated["configured"] = True
    return updated


def get_function_spec():
    return WorkflowFunctionSpec(
        function_id="my_callback_function",
        display_name="My Callback Function",
        description="Double-click node to run callback editor.",
        default_payload={"configured": False},
        on_node_double_click=on_node_double_click,
    )
