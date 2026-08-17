from __future__ import annotations

import base64
from io import BytesIO
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from backend.app import main
from backend.app.aircraft_detector import (
    AircraftDetector,
    AircraftDetectorConfig,
    AircraftDetectorUnavailable,
    webmercator_tile_bounds,
)


class _FakeInput:
    name = "images"
    shape = [1, 3, 1024, 1024]


class _FakeSession:
    def get_inputs(self):
        return [_FakeInput()]

    def run(self, _outputs, _feed):
        # Ultralytics OBB export layout: [batch, candidates, cx cy w h scores angle].
        row = [512.0, 512.0, 240.0, 120.0, 0.95] + [0.0] * 14 + [0.0]
        return [np.asarray([[row]], dtype=np.float32)]

    def get_providers(self):
        return ["CPUExecutionProvider"]


def _png_bytes(width: int = 256, height: int = 256) -> bytes:
    image = Image.new("RGB", (width, height), (80, 100, 120))
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


class AircraftDetectorUnitTests(unittest.TestCase):
    def _detector(self) -> AircraftDetector:
        detector = AircraftDetector(
            AircraftDetectorConfig(
                model_path=main.Path("yolo11n-obb.onnx"),
                max_image_bytes=2_000_000,
            )
        )
        detector._metadata = {
            "task": "obb",
            "names": {0: "plane", 1: "ship"},
            "class_count": 15,
            "license": "AGPL-3.0",
        }
        detector._input_width = 1024
        detector._input_height = 1024
        detector._providers = ["CPUExecutionProvider"]
        return detector

    def test_auto_prefers_coreml_then_cuda_then_cpu(self):
        detector = self._detector()
        detector.config = AircraftDetectorConfig(model_path=detector.config.model_path, provider_mode="auto")
        self.assertEqual(
            detector._provider_chain(["CPUExecutionProvider", "CUDAExecutionProvider", "CoreMLExecutionProvider"]),
            ["CoreMLExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"],
        )

    def test_explicit_coreml_fails_closed_when_unavailable(self):
        detector = self._detector()
        detector.config = AircraftDetectorConfig(model_path=detector.config.model_path, provider_mode="coreml")
        with self.assertRaises(AircraftDetectorUnavailable):
            detector._provider_chain(["CPUExecutionProvider"])

    def test_webmercator_bounds_are_deterministic(self):
        bounds = webmercator_tile_bounds(0, 0, 0)
        self.assertEqual(bounds[0], -180.0)
        self.assertEqual(bounds[2], 180.0)
        self.assertAlmostEqual(bounds[1], -85.05112878, places=6)
        self.assertAlmostEqual(bounds[3], 85.05112878, places=6)

    def test_fake_obb_inference_projects_to_geojson(self):
        detector = self._detector()
        with patch.object(detector, "_load", return_value=(_FakeSession(), np)):
            result = detector.detect_bytes(
                _png_bytes(),
                provenance={"collection_id": "l1d-sr", "item_id": "item-1", "bounds": [-10, 0, 10, 10], "crs": "EPSG:4326"},
            )
        self.assertEqual(len(result["detections"]), 1)
        self.assertEqual(result["detections"][0]["class_name"], "plane")
        self.assertEqual(result["geojson"]["type"], "FeatureCollection")
        geometry = result["geojson"]["features"][0]["geometry"]
        self.assertEqual(geometry["type"], "Polygon")
        for lon, lat in geometry["coordinates"][0]:
            self.assertGreaterEqual(lon, -10)
            self.assertLessEqual(lon, 10)
            self.assertGreaterEqual(lat, 0)
            self.assertLessEqual(lat, 10)

    def test_missing_provenance_is_explicit(self):
        detector = self._detector()
        with patch.object(detector, "_load", return_value=(_FakeSession(), np)):
            result = detector.detect_bytes(_png_bytes())
        self.assertIn("missing_georeferencing", result["warnings"])
        self.assertIsNone(result["geojson"]["features"][0]["geometry"])


class AircraftDetectorApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.refresh = patch.object(main.client, "refresh_access_token", return_value=(True, None))
        cls.refresh.start()
        cls.api = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        cls.api.close()
        cls.refresh.stop()

    def test_base64_route_uses_local_detector_and_returns_no_url(self):
        fake_result = {
            "detector": "aircraft",
            "detections": [],
            "geojson": {"type": "FeatureCollection", "features": []},
            "warnings": ["missing_georeferencing"],
        }
        fake = SimpleNamespace(
            config=main.aircraft_detector.config,
            capability=lambda: {"model_exists": True, "runtime_available": True, "available_providers": ["CPUExecutionProvider"]},
            detect_bytes=lambda raw, provenance=None: fake_result,
        )
        encoded = base64.b64encode(_png_bytes()).decode("ascii")
        with patch.object(main, "aircraft_detector", fake):
            response = self.api.post(
                "/api/detectors/aircraft",
                json={"image_base64": encoded, "collection_id": "l1d-sr", "asset_key": "visual"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["detector"], "aircraft")
        self.assertNotIn("source_url", response.json())

    def test_raw_source_url_without_item_id_is_rejected(self):
        response = self.api.post(
            "/api/detectors/aircraft",
            json={
                "source_url": "s3://bucket/object.tif",
                "z": 17,
                "x": 1,
                "y": 1,
                "collection_id": "l1d-sr",
            },
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("item_id", response.json()["detail"])

    def test_wrong_collection_is_rejected_before_inference(self):
        encoded = base64.b64encode(_png_bytes()).decode("ascii")
        response = self.api.post(
            "/api/detectors/aircraft",
            json={"image_base64": encoded, "collection_id": "quickview-visual", "asset_key": "visual"},
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("l1d-sr", response.json()["detail"])

    def test_item_tile_input_resolves_visual_asset_server_side(self):
        fake_result = {
            "detector": "aircraft",
            "detections": [],
            "geojson": {"type": "FeatureCollection", "features": []},
            "warnings": [],
        }
        fake_detector = SimpleNamespace(
            config=main.aircraft_detector.config,
            capability=lambda: {"model_exists": True, "runtime_available": True},
            detect_bytes=lambda raw, provenance=None: fake_result,
        )
        fake_item = {
            "id": "item-1",
            "collection": "l1d-sr",
            "assets": {"visual": "s3://provider/l1d/item-1.tif"},
        }
        fake_upstream = SimpleNamespace(status_code=200, content=_png_bytes(), text="")
        with patch.object(main, "aircraft_detector", fake_detector), \
             patch.object(main, "_resolve_item", return_value=fake_item) as resolve_item, \
             patch.object(main, "_cog_upstream_request", return_value=(fake_upstream, "oauth_client_credentials")) as cog_request:
            response = self.api.post(
                "/api/detectors/aircraft",
                json={
                    "item_id": "item-1",
                    "source_id": "satellogic",
                    "collection_id": "l1d-sr",
                    "asset_key": "visual",
                    "z": 17,
                    "x": 100,
                    "y": 100,
                    "scale": 4,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        resolve_item.assert_called_once()
        self.assertEqual(cog_request.call_args.kwargs["source_url"], "s3://provider/l1d/item-1.tif")
        self.assertEqual(cog_request.call_args.kwargs["buffer"], 0)

    def test_runtime_endpoint_does_not_expose_model_path(self):
        response = self.api.get("/api/detectors/aircraft")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("model_path", response.json())


if __name__ == "__main__":
    unittest.main()
