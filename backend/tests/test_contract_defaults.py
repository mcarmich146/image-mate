from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from backend.app.config import DEFAULT_SATELLOGIC_CONTRACT_ID, Settings
from backend.app.satellogic_client import SatellogicClient


class ContractDefaultTests(unittest.TestCase):
    def test_missing_blank_and_whitespace_settings_use_showcase(self):
        for value in (None, "", "   "):
            with self.subTest(value=value), patch.dict(os.environ):
                if value is None:
                    os.environ.pop("SATELLOGIC_CONTRACT_ID", None)
                else:
                    os.environ["SATELLOGIC_CONTRACT_ID"] = value
                self.assertEqual(Settings().satellogic_contract_id, DEFAULT_SATELLOGIC_CONTRACT_ID)

    def test_explicit_environment_override_is_preserved_and_trimmed(self):
        with patch.dict(os.environ, SATELLOGIC_CONTRACT_ID=" cont.intentional-override "):
            self.assertEqual(Settings().satellogic_contract_id, "cont.intentional-override")

    def test_headers_default_to_showcase_including_empty_request_contract(self):
        with patch.dict(os.environ, SATELLOGIC_CONTRACT_ID=""), \
                patch("backend.app.satellogic_client.settings", Settings()):
            client = SatellogicClient()
        with patch.object(client, "_get_access_token", return_value="test-token"):
            client.auth_mode = "oauth_client_credentials"
            for value in (None, "", "  "):
                with self.subTest(value=value):
                    self.assertEqual(
                        client.auth_headers(contract_id=value)["X-Satellogic-Contract-Id"],
                        DEFAULT_SATELLOGIC_CONTRACT_ID,
                    )
            self.assertEqual(
                client.auth_headers(contract_id="cont.explicit")["X-Satellogic-Contract-Id"],
                "cont.explicit",
            )
            self.assertNotIn("X-Satellogic-Contract-Id", client.auth_headers(include_contract=False))

    def test_contract_discovery_uses_configured_id_not_name_or_provider_order(self):
        from backend.app import main

        for display_name in ("Sales -  Showcase", "Formula1", "Renamed again"):
            with self.subTest(name=display_name), \
                    patch.object(main.settings, "satellogic_contract_id", DEFAULT_SATELLOGIC_CONTRACT_ID), \
                    patch.object(main.sources, "list_contracts", return_value=[
                        {"id": "cont.other", "name": "Other contract"},
                        {"id": DEFAULT_SATELLOGIC_CONTRACT_ID, "name": display_name},
                    ]):
                result = main.contracts(source_id="satellogic")
                self.assertEqual(result["default_contract_id"], DEFAULT_SATELLOGIC_CONTRACT_ID)
                self.assertEqual(result["contracts"][1]["name"], display_name)


if __name__ == "__main__":
    unittest.main()
