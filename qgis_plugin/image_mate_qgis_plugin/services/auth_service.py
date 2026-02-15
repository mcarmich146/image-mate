# -*- coding: utf-8 -*-
"""Authentication wiring placeholders for QGIS Auth Manager integration."""

from qgis.PyQt.QtCore import QObject
from qgis.core import QgsApplication, QgsAuthMethodConfig


class AuthService(QObject):
    """Phase-0 placeholder.

    Next implementation step:
    - wire provider credentials to QGIS Auth Manager
    - support OAuth token refresh for supported providers
    """

    def __init__(self, parent=None):
        super().__init__(parent)

    @staticmethod
    def validate_authcfg(authcfg_id):
        value = str(authcfg_id or "").strip()
        if not value:
            return True, "not configured"
        auth_mgr = QgsApplication.authManager()
        cfg = QgsAuthMethodConfig()
        ok = bool(auth_mgr.loadAuthenticationConfig(value, cfg, True))
        if not ok or not cfg.id():
            return False, f"authcfg '{value}' not found"
        return True, f"authcfg '{value}' loaded ({cfg.method()})"

    def validate_configuration(self, provider_settings):
        sat_ok, sat_msg = self.validate_authcfg(provider_settings.satellogic_authcfg_id)
        cdse_ok, cdse_msg = self.validate_authcfg(provider_settings.cdse_authcfg_id)
        ok = sat_ok and cdse_ok
        return {
            "ok": ok,
            "message": f"satellogic={sat_msg}; cdse={cdse_msg}",
        }
