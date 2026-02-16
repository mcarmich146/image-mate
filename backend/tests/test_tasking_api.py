from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import main


class TaskingApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._refresh_patcher = patch.object(main.client, "refresh_access_token", return_value=(True, None))
        cls._refresh_patcher.start()
        cls.api = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        cls.api.close()
        cls._refresh_patcher.stop()

    def test_point_tasking_e2e_status_and_acceptance(self):
        store: dict[str, object] = {"orders": [], "list_calls": 0}

        def fake_create_order(feature: dict, contract_id: str | None = None) -> dict:
            order = copy.deepcopy(feature)
            order["id"] = f"ord-{len(store['orders']) + 1:03d}"
            props = order.setdefault("properties", {})
            props["status"] = "accepted"
            props["created"] = "2026-02-13T18:20:00Z"
            store["orders"].append(order)  # type: ignore[arg-type]
            return order

        def fake_list_orders(
            contract_id: str | None = None,
            *,
            limit: int = 100,
            query: str | None = None,
            next_url: str | None = None,
        ) -> dict:
            store["list_calls"] = int(store["list_calls"]) + 1
            status = "accepted" if int(store["list_calls"]) == 1 else "programming"
            out = []
            for order in store["orders"]:  # type: ignore[assignment]
                row = copy.deepcopy(order)
                row.setdefault("properties", {})["status"] = status
                out.append(row)
            return {
                "type": "FeatureCollection",
                "features": out[:limit],
                "next": None,
            }

        def fake_get_order(order_id: str, contract_id: str | None = None) -> dict:
            for row in store["orders"]:  # type: ignore[assignment]
                if str(row.get("id")) == str(order_id):
                    result = copy.deepcopy(row)
                    result.setdefault("properties", {})["status"] = "programming"
                    return result
            raise RuntimeError("order not found")

        payload = {
            "target_type": "point",
            "geometry": {
                "type": "Point",
                "coordinates": [-122.3921, 37.6178],
            },
            "order_name": "point_task_test",
            "project_name": "project-alpha",
            "sku": "TSKPOI-M",
            "start_date": "2026-02-13T18:20:00Z",
            "end_date": "2026-02-16T18:20:00Z",
            "revisit_period": "P1D",
            "contract_id": "contract-123",
        }

        with patch.object(main.client, "create_order", side_effect=fake_create_order) as mocked_create, \
             patch.object(main.client, "list_orders", side_effect=fake_list_orders), \
             patch.object(main.client, "get_order", side_effect=fake_get_order):
            create_resp = self.api.post("/api/tasking/orders", json=payload)
            self.assertEqual(create_resp.status_code, 200, create_resp.text)
            create_body = create_resp.json()
            self.assertTrue(bool(create_body.get("accepted")))
            self.assertEqual(create_body.get("order", {}).get("id"), "ord-001")
            self.assertEqual(create_body.get("order", {}).get("status"), "accepted")
            self.assertEqual(create_body.get("order", {}).get("project_name"), "project-alpha")

            first_list = self.api.get("/api/tasking/orders?limit=20&contract_id=contract-123")
            self.assertEqual(first_list.status_code, 200, first_list.text)
            first_rows = first_list.json().get("orders", [])
            self.assertEqual(len(first_rows), 1)
            self.assertEqual(first_rows[0].get("status"), "accepted")

            second_list = self.api.get("/api/tasking/orders?limit=20&contract_id=contract-123")
            self.assertEqual(second_list.status_code, 200, second_list.text)
            second_rows = second_list.json().get("orders", [])
            self.assertEqual(len(second_rows), 1)
            self.assertEqual(second_rows[0].get("status"), "programming")

            detail = self.api.get("/api/tasking/orders/ord-001?contract_id=contract-123")
            self.assertEqual(detail.status_code, 200, detail.text)
            self.assertEqual(detail.json().get("order", {}).get("id"), "ord-001")
            self.assertEqual(detail.json().get("order", {}).get("status"), "programming")

            projects_resp = self.api.get("/api/tasking/projects?limit=20&contract_id=contract-123")
            self.assertEqual(projects_resp.status_code, 200, projects_resp.text)
            self.assertIn("project-alpha", projects_resp.json().get("projects", []))

            products_resp = self.api.get("/api/tasking/products")
            self.assertEqual(products_resp.status_code, 200, products_resp.text)
            skus = {row.get("sku") for row in products_resp.json().get("products", [])}
            self.assertIn("TSKPOI-M", skus)

            self.assertEqual(mocked_create.call_count, 1)
            kwargs = mocked_create.call_args.kwargs
            self.assertEqual(kwargs.get("contract_id"), "contract-123")

    def test_point_tasking_rejects_non_point_geometry(self):
        payload = {
            "target_type": "point",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-122.5, 37.7],
                    [-122.4, 37.7],
                    [-122.4, 37.8],
                    [-122.5, 37.8],
                    [-122.5, 37.7],
                ]],
            },
            "order_name": "bad_point_task",
            "project_name": "project-alpha",
            "sku": "TSKPOI-M",
            "start_date": "2026-02-13T18:20:00Z",
            "end_date": "2026-02-16T18:20:00Z",
        }
        response = self.api.post("/api/tasking/orders", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Point target requires Point geometry", response.json().get("detail", ""))


if __name__ == "__main__":
    unittest.main()
