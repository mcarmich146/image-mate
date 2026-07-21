#!/usr/bin/env python3
"""Terminal smoke checks for the Mosaicking Studio backend adapter."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sys
import tempfile
import threading


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
        MosaickingLogBuffer,
        mosaicking_progress_from_log,
        normalize_mosaicking_request,
    )

    log_buffer = MosaickingLogBuffer()
    worker = threading.Thread(
        target=lambda: (
            log_buffer.publish("worker entered"),
            log_buffer.publish("engine starting"),
        )
    )
    worker.start()
    worker.join(timeout=5)
    if worker.is_alive():
        raise AssertionError("log-buffer worker did not finish")
    buffered_messages = []
    delivered = log_buffer.drain(buffered_messages.append)
    if delivered != 2 or buffered_messages != ["worker entered", "engine starting"]:
        raise AssertionError(
            f"worker-to-GUI log buffering failed: delivered={delivered} "
            f"messages={buffered_messages}"
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
        progress_values = []
        log_messages = []
        debug_messages = []
        engine_logger = logging.getLogger("seamless_mosaic")
        prior_log_level = engine_logger.level
        handler_count_before = len(engine_logger.handlers)

        def fake_runner(argv):
            args = list(argv)
            calls.append(args)
            engine_logger.info("Output grid: 100x100 x 3 bands")
            engine_logger.info("Loading bounded-resolution planning data")
            engine_logger.info("Planning source 1/2: a.tif")
            engine_logger.info("Planning source 2/2: b.tif")
            engine_logger.info("Full-resolution pass: 5/10 tiles (50.0%)")
            engine_logger.info("Building internal overviews: [2, 4]")
            output_index = args.index("--output") + 1
            output = Path(args[output_index])
            output.write_bytes(b"fake-geotiff")
            output.with_name(output.name + ".analysis.json").write_text(
                json.dumps({"status": "ok"}), encoding="utf-8"
            )
            return 0

        output = temp_dir / "result.tif"
        engine_logger.setLevel(logging.WARNING)
        result = MosaickingService(runner=fake_runner).create_mosaic(
            input_paths=[input_a, input_b, input_a],
            output_path=output,
            progress_callback=progress_values.append,
            log_callback=log_messages.append,
            debug_callback=debug_messages.append,
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
        if progress_values != [0.0, 2.0, 5.0, 12.5, 20.0, 60.0, 95.0, 100.0]:
            raise AssertionError(f"unexpected progress sequence: {progress_values}")
        if not log_messages or "Starting Mosaicker_v2" not in log_messages[0]:
            raise AssertionError(f"startup log was not delivered: {log_messages}")
        if "Mosaic output verified" not in log_messages[-1]:
            raise AssertionError(f"completion log was not delivered: {log_messages}")
        expected_debug_fragments = (
            "Service entered",
            "Normalizing and revalidating",
            "Using the injected mosaicker runner",
            "Invoking the mosaicker runner",
            "runner returned exit_code=0",
            "Output verification passed",
        )
        for fragment in expected_debug_fragments:
            if not any(fragment in message for message in debug_messages):
                raise AssertionError(
                    f"missing debug lifecycle message {fragment!r}: {debug_messages}"
                )
        if any(not message.startswith("DEBUG: ") for message in debug_messages):
            raise AssertionError(f"debug messages were not labeled: {debug_messages}")
        if len(engine_logger.handlers) != handler_count_before:
            raise AssertionError("mosaicker callback logging handler leaked after completion")
        if engine_logger.level != logging.WARNING:
            raise AssertionError("mosaicker logger level was not restored after completion")
        engine_logger.setLevel(prior_log_level)

        expected_progress = {
            "Output grid: 100x100": 2.0,
            "Planning source 2/4: example.tif": 12.5,
            "Full-resolution pass: 9/10 tiles (90.0%)": 84.0,
            "Building internal overviews: [2, 4]": 95.0,
            "Mosaic complete: result.tif": 100.0,
        }
        for message, expected in expected_progress.items():
            actual = mosaicking_progress_from_log(message)
            if actual != expected:
                raise AssertionError(
                    f"progress mapping failed for {message!r}: expected={expected} actual={actual}"
                )

        _expect_error(
            RuntimeError,
            lambda: MosaickingService(runner=lambda _argv: 2).create_mosaic(
                input_paths=[input_a, input_b], output_path=temp_dir / "failure.tif"
            ),
            "engine_exit_code",
        )

        disappearing = temp_dir / "disappearing.tif"
        disappearing.write_bytes(b"temporary")

        def remove_input_and_fail(_argv):
            disappearing.unlink()
            return 1

        try:
            MosaickingService(runner=remove_input_and_fail).create_mosaic(
                input_paths=[input_a, disappearing],
                output_path=temp_dir / "disappeared-output.tif",
            )
        except RuntimeError as exc:
            if "became unavailable" not in str(exc) or disappearing.name not in str(exc):
                raise AssertionError(f"missing-input failure was not actionable: {exc}") from exc
        else:
            raise AssertionError("expected a missing-input failure after the runner returned")

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
