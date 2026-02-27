# -*- coding: utf-8 -*-
"""Workflow UI mixin and graphics items for Image Mate main dock."""

import json
from datetime import datetime, timezone
from pathlib import Path

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtCore import QPointF
from qgis.PyQt.QtCore import QRectF
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QBrush
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtGui import QPainterPath
from qgis.PyQt.QtGui import QPen
from qgis.PyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QGroupBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsProject
from qgis.core import QgsRasterLayer



class WorkflowCanvasView(QGraphicsView):
    """Graphics view that emits delete events for selected workflow items."""

    delete_pressed = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_pressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class WorkflowNodeItem(QGraphicsRectItem):
    """Movable workflow node shown in the workflow canvas."""

    def __init__(
        self,
        node_id,
        node_type,
        label,
        payload,
        moved_callback,
        click_callback=None,
        double_click_callback=None,
    ):
        super().__init__(QRectF(0, 0, 240, 72))
        self.node_id = str(node_id or "").strip()
        self.node_type = str(node_type or "function").strip().lower() or "function"
        self.node_label = str(label or self.node_id or "Node").strip()
        self.node_payload = dict(payload or {})
        self._moved_callback = moved_callback
        self._click_callback = click_callback
        self._double_click_callback = double_click_callback

        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setZValue(2)

        fill_map = {
            "source": QColor(220, 236, 255),
            "function": QColor(224, 244, 224),
            "step": QColor(224, 244, 224),
            "adapter": QColor(255, 240, 214),
        }
        border_map = {
            "source": QColor(56, 118, 176),
            "function": QColor(80, 142, 86),
            "step": QColor(80, 142, 86),
            "adapter": QColor(184, 128, 45),
        }
        fill_color = fill_map.get(self.node_type, QColor(236, 236, 236))
        border_color = border_map.get(self.node_type, QColor(125, 125, 125))
        self._base_fill_color = QColor(fill_color)
        self._base_border_color = QColor(border_color)
        self._base_pen = QPen(self._base_border_color, 1.6)
        self.setBrush(QBrush(self._base_fill_color))
        self.setPen(self._base_pen)
        self._execution_state = "idle"

        self.label_item = QGraphicsTextItem(self.node_label, self)
        self.label_item.setDefaultTextColor(QColor(20, 20, 20))
        self.label_item.setTextWidth(self.rect().width() - 14)
        self.label_item.setPos(7, 7)

        self.meta_item = QGraphicsTextItem(self.node_type.upper(), self)
        self.meta_item.setDefaultTextColor(QColor(70, 70, 70))
        self.meta_item.setPos(7, 46)

    def set_node_label(self, label):
        self.node_label = str(label or self.node_id or "Node").strip()
        self.label_item.setPlainText(self.node_label)

    def set_execution_state(self, state):
        norm = str(state or "idle").strip().lower() or "idle"
        palette = {
            "idle": (self._base_fill_color, self._base_border_color),
            "pending": (QColor(255, 245, 204), QColor(176, 142, 36)),
            "running": (QColor(214, 236, 255), QColor(44, 110, 178)),
            "success": (QColor(214, 245, 220), QColor(42, 126, 64)),
            "error": (QColor(255, 220, 220), QColor(168, 45, 45)),
            "dim": (QColor(229, 229, 229), QColor(140, 140, 140)),
        }
        fill_color, border_color = palette.get(norm, palette["idle"])
        self._execution_state = norm
        self.setBrush(QBrush(fill_color))
        self.setPen(QPen(border_color, 1.8))
        if norm == "idle":
            self.meta_item.setPlainText(self.node_type.upper())
        else:
            self.meta_item.setPlainText(f"{self.node_type.upper()} | {norm.upper()}")

    def center_point(self):
        return self.sceneBoundingRect().center()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and self._moved_callback is not None:
            self._moved_callback(self)
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton and self._click_callback is not None:
            self._click_callback(self)

    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)
        if event.button() == Qt.LeftButton and self._double_click_callback is not None:
            self._double_click_callback(self)


class WorkflowEdgeItem(QGraphicsPathItem):
    """Directed visual edge between two workflow nodes."""

    def __init__(self, source_node, target_node):
        super().__init__()
        self.source_node = source_node
        self.target_node = target_node
        self._normal_pen = QPen(QColor(90, 90, 90), 2.4)
        self._selected_pen = QPen(QColor(198, 75, 28), 2.8)
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        self.setZValue(1)
        self.setPen(self._normal_pen)
        self.update_path()

    def update_path(self):
        if self.source_node is None or self.target_node is None:
            self.setPath(QPainterPath())
            return

        start = self.source_node.center_point()
        end = self.target_node.center_point()
        delta_x = max(abs(end.x() - start.x()) * 0.5, 40.0)
        ctrl_1 = QPointF(start.x() + delta_x, start.y())
        ctrl_2 = QPointF(end.x() - delta_x, end.y())

        path = QPainterPath(start)
        path.cubicTo(ctrl_1, ctrl_2, end)
        self.setPath(path)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self.setPen(self._selected_pen if bool(value) else self._normal_pen)
        return super().itemChange(change, value)


