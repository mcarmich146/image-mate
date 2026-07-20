# -*- coding: utf-8 -*-
"""Controller for Image Mate side-by-side map canvas mode."""

from __future__ import annotations

from typing import Any, Callable

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import QGroupBox
from qgis.PyQt.QtWidgets import QHBoxLayout
from qgis.PyQt.QtWidgets import QInputDialog
from qgis.PyQt.QtWidgets import QLabel
from qgis.PyQt.QtWidgets import QMainWindow
from qgis.PyQt.QtWidgets import QSizePolicy
from qgis.PyQt.QtWidgets import QVBoxLayout
from qgis.PyQt.QtWidgets import QWidget
from qgis.core import QgsRectangle
from qgis.gui import QgsMapCanvas
from qgis.gui import QgsMapToolPan


class _SideBySideWindow(QMainWindow):
    """Standalone window wrapper with close/visibility signals."""

    closed = pyqtSignal()
    visibility_changed = pyqtSignal(bool)

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.visibility_changed.emit(True)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.visibility_changed.emit(False)


class _EditableViewTitleLabel(QLabel):
    """Simple double-click editable title label for each side-by-side view."""

    def __init__(self, side_key: str, text: str, parent=None):
        super().__init__(text, parent)
        self._side_key = str(side_key or "").strip().lower()
        self._double_click_callback = None
        self.setCursor(Qt.PointingHandCursor)

    def set_double_click_callback(self, callback) -> None:
        self._double_click_callback = callback

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and callable(self._double_click_callback):
            self._double_click_callback(self._side_key)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class SideBySideMapController:
    """Create, sync, and lifecycle-manage a two-canvas side-by-side map window."""

    def __init__(self, iface, mode_state_callback: Callable[[bool], None] | None = None):
        self.iface = iface
        self._mode_state_callback = mode_state_callback

        self._dock: _SideBySideWindow | None = None
        self._lhs_canvas: QgsMapCanvas | None = None
        self._rhs_canvas: QgsMapCanvas | None = None
        self._lhs_pan_tool: QgsMapToolPan | None = None
        self._rhs_pan_tool: QgsMapToolPan | None = None
        self._lhs_title_label: _EditableViewTitleLabel | None = None
        self._rhs_title_label: _EditableViewTitleLabel | None = None
        self._figure_title_label: _EditableViewTitleLabel | None = None

        self._sync_guard = False
        self._active = False
        self._last_notified_state: bool | None = None

        self._lhs_default_title = "LHS"
        self._rhs_default_title = "RHS"
        self._figure_default_title = "TITLE FOR FIGURE"
        self._lhs_custom_title = ""
        self._rhs_custom_title = ""
        self._figure_custom_title = ""

    def is_active(self) -> bool:
        dock = self._dock
        return bool(self._active and dock is not None and dock.isVisible())

    def set_mode_state_callback(self, callback: Callable[[bool], None] | None) -> None:
        self._mode_state_callback = callback

    def start(
        self,
        *,
        lhs_layers: list[Any],
        rhs_layers: list[Any],
        initial_extent=None,
        destination_crs=None,
        lhs_default_title="",
        rhs_default_title="",
        preserve_extent_if_active=False,
    ) -> None:
        self._ensure_ui()
        lhs_canvas = self._lhs_canvas
        rhs_canvas = self._rhs_canvas
        dock = self._dock
        if lhs_canvas is None or rhs_canvas is None or dock is None:
            return

        prior_extent = None
        if preserve_extent_if_active and self.is_active():
            try:
                extent = lhs_canvas.extent()
                if extent is not None and not extent.isEmpty():
                    prior_extent = QgsRectangle(extent)
            except Exception:
                prior_extent = None

        lhs_canvas.setLayers(list(lhs_layers or []))
        rhs_canvas.setLayers(list(rhs_layers or []))

        self._update_default_titles(lhs_default=lhs_default_title, rhs_default=rhs_default_title)

        if destination_crs is not None:
            try:
                if destination_crs.isValid():
                    lhs_canvas.setDestinationCrs(destination_crs)
                    rhs_canvas.setDestinationCrs(destination_crs)
            except Exception:
                pass

        launch_combined_extent = None
        if prior_extent is None:
            launch_combined_extent = self._combined_full_extent(lhs_canvas, rhs_canvas)

        seed_extent = prior_extent if prior_extent is not None else launch_combined_extent
        try:
            if seed_extent is None and initial_extent is not None and not initial_extent.isEmpty():
                seed_extent = QgsRectangle(initial_extent)
        except Exception:
            if seed_extent is None:
                seed_extent = None
        if seed_extent is None:
            seed_extent = self._seed_extent_from_canvases()

        if seed_extent is not None and not seed_extent.isEmpty():
            self._set_canvases_extent(seed_extent)
        else:
            try:
                lhs_canvas.zoomToFullExtent()
            except Exception:
                pass
            try:
                lhs_extent = lhs_canvas.extent()
                if lhs_extent is not None and not lhs_extent.isEmpty():
                    self._set_canvases_extent(QgsRectangle(lhs_extent))
            except Exception:
                pass

        self._active = True
        dock.show()
        dock.raise_()
        dock.activateWindow()
        self._notify_mode_state(True)

    def stop(self) -> None:
        was_active = bool(self._active)
        self._active = False
        dock = self._dock
        if dock is not None and dock.isVisible():
            dock.hide()
        if was_active:
            self._notify_mode_state(False)

    def cleanup(self) -> None:
        was_active = bool(self._active)
        self._active = False

        dock = self._dock
        self._dock = None
        self._lhs_canvas = None
        self._rhs_canvas = None
        self._lhs_pan_tool = None
        self._rhs_pan_tool = None
        self._lhs_title_label = None
        self._rhs_title_label = None
        self._figure_title_label = None

        if dock is not None:
            try:
                dock.closed.disconnect(self._on_dock_closed)
            except Exception:
                pass
            try:
                dock.visibility_changed.disconnect(self._on_visibility_changed)
            except Exception:
                pass
            try:
                dock.deleteLater()
            except Exception:
                pass

        if was_active:
            self._notify_mode_state(False)

    @staticmethod
    def _style_view_title(
        title_label: _EditableViewTitleLabel,
        *,
        font_scale: float = 1.5,
    ) -> None:
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        title_label.setMinimumWidth(0)
        title_label.setContentsMargins(0, 2, 0, 2)
        base_font = title_label.font()
        base_size = float(base_font.pointSizeF())
        if base_size <= 0:
            base_size = float(base_font.pointSize())
        if base_size <= 0:
            base_size = 10.0
        base_font.setPointSizeF(base_size * float(font_scale or 1.0))
        base_font.setBold(True)
        title_label.setFont(base_font)

    def _ensure_ui(self) -> None:
        if self._dock is not None and self._lhs_canvas is not None and self._rhs_canvas is not None:
            return

        dock = _SideBySideWindow(self.iface.mainWindow())
        dock.setObjectName("imageMateSideBySideMapWindow")
        dock.setWindowTitle("Image Mate Side-By-Side")
        dock.setWindowFlag(Qt.Window, True)
        dock.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)
        dock.setWindowFlag(Qt.WindowCloseButtonHint, True)
        dock.resize(1280, 760)

        root = QWidget(dock)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        body_row = QHBoxLayout()
        body_row.setContentsMargins(0, 0, 0, 0)
        body_row.setSpacing(0)

        figure_title = _EditableViewTitleLabel("figure", self._figure_default_title, root)
        figure_title.setToolTip("Double-click to rename this figure title.")
        figure_title.set_double_click_callback(self._edit_view_title)
        self._style_view_title(figure_title, font_scale=3.0)
        root_layout.addWidget(figure_title)

        lhs_group = QGroupBox(root)
        lhs_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lhs_group.setMinimumWidth(0)
        lhs_layout = QVBoxLayout(lhs_group)
        lhs_layout.setContentsMargins(6, 6, 6, 6)
        lhs_layout.setSpacing(4)
        lhs_title = _EditableViewTitleLabel("lhs", "LHS", lhs_group)
        lhs_title.setToolTip("Double-click to rename this view.")
        lhs_title.set_double_click_callback(self._edit_view_title)
        self._style_view_title(lhs_title)
        lhs_canvas = QgsMapCanvas(lhs_group)
        lhs_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lhs_canvas.setMinimumHeight(260)
        lhs_layout.addWidget(lhs_title)
        lhs_layout.addWidget(lhs_canvas, 1)

        rhs_group = QGroupBox(root)
        rhs_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        rhs_group.setMinimumWidth(0)
        rhs_layout = QVBoxLayout(rhs_group)
        rhs_layout.setContentsMargins(6, 6, 6, 6)
        rhs_layout.setSpacing(4)
        rhs_title = _EditableViewTitleLabel("rhs", "RHS", rhs_group)
        rhs_title.setToolTip("Double-click to rename this view.")
        rhs_title.set_double_click_callback(self._edit_view_title)
        self._style_view_title(rhs_title)
        rhs_canvas = QgsMapCanvas(rhs_group)
        rhs_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        rhs_canvas.setMinimumHeight(260)
        rhs_layout.addWidget(rhs_title)
        rhs_layout.addWidget(rhs_canvas, 1)

        body_row.addWidget(lhs_group, 1)
        body_row.addWidget(rhs_group, 1)
        body_row.setStretch(0, 1)
        body_row.setStretch(1, 1)

        root_layout.addLayout(body_row, 1)

        dock.setCentralWidget(root)
        dock.closed.connect(self._on_dock_closed)
        dock.visibility_changed.connect(self._on_visibility_changed)

        self._lhs_pan_tool = QgsMapToolPan(lhs_canvas)
        self._rhs_pan_tool = QgsMapToolPan(rhs_canvas)
        lhs_canvas.setMapTool(self._lhs_pan_tool)
        rhs_canvas.setMapTool(self._rhs_pan_tool)

        lhs_canvas.extentsChanged.connect(self._on_lhs_extent_changed)
        rhs_canvas.extentsChanged.connect(self._on_rhs_extent_changed)

        self._dock = dock
        self._lhs_canvas = lhs_canvas
        self._rhs_canvas = rhs_canvas
        self._lhs_title_label = lhs_title
        self._rhs_title_label = rhs_title
        self._figure_title_label = figure_title
        self._update_view_title_labels()

    def _seed_extent_from_canvases(self):
        for canvas in (self._lhs_canvas, self._rhs_canvas):
            if canvas is None:
                continue
            try:
                extent = canvas.fullExtent()
            except Exception:
                continue
            if extent is not None and not extent.isEmpty():
                return QgsRectangle(extent)
        return None

    @staticmethod
    def _combined_full_extent(lhs_canvas: QgsMapCanvas | None, rhs_canvas: QgsMapCanvas | None):
        combined_extent = None
        for canvas in (lhs_canvas, rhs_canvas):
            if canvas is None:
                continue
            try:
                extent = canvas.fullExtent()
            except Exception:
                continue
            if extent is None or extent.isEmpty():
                continue
            if combined_extent is None:
                combined_extent = QgsRectangle(extent)
            else:
                combined_extent.combineExtentWith(extent)
        return combined_extent

    def _set_canvases_extent(self, extent: QgsRectangle) -> None:
        lhs_canvas = self._lhs_canvas
        rhs_canvas = self._rhs_canvas
        if lhs_canvas is None or rhs_canvas is None:
            return
        try:
            self._sync_guard = True
            lhs_canvas.setExtent(QgsRectangle(extent))
            rhs_canvas.setExtent(QgsRectangle(extent))
        finally:
            self._sync_guard = False
        try:
            lhs_canvas.refresh()
        except Exception:
            pass
        try:
            rhs_canvas.refresh()
        except Exception:
            pass

    def _on_lhs_extent_changed(self) -> None:
        self._sync_extent(self._lhs_canvas, self._rhs_canvas)

    def _on_rhs_extent_changed(self) -> None:
        self._sync_extent(self._rhs_canvas, self._lhs_canvas)

    def _sync_extent(self, src_canvas: QgsMapCanvas | None, dst_canvas: QgsMapCanvas | None) -> None:
        if self._sync_guard or not self.is_active():
            return
        if src_canvas is None or dst_canvas is None:
            return
        try:
            extent = src_canvas.extent()
        except Exception:
            return
        if extent is None or extent.isEmpty():
            return

        try:
            self._sync_guard = True
            dst_canvas.setExtent(QgsRectangle(extent))
        finally:
            self._sync_guard = False
        try:
            dst_canvas.refresh()
        except Exception:
            pass

    def _on_dock_closed(self) -> None:
        if not self._active:
            return
        self._active = False
        self._notify_mode_state(False)

    def _on_visibility_changed(self, visible: bool) -> None:
        if bool(visible):
            return
        self._reconcile_hidden_state()

    def _notify_mode_state(self, active: bool) -> None:
        state = bool(active)
        if self._last_notified_state is not None and self._last_notified_state == state:
            return
        self._last_notified_state = state
        callback = self._mode_state_callback
        if not callable(callback):
            return
        try:
            callback(state)
        except Exception:
            pass

    def _reconcile_hidden_state(self) -> None:
        dock = self._dock
        if dock is None:
            return
        if dock.isVisible():
            return
        if not self._active:
            return
        self._active = False
        self._notify_mode_state(False)

    def _update_default_titles(self, *, lhs_default="", rhs_default="") -> None:
        lhs_text = str(lhs_default or "").strip()
        rhs_text = str(rhs_default or "").strip()
        if lhs_text:
            self._lhs_default_title = lhs_text
        if rhs_text:
            self._rhs_default_title = rhs_text
        self._update_view_title_labels()

    def _update_view_title_labels(self) -> None:
        lhs_label = self._lhs_title_label
        rhs_label = self._rhs_title_label
        figure_label = self._figure_title_label
        if lhs_label is not None:
            lhs_label.setText(str(self._lhs_custom_title or self._lhs_default_title or "LHS").strip() or "LHS")
        if rhs_label is not None:
            rhs_label.setText(str(self._rhs_custom_title or self._rhs_default_title or "RHS").strip() or "RHS")
        if figure_label is not None:
            figure_label.setText(
                str(self._figure_custom_title or self._figure_default_title or "TITLE FOR FIGURE").strip()
                or "TITLE FOR FIGURE"
            )

    def _edit_view_title(self, side_key: str) -> None:
        side = str(side_key or "").strip().lower()
        if side not in {"lhs", "rhs", "figure"}:
            return
        dock = self._dock
        if dock is None:
            return

        if side == "lhs":
            current_value = self._lhs_custom_title or self._lhs_default_title
            title = "Rename Left View"
            prompt = "Set custom title (leave empty to revert to selected top-layer name):"
        elif side == "rhs":
            current_value = self._rhs_custom_title or self._rhs_default_title
            title = "Rename Right View"
            prompt = "Set custom title (leave empty to revert to selected top-layer name):"
        else:
            current_value = self._figure_custom_title or self._figure_default_title
            title = "Rename Figure Title"
            prompt = "Set custom title (leave empty to revert to default figure title):"
        value, accepted = QInputDialog.getText(dock, title, prompt, text=str(current_value or ""))
        if not accepted:
            return
        text = str(value or "").strip()
        if side == "lhs":
            self._lhs_custom_title = text
        elif side == "rhs":
            self._rhs_custom_title = text
        else:
            self._figure_custom_title = text
        self._update_view_title_labels()
