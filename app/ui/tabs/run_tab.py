# app/ui/tabs/run_tab.py
import sys, time, json, uuid, csv, subprocess, io, os
from collections import deque
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QFileDialog, QHBoxLayout, QVBoxLayout, QGridLayout, 
    QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QMessageBox, QSizePolicy, 
    QListView, QSplitter, QFrame, QSpacerItem, QCheckBox, QMenu, QDialog,
    QApplication, QScrollArea, QGraphicsOpacityEffect, QPlainTextEdit,
    QStackedWidget
)
from PySide6.QtCore import (
    QTimer, Qt, Signal, Slot, QUrl, QPropertyAnimation, QEasingCurve,
    QAbstractAnimation, QPoint
)
from PySide6.QtGui import (
    QImage,
    QPixmap,
    QPainter,
    QColor,
    QDesktopServices,
    QCursor,
    QAction,
    QActionGroup,
    QFontDatabase,
)

from serial.tools import list_ports

from app.core import video, configio
from app.core.logger import (
    APP_LOGGER, RunLogger, TrackingLogger, FrameLogger, configure_file_logging,
    CSV_FIELDS, TRACKING_FIELDS, FRAME_FIELDS,
)
from app.core.session import RunSession
from app.core.version import APP_VERSION
from app.core.workers import FrameWorker, ProcessCVWorker, RenderWorker
from app.core.paths import RUNS_DIR, LOGO_PATH, BASE_DIR
from app.core.resources import ResourceRegistry

from app.ui.theme import (
    active_theme, set_active_theme, BG, MID, TEXT, SUBTXT, ACCENT, DANGER, BORDER, 
    build_stylesheet, THEMES, DEFAULT_THEME_NAME, set_macos_titlebar_appearance
)
from app.ui.widgets.viewer import ZoomView, PinnedPreviewWindow, AppZoomView
from app.ui.widgets.chart import LiveChart
from app.ui.widgets.containers import AspectRatioContainer

try:
    import psutil
except Exception:
    psutil = None

FOOTER_LOGO_SCALE = 0.036
_ACTIVE_THEME_NAME = "light"
_FONT_FAMILY = "Typestar OCR Regular"
APP_MIN_SIZE = (1280, 780)
CONTENT_MIN_SIZE = (1280, 780)
VIDEO_VIEW_MIN_SIZE = (480, 270)
VIDEO_AREA_MIN_SIZE = (360, 202)
LEFT_PANEL_MIN_WIDTH = 360
RIGHT_PANEL_MIN_WIDTH = 360
RIGHT_SCROLL_MIN_WIDTH = 380
RIGHT_PANEL_TOP_MARGIN = 32
SPLITTER_HANDLE_WIDTH = 10
SPLITTER_LEFT_RATIO = 0.75
MIRROR_SPLITTER_FIXED_WIDTH = 380
MIRROR_SPLITTER_FILL = 100000
PREVIEW_ASPECT_RATIO = (16, 9)
THEME_TRANSITION_MS = 500
STATUS_ROW_SPACING = 12
SECTION_GAP_LARGE = 24
SECTION_GAP_REDUCTION = 8
SECTION_GAP_MIN = 12
SECTION_GAP_HEIGHT_THRESHOLD = 820
SPACING_XXS = 2
SPACING_XS = 4
SPACING_SM = 6
SPACING_MD = 8
LABEL_WIDTH_PADDING_PX = 8
COMBO_POPUP_MIN_WIDTH = 140
COMBO_HINT_PADDING = 24
MODE_COMBO_MIN_WIDTH = 170
MODE_COMBO_MAX_WIDTH_MIN = 220
MODE_COMBO_TEXT_PADDING = 60
MODE_COMBO_WIDTH_PADDING = 10
CONTROL_WIDTH = 200
STEPSIZE_TEXT_PADDING = 40
STEPSIZE_WIDTH_PADDING = 20
CHART_FRAME_BORDER_PX = 1
CHART_CONTROLS_TOP_MARGIN_PX = SPACING_XS
CHART_CONTROLS_SPACING_PX = SPACING_SM
LOGO_TAGLINE_TOP_MARGIN_PX = SPACING_XS
LOGO_ROW_TOP_MARGIN_PX = SPACING_MD
LOGO_BLOCK_SPACING_PX = SPACING_XXS
PERIOD_MIN_S = 0.1
PERIOD_MAX_S = 3600.0
PERIOD_DEFAULT_S = 10.0
WARMUP_MIN_S = 0.0
WARMUP_MAX_S = 600.0
WARMUP_DEFAULT_S = 10.0
WARMUP_DECIMALS = 1
LAMBDA_MIN_RPM = 0.1
LAMBDA_MAX_RPM = 600.0
LAMBDA_DEFAULT_RPM = 6.0
CAMERA_INDEX_MIN = 0
CAMERA_INDEX_MAX = 8
CAMERA_INDEX_DEFAULT = 0
STATUS_TIMER_INTERVAL_MS = 400
SERIAL_TIMER_INTERVAL_MS = 50
PREVIEW_FPS_DEFAULT = 30
AUTO_STOP_MAX_MIN = 20000.0
AUTO_STOP_MIN_MIN = 0.0
AUTO_STOP_DECIMALS = 1
AUTO_STOP_CONTROL_WIDTH = 200
AUTO_STOP_GRACE_TAPS = 2
RUN_LOCK_TOOLTIP = "End the run before you can change the controls further."
LOGO_ALPHA_THRESHOLD = 24
SERIAL_BAUD_DEFAULT = 9600
SERIAL_TIMEOUT_S = 0.0
REPLICANT_MS_THRESHOLD = 10000.0
RUN_ID_TOKEN_LEN = 6
STEPSIZE_MIN = 1
STEPSIZE_MAX = 5
DEFAULT_STEPSIZE = 4
STEPSIZE_OPTIONS = [
    "-",
    "1 (Full Step)",
    "2 (Half Step)",
    "3 (1/4 Step)",
    "4 (1/8 Step)",
    "5 (1/16 Step)",
]
RUN_DIR_CREATE_RETRIES = 5
RUN_SCHEMA_VERSION = 6
GITHUB_README_URL = "https://github.com/svdrecbd/NEMESIS"
CALIFORNIA_NUMERICS_URL = "https://www.californianumerics.com/nemesis/"
MIN_TIMER_DELAY_MS = 1
SECONDS_PER_MIN = 60.0
MS_PER_SEC = 1000.0
LOW_DISK_TRACKING_DECIMATE = 2
LOW_DISK_STATUS_LABEL = "LOW DISK MODE (15 FPS LOG)"
DISK_FULL_STATUS_LABEL = "DISK FULL (BUFFERING)"
STARTER_GUIDE_VERSION = 1
DISK_CALIBRATION_DURATION_S = 15.0
DISK_ESTIMATE_MARGIN = 1.5
DISK_ESTIMATE_GB_DIVISOR = 1_000_000_000.0
DIAG_SAMPLE_INTERVAL_S_DEFAULT = 10.0
DIAG_SAMPLE_INTERVAL_MIN_S = 2.0
DIAG_SAMPLE_INTERVAL_MAX_S = 60.0
DIAG_FILE_NAME = "diagnostics.csv"
DIAG_FIELDS = [
    "timestamp_iso",
    "t_host_s",
    "arm_name",
    "run_id",
    "run_elapsed_s",
    "camera_open",
    "camera_fps_est",
    "cv_fps_est",
    "rec_fps_est",
    "rec_drop_fps",
    "rec_queue_depth",
    "rec_queue_max",
    "serial_connected",
    "camera_dead",
    "low_disk_mode",
    "tracking_decimate",
    "cpu_process_pct",
    "cpu_system_pct",
    "cpu_other_pct",
    "mem_process_mb",
    "mem_system_pct",
    "load_1m",
    "threads",
    "disk_free_gb",
    "disk_write_mb_s",
    "metrics_source",
    "note",
]

def _log_gui_exception(e: Exception, context: str = "GUI operation") -> None:
    APP_LOGGER.error(f"Unhandled GUI exception in {context}: {e}", exc_info=True)


class ThemedDialog(QDialog):
    def __init__(self, parent=None, title=""):
        # Detach from parent for WM to ensure frameless works, but keep ref
        super().__init__(None)
        self._parent_ref = parent
        self._positioned = False
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Main layout (Outer shell)
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)
        
        # Styling
        theme = active_theme()
        bg = theme.get("BG", BG)
        text = theme.get("TEXT", TEXT)
        border = theme.get("BORDER", BORDER)
        mid = theme.get("MID", MID)
        
        # Frame to draw border/bg
        self._frame = QFrame()
        self._frame.setObjectName("DialogFrame")
        self._frame.setStyleSheet(f"QFrame#DialogFrame {{ background: {bg}; border: 1px solid {border}; }}")
        self._main_layout.addWidget(self._frame)
        
        self._frame_layout = QVBoxLayout(self._frame)
        self._frame_layout.setContentsMargins(0, 0, 0, 0)
        self._frame_layout.setSpacing(0)
        
        # Title Bar
        self._title_bar = QWidget()
        self._title_bar.setStyleSheet(f"background: {mid}; border-bottom: 1px solid {border};")
        self._title_bar.setFixedHeight(36)
        
        title_layout = QHBoxLayout(self._title_bar)
        title_layout.setContentsMargins(12, 0, 4, 0)
        
        self._title_label = QLabel(title)
        self._title_label.setStyleSheet(f"color: {text}; font-weight: bold; border: none; background: transparent;")
        title_layout.addWidget(self._title_label)
        title_layout.addStretch(1)
        
        self._close_btn = QPushButton("×")
        self._close_btn.setFixedSize(32, 32)
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; 
                border: none; 
                color: {text}; 
                font-size: 20px;
                font-weight: bold;
                padding: 0;
                margin: 0;
            }}
            QPushButton:hover {{
                background: {DANGER}; 
                color: white;
            }}
        """)
        self._close_btn.clicked.connect(self.close)
        title_layout.addWidget(self._close_btn)
        
        self._frame_layout.addWidget(self._title_bar)
        
        # Content Area
        self._content_widget = QWidget()
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(16, 16, 16, 16)
        self._content_layout.setSpacing(12)
        
        self._frame_layout.addWidget(self._content_widget, 1)
        
        # Drag state
        self._dragging = False
        self._drag_pos = QPoint()

    def apply_theme(self):
        theme = active_theme()
        bg = theme.get("BG", BG)
        text = theme.get("TEXT", TEXT)
        border = theme.get("BORDER", BORDER)
        mid = theme.get("MID", MID)
        
        self._frame.setStyleSheet(f"QFrame#DialogFrame {{ background: {bg}; border: 1px solid {border}; }}")
        self._title_bar.setStyleSheet(f"background: {mid}; border-bottom: 1px solid {border};")
        if hasattr(self, "_title_label"):
            self._title_label.setStyleSheet(f"color: {text}; font-weight: bold; border: none; background: transparent;")
        if hasattr(self, "_close_btn"):
            self._close_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; 
                    border: none; 
                    color: {text}; 
                    font-size: 20px;
                    font-weight: bold;
                    padding: 0;
                    margin: 0;
                }}
                QPushButton:hover {{
                    background: {DANGER}; 
                    color: white;
                }}
            """)

    def setWindowTitle(self, title):
        super().setWindowTitle(title)
        if hasattr(self, "_title_label"):
            self._title_label.setText(title)

    def content_layout(self):
        return self._content_layout

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Map click to title bar coords to check containment
            # title bar is at 0,0 of frame? No, frame is in self.
            # Easiest: Check if click is in top 36px of the window
            if event.position().y() <= self._title_bar.height():
                self._dragging = True
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
            else:
                super().mousePressEvent(event)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._dragging = False
        super().mouseReleaseEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if self._positioned:
            return
        self._positioned = True
        try:
            parent = self._parent_ref
            if parent is not None:
                try:
                    anchor = parent.window()
                    if anchor is None:
                        anchor = parent
                    geo = anchor.frameGeometry()
                except Exception:
                    geo = parent.frameGeometry()
                center = geo.center()
                self.move(center - self.rect().center())
            else:
                screen = QApplication.primaryScreen()
                if screen:
                    center = screen.availableGeometry().center()
                    self.move(center - self.rect().center())
        except Exception:
            pass


class SettingsDialog(ThemedDialog):
    def __init__(self, parent_tab):
        super().__init__(parent_tab, title="NEMESIS Settings")
        self.parent_tab = parent_tab
        self.setFixedSize(380, 620)
        
        layout = self.content_layout()
        
        # Theme
        layout.addWidget(QLabel("Theme"))
        theme_layout = QHBoxLayout()
        self.btn_light = QPushButton("Light")
        self.btn_light.setCheckable(True)
        self.btn_light.clicked.connect(lambda: self._set_theme("light"))
        theme_layout.addWidget(self.btn_light)
        
        self.btn_dark = QPushButton("Dark")
        self.btn_dark.setCheckable(True)
        self.btn_dark.clicked.connect(lambda: self._set_theme("dark"))
        theme_layout.addWidget(self.btn_dark)
        layout.addLayout(theme_layout)
        
        layout.addWidget(self._make_line())
        
        # Layout
        layout.addWidget(QLabel("Layout"))
        self.check_mirror = QCheckBox("Mirror Layout")
        self.check_mirror.toggled.connect(parent_tab._set_mirror_mode)
        layout.addWidget(self.check_mirror)
        
        self.check_wide = QCheckBox("Wide Layout (Top/Bottom)")
        self.check_wide.toggled.connect(parent_tab._set_wide_mode)
        layout.addWidget(self.check_wide)
        
        layout.addWidget(self._make_line())

        # Diagnostics
        layout.addWidget(QLabel("Diagnostics"))
        self.check_diag = QCheckBox("Enable Diagnostics Mode")
        self.check_diag.setChecked(parent_tab._diagnostics_enabled)
        self.check_diag.toggled.connect(parent_tab._set_diagnostics_enabled)
        layout.addWidget(self.check_diag)
        diag_note = QLabel("Diagnostics writes a diagnostics.csv for long-run health + benchmarking.")
        diag_note.setStyleSheet("font-size: 9pt; font-style: italic;")
        diag_note.setWordWrap(True)
        layout.addWidget(diag_note)
        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("Sample interval:"))
        self.diag_interval = QSpinBox()
        self.diag_interval.setRange(int(DIAG_SAMPLE_INTERVAL_MIN_S), int(DIAG_SAMPLE_INTERVAL_MAX_S))
        self.diag_interval.setValue(int(parent_tab._diagnostics_interval_s))
        self.diag_interval.setSuffix(" s")
        self.diag_interval.valueChanged.connect(parent_tab._set_diagnostics_interval)
        interval_row.addWidget(self.diag_interval)
        interval_row.addStretch(1)
        layout.addLayout(interval_row)
        if psutil is None:
            warn = QLabel("psutil not available: diagnostics will be limited.")
            warn.setStyleSheet("font-size: 9pt; font-style: italic;")
            layout.addWidget(warn)
        
        layout.addWidget(self._make_line())
        
        # Actions
        btn_fw = QPushButton("Show Firmware Code...")
        btn_fw.clicked.connect(parent_tab._show_firmware_dialog)
        layout.addWidget(btn_fw)

        btn_calib = QPushButton("Calibrate Disk Estimate...")
        btn_calib.clicked.connect(parent_tab._start_disk_calibration)
        layout.addWidget(btn_calib)

        btn_guide = QPushButton("Starter's Guide...")
        btn_guide.clicked.connect(lambda: parent_tab.show_starter_guide(force=True))
        layout.addWidget(btn_guide)
        
        btn_ports = QPushButton("Refresh Ports")
        btn_ports.clicked.connect(parent_tab._refresh_serial_ports)
        layout.addWidget(btn_ports)
        
        btn_runs = QPushButton("Open Runs Folder")
        btn_runs.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(RUNS_DIR.resolve()))))
        layout.addWidget(btn_runs)
        
        layout.addStretch(1)
        
        # Footer
        link_layout = QHBoxLayout()
        btn_readme = QPushButton("README")
        btn_readme.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(GITHUB_README_URL)))
        link_layout.addWidget(btn_readme)
        
        btn_cn = QPushButton("California Numerics")
        btn_cn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(CALIFORNIA_NUMERICS_URL)))
        link_layout.addWidget(btn_cn)
        layout.addLayout(link_layout)
        
        self._sync_state()

    def _make_line(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    def _set_theme(self, name):
        self.parent_tab._apply_theme(name)
        self.apply_theme()
        self._sync_state()

    def _sync_state(self):
        # Sync Theme buttons
        is_light = self.parent_tab._theme_name == "light"
        self.btn_light.setChecked(is_light)
        self.btn_dark.setChecked(not is_light)
        # Sync Layout checks
        self.check_mirror.setChecked(self.parent_tab._mirror_mode)
        self.check_wide.setChecked(self.parent_tab._wide_mode)
        if hasattr(self, "check_diag"):
            self.check_diag.blockSignals(True)
            self.check_diag.setChecked(self.parent_tab._diagnostics_enabled)
            self.check_diag.blockSignals(False)
        if hasattr(self, "diag_interval"):
            self.diag_interval.blockSignals(True)
            self.diag_interval.setValue(int(self.parent_tab._diagnostics_interval_s))
            self.diag_interval.blockSignals(False)
    
    def showEvent(self, event):
        self._sync_state()
        super().showEvent(event)


class RunSummaryDialog(ThemedDialog):
    def __init__(self, parent_tab, data: dict):
        super().__init__(parent_tab, title="Run Pre-Flight Check")
        self.parent_tab = parent_tab
        self.setFixedSize(400, 520)
        
        layout = self.content_layout()

        warnings = []
        if not data.get("camera_ok", True):
            warnings.append("NO CAMERA FEED")
        if not data.get("serial_ok", True):
            warnings.append("NO SERIAL CONNECTED")
        if warnings:
            warn = QLabel(" / ".join(warnings))
            warn.setWordWrap(True)
            warn.setAlignment(Qt.AlignCenter)
            palette = active_theme()
            danger = palette.get("DANGER", DANGER)
            warn.setStyleSheet(f"color: {danger}; font-weight: 900; font-size: 12pt; padding: 6px;")
            layout.addWidget(warn)
        
        # Grid for details
        grid = QGridLayout()
        grid.setSpacing(10)
        
        row = 0
        def add_item(label, value):
            nonlocal row
            lbl = QLabel(f"<b>{label}</b>")
            val = QLabel(str(value))
            grid.addWidget(lbl, row, 0)
            grid.addWidget(val, row, 1)
            row += 1

        add_item("Arm Name:", data.get("arm_name") or "—")
        add_item("Camera:", f"Index {data.get('cam_index')} ({data.get('cam_res', 'Unknown')})")
        add_item("Serial Port:", data.get('serial_port', 'Not Connected'))
        add_item("Mode:", data.get('mode'))
        add_item("Stepsize:", data.get('stepsize'))
        add_item("Acclimation:", f"{data.get('acclimation_min')} min")
        add_item("Warmup:", f"{data.get('warmup_sec')} s")
        
        duration = data.get('duration_min', 0)
        duration_str = f"{duration} min" if duration > 0 else "Manual (Unlimited)"
        add_item("Duration:", duration_str)
        
        layout.addLayout(grid)
        
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)
        
        # Disk Estimation
        est_label = QLabel(f"<b>Estimated Disk Usage:</b>")
        est_source = data.get("est_source", "")
        est_low = data.get("est_gb_low", 0.0)
        est_high = data.get("est_gb_high", 0.0)
        if est_source == "Manual":
            est_val = QLabel("Manual run (no estimate)")
        else:
            est_val = QLabel(f"{est_low:.2f}–{est_high:.2f} GB ({est_source})")
        est_val.setStyleSheet(f"color: {ACCENT}; font-size: 13pt; font-weight: bold;")
        
        layout.addWidget(est_label)
        layout.addWidget(est_val)
        
        warning = QLabel(
            "Note: Estimates are approximate. High-activity video may require more space."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("font-size: 9pt; font-style: italic;")
        layout.addWidget(warning)
        
        layout.addStretch(1)
        
        # Buttons
        btn_layout = QHBoxLayout()
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        
        self.btn_start = QPushButton("Confirm & Start Run")
        self.btn_start.setStyleSheet(f"background: {ACCENT}; color: white; font-weight: bold; padding: 8px;")
        self.btn_start.clicked.connect(self.accept)

        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.btn_start)
        layout.addLayout(btn_layout)


