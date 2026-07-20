"""Workflow function plugin template.

Supported plugin API
1. Place plugin module under `workflow_plugins/plugins/`.
2. Expose module function:
   `get_function_spec() -> WorkflowFunctionSpec | dict`
3. Required fields:
   - `function_id`: stable string id
   - `display_name`: UI name shown in dropdown
4. Optional fields:
   - `description`: function summary
   - `default_payload`: dict serialized in workflow JSON
   - `on_node_double_click`: callback for node edit action

Node callback API
`on_node_double_click` signature:
`def on_node_double_click(*, dock, node_payload, function_spec) -> dict | None`

- `dock`: `ImageMateMainDock` instance for UI helpers/dialogs.
- `dock.prompt_layer_selection(...)` helper is available to let plugins ask for
  workflow-source and/or existing-project-layer inputs.
- `node_payload`: current payload dict for the node.
- `function_spec`: resolved `WorkflowFunctionSpec`.
- Return updated dict to persist changes, or `None` to keep unchanged.
"""

from ..types import WorkflowFunctionSpec


def get_function_spec():
    return WorkflowFunctionSpec(
        function_id="my_function_id",
        display_name="My Function",
        description="Describe the function behavior here.",
        default_payload={"example_param": "value"},
        on_node_double_click=None,
    )
