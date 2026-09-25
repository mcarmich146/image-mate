from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.agent_projects import AgentProjectService
from backend.app.monitoring_store import MonitoringStore


class AgentProjectServiceTests(unittest.TestCase):
    def _sites(self):
        return [
            {
                "site_id": "site-a",
                "name": "Alpha",
                "latitude": 10.0,
                "longitude": 20.0,
                "footprint_m": 2000,
                "original_coordinate": "10, 20",
            },
            {
                "site_id": "site-b",
                "name": "Bravo",
                "latitude": 11.0,
                "longitude": 21.0,
                "footprint_m": 1000,
            },
        ]

    def test_create_project_persists_sites_and_versioned_context_without_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = AgentProjectService(MonitoringStore(Path(tmp) / "monitoring.sqlite3"))
            project = service.create_project(
                {"project_id": "theme-alpha", "name": "Theme Alpha"},
                self._sites(),
                context_text="# Alpha\nWorking context.",
                context_sources=[{"title": "local note"}],
            )

            self.assertEqual(project["status"], "draft")
            self.assertFalse(project["enabled"])
            self.assertEqual(project["site_count"], 2)
            self.assertEqual(project["context"]["version"], 1)
            self.assertEqual(len(service.list_sites("theme-alpha")), 2)
            self.assertEqual(service.get_context("theme-alpha")["current"]["version"], 1)

            service.import_context("theme-alpha", "# Alpha v2\nUpdated.", [])
            context = service.get_context("theme-alpha", history=True)
            self.assertEqual(context["current"]["version"], 2)
            self.assertEqual([row["version"] for row in context["history"]], [2, 1])

    def test_sync_replaces_sites_and_preserves_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = AgentProjectService(MonitoringStore(Path(tmp) / "monitoring.sqlite3"))
            service.create_project({"project_id": "theme-beta", "name": "Theme Beta"}, self._sites())
            service.sync_project(
                "theme-beta",
                [{"site_id": "site-c", "name": "Charlie", "latitude": 0, "longitude": 0}],
            )
            project = service.get_project("theme-beta")
            self.assertEqual(project["site_count"], 1)
            self.assertEqual(service.list_sites("theme-beta")[0]["site_id"], "site-c")

    def test_duplicate_and_out_of_range_sites_fail_before_project_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MonitoringStore(Path(tmp) / "monitoring.sqlite3")
            service = AgentProjectService(store)
            with self.assertRaises(ValueError):
                service.create_project(
                    {"project_id": "bad", "name": "Bad"},
                    [
                        {"site_id": "same", "name": "A", "latitude": 0, "longitude": 0},
                        {"site_id": "same", "name": "B", "latitude": 0, "longitude": 0},
                    ],
                )
            self.assertEqual(store.list_projects(), [])

            with self.assertRaises(ValueError):
                service.create_project(
                    {"project_id": "bad2", "name": "Bad 2"},
                    [{"site_id": "bad", "name": "Bad", "latitude": 91, "longitude": 0}],
                )
            self.assertEqual(store.list_projects(), [])


if __name__ == "__main__":
    unittest.main()