class UnsavedDataDialog(ThemedDialog):
    def __init__(self, parent_tab, loggers: list):
        super().__init__(parent_tab, title="⚠️ DISK FULL - DATA IN LIFE-RAFT")
        self.parent_tab = parent_tab
        self.loggers = loggers
        self.setFixedSize(450, 300)
        
        layout = self.content_layout()
        
        msg = QLabel(
            "The disk ran out of space during the run.\n\n"
            "<b>Scientific CSV data is currently held in RAM.</b>\n"
            "If you close the application now, this data will be LOST."
        )
        msg.setWordWrap(True)
        msg.setStyleSheet("font-size: 11pt;")
        layout.addWidget(msg)
        
        layout.addStretch(1)
        
        self.btn_retry = QPushButton("I've cleared space. RETRY SAVE.")
        self.btn_retry.setStyleSheet(f"background: {ACCENT}; color: white; font-weight: bold; padding: 12px;")
        self.btn_retry.clicked.connect(self._retry)
        layout.addWidget(self.btn_retry)
        
        self.status_lbl = QLabel("")
        self.status_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_lbl)

    def _retry(self):
        success = True
        for logger in self.loggers:
            if logger and hasattr(logger, "retry_flush"):
                if not logger.retry_flush():
                    success = False
        
        if success:
            self.status_lbl.setText("Success! Data saved to disk.")
            self.status_lbl.setStyleSheet("color: green;")
            QTimer.singleShot(1500, self.accept)
        else:
            self.status_lbl.setText("Error: Still unable to write to disk.")
            self.status_lbl.setStyleSheet(f"color: {DANGER};")


class LowDiskDialog(ThemedDialog):
    def __init__(self, parent_tab):
        super().__init__(parent_tab, title="⚠️ DISK FULL - DATA BUFFERING IN RAM")
        self.parent_tab = parent_tab
        self.enable_low_disk = False
        self.setFixedSize(470, 320)

        layout = self.content_layout()

        msg = QLabel(
            "Disk writes are failing. CSV data is being held in RAM (life-raft).\n\n"
            "Clear disk space to avoid data loss. You may optionally enable Low-Disk Mode "
            "(log every other frame, ~15 FPS at 30 FPS input) to cut RAM growth ~50%."
        )
        msg.setWordWrap(True)
        msg.setStyleSheet("font-size: 11pt;")
        layout.addWidget(msg)

        layout.addStretch(1)

        btn_layout = QHBoxLayout()
        self.btn_continue = QPushButton("Continue (full rate)")
        self.btn_continue.clicked.connect(self.reject)

        self.btn_low_disk = QPushButton("Enable Low-Disk Mode (15 FPS logging)")
        self.btn_low_disk.setStyleSheet(f"background: {ACCENT}; color: white; font-weight: bold; padding: 10px;")
        self.btn_low_disk.clicked.connect(self._enable)

        btn_layout.addWidget(self.btn_continue)
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.btn_low_disk)
        layout.addLayout(btn_layout)

    def _enable(self):
        self.enable_low_disk = True
        self.accept()


class StarterGuideDialog(ThemedDialog):
    def __init__(self, parent_tab):
        super().__init__(parent_tab, title="NEMESIS Starter's Guide")
        self.parent_tab = parent_tab
        self.setFixedSize(520, 520)

        layout = self.content_layout()
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        # Page 1: Welcome + Firmware + Arm Name
        page1 = QWidget()
        p1 = QVBoxLayout(page1)
        p1.addWidget(QLabel("<b>Welcome!</b> Let's set up this arm."))
        p1.addWidget(QLabel("1) Install firmware on the Arduino, then set an arm name."))
        btn_fw = QPushButton("Show Firmware Code...")
        btn_fw.clicked.connect(parent_tab._show_firmware_dialog)
        p1.addWidget(btn_fw)
        p1.addWidget(QLabel("Arm Name"))
        self.arm_name = QLineEdit()
        self.arm_name.setPlaceholderText("Arm Name (e.g. Arm A)")
        self.arm_name.setText(parent_tab.arm_name_edit.text().strip())
        self.arm_name.textChanged.connect(lambda t: parent_tab.arm_name_edit.setText(t))
        p1.addWidget(self.arm_name)
        p1.addStretch(1)
        self.stack.addWidget(page1)

        # Page 2: Disk calibration
        page2 = QWidget()
        p2 = QVBoxLayout(page2)
        p2.addWidget(QLabel("<b>Disk Calibration</b>"))
        p2.addWidget(QLabel("Measure your actual video bitrate and CSV sizes for more accurate estimates."))
        self.calib_status = QLabel("")
        self.calib_status.setWordWrap(True)
        p2.addWidget(self.calib_status)
        btn_calib = QPushButton("Run Disk Calibration")
        btn_calib.clicked.connect(lambda: parent_tab._start_disk_calibration(report_to=self.calib_status))
        p2.addWidget(btn_calib)
        p2.addStretch(1)
        self.stack.addWidget(page2)

        # Page 3: Theme + Layout
        page3 = QWidget()
        p3 = QVBoxLayout(page3)
        p3.addWidget(QLabel("<b>Theme & Layout</b>"))
        theme_row = QHBoxLayout()
        btn_light = QPushButton("Light")
        btn_light.clicked.connect(lambda: parent_tab._apply_theme("light", force=True))
        btn_dark = QPushButton("Dark")
        btn_dark.clicked.connect(lambda: parent_tab._apply_theme("dark", force=True))
        theme_row.addWidget(btn_light)
        theme_row.addWidget(btn_dark)
        p3.addLayout(theme_row)
        mirror = QCheckBox("Mirror Layout")
        mirror.setChecked(parent_tab._mirror_mode)
        mirror.toggled.connect(parent_tab._set_mirror_mode)
        p3.addWidget(mirror)
        wide = QCheckBox("Wide Layout (Top/Bottom)")
        wide.setChecked(parent_tab._wide_mode)
        wide.toggled.connect(parent_tab._set_wide_mode)
        p3.addWidget(wide)
        p3.addStretch(1)
        self.stack.addWidget(page3)

        # Page 4: Diagnostics
        page4 = QWidget()
        p4 = QVBoxLayout(page4)
        p4.addWidget(QLabel("<b>Diagnostics Mode</b>"))
        p4.addWidget(QLabel(
            "Enable optional diagnostics to record performance stats during long runs. "
            "This writes a diagnostics.csv in the run folder for later analysis."
        ))
        diag_toggle = QCheckBox("Enable Diagnostics Mode")
        diag_toggle.setChecked(parent_tab._diagnostics_enabled)
        diag_toggle.toggled.connect(parent_tab._set_diagnostics_enabled)
        p4.addWidget(diag_toggle)
        p4.addStretch(1)
        self.stack.addWidget(page4)

        # Page 5: Finish
        page5 = QWidget()
        p5 = QVBoxLayout(page5)
        p5.addWidget(QLabel("<b>All set.</b> You can reopen this guide from Settings any time."))
        self.chk_done = QCheckBox("Don't show this again")
        self.chk_done.setChecked(True)
        p5.addWidget(self.chk_done)
        p5.addStretch(1)
        self.stack.addWidget(page5)

        # Navigation
        nav = QHBoxLayout()
        self.btn_back = QPushButton("Back")
        self.btn_back.clicked.connect(self._back)
        self.btn_next = QPushButton("Next")
        self.btn_next.clicked.connect(self._next)
        self.btn_skip = QPushButton("Skip for now")
        self.btn_skip.clicked.connect(self.reject)
        nav.addWidget(self.btn_back)
        nav.addStretch(1)
        nav.addWidget(self.btn_skip)
        nav.addWidget(self.btn_next)
        layout.addLayout(nav)

        self._sync_nav()

    def _sync_nav(self):
        idx = self.stack.currentIndex()
        self.btn_back.setEnabled(idx > 0)
        if idx >= self.stack.count() - 1:
            self.btn_next.setText("Finish")
        else:
            self.btn_next.setText("Next")

    def _back(self):
        idx = max(0, self.stack.currentIndex() - 1)
        self.stack.setCurrentIndex(idx)
        self._sync_nav()

    def _next(self):
        idx = self.stack.currentIndex()
        if idx >= self.stack.count() - 1:
            if self.chk_done.isChecked():
                self.parent_tab._mark_starter_guide_complete()
            self.accept()
            return
        self.stack.setCurrentIndex(idx + 1)
        self._sync_nav()


