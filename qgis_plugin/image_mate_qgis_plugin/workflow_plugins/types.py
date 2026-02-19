"""Types for workflow function plugins."""

from dataclasses import dataclass, field
from typing import Any, Callable


NodePayload = dict[str, Any]
NodeDoubleClickCallback = Callable[..., NodePayload | None]


@dataclass
class WorkflowFunctionSpec:
    """Workflow function descriptor used by the Workflows UI."""

    function_id: str
    display_name: str
    description: str = ""
    default_payload: NodePayload = field(default_factory=dict)
    on_node_double_click: NodeDoubleClickCallback | None = None
