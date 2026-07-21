#!/usr/bin/env python3
"""Exercise the mosaicker log buffer through a real QGIS background task."""

from __future__ import annotations

import logging
from pathlib import Path
import sys
import tempfile

from qgis.core import QgsApplication, QgsTask


def main() -> int:
    plugin_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(plugin_root))

    from image_mate_qgis_plugin.services.mosaicking_service import (  # noqa: PLC0415
        MosaickingLogBuffer,
        MosaickingService,
    )

    app = QgsApplication([], False)
    app.initQgis()
    buffer = MosaickingLogBuffer()
    outcome = []

    with tempfile.TemporaryDirectory(prefix="image_mate_qgstask_") as temp_value:
        temp_dir = Path(temp_value)
        input_a = temp_dir / "a.tif"
        input_b = temp_dir / "b.tif"
        output = temp_dir / "result.tif"
        input_a.write_bytes(b"a")
        input_b.write_bytes(b"b")

        def fake_runner(argv):
            logging.getLogger("seamless_mosaic").info(
                "Full-resolution pass: 1/1 tiles (100.0%%)"
            )
            Path(argv[argv.index("--output") + 1]).write_bytes(b"fake-geotiff")
            return 0

        service = MosaickingService(runner=fake_runner)

        def run(task):
            buffer.publish("DEBUG: QGIS background worker entered.")
            return service.create_mosaic(
                input_paths=[input_a, input_b],
                output_path=output,
                progress_callback=task.setProgress,
                log_callback=buffer.publish,
                debug_callback=buffer.publish,
            )

        def finished(exception, result=None):
            outcome.append((exception, result))

        task = QgsTask.fromFunction(
            "Image Mate mosaicker bridge smoke",
            run,
            on_finished=finished,
        )
        QgsApplication.taskManager().addTask(task)
        if not task.waitForFinished(10_000):
            raise AssertionError("QGIS mosaicker task did not finish within 10 seconds")

        messages = []
        buffer.drain(messages.append)
        if not outcome or outcome[0][0] is not None:
            raise AssertionError(f"QGIS mosaicker task failed: {outcome}")
        if not output.exists():
            raise AssertionError("QGIS mosaicker task did not create its output")
        if not any("background worker entered" in message for message in messages):
            raise AssertionError(f"worker diagnostics were not buffered: {messages}")
        if not any("Mosaic output verified" in message for message in messages):
            raise AssertionError(f"completion diagnostics were not buffered: {messages}")

    app.exitQgis()
    print("mosaicking_qgstask_bridge_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
