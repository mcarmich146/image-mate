# -*- coding: utf-8 -*-
"""Settings dialog for provider and auth configuration."""

from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
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

        sat_group = QGroupBox("NewSat Constellation")
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
        self.cdse_client_id = QLineEdit(str(getattr(provider_settings, "cdse_client_id", "") or ""))
        self.cdse_client_id.setPlaceholderText("CDSE OAuth client id")
        self.cdse_client_secret = QLineEdit(str(getattr(provider_settings, "cdse_client_secret", "") or ""))
        self.cdse_client_secret.setPlaceholderText("CDSE OAuth client secret")
        self.cdse_client_secret.setEchoMode(QLineEdit.Password)
        self.cdse_wmts_base_url = QLineEdit(provider_settings.cdse_wmts_base_url)
        self.cdse_wmts_instance_id = QLineEdit(provider_settings.cdse_wmts_instance_id)
        self.cdse_wmts_layer_id = QLineEdit(provider_settings.cdse_wmts_layer_id)
        self.cdse_wmts_use_backend_proxy = QCheckBox("Prefer backend WMTS proxy endpoint")
        self.cdse_wmts_use_backend_proxy.setChecked(bool(getattr(provider_settings, "cdse_wmts_use_backend_proxy", True)))
        self.cdse_authcfg_id = QLineEdit(provider_settings.cdse_authcfg_id)
        self.cdse_authcfg_id.setPlaceholderText("QGIS auth config id")

        cdse_form.addRow(self.cdse_enabled)
        cdse_form.addRow("STAC URL", self.cdse_stac_url)
        cdse_form.addRow("Client ID", self.cdse_client_id)
        cdse_form.addRow("Client Secret", self.cdse_client_secret)
        cdse_form.addRow("WMTS base URL", self.cdse_wmts_base_url)
        cdse_form.addRow("WMTS instance ID", self.cdse_wmts_instance_id)
        cdse_form.addRow("WMTS layer ID", self.cdse_wmts_layer_id)
        cdse_form.addRow(self.cdse_wmts_use_backend_proxy)
        cdse_form.addRow("Auth config ID", self.cdse_authcfg_id)

        vessel_group = QGroupBox("Vessel Detection")
        vessel_form = QFormLayout(vessel_group)
        vessel_model_widget = QWidget(self)
        vessel_model_layout = QHBoxLayout(vessel_model_widget)
        vessel_model_layout.setContentsMargins(0, 0, 0, 0)
        vessel_model_layout.setSpacing(6)
        self.vessel_model_default_path = QLineEdit(str(getattr(provider_settings, "vessel_model_default_path", "") or ""))
        self.vessel_model_browse_btn = QPushButton("Browse...")
        self.vessel_model_browse_btn.clicked.connect(self._browse_vessel_model)
        vessel_model_layout.addWidget(self.vessel_model_default_path, 1)
        vessel_model_layout.addWidget(self.vessel_model_browse_btn)

        self.vessel_conf_threshold_default = QDoubleSpinBox()
        self.vessel_conf_threshold_default.setDecimals(2)
        self.vessel_conf_threshold_default.setRange(0.01, 1.0)
        self.vessel_conf_threshold_default.setSingleStep(0.05)
        self.vessel_conf_threshold_default.setValue(float(getattr(provider_settings, "vessel_conf_threshold_default", 0.25) or 0.25))

        self.vessel_iou_threshold_default = QDoubleSpinBox()
        self.vessel_iou_threshold_default.setDecimals(2)
        self.vessel_iou_threshold_default.setRange(0.01, 1.0)
        self.vessel_iou_threshold_default.setSingleStep(0.05)
        self.vessel_iou_threshold_default.setValue(float(getattr(provider_settings, "vessel_iou_threshold_default", 0.45) or 0.45))

        self.vessel_max_detections_default = QSpinBox()
        self.vessel_max_detections_default.setRange(1, 500)
        self.vessel_max_detections_default.setValue(int(getattr(provider_settings, "vessel_max_detections_default", 20) or 20))

        vessel_form.addRow("Default ONNX Model", vessel_model_widget)
        vessel_form.addRow("Default Confidence", self.vessel_conf_threshold_default)
        vessel_form.addRow("Default IoU", self.vessel_iou_threshold_default)
        vessel_form.addRow("Default Max Detections", self.vessel_max_detections_default)

        root.addWidget(backend_group)
        root.addWidget(sat_group)
        root.addWidget(cdse_group)
        root.addWidget(vessel_group)

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
        cfg.cdse_client_id = self.cdse_client_id.text().strip()
        cfg.cdse_client_secret = self.cdse_client_secret.text().strip()
        cfg.cdse_wmts_base_url = self.cdse_wmts_base_url.text().strip()
        cfg.cdse_wmts_instance_id = self.cdse_wmts_instance_id.text().strip()
        cfg.cdse_wmts_layer_id = self.cdse_wmts_layer_id.text().strip() or "TRUE-COLOR"
        cfg.cdse_wmts_use_backend_proxy = bool(self.cdse_wmts_use_backend_proxy.isChecked())
        cfg.cdse_authcfg_id = self.cdse_authcfg_id.text().strip()
        cfg.vessel_model_default_path = self.vessel_model_default_path.text().strip()
        cfg.vessel_conf_threshold_default = float(self.vessel_conf_threshold_default.value())
        cfg.vessel_iou_threshold_default = float(self.vessel_iou_threshold_default.value())
        cfg.vessel_max_detections_default = int(self.vessel_max_detections_default.value())
        return cfg

    def _browse_vessel_model(self):
        current = str(self.vessel_model_default_path.text() or "").strip()
        file_path, _unused = QFileDialog.getOpenFileName(
            self,
            "Select Vessel ONNX Model",
            current,
            "ONNX Model (*.onnx);;All Files (*)",
        )
        file_path = str(file_path or "").strip()
        if file_path:
            self.vessel_model_default_path.setText(file_path)