class RunTab(QWidget):
    runCompleted = Signal(str, str)
    themeChanged = Signal(str)
    titleChanged = Signal(str)

    class StyledCombo(QComboBox):
        def __init__(self, popup_qss: str = "", *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._popup_qss = popup_qss

        def set_popup_qss(self, popup_qss: str):
            self._popup_qss = popup_qss

        def showPopup(self):
            try:
                v = self.view()
                if v is None:
                    self.setView(QListView())
                    v = self.view()
                v.viewport().setAutoFillBackground(True)
                v.setAutoFillBackground(True)
                v.setAttribute(Qt.WA_StyledBackground, True)
                v.setFrameShape(QFrame.NoFrame)
                
                v.setViewportMargins(0, 0, 0, 0)
                if hasattr(v, 'setSpacing'):
                    v.setSpacing(0)

                if self._popup_qss:
                    v.setStyleSheet(self._popup_qss)
                    v.viewport().setStyleSheet(
                        f"background: {MID}; border: none; margin: 0px; padding: 0px;"
                    )
                    popup_win = v.window()
                    if popup_win:
                        popup_win.setStyleSheet(
                            f"background: {MID}; border: 1px solid {BG}; margin: 0px; padding: 0px;"
                        )
                
                hint = 0
                # sizeHintForColumn works for QListView; add padding for checkmark/scrollbar
                if v.model() and v.model().rowCount() > 0:
                     hint = max(hint, v.sizeHintForColumn(0) + COMBO_HINT_PADDING)
                
                view_w = max(self.width(), hint, COMBO_POPUP_MIN_WIDTH)
                v.setFixedWidth(view_w)
                if hasattr(v, 'setHorizontalScrollBarPolicy'):
                    v.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

            except Exception as e:
                _log_gui_exception(e, "StyledCombo.showPopup setup")
            super().showPopup()

    def _build_combo_popup_qss(self) -> str:
        palette = self._theme
        bg = palette.get("MID", MID)
        text = palette.get("TEXT", TEXT)
        border = palette.get("BORDER", BORDER)
        accent = palette.get("ACCENT", ACCENT)
        base = palette.get("BG", BG)
        return (
            "QListView {"
            f"background: {bg};"
            f"color: {text};"
            f"border: 1px solid {border};"
            "border-radius: 0px;"
            "padding: 4px 0;"
            "outline: none;"
            "}"
            "QListView::item {"
            "padding: 6px 12px;"
            "background: transparent;"
            "}"
            "QListView::item:selected {"
            f"background: {accent};"
            f"color: {base};"
            "}"
        )

    def _refresh_combo_styles(self):
        popup_qss = self._build_combo_popup_qss()
        for combo in (getattr(self, "mode", None), getattr(self, "stepsize", None)):
            if combo is None:
                continue
            try:
                combo.set_popup_qss(popup_qss)
            except Exception:
                pass

    def _refresh_branding_styles(self):
        palette = self._theme if hasattr(self, "_theme") and self._theme else active_theme()
        accent = palette.get("ACCENT", ACCENT)
        text = palette.get("TEXT", TEXT)
        subtxt = palette.get("SUBTXT", SUBTXT)
        current_year = time.localtime().tm_year
        if hasattr(self, "logo_footer") and self.logo_footer:
            if self.logo_footer.pixmap() is None:
                try:
                    self.logo_footer.setStyleSheet(f"color: {accent}; font-size: 16pt; font-weight: bold;")
                except Exception:
                    pass
        if hasattr(self, "logo_tagline") and self.logo_tagline:
            try:
                self.logo_tagline.setText(
                    f'© {current_year} <a href="{CALIFORNIA_NUMERICS_URL}" '
                    f'style="color: {text}; text-decoration: none;">California Numerics</a>'
                )
                self.logo_tagline.setStyleSheet(
                    f"color: {text}; font-size: 10pt; font-weight: normal;"
                )
            except Exception:
                pass
        if hasattr(self, "replicant_status") and self.replicant_status:
            try:
                self.replicant_status.setStyleSheet(f"color: {subtxt};")
            except Exception:
                pass

    def _refresh_recording_indicator(self):
        if not hasattr(self, "rec_indicator"):
            return
        palette = self._theme if hasattr(self, "_theme") and self._theme else active_theme()
        danger = palette.get("DANGER", DANGER)
        subtxt = palette.get("SUBTXT", SUBTXT)
        if getattr(self, "_recording_active", False):
            try:
                self.rec_indicator.setText("● REC ON")
                self.rec_indicator.setStyleSheet(f"color:{danger}; font-weight:bold;")
            except Exception:
                pass
        else:
            try:
                self.rec_indicator.setText("● REC OFF")
                self.rec_indicator.setStyleSheet(f"color:{subtxt};")
            except Exception:
                pass

    def _apply_theme_to_widgets(self):
        theme = self._theme
        bg = theme.get("BG", BG)
        plot_face = theme.get("PLOT_FACE", bg)
        border = theme.get("BORDER", BORDER)
        try:
            self.video_view.set_theme(theme)
        except Exception:
            pass
        try:
            self.app_view.set_theme(theme)
        except Exception:
            pass
        try:
            self.video_area.set_theme(theme)
        except Exception:
            pass
        if hasattr(self, "chart_frame") and self.chart_frame:
            try:
                self.chart_frame.setStyleSheet(
                    f"background: {plot_face}; border: {CHART_FRAME_BORDER_PX}px solid {border};"
                )
            except Exception:
                pass
        try:
            self.live_chart.set_theme(theme)
        except Exception:
            pass
        try:
            self.splitter.set_theme(theme)
        except Exception:
            pass
        for pane in (getattr(self, "_left_widget", None), getattr(self, "_right_widget", None)):
            if pane is None:
                continue
            try:
                pal = pane.palette()
                pal.setColor(pane.backgroundRole(), QColor(bg))
                pane.setPalette(pal)
            except Exception:
                pass
        if getattr(self, "_right_scroll", None):
            try:
                self._right_scroll.setStyleSheet(f"QScrollArea {{ background: {BG}; border: 0px; }}")
            except Exception:
                pass
        if getattr(self, "_pip_window", None):
            try:
                self._pip_window.set_theme(theme)
            except Exception:
                pass
        try:
            if sys.platform == "darwin":
                set_macos_titlebar_appearance(self, QColor(BG))
        except Exception:
            pass
        try:
            self._apply_titlebar_theme()
        except Exception:
            pass
        self._update_mirror_layout()

    def _sync_logo_menu_checks(self):
        if hasattr(self, "_action_light_mode") and self._action_light_mode:
            try:
                self._action_light_mode.blockSignals(True)
                self._action_light_mode.setChecked(self._theme_name == "light")
                self._action_light_mode.blockSignals(False)
            except Exception:
                pass
        if hasattr(self, "_action_dark_mode") and self._action_dark_mode:
            try:
                self._action_dark_mode.blockSignals(True)
                self._action_dark_mode.setChecked(self._theme_name == "dark")
                self._action_dark_mode.blockSignals(False)
            except Exception:
                pass
        if hasattr(self, "_action_mirror_mode") and self._action_mirror_mode:
            try:
                self._action_mirror_mode.blockSignals(True)
                self._action_mirror_mode.setChecked(self._mirror_mode)
                self._action_mirror_mode.blockSignals(False)
            except Exception:
                pass
        if hasattr(self, "_action_wide_mode") and self._action_wide_mode:
            try:
                self._action_wide_mode.blockSignals(True)
                self._action_wide_mode.setChecked(self._wide_mode)
                self._action_wide_mode.blockSignals(False)
            except Exception:
                pass

    def _apply_theme(self, name: str, *, broadcast: bool = True, force: bool = False):
        if not force and name == self._theme_name:
            return
        old_bg = None
        try:
            if hasattr(self, "_theme") and self._theme:
                old_bg = self._theme.get("BG", BG)
        except Exception:
            old_bg = BG
        if broadcast:
            theme_map = set_active_theme(name)
        else:
            theme_map = THEMES.get(name, THEMES.get(DEFAULT_THEME_NAME, active_theme()))
        self._theme_name = name
        self._theme = dict(theme_map)
        if broadcast:
            app = QApplication.instance()
            if app is not None:
                try:
                    app.setStyleSheet(build_stylesheet(_FONT_FAMILY, self.ui_scale))
                except Exception:
                    pass
        self._refresh_combo_styles()
        self._apply_theme_to_widgets()
        self._refresh_branding_styles()
        self._refresh_recording_indicator()
        self._sync_logo_menu_checks()
        if broadcast and old_bg:
            self._start_theme_transition(old_bg)
        if broadcast:
            try:
                self.themeChanged.emit(name)
            except Exception:
                pass

    def apply_theme_external(self, name: str):
        self._apply_theme(name, broadcast=False, force=True)

    def _set_wide_mode(self, enabled: bool):
        enabled = bool(enabled)
        if enabled == self._wide_mode:
            return
        self._wide_mode = enabled
        self._update_layout_structure()
        self._sync_logo_menu_checks()

    def _update_layout_structure(self):
        target_orientation = Qt.Vertical if self._wide_mode else Qt.Horizontal
        
        # 1. Update Content Layout (Video/Chart)
        video = self.video_area
        chart = self.chart_frame
        
        # Ensure they are not deleted when we switch containers
        # We park them on 'self' temporarily
        video.setParent(self)
        chart.setParent(self)
        video.setVisible(True)
        chart.setVisible(True)

        new_content_container = QWidget()
        new_content_container.setAutoFillBackground(True)
        if self._left_widget:
            new_content_container.setPalette(self._left_widget.palette())
        
        if self._wide_mode:
            # Wide Mode: Top container is Horizontal [Video | Chart]
            layout = QHBoxLayout(new_content_container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(SPACING_MD)
            
            # Force expansion
            video.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            chart.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            
            layout.addWidget(video, 1)
            layout.addWidget(chart, 1)
        else:
            # Standard Mode: Left container is Vertical [Video / Chart]
            layout = QVBoxLayout(new_content_container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(SPACING_MD)
            
            # Restore smart sizing policies
            # AspectRatioContainer needs HeightForWidth in vertical stack
            sp_video = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            sp_video.setHeightForWidth(True)
            video.setSizePolicy(sp_video)
            
            # Chart can be preferred
            chart.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            
            # Allow them to take available space (don't align Top)
            layout.addWidget(video, 1)
            layout.addWidget(chart, 1)
            # Remove stretch at end so they fill the space naturally
            # layout.addStretch(1) 

        new_content_container.setMinimumSize(100, 100)
        new_content_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        new_content_container.show()

        # Update Splitter
        if self._left_widget:
            # Check if it's currently in the splitter
            idx = self.splitter.indexOf(self._left_widget)
            if idx >= 0:
                self._left_widget.hide()
                self.splitter.replaceWidget(idx, new_content_container)
                self._left_widget.deleteLater()
            else:
                self.splitter.addWidget(new_content_container)
        else:
            self.splitter.addWidget(new_content_container)
            
        self._left_widget = new_content_container
        
        # 2. Rebuild Control Layout
        self._rebuild_control_layout(self._wide_mode)

        # 3. Orientation & Sizing
        if self.splitter.orientation() != target_orientation:
            self.splitter.setOrientation(target_orientation)

        if self._wide_mode:
            self.splitter.setCollapsible(0, False)
            self.splitter.setCollapsible(1, False)
            # Size will be fixed by _update_mirror_layout immediately after
            # Lock window width to prevent column crushing
            self.splitter.setSizes([1000, 250])
            self.setMinimumWidth(1300)
        else:
            self.splitter.setCollapsible(0, False)
            self.splitter.setCollapsible(1, False)
            self.splitter.setSizes([1000, 380])
            # Restore standard minimum width
            self.setMinimumWidth(APP_MIN_SIZE[0])

        self._update_mirror_layout()
        
        # Schedule a forced update to ensure widgets appear
        # This fixes issues where reparented widgets remain hidden or zero-sized
        QTimer.singleShot(0, self._finalize_layout_update)

    def _finalize_layout_update(self):
        try:
            # Force visibility and updates on content widgets
            if hasattr(self, "video_area"):
                self.video_area.setVisible(True)
                self.video_area.updateGeometry()
            if hasattr(self, "chart_frame"):
                self.chart_frame.setVisible(True)
                self.chart_frame.updateGeometry()
            if getattr(self, "_left_widget", None):
                self._left_widget.setVisible(True)
            
            # Re-apply sizes using the centralized logic
            self._update_mirror_layout()
        except Exception:
            pass

    def _rebuild_control_layout(self, is_wide: bool):
        # 1. Create New Main Layout
        old_widget = self._right_widget
        new_widget = QWidget()
        new_widget.setAutoFillBackground(True)
        new_widget.setPalette(old_widget.palette())
        
        # sections: 0=Header, 1=Serial, 2=Camera, 3=Mode, 4=IO, 5=Footer(Stats), 6=Logo
        sections = self._section_layouts
        
        # Detach sections from old layout
        for section in sections:
            section.setParent(None) 
        
        if is_wide:
            main_layout = QHBoxLayout(new_widget)
            main_layout.setContentsMargins(SPACING_MD, SPACING_MD, SPACING_MD, SPACING_MD)
            main_layout.setSpacing(SECTION_GAP_LARGE)
            
            # Helper to create an equal-width column
            def make_col(*layouts):
                col_widget = QWidget()
                col_layout = QVBoxLayout(col_widget)
                col_layout.setContentsMargins(0, 0, 0, 0)
                col_layout.setSpacing(SPACING_SM)
                for l in layouts:
                    col_layout.addLayout(l)
                col_layout.addStretch(1)
                
                # Critical: Force equal width by ignoring content size hints
                # QSizePolicy.Ignored tells the layout to only use stretch factors
                sp = QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
                sp.setHorizontalStretch(1)
                col_widget.setSizePolicy(sp)
                return col_widget

            # Col 1: Status Line + Serial
            w1 = make_col(sections[0], sections[1], sections[5])
            
            # Col 2: Camera + Recording
            w2 = make_col(sections[2])
            
            # Col 3: Mode + Config
            w3 = make_col(sections[3])
            
            # Col 4: IO + Logo
            w4 = make_col(sections[4], sections[6])
            
            main_layout.addWidget(w1)
            main_layout.addWidget(w2)
            main_layout.addWidget(w3)
            main_layout.addWidget(w4)
            
        else:
            main_layout = QVBoxLayout(new_widget)
            # Match original margins
            main_layout.setContentsMargins(0, RIGHT_PANEL_TOP_MARGIN, 0, 0)
            main_layout.setSpacing(SECTION_GAP_LARGE)
            
            for i, section in enumerate(sections):
                main_layout.addLayout(section)
                if i == len(sections) - 1:
                    main_layout.addStretch(1)
        
        # Replace widget in scroll area
        self._right_scroll.setWidget(new_widget)
        self._right_widget = new_widget
        self._right_layout = main_layout
        
        # Ensure minimums
        if is_wide:
            new_widget.setMinimumWidth(1300) # Match window constraint
            new_widget.setMinimumHeight(200)
        else:
            new_widget.setMinimumWidth(RIGHT_PANEL_MIN_WIDTH)
            new_widget.setMinimumHeight(600)

    def _update_mirror_layout(self):
        split = getattr(self, "splitter", None)
        left = getattr(self, "_left_widget", None)   # Video/Chart Container
        right = getattr(self, "_right_scroll", None) # Controls Container
        if split is None or left is None or right is None:
            return
        
        # Mirror mode logic:
        # Standard: Content -> Controls
        # Mirror: Controls -> Content
        desired = (right, left) if self._mirror_mode else (left, right)
        
        # Reorder widgets
        for idx, widget in enumerate(desired):
            current_idx = split.indexOf(widget)
            if current_idx == -1 or current_idx == idx:
                continue
            try:
                split.blockSignals(True)
                split.insertWidget(idx, widget)
            finally:
                split.blockSignals(False)
        
        # Enforce strict sizing policies
        is_vertical = (split.orientation() == Qt.Vertical)
        
        try:
            # Determine fixed size for controls pane
            fixed_size = MIRROR_SPLITTER_FIXED_WIDTH 
            if is_vertical:
                # Use a slightly smaller height for controls in vertical mode if desired
                # But 380 is a safe bet for the scroll area content
                fixed_size = 250 

            # Apply sizes based on mirror mode
            if self._mirror_mode:
                # [Controls, Content]
                if is_vertical:
                    # Wide Mode Mirrored: Controls on Top
                    split.setSizes([fixed_size, 10000])
                else:
                    # Standard Mode Mirrored: Controls on Left
                    split.setSizes([fixed_size, MIRROR_SPLITTER_FILL])
            else:
                # [Content, Controls]
                if is_vertical:
                    # Wide Mode Standard: Controls on Bottom
                    split.setSizes([10000, fixed_size])
                else:
                    # Standard Mode Standard: Controls on Right
                    split.setSizes([MIRROR_SPLITTER_FILL, fixed_size])
        except Exception:
            pass

        try:
            # Ensure Content stretches and Controls are fixed
            idx_content = split.indexOf(left)
            idx_ctrl = split.indexOf(right)
            if idx_content >= 0:
                split.setStretchFactor(idx_content, 1)
            if idx_ctrl >= 0:
                split.setStretchFactor(idx_ctrl, 0)
            
            # Re-disable handle interaction but keep spacing
            split.setHandleWidth(SPLITTER_HANDLE_WIDTH)
            split.setRubberBand(-1)
            handle = split.handle(1)
            if handle:
                handle.setEnabled(False)
                handle.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        except Exception:
            pass
        self._apply_control_alignment()

    def _apply_control_alignment(self):
        right = getattr(self, "_right_layout", None)
        sections = getattr(self, "_section_layouts", None)
        if right is None or not sections:
            return
        align_controls = Qt.AlignRight | Qt.AlignTop
        if getattr(self, "_mirror_mode", False):
            align_controls = Qt.AlignLeft | Qt.AlignTop
        for idx, section in enumerate(sections):
            try:
                if idx == 0:
                    right.setAlignment(section, Qt.AlignLeft | Qt.AlignTop)
                else:
                    right.setAlignment(section, align_controls)
            except Exception:
                pass

    def _set_mirror_mode(self, enabled: bool):
        enabled = bool(enabled)
        if enabled == self._mirror_mode:
            return
        self._mirror_mode = enabled
        self._update_mirror_layout()
        self._sync_logo_menu_checks()

    def _start_theme_transition(self, from_color: str | QColor | None):
        if not from_color:
            return
        try:
            color = QColor(from_color)
            if not color.isValid():
                raise ValueError
        except Exception:
            color = QColor(BG)
        prev_anim = getattr(self, "_theme_overlay_anim", None)
        if prev_anim is not None:
            try:
                prev_anim.stop()
            except Exception:
                pass
            self._theme_overlay_anim = None
        overlay = getattr(self, "_theme_overlay", None)
        if overlay is not None:
            try:
                overlay.deleteLater()
            except Exception:
                pass
            self._theme_overlay = None
        overlay = QWidget(self)
        overlay.setObjectName("ThemeTransitionOverlay")
        overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        overlay.setAutoFillBackground(True)
        pal = overlay.palette()
        pal.setColor(overlay.backgroundRole(), color)
        overlay.setPalette(pal)
        overlay.setGeometry(self.rect())
        overlay.show()
        overlay.raise_()
        effect = QGraphicsOpacityEffect(overlay)
        overlay.setGraphicsEffect(effect)
        effect.setOpacity(1.0)
        anim = QPropertyAnimation(effect, b"opacity", overlay)
        anim.setDuration(THEME_TRANSITION_MS)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InOutQuad)

        def _cleanup():
            try:
                overlay.deleteLater()
            except Exception:
                pass
            self._theme_overlay = None
            self._theme_overlay_anim = None

        anim.finished.connect(_cleanup)
        anim.start(QAbstractAnimation.DeleteWhenStopped)
        self._theme_overlay = overlay
        self._theme_overlay_anim = anim

    def __init__(self, resource_registry: ResourceRegistry | None = None):
        super().__init__()
        self._resource_registry = resource_registry
        self.ui_scale = 1.0
        self._theme_name = _ACTIVE_THEME_NAME
        self._theme = dict(active_theme())
        self._mirror_mode = False
        self._wide_mode = False
        self._settings_dialog = None
        self._theme_overlay: QWidget | None = None
        self._theme_overlay_anim: QPropertyAnimation | None = None

        # Top dense status line + inline logo
        header_row = QHBoxLayout()
        self.arm_name_edit = QLineEdit()
        self.arm_name_edit.setPlaceholderText("Arm Name (e.g. Arm A)")
        self.arm_name_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.arm_name_edit.textChanged.connect(lambda t: self.titleChanged.emit(t if t.strip() else "Run Tab"))
        
        self.statusline = QLabel("—")
        self.statusline.setObjectName("StatusLine")
        self.statusline.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.statusline.setWordWrap(True)
        self.statusline.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        header_row.addWidget(self.statusline, 1)

        # Video preview (zoomable/pannable)
        self.video_view = ZoomView(bg_color=self._theme.get("BG", BG))
        try:
            self.video_view.firstFrame.connect(self._on_preview_first_frame)
        except Exception:
            pass
        # Remove native frame/border; container draws border
        try:
            self.video_view.setFrameShape(QFrame.NoFrame)
        except Exception:
            pass
        self.video_view.setStyleSheet("border: none; background: transparent;")
        self.video_view.setFocusPolicy(Qt.NoFocus)
        self.video_view.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.video_view.setMinimumSize(*VIDEO_VIEW_MIN_SIZE)

        # Serial controls
        self.port_edit = QComboBox()
        self.port_edit.setEditable(True)
        self.port_edit.setInsertPolicy(QComboBox.NoInsert)
        self.port_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.port_edit.lineEdit().setPlaceholderText("COM3 or /dev/ttyUSB0")
        self._refresh_serial_ports(initial=True)
        self.serial_btn = QPushButton("Connect")
        self.enable_btn = QPushButton("Enable Motor")
        self.disable_btn = QPushButton("Disable Motor")
        self.tap_btn = QPushButton("Manual Tap")
        # Jog controls (half‑step moves handled by firmware)
        self.jog_up_btn = QPushButton("Raise Arm ▲")
        self.jog_down_btn = QPushButton("Lower Arm ▼")
        self.jog_up_btn.setToolTip("Raise tapper arm (half step)")
        self.jog_down_btn.setToolTip("Lower tapper arm (half step)")

        # Camera controls
        self.cam_index = QSpinBox()
        self.cam_index.setRange(CAMERA_INDEX_MIN, CAMERA_INDEX_MAX)
        self.cam_index.setValue(CAMERA_INDEX_DEFAULT)
        self.cam_btn = QPushButton("Open")
        self.cam_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Recording controls (independent)
        self.rec_start_btn = QPushButton("Start")
        self.rec_start_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.rec_stop_btn  = QPushButton("Stop")
        self.rec_stop_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.rec_indicator = QLabel("● REC OFF")
        self._recording_active = False

        # Scheduler controls
        popup_qss = self._build_combo_popup_qss()
        self.mode = RunTab.StyledCombo(popup_qss=popup_qss); self.mode.addItems(["Periodic", "Poisson"])
        # Stabilize width and style popup to avoid clipping
        self.mode.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        fm = self.mode.fontMetrics()
        max_text = max((self.mode.itemText(i) for i in range(self.mode.count())), key=len)
        mode_w = fm.horizontalAdvance(max_text) + MODE_COMBO_TEXT_PADDING
        self.mode.setMinimumWidth(MODE_COMBO_MIN_WIDTH)
        self.mode.setMaximumWidth(max(MODE_COMBO_MAX_WIDTH_MIN, mode_w + MODE_COMBO_WIDTH_PADDING))
        self.mode.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        mv = QListView(); self.mode.setView(mv)
        mv.viewport().setAutoFillBackground(True)
        mv.setAutoFillBackground(True)
        mv.setAttribute(Qt.WA_StyledBackground, True)
        mv.setFrameShape(QFrame.NoFrame)
        self.period_sec = QDoubleSpinBox()
        self.period_sec.setRange(PERIOD_MIN_S, PERIOD_MAX_S)
        self.period_sec.setValue(PERIOD_DEFAULT_S)
        self.period_sec.setSuffix(" s")
        self.period_sec.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.lambda_rpm = QDoubleSpinBox()
        self.lambda_rpm.setRange(LAMBDA_MIN_RPM, LAMBDA_MAX_RPM)
        self.lambda_rpm.setValue(LAMBDA_DEFAULT_RPM)
        self.lambda_rpm.setSuffix(" taps/min")
        self.lambda_rpm.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        shared_control_width = CONTROL_WIDTH
        self.mode.setFixedWidth(shared_control_width)
        self.period_sec.setFixedWidth(shared_control_width)
        self.lambda_rpm.setFixedWidth(shared_control_width)

        # Stepsize (1..5) — sent to firmware, logged per-tap
        self.stepsize = RunTab.StyledCombo(popup_qss=popup_qss)
        self.stepsize.addItems(STEPSIZE_OPTIONS)
        self.stepsize.setCurrentIndex(0)
        # Apply same styled popup to stepsize combobox
        sv = QListView(); self.stepsize.setView(sv)
        sv.viewport().setAutoFillBackground(True)
        sv.setAutoFillBackground(True)
        sv.setAttribute(Qt.WA_StyledBackground, True)
        sv.setFrameShape(QFrame.NoFrame)
        # Compute Stepsize minimum width from item text to avoid clipping while allowing expansion
        self.stepsize.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        s_fm = self.stepsize.fontMetrics()
        try:
            s_max_text = max((self.stepsize.itemText(i) for i in range(self.stepsize.count())), key=len)
        except ValueError:
            s_max_text = str(STEPSIZE_MAX)
        s_w = s_fm.horizontalAdvance(s_max_text) + STEPSIZE_TEXT_PADDING  # text + arrow/padding
        self.stepsize.setFixedWidth(max(shared_control_width, s_w + STEPSIZE_WIDTH_PADDING))
        self.stepsize.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # Replicant replay controls
        self.replicant_load_btn = QPushButton("Load CSV…")
        self.replicant_load_btn.clicked.connect(self._load_replicant_csv)
        self.replicant_clear_btn = QPushButton("Clear")
        self.replicant_clear_btn.clicked.connect(self._clear_replicant_csv)
        self.replicant_status = QLabel("No script loaded")
        self.replicant_status.setWordWrap(False)
        self.replicant_status.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.replicant_status.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)

        # Run controls
        self.run_start_btn = QPushButton("Start Run")
        self.run_stop_btn  = QPushButton("Stop Run")
        self.clear_data_btn = QPushButton("Clear Data")
        self.clear_data_btn.setToolTip("Reset the counters and live chart manually.")

        # Output directory
        self.outdir_edit = QLineEdit()
        self.outdir_edit.setText(str(RUNS_DIR))
        self.outdir_btn  = QPushButton("Choose Output Dir")

        # Config Save/Load
        self.save_cfg_btn = QPushButton("Save Config")
        self.load_cfg_btn = QPushButton("Load Last Config")
        self.flash_config_btn = QPushButton("Flash Hardware Config")
        self.flash_config_btn.setToolTip("Send the current mode, step size, and timing to the controller without starting a run")
        self.flash_config_btn.clicked.connect(self._flash_hardware_config)

        # Pro Mode (keyboard-first interaction)
        self.pro_btn = QPushButton("PM: OFF")
        self.pro_btn.setCheckable(True)
        self.pro_btn.toggled.connect(self._toggle_pro_mode)
        self.pro_mode = False

        # Live chart (template-like raster): embedded Matplotlib, Typestar font
        self.live_chart = LiveChart(font_family=_FONT_FAMILY, theme=self._theme)
        # Wrap chart in a framed panel to match other boxes (use BG to match general background)
        self.chart_frame = QFrame()
        # Match the video preview container styling exactly
        self.chart_frame.setStyleSheet(
            f"background: {BG}; border: {CHART_FRAME_BORDER_PX}px solid {BORDER};"
        )
        self.chart_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        chart_layout = QVBoxLayout(self.chart_frame)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_layout.addWidget(self.live_chart.canvas)
        chart_controls = QHBoxLayout()
        chart_controls.setContentsMargins(0, CHART_CONTROLS_TOP_MARGIN_PX, 0, 0)
        chart_controls.setSpacing(CHART_CONTROLS_SPACING_PX)
        self.long_mode_combo = QComboBox()
        self.long_mode_combo.addItem("Tap Raster", "taps")
        self.long_mode_combo.addItem("Contraction Heatmap", "contraction")
        self.long_mode_combo.currentIndexChanged.connect(self._on_long_mode_view_changed)
        self.long_mode_combo.setVisible(False)
        chart_controls.addWidget(self.long_mode_combo)
        self.export_plot_btn = QPushButton("Export Plot…")
        self.export_plot_btn.clicked.connect(self._export_live_chart)
        chart_controls.addStretch(1)
        chart_controls.addWidget(self.export_plot_btn)
        chart_layout.addLayout(chart_controls)
        self.live_chart.add_long_mode_listener(self._on_live_chart_long_mode)
        # Keep the chart compact so it doesn't force vertical centering
        # Let the canvas drive height; avoid hard caps so layout stays natural

        # Secondary status
        self.status   = QLabel("Idle.")
        self.status.setWordWrap(True)
        try:
            self.status.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        except Exception:
            pass
        self.status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.counters = QLabel(
            "Taps: 0 | Contractions: 0 | Elapsed: 0 s | Rate10: -- /min | Overall: 0.0 /min"
        )
        self.counters.setWordWrap(True)
        serial_status_row = QHBoxLayout()
        serial_status_row.setContentsMargins(0, 0, 0, 0)
        serial_status_row.setSpacing(STATUS_ROW_SPACING)

        self.serial_status = QLabel("Last serial command: —")
        self.serial_status.setWordWrap(True)
        try:
            self.serial_status.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        except Exception:
            pass
        self.serial_status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        serial_status_row.addWidget(self.serial_status, 1)

        self.logo_footer = QLabel()
        self.logo_footer.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        footer_pm = None
        if LOGO_PATH.exists():
            candidate = QPixmap(str(LOGO_PATH))
            if not candidate.isNull():
                target_w = max(1, int(candidate.width() * FOOTER_LOGO_SCALE))
                target_h = max(1, int(candidate.height() * FOOTER_LOGO_SCALE))
                footer_pm = candidate.scaled(target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if footer_pm is not None:
            src = footer_pm.toImage().convertToFormat(QImage.Format_ARGB32)
            w, h = src.width(), src.height()
            alpha_threshold = LOGO_ALPHA_THRESHOLD
            # Trim near-transparent padding so the outline tracks the glyph, not the image box
            min_x, min_y = w, h
            max_x, max_y = -1, -1
            for y in range(h):
                for x in range(w):
                    if src.pixelColor(x, y).alpha() > alpha_threshold:
                        if x < min_x: min_x = x
                        if y < min_y: min_y = y
                        if x > max_x: max_x = x
                        if y > max_y: max_y = y
            if max_x >= min_x and max_y >= min_y:
                crop_w = max_x - min_x + 1
                crop_h = max_y - min_y + 1
                footer_pm = footer_pm.copy(min_x, min_y, crop_w, crop_h)
                src = src.copy(min_x, min_y, crop_w, crop_h)
                w, h = crop_w, crop_h

            masked = QPixmap(w, h)
            masked.fill(Qt.transparent)
            painter = QPainter(masked)
            painter.fillRect(masked.rect(), Qt.black)
            painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            painter.drawPixmap(0, 0, footer_pm)
            painter.end()

            outline = QImage(w, h, QImage.Format_ARGB32)
            outline.fill(Qt.transparent)
            for y in range(h):
                for x in range(w):
                    if src.pixelColor(x, y).alpha() <= alpha_threshold:
                        continue
                    edge = False
                    for dx in (-1, 0, 1):
                        for dy in (-1, 0, 1):
                            if dx == 0 and dy == 0:
                                continue
                            nx, ny = x + dx, y + dy
                            if nx < 0 or ny < 0 or nx >= w or ny >= h or src.pixelColor(nx, ny).alpha() <= alpha_threshold:
                                edge = True
                                break
                        if edge:
                            break
                    if edge:
                        outline.setPixelColor(x, y, QColor(BORDER))

            composed = QPixmap(w, h)
            composed.fill(Qt.transparent)
            painter = QPainter(composed)
            painter.drawPixmap(0, 0, masked)
            painter.drawImage(0, 0, outline)
            painter.end()
            self.logo_footer.setPixmap(composed)
        else:
            self.logo_footer.setText("NEMESIS")
            self.logo_footer.setStyleSheet(f"color: {ACCENT}; font-size: 16pt; font-weight: bold;")
        self.logo_footer.setContentsMargins(0, 0, 0, 0)
        self.logo_footer.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.logo_footer.setCursor(Qt.PointingHandCursor)
        self.logo_footer.setToolTip("Show quick actions")
        self.logo_footer.mousePressEvent = self._logo_pressed

        current_year = time.localtime().tm_year
        self.logo_tagline = QLabel(
            f'© {current_year} <a href="{CALIFORNIA_NUMERICS_URL}" '
            f'style="color: {TEXT}; text-decoration: none;">California Numerics</a>'
        )
        self.logo_tagline.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.logo_tagline.setTextFormat(Qt.RichText)
        self.logo_tagline.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.logo_tagline.setOpenExternalLinks(True)
        self.logo_tagline.setCursor(Qt.PointingHandCursor)
        self.logo_tagline.setStyleSheet(
            f"color: {TEXT}; font-size: 10pt; font-weight: normal;"
        )
        self.logo_tagline.setContentsMargins(0, LOGO_TAGLINE_TOP_MARGIN_PX, 0, 0)
        self.logo_tagline.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self.logo_menu = self._build_logo_menu()
        serial_status_row.addStretch(1)  # keep status text left-aligned

        # Layout
        # Left pane: 16:9-bounded preview, then chart
        left = QVBoxLayout(); left.setContentsMargins(0, 0, 0, 0); left.setSpacing(SPACING_MD)
        self.video_area = AspectRatioContainer(
            self.video_view, PREVIEW_ASPECT_RATIO[0], PREVIEW_ASPECT_RATIO[1]
        )
        try:
            self.video_area.setMinimumSize(*VIDEO_AREA_MIN_SIZE)
        except Exception:
            pass
        sp_video = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        sp_video.setHeightForWidth(True)
        self.video_area.setSizePolicy(sp_video)
        self.chart_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        left.addWidget(self.video_area, 1)
        left.addWidget(self.chart_frame, 1)
        # Top margin keeps controls clear of the window chrome
        right = QVBoxLayout()
        right.setContentsMargins(0, RIGHT_PANEL_TOP_MARGIN, 0, 0)
        right.setSpacing(SPACING_MD)

        top_status_section = QVBoxLayout()
        top_status_section.setContentsMargins(0, 0, 0, 0)
        top_status_section.setSpacing(0)
        top_status_section.addLayout(header_row)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Serial:"))
        r1.addWidget(self.port_edit, 1)
        r1.addWidget(self.serial_btn)
        r1.addWidget(self.pro_btn)

        r1b = QHBoxLayout(); r1b.addWidget(self.enable_btn); r1b.addWidget(self.disable_btn); r1b.addWidget(self.tap_btn)
        # Place jog controls directly under Activate/Deactivate row
        r1c = QHBoxLayout(); r1c.addWidget(self.jog_down_btn); r1c.addWidget(self.jog_up_btn)
        serial_ctrl_section = QVBoxLayout()
        serial_ctrl_section.setContentsMargins(0, 0, 0, 0)
        serial_ctrl_section.setSpacing(SPACING_SM)
        serial_ctrl_section.addLayout(r1)
        serial_ctrl_section.addLayout(r1b)
        serial_ctrl_section.addLayout(r1c)

        r2 = QHBoxLayout(); r2.addWidget(QLabel("Camera idx:")); r2.addWidget(self.cam_index); r2.addWidget(self.cam_btn)
        self.popout_btn = QPushButton("POP")
        self.popout_btn.setCheckable(True)
        self.popout_btn.setToolTip("Open a floating always-on-top preview window")
        self.popout_btn.toggled.connect(self._toggle_preview_popout)
        self.popout_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        r2.addWidget(self.popout_btn)
        
        self.show_cv_check = QCheckBox("Analogue")
        self.show_cv_check.setToolTip("Overlay Stentor tracking and state classification")
        r2.addWidget(self.show_cv_check)
        
        self.auto_rec_check = QCheckBox("Rec")
        self.auto_rec_check.setToolTip("Start recording automatically when the run starts")
        r2b = QHBoxLayout(); r2b.addWidget(self.rec_start_btn); r2b.addWidget(self.rec_stop_btn); r2b.addWidget(self.rec_indicator); r2b.addWidget(self.auto_rec_check)
        camera_section = QVBoxLayout()
        camera_section.setContentsMargins(0, 0, 0, 0)
        camera_section.setSpacing(SPACING_SM)
        camera_section.addLayout(r2)
        camera_section.addLayout(r2b)

        # Stable label widths to prevent relayout
        self.lbl_mode = QLabel("Mode:")
        self.lbl_period = QLabel("Period:")
        self.lbl_lambda = QLabel("λ (taps/min):")
        self.lbl_stepsize = QLabel("Stepsize:")
        self.lbl_replicant = QLabel("Replicant:")
        self.lbl_warmup = QLabel("Warmup:")
        self.lbl_acclimation = QLabel("Acclimation:")
        self.lbl_autostop = QLabel("Stop after (min):")
        lfm = self.lbl_mode.fontMetrics()
        label_w = max(
            lfm.horizontalAdvance("Mode:"),
            lfm.horizontalAdvance("Period:"),
            lfm.horizontalAdvance("λ (taps/min):"),
            lfm.horizontalAdvance("Stepsize:"),
            lfm.horizontalAdvance("Replicant:"),
            lfm.horizontalAdvance("Warmup:"),
            lfm.horizontalAdvance("Acclimation:"),
            lfm.horizontalAdvance("Stop after (min):")
        ) + LABEL_WIDTH_PADDING_PX
        for lbl in (self.lbl_mode, self.lbl_period, self.lbl_lambda, self.lbl_stepsize, self.lbl_replicant, self.lbl_warmup, self.lbl_acclimation, self.lbl_autostop):
            lbl.setFixedWidth(label_w)
        controls_grid = QGridLayout()
        controls_grid.setContentsMargins(0, 0, 0, 0)
        controls_grid.setHorizontalSpacing(SPACING_SM)
        controls_grid.setVerticalSpacing(SPACING_XS)
        replicant_controls = QHBoxLayout()
        replicant_controls.setContentsMargins(0, 0, 0, 0)
        replicant_controls.setSpacing(SPACING_SM)
        replicant_controls.addWidget(self.replicant_status, 1, Qt.AlignLeft)
        replicant_controls.addStretch(1)
        replicant_controls.addWidget(self.replicant_load_btn, 0, Qt.AlignRight)
        replicant_controls.addWidget(self.replicant_clear_btn, 0, Qt.AlignRight)

        # Warmup control
        self.warmup_sec = QDoubleSpinBox()
        self.warmup_sec.setRange(WARMUP_MIN_S, WARMUP_MAX_S)
        self.warmup_sec.setValue(WARMUP_DEFAULT_S)
        self.warmup_sec.setDecimals(WARMUP_DECIMALS)
        self.warmup_sec.setSuffix(" s")
        self.warmup_sec.setSpecialValueText("Off")
        self.warmup_sec.setFixedWidth(CONTROL_WIDTH)
        self.warmup_sec.setToolTip(
            "Delay after recording starts but before the first tap fires."
        )

        # Acclimation control
        self.acclimation_min = QDoubleSpinBox()
        self.acclimation_min.setRange(0.0, 1440.0) # Up to 24 hours
        self.acclimation_min.setValue(0.0)
        self.acclimation_min.setDecimals(1)
        self.acclimation_min.setSuffix(" min")
        self.acclimation_min.setSpecialValueText("Off")
        self.acclimation_min.setFixedWidth(CONTROL_WIDTH)
        self.acclimation_min.setToolTip("Initial settling period (no recording/stimuli) before the run officially starts.")

        # Auto-stop control
        self.auto_stop_min = QDoubleSpinBox()
        self.auto_stop_min.setRange(AUTO_STOP_MIN_MIN, AUTO_STOP_MAX_MIN)
        self.auto_stop_min.setValue(AUTO_STOP_MIN_MIN)
        self.auto_stop_min.setDecimals(AUTO_STOP_DECIMALS)
        self.auto_stop_min.setSuffix(" min")
        self.auto_stop_min.setSpecialValueText("Off")
        self.auto_stop_min.setFixedWidth(AUTO_STOP_CONTROL_WIDTH)
        self.auto_stop_min.setToolTip("Stop run automatically after N minutes (0=Off)")
        
        controls_grid.addWidget(self.lbl_replicant, 0, 0, Qt.AlignLeft)
        controls_grid.addLayout(replicant_controls, 0, 1)
        controls_grid.addWidget(self.lbl_mode, 1, 0, Qt.AlignLeft)
        controls_grid.addWidget(self.mode, 1, 1, Qt.AlignRight)
        controls_grid.addWidget(self.lbl_period, 2, 0, Qt.AlignLeft)
        controls_grid.addWidget(self.period_sec, 2, 1, Qt.AlignRight)
        controls_grid.addWidget(self.lbl_lambda, 3, 0, Qt.AlignLeft)
        controls_grid.addWidget(self.lambda_rpm, 3, 1, Qt.AlignRight)
        controls_grid.addWidget(self.lbl_stepsize, 4, 0, Qt.AlignLeft)
        controls_grid.addWidget(self.stepsize, 4, 1, Qt.AlignRight)
        controls_grid.addWidget(self.lbl_warmup, 5, 0, Qt.AlignLeft)
        controls_grid.addWidget(self.warmup_sec, 5, 1, Qt.AlignRight)
        controls_grid.addWidget(self.lbl_acclimation, 6, 0, Qt.AlignLeft)
        controls_grid.addWidget(self.acclimation_min, 6, 1, Qt.AlignRight)
        controls_grid.addWidget(self.lbl_autostop, 7, 0, Qt.AlignLeft)
        controls_grid.addWidget(self.auto_stop_min, 7, 1, Qt.AlignRight)
        controls_grid.setColumnStretch(1, 1)
        mode_section = QVBoxLayout()
        mode_section.setContentsMargins(0, 0, 0, 0)
        mode_section.setSpacing(SPACING_SM)
        mode_section.addLayout(controls_grid)
        flash_row = QHBoxLayout(); flash_row.setContentsMargins(0, 0, 0, 0); flash_row.addWidget(self.flash_config_btn, 1)
        mode_section.addLayout(flash_row)

        r4 = QHBoxLayout(); r4.addWidget(self.run_start_btn); r4.addWidget(self.run_stop_btn); r4.addWidget(self.clear_data_btn)
        r5 = QHBoxLayout(); r5.addWidget(QLabel("Output dir:")); r5.addWidget(self.outdir_edit,1); r5.addWidget(self.outdir_btn)
        r5a = QHBoxLayout(); r5a.addWidget(QLabel("Arm name:")); r5a.addWidget(self.arm_name_edit, 1)

        # Config save/load row (was missing from layout)
        r5b = QHBoxLayout(); r5b.addWidget(self.save_cfg_btn); r5b.addWidget(self.load_cfg_btn)
        r5c = QHBoxLayout(); r5c.addWidget(self.flash_config_btn, 1)

        io_section = QVBoxLayout()
        io_section.setContentsMargins(0, 0, 0, 0)
        io_section.setSpacing(SPACING_SM)
        io_section.addLayout(r4)
        io_section.addLayout(r5)
        io_section.addLayout(r5a)
        io_section.addLayout(r5b)

        # (chart moved under the video preview)
        footer_status_section = QVBoxLayout()
        footer_status_section.setContentsMargins(0, 0, 0, 0)
        footer_status_section.setSpacing(SPACING_SM)
        footer_status_section.addWidget(self.counters)
        footer_status_section.addWidget(self.status)
        footer_status_section.addLayout(serial_status_row)

        logo_section = QVBoxLayout()
        logo_section.setContentsMargins(0, 0, 0, 0)
        logo_section.setSpacing(0)
        logo_row = QHBoxLayout()
        logo_row.setContentsMargins(0, LOGO_ROW_TOP_MARGIN_PX, 0, 0)  # small gap above helps line up with chart base
        logo_block = QVBoxLayout()
        logo_block.setContentsMargins(0, 0, 0, 0)
        logo_block.setSpacing(LOGO_BLOCK_SPACING_PX)
        logo_block.addWidget(self.logo_footer, 0, Qt.AlignLeft | Qt.AlignBottom)
        logo_block.addWidget(self.logo_tagline, 0, Qt.AlignLeft | Qt.AlignTop)
        logo_row.addLayout(logo_block)
        logo_row.addStretch(1)
        logo_section.addLayout(logo_row)
        logo_section.addStretch(1)

        section_gap = SECTION_GAP_LARGE  # triple gap keeps clusters distinct without feeling sparse
        self._section_gap = section_gap
        sections = [
            top_status_section,
            serial_ctrl_section,
            camera_section,
            mode_section,
            io_section,
            footer_status_section,
            logo_section,
        ]
        self._section_layouts = sections
        self._section_spacers = []
        for idx, section in enumerate(sections):
            right.addLayout(section)
            if idx < len(sections) - 1:
                spacer = QSpacerItem(0, section_gap, QSizePolicy.Minimum, QSizePolicy.Fixed)
                self._section_spacers.append(spacer)
                right.addItem(spacer)


        # Decouple panes with a splitter so right-side changes don't tug the preview
        leftw = QWidget(); leftw.setLayout(left)
        leftw.setAutoFillBackground(True)
        pal_left = leftw.palette(); pal_left.setColor(leftw.backgroundRole(), QColor(BG)); leftw.setPalette(pal_left)
        try:
            # Prevent splitter from shrinking left content beneath a usable width
            leftw.setMinimumWidth(max(LEFT_PANEL_MIN_WIDTH, self.video_area.minimumWidth()))
        except Exception:
            pass
        rightw = QWidget()
        rightw.setLayout(right)
        self._right_layout = right
        self._right_widget = rightw
        rightw.setAutoFillBackground(True)
        pal_right = rightw.palette(); pal_right.setColor(rightw.backgroundRole(), QColor(BG)); rightw.setPalette(pal_right)
        try:
            rightw.setMinimumWidth(RIGHT_PANEL_MIN_WIDTH)
        except Exception:
            pass
        right_scroll = QScrollArea()
        right_scroll.setWidget(rightw)
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        right_scroll.setMinimumWidth(RIGHT_SCROLL_MIN_WIDTH)
        self._right_scroll = right_scroll
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(leftw)
        splitter.addWidget(right_scroll)
        splitter.setChildrenCollapsible(False)
        try:
            splitter.setCollapsible(0, False)
            splitter.setCollapsible(1, False)
        except Exception:
            pass
        splitter.setHandleWidth(SPLITTER_HANDLE_WIDTH)
        try:
            splitter.setRubberBand(-1)
        except Exception:
            pass
        try:
            handle = splitter.handle(1)
            if handle:
                handle.setEnabled(False)
                handle.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        except Exception:
            pass
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        try:
            total = max(1, self.width())
            left = int(round(total * SPLITTER_LEFT_RATIO))
            right = max(RIGHT_PANEL_MIN_WIDTH, total - left)
            splitter.setSizes([left, right])
        except Exception:
            pass

        self._left_widget = leftw
        self.splitter = splitter

        # Wrap entire UI content in a zoomable view for browser-like zoom
        contentw = QWidget()
        content_layout = QHBoxLayout(contentw)
        content_layout.setContentsMargins(0,0,0,0)
        content_layout.addWidget(splitter)
        contentw.setMinimumSize(*CONTENT_MIN_SIZE)
        self.app_view = AppZoomView(bg_color=self._theme.get("BG", BG))
        self.app_view.set_content(contentw)
        # Enforce a minimum window size that encompasses the full UI content
        try:
            min_hint = contentw.minimumSizeHint()
            if not min_hint.isValid() or min_hint.width() <= 0:
                min_hint = contentw.sizeHint()
            min_w = max(APP_MIN_SIZE[0], min_hint.width())
            min_h = max(APP_MIN_SIZE[1], min_hint.height())
            self.setMinimumSize(min_w, min_h)
            # Ensure initial window isn't smaller than minimum content
            self.resize(max(self.width(), min_w), max(self.height(), min_h))
        except Exception:
            pass
        root = QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.addWidget(self.app_view)
        # Finalize minimum size after the widget is laid out so viewport >= content minimum
        QTimer.singleShot(0, self._adjust_min_window_size)
        QTimer.singleShot(0, self._apply_titlebar_theme)
        QTimer.singleShot(0, self._update_section_spacers)
        self._refresh_combo_styles()
        self._refresh_branding_styles()
        self._refresh_recording_indicator()
        self._sync_logo_menu_checks()
        self._update_mirror_layout()
        self._init_run_lock_controls()

        # State
        self.cap = None
        self.recorder = None
        self._frame_worker: FrameWorker | None = None
        
        # CV Worker (Process-based)
        self.cv_worker = ProcessCVWorker()
        self.cv_worker.resultsReady.connect(self._on_cv_results)
        
        # Render Worker (Offload UI composition)
        self.render_worker = RenderWorker()
        self.render_worker.imageReady.connect(self._on_render_ready)
        self.render_worker.start()
        
        self.run_timer   = QTimer(self); self.run_timer.setSingleShot(True); self.run_timer.timeout.connect(self._on_tap_due)
        self.session = RunSession()
        self.session.reset_runtime_state()
        self.serial = self.session.serial
        self._pending_taps = deque()
        self._contraction_count = 0
        self._last_cv_states: dict[int, str] = {}
        self._hardware_run_active = False
        self._hardware_configured = False
        self._awaiting_switch_start = False
        self._active_serial_port = ""
        self._run_controlled_by_host = True
        self._auto_rec_started = False
        self._preview_frame_counter = 0
        self._recorded_frame_counter = 0
        self._zero_warmup_warning_shown = False
        self._auto_stop_pending_taps: int | None = None
        self._next_tap_delay_s: float | None = None
        self._tracking_log_decimate = 1
        self._tracking_log_counter = 0
        self._low_disk_mode_active = False
        self._low_disk_dialog_shown = False
        self._disk_full_detected = False
        self._disk_calib_active = False
        self._disk_calib_recorder: video.VideoRecorder | None = None
        self._disk_calib_start_ts = 0.0
        self._disk_calib_path: Path | None = None
        self._disk_calib_counts: list[int] = []
        self._disk_calib_frames = 0
        self._disk_calib_last_results = None
        self._disk_calib_report_label: QLabel | None = None
        self._diagnostics_enabled = False
        self._diagnostics_interval_s = DIAG_SAMPLE_INTERVAL_S_DEFAULT
        self._diagnostics_timer = QTimer(self)
        self._diagnostics_timer.setInterval(int(self._diagnostics_interval_s * MS_PER_SEC))
        self._diagnostics_timer.timeout.connect(self._sample_diagnostics)
        self._diag_f = None
        self._diag_w = None
        self._diag_prev_ts: float | None = None
        self._diag_prev_io = None
        self._diag_process = psutil.Process() if psutil is not None else None
        self._diag_preview_frames = 0
        self._diag_cv_frames = 0
        self._diag_prev_preview_frames = 0
        self._diag_prev_cv_frames = 0
        self._diag_prev_rec_frames = 0
        self._diag_prev_drop_frames = 0
        self._auto_stop_timer = QTimer(self)
        self._auto_stop_timer.setSingleShot(True)
        self._auto_stop_timer.timeout.connect(self._on_auto_stop_due)
        # Dense status line updater
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._refresh_statusline)
        self.status_timer.start(STATUS_TIMER_INTERVAL_MS)
        self.serial_timer = QTimer(self)
        self.serial_timer.setInterval(SERIAL_TIMER_INTERVAL_MS)
        self.serial_timer.timeout.connect(self._drain_serial_queue)
        
        # Staged Start logic
        self._acclimation_timer = QTimer(self)
        self._acclimation_timer.setSingleShot(True)
        self._acclimation_timer.timeout.connect(self._on_acclimation_finished)
        self._acclimation_end_time: float | None = None

        # Signals
        self.cam_btn.clicked.connect(self._open_camera)
        self.serial_btn.clicked.connect(self._toggle_serial)
        self.enable_btn.clicked.connect(lambda: self._send_serial_char('e', "Enable motor"))
        self.disable_btn.clicked.connect(lambda: self._send_serial_char('d', "Disable motor"))
        self.tap_btn.clicked.connect(self._manual_tap)
        self.jog_up_btn.clicked.connect(lambda: self._send_serial_char('r', "Raise arm"))
        self.jog_down_btn.clicked.connect(lambda: self._send_serial_char('l', "Lower arm"))
        self.rec_start_btn.clicked.connect(self._start_recording)
        self.rec_stop_btn.clicked.connect(self._stop_recording)
        self.run_start_btn.clicked.connect(self._start_run)
        self.run_stop_btn.clicked.connect(self._stop_run)
        self.clear_data_btn.clicked.connect(self._clear_run_data)
        self.outdir_btn.clicked.connect(self._choose_outdir)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.save_cfg_btn.clicked.connect(self._save_config_clicked)
        self.load_cfg_btn.clicked.connect(self._load_config_clicked)
        self.pro_btn.clicked.connect(self._toggle_pro_mode)
        self.period_sec.editingFinished.connect(lambda: self._update_status("Period updated."))
        self.lambda_rpm.editingFinished.connect(lambda: self._update_status("Lambda updated."))
        self.warmup_sec.editingFinished.connect(self._on_warmup_changed)
        self.stepsize.currentTextChanged.connect(self._on_stepsize_changed)
        self.port_edit.editTextChanged.connect(self._on_port_text_changed)

        self._mode_changed()
        self._update_status("Ready.")
        self._reset_serial_indicator()
        self.preview_fps = PREVIEW_FPS_DEFAULT
        self.current_stepsize = DEFAULT_STEPSIZE
        self._pip_window: PinnedPreviewWindow | None = None
        self._motor_enabled = False
        self._calibration_paths: tuple[Path, ...] = (
            Path.home() / ".nemesis" / "calibration.json",
            RUNS_DIR / "calibration.json",
        )
        self._active_calibration_path: Path | None = None
        self._period_calibration: dict[str, float] = self._load_calibration()
        if self._active_calibration_path is None:
            self._active_calibration_path = self._calibration_paths[0]
        self._awaiting_replicant_timer = False
        self._sleep_inhibitor: subprocess.Popen | None = None
        
        # Camera Heartbeat Watchdog
        self._last_frame_ts: float | None = None
        self._watchdog_timer = QTimer(self)
        self._watchdog_timer.setInterval(2000) # Check every 2 seconds
        self._watchdog_timer.timeout.connect(self._check_camera_heartbeat)
        self._camera_dead = False

    def _set_sleep_inhibition(self, active: bool):
        if sys.platform != "darwin":
            return
        if active:
            if self._sleep_inhibitor is None:
                try:
                    # 'caffeinate -i' prevents system idle sleep
                    # -w <pid> ensures it dies if this process crashes
                    self._sleep_inhibitor = subprocess.Popen(
                        ["caffeinate", "-i", "-w", str(sys.getpid())],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    APP_LOGGER.info("Sleep inhibition (caffeinate) activated.")
                except Exception as e:
                    APP_LOGGER.error(f"Failed to start caffeinate: {e}")
        else:
            if self._sleep_inhibitor is not None:
                try:
                    self._sleep_inhibitor.terminate()
                    self._sleep_inhibitor.wait(timeout=1.0)
                except Exception:
                    pass
                self._sleep_inhibitor = None
                APP_LOGGER.info("Sleep inhibition deactivated.")

    def show_starter_guide(self, *, force: bool = False):
        if not force and not self._should_show_starter_guide():
            return
        dlg = StarterGuideDialog(self)
        dlg.exec()

    def _should_show_starter_guide(self) -> bool:
        cfg = configio.load_config() or {}
        guide = cfg.get("starter_guide", {})
        if guide.get("completed") and guide.get("version") == STARTER_GUIDE_VERSION:
            return False
        return True

    def _mark_starter_guide_complete(self):
        cfg = configio.load_config() or {}
        cfg["starter_guide"] = {
            "completed": True,
            "version": STARTER_GUIDE_VERSION,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        configio.save_config(cfg)

    def _set_low_disk_mode(self, active: bool, *, reason: str = ""):
        if active:
            if self._low_disk_mode_active:
                return
            self._low_disk_mode_active = True
            self._tracking_log_decimate = LOW_DISK_TRACKING_DECIMATE
            self._tracking_log_counter = 0
            self._update_status("Low-disk mode enabled: tracking logs every other frame (~15 FPS at 30 FPS input).")
        else:
            if not self._low_disk_mode_active:
                return
            self._low_disk_mode_active = False
            self._tracking_log_decimate = 1
            self._tracking_log_counter = 0
            self._update_status("Low-disk mode disabled.")
        if self.session.run_dir:
            try:
                self._update_run_metadata(
                    Path(self.session.run_dir),
                    {
                        "low_disk_mode": bool(self._low_disk_mode_active),
                        "tracking_log_decimate": int(self._tracking_log_decimate),
                        "low_disk_reason": reason or "",
                    },
                )
            except Exception:
                pass

    def _build_logo_menu(self) -> QMenu:
        menu = QMenu(self)
        theme_group = QActionGroup(menu)
        theme_group.setExclusive(True)

        self._action_light_mode = QAction("Light Mode", menu)
        self._action_light_mode.setCheckable(True)
        self._action_light_mode.triggered.connect(lambda: self._apply_theme("light"))
        menu.addAction(self._action_light_mode)
        theme_group.addAction(self._action_light_mode)

        action_dark = QAction("Dark Mode", menu)
        action_dark.setCheckable(True)
        action_dark.triggered.connect(lambda: self._apply_theme("dark"))
        menu.addAction(action_dark)
        theme_group.addAction(action_dark)
        self._action_dark_mode = action_dark

        menu.addSeparator()

        self._action_mirror_mode = QAction("Mirror Layout", menu)
        self._action_mirror_mode.setCheckable(True)
        self._action_mirror_mode.toggled.connect(self._set_mirror_mode)
        menu.addAction(self._action_mirror_mode)

        self._action_wide_mode = QAction("Wide Layout (Top/Bottom)", menu)
        self._action_wide_mode.setCheckable(True)
        self._action_wide_mode.toggled.connect(self._set_wide_mode)
        menu.addAction(self._action_wide_mode)

        menu.addSeparator()

        action_fw = QAction("Show Firmware Code...", menu)
        action_fw.triggered.connect(self._show_firmware_dialog)
        menu.addAction(action_fw)

        menu.addSeparator()

        action_refresh_ports = QAction("Refresh Ports", menu)
        action_refresh_ports.triggered.connect(self._refresh_serial_ports)
        menu.addAction(action_refresh_ports)

        action_open_runs = QAction("Open Runs Folder", menu)
        action_open_runs.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(RUNS_DIR.resolve())))
        )
        menu.addAction(action_open_runs)

        action_open_readme = QAction("Open README", menu)
        action_open_readme.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(GITHUB_README_URL))
        )
        menu.addAction(action_open_readme)
        action_open_cn = QAction("California Numerics", menu)
        action_open_cn.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(CALIFORNIA_NUMERICS_URL))
        )
        menu.addAction(action_open_cn)
        return menu

    def _show_firmware_dialog(self):
        fw_path = BASE_DIR / "firmware/arduino/stentor_habituator_stepper_v9/NEMESIS_Firmware.ino"
        content = ""
        try:
            with fw_path.open("r", encoding="utf-8") as fh:
                content = fh.read()
        except Exception as exc:
            content = f"// Error reading firmware file:\n// {fw_path}\n// {exc}"
            _log_gui_exception(exc, context="Load firmware file")

        dialog = ThemedDialog(self, title="Arduino Firmware Source")
        dialog.resize(700, 600)

        layout = dialog.content_layout()
        
        info = QLabel("Copy this code and flash it to your Arduino via the Arduino IDE.")
        info.setWordWrap(True)
        layout.addWidget(info)

        editor = QPlainTextEdit()
        editor.setPlainText(content)
        editor.setReadOnly(True)
        try:
            # Try to use a monospaced font
            font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
            editor.setFont(font)
        except Exception:
            pass
        layout.addWidget(editor)

        btn_row = QHBoxLayout()
        copy_btn = QPushButton("Copy All to Clipboard")

        def _copy():
            editor.selectAll()
            editor.copy()
            # Deselect to show it's done, or just give feedback
            cursor = editor.textCursor()
            cursor.clearSelection()
            editor.setTextCursor(cursor)
            self._update_status("Firmware code copied to clipboard.")
            copy_btn.setText("Copied!")
            QTimer.singleShot(2000, lambda: copy_btn.setText("Copy All to Clipboard"))

        copy_btn.clicked.connect(_copy)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)

        btn_row.addStretch(1)
        btn_row.addWidget(copy_btn)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        dialog.exec()

    def _logo_pressed(self, event):
        if self._settings_dialog is None:
            self._settings_dialog = SettingsDialog(self)
        
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    def _apply_titlebar_theme(self):
        try:
            if sys.platform == "darwin":
                set_macos_titlebar_appearance(self, QColor(self._theme.get("BG", BG)))
        except Exception:
            pass

    def _adjust_min_window_size(self):
        try:
            hint = self.minimumSizeHint()
            if hint.isValid():
                self.setMinimumSize(
                    max(self.minimumWidth(), hint.width()),
                    max(self.minimumHeight(), hint.height()),
                )
        except Exception:
            pass

    def _update_section_spacers(self):
        spacers = getattr(self, "_section_spacers", None)
        if not spacers:
            return
        gap = getattr(self, "_section_gap", SECTION_GAP_MIN)
        if self.height() < SECTION_GAP_HEIGHT_THRESHOLD:
            gap = max(SECTION_GAP_MIN, gap - SECTION_GAP_REDUCTION)
        for spacer in spacers:
            spacer.changeSize(0, gap, QSizePolicy.Minimum, QSizePolicy.Fixed)
        layout = getattr(self, "_right_layout", None)
        if layout is not None:
            layout.invalidate()

    def _refresh_serial_ports(self, initial: bool = False):
        current = ""
        try:
            current = self.port_edit.currentText().strip()
        except Exception:
            pass
        ports = [port.device for port in list_ports.comports()]
        try:
            self.port_edit.blockSignals(True)
            self.port_edit.clear()
            for port in ports:
                self.port_edit.addItem(port)
            if current and current not in ports:
                self.port_edit.addItem(current)
            if current:
                self.port_edit.setCurrentText(current)
            elif ports:
                self.port_edit.setCurrentIndex(0)
                self._active_serial_port = ports[0]
        finally:
            try:
                self.port_edit.blockSignals(False)
            except Exception:
                pass
        if initial and ports and not current:
            self._active_serial_port = ports[0]

    def _on_preview_first_frame(self):
        try:
            if self._pip_window:
                self._pip_window.reset_first_frame()
        except Exception:
            pass
        self._update_status("Camera streaming.")

    def _toggle_preview_popout(self, checked: bool):
        if checked:
            if self._pip_window is None:
                self._pip_window = PinnedPreviewWindow()
                try:
                    self._pip_window.set_theme(self._theme)
                except Exception:
                    pass
                self._pip_window.closed.connect(lambda: self.popout_btn.setChecked(False))
            try:
                w, h = self.session.preview_size
                if w and h:
                    self._pip_window.set_aspect(w, h)
            except Exception:
                pass
            self._pip_window.show()
            return
        if self._pip_window:
            try:
                self._pip_window.close()
            except Exception:
                pass
            self._pip_window = None

    def _on_live_chart_long_mode(self, active: bool):
        if not hasattr(self, "long_mode_combo"):
            return
        combo = self.long_mode_combo
        combo.blockSignals(True)
        if active:
            view = self.live_chart.long_run_view()
            idx = combo.findData(view)
            if idx < 0:
                idx = 0
            combo.setCurrentIndex(idx)
            combo.setVisible(True)
        else:
            combo.setCurrentIndex(0)
            combo.setVisible(False)
        combo.blockSignals(False)

    def _on_long_mode_view_changed(self, index: int):
        if not hasattr(self, "long_mode_combo"):
            return
        combo = self.long_mode_combo
        if not combo.isVisible():
            return
        view = combo.itemData(index)
        if not view:
            return
        self.live_chart.set_long_run_view(str(view))

    def _mode_changed(self):
        mode_text = self.mode.currentText().strip().lower()
        is_poisson = mode_text == "poisson"
        try:
            self.period_sec.setEnabled(not is_poisson)
            self.lbl_period.setEnabled(not is_poisson)
        except Exception:
            pass
        try:
            self.lambda_rpm.setEnabled(is_poisson)
            self.lbl_lambda.setEnabled(is_poisson)
        except Exception:
            pass
        label = "Poisson" if is_poisson else "Periodic"
        self._update_status(f"Mode set to {label}.")

    def _selected_stepsize(self) -> Optional[int]:
        try:
            text = self.stepsize.currentText().strip()
        except Exception:
            return None
        if not text:
            return None
        if text[0].isdigit():
            val = int(text[0])
            if STEPSIZE_MIN <= val <= STEPSIZE_MAX:
                return val
        return None

    def _parse_replicant_csv(self, path: Path) -> list[float]:
        times: list[float] = []
        try:
            with path.open("r", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                fieldnames = reader.fieldnames or []
                key = None
                units_ms = False
                for cand in ("t_host_ms", "timestamp", "time"):
                    if cand in fieldnames:
                        key = cand
                        units_ms = "ms" in cand
                        break
                if key:
                    for row in reader:
                        raw = row.get(key, "").strip()
                        if not raw:
                            continue
                        try:
                            times.append(float(raw))
                        except ValueError:
                            continue
                else:
                    fh.seek(0)
                    raw_reader = csv.reader(fh)
                    for row in raw_reader:
                        if not row:
                            continue
                        try:
                            times.append(float(row[0]))
                        except ValueError:
                            continue
                if not times:
                    return []
                max_val = max(times)
                if not units_ms and max_val > REPLICANT_MS_THRESHOLD:
                    units_ms = True
                if units_ms:
                    times = [t / MS_PER_SEC for t in times]
        except Exception:
            return []
        times.sort()
        base = times[0]
        offsets = [max(0.0, t - base) for t in times]
        return offsets

    def _load_replicant_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load replicant CSV",
            str(RUNS_DIR),
            "CSV Files (*.csv)",
        )
        if not path:
            return
        offsets = self._parse_replicant_csv(Path(path))
        if not offsets:
            QMessageBox.warning(self, "Replicant", "No valid timestamps found in CSV.")
            return
        delays = [offsets[0]] + [max(0.0, offsets[i] - offsets[i - 1]) for i in range(1, len(offsets))]
        self.session.replicant_path = path
        self.session.replicant_offsets = offsets
        self.session.replicant_delays = delays
        self.session.replicant_total = len(offsets)
        self.session.replicant_progress = 0
        self.session.replicant_ready = True
        self.session.replicant_enabled = True
        self.replicant_status.setText(f"{Path(path).name} ({len(offsets)} taps)")
        self.live_chart.set_replay_targets(offsets)
        self.live_chart.mark_replay_progress(0)
        self._update_status("Replicant script loaded.")

    def _clear_replicant_csv(self):
        self.session.replicant_enabled = False
        self.session.replicant_ready = False
        self.session.replicant_path = None
        self.session.replicant_offsets.clear()
        self.session.replicant_delays.clear()
        self.session.replicant_total = 0
        self.session.replicant_progress = 0
        self.replicant_status.setText("No script loaded")
        self.live_chart.clear_replay_targets()
        self._update_status("Replicant cleared.")

    def _send_hardware_config(self, mode_char: str, stepsize: int, value: float, awaiting_switch: bool) -> bool:
        if not self.serial or not self.serial.is_open():
            self._update_status("Serial not connected.")
            return False
        payload = f"{mode_char},{stepsize},{value}\n"
        if not self.serial.send_char("c"):
            self._update_status("Failed to send config header.")
            return False
        if not self.serial.send_text(payload):
            self._update_status("Failed to send config payload.")
            return False
        self._hardware_configured = True
        self._awaiting_switch_start = awaiting_switch
        return True

    def _flash_hardware_config(self):
        stepsize = self._selected_stepsize() or self.current_stepsize or DEFAULT_STEPSIZE
        if self.session.replicant_ready:
            mode_char = "H"
            value = float(self.session.replicant_total)
        else:
            mode_text = self.mode.currentText().strip().lower()
            if mode_text == "poisson":
                mode_char = "R"
                value = float(self.lambda_rpm.value())
            else:
                mode_char = "P"
                value = float(self.period_sec.value())
        if self._send_hardware_config(mode_char, stepsize, value, awaiting_switch=True):
            self._update_status("Hardware configured. Toggle switch to begin.")

    def _export_live_chart(self):
        default_dir = RUNS_DIR
        if self.session.run_dir:
            try:
                default_dir = Path(self.session.run_dir)
            except Exception:
                pass
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Export plot",
            str(Path(default_dir) / "live_plot.png"),
            "PNG Image (*.png);;PDF Document (*.pdf);;SVG Vector (*.svg)",
        )
        if not dest:
            return
        try:
            self.live_chart.save(dest)
        except Exception as exc:
            QMessageBox.warning(self, "Export Plot", f"Failed to export plot: {exc}")
            return
        QMessageBox.information(self, "Export Plot", f"Plot exported → {dest}")

    def _update_status(self, message: str):
        try:
            self.status.setText(message)
        except Exception:
            pass

    def _maybe_update_preview_aspect(self, w: int, h: int):
        if w <= 0 or h <= 0:
            return
        try:
            self.video_area.set_aspect(w, h)
        except Exception:
            pass
        self.session.preview_size = (w, h)
        if self._pip_window:
            try:
                self._pip_window.set_aspect(w, h)
            except Exception:
                pass

    def _reset_serial_indicator(self, state: str = "disconnected"):
        state = state.lower().strip()
        if state == "connected":
            self.serial_status.setText("Serial connected.")
            self.serial_btn.setText("Disconnect")
        elif state == "waiting":
            self.serial_status.setText("Waiting for device…")
            self.serial_btn.setText("Disconnect")
        else:
            self.serial_status.setText("Serial disconnected.")
            self.serial_btn.setText("Connect")

    def _drain_serial_queue(self):
        link = self.serial
        if link is None:
            return
        while True:
            item = link.read_line_nowait(with_timestamp=True)
            if item is None:
                break
            ts, line = item if isinstance(item, tuple) else (time.monotonic(), item)
            text = str(line).strip()
            if not text:
                continue
            self.serial_status.setText(f"Last serial: {text}")
            if text.startswith("ERROR:DISCONNECTED"):
                self._reset_serial_indicator("disconnected")
                continue
            if text.startswith("EVENT:TAP"):
                parts = text.split(",", 1)
                firmware_ms = None
                if len(parts) == 2:
                    try:
                        firmware_ms = float(parts[1])
                    except ValueError:
                        firmware_ms = None
                self._log_pending_tap(firmware_ms, host_time_s=ts)
                continue
            if text.startswith("EVENT:MODE_ACTIVATED"):
                if self._awaiting_switch_start and not self._hardware_run_active:
                    self._awaiting_switch_start = False
                    self._start_run(hardware_controlled=True)
                continue
            if text.startswith("EVENT:MODE_DEACTIVATED"):
                if self._hardware_run_active and not self._run_controlled_by_host:
                    self._stop_run(from_hardware=True)
                continue
            if text.startswith("CONFIG:STEPSIZE="):
                try:
                    step = int(text.split("=", 1)[1])
                    self.current_stepsize = step
                except Exception:
                    pass
            if text.startswith("CONFIG:OK") or text.startswith("CONFIG:DONE"):
                self._hardware_configured = True

    def _refresh_statusline(self):
        parts = []
        if self._acclimation_end_time is not None:
            remaining = max(0.0, self._acclimation_end_time - time.monotonic())
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            parts.append(f"ACCLIMATION: {mins:02d}:{secs:02d}")
        if self._low_disk_mode_active:
            parts.append(LOW_DISK_STATUS_LABEL)
        elif self._disk_full_detected:
            parts.append(DISK_FULL_STATUS_LABEL)
            
        if self.cap is not None:
            idx = self.session.camera_index if self.session.camera_index is not None else "?"
            parts.append(f"Cam {idx}")
        else:
            parts.append("Cam off")
        if self.serial and self.serial.is_open():
            port = self._active_serial_port or self.port_edit.currentText().strip()
            parts.append(f"Serial {port}")
        else:
            parts.append("Serial off")
        if self._recording_active:
            parts.append("REC")
        if self._hardware_run_active:
            parts.append("RUN")
        if self.session.replicant_ready:
            parts.append("Replicant")
        try:
            self.statusline.setText(" | ".join(parts))
        except Exception:
            pass

        self._check_disk_write_errors()

        if self.session.run_start is None:
            elapsed = self.session.last_run_elapsed
        else:
            elapsed = max(0.0, time.monotonic() - self.session.run_start)
            self.session.last_run_elapsed = elapsed
        rate10 = self.session.recent_rate_per_min()
        rate10_str = "--" if rate10 is None else f"{rate10:.1f}"
        overall = 0.0
        if elapsed > 0:
            overall = (self.session.taps / elapsed) * SECONDS_PER_MIN
        try:
            self.counters.setText(
                f"Taps: {self.session.taps} | Contractions: {self._contraction_count} | "
                f"Elapsed: {elapsed:.1f} s | "
                f"Rate10: {rate10_str} /min | Overall: {overall:.1f} /min"
            )
        except Exception:
            pass

    def _check_disk_write_errors(self):
        if not self._hardware_run_active:
            return
        for logger in (self.session.logger, self.session.tracking_logger):
            if logger is None or not hasattr(logger, "consume_flush_error"):
                continue
            err, no_space = logger.consume_flush_error()
            if err is None:
                continue
            if no_space:
                if not self._disk_full_detected:
                    self._disk_full_detected = True
                    self._update_status("Disk full: buffering CSV data in RAM.")
                if not self._low_disk_dialog_shown:
                    self._low_disk_dialog_shown = True
                    dlg = LowDiskDialog(self)
                    if dlg.exec() and dlg.enable_low_disk:
                        self._set_low_disk_mode(True, reason="disk_full")
            else:
                self._update_status(f"CSV write error: {err}")

    def _set_diagnostics_enabled(self, enabled: bool):
        self._diagnostics_enabled = bool(enabled)
        cfg = configio.load_config() or {}
        run_cfg = cfg.get("run", {})
        run_cfg["diagnostics_enabled"] = self._diagnostics_enabled
        run_cfg["diagnostics_interval_s"] = float(self._diagnostics_interval_s)
        cfg["run"] = run_cfg
        configio.save_config(cfg)
        if self._diagnostics_enabled and self._hardware_run_active:
            self._start_diagnostics_logging()
        else:
            self._stop_diagnostics_logging()
        if self._hardware_run_active and self.session.run_dir:
            try:
                self._update_run_metadata(
                    Path(self.session.run_dir),
                    {
                        "diagnostics_enabled": bool(self._diagnostics_enabled),
                        "diagnostics_interval_s": float(self._diagnostics_interval_s),
                    },
                )
            except Exception:
                pass

    def _set_diagnostics_interval(self, value: int):
        interval = max(DIAG_SAMPLE_INTERVAL_MIN_S, min(DIAG_SAMPLE_INTERVAL_MAX_S, float(value)))
        self._diagnostics_interval_s = interval
        self._diagnostics_timer.setInterval(int(self._diagnostics_interval_s * MS_PER_SEC))
        cfg = configio.load_config() or {}
        run_cfg = cfg.get("run", {})
        run_cfg["diagnostics_enabled"] = self._diagnostics_enabled
        run_cfg["diagnostics_interval_s"] = float(self._diagnostics_interval_s)
        cfg["run"] = run_cfg
        configio.save_config(cfg)
        if self._hardware_run_active and self.session.run_dir:
            try:
                self._update_run_metadata(
                    Path(self.session.run_dir),
                    {"diagnostics_interval_s": float(self._diagnostics_interval_s)},
                )
            except Exception:
                pass

    def _start_diagnostics_logging(self):
        if not self._diagnostics_enabled or not self.session.run_dir:
            return
        if self._diag_w is not None:
            return
        try:
            path = Path(self.session.run_dir) / DIAG_FILE_NAME
            self._diag_f = open(path, "a", newline="", encoding="utf-8")
            self._diag_w = csv.DictWriter(self._diag_f, fieldnames=DIAG_FIELDS)
            if self._diag_f.tell() == 0:
                self._diag_w.writeheader()
        except Exception:
            self._diag_f = None
            self._diag_w = None
            return
        self._diag_prev_ts = time.monotonic()
        self._diag_prev_preview_frames = self._diag_preview_frames
        self._diag_prev_cv_frames = self._diag_cv_frames
        if self.recorder:
            self._diag_prev_rec_frames = self.recorder.total_frames
            self._diag_prev_drop_frames = self.recorder.dropped_frames
        else:
            self._diag_prev_rec_frames = 0
            self._diag_prev_drop_frames = 0
        if psutil is not None and self._diag_process is not None:
            try:
                self._diag_process.cpu_percent(None)
                psutil.cpu_percent(None)
                self._diag_prev_io = psutil.disk_io_counters()
            except Exception:
                self._diag_prev_io = None
        self._diagnostics_timer.start()

    def _stop_diagnostics_logging(self):
        self._diagnostics_timer.stop()
        try:
            if self._diag_f:
                self._diag_f.flush()
                self._diag_f.close()
        except Exception:
            pass
        self._write_diagnostics_summary()
        self._diag_f = None
        self._diag_w = None
        self._diag_prev_ts = None
        self._diag_prev_io = None

    def _sample_diagnostics(self):
        if not self._hardware_run_active or self._diag_w is None or self._diag_f is None:
            return
        now = time.monotonic()
        prev_ts = self._diag_prev_ts or now
        dt = max(0.001, now - prev_ts)
        self._diag_prev_ts = now

        preview_delta = self._diag_preview_frames - self._diag_prev_preview_frames
        self._diag_prev_preview_frames = self._diag_preview_frames
        cv_delta = self._diag_cv_frames - self._diag_prev_cv_frames
        self._diag_prev_cv_frames = self._diag_cv_frames
        preview_fps = preview_delta / dt
        cv_fps = cv_delta / dt

        rec_fps = ""
        rec_drop_fps = ""
        rec_q = ""
        rec_qmax = ""
        if self.recorder:
            total = self.recorder.total_frames
            dropped = self.recorder.dropped_frames
            rec_fps = (total - self._diag_prev_rec_frames) / dt
            rec_drop_fps = (dropped - self._diag_prev_drop_frames) / dt
            self._diag_prev_rec_frames = total
            self._diag_prev_drop_frames = dropped
            try:
                rec_q = self.recorder.queue_size()
                rec_qmax = self.recorder.queue_max()
            except Exception:
                rec_q = ""
                rec_qmax = ""

        run_elapsed = ""
        if self.session.run_start is not None:
            run_elapsed = max(0.0, time.monotonic() - self.session.run_start)

        cpu_proc = ""
        cpu_sys = ""
        cpu_other = ""
        mem_proc = ""
        mem_sys = ""
        load_1m = ""
        threads = ""
        disk_free_gb = ""
        disk_write_mb_s = ""
        metrics_source = "basic"
        note = ""
        if psutil is not None and self._diag_process is not None:
            metrics_source = "psutil"
            try:
                cpu_proc = self._diag_process.cpu_percent(None)
                cpu_sys = psutil.cpu_percent(None)
                cpu_other = max(0.0, float(cpu_sys) - float(cpu_proc))
            except Exception:
                pass
            try:
                mem_proc = self._diag_process.memory_info().rss / 1_000_000.0
                mem_sys = psutil.virtual_memory().percent
            except Exception:
                pass
            try:
                threads = self._diag_process.num_threads()
            except Exception:
                pass
            try:
                usage = psutil.disk_usage(str(Path(self.session.run_dir)))
                disk_free_gb = usage.free / DISK_ESTIMATE_GB_DIVISOR
            except Exception:
                pass
            try:
                if self._diag_prev_io is not None:
                    io_now = psutil.disk_io_counters()
                    if io_now:
                        delta = io_now.write_bytes - self._diag_prev_io.write_bytes
                        disk_write_mb_s = (delta / dt) / 1_000_000.0
                        self._diag_prev_io = io_now
            except Exception:
                pass
        try:
            load_1m = os.getloadavg()[0]
        except Exception:
            pass

        row = {
            "timestamp_iso": datetime.now(timezone.utc).isoformat(),
            "t_host_s": f"{now:.3f}",
            "arm_name": self.arm_name_edit.text().strip(),
            "run_id": Path(self.session.run_dir).name if self.session.run_dir else "",
            "run_elapsed_s": run_elapsed,
            "camera_open": bool(self.cap is not None),
            "camera_fps_est": f"{preview_fps:.2f}",
            "cv_fps_est": f"{cv_fps:.2f}",
            "rec_fps_est": f"{rec_fps:.2f}" if rec_fps != "" else "",
            "rec_drop_fps": f"{rec_drop_fps:.2f}" if rec_drop_fps != "" else "",
            "rec_queue_depth": rec_q,
            "rec_queue_max": rec_qmax,
            "serial_connected": bool(self.serial and self.serial.is_open()),
            "camera_dead": bool(self._camera_dead),
            "low_disk_mode": bool(self._low_disk_mode_active),
            "tracking_decimate": int(self._tracking_log_decimate),
            "cpu_process_pct": cpu_proc,
            "cpu_system_pct": cpu_sys,
            "cpu_other_pct": cpu_other,
            "mem_process_mb": mem_proc,
            "mem_system_pct": mem_sys,
            "load_1m": load_1m,
            "threads": threads,
            "disk_free_gb": disk_free_gb,
            "disk_write_mb_s": disk_write_mb_s,
            "metrics_source": metrics_source,
            "note": note,
        }
        try:
            self._diag_w.writerow(row)
            self._diag_f.flush()
        except Exception:
            pass

    def _write_diagnostics_summary(self):
        if not self.session.run_dir:
            return
        diag_path = Path(self.session.run_dir) / DIAG_FILE_NAME
        if not diag_path.exists():
            return
        try:
            rows = []
            with diag_path.open("r", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    rows.append(row)
        except Exception:
            return
        if not rows:
            return

        def _to_float(val):
            try:
                return float(val)
            except Exception:
                return None

        def _percentile(values, pct):
            if not values:
                return None
            values = sorted(values)
            if len(values) == 1:
                return values[0]
            k = (len(values) - 1) * (pct / 100.0)
            f = int(k)
            c = min(f + 1, len(values) - 1)
            if f == c:
                return values[f]
            return values[f] + (values[c] - values[f]) * (k - f)

        cpu_proc = [v for v in (_to_float(r.get("cpu_process_pct", "")) for r in rows) if v is not None]
        cpu_sys = [v for v in (_to_float(r.get("cpu_system_pct", "")) for r in rows) if v is not None]
        mem_proc = [v for v in (_to_float(r.get("mem_process_mb", "")) for r in rows) if v is not None]
        mem_sys = [v for v in (_to_float(r.get("mem_system_pct", "")) for r in rows) if v is not None]
        disk_free = [v for v in (_to_float(r.get("disk_free_gb", "")) for r in rows) if v is not None]
        cam_fps = [v for v in (_to_float(r.get("camera_fps_est", "")) for r in rows) if v is not None]
        cv_fps = [v for v in (_to_float(r.get("cv_fps_est", "")) for r in rows) if v is not None]
        rec_fps = [v for v in (_to_float(r.get("rec_fps_est", "")) for r in rows) if v is not None]
        rec_drop = [v for v in (_to_float(r.get("rec_drop_fps", "")) for r in rows) if v is not None]
        disk_write = [v for v in (_to_float(r.get("disk_write_mb_s", "")) for r in rows) if v is not None]

        summary = {
            "arm_name": rows[-1].get("arm_name", ""),
            "run_id": rows[-1].get("run_id", ""),
            "samples": len(rows),
            "interval_s": self._diagnostics_interval_s,
            "cpu_process_pct_avg": (sum(cpu_proc) / len(cpu_proc)) if cpu_proc else None,
            "cpu_process_pct_p95": _percentile(cpu_proc, 95),
            "cpu_system_pct_avg": (sum(cpu_sys) / len(cpu_sys)) if cpu_sys else None,
            "cpu_system_pct_p95": _percentile(cpu_sys, 95),
            "mem_process_mb_avg": (sum(mem_proc) / len(mem_proc)) if mem_proc else None,
            "mem_process_mb_max": max(mem_proc) if mem_proc else None,
            "mem_system_pct_avg": (sum(mem_sys) / len(mem_sys)) if mem_sys else None,
            "mem_system_pct_p95": _percentile(mem_sys, 95),
            "disk_free_gb_min": min(disk_free) if disk_free else None,
            "disk_write_mb_s_avg": (sum(disk_write) / len(disk_write)) if disk_write else None,
            "camera_fps_avg": (sum(cam_fps) / len(cam_fps)) if cam_fps else None,
            "camera_fps_p05": _percentile(cam_fps, 5),
            "cv_fps_avg": (sum(cv_fps) / len(cv_fps)) if cv_fps else None,
            "cv_fps_p05": _percentile(cv_fps, 5),
            "rec_fps_avg": (sum(rec_fps) / len(rec_fps)) if rec_fps else None,
            "rec_drop_fps_avg": (sum(rec_drop) / len(rec_drop)) if rec_drop else None,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            out_path = Path(self.session.run_dir) / "diagnostics_summary.json"
            with out_path.open("w", encoding="utf-8") as fh:
                json.dump(summary, fh, indent=2)
        except Exception:
            pass

    def _csv_row_bytes(self, fieldnames: list[str], row: dict) -> int:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writerow(row)
        return len(buf.getvalue().encode("utf-8"))

    def _estimate_tracking_row_bytes(self, results) -> int:
        if results:
            s = results[0]
            row = {
                "frame_idx": 0,
                "timestamp": f"{0.0:.{TRACKING_TS_PRECISION}f}",
                "stentor_id": s.id,
                "state": s.state,
                "circularity": f"{s.circularity:.{CIRCULARITY_PRECISION}f}",
                "x": f"{s.centroid[0]:.{CENTROID_PRECISION}f}",
                "y": f"{s.centroid[1]:.{CENTROID_PRECISION}f}",
                "area": int(s.area),
                "edge_reflection": "1" if getattr(s, "edge_reflection", False) else "0",
            }
        else:
            row = {
                "frame_idx": 0,
                "timestamp": f"{0.0:.{TRACKING_TS_PRECISION}f}",
                "stentor_id": "",
                "state": "NONE",
                "circularity": "",
                "x": "",
                "y": "",
                "area": "",
                "edge_reflection": "0",
            }
        return self._csv_row_bytes(TRACKING_FIELDS, row)

    def _estimate_frame_row_bytes(self) -> int:
        row = {
            "frame_idx": 0,
            "timestamp": f"{0.0:.{FRAME_TS_PRECISION}f}",
        }
        return self._csv_row_bytes(FRAME_FIELDS, row)

    def _estimate_tap_row_bytes(self) -> int:
        row = {
            "run_id": "run_YYYYMMDD_HHMMSS",
            "tap_id": 1,
            "tap_uuid": "00000000000000000000000000000000",
            "t_host_ms": 0,
            "t_host_iso": "",
            "t_fw_ms": "",
            "mode": "Periodic",
            "stepsize": 4,
            "mark": "scheduled",
            "notes": "",
            "frame_preview_idx": 0,
            "frame_recorded_idx": 0,
            "recording_path": "",
        }
        return self._csv_row_bytes(CSV_FIELDS, row)

    def _estimate_disk_usage(self, duration_min: float) -> tuple[float, float, str, str]:
        if duration_min <= 0:
            return 0.0, 0.0, "Manual", ""
        duration_s = duration_min * SECONDS_PER_MIN
        cfg = configio.load_config() or {}
        calib = cfg.get("disk_calibration") or {}

        if calib.get("video_bytes_per_sec"):
            bytes_per_sec = float(calib["video_bytes_per_sec"])
            src = "Calibrated"
            note = calib.get("note", "")
            if self.cap:
                try:
                    w, h = self.cap.get_size()
                    cw, ch = calib.get("frame_size", [w, h])
                    if cw and ch and w and h:
                        bytes_per_sec *= (w * h) / float(cw * ch)
                except Exception:
                    pass
            fps_est = float(calib.get("fps_est") or (self.cap.get_fps() if self.cap else self.preview_fps) or self.preview_fps)
            avg_rows_per_frame = float(calib.get("avg_rows_per_frame") or 1.0)
            tracking_row_bytes = float(calib.get("tracking_row_bytes") or 0.0)
            frame_row_bytes = float(calib.get("frame_row_bytes") or 0.0)
            tap_row_bytes = float(calib.get("tap_row_bytes") or 0.0)
            video_bytes = bytes_per_sec * duration_s
            tracking_bytes = fps_est * avg_rows_per_frame * tracking_row_bytes * duration_s
            frame_bytes = fps_est * frame_row_bytes * duration_s
            tap_rate = 0.0
            mode_label = self.mode.currentText().strip()
            if mode_label.lower() == "periodic":
                period = max(0.001, float(self.period_sec.value()))
                tap_rate = 1.0 / period
            elif mode_label.lower() == "poisson":
                tap_rate = float(self.lambda_rpm.value()) / 60.0
            taps_bytes = tap_rate * tap_row_bytes * duration_s
            total_bytes = video_bytes + tracking_bytes + frame_bytes + taps_bytes
            low_gb = total_bytes / DISK_ESTIMATE_GB_DIVISOR
            high_gb = low_gb * DISK_ESTIMATE_MARGIN
            return low_gb, high_gb, src, note

        # Fallback heuristic
        est_gb = (duration_min / 60.0) * 1.5
        if self.cap:
            w, h = self.cap.get_size()
            if w > 0 and h > 0:
                est_gb *= (w * h) / (1280 * 720)
        est_gb *= 1.2
        return est_gb, est_gb * DISK_ESTIMATE_MARGIN, "Heuristic", ""

    def _start_disk_calibration(self, *, report_to: QLabel | None = None):
        if self._disk_calib_active:
            return
        if self._hardware_run_active or self._acclimation_end_time is not None:
            self._update_status("Stop the run before disk calibration.")
            return
        if self.cap is None:
            QMessageBox.warning(self, "Disk Calibration", "Open the camera first.")
            return
        if self._frame_worker is None:
            QMessageBox.warning(self, "Disk Calibration", "Start the camera preview first.")
            return

        base_dir = RUNS_DIR / "_calibration"
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        fname = f"disk_calib_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
        path = base_dir / fname
        fps = self.cap.get_fps() or self.preview_fps
        size = self.cap.get_size()
        try:
            recorder = video.VideoRecorder(str(path), fps=fps, frame_size=size)
        except Exception as exc:
            QMessageBox.warning(self, "Disk Calibration", f"Failed to start recorder: {exc}")
            return
        if not recorder.is_open():
            QMessageBox.warning(self, "Disk Calibration", "Failed to start recorder.")
            return

        self._disk_calib_active = True
        self._disk_calib_recorder = recorder
        self._disk_calib_start_ts = time.monotonic()
        self._disk_calib_path = path
        self._disk_calib_counts = []
        self._disk_calib_frames = 0
        self._disk_calib_last_results = None
        self._disk_calib_report_label = report_to
        self._update_status(f"Disk calibration recording ({DISK_CALIBRATION_DURATION_S:.0f}s)...")
        if report_to is not None:
            report_to.setText("Calibration running...")

    def _finish_disk_calibration(self):
        if not self._disk_calib_active:
            return
        self._disk_calib_active = False
        recorder = self._disk_calib_recorder
        path = self._disk_calib_path
        start_ts = self._disk_calib_start_ts
        report_to = self._disk_calib_report_label
        self._disk_calib_recorder = None
        self._disk_calib_path = None
        self._disk_calib_report_label = None

        try:
            if recorder:
                recorder.close()
        except Exception:
            pass

        elapsed = max(0.1, time.monotonic() - start_ts)
        if not path or not path.exists():
            self._update_status("Disk calibration failed.")
            return
        try:
            size_bytes = path.stat().st_size
        except Exception:
            size_bytes = 0

        fps_est = self._disk_calib_frames / elapsed if elapsed > 0 else 0.0
        if fps_est <= 0:
            fps_est = self.cap.get_fps() or self.preview_fps
        avg_rows_per_frame = 1.0
        if self._disk_calib_counts:
            avg_rows_per_frame = sum(self._disk_calib_counts) / float(len(self._disk_calib_counts))
            avg_rows_per_frame = max(1.0, avg_rows_per_frame)

        tracking_row_bytes = self._estimate_tracking_row_bytes(self._disk_calib_last_results)
        frame_row_bytes = self._estimate_frame_row_bytes()
        tap_row_bytes = self._estimate_tap_row_bytes()
        video_bps = size_bytes / elapsed if elapsed > 0 else 0.0
        if video_bps <= 0.0:
            self._update_status("Disk calibration failed: sample size 0.")
            return

        cfg = configio.load_config() or {}
        cfg["disk_calibration"] = {
            "video_bytes_per_sec": video_bps,
            "fps_est": fps_est,
            "frame_size": list(self.cap.get_size() if self.cap else (0, 0)),
            "avg_rows_per_frame": avg_rows_per_frame,
            "tracking_row_bytes": tracking_row_bytes,
            "frame_row_bytes": frame_row_bytes,
            "tap_row_bytes": tap_row_bytes,
            "sample_sec": elapsed,
            "sample_bytes": size_bytes,
            "measured_at": datetime.now(timezone.utc).isoformat(),
            "note": "Calibrated from a short recording sample.",
        }
        configio.save_config(cfg)

        try:
            path.unlink()
        except Exception:
            pass

        gb_per_hr = (video_bps * 3600.0) / DISK_ESTIMATE_GB_DIVISOR
        msg = f"Calibration complete. Video rate ~{gb_per_hr:.2f} GB/hr."
        self._update_status(msg)
        if report_to is not None:
            report_to.setText(msg)
        else:
            QMessageBox.information(self, "Disk Calibration", msg)

    def _cancel_disk_calibration(self):
        if not self._disk_calib_active:
            return
        self._disk_calib_active = False
        try:
            if self._disk_calib_recorder:
                self._disk_calib_recorder.close()
        except Exception:
            pass
        self._disk_calib_recorder = None
        self._disk_calib_path = None
        if self._disk_calib_report_label is not None:
            self._disk_calib_report_label.setText("Calibration cancelled.")
        self._disk_calib_report_label = None
        self._update_status("Disk calibration cancelled.")

    def _init_run_lock_controls(self):
        self._run_lock_controls = [
            self.arm_name_edit,
            self.port_edit,
            self.serial_btn,
            self.enable_btn,
            self.disable_btn,
            self.tap_btn,
            self.jog_up_btn,
            self.jog_down_btn,
            self.cam_index,
            self.cam_btn,
            self.popout_btn,
            self.show_cv_check,
            self.rec_start_btn,
            self.rec_stop_btn,
            self.auto_rec_check,
            self.mode,
            self.period_sec,
            self.lambda_rpm,
            self.stepsize,
            self.warmup_sec,
            self.acclimation_min,
            self.auto_stop_min,
            self.replicant_load_btn,
            self.replicant_clear_btn,
            self.save_cfg_btn,
            self.load_cfg_btn,
            self.outdir_edit,
            self.outdir_btn,
            self.flash_config_btn,
            self.pro_btn,
            self.clear_data_btn,
            self.run_start_btn,
        ]
        self._run_lock_tooltips = {}
        for widget in self._run_lock_controls:
            if widget is None:
                continue
            try:
                widget.setAttribute(Qt.WA_AlwaysShowToolTips, True)
            except Exception:
                pass
            try:
                self._run_lock_tooltips[widget] = widget.toolTip()
            except Exception:
                self._run_lock_tooltips[widget] = ""

    def _set_run_controls_locked(self, locked: bool):
        if not hasattr(self, "_run_lock_controls"):
            return
        if locked:
            self._run_lock_prev_enabled = {}
            for widget in self._run_lock_controls:
                if widget is None:
                    continue
                try:
                    self._run_lock_prev_enabled[widget] = widget.isEnabled()
                except Exception:
                    self._run_lock_prev_enabled[widget] = True
                try:
                    widget.setEnabled(False)
                except Exception:
                    pass
                try:
                    widget.setToolTip(RUN_LOCK_TOOLTIP)
                except Exception:
                    pass
        else:
            prev = getattr(self, "_run_lock_prev_enabled", {})
            for widget in self._run_lock_controls:
                if widget is None:
                    continue
                if widget in prev:
                    try:
                        widget.setEnabled(prev[widget])
                    except Exception:
                        pass
                else:
                    try:
                        widget.setEnabled(True)
                    except Exception:
                        pass
                try:
                    widget.setToolTip(self._run_lock_tooltips.get(widget, ""))
                except Exception:
                    pass
            self._run_lock_prev_enabled = {}

    def _on_stepsize_changed(self, text: str):
        step = self._selected_stepsize()
        if step is None:
            return
        self.current_stepsize = step
        if self.serial and self.serial.is_open():
            self._send_serial_char(str(step), f"Stepsize {step}")

    def _on_warmup_changed(self, value: float | None = None):
        if value is None:
            value = self.warmup_sec.value()
        warmup = max(0.0, float(value))
        if warmup <= 0.0:
            if not self._zero_warmup_warning_shown:
                self._show_native_alert(
                    "Warmup disabled",
                    "Warmup is set to 0. Recording starts immediately and the first tap fires right away,\n"
                    "so you may miss the opening frames of the first tap (often the most important).",
                )
                self._zero_warmup_warning_shown = True
            self._update_status("Warmup disabled.")
        else:
            self._zero_warmup_warning_shown = False
            self._update_status(f"Warmup set to {warmup:.1f} s.")

    def _save_config_clicked(self):
        cfg = configio.load_config() or {}
        run_cfg = cfg.get("run", {})
        run_cfg.update(
            {
                "mode": self.mode.currentText(),
                "period_sec": float(self.period_sec.value()),
                "lambda_rpm": float(self.lambda_rpm.value()),
                "stepsize": self._selected_stepsize(),
                "warmup_sec": float(self.warmup_sec.value()),
                "acclimation_min": float(self.acclimation_min.value()),
                "arm_name": self.arm_name_edit.text().strip(),
                "diagnostics_enabled": bool(self._diagnostics_enabled),
                "diagnostics_interval_s": float(self._diagnostics_interval_s),
                "output_dir": self.outdir_edit.text().strip(),
                "camera_index": int(self.cam_index.value()),
                "serial_port": self.port_edit.currentText().strip(),
                "auto_rec": bool(self.auto_rec_check.isChecked()),
                "show_cv": bool(self.show_cv_check.isChecked()),
                "mirror_mode": bool(self._mirror_mode),
                "theme": self._theme_name,
            }
        )
        cfg["run"] = run_cfg
        configio.save_config(cfg)
        self._update_status("Config saved.")

    def _load_config_clicked(self):
        cfg = configio.load_config()
        if not cfg or "run" not in cfg:
            self._update_status("No saved config found.")
            return
        run_cfg = cfg.get("run", {})
        if "mode" in run_cfg:
            idx = self.mode.findText(run_cfg["mode"])
            if idx >= 0:
                self.mode.setCurrentIndex(idx)
        if "period_sec" in run_cfg:
            self.period_sec.setValue(float(run_cfg["period_sec"]))
        if "lambda_rpm" in run_cfg:
            self.lambda_rpm.setValue(float(run_cfg["lambda_rpm"]))
        if "stepsize" in run_cfg and run_cfg["stepsize"]:
            step = int(run_cfg["stepsize"])
            for i in range(self.stepsize.count()):
                if self.stepsize.itemText(i).strip().startswith(str(step)):
                    self.stepsize.setCurrentIndex(i)
                    break
        if "warmup_sec" in run_cfg:
            try:
                self.warmup_sec.blockSignals(True)
                self.warmup_sec.setValue(float(run_cfg["warmup_sec"]))
            finally:
                self.warmup_sec.blockSignals(False)
        if "acclimation_min" in run_cfg:
            try:
                self.acclimation_min.blockSignals(True)
                self.acclimation_min.setValue(float(run_cfg["acclimation_min"]))
            finally:
                self.acclimation_min.blockSignals(False)
        if "output_dir" in run_cfg and run_cfg["output_dir"]:
            self.outdir_edit.setText(run_cfg["output_dir"])
        if "camera_index" in run_cfg:
            self.cam_index.setValue(int(run_cfg["camera_index"]))
        if "serial_port" in run_cfg and run_cfg["serial_port"]:
            self.port_edit.setCurrentText(run_cfg["serial_port"])
            self._active_serial_port = run_cfg["serial_port"]
        if "arm_name" in run_cfg:
            self.arm_name_edit.setText(str(run_cfg["arm_name"]))
        elif "rig_name" in run_cfg:
            self.arm_name_edit.setText(str(run_cfg["rig_name"]))
        if "diagnostics_interval_s" in run_cfg:
            try:
                self._set_diagnostics_interval(float(run_cfg["diagnostics_interval_s"]))
            except Exception:
                pass
        if "diagnostics_enabled" in run_cfg:
            try:
                self._set_diagnostics_enabled(bool(run_cfg["diagnostics_enabled"]))
            except Exception:
                pass
        if "auto_rec" in run_cfg:
            self.auto_rec_check.setChecked(bool(run_cfg["auto_rec"]))
        if "show_cv" in run_cfg:
            self.show_cv_check.setChecked(bool(run_cfg["show_cv"]))
        if "mirror_mode" in run_cfg:
            self._set_mirror_mode(bool(run_cfg["mirror_mode"]))
        if "theme" in run_cfg:
            try:
                self._apply_theme(run_cfg["theme"], force=True)
            except Exception:
                pass
        self._update_status("Config loaded.")

    def _show_native_alert(self, title: str, message: str, *, icon=QMessageBox.Warning) -> None:
        if sys.platform == "darwin":
            try:
                def _osa_expr(value: str) -> str:
                    lines = str(value).splitlines()
                    if not lines:
                        return "\"\""
                    escaped = []
                    for line in lines:
                        line = line.replace("\\", "\\\\").replace("\"", "\\\"")
                        escaped.append(f"\"{line}\"")
                    return " & return & ".join(escaped)

                level = " as informational"
                if icon == QMessageBox.Critical:
                    level = " as critical"
                elif icon == QMessageBox.Warning:
                    level = " as warning"
                script = (
                    f"display alert {_osa_expr(title)} "
                    f"message {_osa_expr(message)}{level}"
                )
                completed = subprocess.run(["osascript", "-e", script], check=False)
                if completed.returncode == 0:
                    return
            except Exception:
                pass
        box = QMessageBox(self)
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText(message)
        box.setStandardButtons(QMessageBox.Ok)
        box.exec()

    def _toggle_pro_mode(self, enabled: bool):
        self.pro_mode = bool(enabled)
        self.pro_btn.setText("PM: ON" if self.pro_mode else "PM: OFF")
        self._update_status("Pro mode enabled." if self.pro_mode else "Pro mode disabled.")

    def _choose_outdir(self):
        current = self.outdir_edit.text().strip() or str(RUNS_DIR)
        dest = QFileDialog.getExistingDirectory(self, "Choose output directory", current)
        if not dest:
            return
        self.outdir_edit.setText(dest)

    def _clear_run_data(self):
        self.session.taps = 0
        self.session.reset_tap_history()
        self.session.last_run_elapsed = 0.0
        self._contraction_count = 0
        self._last_cv_states.clear()
        self.live_chart.reset()
        if self.session.replicant_ready:
            self.live_chart.set_replay_targets(self.session.replicant_offsets)
        self._update_status("Counters cleared.")

    def _make_run_id(self) -> str:
        ts = time.strftime("%Y%m%d_%H%M%S")
        token = uuid.uuid4().hex[:RUN_ID_TOKEN_LEN].upper()
        return f"run_{ts}_{token}"

    def _create_run_dir(self, base_dir: Path) -> tuple[Path, str]:
        base_dir.mkdir(parents=True, exist_ok=True)
        for _ in range(RUN_DIR_CREATE_RETRIES):
            run_id = self._make_run_id()
            run_dir = base_dir / run_id
            if not run_dir.exists():
                run_dir.mkdir(parents=True, exist_ok=True)
                return run_dir, run_id
        run_id = self._make_run_id()
        run_dir = base_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir, run_id

    def _write_run_metadata(self, run_dir: Path, run_id: str, mode: str, *, hardware_controlled: bool):
        cv_cfg = {}
        try:
            cfg = configio.load_config() or {}
            cv_cfg = dict(cfg.get("cv", {}))
        except Exception:
            cv_cfg = {}
        camera_fps = None
        camera_size = None
        if self.cap is not None:
            try:
                camera_fps = self.cap.get_fps()
            except Exception:
                camera_fps = None
            try:
                camera_size = self.cap.get_size()
            except Exception:
                camera_size = None
        data = {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": run_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "run_start_host_ms": int(round(self.session.run_start * MS_PER_SEC)) if self.session.run_start else None,
            "app_version": APP_VERSION,
            "arm_name": self.arm_name_edit.text().strip(),
            "serial_port": self._active_serial_port or self.port_edit.currentText().strip(),
            "camera_index": self.session.camera_index,
            "camera_fps": camera_fps,
            "camera_frame_size": camera_size,
            "preview_fps": self.preview_fps,
            "mode": mode,
            "period_sec": float(self.period_sec.value()) if mode == "Periodic" else None,
            "lambda_rpm": float(self.lambda_rpm.value()) if mode == "Poisson" else None,
            "stepsize": self._selected_stepsize() or self.current_stepsize,
            "warmup_sec": float(self.warmup_sec.value()),
            "acclimation_min": float(self.acclimation_min.value()),
            "low_disk_mode": bool(self._low_disk_mode_active),
            "tracking_log_decimate": int(self._tracking_log_decimate),
            "low_disk_reason": "",
            "diagnostics_enabled": bool(self._diagnostics_enabled),
            "diagnostics_interval_s": float(self._diagnostics_interval_s),
            "recording_path": self.recorder.path if self.recorder else "",
            "hardware_controlled": bool(hardware_controlled),
            "cv_config": cv_cfg,
        }
        try:
            with (run_dir / "run.json").open("w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except Exception:
            pass

    def _update_run_metadata(self, run_dir: Path, updates: dict):
        meta_path = run_dir / "run.json"
        data = {}
        if meta_path.exists():
            try:
                with meta_path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception:
                data = {}
        data.update(updates)
        try:
            with meta_path.open("w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except Exception:
            pass

    def _queue_pending_tap(self, mode: str, mark: str):
        if self.session.logger is None:
            return
        self._pending_taps.append(
            {
                "host_time_s": time.monotonic(),
                "mode": mode,
                "mark": mark,
                "stepsize": self._selected_stepsize() or self.current_stepsize,
                "preview_frame_idx": getattr(self, "_preview_frame_counter", None),
                "recorded_frame_idx": getattr(self, "_recorded_frame_counter", None),
            }
        )

    def _log_pending_tap(self, firmware_ms: Optional[float], host_time_s: Optional[float] = None):
        if self.session.logger is None:
            return
        if self._pending_taps:
            entry = self._pending_taps.popleft()
        else:
            entry = {
                "host_time_s": time.monotonic(),
                "mode": "Hardware",
                "mark": "hardware",
                "stepsize": self._selected_stepsize() or self.current_stepsize,
                "preview_frame_idx": getattr(self, "_preview_frame_counter", None),
                "recorded_frame_idx": getattr(self, "_recorded_frame_counter", None),
            }
        host_time = host_time_s or entry.get("host_time_s") or time.monotonic()
        if self.session.run_start is None:
            self.session.run_start = host_time
            if self.session.run_dir:
                try:
                    self._update_run_metadata(
                        Path(self.session.run_dir),
                        {"run_start_host_ms": int(round(host_time * MS_PER_SEC))},
                    )
                except Exception:
                    pass
            if not self._auto_stop_timer.isActive():
                auto_stop_min = float(self.auto_stop_min.value())
                if auto_stop_min > 0.0:
                    self._auto_stop_timer.start(int(auto_stop_min * SECONDS_PER_MIN * MS_PER_SEC))
        try:
            self.session.logger.log_tap(
                host_time_s=host_time,
                mode=entry.get("mode", ""),
                mark=entry.get("mark", ""),
                stepsize=entry.get("stepsize"),
                firmware_ms=firmware_ms,
                preview_frame_idx=entry.get("preview_frame_idx"),
                recorded_frame_idx=entry.get("recorded_frame_idx"),
            )
        except Exception:
            pass
        self.session.taps += 1
        self.session.record_tap_interval(host_time)
        if self.session.run_start is not None:
            self.live_chart.add_tap(host_time - self.session.run_start)
        if self.session.replicant_running:
            self.session.replicant_progress = min(self.session.replicant_progress + 1, self.session.replicant_total)
            self.live_chart.mark_replay_progress(self.session.replicant_progress)
        self._update_next_tap_status()
        pending = self._auto_stop_pending_taps
        if pending is not None:
            pending -= 1
            if pending <= 0:
                self._auto_stop_pending_taps = None
                self._stop_run()
            else:
                self._auto_stop_pending_taps = pending

    def _schedule_next_tap(self, delay_s: float, *, track_next: bool = True):
        delay_ms = max(MIN_TIMER_DELAY_MS, int(delay_s * MS_PER_SEC))
        self.run_timer.start(delay_ms)
        if track_next:
            self._next_tap_delay_s = float(delay_s)

    def _on_auto_stop_due(self):
        if not self._hardware_run_active:
            return
        self._auto_stop_pending_taps = AUTO_STOP_GRACE_TAPS
        self._update_status(
            f"Auto-stop reached. Allowing {AUTO_STOP_GRACE_TAPS} more tap(s)."
        )

    def _should_schedule_next_tap(self) -> bool:
        pending = self._auto_stop_pending_taps
        if pending is None:
            return True
        return pending > 1

    def _update_next_tap_status(self):
        if not self._run_controlled_by_host or not self._hardware_run_active:
            return
        if self._next_tap_delay_s is None:
            return
        try:
            self.serial_status.setText(f"Next tap in {self._next_tap_delay_s:.1f}s")
        except Exception:
            pass

    def _relocate_active_recording(self, run_dir: Path) -> bool:
        if not self.recorder:
            return True
        try:
            current_path = Path(self.recorder.path)
        except Exception:
            return False
        if not current_path.exists():
            return True
        try:
            if current_path.parent.resolve() == run_dir.resolve():
                return True
        except Exception:
            if current_path.parent == run_dir:
                return True
        target_path = run_dir / current_path.name
        if target_path.exists():
            return True
        if not self.recorder.relocate(str(target_path)):
            return False
        return True

    def _start_run(self, *, hardware_controlled: bool = False):
        if self._hardware_run_active or self._acclimation_end_time is not None:
            return
        self._tracking_log_decimate = 1
        self._tracking_log_counter = 0
        self._low_disk_mode_active = False
        self._low_disk_dialog_shown = False
        self._disk_full_detected = False
        self._diag_preview_frames = 0
        self._diag_cv_frames = 0
        self._diag_prev_preview_frames = 0
        self._diag_prev_cv_frames = 0
        self._diag_prev_rec_frames = 0
        self._diag_prev_drop_frames = 0
            
        # 1. Gather Data for Summary
        acclimation_min = float(self.acclimation_min.value())
        warmup_sec = float(self.warmup_sec.value())
        duration_min = float(self.auto_stop_min.value())
        
        mode_text = self.mode.currentText()
        if self.session.replicant_ready:
            mode_text = "Replicant"
            
        est_low_gb, est_high_gb, est_source, est_note = self._estimate_disk_usage(duration_min)

        if not hardware_controlled:
            cam_ok = self.cap is not None
            serial_ok = bool(self.serial and self.serial.is_open())
            serial_label = self._active_serial_port or self.port_edit.currentText().strip()
            if not serial_ok:
                serial_label = serial_label or "Not Connected"
            summary_data = {
                "arm_name": self.arm_name_edit.text().strip(),
                "cam_index": self.cam_index.value(),
                "cam_res": f"{self.cap.get_size()[0]}x{self.cap.get_size()[1]}" if self.cap else "Closed",
                "camera_ok": cam_ok,
                "serial_ok": serial_ok,
                "serial_port": serial_label,
                "mode": mode_text,
                "stepsize": self.stepsize.currentText(),
                "acclimation_min": acclimation_min,
                "warmup_sec": warmup_sec,
                "duration_min": duration_min,
                "est_gb_low": est_low_gb,
                "est_gb_high": est_high_gb,
                "est_source": est_source,
                "est_note": est_note,
            }
            dlg = RunSummaryDialog(self, summary_data)
            if not dlg.exec():
                return

        if not hardware_controlled and acclimation_min > 0:
            acclimation_s = acclimation_min * SECONDS_PER_MIN
            self._acclimation_end_time = time.monotonic() + acclimation_s
            self._acclimation_timer.start(int(acclimation_s * MS_PER_SEC))
            self._set_run_controls_locked(True)
            self._set_sleep_inhibition(True)
            self._update_status(f"Acclimation started. Run will begin in {acclimation_min:.1f} minutes.")
            return

        self._really_start_run(hardware_controlled=hardware_controlled)

    def _on_acclimation_finished(self):
        self._acclimation_end_time = None
        self._really_start_run(hardware_controlled=False)

    def _really_start_run(self, *, hardware_controlled: bool = False):
        base_dir = Path(self.outdir_edit.text().strip() or str(RUNS_DIR))
        run_dir, run_id = self._create_run_dir(base_dir)
        self.session.run_dir = str(run_dir)
        self.session.run_start = None
        self.session.taps = 0
        self.session.last_run_elapsed = 0.0
        self.session.reset_tap_history()
        self._preview_frame_counter = 0
        self._recorded_frame_counter = 0
        self._pending_taps.clear()
        self._run_controlled_by_host = not hardware_controlled
        self._contraction_count = 0
        self._auto_stop_pending_taps = None
        self._next_tap_delay_s = None
        self._next_host_target_time = None
        self.live_chart.reset()
        current_results = getattr(self.session, "cv_results", None) or []
        self._last_cv_states = {result.id: result.state for result in current_results}
        relocated_ok = self._relocate_active_recording(run_dir)
        first_delay_s: float | None = None
        warmup_s = max(0.0, float(self.warmup_sec.value()))

        mode_label = "Periodic"
        if self.session.replicant_ready:
            mode_label = "Replicant"
        else:
            mode_text = self.mode.currentText().strip()
            mode_label = mode_text or "Periodic"

        if not hardware_controlled:
            if self.session.replicant_ready:
                self.session.replicant_running = True
                self.session.replicant_index = 0
                self.session.replicant_progress = 0
                self.session.replicant_total = len(self.session.replicant_delays)
                stepsize = self._selected_stepsize() or self.current_stepsize or DEFAULT_STEPSIZE
                self._send_hardware_config("H", stepsize, float(self.session.replicant_total), awaiting_switch=False)
            else:
                if mode_label.lower() == "poisson":
                    self.session.scheduler.configure_poisson(float(self.lambda_rpm.value()))
                else:
                    self.session.scheduler.configure_periodic(float(self.period_sec.value()))
                stepsize = self._selected_stepsize() or self.current_stepsize or DEFAULT_STEPSIZE
                if mode_label.lower() == "poisson":
                    self._send_hardware_config("R", stepsize, float(self.lambda_rpm.value()), awaiting_switch=False)
                else:
                    self._send_hardware_config("P", stepsize, float(self.period_sec.value()), awaiting_switch=False)
        else:
            self.session.replicant_running = False
            self.session.replicant_index = 0
            self.session.replicant_progress = 0

        self.session.logger = RunLogger(run_dir=run_dir, run_id=run_id)
        self.session.tracking_logger = TrackingLogger(run_dir=run_dir)
        self.session.frame_logger = FrameLogger(run_dir=run_dir)
        try:
            configure_file_logging(run_dir / "app.log")
        except Exception:
            pass

        if self.session.replicant_ready:
            replay_targets = self.session.replicant_offsets
            self.live_chart.set_replay_targets(replay_targets)
            self.live_chart.mark_replay_progress(0)
        else:
            self.live_chart.clear_replay_targets()

        if self.auto_rec_check.isChecked() and not self.recorder:
            self._auto_rec_started = True
            self._start_recording()
            if not self.recorder:
                self._auto_rec_started = False
        if self.recorder and self.session.logger:
            try:
                self.session.logger.set_recording_path(self.recorder.path)
            except Exception:
                pass

        self._write_run_metadata(run_dir, run_id, mode_label, hardware_controlled=hardware_controlled)
        self._hardware_run_active = True
        self.session.hardware_run_active = True
        self._set_run_controls_locked(True)
        self._set_sleep_inhibition(True)
        if self._diagnostics_enabled:
            self._start_diagnostics_logging()

        if not hardware_controlled:
            if self.session.replicant_running and self.session.replicant_delays:
                first_delay_s = warmup_s + self.session.replicant_delays[0]
            else:
                first_delay_s = warmup_s
            
            # Absolute Scheduling Init
            now = time.monotonic()
            self._next_host_target_time = now + first_delay_s
            self._schedule_next_tap(first_delay_s, track_next=False)

        if not self.serial or not self.serial.is_open():
            status_msg = "Run started (serial disconnected)."
        else:
            status_msg = "Run started."
        if not hardware_controlled and first_delay_s is not None:
            if first_delay_s <= 0.0:
                delay_label = "immediately"
            else:
                delay_label = f"in {first_delay_s:.1f}s"
            delay_msg = f"Host run armed. First tap {delay_label} - do not flip switch."
            status_msg = f"{status_msg} {delay_msg}"
            try:
                self.serial_status.setText(delay_msg)
            except Exception:
                pass
        if not relocated_ok:
            status_msg = f"{status_msg} Recording stayed in original folder."
        self._update_status(status_msg)

    def _stop_run(self, *, from_hardware: bool = False):
        self._acclimation_timer.stop()
        self._acclimation_end_time = None
        self._set_sleep_inhibition(False)
        if not self._hardware_run_active and not from_hardware:
            self._set_run_controls_locked(False)
            self._update_status("Acclimation cancelled.")
            return

        if not self._hardware_run_active:
            return
        recording_path = self.recorder.path if self.recorder else ""
        self.run_timer.stop()
        self._auto_stop_timer.stop()
        self._auto_stop_pending_taps = None
        self._next_tap_delay_s = None
        self._next_host_target_time = None
        self._hardware_run_active = False
        self.session.hardware_run_active = False
        self._set_run_controls_locked(False)
        self._low_disk_mode_active = False
        self._tracking_log_decimate = 1
        self._low_disk_dialog_shown = False
        self._disk_full_detected = False
        self._stop_diagnostics_logging()
        # Check for unsaved Life-Raft data
        for logger in (self.session.logger, self.session.tracking_logger):
            if logger and hasattr(logger, "retry_flush"):
                try:
                    logger.retry_flush()
                except Exception:
                    pass
        loggers_with_data = []
        if self.session.logger and getattr(self.session.logger, "has_unsaved_data", lambda: False)():
            loggers_with_data.append(self.session.logger)
        if self.session.tracking_logger and getattr(self.session.tracking_logger, "has_unsaved_data", lambda: False)():
            loggers_with_data.append(self.session.tracking_logger)
            
        if loggers_with_data:
            dlg = UnsavedDataDialog(self, loggers_with_data)
            dlg.exec()

        if self.session.logger:
            try:
                self.session.logger.close()
            except Exception:
                pass
            self.session.logger = None
        if self.session.tracking_logger:
            try:
                self.session.tracking_logger.close()
            except Exception:
                pass
            self.session.tracking_logger = None
        if self.session.frame_logger:
            try:
                self.session.frame_logger.close()
            except Exception:
                pass
            self.session.frame_logger = None

        if self.recorder:
            self._stop_recording()
        self._auto_rec_started = False

        if self.session.run_dir:
            try:
                run_dir = Path(self.session.run_dir)
                updates = {
                    "ended_at": datetime.now(timezone.utc).isoformat(),
                    "duration_s": self.session.last_run_elapsed,
                    "taps": self.session.taps,
                    "recording_path": recording_path,
                }
                self._update_run_metadata(run_dir, updates)
                self.runCompleted.emit(run_dir.name, str(run_dir))
            except Exception:
                pass

        self.session.run_start = None
        self.session.replicant_running = False
        self.session.replicant_index = 0
        self.session.replicant_progress = 0
        self._pending_taps.clear()
        if from_hardware:
            self._update_status("Hardware run stopped.")
        else:
            self._update_status("Run stopped.")

    def _on_tap_due(self):
        if not self._hardware_run_active or not self._run_controlled_by_host:
            return
            
        # 1. Execute the Tap (Send Command)
        mode_label = self.mode.currentText().strip() or "Periodic"
        mark = "scheduled"
        
        if self.session.replicant_running:
            mode_label = "Replicant"
            if self.session.replicant_index >= len(self.session.replicant_delays):
                self._stop_run()
                return
            
        self._queue_pending_tap(mode_label, mark)
        sent = self._send_serial_char("t", f"{mode_label} tap")
        if not sent:
            self._log_pending_tap(None)

        # 2. Schedule Next (Absolute Timing)
        if self.session.replicant_running:
            self.session.replicant_index += 1
            if self.session.replicant_index < len(self.session.replicant_delays):
                # Replicant: Targets are pre-calculated offsets. 
                # Ideally, we'd base this on run_start + offset[i].
                # But to fit existing logic, we just add the delta.
                delta = self.session.replicant_delays[self.session.replicant_index]
                if self._next_host_target_time is None:
                    self._next_host_target_time = time.monotonic()
                self._next_host_target_time += delta
            else:
                self._stop_run()
                return
        else:
            # Periodic/Poisson
            delta = self.session.scheduler.next_delay_s()
            if self._next_host_target_time is None:
                 self._next_host_target_time = time.monotonic()
            self._next_host_target_time += delta

        if self._should_schedule_next_tap():
            now = time.monotonic()
            delay = self._next_host_target_time - now
            # If we are late (negative delay), fire immediately (0) to catch up
            self._schedule_next_tap(max(0.0, delay))
        else:
            self._next_tap_delay_s = None

    def _start_recording(self):
        if self.cap is None:
            self._update_status("Camera not open.")
            return
        if self.recorder is not None:
            return
        target_dir: Path
        if self.session.run_dir:
            target_dir = Path(self.session.run_dir)
        else:
            base = Path(self.outdir_edit.text().strip() or str(RUNS_DIR))
            target_dir = base / f"recording_{time.strftime('%Y%m%d_%H%M%S')}"
            target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / "video.mp4"
        fps = self.cap.get_fps() or self.preview_fps
        size = self.cap.get_size()
        try:
            self.recorder = video.VideoRecorder(str(path), fps=fps, frame_size=size)
        except Exception as e:
            self.recorder = None
            self._update_status(f"Failed to start recording: {e}")
            return
        if not self.recorder.is_open():
            self.recorder = None
            self._update_status("Failed to start recording.")
            return
        self._recording_active = True
        self._refresh_recording_indicator()
        if self.session.logger:
            try:
                self.session.logger.set_recording_path(self.recorder.path)
            except Exception:
                pass
        if self.session.run_dir:
            try:
                self._update_run_metadata(Path(self.session.run_dir), {"recording_path": self.recorder.path})
            except Exception:
                pass
        self._update_status(f"Recording → {self.recorder.path}")

    def _stop_recording(self):
        if self.recorder:
            try:
                self.recorder.close()
            except Exception:
                pass
        self.recorder = None
        self._recording_active = False
        self._refresh_recording_indicator()
        self._update_status("Recording stopped.")

    def _send_serial_char(self, ch: str, label: str = "") -> bool:
        if not self.serial or not self.serial.is_open():
            self._update_status("Serial not connected.")
            return False
        ok = self.serial.send_char(ch)
        if ok:
            if label:
                self.serial_status.setText(f"Last serial command: {label}")
            if ch == "e":
                self._motor_enabled = True
            elif ch == "d":
                self._motor_enabled = False
        else:
            self._update_status(f"Failed to send '{ch}'.")
        return ok

    def _manual_tap(self):
        self._queue_pending_tap("Manual", "manual")
        sent = self._send_serial_char("t", "Manual tap")
        if not sent:
            self._log_pending_tap(None)

    def _toggle_serial(self):
        if self.serial and self.serial.is_open():
            try:
                self.serial.close()
            except Exception:
                pass
            self.serial_timer.stop()
            if self._resource_registry and self._active_serial_port:
                self._resource_registry.release_serial(self, self._active_serial_port)
            self.session.active_serial_port = ""
            self._reset_serial_indicator("disconnected")
            return

        port = self.port_edit.currentText().strip()
        if not port:
            self._update_status("Select a serial port first.")
            return
        if self._resource_registry:
            ok, owner = self._resource_registry.claim_serial(self, port)
            if not ok:
                QMessageBox.warning(self, "Serial", "Port is already in use.")
                return
        self._active_serial_port = port
        self.session.active_serial_port = port
        try:
            self.serial.open(port, baudrate=SERIAL_BAUD_DEFAULT, timeout=SERIAL_TIMEOUT_S)
        except Exception as e:
            self._update_status(f"Failed to open serial: {e}")
            if self._resource_registry:
                self._resource_registry.release_serial(self, port)
            return
        self.serial_timer.start()
        self._reset_serial_indicator("waiting")

    def _open_camera(self):
        if self.cap is not None:
            self._cancel_disk_calibration()
            try:
                self._stop_frame_stream()
            except Exception:
                pass
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
            if self._resource_registry is not None and self.session.camera_index is not None:
                self._resource_registry.release_camera(self, self.session.camera_index)
            self.session.camera_index = None
            self.cam_btn.setText("Open")
            self._update_status("Camera closed.")
            return

        index = int(self.cam_index.value())
        if self._resource_registry:
            ok, owner = self._resource_registry.claim_camera(self, index)
            if not ok:
                QMessageBox.warning(self, "Camera", "Camera index already in use.")
                return
        cap = video.VideoCapture(index)
        if not cap.open():
            QMessageBox.warning(self, "Camera", "Failed to open camera.")
            if self._resource_registry:
                self._resource_registry.release_camera(self, index)
            return
        self.cap = cap
        self.session.camera_index = index
        self.cam_btn.setText("Close")
        self._start_frame_stream()
        self._update_status(f"Camera {index} opened.")
        if self.session.run_dir:
            try:
                self._update_run_metadata(
                    Path(self.session.run_dir),
                    {
                        "camera_index": index,
                        "camera_fps": cap.get_fps(),
                        "camera_frame_size": cap.get_size(),
                    },
                )
            except Exception:
                pass

    def _load_calibration(self) -> dict[str, float]:
        for path in self._calibration_paths:
            try:
                if path.exists():
                    with path.open("r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    if isinstance(data, dict):
                        self._active_calibration_path = path
                        return data
            except Exception:
                continue
        return {}

    # Frame loop
    def _handle_frame(self, frame, frame_idx, timestamp):
        if self.cap is None or frame is None:
            return
        
        self._last_frame_ts = time.monotonic()
        self._diag_preview_frames += 1
        if self._disk_calib_active and self._disk_calib_recorder is not None:
            try:
                self._disk_calib_recorder.write(frame)
                self._disk_calib_frames += 1
                if (time.monotonic() - self._disk_calib_start_ts) >= DISK_CALIBRATION_DURATION_S:
                    self._finish_disk_calibration()
            except Exception:
                pass
        # Frame arrives as BGR from FrameWorker (Zero-Copy)
        bgr = frame 
        
        # Submit to Render Worker for Composition (Off-Thread)
        # We pass the CURRENT known mask.
        mask = getattr(self.session, "cv_mask", None)
        
        # Only draw overlay if enabled
        if hasattr(self, "show_cv_check") and not self.show_cv_check.isChecked():
            mask = None
            
        self.render_worker.submit_frame(bgr, mask, frame_idx)
        if self.session.frame_logger:
            try:
                self.session.frame_logger.log_frame(frame_idx, timestamp)
            except Exception:
                pass

        # Recording (Direct BGR Write - Fast)
        if self.recorder:
            self._recorded_frame_counter = frame_idx
            self.session.recorded_frame_counter = frame_idx
            self.recorder.write(bgr)

    def _on_render_ready(self, qimage, frame_idx):
        """Called when RenderWorker finishes composing the frame + overlay."""
        pix = QPixmap.fromImage(qimage)
        
        self._preview_frame_counter = frame_idx
        self.session.preview_frame_counter = frame_idx
        
        if pix.width() and pix.height():
            self._maybe_update_preview_aspect(pix.width(), pix.height())
            
        self.video_view.set_image(pix)
        if self._pip_window:
            self._pip_window.set_pixmap(pix)

    def _on_cv_results(self, results, frame_idx, timestamp, mask):
        self.session.cv_results = results
        self.session.cv_mask = mask
        self._diag_cv_frames += 1
        if self._disk_calib_active:
            count = len(results) if results else 1
            self._disk_calib_counts.append(count)
            self._disk_calib_last_results = results
        if self.session.tracking_logger:
            if self._tracking_log_decimate <= 1 or (self._tracking_log_counter % self._tracking_log_decimate == 0):
                self.session.tracking_logger.log_frame(frame_idx, timestamp, results)
            self._tracking_log_counter += 1
        try:
            current_ids = {res.id for res in results}
        except Exception:
            current_ids = set()
        for stale_id in list(self._last_cv_states):
            if stale_id not in current_ids:
                self._last_cv_states.pop(stale_id, None)
        run_start = self.session.run_start
        for res in results or []:
            prev_state = self._last_cv_states.get(res.id)
            if run_start is not None and res.state == "CONTRACTED" and prev_state != "CONTRACTED":
                t_since = float(timestamp) - run_start
                if t_since >= 0:
                    self._contraction_count += 1
                    self.live_chart.add_contraction(t_since)
            self._last_cv_states[res.id] = res.state

    # _draw_cv_overlay removed - logic moved to RenderWorker

    def _start_frame_stream(self):
        if self.cap is None or self._frame_worker is not None:
            return
        interval = int(MS_PER_SEC / max(1, self.preview_fps))
        self._frame_worker = FrameWorker(self.cap, interval)
        
        # 1. Start CV process once SHM is allocated
        self._frame_worker.shmReady.connect(self.cv_worker.start_processing, Qt.QueuedConnection)
        
        # 2. Feed frame indices to CV worker (it reads actual data from SHM)
        # Use cvTaskReady (lightweight) instead of frameReady (heavy)
        self._frame_worker.cvTaskReady.connect(self.cv_worker.process_frame, Qt.QueuedConnection)
        
        # 3. Handle UI Preview
        self._frame_worker.frameReady.connect(self._handle_frame, Qt.QueuedConnection)
             
        self._frame_worker.error.connect(self._update_status, Qt.QueuedConnection)
        self.cv_worker.error.connect(self._update_status, Qt.QueuedConnection)
        self._frame_worker.stopped.connect(self._on_frame_worker_stopped, Qt.QueuedConnection)
        
        self._last_frame_ts = time.monotonic()
        self._camera_dead = False
        self._watchdog_timer.start()
        self._frame_worker.start()

    @Slot()
    def _on_frame_worker_stopped(self):
        self._watchdog_timer.stop()
        self._camera_dead = False
        # Stop CV process when camera stops
        if self.cv_worker:
            self.cv_worker.stop_processing()
        self._frame_worker = None

    def _stop_frame_stream(self):
        worker = self._frame_worker
        if worker:
            worker.stop()
        self._cleanup_frame_stream()

    def _cleanup_frame_stream(self):
        if self._frame_worker is not None:
            try:
                self._frame_worker.deleteLater()
            except Exception:
                pass
            self._frame_worker = None

    def _on_port_text_changed(self, text: str):
        text = text.strip()
        self._active_serial_port = text

    def _check_camera_heartbeat(self):
        if self._last_frame_ts is None or self.cap is None:
            return
            
        elapsed = time.monotonic() - self._last_frame_ts
        if elapsed > 5.0: # 5 second threshold
            self._camera_dead = True
            self._update_status(f"⚠️ CAMERA TIMEOUT: No frames for {elapsed:.1f}s!")
            # Visual alert: toggle status line color
            palette = self._theme
            danger = palette.get("DANGER", "#FF0000")
            self.status.setStyleSheet(f"color: {danger}; font-weight: bold; font-size: 14pt;")
            # Audible alert
            try:
                QApplication.beep()
            except Exception:
                pass
        else:
            if self._camera_dead:
                self._camera_dead = False
                # Restore style
                text_color = self._theme.get("TEXT", "#000000")
                self.status.setStyleSheet(f"color: {text_color}; font-weight: normal; font-size: 11pt;")
                self._update_status("Camera recovered.")

    def shutdown(self):
        try:
            self._stop_frame_stream()
        except Exception:
            pass
        try:
            if self._hardware_run_active:
                self._stop_run()
        except Exception:
            pass
        if self.recorder:
            try:
                self._stop_recording()
            except Exception:
                pass
        if hasattr(self, "render_worker") and self.render_worker:
            self.render_worker.stop()
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        self.session.camera_index = None
        if self._pip_window:
            try:
                self._pip_window.close()
            except Exception:
                pass
            self._pip_window = None
        if self.serial.is_open():
            try:
                self.serial.close()
            except Exception:
                pass
            try:
                self.serial_btn.setText("Connect")
            except Exception:
                pass
            self._reset_serial_indicator("disconnected")
        self.serial_timer.stop()
        self._hardware_run_active = False
        self._awaiting_switch_start = False
        self._hardware_configured = False
        self._active_serial_port = ""
        registry = getattr(self, "_resource_registry", None)
        if registry is not None:
            registry.release_all(self)
        try:
            self.session.reset_runtime_state()
        except Exception:
            pass
