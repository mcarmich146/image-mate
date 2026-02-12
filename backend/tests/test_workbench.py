from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from backend.app.workbench import (
    GeoWorkbenchEngine,
    MockThirdPartyProvider,
    lint_citations,
    normalize_geometry,
    report_json_schema_check,
    scene_from_item,
    sha256_bytes,
)


def _sample_item(scene_id: str, dt: str, west: float = -122.6, south: float = 37.6) -> dict:
    east = west + 0.08
    north = south + 0.06
    return {
        "id": scene_id,
        "datetime": dt,
        "outcome_id": f"{scene_id}_outcome",
        "cloud_cover": 12.0,
        "gsd": 0.9,
        "valid_pixel_percent": 88.0,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [west, south],
                [east, south],
                [east, north],
                [west, north],
                [west, south],
            ]],
        },
        "assets": {
            "thumbnail": f"https://example.com/{scene_id}_thumb.png",
            "preview": f"https://example.com/{scene_id}_preview.png",
            "visual": f"https://example.com/{scene_id}_visual.tif",
        },
    }


class WorkbenchCoreTests(unittest.TestCase):
    def test_normalize_geometry_wraps_longitudes(self):
        geom = {
            "type": "Polygon",
            "coordinates": [[
                [220.0, 10.0],
                [221.0, 10.0],
                [221.0, 11.0],
                [220.0, 11.0],
                [220.0, 10.0],
            ]],
        }
        norm = normalize_geometry(geom)
        first_lon = norm["coordinates"][0][0][0]
        self.assertTrue(-180.0 <= first_lon <= 180.0)

    def test_provider_normalization_and_metrics_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = [
                _sample_item("scene-a", "2026-02-01T00:00:00Z"),
                _sample_item("scene-b", "2026-02-02T00:00:00Z", west=-122.5),
            ]
            by_id = {i["id"]: i for i in items}

            engine = GeoWorkbenchEngine(
                root_dir=root,
                search_items_fn=lambda payload: items,
                resolve_item_fn=lambda item_id, contract_id=None: by_id.get(item_id),
            )
            provider = MockThirdPartyProvider()
            scenes = [scene_from_item(i) for i in items]
            raw = provider.run(scenes=scenes, roi=items[0]["geometry"], analytic_types=["aircraft", "change"], params={})
            normalized = engine._normalize_provider_output(raw, provider)
            self.assertEqual(normalized["type"], "FeatureCollection")
            self.assertIn("features", normalized)

            run = {
                "run_id": "run.test",
                "artifacts": [],
            }
            engine.runs[run["run_id"]] = run
            metrics = engine._stage_metrics(run, normalized)
            self.assertIn("scene_metrics", metrics)
            self.assertIn("summary", metrics["scene_metrics"])
            self.assertGreaterEqual(metrics["scene_metrics"]["summary"]["scene_count"], 0)

    def test_citation_linter(self):
        good = (
            "## Findings\n"
            "- Change detected. [EVIDENCE scene_id=s1 captured_at=2026-01-01T00:00:00Z artifact=metrics uri=scene_metrics.json]\n"
        )
        ok, reason, _ = lint_citations(good)
        self.assertTrue(ok, reason)

        bad = "## Findings\n- Claim without reference\n"
        ok2, reason2, missing = lint_citations(bad)
        self.assertFalse(ok2)
        self.assertTrue(missing or "No evidence tokens" in reason2)

    def test_report_json_schema_check(self):
        ok, _ = report_json_schema_check(
            {
                "profile": "x",
                "summary": {},
                "findings": [],
                "confidence": {},
                "limitations": [],
                "appendix": {},
            }
        )
        self.assertTrue(ok)

        ok2, _ = report_json_schema_check({"profile": "x"})
        self.assertFalse(ok2)

    def test_workflow_graph_validation_rejects_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = GeoWorkbenchEngine(
                root_dir=root,
                search_items_fn=lambda payload: [],
                resolve_item_fn=lambda item_id, contract_id=None: None,
            )
            with self.assertRaises(ValueError):
                engine.create_or_update_workflow(
                    {
                        "workflow_id": "bad_cycle",
                        "version": "1.0.0",
                        "graph_json": {
                            "nodes": [
                                {"id": "evidence", "skill": "evidence_bundle", "depends_on": ["report"]},
                                {"id": "report", "skill": "report_writer", "depends_on": ["evidence"]},
                            ]
                        },
                        "default_params": {"profile": "airbase"},
                    }
                )

    def test_custom_workflow_graph_executes_by_node_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = [
                _sample_item("scene-a", "2026-02-01T00:00:00Z"),
                _sample_item("scene-b", "2026-02-02T00:00:00Z", west=-122.5),
            ]
            by_id = {i["id"]: i for i in items}
            engine = GeoWorkbenchEngine(
                root_dir=root,
                search_items_fn=lambda payload: items,
                resolve_item_fn=lambda item_id, contract_id=None: by_id.get(item_id),
            )
            engine.create_or_update_workflow(
                {
                    "workflow_id": "airbase_custom_graph",
                    "version": "1.1.0",
                    "graph_json": {
                        "nodes": [
                            {"id": "report", "skill": "report_writer", "depends_on": ["evidence", "metrics", "change"]},
                            {"id": "change", "skill": "change_pol", "depends_on": ["metrics"]},
                            {"id": "metrics", "skill": "scene_metrics", "depends_on": ["analytics"]},
                            {"id": "analytics", "skill": "analytics_provider", "depends_on": ["evidence"]},
                            {"id": "evidence", "skill": "evidence_bundle"},
                        ]
                    },
                    "default_params": {
                        "profile": "airbase",
                        "provider_id": "thirdparty.mock",
                        "analytic_types": ["aircraft", "change"],
                        "max_scenes": 10,
                    },
                }
            )
            run = engine.create_run(
                workflow_id="airbase_custom_graph",
                workflow_version="1.1.0",
                inputs_payload={
                    "roi": items[0]["geometry"],
                    "scene_ids": ["scene-a", "scene-b"],
                    "start_date": "2026-02-01T00:00:00Z",
                    "end_date": "2026-02-02T00:00:00Z",
                    "params": {"max_scenes": 10},
                },
            )
            deadline = time.time() + 6.0
            latest = run
            while time.time() < deadline:
                latest = engine.get_run(run["run_id"]) or latest
                if latest.get("status") in {"completed", "failed"}:
                    break
                time.sleep(0.05)
            self.assertEqual(latest.get("status"), "completed", latest.get("logs"))
            stages = [s.get("stage") for s in (latest.get("stage_progress") or [])]
            self.assertIn("evidence", stages)
            self.assertIn("analytics", stages)
            self.assertIn("metrics", stages)
            self.assertIn("change", stages)
            self.assertIn("report", stages)

    def test_forest_urban_workflow_report_contains_image_insets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = [
                _sample_item("scene-a", "2026-02-01T00:00:00Z"),
                _sample_item("scene-b", "2026-02-02T00:00:00Z", west=-122.5),
                _sample_item("scene-c", "2026-02-03T00:00:00Z", west=-122.4),
            ]
            by_id = {i["id"]: i for i in items}
            engine = GeoWorkbenchEngine(
                root_dir=root,
                search_items_fn=lambda payload: items,
                resolve_item_fn=lambda item_id, contract_id=None: by_id.get(item_id),
            )
            run = engine.create_run(
                workflow_id="forest_urban_change_series",
                workflow_version="1.0.0",
                inputs_payload={
                    "roi": items[0]["geometry"],
                    "scene_ids": ["scene-a", "scene-b", "scene-c"],
                    "start_date": "2026-02-01T00:00:00Z",
                    "end_date": "2026-02-03T00:00:00Z",
                    "params": {"max_scenes": 10},
                },
            )
            deadline = time.time() + 6.0
            latest = run
            while time.time() < deadline:
                latest = engine.get_run(run["run_id"]) or latest
                if latest.get("status") in {"completed", "failed"}:
                    break
                time.sleep(0.05)
            self.assertEqual(latest.get("status"), "completed", latest.get("logs"))
            artifacts = latest.get("artifacts") or []
            report_md_path = next(Path(str(a.get("uri"))) for a in artifacts if Path(str(a.get("uri"))).name == "report.md")
            report_md = report_md_path.read_text(encoding="utf-8")
            self.assertIn("## Image Insets", report_md)
            self.assertIn("![scene-", report_md)
            report_json_path = next(Path(str(a.get("uri"))) for a in artifacts if Path(str(a.get("uri"))).name == "report.json")
            report_json = json.loads(report_json_path.read_text(encoding="utf-8"))
            self.assertEqual(report_json.get("profile"), "Forest and Urban Change Time Series Evidence Report")
            self.assertTrue(isinstance(report_json.get("image_insets"), list))
            self.assertGreaterEqual(len(report_json.get("image_insets") or []), 1)

    def test_end_to_end_run_artifacts_with_hashes_and_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = [
                _sample_item("scene-a", "2026-02-01T00:00:00Z"),
                _sample_item("scene-b", "2026-02-02T00:00:00Z", west=-122.5),
            ]
            by_id = {i["id"]: i for i in items}
            engine = GeoWorkbenchEngine(
                root_dir=root,
                search_items_fn=lambda payload: items,
                resolve_item_fn=lambda item_id, contract_id=None: by_id.get(item_id),
            )
            run = engine.create_run(
                workflow_id="airbase_time_series_analyst",
                workflow_version="1.0.0",
                inputs_payload={
                    "roi": items[0]["geometry"],
                    "scene_ids": ["scene-a", "scene-b"],
                    "start_date": "2026-02-01T00:00:00Z",
                    "end_date": "2026-02-02T00:00:00Z",
                    "params": {"max_scenes": 10},
                },
            )

            deadline = time.time() + 6.0
            latest = run
            while time.time() < deadline:
                latest = engine.get_run(run["run_id"]) or latest
                if latest.get("status") in {"completed", "failed"}:
                    break
                time.sleep(0.05)

            self.assertEqual(latest.get("status"), "completed", latest.get("logs"))
            artifacts = latest.get("artifacts") or []
            names = {Path(str(a.get("uri"))).name for a in artifacts}
            self.assertIn("report.md", names)
            self.assertIn("report.json", names)
            self.assertIn("provenance.json", names)
            self.assertIn("hashes.txt", names)

            # Ensure stored sha256 matches content bytes.
            for art in artifacts:
                path = Path(str(art.get("uri")))
                if not path.exists():
                    continue
                digest = sha256_bytes(path.read_bytes())
                self.assertEqual(digest, art.get("sha256"))

            report_path = next(Path(str(a.get("uri"))) for a in artifacts if Path(str(a.get("uri"))).name == "report.md")
            report_md = report_path.read_text(encoding="utf-8")
            ok, reason, _ = lint_citations(report_md)
            self.assertTrue(ok, reason)

            report_json_path = next(Path(str(a.get("uri"))) for a in artifacts if Path(str(a.get("uri"))).name == "report.json")
            report_json = json.loads(report_json_path.read_text(encoding="utf-8"))
            ok2, reason2 = report_json_schema_check(report_json)
            self.assertTrue(ok2, reason2)


if __name__ == "__main__":
    unittest.main()
