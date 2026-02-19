"""Workflow function plugin system for the Workflows canvas."""

from .manager import WorkflowPluginManager
from .types import WorkflowFunctionSpec

__all__ = ["WorkflowPluginManager", "WorkflowFunctionSpec"]
