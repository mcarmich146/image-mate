# -*- coding: utf-8 -*-
"""Settings dialog for provider and auth configuration."""

from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
)


class SettingsDialog(QDialog):
    def __init__(self, provider_settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Image Mate Settings")
        self.resize(620, 420)

        root = QVBoxLayout(self)

        backend_group = QGroupBox("Backend Streaming")
        backend_form = QFormLayout(backend_group)
        self.backend_api_base_url = QLineEdit(provider_settings.backend_api_base_url)
        self.backend_api_base_url.setPlaceholderText("http://localhost:8000")
        backend_form.addRow("Backend API base URL", self.backend_api_base_url)

        sat_group = QGroupBox("Satellogic")
        sat_form = QFormLayout(sat_group)
        self.sat_auth_mode = QComboBox()
        self.sat_auth_mode.addItems([
            "oauth_client_credentials",
            "auto",
            "bearer",
            "key_secret",
        ])
        self.sat_auth_mode.setCurrentText(provider_settings.satellogic_auth_mode)

        self.sat_contract = QLineEdit(provider_settings.satellogic_contract_id)
        self.sat_stac_url = QLineEdit(provider_settings.satellogic_stac_url)
        self.sat_authcfg_id = QLineEdit(provider_settings.satellogic_authcfg_id)
        self.sat_authcfg_id.setPlaceholderText("QGIS auth config id")

        sat_form.addRow("Auth mode", self.sat_auth_mode)
        sat_form.addRow("Contract ID", self.sat_contract)
        sat_form.addRow("STAC URL", self.sat_stac_url)
        sat_form.addRow("Auth config ID", self.sat_authcfg_id)

        cdse_group = QGroupBox("Merlin / CDSE")
        cdse_form = QFormLayout(cdse_group)
        self.cdse_enabled = QCheckBox("Enable Merlin (Sentinel-2)")
        self.cdse_enabled.setChecked(bool(provider_settings.cdse_enabled))
        self.cdse_stac_url = QLineEdit(provider_settings.cdse_stac_url)
        self.cdse_wmts_base_url = QLineEdit(provider_settings.cdse_wmts_base_url)
        self.cdse_wmts_instance_id = QLineEdit(provider_settings.cdse_wmts_instance_id)
        self.cdse_wmts_layer_id = QLineEdit(provider_settings.cdse_wmts_layer_id)
        self.cdse_authcfg_id = QLineEdit(provider_settings.cdse_authcfg_id)
        self.cdse_authcfg_id.setPlaceholderText("QGIS auth config id")

        cdse_form.addRow(self.cdse_enabled)
        cdse_form.addRow("STAC URL", self.cdse_stac_url)
        cdse_form.addRow("WMTS base URL", self.cdse_wmts_base_url)
        cdse_form.addRow("WMTS instance ID", self.cdse_wmts_instance_id)
        cdse_form.addRow("WMTS layer ID", self.cdse_wmts_layer_id)
        cdse_form.addRow("Auth config ID", self.cdse_authcfg_id)

        root.addWidget(backend_group)
        root.addWidget(sat_group)
        root.addWidget(cdse_group)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(buttons)
        root.addLayout(btn_row)

    def apply_to(self, cfg):
        cfg.backend_api_base_url = self.backend_api_base_url.text().strip() or "http://localhost:8000"
        cfg.satellogic_auth_mode = self.sat_auth_mode.currentText().strip()
        cfg.satellogic_contract_id = self.sat_contract.text().strip()
        cfg.satellogic_stac_url = self.sat_stac_url.text().strip()
        cfg.satellogic_authcfg_id = self.sat_authcfg_id.text().strip()

        cfg.cdse_enabled = bool(self.cdse_enabled.isChecked())
        cfg.cdse_stac_url = self.cdse_stac_url.text().strip()
        cfg.cdse_wmts_base_url = self.cdse_wmts_base_url.text().strip()
        cfg.cdse_wmts_instance_id = self.cdse_wmts_instance_id.text().strip()
        cfg.cdse_wmts_layer_id = self.cdse_wmts_layer_id.text().strip() or "TRUE-COLOR"
        cfg.cdse_authcfg_id = self.cdse_authcfg_id.text().strip()
        return cfg
