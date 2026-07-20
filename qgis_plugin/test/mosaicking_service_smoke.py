#!/usr/bin/env python3
"""Terminal smoke checks for the Mosaicking Studio backend adapter."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile


def _expect_error(exception_type, callback, label):
    try:
        callback()
    except exception_type:
        return
    raise AssertionError(f"{label}: expected {exception_type.__name__}")


def main() -> int:
    plugin_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(plugin_root))

    from image_mate_qgis_plugin.services.mosaicking_service import (  # noqa: PLC0415
        MosaickingService,
        normalize_mosaicking_request,
    )

    with tempfile.TemporaryDirectory(prefix="image_mate_mosaicking_") as temp_value:
        temp_dir = Path(temp_value)
        input_a = temp_dir / "a.tif"
        input_b = temp_dir / "b.tif"
        input_a.write_bytes(b"a")
        input_b.write_bytes(b"b")

        _expect_error(
            ValueError,
            lambda: normalize_mosaicking_request(
                input_paths=[input_a], output_path=temp_dir / "one.tif"
            ),
            "minimum_inputs",
        )
        _expect_error(
            ValueError,
            lambda: normalize_mosaicking_request(
                input_paths=[input_a, input_b], output_path=temp_dir / "bad.png"
            ),
            "output_extension",
        )
        _expect_error(
            ValueError,
            lambda: normalize_mosaicking_request(
                input_paths=[input_a, input_b], output_path=input_a, overwrite=True
            ),
            "output_is_input",
        )

        existing = temp_dir / "existing.tif"
        existing.write_bytes(b"existing")
        _expect_error(
            FileExistsError,
            lambda: normalize_mosaicking_request(
                input_paths=[input_a, input_b], output_path=existing
            ),
            "explicit_overwrite",
        )

        calls = []

        def fake_runner(argv):
            args = list(argv)
            calls.append(args)
            output_index = args.index("--output") + 1
            output = Path(args[output_index])
            output.write_bytes(b"fake-geotiff")
            output.with_name(output.name + ".analysis.json").write_text(
                json.dumps({"status": "ok"}), encoding="utf-8"
            )
            return 0

        output = temp_dir / "result.tif"
        result = MosaickingService(runner=fake_runner).create_mosaic(
            input_paths=[input_a, input_b, input_a],
            output_path=output,
        )
        if result.get("input_count") != 2:
            raise AssertionError(f"unexpected input count: {result}")
        if result.get("output_path") != str(output.resolve()):
            raise AssertionError(f"unexpected output path: {result}")
        if not str(result.get("analysis_path") or "").endswith(".analysis.json"):
            raise AssertionError(f"missing analysis path: {result}")
        args = calls[0]
        if args[:2] != [str(input_a.resolve()), str(input_b.resolve())]:
            raise AssertionError(f"input order was not preserved: {args}")
        if any(token in args for token in ("--feather", "--cloud-threshold", "--seam-method")):
            raise AssertionError(f"MVP unexpectedly overrides engine defaults: {args}")

        _expect_error(
            RuntimeError,
            lambda: MosaickingService(runner=lambda _argv: 2).create_mosaic(
                input_paths=[input_a, input_b], output_path=temp_dir / "failure.tif"
            ),
            "engine_exit_code",
        )
        _expect_error(
            RuntimeError,
            lambda: MosaickingService(runner=lambda _argv: 0).create_mosaic(
                input_paths=[input_a, input_b], output_path=temp_dir / "missing.tif"
            ),
            "missing_output",
        )

    print("mosaicking_service_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
