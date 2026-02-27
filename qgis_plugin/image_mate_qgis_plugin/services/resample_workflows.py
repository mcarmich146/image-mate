# -*- coding: utf-8 -*-
"""Shared workflow presets for raster resampling actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple


@dataclass(frozen=True)
class ResampleWorkflowSpec:
    workflow_id: str
    action_label: str
    dialog_title: str
    operation_key: str
    default_output_hint: str
    layer_name_prefix: str
    stage_resolutions_m: Tuple[float, ...]

    def resolution_chain_label(self) -> str:
        return format_resolution_chain(self.stage_resolutions_m)


def format_resolution_m(value: float) -> str:
    return f"{float(value):g} m"


def format_resolution_chain(values: Iterable[float]) -> str:
    tokens = [format_resolution_m(value) for value in values]
    return " -> ".join(tokens)


def resolution_hint_token(value: float) -> str:
    token = f"{float(value):g}".replace(".", "p")
    return f"{token}m"


RESAMPLE_WORKFLOW_PLANETSCOPE_10P8_TO_3M = ResampleWorkflowSpec(
    workflow_id="planetscope_10p8_to_3m",
    action_label="Resample to 10.8->3m (PlanetScope)",
    dialog_title="Resample to 10.8->3m (PlanetScope)",
    operation_key="resample_planetscope_10p8_to_3m",
    default_output_hint="resample_planetscope_3m",
    layer_name_prefix="Image Mate Resample PlanetScope",
    stage_resolutions_m=(10.8, 3.0),
)

RESAMPLE_WORKFLOW_MERLIN_2M_TO_1M = ResampleWorkflowSpec(
    workflow_id="merlin_2m_to_1m",
    action_label="Resample to 2m->1m (Merlin)",
    dialog_title="Resample to 2m->1m (Merlin)",
    operation_key="resample_merlin_2m_to_1m",
    default_output_hint="resample_merlin_1m",
    layer_name_prefix="Image Mate Resample Merlin",
    stage_resolutions_m=(2.0, 1.0),
)

RESAMPLE_WORKFLOW_MERLIN_3P76M_TO_1M = ResampleWorkflowSpec(
    workflow_id="merlin_3p76m_to_1m",
    action_label="Resample to 3.76m->1m (Merlin)",
    dialog_title="Resample to 3.76m->1m (Merlin)",
    operation_key="resample_merlin_3p76m_to_1m",
    default_output_hint="resample_merlin_1m_from_3p76m",
    layer_name_prefix="Image Mate Resample Merlin",
    stage_resolutions_m=(3.76, 1.0),
)