class WorkflowDockMixin:
    def _build_workflow_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.workflow_tabs = QTabWidget()
        self.workflow_canvas_tab = self._build_workflow_canvas_tab()
        self.workflow_log_tab = self._build_workflow_log_tab()
        self.workflow_tabs.addTab(self.workflow_canvas_tab, "Canvas")
        self.workflow_tabs.addTab(self.workflow_log_tab, "Execution Log")

        layout.addWidget(self.workflow_tabs, 1)
        return tab

    def _build_workflow_source_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        source_group = QGroupBox("Workflow Source Selection")
        source_form = QFormLayout(source_group)
        self.workflow_source_mode_combo = QComboBox()
        self.workflow_source_mode_combo.addItem("Single Image", "single")
        self.workflow_source_mode_combo.addItem("Stack (Checked Results)", "stack")
        self.workflow_source_mode_combo.currentIndexChanged.connect(self._on_workflow_source_mode_changed)

        self.workflow_single_source_combo = QComboBox()
        self.workflow_single_source_combo.setMinimumWidth(0)
        self.workflow_stack_source_combo = QComboBox()
        self.workflow_stack_source_combo.setMinimumWidth(0)

        self.workflow_checked_summary = QLabel("Checked results: 0")
        self.workflow_checked_summary.setWordWrap(True)

        source_form.addRow("Source Type", self.workflow_source_mode_combo)
        source_form.addRow("Single Image", self.workflow_single_source_combo)
        source_form.addRow("Image Stack", self.workflow_stack_source_combo)
        source_form.addRow("Stack Status", self.workflow_checked_summary)

        add_source_btn = QPushButton("Add Source Node to Canvas")
        add_source_btn.clicked.connect(self._add_selected_source_node)
        self.workflow_add_source_btn = add_source_btn

        help_text = QLabel(
            "In Explore > Results, check multiple rows to build a stack.\n"
            "Use 'Single Image' for one item or 'Stack' for all checked items."
        )
        help_text.setWordWrap(True)

        layout.addWidget(source_group)
        layout.addWidget(help_text)
        layout.addWidget(add_source_btn)
        layout.addStretch(1)
        return tab

    def _build_workflow_canvas_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        source_controls = QHBoxLayout()
        self.workflow_source_mode_combo = QComboBox()
        self.workflow_source_mode_combo.addItem("Single Image", "single")
        self.workflow_source_mode_combo.addItem("Temporal Stack", "stack")
        self.workflow_source_mode_combo.addItem("Mosaic-Bundle", "mosaic_bundle")
        self.workflow_source_mode_combo.addItem("Multi-Temporal Stacks", "multi_temporal_stacks")
        self.workflow_source_mode_combo.currentIndexChanged.connect(self._on_workflow_source_mode_changed)
        mode_model = self.workflow_source_mode_combo.model()
        if mode_model is not None:
            for idx in (2, 3):
                model_item = mode_model.item(idx)
                if model_item is not None:
                    model_item.setEnabled(False)

        add_source_btn = QPushButton("Add Source")
        add_source_btn.clicked.connect(self._add_selected_source_node)
        self.workflow_add_source_btn = add_source_btn

        source_controls.addWidget(QLabel("Source"))
        source_controls.addWidget(self.workflow_source_mode_combo, 1)
        source_controls.addWidget(add_source_btn)

        function_controls = QHBoxLayout()
        self.workflow_function_combo = QComboBox()
        self.workflow_function_combo.setMinimumWidth(0)

        refresh_functions_btn = QPushButton("Refresh Functions")
        refresh_functions_btn.clicked.connect(self._reload_workflow_functions)
        add_function_btn = QPushButton("Add Function Node")
        add_function_btn.clicked.connect(self._add_selected_function_node)
        self.workflow_refresh_functions_btn = refresh_functions_btn
        self.workflow_add_function_btn = add_function_btn

        self.workflow_connect_btn = QPushButton("Connect Nodes")
        self.workflow_connect_btn.clicked.connect(self._toggle_workflow_connect_mode)

        delete_btn = QPushButton("Delete Selected")
        delete_btn.clicked.connect(self._delete_selected_workflow_items)
        self.workflow_delete_btn = delete_btn

        function_controls.addWidget(QLabel("Function"))
        function_controls.addWidget(self.workflow_function_combo, 1)
        function_controls.addWidget(refresh_functions_btn)
        function_controls.addWidget(add_function_btn)

        action_controls = QHBoxLayout()
        execute_btn = QPushButton("Execute Workflow")
        execute_btn.setStyleSheet("font-weight: 700;")
        execute_btn.clicked.connect(self._execute_workflow)
        self.workflow_execute_btn = execute_btn
        save_btn = QPushButton("Save Workflow")
        save_btn.clicked.connect(self._save_workflow_json)
        load_btn = QPushButton("Load Workflow")
        load_btn.clicked.connect(self._load_workflow_json)
        self.workflow_save_btn = save_btn
        self.workflow_load_btn = load_btn

        action_controls.addWidget(self.workflow_connect_btn)
        action_controls.addWidget(delete_btn)
        action_controls.addWidget(save_btn)
        action_controls.addWidget(load_btn)
        action_controls.addWidget(execute_btn)
        action_controls.addStretch(1)

        self.workflow_canvas = WorkflowCanvasView(self._workflow_scene)
        self.workflow_canvas.setSceneRect(0, 0, 2000, 1400)
        self.workflow_canvas.setDragMode(QGraphicsView.RubberBandDrag)
        self.workflow_canvas.setFocusPolicy(Qt.StrongFocus)
        self.workflow_canvas.setMinimumHeight(320)
        self.workflow_canvas.delete_pressed.connect(self._delete_selected_workflow_items)
        self.workflow_canvas.setToolTip(
            "Drag nodes to move. Press Delete to remove selected node/edge. "
            "Click 'Connect Nodes' then click node 1 and node 2 to connect."
        )

        layout.addLayout(source_controls)
        layout.addLayout(function_controls)
        layout.addLayout(action_controls)
        layout.addWidget(self.workflow_canvas, 1)
        return tab

    def _build_workflow_log_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.workflow_status_label = QLabel("")
        self.workflow_status_label.setWordWrap(True)
        self.workflow_progress_bar = QProgressBar()
        self.workflow_progress_bar.setRange(0, 100)
        self.workflow_progress_bar.setValue(0)
        self.workflow_progress_bar.setFormat("%p%")
        self.workflow_execution_log = QTextEdit()
        self.workflow_execution_log.setReadOnly(True)
        self.workflow_execution_log.setPlaceholderText("Workflow execution log will appear here.")

        layout.addWidget(self.workflow_status_label)
        layout.addWidget(self.workflow_progress_bar)
        layout.addWidget(self.workflow_execution_log, 1)
        return tab

    def _refresh_workflow_source_options(self):
        if not hasattr(self, "workflow_single_source_combo"):
            return

        prior_single = str(self.workflow_single_source_combo.currentData() or "").strip()
        self.workflow_single_source_combo.blockSignals(True)
        self.workflow_single_source_combo.clear()
        for row in self._result_rows:
            row_label = str(row.get("label") or "").strip()
            row_item_id = str(row.get("item_id") or "").strip()
            if not row_item_id:
                continue
            self.workflow_single_source_combo.addItem(row_label, row_item_id)
        if self.workflow_single_source_combo.count() == 0:
            self.workflow_single_source_combo.addItem("No search results available", "")
        elif prior_single:
            idx = self.workflow_single_source_combo.findData(prior_single)
            if idx >= 0:
                self.workflow_single_source_combo.setCurrentIndex(idx)
        self.workflow_single_source_combo.blockSignals(False)

        self.workflow_stack_source_combo.blockSignals(True)
        self.workflow_stack_source_combo.clear()
        checked_rows = []
        for row in self._result_rows:
            row_item_id = str(row.get("item_id") or "").strip()
            if row_item_id and row_item_id in self._checked_result_ids:
                checked_rows.append(row)
        checked_item_ids = [str(row.get("item_id") or "").strip() for row in checked_rows]
        checked_item_ids = [row_id for row_id in checked_item_ids if row_id]
        if checked_item_ids:
            self.workflow_stack_source_combo.addItem(
                f"Checked stack ({len(checked_item_ids)} images)",
                checked_item_ids,
            )
        else:
            self.workflow_stack_source_combo.addItem("No checked results available", [])
        self.workflow_stack_source_combo.blockSignals(False)

        if hasattr(self, "workflow_checked_summary"):
            self.workflow_checked_summary.setText(f"Checked results: {len(checked_item_ids)}")

    def _on_workflow_source_mode_changed(self):
        if not hasattr(self, "workflow_source_mode_combo"):
            return
        mode = str(self.workflow_source_mode_combo.currentData() or "single").strip()
        single_mode = mode != "stack"
        if hasattr(self, "workflow_single_source_combo"):
            self.workflow_single_source_combo.setEnabled(single_mode)
        if hasattr(self, "workflow_stack_source_combo"):
            self.workflow_stack_source_combo.setEnabled(not single_mode)

    def _set_workflow_hint(self, text):
        if hasattr(self, "workflow_status_label"):
            self.workflow_status_label.setText(str(text or "").strip())

    def append_workflow_execution_log(self, text):
        if not hasattr(self, "workflow_execution_log"):
            return
        message = str(text or "").strip()
        if not message:
            return
        stamp = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
        self.workflow_execution_log.append(f"[{stamp}] {message}")
        QApplication.processEvents()

    def clear_workflow_execution_log(self):
        if hasattr(self, "workflow_execution_log"):
            self.workflow_execution_log.clear()

    def set_workflow_execution_progress(self, completed, total, status_text=""):
        if hasattr(self, "workflow_progress_bar"):
            total_steps = max(1, int(total or 1))
            done = max(0, min(int(completed or 0), total_steps))
            percent = int(round((float(done) / float(total_steps)) * 100.0))
            self.workflow_progress_bar.setValue(percent)
            self.workflow_progress_bar.setFormat(f"{percent}% ({done}/{total_steps})")
        if status_text:
            self._set_workflow_hint(status_text)
        QApplication.processEvents()

    def set_workflow_node_execution_state(self, node_id, state):
        node_key = str(node_id or "").strip()
        node = self._workflow_nodes.get(node_key)
        if node is None:
            return
        node.set_execution_state(state)
        QApplication.processEvents()

    def set_workflow_active_node(self, node_id):
        active_id = str(node_id or "").strip()
        for current_id, node in self._workflow_nodes.items():
            current_state = str(getattr(node, "_execution_state", "idle") or "idle").strip().lower()
            if not active_id:
                if current_state == "dim":
                    node.set_execution_state("pending")
                continue
            if current_id == active_id:
                if current_state not in {"running", "success", "error"}:
                    node.set_execution_state("running")
            else:
                if current_state in {"pending", "running", "idle", "dim"}:
                    node.set_execution_state("dim")
        QApplication.processEvents()

    def set_workflow_canvas_locked(self, locked):
        is_locked = bool(locked)
        self._workflow_canvas_locked = is_locked
        if is_locked and self._workflow_connect_mode_active:
            self._cancel_workflow_connect_mode("")
        for attr_name in [
            "workflow_source_mode_combo",
            "workflow_single_source_combo",
            "workflow_stack_source_combo",
            "workflow_add_source_btn",
            "workflow_function_combo",
            "workflow_refresh_functions_btn",
            "workflow_add_function_btn",
            "workflow_connect_btn",
            "workflow_delete_btn",
            "workflow_execute_btn",
            "workflow_save_btn",
            "workflow_load_btn",
        ]:
            widget = getattr(self, attr_name, None)
            if widget is not None:
                widget.setEnabled(not is_locked)
        canvas = getattr(self, "workflow_canvas", None)
        if canvas is not None:
            canvas.setInteractive(not is_locked)
            canvas.setDragMode(QGraphicsView.NoDrag if is_locked else QGraphicsView.RubberBandDrag)
        QApplication.processEvents()

    def reset_workflow_execution_visuals(self, clear_log=False):
        if clear_log:
            self.clear_workflow_execution_log()
        if hasattr(self, "workflow_progress_bar"):
            self.workflow_progress_bar.setValue(0)
            self.workflow_progress_bar.setFormat("0%")
        for node in self._workflow_nodes.values():
            node.set_execution_state("idle")
        QApplication.processEvents()

    def prompt_layer_selection(
        self,
        *,
        title="Select Input Layer",
        include_project_layers=False,
        include_workflow_sources=True,
    ):
        options = []

        if include_workflow_sources:
            for node in self._workflow_nodes.values():
                if node.node_type != "source":
                    continue
                options.append(
                    (
                        f"Workflow Source | {node.node_label} ({node.node_id})",
                        {
                            "kind": "workflow_source_node",
                            "node_id": node.node_id,
                            "node_label": node.node_label,
                        },
                    )
                )

        if include_project_layers:
            for layer in QgsProject.instance().mapLayers().values():
                layer_id = str(layer.id() or "").strip()
                if not layer_id:
                    continue
                options.append(
                    (
                        f"Project Layer | {layer.name()} ({layer_id})",
                        {
                            "kind": "project_layer",
                            "layer_id": layer_id,
                            "layer_name": str(layer.name() or "").strip(),
                        },
                    )
                )

        if not options:
            QMessageBox.warning(
                self,
                title,
                "No eligible input layers found. Add a source node or enable project-layer selection.",
            )
            return None

        labels = [row[0] for row in options]
        selected_label, ok = QInputDialog.getItem(
            self,
            title,
            "Input Source/Layer",
            labels,
            0,
            False,
        )
        if not ok:
            return None
        selected_label = str(selected_label or "").strip()
        for label, payload in options:
            if label == selected_label:
                return dict(payload)
        return None

    @staticmethod
    def _workflow_outputfile_token_specs(grouping_type):
        mode = str(grouping_type or "single").strip().lower()
        stack_like_modes = {
            "stack",
            "mosaic_bundle",
            "multi_temporal_stacks",
            "multi_stack",
            "bundle",
            "auto",
            "any",
        }
        if mode not in stack_like_modes:
            return []
        return [
            ("{index}", "1-based output index"),
            ("{index_03}", "1-based output index with zero padding (001, 002, ...)"),
            ("{item_id}", "Source item id"),
            ("{collection_date}", "Collection date token"),
            ("{collection_datetime}", "Collection datetime token"),
            ("{logical_source_key}", "Logical source key token"),
        ]

    @staticmethod
    def _insert_token_into_line_edit(line_edit, token_text):
        target = line_edit if isinstance(line_edit, QLineEdit) else None
        token = str(token_text or "").strip()
        if target is None or not token:
            return
        current = str(target.text() or "")
        cursor_pos = int(target.cursorPosition())
        cursor_pos = max(0, min(cursor_pos, len(current)))
        updated = f"{current[:cursor_pos]}{token}{current[cursor_pos:]}"
        target.setText(updated)
        target.setCursorPosition(cursor_pos + len(token))
        target.setFocus()

    def request_outputfile_ui(
        self,
        *,
        parent,
        grouping_type="single",
        placeholder_text="Select output file path...",
        browse_caption="Select Output File",
        file_filter="All files (*.*)",
        default_suffix="",
        initial_path="",
    ):
        suffix = str(default_suffix or "").strip()
        if suffix and not suffix.startswith("."):
            suffix = f".{suffix}"
        initial_value = str(initial_path or "").strip()

        container = QWidget(parent)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(4)

        row_widget = QWidget(container)
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        path_edit = QLineEdit(row_widget)
        path_edit.setPlaceholderText(str(placeholder_text or "").strip() or "Select output file path...")
        path_edit.setMinimumWidth(0)
        if initial_value:
            path_edit.setText(initial_value)

        browse_btn = QPushButton("Browse...", row_widget)

        def _browse_output_file():
            current = str(path_edit.text() or "").strip()
            fallback_name = f"output{suffix}" if suffix else "output"
            start_file = current or initial_value or fallback_name
            selected_path, _ = QFileDialog.getSaveFileName(
                parent or self,
                str(browse_caption or "Select Output File"),
                start_file,
                str(file_filter or "All files (*.*)"),
            )
            selected_path = str(selected_path or "").strip()
            if not selected_path:
                return
            if suffix and not Path(selected_path).suffix:
                selected_path = f"{selected_path}{suffix}"
            path_edit.setText(selected_path)

        browse_btn.clicked.connect(_browse_output_file)

        row_layout.addWidget(path_edit, 1)
        row_layout.addWidget(browse_btn)
        container_layout.addWidget(row_widget)

        token_specs = self._workflow_outputfile_token_specs(grouping_type)
        if token_specs:
            token_widget = QWidget(container)
            token_layout = QHBoxLayout(token_widget)
            token_layout.setContentsMargins(0, 0, 0, 0)
            token_layout.setSpacing(4)
            token_layout.addWidget(QLabel("Supported tokens:", token_widget))
            for token, tooltip in token_specs:
                token_btn = QPushButton(str(token), token_widget)
                token_btn.setToolTip(str(tooltip))
                token_btn.clicked.connect(
                    lambda _checked=False, tok=str(token): self._insert_token_into_line_edit(path_edit, tok)
                )
                token_layout.addWidget(token_btn)
            token_layout.addStretch(1)
            container_layout.addWidget(token_widget)
            path_edit.setToolTip(
                "Click a token button to insert it into the output path at the cursor position."
            )

        return {
            "widget": container,
            "line_edit": path_edit,
            "browse_button": browse_btn,
            "token_specs": token_specs,
            "default_suffix": suffix,
            "grouping_type": str(grouping_type or "").strip().lower(),
        }

    def _reload_workflow_functions(self):
        self._workflow_function_specs = self._workflow_plugin_manager.reload()
        self._refresh_workflow_function_options()

    def _refresh_workflow_function_options(self):
        if not hasattr(self, "workflow_function_combo"):
            return

        prior_id = str(self.workflow_function_combo.currentData() or "").strip()
        self.workflow_function_combo.blockSignals(True)
        self.workflow_function_combo.clear()

        for spec in self._workflow_function_specs:
            self.workflow_function_combo.addItem(spec.display_name, spec.function_id)

        if self.workflow_function_combo.count() == 0:
            self.workflow_function_combo.addItem("No function plugins found", "")

        if prior_id:
            idx = self.workflow_function_combo.findData(prior_id)
            if idx >= 0:
                self.workflow_function_combo.setCurrentIndex(idx)

        self.workflow_function_combo.blockSignals(False)

    def _selected_workflow_function_spec(self):
        function_id = str(self.workflow_function_combo.currentData() or "").strip()
        if not function_id:
            return None
        return self._workflow_plugin_manager.get(function_id)

    @staticmethod
    def _function_node_label(spec, payload):
        suffix = ""
        if spec.function_id == "clip_to_aoi":
            aoi_source_type = str(payload.get("aoi_source_type") or "").strip().lower()
            aoi_layer_name = str(payload.get("aoi_project_layer_name") or "").strip()
            aoi_name = str(payload.get("aoi_file_name") or "").strip()
            aoi_path = str(payload.get("aoi_path") or "").strip()
            output_path = str(payload.get("output_path") or "").strip()
            output_name = str(payload.get("output_file_name") or "").strip()
            output_hint = str(payload.get("output_name_hint") or "").strip()
            if not output_name and output_path:
                output_name = Path(output_path).name
            if not output_name and output_hint:
                output_name = output_hint
            if aoi_source_type == "project_layer" and aoi_layer_name:
                aoi_name = aoi_layer_name
            elif aoi_source_type == "canvas":
                aoi_name = "Canvas Extent"
            if not aoi_name and aoi_path:
                aoi_name = Path(aoi_path).name
            parts = []
            if aoi_name:
                parts.append(f"AOI={aoi_name}")
            if output_name:
                parts.append(f"OUT={output_name}")
            else:
                parts.append("OUT=auto")
            if parts:
                suffix = f" [{', '.join(parts)}]"
        elif spec.function_id == "temporal_stack_to_video":
            output_path = str(payload.get("output_path") or "").strip()
            output_name = str(payload.get("output_file_name") or "").strip()
            output_hint = str(payload.get("output_name_hint") or "").strip()
            if not output_name and output_path:
                output_name = Path(output_path).name
            if not output_name and output_hint:
                output_name = output_hint
            fps_value = payload.get("frames_per_second")
            pause_value = payload.get("pause_between_dates_seconds")
            parts = []
            if output_name:
                parts.append(f"OUT={output_name}")
            else:
                parts.append("OUT=auto")
            try:
                parts.append(f"FPS={int(fps_value)}")
            except Exception:
                pass
            try:
                pause_float = float(pause_value)
                if pause_float > 0.0:
                    parts.append(f"PAUSE={pause_float:g}s")
            except Exception:
                pass
            if parts:
                suffix = f" [{', '.join(parts)}]"
        return f"Function {spec.display_name}{suffix}"

    @classmethod
    def _adapter_node_label(cls, payload):
        adapter_payload = payload if isinstance(payload, dict) else {}
        adapter_id = str(adapter_payload.get("adapter_id") or "").strip()
        adapter_name = str(adapter_payload.get("adapter_name") or "").strip()
        adapted_name = str(
            adapter_payload.get("adapted_function_name")
            or adapter_payload.get("adapted_function_id")
            or ""
        ).strip()
        if adapter_id == cls.ADAPTER_ID_FOR_EACH_IMAGE_IN_STACK:
            if adapted_name:
                return f"Adapter {cls.ADAPTER_NAME_FOR_EACH_IMAGE_IN_STACK} -> {adapted_name}"
            return f"Adapter {cls.ADAPTER_NAME_FOR_EACH_IMAGE_IN_STACK}"
        if adapter_name:
            if adapted_name:
                return f"Adapter {adapter_name} -> {adapted_name}"
            return f"Adapter {adapter_name}"
        if adapter_id:
            if adapted_name:
                return f"Adapter {adapter_id} -> {adapted_name}"
            return f"Adapter {adapter_id}"
        return "Adapter"

    @staticmethod
    def _source_node_mode(payload):
        node_payload = payload if isinstance(payload, dict) else {}
        mode = str(node_payload.get("mode") or "single").strip().lower()
        if mode in {"single", "stack"}:
            return mode
        item_ids = ImageMateMainDock._coerce_str_list(node_payload.get("item_ids"))
        return "stack" if len(item_ids) > 1 else "single"

    @classmethod
    def _source_node_label(cls, payload, *, include_selected=True):
        node_payload = payload if isinstance(payload, dict) else {}
        mode = cls._source_node_mode(node_payload)
        item_ids = cls._coerce_str_list(node_payload.get("item_ids"))
        if mode == "stack":
            if include_selected and item_ids:
                return f"Source Stack ({len(item_ids)} images)"
            return "Source Stack (select images)"
        if include_selected and item_ids:
            return f"Source {item_ids[0]}"
        return "Source (select image)"

    def _workflow_search_result_options(self):
        options = []
        for row in self._result_rows:
            item_id = str(row.get("item_id") or "").strip()
            label = str(row.get("label") or "").strip()
            if not item_id:
                continue
            options.append((item_id, label or item_id))
        return options

    def _prompt_source_single_item_id(self, initial_item_id=""):
        options = self._workflow_search_result_options()
        if not options:
            QMessageBox.warning(
                self,
                "No Search Results",
                "Run a search first, then double-click the source node to pick an image.",
            )
            return None

        labels = [label for _item_id, label in options]
        selected_idx = 0
        initial = str(initial_item_id or "").strip()
        if initial:
            for idx, (item_id, _label) in enumerate(options):
                if item_id == initial:
                    selected_idx = idx
                    break

        chosen_label, accepted = QInputDialog.getItem(
            self,
            "Select Source Image",
            "Search Results",
            labels,
            selected_idx,
            False,
        )
        if not accepted:
            return None
        chosen_text = str(chosen_label or "").strip()
        for item_id, label in options:
            if label == chosen_text:
                return item_id
        return None

    def _prompt_source_stack_item_ids(self, initial_item_ids):
        options = self._workflow_search_result_options()
        if not options:
            QMessageBox.warning(
                self,
                "No Search Results",
                "Run a search first, then double-click the source node to pick images.",
            )
            return None

        initial_set = set(self._coerce_str_list(initial_item_ids))
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Source Stack")
        dialog.resize(760, 420)
        layout = QVBoxLayout(dialog)

        desc = QLabel("Select one or more images from current search results.")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        list_widget = QListWidget(dialog)
        list_widget.setMinimumHeight(280)
        for item_id, label in options:
            item = QListWidgetItem(label, list_widget)
            item.setData(Qt.UserRole, item_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if item_id in initial_set else Qt.Unchecked)
        layout.addWidget(list_widget, 1)

        quick_row = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        clear_btn = QPushButton("Clear All")
        quick_row.addWidget(select_all_btn)
        quick_row.addWidget(clear_btn)
        quick_row.addStretch(1)
        layout.addLayout(quick_row)

        def _set_all(check_state):
            for idx in range(list_widget.count()):
                row_item = list_widget.item(idx)
                if row_item is not None:
                    row_item.setCheckState(check_state)

        select_all_btn.clicked.connect(lambda: _set_all(Qt.Checked))
        clear_btn.clicked.connect(lambda: _set_all(Qt.Unchecked))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return None

        selected_ids = []
        for idx in range(list_widget.count()):
            row_item = list_widget.item(idx)
            if row_item is None or row_item.checkState() != Qt.Checked:
                continue
            row_item_id = str(row_item.data(Qt.UserRole) or "").strip()
            if row_item_id:
                selected_ids.append(row_item_id)

        if not selected_ids:
            QMessageBox.warning(self, "No Sources Selected", "Select at least one image for stack mode.")
            return None
        return selected_ids

    def _edit_source_node_selection(self, node_item):
        if node_item is None:
            return

        node_payload = dict(node_item.node_payload or {})
        mode = self._source_node_mode(node_payload)
        current_ids = self._coerce_str_list(node_payload.get("item_ids"))

        if mode == "stack":
            selected_ids = self._prompt_source_stack_item_ids(current_ids)
            if selected_ids is None:
                return
            node_payload["mode"] = "stack"
            node_payload["item_ids"] = list(selected_ids)
        else:
            initial_id = current_ids[0] if current_ids else ""
            selected_id = self._prompt_source_single_item_id(initial_id)
            if selected_id is None:
                return
            node_payload["mode"] = "single"
            node_payload["item_ids"] = [selected_id]

        node_item.node_payload = dict(node_payload)
        node_item.set_node_label(self._source_node_label(node_payload, include_selected=True))
        self._set_workflow_hint(f"Updated source node: {node_item.node_id}")

    def _toggle_workflow_connect_mode(self):
        if self._workflow_canvas_locked:
            self._set_workflow_hint("Workflow is executing; canvas editing is locked.")
            return
        if self._workflow_connect_mode_active:
            self._cancel_workflow_connect_mode("Connect mode cancelled.")
            return
        self._workflow_connect_mode_active = True
        self._workflow_connect_source_node_id = ""
        if hasattr(self, "workflow_connect_btn"):
            self.workflow_connect_btn.setText("Connect: select node 1")
        self._set_workflow_hint("Connect mode active: click source node, then target node.")

    def _cancel_workflow_connect_mode(self, hint_text=""):
        self._workflow_connect_mode_active = False
        self._workflow_connect_source_node_id = ""
        if hasattr(self, "workflow_connect_btn"):
            self.workflow_connect_btn.setText("Connect Nodes")
        if hint_text:
            self._set_workflow_hint(hint_text)

    def _on_workflow_node_clicked(self, node_item):
        if self._workflow_canvas_locked:
            return
        if not self._workflow_connect_mode_active:
            return
        if node_item is None:
            return

        node_id = str(node_item.node_id or "").strip()
        if not node_id:
            return

        if not self._workflow_connect_source_node_id:
            self._workflow_connect_source_node_id = node_id
            if hasattr(self, "workflow_connect_btn"):
                self.workflow_connect_btn.setText("Connect: select node 2")
            self._set_workflow_hint(f"Connect mode: source node selected ({node_id}). Click target node.")
            return

        source_id = self._workflow_connect_source_node_id
        target_id = node_id
        if source_id == target_id:
            self._set_workflow_hint("Connect mode: source and target cannot be the same node. Select target node.")
            return

        if self._add_workflow_edge(source_id, target_id):
            self._cancel_workflow_connect_mode(f"Connected {source_id} -> {target_id}.")
        else:
            self._cancel_workflow_connect_mode("Unable to create edge. It may already exist.")

    def _on_workflow_node_double_clicked(self, node_item):
        if self._workflow_canvas_locked:
            self._set_workflow_hint("Workflow is executing; node configuration is locked.")
            return
        if node_item is None:
            return
        if node_item.node_type == "source":
            self._edit_source_node_selection(node_item)
            return
        if node_item.node_type == "adapter":
            self._edit_adapter_node(node_item)
            return
        if node_item.node_type != "function":
            return

        function_id = str(node_item.node_payload.get("function_id") or "").strip()
        if not function_id:
            return

        try:
            updated_payload = self._workflow_plugin_manager.run_node_double_click_callback(
                function_id=function_id,
                node_payload=node_item.node_payload,
                dock=self,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Function Callback", f"Function callback failed:\n{exc}")
            return

        if not isinstance(updated_payload, dict):
            return

        node_item.node_payload = dict(updated_payload)
        spec = self._workflow_plugin_manager.get(function_id)
        if spec is not None:
            node_item.node_payload["function_id"] = spec.function_id
            node_item.node_payload["function_name"] = spec.display_name
            node_item.set_node_label(self._function_node_label(spec, node_item.node_payload))
        self._set_workflow_hint(f"Updated function node: {node_item.node_id}")

    def _edit_adapter_node(self, node_item):
        adapter_payload = dict(node_item.node_payload or {})
        adapter_id = str(adapter_payload.get("adapter_id") or "").strip()
        if adapter_id != self.ADAPTER_ID_FOR_EACH_IMAGE_IN_STACK:
            self._set_workflow_hint("Adapter node is not configurable.")
            return

        function_id = str(adapter_payload.get("adapted_function_id") or "").strip()
        if not function_id:
            self._set_workflow_hint("Adapter has no embedded function to configure.")
            return
        function_payload = adapter_payload.get("adapted_function_payload")
        function_payload = dict(function_payload or {}) if isinstance(function_payload, dict) else {}
        callback_payload = dict(function_payload)
        callback_payload["__workflow_grouping_type"] = "stack"

        try:
            updated_payload = self._workflow_plugin_manager.run_node_double_click_callback(
                function_id=function_id,
                node_payload=callback_payload,
                dock=self,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Adapter Callback", f"Embedded function callback failed:\n{exc}")
            return

        if not isinstance(updated_payload, dict):
            return

        spec = self._workflow_plugin_manager.get(function_id)
        if spec is not None:
            updated_payload["function_id"] = spec.function_id
            updated_payload["function_name"] = spec.display_name
            adapter_payload["adapted_function_id"] = spec.function_id
            adapter_payload["adapted_function_name"] = spec.display_name
        updated_payload.pop("__workflow_grouping_type", None)
        adapter_payload["adapted_function_payload"] = dict(updated_payload)
        node_item.node_payload = adapter_payload
        node_item.set_node_label(self._adapter_node_label(adapter_payload))
        self._set_workflow_hint(f"Updated adapter node: {node_item.node_id}")

    def _add_selected_source_node(self):
        if self._workflow_canvas_locked:
            self._set_workflow_hint("Workflow is executing; canvas editing is locked.")
            return
        mode = str(self.workflow_source_mode_combo.currentData() or "single").strip().lower()
        if mode not in {"single", "stack"}:
            QMessageBox.information(
                self,
                "Source Mode Not Supported",
                "This source mode is not supported yet.",
            )
            return

        payload = {
            "mode": "stack" if mode == "stack" else "single",
            "item_ids": [],
        }
        label = self._source_node_label(payload, include_selected=False)
        self._add_workflow_node("source", label, payload=payload)
        self.workflow_tabs.setCurrentWidget(self.workflow_canvas_tab)
        self._set_workflow_hint(
            "Source node added. Double-click the source node to select imagery from current search results."
        )

    def _add_selected_function_node(self):
        if self._workflow_canvas_locked:
            self._set_workflow_hint("Workflow is executing; canvas editing is locked.")
            return
        spec = self._selected_workflow_function_spec()
        if spec is None:
            QMessageBox.warning(self, "No Function Selected", "Choose a function plugin first.")
            return
        payload = {
            "function_id": spec.function_id,
            "function_name": spec.display_name,
            "description": spec.description,
        }
        payload.update(dict(spec.default_payload or {}))
        label = self._function_node_label(spec, payload)
        self._add_workflow_node(
            "function",
            label,
            payload=payload,
        )
        self._set_workflow_hint(
            "Function node added. Double-click the node to configure plugin-specific inputs."
        )

    def _next_workflow_node_id(self):
        while True:
            self._workflow_node_seq += 1
            node_id = f"node-{self._workflow_node_seq}"
            if node_id not in self._workflow_nodes:
                return node_id

    def _next_workflow_node_pos(self):
        index = len(self._workflow_nodes)
        col = index % 4
        row = index // 4
        return QPointF(36 + col * 260, 36 + row * 118)

    def _add_workflow_node(self, node_type, label, payload=None, pos=None, node_id=None):
        node_id_value = str(node_id or "").strip() or self._next_workflow_node_id()
        if node_id_value in self._workflow_nodes:
            return self._workflow_nodes[node_id_value]

        if node_id_value.startswith("node-"):
            suffix = node_id_value[5:]
            if suffix.isdigit():
                self._workflow_node_seq = max(self._workflow_node_seq, int(suffix))

        node_item = WorkflowNodeItem(
            node_id=node_id_value,
            node_type=node_type,
            label=label,
            payload=payload,
            moved_callback=self._on_workflow_node_moved,
            click_callback=self._on_workflow_node_clicked,
            double_click_callback=self._on_workflow_node_double_clicked,
        )
        self._workflow_scene.addItem(node_item)
        if pos is None:
            node_item.setPos(self._next_workflow_node_pos())
        else:
            node_item.setPos(pos)
        self._workflow_nodes[node_id_value] = node_item
        return node_item

    def _on_workflow_node_moved(self, node_item):
        if node_item is None:
            return
        for edge in self._workflow_edges:
            if edge.source_node is node_item or edge.target_node is node_item:
                edge.update_path()

    def _add_workflow_edge(self, source_node_id, target_node_id):
        source_key = str(source_node_id or "").strip()
        target_key = str(target_node_id or "").strip()
        if not source_key or not target_key or source_key == target_key:
            return False
        source_node = self._workflow_nodes.get(source_key)
        target_node = self._workflow_nodes.get(target_key)
        if source_node is None or target_node is None:
            return False
        if self._should_auto_wrap_stack_clip_function(source_node, target_node):
            adapter_node = self._replace_function_node_with_stack_adapter(target_node)
            if adapter_node is None:
                return False
            return self._add_direct_workflow_edge(source_node, adapter_node)
        return self._add_direct_workflow_edge(source_node, target_node)

    def _add_direct_workflow_edge(self, source_node, target_node):
        if source_node is None or target_node is None:
            return False
        if source_node is target_node:
            return False
        for edge in self._workflow_edges:
            if edge.source_node is source_node and edge.target_node is target_node:
                return False
        edge_item = WorkflowEdgeItem(source_node, target_node)
        self._workflow_scene.addItem(edge_item)
        self._workflow_edges.append(edge_item)
        return True

    def _should_auto_wrap_stack_clip_function(self, source_node, target_node):
        if source_node is None or target_node is None:
            return False
        if str(source_node.node_type or "").strip().lower() != "source":
            return False
        if str(target_node.node_type or "").strip().lower() != "function":
            return False
        if self._source_node_mode(source_node.node_payload) != "stack":
            return False
        function_id = str(target_node.node_payload.get("function_id") or "").strip()
        if function_id != "clip_to_aoi":
            return False
        return True

    def _build_stack_clip_adapter_payload_from_function(self, function_node):
        node = function_node
        if node is None:
            return {}
        function_payload = dict(node.node_payload or {})
        function_id = str(function_payload.get("function_id") or "").strip()
        function_name = str(function_payload.get("function_name") or "").strip()
        if not function_name and function_id:
            spec = self._workflow_plugin_manager.get(function_id)
            if spec is not None:
                function_name = spec.display_name
        return {
            "adapter_id": self.ADAPTER_ID_FOR_EACH_IMAGE_IN_STACK,
            "adapter_name": self.ADAPTER_NAME_FOR_EACH_IMAGE_IN_STACK,
            "adapted_function_id": function_id,
            "adapted_function_name": function_name,
            "adapted_function_payload": function_payload,
            "auto_inserted": True,
        }

    def _replace_function_node_with_stack_adapter(self, function_node):
        node = function_node
        if node is None:
            return None
        if str(node.node_type or "").strip().lower() != "function":
            return None
        function_id = str(node.node_payload.get("function_id") or "").strip()
        if function_id != "clip_to_aoi":
            return None

        adapter_payload = self._build_stack_clip_adapter_payload_from_function(node)
        adapter_label = self._adapter_node_label(adapter_payload)
        adapter_node_id = str(node.node_id or "").strip()
        adapter_pos = QPointF(node.pos())

        upstream_nodes = []
        downstream_nodes = []
        remove_edges = []
        for edge in self._workflow_edges:
            if edge.target_node is node:
                remove_edges.append(edge)
                if edge.source_node is not None and edge.source_node not in upstream_nodes:
                    upstream_nodes.append(edge.source_node)
                continue
            if edge.source_node is node:
                remove_edges.append(edge)
                if edge.target_node is not None and edge.target_node not in downstream_nodes:
                    downstream_nodes.append(edge.target_node)

        for edge in remove_edges:
            if edge in self._workflow_edges:
                self._workflow_edges.remove(edge)
            self._workflow_scene.removeItem(edge)

        self._workflow_scene.removeItem(node)
        self._workflow_nodes.pop(adapter_node_id, None)

        adapter_node = self._add_workflow_node(
            node_type="adapter",
            label=adapter_label,
            payload=adapter_payload,
            pos=adapter_pos,
            node_id=adapter_node_id,
        )
        for upstream in upstream_nodes:
            self._add_direct_workflow_edge(upstream, adapter_node)
        for downstream in downstream_nodes:
            self._add_direct_workflow_edge(adapter_node, downstream)
        return adapter_node

    def _delete_selected_workflow_items(self):
        if self._workflow_canvas_locked:
            self._set_workflow_hint("Workflow is executing; deletion is disabled.")
            return
        selected_items = list(self._workflow_scene.selectedItems() or [])
        if not selected_items:
            return

        selected_nodes = [item for item in selected_items if isinstance(item, WorkflowNodeItem)]
        selected_edges = [item for item in selected_items if isinstance(item, WorkflowEdgeItem)]

        remove_node_ids = {node.node_id for node in selected_nodes}
        remove_edges = set(selected_edges)

        remaining_edges = []
        for edge in self._workflow_edges:
            source_id = edge.source_node.node_id if edge.source_node is not None else ""
            target_id = edge.target_node.node_id if edge.target_node is not None else ""
            if edge in remove_edges or source_id in remove_node_ids or target_id in remove_node_ids:
                self._workflow_scene.removeItem(edge)
            else:
                remaining_edges.append(edge)
        self._workflow_edges = remaining_edges

        for node in selected_nodes:
            self._workflow_scene.removeItem(node)
            self._workflow_nodes.pop(node.node_id, None)

        if self._workflow_connect_source_node_id in remove_node_ids:
            self._cancel_workflow_connect_mode("Connect mode cancelled: selected source node was deleted.")
            return

        self._set_workflow_hint(
            f"Deleted {len(selected_nodes)} node(s) and {len(selected_edges)} explicitly selected edge(s)."
        )

    def _execute_workflow(self):
        if self._workflow_canvas_locked:
            self._set_workflow_hint("Workflow is already executing.")
            return
        payload = self._serialize_workflow(include_source_assignments=True)
        nodes = payload.get("nodes") if isinstance(payload, dict) else []
        if not isinstance(nodes, list) or not nodes:
            QMessageBox.warning(
                self,
                "Execute Workflow",
                "The workflow canvas is empty. Add nodes before execution.",
            )
            return
        self.reset_workflow_execution_visuals(clear_log=True)
        self.set_workflow_execution_progress(0, len(nodes), "Workflow queued for execution.")
        self.append_workflow_execution_log(
            f"Execution requested with {len(nodes)} node(s)."
        )
        if hasattr(self, "workflow_tabs") and hasattr(self, "workflow_log_tab"):
            self.workflow_tabs.setCurrentWidget(self.workflow_log_tab)
        self.execute_workflow_requested.emit(payload)
        self._set_workflow_hint("Workflow execution requested.")

    def _serialize_workflow(self, include_source_assignments=True):
        nodes = []
        for node in self._workflow_nodes.values():
            pos = node.pos()
            node_payload = dict(node.node_payload or {})
            node_label = str(node.node_label or node.node_id).strip()
            if node.node_type == "source":
                source_mode = self._source_node_mode(node_payload)
                selected_item_ids = self._coerce_str_list(node_payload.get("item_ids"))
                effective_item_ids = selected_item_ids if include_source_assignments else []
                node_payload = {
                    "mode": source_mode,
                    "item_ids": effective_item_ids,
                }
                node_label = self._source_node_label(
                    node_payload,
                    include_selected=bool(include_source_assignments),
                )
            nodes.append(
                {
                    "id": node.node_id,
                    "type": node.node_type,
                    "label": node_label,
                    "payload": node_payload,
                    "position": {"x": float(pos.x()), "y": float(pos.y())},
                }
            )
        nodes = sorted(nodes, key=lambda row: str(row.get("id") or ""))

        edges = []
        for edge in self._workflow_edges:
            source_id = edge.source_node.node_id if edge.source_node is not None else ""
            target_id = edge.target_node.node_id if edge.target_node is not None else ""
            if source_id and target_id:
                edges.append({"source": source_id, "target": target_id})
        edges = sorted(edges, key=lambda row: (str(row.get("source") or ""), str(row.get("target") or "")))

        return {
            "version": 1,
            "saved_at_utc": datetime.now(tz=timezone.utc).isoformat(),
            "nodes": nodes,
            "edges": edges,
        }

    def _save_workflow_json(self):
        suggested_name = (
            "image_mate_workflow_"
            + datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + ".json"
        )
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Workflow JSON",
            suggested_name,
            "JSON files (*.json);;All files (*.*)",
        )
        if not file_path:
            return
        if not str(file_path).lower().endswith(".json"):
            file_path = f"{file_path}.json"

        payload = self._serialize_workflow(include_source_assignments=False)
        try:
            with open(file_path, "w", encoding="utf-8") as out:
                json.dump(payload, out, indent=2)
        except Exception as exc:
            QMessageBox.warning(self, "Save Workflow", f"Failed to save workflow JSON:\n{exc}")
            return
        self._set_workflow_hint(f"Workflow saved: {file_path}")

    def _clear_workflow_scene(self):
        self._workflow_scene.clear()
        self._workflow_nodes = {}
        self._workflow_edges = []
        self._workflow_node_seq = 0
        self._cancel_workflow_connect_mode("")

    @staticmethod
    def _coerce_pos(value):
        if isinstance(value, dict):
            try:
                return QPointF(float(value.get("x", 0.0)), float(value.get("y", 0.0)))
            except Exception:
                return None
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            try:
                return QPointF(float(value[0]), float(value[1]))
            except Exception:
                return None
        return None

    @staticmethod
    def _coerce_str_list(values):
        if not isinstance(values, list):
            return []
        out = []
        for value in values:
            text = str(value or "").strip()
            if text:
                out.append(text)
        return out

    def _apply_loaded_source_selection(self, source_selection):
        if not isinstance(source_selection, dict):
            return

        mode = str(source_selection.get("mode") or "single").strip().lower()
        if mode not in {"single", "stack"}:
            mode = "single"
        mode_idx = self.workflow_source_mode_combo.findData(mode)
        if mode_idx >= 0:
            self.workflow_source_mode_combo.setCurrentIndex(mode_idx)

        single_item_id = str(source_selection.get("single_item_id") or "").strip()
        if single_item_id:
            idx = self.workflow_single_source_combo.findData(single_item_id)
            if idx >= 0:
                self.workflow_single_source_combo.setCurrentIndex(idx)

        stack_item_ids = self._coerce_str_list(source_selection.get("stack_item_ids"))
        if stack_item_ids:
            match_idx = -1
            for idx in range(self.workflow_stack_source_combo.count()):
                data = self.workflow_stack_source_combo.itemData(idx)
                if isinstance(data, list) and [str(v) for v in data] == stack_item_ids:
                    match_idx = idx
                    break
            if match_idx >= 0:
                self.workflow_stack_source_combo.setCurrentIndex(match_idx)
            else:
                self.workflow_stack_source_combo.addItem(
                    f"Loaded stack ({len(stack_item_ids)} images)",
                    stack_item_ids,
                )
                self.workflow_stack_source_combo.setCurrentIndex(self.workflow_stack_source_combo.count() - 1)

        self._on_workflow_source_mode_changed()

    def _load_workflow_json(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Workflow JSON",
            "",
            "JSON files (*.json);;All files (*.*)",
        )
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as src:
                payload = json.load(src)
        except Exception as exc:
            QMessageBox.warning(self, "Load Workflow", f"Failed to read workflow JSON:\n{exc}")
            return

        if not isinstance(payload, dict):
            QMessageBox.warning(self, "Load Workflow", "Workflow JSON root must be an object.")
            return

        nodes_data = payload.get("nodes")
        edges_data = payload.get("edges")
        if not isinstance(nodes_data, list) or not isinstance(edges_data, list):
            QMessageBox.warning(self, "Load Workflow", "Workflow JSON must contain 'nodes' and 'edges' lists.")
            return

        self._clear_workflow_scene()
        self._refresh_workflow_source_options()

        for row in nodes_data:
            if not isinstance(row, dict):
                continue
            node_id = str(row.get("id") or "").strip()
            if not node_id:
                continue
            node_type = str(row.get("type") or "function").strip().lower() or "function"
            if node_type == "step":
                node_type = "function"
            node_label = str(row.get("label") or node_id).strip()
            node_payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            if node_type == "source":
                source_mode = self._source_node_mode(node_payload)
                node_payload = {
                    "mode": source_mode,
                    "item_ids": [],
                }
                node_label = self._source_node_label(node_payload, include_selected=False)
            if node_type == "function":
                function_id = str(node_payload.get("function_id") or node_payload.get("step_id") or "").strip()
                function_name = str(node_payload.get("function_name") or node_payload.get("step_name") or "").strip()
                if function_id and "function_id" not in node_payload:
                    node_payload["function_id"] = function_id
                if function_name and "function_name" not in node_payload:
                    node_payload["function_name"] = function_name
            if node_type == "adapter":
                adapter_id = str(node_payload.get("adapter_id") or "").strip()
                if not adapter_id:
                    node_payload["adapter_id"] = self.ADAPTER_ID_FOR_EACH_IMAGE_IN_STACK
                    node_payload["adapter_name"] = self.ADAPTER_NAME_FOR_EACH_IMAGE_IN_STACK
                adapted_function_id = str(node_payload.get("adapted_function_id") or "").strip()
                adapted_payload = node_payload.get("adapted_function_payload")
                if adapted_payload is not None and not isinstance(adapted_payload, dict):
                    node_payload["adapted_function_payload"] = {}
                if adapted_function_id and not str(node_payload.get("adapted_function_name") or "").strip():
                    spec = self._workflow_plugin_manager.get(adapted_function_id)
                    if spec is not None:
                        node_payload["adapted_function_name"] = spec.display_name
                node_label = self._adapter_node_label(node_payload)
            node_pos = self._coerce_pos(row.get("position"))
            self._add_workflow_node(
                node_type=node_type,
                label=node_label,
                payload=node_payload,
                pos=node_pos,
                node_id=node_id,
            )

        for row in edges_data:
            if not isinstance(row, dict):
                continue
            source_id = str(row.get("source") or "").strip()
            target_id = str(row.get("target") or "").strip()
            if source_id and target_id:
                self._add_workflow_edge(source_id, target_id)
        self._set_workflow_hint(
            f"Workflow loaded: {file_path}. Double-click source nodes to select images from current search results."
        )
