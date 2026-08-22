from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.analysis_store import AnalysisRecipeStore
from backend.app.monitoring_store import MonitoringStore
from backend.app.mosaic_store import MosaicStore


def _polygon():
    return {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}


class AnalystWorkspaceTests(unittest.TestCase):
    def test_recipe_store_seeds_and_validates_compatibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AnalysisRecipeStore(Path(tmp) / "analysis.sqlite3")
            recipe = store.get("recipe.aircraft-surveillance")
            self.assertIsNotNone(recipe)
            ok, _ = store.compatibility(recipe or {}, {"source_id": "satellogic", "collection": "l1d-sr", "gsd": 0.7})
            self.assertTrue(ok)
            ok, reason = store.compatibility(recipe or {}, {"source_id": "merlin-s2", "collection": "sentinel-2-l2a", "gsd": 10})
            self.assertFalse(ok)
            self.assertIn("source", reason)

    def test_monitoring_project_deduplicates_items_and_alerts(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MonitoringStore(Path(tmp) / "monitoring.sqlite3")
            project = store.create_project({"name": "Border watch", "geometry": _polygon(), "sources": [{"source_id": "satellogic"}]})
            first = store.record_project_items(project["project_id"], [{"id": "scene-1", "geometry": _polygon()}])
            second = store.record_project_items(project["project_id"], [{"id": "scene-1", "geometry": _polygon()}])
            self.assertEqual(len(first), 1)
            self.assertEqual(second, [])
            alert = store.create_alert({"project_id": project["project_id"], "source_item_id": "scene-1", "title": "New imagery"})
            self.assertEqual(store.get_open_alert_for_item(project["project_id"], "scene-1")["alert_id"], alert["alert_id"])
            action = store.create_proposed_action({"project_id": project["project_id"], "alert_id": alert["alert_id"], "action_type": "tasking"})
            approved = store.decide_proposed_action(action["action_id"], "approved", "reviewed")
            self.assertEqual(approved["status"], "approved")

    def test_public_recipe_monitoring_and_mosaic_project_routes(self):
        api = TestClient(main.app)
        with tempfile.TemporaryDirectory() as tmp:
            old_analysis = main.app.state.analysis_store
            old_monitoring = main.app.state.monitoring_store
            old_mosaic = main.app.state.mosaic_store
            main.app.state.analysis_store = AnalysisRecipeStore(Path(tmp) / "analysis.sqlite3")
            main.app.state.monitoring_store = MonitoringStore(Path(tmp) / "monitoring.sqlite3")
            main.app.state.mosaic_store = MosaicStore(Path(tmp) / "mosaic.sqlite3")
            try:
                recipes = api.get("/api/analysis/recipes")
                self.assertEqual(recipes.status_code, 200)
                recipe_id = recipes.json()["recipes"][0]["recipe_id"]
                project = api.post("/api/monitoring/projects", json={"name": "Border watch", "geometry": _polygon(), "analysis_recipe_id": recipe_id})
                self.assertEqual(project.status_code, 200, project.text)
                project_id = project.json()["project_id"]
                alerts = api.get(f"/api/monitoring/projects/{project_id}/alerts")
                self.assertEqual(alerts.status_code, 200)
                mosaic = api.post("/api/mosaics/projects", json={"name": "AOI mosaic", "source_item_ids": ["a", "b"], "output_bands": "rgb"})
                self.assertEqual(mosaic.status_code, 200, mosaic.text)
                fetched = api.get(f"/api/mosaics/projects/{mosaic.json()['project_id']}")
                self.assertEqual(fetched.json()["status"], "Draft")
            finally:
                main.app.state.analysis_store = old_analysis
                main.app.state.monitoring_store = old_monitoring
                main.app.state.mosaic_store = old_mosaic
                api.close()


if __name__ == "__main__":
    unittest.main()
