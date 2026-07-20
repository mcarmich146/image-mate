#!/usr/bin/env python3
"""Run vessel ONNX inference in an isolated Python runtime."""

from __future__ import annotations

from pathlib import Path
import sys


def main() -> int:
    plugin_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(plugin_root))
    from image_mate_qgis_plugin.services.vessel_inference_runner import main as runner_main  # noqa: PLC0415

    return int(runner_main())


if __name__ == "__main__":
    raise SystemExit(main())
