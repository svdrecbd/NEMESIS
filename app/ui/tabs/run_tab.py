# app/ui/tabs/run_tab.py
import sys, os, time, json, uuid, csv, threading, math
from pathlib import Path
from collections.abc import Sequence, Callable
from datetime import datetime, timezone
from typing import Optional, Any
import cv2

from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QFileDialog, QHBoxLayout, QVBoxLayout, QGridLayout, 
    QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QMessageBox, QSizePolicy, 
    QListView, QSplitter, QFrame, QSpacerItem, QCheckBox, QProgressDialog, QMenu,
    QApplication, QStyleFactory, QScrollArea, QToolButton, QDialog, QPlainTextEdit,
    QGraphicsOpacityEffect
)
from PySide6.QtCore import (
    QTimer, Qt, QSize, Signal, Slot, QUrl, QPoint, QPropertyAnimation, QEasingCurve, QRect,
    QEvent, QAbstractAnimation
)
from PySide6.QtGui import QImage, QPixmap, QFontDatabase, QFont, QIcon, QPainter, QColor, QPen, QPalette, QDesktopServices, QCursor

from serial.tools import list_ports

from app.core import video, scheduler, configio
from app.core.logger import APP_LOGGER, RunLogger, TrackingLogger, configure_file_logging
from app.core.session import RunSession
from app.core.workers import FrameWorker, ProcessCVWorker
from app.core.paths import RUNS_DIR, LOGO_PATH, BASE_DIR
from app.core.runlib import RunLibrary
from app.drivers.arduino_driver import SerialLink

from app.ui.theme import (
    active_theme, set_active_theme, BG, MID, TEXT, SUBTXT, ACCENT, DANGER, BORDER, 
    BUTTON_BORDER, BUTTON_CHECKED_BG, INPUT_BORDER, build_stylesheet, THEMES, 
    DEFAULT_THEME_NAME, set_macos_titlebar_appearance
)
from app.ui.widgets.viewer import ZoomView, PinnedPreviewWindow, AppZoomView
from app.ui.widgets.chart import LiveChart
from app.ui.widgets.containers import AspectRatioContainer

APP_VERSION = "1.0-rc1"
FOOTER_LOGO_SCALE = 0.036
_ACTIVE_THEME_NAME = "light"
_FONT_FAMILY = "Typestar OCR Regular"

def _log_gui_exception(e: Exception, context: str = "GUI operation") -> None:
    APP_LOGGER.error(f"Unhandled GUI exception in {context}: {e}", exc_info=True)

class ResourceRegistry:
    """Tracks camera and serial ownership across run tabs."""

    def __init__(self):
        self._camera_owners: dict[int, Any] = {}
        self._serial_owners: dict[str, Any] = {}

    def claim_camera(self, owner: Any, index: int) -> tuple[bool, Optional[Any]]:
        idx = int(index)
        existing = self._camera_owners.get(idx)
        if existing is not None and existing is not owner:
            return False, existing
        self._camera_owners[idx] = owner
        return True, existing

    def release_camera(self, owner: Any, index: Optional[int] = None) -> None:
        if index is not None:
            idx = int(index)
            if self._camera_owners.get(idx) is owner:
                self._camera_owners.pop(idx, None)
            return
        for idx, current in list(self._camera_owners.items()):
            if current is owner:
                self._camera_owners.pop(idx, None)

    def claim_serial(self, owner: Any, port: str) -> tuple[bool, Optional[Any]]:
        key = port.strip()
        existing = self._serial_owners.get(key)
        if existing is not None and existing is not owner:
            return False, existing
        self._serial_owners[key] = owner
        return True, existing

    def release_serial(self, owner: Any, port: Optional[str] = None) -> None:
        if port is not None:
            key = port.strip()
            if self._serial_owners.get(key) is owner:
                self._serial_owners.pop(key, None)
            return
        for key, current in list(self._serial_owners.items()):
            if current is owner:
                self._serial_owners.pop(key, None)

    def release_all(self, owner: Any) -> None:
        self.release_camera(owner)
        self.release_serial(owner)


class RunTab(QWidget):
    runCompleted = Signal(str, str)
    themeChanged = Signal(str)

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
                try:
                    v.setViewportMargins(0, 0, 0, 0)
                    if hasattr(v, 'setSpacing'):
                        v.setSpacing(0)
                except Exception:
                    pass
                if self._popup_qss:
                    v.setStyleSheet(self._popup_qss)
                    try:
                        v.viewport().setStyleSheet(
                            f"background: {MID}; border: none; margin: 0px; padding: 0px;"
                        )
                    except Exception:
                        pass
                    try:
                        popup_win = v.window()
                        if popup_win:
                            popup_win.setStyleSheet(
                                f"background: {MID}; border: 1px solid {BG}; margin: 0px; padding: 0px;"
                            )
                    except Exception:
                        pass
                try:
                    hint = 0
                    try:
                        # sizeHintForColumn works for QListView; add padding for checkmark/scrollbar
                        hint = max(hint, v.sizeHintForColumn(0) + 24)
                    except Exception:
                        pass
                    view_w = max(self.width(), hint, 140)
                    v.setFixedWidth(view_w)
                    if hasattr(v, 'setHorizontalScrollBarPolicy'):
                        v.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                except Exception:
                    pass
            except Exception:
                pass
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
        if hasattr(self, "logo_footer") and self.logo_footer:
            if self.logo_footer.pixmap() is None:
                try:
                    self.logo_footer.setStyleSheet(f"color: {ACCENT}; font-size: 16pt; font-weight: bold;")
                except Exception:
                    pass
        if hasattr(self, "logo_tagline") and self.logo_tagline:
            try:
                self.logo_tagline.setStyleSheet(
                    f"color: {TEXT}; font-size: 10pt; font-weight: normal;"
                )
            except Exception:
                pass
        if hasattr(self, "replicant_status") and self.replicant_status:
            try:
                self.replicant_status.setStyleSheet(f"color: {SUBTXT};")
            except Exception:
                pass

    def _refresh_recording_indicator(self):
        if not hasattr(self, "rec_indicator"):
            return
        if getattr(self, "_recording_active", False):
            try:
                self.rec_indicator.setText("● REC ON")
                self.rec_indicator.setStyleSheet(f"color:{DANGER}; font-weight:bold;")
            except Exception:
                pass
        else:
            try:
                self.rec_indicator.setText("● REC OFF")
                self.rec_indicator.setStyleSheet(f"color:{SUBTXT};")
            except Exception:
                pass

    def _apply_theme_to_widgets(self):
        theme = self._theme
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
                self.chart_frame.setStyleSheet(f"background: {BG}; border: 1px solid {BORDER};")
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
                pal.setColor(pane.backgroundRole(), QColor(BG))
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
        if hasattr(self, "_action_mirror_mode") and self._action_mirror_mode:
            try:
                self._action_mirror_mode.blockSignals(True)
                self._action_mirror_mode.setChecked(self._mirror_mode)
                self._action_mirror_mode.blockSignals(False)
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

    def _update_mirror_layout(self):
        split = getattr(self, "splitter", None)
        left = getattr(self, "_left_widget", None)   # Video pane
        right = getattr(self, "_right_widget", None) # Controls pane
        if split is None or left is None or right is None:
            return
        
        # Mirror mode: Controls (right) | Video (left)
        # Normal mode: Video (left) | Controls (right)
        desired = (right, left) if self._mirror_mode else (left, right)
        
        # Reorder widgets if needed
        for idx, widget in enumerate(desired):
            current_idx = split.indexOf(widget)
            if current_idx == -1 or current_idx == idx:
                continue
            try:
                split.blockSignals(True)
                split.insertWidget(idx, widget)
            finally:
                split.blockSignals(False)
        
        # Enforce strict sizing: Controls get minimal width, Video gets the rest
        try:
            if self._mirror_mode:
                # [Controls, Video]
                split.setSizes([380, 100000])
            else:
                # [Video, Controls]
                split.setSizes([100000, 380])
        except Exception:
            pass

        try:
            # Ensure Video (left) stretches and Controls (right) are fixed
            idx_video = split.indexOf(left)
            idx_ctrl = split.indexOf(right)
            if idx_video >= 0:
                split.setStretchFactor(idx_video, 1)
            if idx_ctrl >= 0:
                split.setStretchFactor(idx_ctrl, 0)
            
            # Re-disable handle to prevent sliding, but keep 10px gap
            split.setHandleWidth(10)
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
        anim.setDuration(500)
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
        self._theme_overlay: QWidget | None = None
        self._theme_overlay_anim: QPropertyAnimation | None = None

        # Top dense status line + inline logo
        header_row = QHBoxLayout()
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
        self.video_view.setMinimumSize(480, 270)

        # Serial controls
        self.port_edit = QComboBox()
        self.port_edit.setEditable(True)
        self.port_edit.setInsertPolicy(QComboBox.NoInsert)
        self.port_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.port_edit.lineEdit().setPlaceholderText("COM3 or /dev/ttyUSB0")
        self._refresh_serial_ports(initial=True)
        self.serial_btn = QPushButton("Connect Serial")
        self.enable_btn = QPushButton("Enable Motor")
        self.disable_btn = QPushButton("Disable Motor")
        self.tap_btn = QPushButton("Manual Tap")
        # Jog controls (half‑step moves handled by firmware)
        self.jog_up_btn = QPushButton("Raise Arm ▲")
        self.jog_down_btn = QPushButton("Lower Arm ▼")
        self.jog_up_btn.setToolTip("Raise tapper arm (half step)")
        self.jog_down_btn.setToolTip("Lower tapper arm (half step)")

        # Camera controls
        self.cam_index = QSpinBox(); self.cam_index.setRange(0, 8); self.cam_index.setValue(0)
        self.cam_btn = QPushButton("Open Camera")
        self.cam_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Recording controls (independent)
        self.rec_start_btn = QPushButton("Start Recording")
        self.rec_start_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.rec_stop_btn  = QPushButton("Stop Recording")
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
        mode_w = fm.horizontalAdvance(max_text) + 60
        self.mode.setMinimumWidth(170)
        self.mode.setMaximumWidth(max(220, mode_w + 10))
        self.mode.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        mv = QListView(); self.mode.setView(mv)
        mv.viewport().setAutoFillBackground(True)
        mv.setAutoFillBackground(True)
        mv.setAttribute(Qt.WA_StyledBackground, True)
        mv.setFrameShape(QFrame.NoFrame)
        self.period_sec = QDoubleSpinBox(); self.period_sec.setRange(0.1, 3600.0); self.period_sec.setValue(10.0); self.period_sec.setSuffix(" s")
        self.period_sec.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.lambda_rpm = QDoubleSpinBox(); self.lambda_rpm.setRange(0.1, 600.0); self.lambda_rpm.setValue(6.0); self.lambda_rpm.setSuffix(" taps/min")
        self.lambda_rpm.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        shared_control_width = 200
        self.mode.setFixedWidth(shared_control_width)
        self.period_sec.setFixedWidth(shared_control_width)
        self.lambda_rpm.setFixedWidth(shared_control_width)

        # Stepsize (1..5) — sent to firmware, logged per-tap
        self.stepsize = RunTab.StyledCombo(popup_qss=popup_qss)
        self.stepsize.addItems(["-", "1 (Full Step)","2 (Half Step)","3 (1/4 Step)","4 (1/8 Step)","5 (1/16 Step)"])
        self.stepsize.setCurrentIndex(0)
        self.stepsize.currentTextChanged.connect(self._on_stepsize_changed)
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
            s_max_text = "5"
        s_w = s_fm.horizontalAdvance(s_max_text) + 40  # text + arrow/padding
        self.stepsize.setFixedWidth(max(shared_control_width, s_w + 20))
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
        self.pro_btn = QPushButton("Pro Mode: OFF")
        self.pro_btn.setCheckable(True)
        self.pro_btn.toggled.connect(self._toggle_pro_mode)
        self.pro_mode = False

        # Live chart (template-like raster): embedded Matplotlib, Typestar font
        self.live_chart = LiveChart(font_family=_FONT_FAMILY, theme=self._theme)
        # Wrap chart in a framed panel to match other boxes (use BG to match general background)
        self.chart_frame = QFrame()
        # Match the video preview container styling exactly
        self.chart_frame.setStyleSheet(f"background: {BG}; border: 1px solid {BORDER};")
        self.chart_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        chart_layout = QVBoxLayout(self.chart_frame)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_layout.addWidget(self.live_chart.canvas)
        chart_controls = QHBoxLayout()
        chart_controls.setContentsMargins(0, 4, 0, 0)
        chart_controls.setSpacing(6)
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
        self.counters = QLabel("Taps: 0 | Elapsed: 0 s | Rate10: -- /min | Overall: 0.0 /min")
        self.counters.setWordWrap(True)
        serial_status_row = QHBoxLayout()
        serial_status_row.setContentsMargins(0, 0, 0, 0)
        serial_status_row.setSpacing(12)

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
            alpha_threshold = 24
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
        self.logo_tagline = QLabel(f"© {current_year} California Numerics")
        self.logo_tagline.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.logo_tagline.setTextFormat(Qt.PlainText)
        self.logo_tagline.setTextInteractionFlags(Qt.NoTextInteraction)
        self.logo_tagline.setStyleSheet(
            f"color: {TEXT}; font-size: 10pt; font-weight: normal;"
        )
        self.logo_tagline.setContentsMargins(0, 4, 0, 0)
        self.logo_tagline.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self.logo_menu = self._build_logo_menu()
        serial_status_row.addStretch(1)  # keep status text left-aligned

        # Layout
        # Left pane: 16:9-bounded preview, then chart; keep both anchored to top
        left = QVBoxLayout(); left.setContentsMargins(0, 0, 0, 0); left.setSpacing(8)
        self.video_area = AspectRatioContainer(self.video_view, 16, 9)
        try:
            self.video_area.setMinimumSize(360, 202)
        except Exception:
            pass
        left.addWidget(self.video_area, 0, Qt.AlignTop)
        left.addWidget(self.chart_frame, 0, Qt.AlignTop)
        left.addStretch(1)
        # Top margin keeps controls clear of the window chrome
        right = QVBoxLayout(); right.setContentsMargins(0, 32, 0, 0); right.setSpacing(8)

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
        serial_ctrl_section.setSpacing(6)
        serial_ctrl_section.addLayout(r1)
        serial_ctrl_section.addLayout(r1b)
        serial_ctrl_section.addLayout(r1c)

        r2 = QHBoxLayout(); r2.addWidget(QLabel("Camera idx:")); r2.addWidget(self.cam_index); r2.addWidget(self.cam_btn)
        self.popout_btn = QPushButton("Pop-out Preview")
        self.popout_btn.setCheckable(True)
        self.popout_btn.setToolTip("Open a floating always-on-top preview window")
        self.popout_btn.toggled.connect(self._toggle_preview_popout)
        self.popout_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        r2.addWidget(self.popout_btn)
        
        self.show_cv_check = QCheckBox("Show Analysis")
        self.show_cv_check.setToolTip("Overlay Stentor tracking and state classification")
        r2.addWidget(self.show_cv_check)
        
        self.auto_rec_check = QCheckBox("Auto-Rec")
        self.auto_rec_check.setToolTip("Start recording automatically when run starts")
        r2b = QHBoxLayout(); r2b.addWidget(self.rec_start_btn); r2b.addWidget(self.rec_stop_btn); r2b.addWidget(self.rec_indicator); r2b.addWidget(self.auto_rec_check)
        camera_section = QVBoxLayout()
        camera_section.setContentsMargins(0, 0, 0, 0)
        camera_section.setSpacing(6)
        camera_section.addLayout(r2)
        camera_section.addLayout(r2b)

        # Stable label widths to prevent relayout
        self.lbl_mode = QLabel("Mode:")
        self.lbl_period = QLabel("Period:")
        self.lbl_lambda = QLabel("λ (taps/min):")
        self.lbl_stepsize = QLabel("Stepsize:")
        self.lbl_replicant = QLabel("Replicant:")
        self.lbl_autostop = QLabel("Stop after (min):")
        lfm = self.lbl_mode.fontMetrics()
        label_w = max(
            lfm.horizontalAdvance("Mode:"),
            lfm.horizontalAdvance("Period:"),
            lfm.horizontalAdvance("λ (taps/min):"),
            lfm.horizontalAdvance("Stepsize:"),
            lfm.horizontalAdvance("Replicant:"),
            lfm.horizontalAdvance("Stop after (min):")
        ) + 8
        for lbl in (self.lbl_mode, self.lbl_period, self.lbl_lambda, self.lbl_stepsize, self.lbl_replicant, self.lbl_autostop):
            lbl.setFixedWidth(label_w)
        controls_grid = QGridLayout()
        controls_grid.setContentsMargins(0, 0, 0, 0)
        controls_grid.setHorizontalSpacing(6)
        controls_grid.setVerticalSpacing(4)
        replicant_controls = QHBoxLayout()
        replicant_controls.setContentsMargins(0, 0, 0, 0)
        replicant_controls.setSpacing(6)
        replicant_controls.addWidget(self.replicant_status, 1, Qt.AlignLeft)
        replicant_controls.addStretch(1)
        replicant_controls.addWidget(self.replicant_load_btn, 0, Qt.AlignRight)
        replicant_controls.addWidget(self.replicant_clear_btn, 0, Qt.AlignRight)
        
        # Auto-stop control
        self.auto_stop_min = QDoubleSpinBox()
        self.auto_stop_min.setRange(0.0, 20000.0)
        self.auto_stop_min.setValue(0.0)
        self.auto_stop_min.setDecimals(1)
        self.auto_stop_min.setSuffix(" min")
        self.auto_stop_min.setSpecialValueText("Off")
        self.auto_stop_min.setFixedWidth(200)
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
        controls_grid.addWidget(self.lbl_autostop, 5, 0, Qt.AlignLeft)
        controls_grid.addWidget(self.auto_stop_min, 5, 1, Qt.AlignRight)
        controls_grid.setColumnStretch(1, 1)
        mode_section = QVBoxLayout()
        mode_section.setContentsMargins(0, 0, 0, 0)
        mode_section.setSpacing(6)
        mode_section.addLayout(controls_grid)
        flash_row = QHBoxLayout(); flash_row.setContentsMargins(0, 0, 0, 0); flash_row.addWidget(self.flash_config_btn, 1)
        mode_section.addLayout(flash_row)

        r4 = QHBoxLayout(); r4.addWidget(self.run_start_btn); r4.addWidget(self.run_stop_btn); r4.addWidget(self.clear_data_btn)
        r5 = QHBoxLayout(); r5.addWidget(QLabel("Output dir:")); r5.addWidget(self.outdir_edit,1); r5.addWidget(self.outdir_btn)

        # Config save/load row (was missing from layout)
        r5b = QHBoxLayout(); r5b.addWidget(self.save_cfg_btn); r5b.addWidget(self.load_cfg_btn)
        r5c = QHBoxLayout(); r5c.addWidget(self.flash_config_btn, 1)

        io_section = QVBoxLayout()
        io_section.setContentsMargins(0, 0, 0, 0)
        io_section.setSpacing(6)
        io_section.addLayout(r4)
        io_section.addLayout(r5)
        io_section.addLayout(r5b)

        # (chart moved under the video preview)
        footer_status_section = QVBoxLayout()
        footer_status_section.setContentsMargins(0, 0, 0, 0)
        footer_status_section.setSpacing(6)
        footer_status_section.addWidget(self.counters)
        footer_status_section.addWidget(self.status)
        footer_status_section.addLayout(serial_status_row)

        logo_section = QVBoxLayout()
        logo_section.setContentsMargins(0, 0, 0, 0)
        logo_section.setSpacing(0)
        logo_row = QHBoxLayout()
        logo_row.setContentsMargins(0, 8, 0, 0)  # small gap above helps line up with chart base
        logo_block = QVBoxLayout()
        logo_block.setContentsMargins(0, 0, 0, 0)
        logo_block.setSpacing(2)
        logo_block.addWidget(self.logo_footer, 0, Qt.AlignLeft | Qt.AlignBottom)
        logo_block.addWidget(self.logo_tagline, 0, Qt.AlignLeft | Qt.AlignTop)
        logo_row.addLayout(logo_block)
        logo_row.addStretch(1)
        logo_section.addLayout(logo_row)
        logo_section.addStretch(1)

        section_gap = 24  # triple gap keeps clusters distinct without feeling sparse
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
            leftw.setMinimumWidth(max(360, self.video_area.minimumWidth()))
        except Exception:
            pass
        rightw = QWidget()
        rightw.setLayout(right)
        self._right_layout = right
        self._right_widget = rightw
        rightw.setAutoFillBackground(True)
        pal_right = rightw.palette(); pal_right.setColor(rightw.backgroundRole(), QColor(BG)); rightw.setPalette(pal_right)
        try:
            rightw.setMinimumWidth(360)
        except Exception:
            pass
        right_scroll = QScrollArea()
        right_scroll.setWidget(rightw)
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        right_scroll.setMinimumWidth(380)
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
        splitter.setHandleWidth(10)
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
            left = int(round(total * 0.75))
            right = max(360, total - left)
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
        contentw.setMinimumSize(1280, 780)
        self.app_view = AppZoomView(bg_color=self._theme.get("BG", BG))
        self.app_view.set_content(contentw)
        # Enforce a minimum window size that encompasses the full UI content
        try:
            min_hint = contentw.minimumSizeHint()
            if not min_hint.isValid() or min_hint.width() <= 0:
                min_hint = contentw.sizeHint()
            min_w = max(1280, min_hint.width())
            min_h = max(780, min_hint.height())
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

        # State
        self.cap = None
        self.recorder = None
        self._frame_worker: FrameWorker | None = None
        
        # CV Worker (Process-based)
        self.cv_worker = ProcessCVWorker()
        self.cv_worker.resultsReady.connect(self._on_cv_results)
        
        self.run_timer   = QTimer(self); self.run_timer.setSingleShot(True); self.run_timer.timeout.connect(self._on_tap_due)
        self.session = RunSession()
        self.session.reset_runtime_state()
        # Dense status line updater
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._refresh_statusline)
        self.status_timer.start(400)
        self.serial_timer = QTimer(self)
        self.serial_timer.setInterval(50)
        self.serial_timer.timeout.connect(self._drain_serial_queue)

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
        self.period_sec.valueChanged.connect(lambda _v: self._update_status("Period updated."))
        self.lambda_rpm.valueChanged.connect(lambda _v: self._update_status("Lambda updated."))
        self.stepsize.currentTextChanged.connect(self._on_stepsize_changed)
        self.port_edit.editTextChanged.connect(self._on_port_text_changed)

        # Install global event filter for pinch zoom (app-wide)
        try:
            QApplication.instance().installEventFilter(self)
        except Exception:
            pass
        self._mode_changed()
        self._update_status("Ready.")
        self._reset_serial_indicator()
        self.preview_fps = 30
        self.current_stepsize = 4
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

    # Frame loop
    def _handle_frame(self, frame, frame_idx, timestamp):
        if self.cap is None or frame is None:
            return
        
        # Overlay CV Results
        overlay = frame.copy()
        rgb = cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        pix = QPixmap.fromImage(qimg)
        
        # Draw CV Results
        self._draw_cv_overlay(pix)
        
        self._preview_frame_counter = frame_idx
        
        h, w = overlay.shape[:2]
        if w and h:
            self._maybe_update_preview_aspect(w, h)
            
        self.video_view.set_image(pix)
        if self._pip_window:
            self._pip_window.set_pixmap(pix)
            
        if self.recorder:
            self._recorded_frame_counter = frame_idx
            self.recorder.write(frame)

    def _on_cv_results(self, results, frame_idx, timestamp, mask):
        self.session.cv_results = results
        self.session.cv_mask = mask
        if self.session.tracking_logger:
            self.session.tracking_logger.log_frame(frame_idx, timestamp, results)

    def _draw_cv_overlay(self, pixmap: QPixmap):
        if not hasattr(self, "show_cv_check") or not self.show_cv_check.isChecked():
            return
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        results = getattr(self.session, "cv_results", [])
        for s in results:
            r, g, b = s.debug_color
            color = QColor(r, g, b)
            cx, cy = s.centroid
            painter.setPen(QPen(color, 2))
            painter.drawEllipse(QPoint(int(cx), int(cy)), 15, 15)
            painter.setPen(QPen(Qt.white, 1))
            painter.drawText(int(cx) - 10, int(cy) - 20, f"ID:{s.id}")
            painter.drawText(int(cx) - 10, int(cy) + 30, s.state[:3])
        painter.end()

    def _start_frame_stream(self):
        if self.cap is None or self._frame_worker is not None:
            return
        interval = int(1000 / max(1, self.preview_fps))
        self._frame_worker = FrameWorker(self.cap, interval)
        
        # 1. Start CV process once SHM is allocated
        self._frame_worker.shmReady.connect(self.cv_worker.start_processing, Qt.QueuedConnection)
        
        # 2. Feed frame indices to CV worker (it reads actual data from SHM)
        self._frame_worker.frameReady.connect(self.cv_worker.process_frame, Qt.QueuedConnection)
        
        # 3. Handle UI Preview
        self._frame_worker.frameReady.connect(self._handle_frame, Qt.QueuedConnection)
             
        self._frame_worker.error.connect(self._update_status, Qt.QueuedConnection)
        self._frame_worker.stopped.connect(self._on_frame_worker_stopped, Qt.QueuedConnection)
        self._frame_worker.start()

    @Slot()
    def _on_frame_worker_stopped(self):
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

    def shutdown(self):
        try:
            self._stop_frame_stream()
        except Exception:
            pass
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
                self.serial_btn.setText("Connect Serial")
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