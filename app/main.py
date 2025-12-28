# app.py — NEMESIS UI (v1.0-rc1, unified feature set)
import sys, os, time, json, uuid, csv, threading, math
from pathlib import Path
from collections.abc import Sequence, Callable
from datetime import datetime, timezone
from typing import Optional, Any

from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QFileDialog,
    QHBoxLayout, QVBoxLayout, QGridLayout, QComboBox, QSpinBox, QDoubleSpinBox,
    QLineEdit, QMessageBox, QSizePolicy, QListView, QSplitter, QStyleFactory, QFrame, QSpacerItem,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsProxyWidget, QSplitterHandle, QMenu,
    QGraphicsOpacityEffect, QTabWidget, QListWidget, QListWidgetItem, QInputDialog, QTabBar, QToolButton,
    QStyleOptionTab, QStyle, QScrollArea, QStylePainter, QAbstractItemView, QDialog, QPlainTextEdit,
    QCheckBox, QProgressDialog
)
from PySide6.QtCore import (
    QTimer, Qt, QEvent, QSize, Signal, QObject, Slot, QUrl, QPoint,
    QPropertyAnimation, QEasingCurve, QAbstractAnimation, QRect, QThread
)
from PySide6.QtGui import QImage, QPixmap, QFontDatabase, QFont, QIcon, QPainter, QColor, QPen, QDesktopServices, QCursor, QPalette
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import MultipleLocator, AutoLocator, NullLocator
import matplotlib as mpl
from matplotlib import font_manager
from serial.tools import list_ports
import shiboken6

# Internal modules
from .core import video, scheduler, configio, cvbot
from .core import logger as runlogger_module
from .core.logger import APP_LOGGER, TrackingLogger
from .core.session import RunSession
from .core.runlib import RunLibrary, RunSummary
from .core.analyzer import RunAnalyzer
import shutil
import cv2

# Function to get resource path for packaged applications (PyInstaller compatibility)
def _get_resource_path(relative_path: str) -> Path:
    """Get absolute path to resource, works for dev and for PyInstaller."""
    try:
        # PyInstaller creates a temporary folder and stores path in _MEIPASS
        base_path = Path(sys._MEIPASS)
    except AttributeError:
        # Fallback to dev mode: main.py is in app/, so two levels up is project root
        base_path = Path(__file__).resolve().parent.parent
    return base_path / relative_path

class CVWorker(QObject):
    resultsReady = Signal(object, int, float, object) # results, frame_idx, timestamp, mask_image
    
    def __init__(self):
        super().__init__()
        self.tracker = cvbot.StentorTracker()
        self._busy = False

    @Slot(object, int, float)
    def process_frame(self, frame, frame_idx, timestamp):
        if self._busy:
            return
        self._busy = True
        try:
            # Run the heavy math
            results, mask = self.tracker.process_frame(frame, timestamp)
            self.resultsReady.emit(results, frame_idx, timestamp, mask)
        except Exception as e:
            APP_LOGGER.error(f"CV Error: {e}")
        finally:
            self._busy = False

HEATMAP_PALETTES = ("inferno", "magma", "cividis", "plasma", "viridis", "turbo")

# Assets & Version
# Resolve assets relative to the project root, not the current working directory
BASE_DIR = _get_resource_path(".")
RUNS_DIR = (BASE_DIR / "runs").resolve()
RUNS_DIR.mkdir(parents=True, exist_ok=True)

def _migrate_legacy_run_dirs():
    for legacy in BASE_DIR.glob("run_*"):
        if not legacy.is_dir():
            continue
        dest = RUNS_DIR / legacy.name
        if dest.exists():
            continue
        try:
            legacy.replace(dest)
        except Exception as e:
            APP_LOGGER.error(f"Failed to migrate legacy run directory {legacy}: {e}")

_migrate_legacy_run_dirs()
ASSETS_DIR = _get_resource_path("assets")
FONT_PATH = _get_resource_path("assets/fonts/Typestar OCR Regular.otf")
LOGO_PATH = _get_resource_path("assets/images/transparent_logo.png")
FOOTER_LOGO_SCALE = 0.036  # further ~25% shrink keeps footer badge minimal
APP_VERSION = "1.0-rc1"
_FONT_FAMILY = None  # set at runtime when font loads
_APP_ICON: QIcon | None = None


# Shared Registries

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


class LeftAlignTabBar(QTabBar):
    """Tab bar that left-aligns text and applies consistent padding."""

    def tabSizeHint(self, index: int) -> QSize:
        size = super().tabSizeHint(index)
        size.setWidth(max(size.width(), 160))
        return size

    def paintEvent(self, event):
        painter = QStylePainter(self)
        for index in range(self.count()):
            opt = QStyleOptionTab()
            self.initStyleOption(opt, index)
            opt.rect = self.tabRect(index)
            painter.drawControl(QStyle.CE_TabBarTabShape, opt)

            text_rect = opt.rect.adjusted(12, 0, -12, 0)
            painter.save()
            role = QPalette.ButtonText if opt.state & QStyle.State_Selected else QPalette.WindowText
            painter.setPen(opt.palette.color(role))
            alignment = Qt.AlignVCenter | Qt.AlignLeft
            offset = 0
            if not opt.icon.isNull():
                icon_size = opt.iconSize if not opt.iconSize.isEmpty() else QSize(16, 16)
                icon_rect = QRect(text_rect.left(), text_rect.center().y() - icon_size.height() // 2, icon_size.width(), icon_size.height())
                opt.icon.paint(painter, icon_rect, Qt.AlignLeft | Qt.AlignVCenter,
                               QIcon.Active if opt.state & QStyle.State_Selected else QIcon.Normal,
                               QIcon.On if opt.state & QStyle.State_Selected else QIcon.Off)
                offset = icon_rect.width() + 6
            painter.drawText(text_rect.adjusted(offset, 0, 0, 0), alignment, opt.text)
            painter.restore()


# Themes
THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "BG": "#0d0f12",
        "MID": "#161a1f",
        "TEXT": "#e6ecf7",
        "SUBTXT": "#8a93a3",
        "ACCENT": "#5aa3ff",
        "DANGER": "#e33",
        "BORDER": "#333333",
        "SCROLLBAR": "#2a2f36",
        "OUTLINE": "#333333",
        "PLOT_FACE": "#161a1f",
        "GRID": "#3a414b",
        "DISABLED_BG": "#0a0d11",
        "DISABLED_TEXT": "#5e6876",
        "DISABLED_BORDER": "#11161c",
        "BUTTON_BORDER": "#252a31",
        "BUTTON_CHECKED_BG": "#1f2731",
        "INPUT_BORDER": "#252a31",
    },
    "light": {
        "BG": "#f4f7fb",
        "MID": "#e7ecf6",
        "TEXT": "#1d2334",
        "SUBTXT": "#4f5a6d",
        "ACCENT": "#3367ff",
        "DANGER": "#c0392b",
        "BORDER": "#cbd4e4",
        "SCROLLBAR": "#a3b1c7",
        "OUTLINE": "#9aa7bd",
        "PLOT_FACE": "#f4f7fb",
        "GRID": "#cdd5e5",
        "DISABLED_BG": "#e0e6f2",
        "DISABLED_TEXT": "#8a94a6",
        "DISABLED_BORDER": "#c5cedf",
        "BUTTON_BORDER": "#c0c8da",
        "BUTTON_CHECKED_BG": "#d6def2",
        "INPUT_BORDER": "#c0c8da",
    },
}

DEFAULT_THEME_NAME = "light"
_ACTIVE_THEME_NAME = DEFAULT_THEME_NAME


def _apply_theme_globals(theme: dict[str, str]) -> None:
    global BG, MID, TEXT, SUBTXT, ACCENT, DANGER, BORDER, SCROLLBAR, OUTLINE, PLOT_FACE, GRID, DISABLED_BG, DISABLED_TEXT, DISABLED_BORDER, BUTTON_BORDER, BUTTON_CHECKED_BG, INPUT_BORDER
    BG = theme["BG"]
    MID = theme["MID"]
    TEXT = theme["TEXT"]
    SUBTXT = theme["SUBTXT"]
    ACCENT = theme["ACCENT"]
    DANGER = theme["DANGER"]
    BORDER = theme["BORDER"]
    SCROLLBAR = theme["SCROLLBAR"]
    OUTLINE = theme["OUTLINE"]
    PLOT_FACE = theme["PLOT_FACE"]
    GRID = theme["GRID"]
    DISABLED_BG = theme["DISABLED_BG"]
    DISABLED_TEXT = theme["DISABLED_TEXT"]
    DISABLED_BORDER = theme["DISABLED_BORDER"]
    BUTTON_BORDER = theme["BUTTON_BORDER"]
    BUTTON_CHECKED_BG = theme["BUTTON_CHECKED_BG"]
    INPUT_BORDER = theme["INPUT_BORDER"]


def active_theme() -> dict[str, str]:
    return THEMES[_ACTIVE_THEME_NAME]


_apply_theme_globals(active_theme())


def set_active_theme(name: str) -> dict[str, str]:
    global _ACTIVE_THEME_NAME
    if name not in THEMES:
        raise ValueError(f"Unknown theme '{name}'")
    _ACTIVE_THEME_NAME = name
    theme = active_theme()
    _apply_theme_globals(theme)
    return theme


def build_app_icon() -> QIcon | None:
    try:
        image = QImage(str(LOGO_PATH))
        if image.isNull():
            return None
        width = image.width()
        height = image.height()
        min_x, min_y = width, height
        max_x, max_y = -1, -1
        for y in range(height):
            for x in range(width):
                if image.pixelColor(x, y).alpha() > 10:
                    if x < min_x:
                        min_x = x
                    if x > max_x:
                        max_x = x
                    if y < min_y:
                        min_y = y
                    if y > max_y:
                        max_y = y
        if min_x > max_x or min_y > max_y:
            cropped = image
        else:
            rect = QRect(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)
            cropped = image.copy(rect)
        size = max(cropped.width(), cropped.height())
        square = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        square.fill(Qt.transparent)
        painter = QPainter(square)
        try:
            painter.drawImage(
                (size - cropped.width()) // 2,
                (size - cropped.height()) // 2,
                cropped
            )
        finally:
            painter.end()
        base_pix = QPixmap.fromImage(square)
        icon = QIcon()
        for target in (16, 32, 64, 128, 256):
            icon.addPixmap(base_pix.scaled(target, target, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        return icon
    except Exception as e:
        _log_gui_exception(e, context="build_app_icon")
        return None

def build_stylesheet(font_family: str | None, scale: float = 1.0) -> str:
    s = max(0.7, min(scale, 2.0))
    family_rule = f"font-family: '{font_family}';" if font_family else ""
    font_pt = int(round(11 * s))
    status_pt = int(round(10 * s))
    btn_py = int(round(6 * s)); btn_px = int(round(10 * s))
    inp_py = int(round(4 * s)); inp_px = int(round(6 * s))
    tab_py = int(round(6 * s))
    tab_left_px = int(round(12 * s))
    tab_right_px = int(round(24 * s))
    tab_min_w = int(round(120 * s))
    return f"""
* {{ background: {BG}; color: {TEXT}; font-size: {font_pt}pt; {family_rule} }}
QWidget {{ background: {BG}; }}
QLabel#StatusLine {{ color: {TEXT}; font-size: {status_pt}pt; }}
QPushButton {{ background: {MID}; border:1px solid {BUTTON_BORDER}; padding:{btn_py}px {btn_px}px; border-radius:0px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:checked {{ background:{BUTTON_CHECKED_BG}; border-color:{ACCENT}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background:{MID}; border:1px solid {INPUT_BORDER}; padding:{inp_py}px {inp_px}px; border-radius:0px; }}
/* Disabled state — strongly greyed out for clarity */
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    background: {DISABLED_BG};
    color: {DISABLED_TEXT};
    border: 1px solid {DISABLED_BORDER};
}}
QLabel:disabled {{ color: {DISABLED_TEXT}; }}
QTabWidget::pane {{ border: 0px; }}
QTabBar::tab {{
    padding: {tab_py}px {tab_right_px}px {tab_py}px {tab_left_px}px;
    margin: 2px;
    border: 0px;
    border-radius: 0px;
    min-width: {tab_min_w}px;
    background: {BG};
    color: {TEXT};
    text-align: left;
}}
QTabBar::tab:selected {{
    background: {MID};
    color: {TEXT};
    border-bottom: 2px solid {ACCENT};
    text-align: left;
}}
QTabBar::tab:!selected {{
    background: {BG};
    border-bottom: 2px solid transparent;
    text-align: left;
}}
QTabBar::close-button {{
    border: none;
    background: transparent;
    margin: 0px;
    padding: 0px;
}}
QTabBar::close-button:hover {{
    background: {ACCENT};
    color: {BG};
    border-radius: 0px;
}}
"""

def _apply_global_font(app: QApplication):
    """Load Typestar OCR and apply as app default if present."""
    global _FONT_FAMILY
    fid = QFontDatabase.addApplicationFont(str(FONT_PATH))
    if fid != -1:
        fams = QFontDatabase.applicationFontFamilies(fid)
        if fams:
            _FONT_FAMILY = fams[0]
            app.setFont(QFont(_FONT_FAMILY, 11))

def _log_gui_exception(e: Exception, context: str = "GUI operation") -> None:
    APP_LOGGER.error(f"Unhandled GUI exception in {context}: {e}", exc_info=True)

def apply_matplotlib_theme(font_family: str | None, theme: dict[str, str]):
    """Make Matplotlib match the NEMESIS UI theme."""
    mpl_family = None
    try:
        if FONT_PATH.exists():
            font_manager.fontManager.addfont(str(FONT_PATH))
            mpl_family = font_manager.FontProperties(fname=str(FONT_PATH)).get_name()
    except Exception:
        mpl_family = None
    # Prefer the actual family name discovered by Matplotlib for the Typestar file
    family = mpl_family or font_family or "DejaVu Sans"
    base_size = 10
    tick_size = max(8, base_size - 1)
    face = theme.get("PLOT_FACE", theme.get("MID", MID))
    text_color = theme.get("TEXT", TEXT)
    grid_color = theme.get("GRID", GRID)
    mpl.rcParams.update({
        "font.family": [family],
        "font.sans-serif": [family, "DejaVu Sans", "Arial"],
        "font.size": base_size,
        "axes.titlesize": base_size,
        "axes.labelsize": base_size,
        "xtick.labelsize": tick_size,
        "ytick.labelsize": tick_size,
        "figure.facecolor": face,
        "axes.facecolor": face,
        "axes.edgecolor": text_color,
        "axes.labelcolor": text_color,
        "xtick.color": text_color,
        "ytick.color": text_color,
        "text.color": text_color,
        "figure.autolayout": True,
        "grid.color": grid_color,
        "grid.linestyle": ":",
        "grid.alpha": 0.8,
        "axes.titleweight": "regular",
        "axes.titlepad": 8,
        "axes.grid": False,
        "savefig.facecolor": face,
        "savefig.edgecolor": face,
    })


def _set_macos_titlebar_appearance(widget: QWidget, color: QColor) -> bool:
    """Force a dark titlebar on macOS when the Fusion palette looks too light."""
    if sys.platform != "darwin":
        return False
    try:
        from ctypes import cdll, util, c_void_p, c_char_p, c_bool, c_double
    except Exception as e:
        APP_LOGGER.error(f"Failed to import ctypes in _set_macos_titlebar_appearance: {e}")
        return False
    try:
        objc = cdll.LoadLibrary(util.find_library('objc'))
    except Exception as e:
        APP_LOGGER.error(f"Failed to load objc library in _set_macos_titlebar_appearance: {e}")
        return False

    def _cls(name: bytes) -> c_void_p:
        objc.objc_getClass.restype = c_void_p
        objc.objc_getClass.argtypes = [c_char_p]
        return objc.objc_getClass(name)

    def _sel(name: bytes) -> c_void_p:
        objc.sel_registerName.restype = c_void_p
        objc.sel_registerName.argtypes = [c_char_p]
        return objc.sel_registerName(name)

    def _msg(receiver: c_void_p, selector: c_void_p, *args, restype=c_void_p, argtypes=None):
        if argtypes is None:
            argtypes = [c_void_p] * len(args)
        objc.objc_msgSend.restype = restype
        objc.objc_msgSend.argtypes = [c_void_p, c_void_p] + list(argtypes)
        return objc.objc_msgSend(receiver, selector, *args)

    try:
        view = c_void_p(int(widget.winId()))
    except Exception as e:
        APP_LOGGER.error(f"Failed to get widget window ID in _set_macos_titlebar_appearance: {e}")
        return False
    if not view.value:
        return False
    window = _msg(view, _sel(b"window"))
    if not window:
        return False

    NSString = _cls(b"NSString")
    stringWithUTF8String = _sel(b"stringWithUTF8String:")
    NSAppearance = _cls(b"NSAppearance")
    appearanceNamed = _sel(b"appearanceNamed:")
    ns_name = _msg(NSString, stringWithUTF8String, c_char_p(b"NSAppearanceNameVibrantDark"), restype=c_void_p, argtypes=[c_char_p])
    if not ns_name:
        return False
    appearance = _msg(NSAppearance, appearanceNamed, ns_name)
    if not appearance:
        return False

    NSColor = _cls(b"NSColor")
    colorWithSRGB = _sel(b"colorWithSRGBRed:green:blue:alpha:")
    try:
        r = float(max(0.0, min(1.0, color.redF())))
        g = float(max(0.0, min(1.0, color.greenF())))
        b = float(max(0.0, min(1.0, color.blueF())))
        ns_color = _msg(NSColor, colorWithSRGB,
                        c_double(r), c_double(g), c_double(b), c_double(1.0),
                        restype=c_void_p,
                        argtypes=[c_double, c_double, c_double, c_double])
    except Exception as e:
        APP_LOGGER.error(f"Error converting QColor to NSColor in _set_macos_titlebar_appearance: {e}")
        ns_color = None

    try:
        _msg(window, _sel(b"setAppearance:"), appearance, restype=None, argtypes=[c_void_p])
        # Prevent automatic accent recoloring so it stays dark
        _msg(window, _sel(b"setTitlebarAppearsTransparent:"), c_bool(False), restype=None, argtypes=[c_bool])
        if ns_color:
            _msg(window, _sel(b"setBackgroundColor:"), ns_color, restype=None, argtypes=[c_void_p])
    except Exception as e:
        APP_LOGGER.error(f"Error applying appearance in _set_macos_titlebar_appearance: {e}")
        return False
    return True

class LiveChart:
    PALETTES = HEATMAP_PALETTES
    def __init__(self, font_family: str | None, theme: dict[str, str]):
        self.font_family = font_family
        self.theme = theme
        apply_matplotlib_theme(font_family, theme)
        self.fig, (self.ax_top, self.ax_bot) = plt.subplots(
            2, 1, sharex=True, figsize=(6.2, 3.2),
            gridspec_kw={"height_ratios": [1, 5]}
        )
        # Compact layout and tighter suptitle position to reduce top padding
        try:
            self.fig.subplots_adjust(top=0.82, bottom=0.18, left=0.10, right=0.98, hspace=0.12)
        except Exception as e:
            _log_gui_exception(e, context="LiveChart.__init__ subplots_adjust")
        self.canvas = FigureCanvas(self.fig)
        # Reduce minimum height so the preview keeps priority
        self.canvas.setMinimumHeight(160)
        try:
            # Canvas transparent; outer QFrame draws the border/background
            self.canvas.setStyleSheet("background: transparent;")
        except Exception as e:
            APP_LOGGER.error(f"Error setting canvas stylesheet in LiveChart.__init__: {e}")
        self.times_sec: list[float] = []
        self._time_unit: str = "minutes"
        self._last_max_elapsed_sec: float = 0.0
        self.replay_targets: list[float] = []
        self.replay_completed: int = 0
        self.heatmap_palette: str = HEATMAP_PALETTES[0]
        self._heatmap_cbar = None
        self._heatmap_im = None
        self._heatmap_active = False
        self._heatmap_listeners: list[Callable[[bool], None]] = []
        self._long_run_active: bool = False
        self._long_run_listeners: list[Callable[[bool], None]] = []
        self._long_run_view: str = "taps"
        self.contraction_heatmap: np.ndarray | None = None
        self._init_axes()

    def _init_axes(self):
        text_color = self.color("TEXT")
        self.fig.suptitle("Stentor Habituation to Stimuli", fontsize=10, color=text_color, y=0.98)
        try:
            self.fig.patch.set_alpha(0.0)
            self.fig.patch.set_facecolor('none')
        except Exception as e:
            APP_LOGGER.error(f"Error setting figure patch properties in LiveChart._init_axes: {e}")
        self._configure_standard_axes(0.0)
        self.canvas.draw_idle()

    def reset(self):
        self.times_sec.clear()
        self.replay_completed = min(self.replay_completed, len(self.replay_targets))
        self._last_max_elapsed_sec = 0.0
        self._long_run_view = "taps"
        self.contraction_heatmap = None
        self._clear_heatmap_artists()
        self._configure_standard_axes(0.0)
        self._set_long_mode(False)
        self._set_heatmap_state(False)
        self.canvas.draw_idle()

    def add_tap(self, t_since_start_s: float):
        self.times_sec.append(float(t_since_start_s))
        self._redraw()

    def set_times(self, times_seconds: Sequence[float]):
        self.times_sec = [float(v) for v in times_seconds]
        self._redraw()

    def set_replay_targets(self, targets: Sequence[float] | None):
        self.replay_targets = [] if targets is None else [float(v) for v in targets]
        self.replay_completed = 0
        self._redraw()

    def mark_replay_progress(self, completed: int):
        if completed < 0:
            completed = 0
        if completed > len(self.replay_targets):
            completed = len(self.replay_targets)
        self.replay_completed = completed
        self._redraw()

    def clear_replay_targets(self):
        self.replay_targets = []
        self.replay_completed = 0
        self._redraw()

    def set_contraction_heatmap(self, matrix: Sequence[Sequence[float]] | None):
        if matrix is None:
            self.contraction_heatmap = None
        else:
            arr = np.asarray(matrix, dtype=float)
            if arr.ndim != 2 or arr.size == 0:
                self.contraction_heatmap = None
            else:
                self.contraction_heatmap = arr
        if self._long_run_view == "contraction" and self._long_run_active:
            self._redraw()

    def set_long_run_view(self, view: str):
        view_key = (view or "").strip().lower()
        if view_key not in {"taps", "contraction"}:
            return
        if view_key == self._long_run_view:
            return
        self._long_run_view = view_key
        self._redraw()

    def long_run_view(self) -> str:
        return self._long_run_view

    def long_run_active(self) -> bool:
        return self._long_run_active

    def add_long_mode_listener(self, callback: Callable[[bool], None]) -> None:
        if callback in self._long_run_listeners:
            try:
                callback(self._long_run_active)
            except Exception:
                pass
            return
        self._long_run_listeners.append(callback)
        try:
            callback(self._long_run_active)
        except Exception:
            pass


    def _set_long_mode(self, active: bool) -> None:
        if self._long_run_active == active:
            return
        self._long_run_active = active
        if not active:
            self._long_run_view = "taps"
            self._clear_heatmap_artists()
        for callback in list(self._long_run_listeners):
            try:
                callback(active)
            except Exception:
                continue

    def _redraw(self):
        max_elapsed_sec_actual = max(self.times_sec) if self.times_sec else 0.0
        max_elapsed_sec_script = max(self.replay_targets) if self.replay_targets else 0.0
        max_elapsed_sec = max(max_elapsed_sec_actual, max_elapsed_sec_script)
        if max_elapsed_sec <= 0:
            self._configure_standard_axes(0.0)
            self._set_long_mode(False)
            self._set_heatmap_state(False)
            self.canvas.draw_idle()
            return

        long_mode = max_elapsed_sec >= 3 * 3600
        heatmap_on = False
        if long_mode:
            if self._long_run_view == "contraction":
                self._configure_long_heatmap_axes()
                self._draw_contraction_heatmap()
                heatmap_on = True
            else:
                self._configure_long_raster_axes(max_elapsed_sec)
                self._draw_long_raster(max_elapsed_sec)
        else:
            self._configure_standard_axes(max_elapsed_sec)
            self._draw_standard_raster()

        self._set_long_mode(long_mode)
        self._set_heatmap_state(heatmap_on)
        self.canvas.draw_idle()

    def _configure_standard_axes(self, max_elapsed_sec: float) -> None:
        text_color = self.color("TEXT")
        ax_top = self.ax_top
        ax_bot = self.ax_bot

        ax_top.cla()
        ax_bot.cla()
        try:
            ax_top.set_facecolor('none')
            ax_bot.set_facecolor('none')
        except Exception:
            pass

        self._clear_heatmap_artists()

        ax_bot.set_visible(True)
        ax_top.set_ylabel("Taps", color=text_color)
        ax_top.set_yticks([])
        ax_top.tick_params(axis='x', colors=text_color)
        ax_top.tick_params(axis='y', colors=text_color)
        for spine in ax_top.spines.values():
            spine.set_color(text_color)
        ax_top.set_title("")

        ax_bot.set_ylabel("% Contracted")
        ax_bot.set_ylim(-5, 105)
        ax_bot.yaxis.set_major_formatter(plt.FuncFormatter("{:.0f}%".format))
        ax_bot.tick_params(axis='x', colors=text_color)
        ax_bot.tick_params(axis='y', colors=text_color)
        for spine in ax_bot.spines.values():
            spine.set_color(text_color)
        ax_bot.set_title("")

        minutes_span = max_elapsed_sec / 60.0 if max_elapsed_sec else 0.0
        default_limit = 60.0
        target_limit = minutes_span * 1.05 if minutes_span else default_limit
        max_unit_val = max(default_limit, min(180.0, target_limit))

        major = MultipleLocator(10)
        minor = MultipleLocator(1)
        ax_top.xaxis.set_major_locator(major)
        ax_top.xaxis.set_minor_locator(minor)
        ax_bot.xaxis.set_major_locator(MultipleLocator(10))
        ax_bot.xaxis.set_minor_locator(MultipleLocator(1))
        ax_bot.set_xlabel("Time (minutes)")
        ax_top.grid(True, which="major", axis="x", linestyle=":", alpha=0.9)
        ax_top.grid(True, which="minor", axis="x", linestyle=":", alpha=0.35)
        ax_bot.grid(True, which="major", axis="x", linestyle=":", alpha=0.9)
        ax_bot.grid(True, which="minor", axis="x", linestyle=":", alpha=0.35)

        ax_top.set_xlim(0, max_unit_val)
        ax_bot.set_xlim(0, max_unit_val)
        self._time_unit = "minutes"
        self._last_max_elapsed_sec = max_elapsed_sec
        try:
            self.fig.subplots_adjust(top=0.82, bottom=0.18, left=0.10, right=0.98, hspace=0.12)
            self.fig.suptitle("Stentor Habituation to Stimuli", fontsize=10, color=text_color, y=0.98)
        except Exception as e:
            APP_LOGGER.error(f"Error adjusting subplots or suptitle in LiveChart._redraw: {e}")

    def _configure_long_raster_axes(self, max_elapsed_sec: float) -> None:
        text_color = self.color("TEXT")
        ax_top = self.ax_top
        ax_bot = self.ax_bot

        ax_top.cla()
        ax_bot.cla()
        try:
            ax_top.set_facecolor('none')
            ax_bot.set_facecolor('none')
        except Exception:
            pass

        ax_bot.set_visible(False)
        ax_bot.set_axis_off()

        ax_top.set_visible(True)
        ax_top.set_ylabel("Hour")
        ax_top.tick_params(axis='x', colors=text_color)
        ax_top.tick_params(axis='y', colors=text_color)
        for spine in ax_top.spines.values():
            spine.set_color(text_color)

        self._clear_heatmap_artists()

        self._time_unit = "hours"
        self._last_max_elapsed_sec = max_elapsed_sec
        try:
            self.fig.subplots_adjust(top=0.90, bottom=0.10, left=0.10, right=0.98)
            self.fig.suptitle("Tap raster by hour", fontsize=10, color=text_color, y=0.97)
        except Exception as e:
            APP_LOGGER.error(f"Error adjusting subplots or suptitle in LiveChart._redraw (long raster): {e}")

    def _configure_long_heatmap_axes(self) -> None:
        text_color = self.color("TEXT")
        ax_top = self.ax_top
        ax_bot = self.ax_bot

        ax_top.cla()
        ax_bot.cla()
        try:
            ax_top.set_facecolor('none')
            ax_bot.set_facecolor('none')
        except Exception:
            pass

        ax_bot.set_visible(False)
        ax_bot.set_axis_off()

        ax_top.set_visible(True)
        ax_top.tick_params(axis='x', colors=text_color)
        ax_top.tick_params(axis='y', colors=text_color)
        for spine in ax_top.spines.values():
            spine.set_color(text_color)

        self._time_unit = "hours"
        try:
            self.fig.subplots_adjust(top=0.90, bottom=0.10, left=0.10, right=0.92)
            self.fig.suptitle("Contraction heatmap", fontsize=10, color=text_color, y=0.97)
        except Exception as e:
            APP_LOGGER.error(f"Error adjusting subplots or suptitle in LiveChart._redraw (long heatmap): {e}")

    def _draw_standard_raster(self) -> None:
        text_color = self.color("TEXT")
        accent_color = self.color("ACCENT")
        remaining_color = self.color("SUBTXT")

        factor = 60.0
        ts_unit = [t / factor for t in self.times_sec]
        highlighted = [t for i, t in enumerate(ts_unit) if (i + 1) % 10 == 0]
        regular = [t for i, t in enumerate(ts_unit) if (i + 1) % 10 != 0]

        if self.replay_targets:
            replay_unit = [t / factor for t in self.replay_targets]
            completed_unit = replay_unit[: self.replay_completed]
            remaining_unit = replay_unit[self.replay_completed :]
            if remaining_unit:
                self.ax_top.eventplot(
                    remaining_unit,
                    orientation="horizontal",
                    colors=remaining_color,
                    linewidth=0.8,
                )
            if completed_unit and not self.times_sec:
                self.ax_top.eventplot(
                    completed_unit,
                    orientation="horizontal",
                    colors=accent_color,
                    linewidth=1.0,
                )

        if regular:
            self.ax_top.eventplot(regular, orientation="horizontal", colors=text_color, linewidth=0.9)
        if highlighted:
            self.ax_top.eventplot(highlighted, orientation="horizontal", colors=accent_color, linewidth=1.6)

    def _draw_long_raster(self, max_elapsed_sec: float) -> None:
        ax = self.ax_top
        text_color = self.color("TEXT")
        accent_color = self.color("ACCENT")
        pending_color = self.color("SUBTXT")

        taps_actual = np.asarray(self.times_sec, dtype=float)
        taps_script = np.asarray(self.replay_targets, dtype=float) if self.replay_targets else np.empty(0, dtype=float)

        taps_actual = taps_actual[np.isfinite(taps_actual)]
        taps_actual = taps_actual[taps_actual >= 0.0]
        taps_script = taps_script[np.isfinite(taps_script)]
        taps_script = taps_script[taps_script >= 0.0]

        reference = taps_actual if taps_actual.size else taps_script
        if reference.size == 0:
            ax.text(
                0.5,
                0.5,
                "No tap data",
                color=self.color("SUBTXT"),
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
            ax.set_axis_off()
            return

        max_sec = max(max_elapsed_sec, float(reference.max()))
        hours = max(1, int(math.ceil((max_sec + 1e-9) / 3600.0)))
        line_offsets = np.arange(hours)

        regular_groups = [[] for _ in range(hours)]
        highlight_groups = [[] for _ in range(hours)]
        pending_groups = [[] for _ in range(hours)]

        for idx, value in enumerate(taps_actual):
            hour = min(int(value // 3600), hours - 1)
            minute_within_hour = (value % 3600.0) / 60.0
            if (idx + 1) % 10 == 0:
                highlight_groups[hour].append(minute_within_hour)
            else:
                regular_groups[hour].append(minute_within_hour)

        if taps_script.size:
            for idx, value in enumerate(taps_script):
                if idx < self.replay_completed:
                    continue
                hour = min(int(value // 3600), hours - 1)
                minute_within_hour = (value % 3600.0) / 60.0
                pending_groups[hour].append(minute_within_hour)

        ax.cla()
        ax.set_visible(True)
        ax.set_ylabel("Hour")
        ax.set_xlabel("Minute within hour")
        ax.tick_params(axis='x', colors=text_color)
        ax.tick_params(axis='y', colors=text_color)
        for spine in ax.spines.values():
            spine.set_color(text_color)

        if any(group for group in pending_groups):
            ax.eventplot(
                pending_groups,
                lineoffsets=line_offsets,
                linelengths=0.7,
                linewidth=0.8,
                colors=pending_color,
            )
        if any(group for group in regular_groups):
            ax.eventplot(
                regular_groups,
                lineoffsets=line_offsets,
                linelengths=0.7,
                linewidth=0.9,
                colors=text_color,
            )
        if any(group for group in highlight_groups):
            ax.eventplot(
                highlight_groups,
                lineoffsets=line_offsets,
                linelengths=0.7,
                linewidth=1.3,
                colors=accent_color,
            )

        ax.set_ylim(-0.5, hours - 0.5)
        ax.set_yticks(line_offsets)
        ax.set_yticklabels([f"H{h:02d}" for h in range(hours)])
        ax.invert_yaxis()
        ax.set_xlim(-0.5, 59.5)
        ax.set_xticks(np.arange(0, 60, 5))
        ax.grid(axis="x", which="major", linestyle=":", alpha=0.25)

    def _draw_contraction_heatmap(self) -> None:
        ax = self.ax_top
        text_color = self.color("TEXT")

        ax.cla()
        ax.set_visible(True)

        data = self.contraction_heatmap
        try:
            self.fig.suptitle(f"Contraction heatmap — {self.heatmap_palette.title()}", fontsize=10, color=text_color, y=0.97)
        except Exception as e:
            APP_LOGGER.error(f"Error setting suptitle in LiveChart._redraw: {e}")
        if data is None or data.size == 0:
            ax.text(
                0.5,
                0.5,
                "No contraction data",
                color=self.color("SUBTXT"),
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
            ax.set_axis_off()
            self._clear_heatmap_artists()
            return

        matrix = np.asarray(data, dtype=float)
        if matrix.ndim != 2 or matrix.shape[1] == 0:
            ax.text(
                0.5,
                0.5,
                "Invalid contraction matrix",
                color=self.color("SUBTXT"),
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
            ax.set_axis_off()
            self._clear_heatmap_artists()
            return

        hours = matrix.shape[0]
        cmap_name = self.heatmap_palette if self.heatmap_palette in HEATMAP_PALETTES else HEATMAP_PALETTES[0]
        img = ax.imshow(
            matrix,
            aspect="auto",
            interpolation="nearest",
            cmap=cmap_name,
            vmin=0.0,
            vmax=100.0,
        )
        self._heatmap_im = img
        if self._heatmap_cbar is None:
            self._heatmap_cbar = self.fig.colorbar(img, ax=ax, pad=0.02, fraction=0.05)
        else:
            try:
                self._heatmap_cbar.update_normal(img)
            except Exception:
                self._heatmap_cbar = self.fig.colorbar(img, cax=self._heatmap_cbar.ax)

        try:
            self._heatmap_cbar.set_label("Contraction %", color=text_color)
            self._heatmap_cbar.ax.yaxis.set_tick_params(color=text_color)
            plt.setp(self._heatmap_cbar.ax.get_yticklabels(), color=text_color)
        except Exception:
            pass

        ax.set_ylim(-0.5, hours - 0.5)
        ax.set_yticks(np.arange(hours))
        ax.set_yticklabels([f"H{h:02d}" for h in range(hours)])
        ax.invert_yaxis()
        ax.set_xlim(-0.5, 59.5)
        ax.set_xticks(np.arange(0, 60, 5))
        ax.set_xlabel("Minute within hour")
        ax.set_ylabel("Hour")
        for spine in ax.spines.values():
            spine.set_color(text_color)
        ax.tick_params(axis='x', colors=text_color)
        ax.tick_params(axis='y', colors=text_color)
        for x in range(0, 60, 5):
            ax.axvline(x - 0.5, color=self.color("GRID"), linewidth=0.35, alpha=0.2)

    def set_heatmap_palette(self, palette: str) -> None:
        candidate = (palette or "").strip().lower()
        if candidate not in HEATMAP_PALETTES:
            candidate = HEATMAP_PALETTES[0]
        if candidate == self.heatmap_palette:
            return
        self.heatmap_palette = candidate
        if self._heatmap_active:
            try:
                if self._heatmap_im is not None:
                    self._heatmap_im.set_cmap(candidate)
                    if self._heatmap_cbar is not None:
                        self._heatmap_cbar.update_normal(self._heatmap_im)
                        self._heatmap_cbar.set_label("Contraction %", color=self.color("TEXT"))
                        self._heatmap_cbar.ax.yaxis.set_tick_params(color=self.color("TEXT"))
                        plt.setp(self._heatmap_cbar.ax.get_yticklabels(), color=self.color("TEXT"))
                else:
                    self._redraw()
                try:
                    self.fig.suptitle(f"Contraction heatmap — {self.heatmap_palette.title()}", fontsize=10, color=self.color("TEXT"), y=0.97)
                except Exception:
                    pass
                self.canvas.draw_idle()
            except Exception:
                self._redraw()

    def heatmap_active(self) -> bool:
        return self._heatmap_active

    def save(self, path: str, dpi: int = 300) -> None:
        self.fig.savefig(path, dpi=dpi, bbox_inches='tight')

    def color(self, key: str) -> str:
        if key in self.theme:
            return self.theme[key]
        return active_theme().get(key, globals().get(key, "#ffffff"))

    def set_theme(self, theme: dict[str, str]):
        self.theme = theme
        apply_matplotlib_theme(self.font_family, theme)
        if self.times_sec or self.replay_targets:
            self._redraw()
        else:
            if self._long_run_active:
                if self._long_run_view == "contraction":
                    self._configure_long_heatmap_axes()
                    self._draw_contraction_heatmap()
                else:
                    self._configure_long_raster_axes(self._last_max_elapsed_sec)
            else:
                self._configure_standard_axes(self._last_max_elapsed_sec)
            self._set_long_mode(self._long_run_active)
            self._set_heatmap_state(self._long_run_active and self._long_run_view == "contraction")
            self.canvas.draw_idle()

    def add_heatmap_listener(self, callback: Callable[[bool], None]) -> None:
        if callback in self._heatmap_listeners:
            try:
                callback(self._heatmap_active)
            except Exception:
                pass
            return
        self._heatmap_listeners.append(callback)
        try:
            callback(self._heatmap_active)
        except Exception:
            pass

    def _set_heatmap_state(self, active: bool) -> None:
        if self._heatmap_active == active:
            return
        self._heatmap_active = active
        for callback in list(self._heatmap_listeners):
            try:
                callback(active)
            except Exception:
                continue

    def _clear_heatmap_artists(self) -> None:
        if self._heatmap_cbar is not None:
            try:
                self._heatmap_cbar.ax.remove()
            except Exception:
                pass
        self._heatmap_cbar = None
        self._heatmap_im = None

class ZoomView(QGraphicsView):
    firstFrame = Signal()
    def __init__(self, bg_color: str = "#000", parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pix = QGraphicsPixmapItem()
        self._scene.addItem(self._pix)
        # Visuals
        try:
            self.setBackgroundBrush(QColor(bg_color))
        except Exception:
            pass
        self._bg_color = bg_color
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        # Ensure full repaint on first draw to avoid seams on some GPUs
        try:
            self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        except Exception:
            pass
        # Scrollbars auto-hide behavior
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.horizontalScrollBar().setVisible(False)
        self.verticalScrollBar().setVisible(False)
        # Ensure the view never paints its own frame/border; keep viewport transparent
        self._base_qss = (
            "QGraphicsView { border: none; background: transparent; }\n"
            "QGraphicsView::viewport { background: transparent; border: none; }\n"
        )
        self._scrollbar_qss = (
            "QScrollBar:vertical { width: 6px; background: transparent; margin: 2px; }\n"
            f"QScrollBar::handle:vertical {{ background: {SCROLLBAR}; border-radius: 0px; }}\n"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; background: transparent; }\n"
            "QScrollBar:horizontal { height: 6px; background: transparent; margin: 2px; }\n"
            f"QScrollBar::handle:horizontal {{ background: {SCROLLBAR}; border-radius: 0px; }}\n"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; background: transparent; }\n"
        )
        try:
            self.setStyleSheet(self._base_qss)
            self.viewport().setStyleSheet("background: transparent; border: none;")
        except Exception:
            pass
        self._scrollbar_style_applied = False
        # State
        self._has_image = False
        self._zoom = 1.0
        self._min_zoom = 0.2
        self._max_zoom = 8.0
        self._emitted_first = False
        self._last_pix_size = QSize()
        self._pending_refit = False
        self._sb_timer = QTimer(self)
        self._sb_timer.setSingleShot(True)
        self._sb_timer.timeout.connect(self._hide_scrollbars)
        # Enable pinch gesture across platforms
        try:
            self.grabGesture(Qt.PinchGesture)
        except Exception:
            pass

    def _build_scrollbar_qss(self, color: str) -> str:
        return (
            "QScrollBar:vertical { width: 6px; background: transparent; margin: 2px; }\n"
            f"QScrollBar::handle:vertical {{ background: {color}; border-radius: 0px; }}\n"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; background: transparent; }\n"
            "QScrollBar:horizontal { height: 6px; background: transparent; margin: 2px; }\n"
            f"QScrollBar::handle:horizontal {{ background: {color}; border-radius: 0px; }}\n"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; background: transparent; }\n"
        )

    def set_theme(self, theme: dict[str, str]):
        bg_color = theme.get("BG", self._bg_color)
        try:
            self.setBackgroundBrush(QColor(bg_color))
        except Exception as e:
            APP_LOGGER.error(f"Error setting background brush in ZoomView: {e}")
        try:
            if self._scrollbar_style_applied:
                self.setStyleSheet(self._base_qss + self._scrollbar_qss)
            else:
                self.setStyleSheet(self._base_qss)
            self.viewport().setStyleSheet("background: transparent; border: none;")
        except Exception:
            pass

    def set_image(self, pix: QPixmap):
        has_pix = hasattr(pix, "isNull") and not pix.isNull()
        size_changed = False
        if has_pix:
            new_size = pix.size()
            if new_size != self._last_pix_size:
                self._last_pix_size = QSize(new_size)
                size_changed = True
        else:
            self._last_pix_size = QSize()
        self._pix.setPixmap(pix)
        if not has_pix:
            self._has_image = False
            return
        needs_refit = False
        if self._pending_refit:
            needs_refit = True
        elif not self._has_image:
            needs_refit = True
        elif size_changed and abs(self._zoom - 1.0) < 1e-3:
            needs_refit = True
        self._has_image = True
        if needs_refit:
            self._refit_view()
        self._pending_refit = False
        # Emit firstFrame once, on the first real pixmap
        if not self._emitted_first and hasattr(pix, 'isNull') and not pix.isNull():
            self._emitted_first = True
            try:
                self.firstFrame.emit()
            except Exception:
                pass
        # Style thin scrollbars (once) without reintroducing a view border
        if not self._scrollbar_style_applied:
            try:
                self.setStyleSheet(self._base_qss + self._scrollbar_qss)
                self.viewport().setStyleSheet("background: transparent; border: none;")
            except Exception as e:
                APP_LOGGER.error(f"Error applying scrollbar style in ZoomView.set_image: {e}")
            self._scrollbar_style_applied = True

    def reset_first_frame(self):
        """Allow the next real pixmap to emit firstFrame again and refit view."""
        current = self._pix.pixmap()
        has_pix = hasattr(current, "isNull") and not current.isNull() if current is not None else False
        self._emitted_first = False
        self._pending_refit = True
        self._last_pix_size = QSize()
        if has_pix:
            self._has_image = True
        else:
            self._has_image = False
            try:
                self.resetTransform()
            except Exception as e:
                APP_LOGGER.error(f"Error resetting transform in ZoomView.reset_first_frame: {e}")
            self._zoom = 1.0

    def _zoom_by(self, factor: float):
        new_zoom = max(self._min_zoom, min(self._zoom * factor, self._max_zoom))
        if abs(new_zoom - self._zoom) < 1e-6:
            return
        real = new_zoom / self._zoom
        self.scale(real, real)
        self._zoom = new_zoom
        self._show_scrollbars_temporarily()

    def event(self, ev):
        # macOS: QNativeGestureEvent for pinch
        if ev.type() == QEvent.NativeGesture:
            try:
                # Some bindings expose gestureType/value on the event
                gtype = getattr(ev, 'gestureType', None)
                if callable(gtype):
                    gtype = gtype()
                val = getattr(ev, 'value', None)
                if callable(val):
                    val = val()
            except Exception as e:
                APP_LOGGER.error(f"Error processing NativeGesture in ZoomView.event: {e}")
                pass
        # Cross-platform: QPinchGesture via gesture events
        if ev.type() == QEvent.Gesture:
            try:
                pinch = ev.gesture(Qt.PinchGesture)
                if pinch is not None:
                    sf = getattr(pinch, 'scaleFactor', None)
                    if callable(sf):
                        sf = sf()
                    if sf:
                        self._zoom_by(float(sf))
                        ev.accept()
                        return True
            except Exception as e:
                APP_LOGGER.error(f"Error processing QEvent.Gesture in ZoomView.event: {e}")
                pass
        return super().event(ev)

    def wheelEvent(self, e):
        # Two-finger scroll pans the view; scrollbars are hidden
        try:
            dx = e.angleDelta().x()
            dy = e.angleDelta().y()
            h = self.horizontalScrollBar()
            v = self.verticalScrollBar()
            if h: h.setValue(h.value() - dx)
            if v: v.setValue(v.value() - dy)
            e.accept()
            self._show_scrollbars_temporarily()
            return
        except Exception:
            pass
        return super().wheelEvent(e)

    def mousePressEvent(self, e):
        self._show_scrollbars_temporarily()
        return super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        self._show_scrollbars_temporarily()
        return super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._show_scrollbars_temporarily()
        return super().mouseReleaseEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Keep initial fit; if user has zoomed, don't override
        if self._has_image and abs(self._zoom - 1.0) < 1e-3:
            self._refit_view()

    def _refit_view(self):
        try:
            self.fitInView(self._pix, Qt.KeepAspectRatio)
            self._zoom = 1.0
        except Exception:
            pass
    def drawForeground(self, painter: QPainter, rect):
        super().drawForeground(painter, rect)
        if not self._has_image:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QColor(SUBTXT))
            font = painter.font()
            font.setPointSize(14)
            painter.setFont(font)
            text = "Video Preview"
            br = painter.boundingRect(rect, Qt.AlignCenter, text)
            painter.drawText(br, Qt.AlignCenter, text)
            painter.restore()
    def _show_scrollbars_temporarily(self):
        try:
            if self.horizontalScrollBar():
                self.horizontalScrollBar().setVisible(True)
            if self.verticalScrollBar():
                self.verticalScrollBar().setVisible(True)
            self._sb_timer.start(700)
        except Exception:
            pass

    def _hide_scrollbars(self):
        try:
            if self.horizontalScrollBar():
                self.horizontalScrollBar().setVisible(False)
            if self.verticalScrollBar():
                self.verticalScrollBar().setVisible(False)
        except Exception:
            pass


class PinnedPreviewWindow(QWidget):
    """Floating always-on-top window mirroring the live preview."""

    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NEMESIS Preview — Pop-out")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.Tool, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.view = ZoomView(bg_color=BG)
        self.container = AspectRatioContainer(self.view, 16, 9)
        layout.addWidget(self.container)
        self.resize(420, 236)

    def set_pixmap(self, pixmap: QPixmap):
        self.view.set_image(pixmap)

    def set_aspect(self, w: int, h: int):
        self.container.set_aspect(w, h)

    def set_border_visible(self, on: bool):
        self.container.set_border_visible(on)

    def reset_first_frame(self):
        self.view.reset_first_frame()

    def closeEvent(self, event):
        try:
            self.closed.emit()
        except Exception:
            pass
        super().closeEvent(event)





class FrameWorker(QObject):
    frameReady = Signal(object, int, float)
    error = Signal(str)
    stopped = Signal()

    def __init__(self, capture: video.VideoCapture, interval_ms: int = 33):
        super().__init__()
        self._capture = capture
        self._interval_s = max(0.005, float(interval_ms) / 1000.0)
        self._running = False
        self._thread: threading.Thread | None = None
        self._frame_idx = 0

    def _emit_safe(self, signal, *args):
        if not shiboken6.isValid(self):
            return
        try:
            signal.emit(*args)
        except RuntimeError:
            pass

    def _loop(self):
        interval = self._interval_s
        next_tick = time.perf_counter()
        while self._running:
            try:
                ok, frame = self._capture.read()
            except Exception as exc:
                self._emit_safe(self.error, f"Camera error: {exc}")
                break
            
            ts = time.monotonic()
            if ok and frame is not None:
                self._frame_idx += 1
                self._emit_safe(self.frameReady, frame, self._frame_idx, ts)
            
            if interval > 0:
                next_tick += interval
                sleep_for = next_tick - time.perf_counter()
                if sleep_for > 0:
                    time.sleep(sleep_for)
                else:
                    next_tick = time.perf_counter()
        
        self._running = False
        self._thread = None
        self._emit_safe(self.stopped)

    @Slot()
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="FrameWorkerLoop", daemon=True)
        self._thread.start()

    @Slot()
    def stop(self, wait_timeout: float = 1.0) -> bool:
        thread = self._thread
        if thread is None:
            self._running = False
            self._thread = None
            return True
        self._running = False
        if threading.current_thread() is thread:
            return False
        deadline = time.perf_counter() + max(0.0, wait_timeout)
        while thread.is_alive():
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break
            thread.join(timeout=min(0.1, remaining))
        if thread.is_alive():
            return False
        self._thread = None
        return True

    def is_alive(self) -> bool:
        thread = self._thread
        return bool(thread and thread.is_alive())


class AspectRatioContainer(QWidget):
    """Container that keeps a child at a fixed aspect ratio and only uses the
    height it needs for the current width (no wasted vertical space)."""
    def __init__(self, child: QWidget, ratio_w: int = 16, ratio_h: int = 9, parent=None):
        super().__init__(parent)
        self._child = child
        self._ratio_w = max(1, int(ratio_w))
        self._ratio_h = max(1, int(ratio_h))
        self._child.setParent(self)
        # Tell the layout system we compute height from width.
        sp = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)
        # Container draws its own border to avoid halos (match preview box styling)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._border_px = 1
        self._show_border = True
        self._apply_border_style()
        # Reasonable floor so it never collapses
        self.setMinimumSize(480, 270)

    # --- Qt "height-for-width" plumbing ---
    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w: int) -> int:
        return max(self.minimumHeight(), int(w * self._ratio_h / self._ratio_w))

    def sizeHint(self) -> QSize:
        # Width-driven; height will be computed via heightForWidth
        base_w = 720
        return QSize(base_w, self.heightForWidth(base_w))

    def set_aspect(self, w: int, h: int):
        try:
            w = int(w); h = int(h)
        except Exception:
            return
        if w > 0 and h > 0:
            self._ratio_w, self._ratio_h = w, h
            self.updateGeometry()

    def aspect_ratio(self) -> tuple[int, int]:
        return self._ratio_w, self._ratio_h

    def aspect_ratio(self) -> tuple[int, int]:
        return self._ratio_w, self._ratio_h

    def _apply_border_style(self, theme: dict[str, str] | None = None):
        palette = theme or active_theme()
        border_color = palette.get("BORDER", BORDER)
        bg = palette.get("BG", BG)
        border = f"{self._border_px}px solid {border_color}" if self._show_border else "none"
        self.setStyleSheet(f"background: {bg}; border: {border};")

    def set_border_visible(self, on: bool):
        self._show_border = bool(on)
        self._apply_border_style()
        # Relayout to account for changed effective border width
        try:
            self.updateGeometry()
        except Exception:
            pass
        self.update()

    def set_theme(self, theme: dict[str, str]):
        self._apply_border_style(theme)

    def border_visible(self) -> bool:
        return bool(getattr(self, "_show_border", True))

    def resizeEvent(self, e):
        # Fit child to inner rect inside border; if border hidden, don't subtract it
        b = self._border_px if getattr(self, "_show_border", True) else 0
        outer_w = self.width(); outer_h = self.height()
        W = max(1, outer_w - 2*b)
        H = max(1, outer_h - 2*b)
        target_w = W
        target_h = int(W * self._ratio_h / self._ratio_w)
        if target_h > H:
            target_h = H
            target_w = int(H * self._ratio_w / self._ratio_h)
        x = b + (W - target_w) // 2
        y = b + (H - target_h) // 2
        self._child.setGeometry(x, y, target_w, target_h)
        super().resizeEvent(e)


class AppZoomView(QGraphicsView):
    def __init__(self, bg_color: str = "#000", parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._proxy: QGraphicsProxyWidget | None = None
        self._content: QWidget | None = None
        self._base_size: QSize = QSize(0, 0)
        self._bg_color = bg_color
        # Visuals
        try:
            self.setBackgroundBrush(QColor(bg_color))
        except Exception:
            pass
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        try:
            self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        except Exception:
            pass
        try:
            self.viewport().setAttribute(Qt.WA_OpaquePaintEvent, True)
        except Exception:
            pass
        # Scrollbars: thin, auto-hide
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.horizontalScrollBar().setVisible(False)
        self.verticalScrollBar().setVisible(False)
        self._scrollbar_style = self._build_scrollbar_style(SCROLLBAR)
        self._apply_scrollbar_style()
        # State
        self._scale = 1.0
        self._min_scale = 1.0
        self._max_scale = 1.35
        self._sb_timer = QTimer(self)
        self._sb_timer.setSingleShot(True)
        self._sb_timer.timeout.connect(self._hide_scrollbars)
        self._content_fits = True
        try:
            self.grabGesture(Qt.PinchGesture)
        except Exception:
            pass

    def _build_scrollbar_style(self, color: str) -> str:
        return (
            "QScrollBar:vertical { width: 6px; background: transparent; margin: 2px; }\n"
            f"QScrollBar::handle:vertical {{ background: {color}; border-radius: 0px; }}\n"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; background: transparent; }\n"
            "QScrollBar:horizontal { height: 6px; background: transparent; margin: 2px; }\n"
            f"QScrollBar::handle:horizontal {{ background: {color}; border-radius: 0px; }}\n"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; background: transparent; }\n"
        )

    def _apply_scrollbar_style(self):
        try:
            self.setStyleSheet(self._scrollbar_style)
        except Exception:
            pass

    def set_theme(self, theme: dict[str, str]):
        bg_color = theme.get("BG", self._bg_color)
        try:
            self.setBackgroundBrush(QColor(bg_color))
        except Exception:
            pass
        self._bg_color = bg_color
        self._scrollbar_style = self._build_scrollbar_style(theme.get("SCROLLBAR", SCROLLBAR))
        self._apply_scrollbar_style()

    def set_content(self, w: QWidget):
        self._scene.clear()
        self._proxy = self._scene.addWidget(w)
        self._content = w
        self.resetTransform()
        self._scale = 1.0
        # Establish a fixed base content size to prevent reflow on zoom
        hint = w.sizeHint()
        if not hint.isValid() or hint.width() <= 0 or hint.height() <= 0:
            hint = w.minimumSizeHint()
        if not hint.isValid() or hint.width() <= 0 or hint.height() <= 0:
            hint = QSize(1200, 720)
        self._base_size = hint
        self._apply_geometry_to_proxy()
        self._update_interaction_state()

    def set_scale(self, s: float):
        s = max(self._min_scale, min(s, self._max_scale))
        self._scale = s
        self.resetTransform()
        self.scale(s, s)
        if s > 1.0 + 1e-3:
            self._show_scrollbars_temporarily()
        else:
            self._hide_scrollbars()
        self._update_interaction_state()

    def zoom_by(self, factor: float):
        self.set_scale(self._scale * factor)

    def event(self, ev):
        if ev.type() == QEvent.NativeGesture:
            try:
                gtype = getattr(ev, 'gestureType', None)
                if callable(gtype): gtype = gtype()
                val = getattr(ev, 'value', None)
                if callable(val): val = val()
                if gtype == Qt.NativeGestureType.Zoom and val is not None:
                    factor = 1.0 + (float(val) * 0.5)
                    factor = max(0.7, min(factor, 1.3))
                    self.zoom_by(factor)
                    ev.accept(); return True
            except Exception:
                pass
        if ev.type() == QEvent.Gesture:
            try:
                pinch = ev.gesture(Qt.PinchGesture)
                if pinch is not None:
                    sf = getattr(pinch, 'scaleFactor', None)
                    if callable(sf): sf = sf()
                    if sf:
                        self.zoom_by(float(sf))
                        ev.accept(); return True
            except Exception:
                pass
        return super().event(ev)

    def wheelEvent(self, e):
        # Two-finger scroll pans; reveal scrollbars temporarily
        try:
            h = self.horizontalScrollBar(); v = self.verticalScrollBar()
            has_scroll_range = ((h and h.maximum() > 0) or (v and v.maximum() > 0))
            if self._scale <= 1.0 + 1e-3 and not has_scroll_range:
                return super().wheelEvent(e)
            pd = e.pixelDelta(); ad = e.angleDelta()
            dx = pd.x() if not pd.isNull() else ad.x()
            dy = pd.y() if not pd.isNull() else ad.y()
            if h:
                h.setValue(h.value() - dx)
            if v:
                v.setValue(v.value() - dy)
            e.accept()
            self._show_scrollbars_temporarily()
            return
        except Exception:
            pass
        return super().wheelEvent(e)

    def _show_scrollbars_temporarily(self):
        try:
            if self.horizontalScrollBar():
                self.horizontalScrollBar().setVisible(True)
            if self.verticalScrollBar():
                self.verticalScrollBar().setVisible(True)
            if getattr(self, "_content_fits", True):
                self._sb_timer.start(700)
        except Exception:
            pass

    def _hide_scrollbars(self):
        try:
            if not getattr(self, "_content_fits", True):
                return
            if self.horizontalScrollBar():
                self.horizontalScrollBar().setVisible(False)
            if self.verticalScrollBar():
                self.verticalScrollBar().setVisible(False)
        except Exception:
            pass

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Reflow content only when window resizes; pinch zoom does not trigger reflow
        self._apply_geometry_to_proxy()
        self._update_interaction_state()

    def _apply_geometry_to_proxy(self):
        try:
            if not self._proxy:
                return
            if not self._content or not self._proxy:
                return
            vp = self.viewport().size()
            # Always size the embedded content to the current viewport on resize
            hint = self._content.minimumSizeHint()
            if not hint.isValid() or hint.width() <= 0 or hint.height() <= 0:
                hint = self._content.sizeHint()
            min_w = max(1, hint.width())
            min_h = max(1, hint.height())
            w = max(min_w, int(vp.width()))
            h = max(min_h, int(vp.height()))
            self._proxy.setPos(0, 0)
            self._proxy.resize(w, h)
            self._scene.setSceneRect(0, 0, w, h)
        except Exception:
            pass

    def _update_interaction_state(self):
        try:
            vp = self.viewport().size()
            sr = self._scene.sceneRect()
            fits_w = sr.width() <= vp.width() + 0.5
            fits_h = sr.height() <= vp.height() + 0.5
            content_fits = fits_w and fits_h
            self._content_fits = content_fits
            if self._scale <= 1.0 + 1e-3 and content_fits:
                self.setDragMode(QGraphicsView.NoDrag)
                if self.horizontalScrollBar():
                    self.horizontalScrollBar().setRange(0, 0)
                    self.horizontalScrollBar().setVisible(False)
                if self.verticalScrollBar():
                    self.verticalScrollBar().setRange(0, 0)
                    self.verticalScrollBar().setVisible(False)
            else:
                self.setDragMode(QGraphicsView.ScrollHandDrag)
                if self.horizontalScrollBar():
                    self.horizontalScrollBar().setVisible(True)
                if self.verticalScrollBar():
                    self.verticalScrollBar().setVisible(True)
        except Exception:
            pass


class PinnedPreviewWindow(QWidget):
    """Floating always-on-top preview window."""

    closed = Signal()

    def __init__(self):
        super().__init__(None)
        self.setWindowTitle("NEMESIS Preview — Pop-out")
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.view = ZoomView(bg_color=BG)
        self.container = AspectRatioContainer(self.view, 16, 9)
        layout.addWidget(self.container)
        self.resize(420, 236)

    def set_theme(self, theme: dict[str, str]):
        try:
            self.view.set_theme(theme)
        except Exception:
            pass
        try:
            self.container.set_theme(theme)
        except Exception:
            pass

    def set_pixmap(self, pixmap: QPixmap):
        self.view.set_image(pixmap)

    def set_aspect(self, w: int, h: int):
        self.container.set_aspect(w, h)

    def set_border_visible(self, on: bool):
        self.container.set_border_visible(on)

    def reset_first_frame(self):
        self.view.reset_first_frame()

    def closeEvent(self, event):
        try:
            self.closed.emit()
        except Exception:
            pass
        super().closeEvent(event)


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
            # Prepare the view BEFORE opening so first-open uses correct metrics and style
            try:
                v = self.view()
                if v is None:
                    # Ensure a view exists
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
                    # Apply QSS directly to the view so it paints border/radius consistently
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
                # Keep popup width aligned with the combo; compute a good first width
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
            # Now open the popup
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
                _set_macos_titlebar_appearance(self, QColor(BG))
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
        # This overrides any previous user resizing or state
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
                        outline.setPixelColor(x, y, QColor(OUTLINE))

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
        
        # CV Worker Thread
        self.cv_thread = QThread()
        self.cv_worker = CVWorker()
        self.cv_worker.moveToThread(self.cv_thread)
        self.cv_worker.resultsReady.connect(self._on_cv_results)
        self.cv_thread.start()
        
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

    # Session property shortcuts (for compatibility during refactor)
    @property
    def scheduler(self):
        return self.session.scheduler

    @property
    def serial(self):
        return self.session.serial

    @property
    def logger(self):
        return self.session.logger

    @logger.setter
    def logger(self, value):
        self.session.logger = value

    @property
    def run_dir(self):
        return self.session.run_dir

    @run_dir.setter
    def run_dir(self, value):
        self.session.run_dir = value

    @property
    def run_start(self):
        return self.session.run_start

    @run_start.setter
    def run_start(self, value):
        self.session.run_start = value

    @property
    def taps(self):
        return self.session.taps

    @taps.setter
    def taps(self, value):
        self.session.taps = value

    @property
    def _pending_run_metadata(self):
        return self.session.pending_run_metadata

    @_pending_run_metadata.setter
    def _pending_run_metadata(self, value):
        self.session.pending_run_metadata = value

    @property
    def _hardware_run_active(self):
        return self.session.hardware_run_active

    @_hardware_run_active.setter
    def _hardware_run_active(self, value):
        self.session.hardware_run_active = value

    @property
    def _awaiting_switch_start(self):
        return self.session.awaiting_switch_start

    @_awaiting_switch_start.setter
    def _awaiting_switch_start(self, value):
        self.session.awaiting_switch_start = value

    @property
    def _hardware_configured(self):
        return self.session.hardware_configured

    @_hardware_configured.setter
    def _hardware_configured(self, value):
        self.session.hardware_configured = value

    @property
    def _last_hw_tap_ms(self):
        return self.session.last_hw_tap_ms

    @_last_hw_tap_ms.setter
    def _last_hw_tap_ms(self, value):
        self.session.last_hw_tap_ms = value

    @property
    def _flash_only_mode(self):
        return self.session.flash_only_mode

    @_flash_only_mode.setter
    def _flash_only_mode(self, value):
        self.session.flash_only_mode = value

    @property
    def _first_hw_tap_ms(self):
        return self.session.first_hw_tap_ms

    @_first_hw_tap_ms.setter
    def _first_hw_tap_ms(self, value):
        self.session.first_hw_tap_ms = value

    @property
    def _first_host_tap_monotonic(self):
        return self.session.first_host_tap_monotonic

    @_first_host_tap_monotonic.setter
    def _first_host_tap_monotonic(self, value):
        self.session.first_host_tap_monotonic = value

    @property
    def _last_host_tap_monotonic(self):
        return self.session.last_host_tap_monotonic

    @_last_host_tap_monotonic.setter
    def _last_host_tap_monotonic(self, value):
        self.session.last_host_tap_monotonic = value

    @property
    def _active_serial_port(self):
        return self.session.active_serial_port

    @_active_serial_port.setter
    def _active_serial_port(self, value):
        self.session.active_serial_port = value

    @property
    def _hardware_config_message(self):
        return self.session.hardware_config_message

    @_hardware_config_message.setter
    def _hardware_config_message(self, value: str):
        self.session.hardware_config_message = value

    @property
    def _preview_size(self) -> tuple[int, int]:
        return self.session.preview_size

    @_preview_size.setter
    def _preview_size(self, value: tuple[int, int]):
        try:
            w, h = value
            self.session.preview_size = (int(w), int(h))
        except Exception:
            self.session.preview_size = (0, 0)

    def _reset_tap_history(self) -> None:
        self.session.reset_tap_history()

    def _record_tap_interval(self, host_ts: float) -> None:
        self.session.record_tap_interval(host_ts)

    def _recent_rate_per_min(self) -> float | None:
        return self.session.recent_rate_per_min()

    def _reset_frame_counters(self) -> None:
        self.session.reset_frame_counters()

    @property
    def _last_run_elapsed(self):
        return self.session.last_run_elapsed

    @_last_run_elapsed.setter
    def _last_run_elapsed(self, value):
        self.session.last_run_elapsed = value

    @property
    def _preview_frame_counter(self):
        return self.session.preview_frame_counter

    @_preview_frame_counter.setter
    def _preview_frame_counter(self, value):
        self.session.preview_frame_counter = value

    @property
    def _recorded_frame_counter(self):
        return self.session.recorded_frame_counter

    @_recorded_frame_counter.setter
    def _recorded_frame_counter(self, value):
        self.session.recorded_frame_counter = value

    def _update_section_spacers(self):
        spacers = getattr(self, "_section_spacers", None)
        layouts = getattr(self, "_section_layouts", None)
        right_widget = getattr(self, "_right_widget", None)
        right_scroll = getattr(self, "_right_scroll", None)
        if not spacers or not layouts or right_widget is None:
            return
        gaps = len(spacers)
        if gaps == 0:
            return
        try:
            viewport_h = right_scroll.viewport().height() if right_scroll else right_widget.height()
            available = viewport_h - sum(layout.sizeHint().height() for layout in layouts)
        except Exception:
            available = 0
        available = max(0, available)
        target = self._section_gap
        if gaps:
            try:
                target = min(self._section_gap, available // gaps)
            except Exception:
                target = self._section_gap
        target = max(0, target)
        for spacer in spacers:
            spacer.changeSize(0, target, QSizePolicy.Minimum, QSizePolicy.Fixed)
        try:
            self._right_layout.invalidate()
        except Exception:
            pass

    def _build_logo_menu(self) -> QMenu:
        menu = QMenu()
        menu.setObjectName("logoQuickActions")
        self._action_light_mode = menu.addAction("Light Mode")
        self._action_light_mode.setCheckable(True)
        self._action_light_mode.triggered.connect(self._on_light_mode_triggered)

        self._action_mirror_mode = menu.addAction("Mirror Mode")
        self._action_mirror_mode.setCheckable(True)
        self._action_mirror_mode.triggered.connect(self._on_mirror_mode_triggered)

        menu.addSeparator()
        action_fw = menu.addAction("Show Firmware Code...")
        action_fw.triggered.connect(self._show_firmware_dialog)

        menu.addSeparator()
        action_site = menu.addAction("Visit California Numerics")
        action_site.triggered.connect(lambda: QDesktopServices.openUrl(QUrl("https://californianumerics.com")))
        QTimer.singleShot(0, self._sync_logo_menu_checks)
        return menu

    def _logo_pressed(self, event):
        try:
            button = event.button()
        except Exception:
            button = Qt.LeftButton
        if button != Qt.LeftButton:
            return
        if not hasattr(self, "logo_menu") or self.logo_menu is None:
            return
        self.logo_menu.popup(QCursor.pos())

    def _on_light_mode_triggered(self, checked: bool):
        target = "light" if checked else "dark"
        self._apply_theme(target)

    def _on_mirror_mode_triggered(self, checked: bool):
        self._set_mirror_mode(checked)

    def _show_firmware_dialog(self):
        fw_path = BASE_DIR / "firmware/arduino/stentor_habituator_stepper_v9/NEMESIS_Firmware.ino"
        content = ""
        try:
            with open(fw_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            content = f"// Error reading firmware file:\n// {fw_path}\n// {e}"
            _log_gui_exception(e, context="Load firmware file")

        dialog = QDialog(self)
        dialog.setWindowTitle("Arduino Firmware Source")
        dialog.resize(600, 500)
        
        layout = QVBoxLayout(dialog)
        info = QLabel("Copy this code and flash it to your Arduino via the Arduino IDE.")
        info.setWordWrap(True)
        layout.addWidget(info)
        
        editor = QPlainTextEdit()
        editor.setPlainText(content)
        editor.setReadOnly(True)
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        editor.setFont(font)
        layout.addWidget(editor)
        
        btn_row = QHBoxLayout()
        copy_btn = QPushButton("Copy All")
        # Lambda to ensure sequence: select all -> copy -> (optional) restore selection? 
        # Just copy is enough if selectAll is visual feedback.
        def _copy():
            editor.selectAll()
            editor.copy()
            self._update_status("Firmware code copied to clipboard.")
            
        copy_btn.clicked.connect(_copy)
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        
        btn_row.addStretch(1)
        btn_row.addWidget(copy_btn)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
        
        dialog.exec()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_section_spacers()
        overlay = getattr(self, "_theme_overlay", None)
        if overlay is not None:
            try:
                overlay.setGeometry(self.rect())
                overlay.raise_()
            except Exception:
                pass

    def eventFilter(self, obj, ev):
        # Global pinch-zoom + browser parity shortcuts
        try:
            if ev.type() == QEvent.NativeGesture:
                gtype = getattr(ev, 'gestureType', None)
                if callable(gtype): gtype = gtype()
                val = getattr(ev, 'value', None)
                if callable(val): val = val()
                if gtype == Qt.NativeGestureType.Zoom and val is not None:
                    factor = 1.0 + (float(val) * 0.35)
                    self.app_view.zoom_by(factor)
                    ev.accept(); return True
            if ev.type() == QEvent.Gesture:
                pinch = ev.gesture(Qt.PinchGesture)
                if pinch is not None:
                    sf = getattr(pinch, 'scaleFactor', None)
                    if callable(sf): sf = sf()
                    if sf:
                        self.app_view.zoom_by(float(sf))
                        ev.accept(); return True
            if ev.type() == QEvent.KeyPress:
                key = ev.key(); mods = ev.modifiers()
                # Cmd/Ctrl based browser-like shortcuts
                if mods & Qt.ControlModifier or mods & Qt.MetaModifier:
                    if key in (Qt.Key_Plus, Qt.Key_Equal):
                        self.app_view.zoom_by(1.1); ev.accept(); return True
                    if key == Qt.Key_Minus:
                        self.app_view.zoom_by(1/1.1); ev.accept(); return True
                    if key == Qt.Key_0:
                        self.app_view.set_scale(1.0); ev.accept(); return True
        except Exception:
            pass
        return super().eventFilter(obj, ev)

    # Pro Mode
    def _toggle_pro_mode(self, on: bool):
        self.pro_mode = on
        self.pro_btn.setText(f"Pro Mode: {'ON' if on else 'OFF'}")
        # Hide some buttons to reduce visual noise in Pro
        for w in [self.enable_btn, self.disable_btn, self.outdir_btn]:
            w.setVisible(not on)

    def _toggle_preview_popout(self, on: bool):
        if on:
            if self._pip_window is None:
                self._pip_window = PinnedPreviewWindow()
                self._pip_window.closed.connect(self._on_pip_closed)
            aspect_w, aspect_h = self.video_area.aspect_ratio()
            self._pip_window.set_aspect(aspect_w, aspect_h)
            self._pip_window.set_border_visible(self.video_area.border_visible())
            self._pip_window.reset_first_frame()
            self._pip_window.show()
            try:
                self._pip_window.raise_()
                self._pip_window.activateWindow()
            except Exception:
                pass
            self.popout_btn.setText("Close Pop-out")
            self.popout_btn.setToolTip("Close the floating preview window")
        else:
            if self._pip_window:
                self._pip_window.close()
            else:
                self.popout_btn.setText("Pop-out Preview")
                self.popout_btn.setToolTip("Open a floating always-on-top preview window")

    def _on_pip_closed(self):
        self._pip_window = None
        if self.popout_btn.isChecked():
            self.popout_btn.blockSignals(True)
            self.popout_btn.setChecked(False)
            self.popout_btn.blockSignals(False)
        self.popout_btn.setText("Pop-out Preview")
        self.popout_btn.setToolTip("Open a floating always-on-top preview window")

    def keyPressEvent(self, event):
        if not self.pro_mode:
            return super().keyPressEvent(event)
        key = event.key()
        if key == Qt.Key_Space: self._send_tap("manual"); return
        if key == Qt.Key_R: self._stop_recording() if self.recorder else self._start_recording(); return
        if key == Qt.Key_S: self._start_run() if self.session.logger is None else self._stop_run(); return
        if key == Qt.Key_E: self._send_serial_char('e', "Enable motor"); return
        if key == Qt.Key_D: self._send_serial_char('d', "Disable motor"); return
        if key in (Qt.Key_1, Qt.Key_2, Qt.Key_3, Qt.Key_4, Qt.Key_5):
            val = int(chr(key)); self._apply_stepsize(val); return
        if key == Qt.Key_C: self._toggle_serial(); return
        if key == Qt.Key_V: self._open_camera(); return
        if key == Qt.Key_BracketLeft and self.mode.currentText()=="Periodic":
            self.period_sec.setValue(max(0.1, self.period_sec.value()-0.5)); return
        if key == Qt.Key_BracketRight and self.mode.currentText()=="Periodic":
            self.period_sec.setValue(self.period_sec.value()+0.5); return
        if key == Qt.Key_BraceLeft and self.mode.currentText()=="Poisson":
            self.lambda_rpm.setValue(max(0.1, self.lambda_rpm.value()-0.5)); return
        if key == Qt.Key_BraceRight and self.mode.currentText()=="Poisson":
            self.lambda_rpm.setValue(self.lambda_rpm.value()+0.5); return
        return super().keyPressEvent(event)

    # Stepsize
    def _on_stepsize_changed(self, text: str):
        # Accept labels like "4 (1/8 Step)" by parsing the leading integer
        try:
            head = ''.join(ch for ch in text if ch.isdigit())
            val = int(head[0]) if head else None
        except Exception:
            val = None
        if val is None:
            return
        self._apply_stepsize(val)

    def _apply_stepsize(self, val: int):
        if val not in (1,2,3,4,5):
            self.current_stepsize = 4
            return
        self.current_stepsize = val
        self.stepsize.blockSignals(True)
        try:
            self.stepsize.setCurrentIndex(val)
        finally:
            self.stepsize.blockSignals(False)
        self._send_serial_char(str(val), "Set stepsize")

    def _reset_serial_indicator(self, note: str | None = None):
        text = "Last serial command: —"
        if note:
            text += f" ({note})"
        if hasattr(self, "serial_status"):
            self.serial_status.setText(text)

    def _record_serial_command(self, payload: str, note: str | None = None):
        display = payload.replace('\n', '↵') if payload else '—'
        text = f"Last serial command: {display}"
        if note:
            text += f" ({note})"
        if hasattr(self, "serial_status"):
            self.serial_status.setText(text)

    def _reset_tap_history(self) -> None:
        self.session.reset_tap_history()

    def _reset_frame_counters(self) -> None:
        self.session.reset_frame_counters()

    def _record_tap_interval(self, host_ts: float) -> None:
        self.session.record_tap_interval(host_ts)

    def _recent_rate_per_min(self) -> float | None:
        return self.session.recent_rate_per_min()

    # Hardware serial processing

    def _handle_serial_error(self, msg: str):
        self._update_status(f"Serial Error: {msg}")
        if self.serial.is_open():
            self._toggle_serial() # Disconnect to reset state
        if hasattr(self, "serial_status"):
            self.serial_status.setText(f"Error: {msg}")

    def _drain_serial_queue(self):
        if not self.serial.is_open():
            return
        while True:
            item = self.serial.read_line_nowait(with_timestamp=True)
            if item is None:
                break
            timestamp, line = item
            cleaned = line.strip()
            if cleaned.startswith("ERROR:"):
                self._handle_serial_error(cleaned)
                break
            if not cleaned:
                continue
            self._handle_serial_line(cleaned, timestamp)

    def _handle_serial_line(self, line: str, timestamp: float | None = None):
        self._hardware_config_message = line
        if line.startswith("EVENT:"):
            payload = line[6:]
            event, _, data = payload.partition(',')
            self._handle_hardware_event(event.strip().upper(), data.strip(), timestamp)
            return
        if line.startswith("CONFIG:"):
            self._handle_hardware_config_message(line)
            return
        if line.startswith("Motor enabled"):
            self._motor_enabled = True
        elif line.startswith("Motor disabled"):
            self._motor_enabled = False
        if hasattr(self, "serial_status"):
            self.serial_status.setText(f"HW → {line}")

    def _handle_hardware_config_message(self, line: str):
        if line.startswith("CONFIG:OK"):
            self._hardware_configured = True
            if hasattr(self, "serial_status"):
                self.serial_status.setText(line)
            if self._awaiting_switch_start:
                self._update_status("Hardware configured. Flip the switch ON to begin.")
        elif line.startswith("CONFIG:ERR"):
            self._hardware_configured = False
            self._awaiting_switch_start = False
            if hasattr(self, "serial_status"):
                self.serial_status.setText(line)
            self._update_status(f"Hardware configuration failed: {line}")
            if self.session.logger or self.session.pending_run_metadata is not None:
                self._stop_run(from_hardware=True, reason="Hardware configuration failed.")
        elif line.startswith("CONFIG:STEPSIZE"):
            if hasattr(self, "serial_status"):
                self.serial_status.setText(line)
        elif line.startswith("CONFIG:DONE"):
            if hasattr(self, "serial_status"):
                self.serial_status.setText(line)
            if self._awaiting_switch_start:
                self._update_status("Hardware ready. Flip the switch to begin.")

    def _handle_hardware_event(self, event: str, data: str, host_ts: float | None = None):
        if event == "SWITCH":
            if hasattr(self, "serial_status"):
                self.serial_status.setText(f"Switch {data.upper() if data else '?'}")
            if self._awaiting_switch_start and data.upper() == "ON":
                self._update_status("Switch ON detected. Waiting for hardware activation…")
            return
        if event == "MODE_ACTIVATED":
            self._on_hardware_run_started(host_ts)
            return
        if event == "MODE_DEACTIVATED":
            self._on_hardware_run_stopped()
            return
        if event == "TAP":
            self._on_hardware_tap(data, host_ts)

    def _compose_hardware_config(self) -> tuple[str, dict[str, object]]:
        use_replicant = self._replicant_mode_active()
        mode_text = "Replicant" if use_replicant else self.mode.currentText()
        mode_token = 'H' if use_replicant else ('P' if mode_text == "Periodic" else 'R')
        stepsize = max(1, min(int(self.current_stepsize), 5))
        period_s = float(self.period_sec.value())
        lambda_rpm = float(self.lambda_rpm.value())
        port = self.port_edit.currentText().strip()
        calibration: float | None = None
        if mode_token == 'P':
            period_s = max(0.001, period_s)
            calibration = self._lookup_period_calibration(port)
            adjusted_period = period_s * calibration
            config_value = f"{adjusted_period:.6f}"
        elif mode_token == 'R':
            lambda_rpm = max(0.01, lambda_rpm)
            config_value = f"{lambda_rpm:.6f}"
        else:
            config_value = f"{self.session.replicant_total}"
        message = f"C,{mode_token},{stepsize},{config_value}\n"
        meta = {
            "mode": mode_token,
            "mode_label": mode_text,
            "stepsize": stepsize,
            "value": config_value,
            "period_sec": period_s,
            "lambda_rpm": lambda_rpm,
            "seed": None,
            "outdir": self.outdir_edit.text().strip() or str(RUNS_DIR),
            "rec_path": getattr(self.recorder, "path", ""),
            "timestamp": time.strftime("%Y%m%d_%H%M%S"),
            "port": port,
            "period_calibration": float(calibration) if calibration is not None else None,
            "replicant_path": self.session.replicant_path,
            "replicant_taps": self.session.replicant_total,
        }
        self.session.replicant_enabled = use_replicant
        return message, meta

    def _clear_run_data(self):
        if self.session.hardware_run_active:
            QMessageBox.information(self, "Run Active", "Stop the run before clearing.")
            return
        try:
            self.live_chart.reset()
        except Exception:
            pass
        self._reset_tap_history()
        self._reset_frame_counters()
        self.taps = 0
        self.run_start = None
        self._last_run_elapsed = 0.0
        self._first_hw_tap_ms = None
        self._first_host_tap_monotonic = None
        self._last_host_tap_monotonic = None
        self._update_status("Run data cleared.")
        self.counters.setText("Taps: 0 | Elapsed: 0 s | Rate10: -- /min | Overall: 0.0 /min")
        self._refresh_statusline()

    def _flash_hardware_config(self):
        if not self.serial.is_open():
            QMessageBox.warning(self, "Serial", "Connect to the controller before flashing the configuration.")
            return
        while self.serial.read_line_nowait() is not None:
            pass
        message, meta = self._compose_hardware_config()
        self.serial.send_text(message)
        self._record_serial_command("FLASH", "Config payload sent")
        self.session.hardware_configured = False
        self.session.awaiting_switch_start = True
        self.session.hardware_run_active = False
        self.session.flash_only_mode = True
        meta["source"] = "flash"
        self._pending_run_metadata = meta
        self._last_hw_tap_ms = None
        self.run_start = None
        self.taps = 0
        self._reset_tap_history()
        self._reset_frame_counters()
        self.counters.setText("Taps: 0 | Elapsed: 0 s | Rate10: -- /min | Overall: 0.0 /min")
        try:
            self.live_chart.reset()
        except Exception:
            pass
        self._active_serial_port = meta.get("port", self.port_edit.currentText().strip())
        self._update_status("Config flashed for testing. Flip the switch to move; press Start Run to log data.")
        self._send_serial_char('e', "Enable motor")

    def _manual_tap(self):
        if not self.serial.is_open():
            self._update_status("Tap skipped: serial disconnected.")
            return
        if not self._motor_enabled:
            self._send_serial_char('e', "Enable motor")
        self._send_tap("manual")

    def _send_tap(self, mark: str = "scheduled") -> None:
        if not self.serial.is_open():
            self._update_status("Tap skipped: serial disconnected.")
            return
        host_now = time.monotonic()
        if mark != "scheduled" and not self._motor_enabled:
            self._send_serial_char('e', "Enable motor")
        self._send_serial_char('t', f"Tap ({mark})")
        self.taps += 1
        start = self.run_start or host_now
        elapsed = host_now - start
        self._record_tap_interval(host_now)
        if elapsed > 0:
            self._last_run_elapsed = elapsed
        recent_rate = self._recent_rate_per_min()
        recent_str = f"{recent_rate:.2f}" if recent_rate is not None else "--"
        overall_rate = (self.taps / elapsed * 60.0) if elapsed > 0 else 0.0
        overall_str = f"{overall_rate:.2f}" if elapsed > 0 else "--"
        elapsed_display = int(round(elapsed))
        self.counters.setText(
            f"Taps: {self.taps} | Elapsed: {elapsed_display} s | Rate10: {recent_str} /min | Overall: {overall_str} /min"
        )
        if self.logger:
            host_iso = datetime.now(timezone.utc).isoformat()
            self.logger.log_tap(
                host_time_s=host_now,
                mode=self.mode.currentText(),
                mark=mark,
                stepsize=self.current_stepsize,
                host_iso=host_iso,
                firmware_ms=None,
                preview_frame_idx=self._preview_frame_counter,
                recorded_frame_idx=self._recorded_frame_counter,
            )
        if mark == "scheduled" and self.run_start:
            try:
                self.live_chart.add_tap(elapsed)
            except Exception:
                pass

    def _on_tap_due(self):
        # Safety check: if run stopped (run_start is None), do not proceed
        if self.run_start is None:
            return

        if self.session.replicant_running:
            self._fire_replicant_tap()
            return
        self._send_tap("scheduled")
        
        # Double-check run state after sending tap, before scheduling next
        if self.run_start is None:
            return

        delay = self.session.scheduler.next_delay_s()
        self.run_timer.start(int(delay * 1000))
        self._update_status(f"Tap sent. Next in {delay:.3f}s")

    def _on_hardware_run_started(self, host_timestamp: float | None = None):
        host_now = host_timestamp if host_timestamp is not None else time.monotonic()
        if self.session.logger is None and not self.session.flash_only_mode:
            self._initialize_run_logger()
        self.session.hardware_run_active = True
        self.session.awaiting_switch_start = False
        self._first_hw_tap_ms = None
        self._last_hw_tap_ms = None
        self._first_host_tap_monotonic = None
        self._last_host_tap_monotonic = None
        self.taps = 0
        self.run_start = host_now
        self._reset_tap_history()
        self._reset_frame_counters()
        self.counters.setText("Taps: 0 | Elapsed: 0 s | Rate10: -- /min | Overall: 0.0 /min")
        try:
            self.live_chart.reset()
        except Exception:
            pass
        if self.session.logger is None:
            self._update_status("Hardware run active (not logging). Press Start Run to capture data.")
        else:
            self._update_status("Hardware run active.")
        self.session.flash_only_mode = False
        if self.session.replicant_enabled and self.session.replicant_ready:
            self.session.replicant_running = True
            self.session.replicant_progress = 0
            self.session.replicant_index = 0
            self._awaiting_replicant_timer = False
            self.live_chart.set_replay_targets(self.session.replicant_offsets)
            self.live_chart.mark_replay_progress(0)
            self._update_replicant_status()
            self._schedule_next_replicant()

    def _on_hardware_run_stopped(self):
        if not self.session.hardware_run_active and not self.session.awaiting_switch_start:
            return
        self.session.hardware_run_active = False
        self.session.awaiting_switch_start = False
        self.session.last_hw_tap_ms = None
        self.session.replicant_running = False
        self.session.replicant_index = 0
        self.session.replicant_progress = 0
        self._awaiting_replicant_timer = False
        self._stop_run(from_hardware=True, reason="Hardware run stopped.")

    def _on_hardware_tap(self, data: str, host_timestamp: float | None = None):
        if not self._hardware_run_active:
            return
        is_replicant = self.session.replicant_running
        host_now = host_timestamp if host_timestamp is not None else time.monotonic()
        if self._first_host_tap_monotonic is None:
            self._first_host_tap_monotonic = host_now
        self._last_host_tap_monotonic = host_now
        if self.run_start is None:
            self.run_start = host_now
        elapsed = host_now - self.run_start
        self.taps += 1
        self._record_tap_interval(host_now)
        overall_rate = (self.taps / elapsed * 60.0) if elapsed > 0 else 0.0
        recent_rate = self._recent_rate_per_min()
        recent_str = f"{recent_rate:.2f}" if recent_rate is not None else "--"
        overall_str = f"{overall_rate:.2f}" if elapsed > 0 else "--"
        elapsed_display = int(round(elapsed))
        self.counters.setText(
            f"Taps: {self.taps} | Elapsed: {elapsed_display} s | Rate10: {recent_str} /min | Overall: {overall_str} /min"
        )
        self._last_run_elapsed = elapsed if elapsed > 0 else self._last_run_elapsed
        try:
            self.live_chart.add_tap(elapsed)
        except Exception:
            pass
        try:
            if data:
                value = float(data)
                if self._first_hw_tap_ms is None:
                    self._first_hw_tap_ms = value
                self._last_hw_tap_ms = value
            else:
                value = None
        except Exception:
            self._last_hw_tap_ms = None
            value = None
        if self.logger:
            note = f"hw_ms={data}" if data else None
            host_iso = datetime.now(timezone.utc).isoformat()
            self.logger.log_tap(
                host_time_s=host_now,
                mode="Replicant" if is_replicant else self.mode.currentText(),
                mark="replicant" if is_replicant else "hardware",
                stepsize=self.current_stepsize,
                notes=note,
                host_iso=host_iso,
                firmware_ms=value,
                preview_frame_idx=self._preview_frame_counter,
                recorded_frame_idx=self._recorded_frame_counter,
            )
        if is_replicant:
            self.session.replicant_progress += 1
            self.live_chart.mark_replay_progress(self.session.replicant_progress)
            self._update_replicant_status()
            if (
                self.session.replicant_progress >= self.session.replicant_total
                and self.session.replicant_index >= self.session.replicant_total
            ):
                self._finish_replicant_sequence()
            else:
                self._schedule_next_replicant()

    def _initialize_run_logger(self, force: bool = False):
        if self.logger is not None and not force:
            return
        meta = self._pending_run_metadata or {}
        outdir = meta.get("outdir") or (self.outdir_edit.text().strip() or str(RUNS_DIR))
        ts = time.strftime("%Y%m%d_%H%M%S")
        if force and self.logger is not None:
            try:
                self.logger.close()
            except Exception:
                pass
            self.logger = None
        run_token = uuid.uuid4().hex[:6].upper()
        run_dir = Path(outdir) / f"run_{ts}_{run_token}"
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self._update_status(f"Failed to create run directory: {exc}")
            return
        rec_path = meta.get("rec_path") or getattr(self.recorder, "path", "")
        self.logger = runlogger_module.RunLogger(run_dir, recording_path=rec_path)
        self.run_dir = run_dir
        
        # Initialize CV Tracking Logger
        try:
            self.session.tracking_logger = TrackingLogger(run_dir)
        except Exception as e:
            self._update_status(f"Failed to init tracking log: {e}")
        
        # Capture app logs to run folder
        try:
            runlogger_module.configure_file_logging(run_dir / "app.log")
        except Exception:
            pass

        seed = meta.get("seed")
        if seed in (None, "", "None"):
            self.session.scheduler.set_seed(None)
        else:
            try:
                self.session.scheduler.set_seed(int(seed))
            except Exception:
                self.session.scheduler.set_seed(None)
        mode_token = meta.get("mode", 'P')
        if mode_token == 'P':
            self.session.scheduler.configure_periodic(meta.get("period_sec", float(self.period_sec.value())))
        elif mode_token == 'R':
            self.session.scheduler.configure_poisson(meta.get("lambda_rpm", float(self.lambda_rpm.value())))
        else:
            self.session.scheduler.configure_periodic(meta.get("period_sec", float(self.period_sec.value())))

        run_json = {
            "run_id": self.logger.run_id,
            "started_at": ts,
            "app_version": APP_VERSION,
            "firmware_commit": "",
            "camera_index": self.cam_index.value(),
            "recording_path": rec_path,
            "serial_port": self.port_edit.currentText().strip(),
            "mode": meta.get("mode_label", self.mode.currentText()),
            "period_sec": meta.get("period_sec", float(self.period_sec.value())),
            "lambda_rpm": meta.get("lambda_rpm", float(self.lambda_rpm.value())),
            "seed": seed,
            "stepsize": meta.get("stepsize", self.current_stepsize),
            "scheduler": self.session.scheduler.descriptor(),
            "hardware_trigger": "switch",
            "config_source": meta.get("source", "unknown"),
        }
        if meta.get("replicant_path"):
            run_json["replicant_path"] = meta.get("replicant_path")
            run_json["replicant_taps"] = meta.get("replicant_taps", 0)
            duration = self.session.replicant_offsets[-1] if self.session.replicant_offsets else 0.0
            run_json["replicant_duration_s"] = duration
            run_json["scheduler"] = {"mode": "Replicant", "total_taps": meta.get("replicant_taps", 0)}
        try:
            with open(run_dir / "run.json", "w", encoding="utf-8") as f:
                json.dump(run_json, f, indent=2)
        except Exception as exc:
            self._update_status(f"Failed to write run.json: {exc}")
        meta["run_id"] = self.logger.run_id
        meta["outdir"] = str(outdir)
        self._pending_run_metadata = meta
    def _send_serial_char(self, payload: str, note: str | None = None) -> bool:
        if not payload:
            return False
        if not self.serial.is_open():
            if note:
                self._record_serial_command('—', f"{note}; serial closed")
            return False
        for ch in payload:
            if not self.serial.send_char(ch):
                self._handle_serial_error("Write failed (device disconnected?)")
                return False
        self._record_serial_command(payload, note)
        if len(payload) == 1:
            if payload == 'e':
                self._motor_enabled = True
            elif payload == 'd':
                self._motor_enabled = False
        return True

    # Camera
    def _on_preview_first_frame(self):
        try:
            self.video_area.set_border_visible(True)
        except Exception:
            pass
        if self._pip_window:
            try:
                self._pip_window.set_border_visible(True)
            except Exception:
                pass

    def _open_camera(self):
        idx = self.cam_index.value()
        registry = getattr(self, "_resource_registry", None)
        if self.cap is None:
            if registry is not None:
                ok, _owner = registry.claim_camera(self, idx)
                if not ok:
                    self._update_status(f"Camera {idx} already in use on another tab.")
                    return
            self.cap = video.VideoCapture(idx)
            if not self.cap.open():
                self._update_status("Failed to open camera.")
                self.cap = None
                if registry is not None:
                    registry.release_camera(self, idx)
                self.session.camera_index = None
                return
            self.session.camera_index = idx
            try:
                w, h = self.cap.get_size()
                if w and h:
                    self._preview_size = (w, h)
                    self.video_area.set_aspect(w, h)
                    self.video_area.update()
                    if self._pip_window:
                        self._pip_window.set_aspect(w, h)
                self.video_area.set_border_visible(True)
                self.video_view.reset_first_frame()
                if self._pip_window:
                    self._pip_window.set_border_visible(True)
                    self._pip_window.reset_first_frame()
            except Exception:
                pass
            self.preview_fps = int(self.cap.get_fps() or 30)
            self._start_frame_stream()
            self.cam_btn.setText("Close Camera"); self._update_status(f"Camera {idx} open. Preview live.")
        else:
            self._stop_recording()
            self._stop_frame_stream()
            self.cap.release(); self.cap = None
            active_idx = self.session.camera_index if self.session.camera_index is not None else idx
            if registry is not None:
                registry.release_camera(self, active_idx)
            self.session.camera_index = None
            try:
                self.video_area.set_border_visible(True)
                self.video_view.reset_first_frame()
                self.video_area.update()
                if self._pip_window:
                    self._pip_window.set_border_visible(True)
                    self._pip_window.reset_first_frame()
            except Exception:
                pass
            self.cam_btn.setText("Open Camera"); self._update_status("Camera closed.")

    def _maybe_update_preview_aspect(self, width: int, height: int):
        if width <= 0 or height <= 0:
            return
        prev_w, prev_h = self._preview_size
        if prev_w == width and prev_h == height:
            return
        self._preview_size = (width, height)
        try:
            self.video_area.set_aspect(width, height)
            self.video_area.update()
        except Exception:
            pass
        if self._pip_window:
            try:
                self._pip_window.set_aspect(width, height)
            except Exception:
                pass

    # Serial
    def _toggle_serial(self):
        registry = getattr(self, "_resource_registry", None)
        if not self.serial.is_open():
            port = self.port_edit.currentText().strip()
            if not port:
                port = self._auto_detect_serial_port()
                if port:
                    idx = self.port_edit.findText(port, Qt.MatchFixedString)
                    if idx == -1:
                        self.port_edit.addItem(port)
                        idx = self.port_edit.findText(port, Qt.MatchFixedString)
                    if idx != -1:
                        self.port_edit.setCurrentIndex(idx)
                    else:
                        self.port_edit.setCurrentText(port)
            if not port:
                self._update_status("Enter a serial port first.")
                return
            if registry is not None:
                ok, _owner = registry.claim_serial(self, port)
                if not ok:
                    self._update_status(f"Serial port {port} already in use on another tab.")
                    return
            try:
                self.serial.open(port, baudrate=9600, timeout=0)
                self.serial_btn.setText("Disconnect Serial"); self._update_status(f"Serial connected on {port}.")
                self._reset_serial_indicator("connected")
                self._active_serial_port = port
                self._motor_enabled = False
                if not self.serial_timer.isActive():
                    self.serial_timer.start()
            except Exception as e:
                self._update_status(f"Serial error: {e}")
                self._reset_serial_indicator("error")
                if registry is not None:
                    registry.release_serial(self, port)
        else:
            port = self._active_serial_port or self.port_edit.currentText().strip()
            self.serial.close(); self.serial_btn.setText("Connect Serial"); self._update_status("Serial disconnected.")
            self._reset_serial_indicator("disconnected")
            self.serial_timer.stop()
            self._hardware_run_active = False
            self._awaiting_switch_start = False
            self._hardware_configured = False
            self._motor_enabled = False
            if registry is not None and port:
                registry.release_serial(self, port)
            self._active_serial_port = ""

    # Output dir
    def _choose_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "Choose output directory")
        if d: self.outdir_edit.setText(d)

    # Replicant controls
    def _replicant_mode_active(self) -> bool:
        return bool(self.session.replicant_enabled and self.session.replicant_ready)

    def _load_replicant_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select taps.csv to replay",
            str(Path(self.outdir_edit.text().strip() or RUNS_DIR).resolve()),
            "CSV Files (*.csv)",
        )
        if not path:
            return
        if self._load_replicant_from_path(path, quiet=False):
            self.session.replicant_enabled = self.session.replicant_ready
            self._mode_changed()
            self._update_replicant_status()

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

    def _export_live_chart(self):
        base_dir = Path(self.outdir_edit.text().strip() or RUNS_DIR)
        default_path = base_dir / f"nemesis_plot_{time.strftime('%Y%m%d_%H%M%S')}.png"
        dest, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export plot",
            str(default_path),
            "PNG Image (*.png);;PDF Document (*.pdf);;SVG Vector (*.svg)"
        )
        if not dest:
            return
        try:
            dpi = 300 if selected_filter.startswith("PNG") else 0
            if dpi:
                self.live_chart.save(dest, dpi=dpi)
            else:
                self.live_chart.save(dest)
            self._update_status(f"Plot exported → {dest}")
        except Exception as exc:
            QMessageBox.warning(self, "Export Plot", f"Failed to export plot: {exc}")

    def _load_replicant_from_path(self, path: str, quiet: bool = False) -> bool:
        try:
            offsets, delays = self._parse_replicant_csv(path)
        except Exception as exc:
            if not quiet:
                QMessageBox.warning(self, "Replicant", f"Failed to load taps.csv: {exc}")
            return False
        total = len(offsets)
        self.session.replicant_path = path
        self.session.replicant_offsets = offsets
        self.session.replicant_delays = delays
        self.session.replicant_total = total
        self.session.replicant_progress = 0
        self.session.replicant_ready = total > 0
        summary = "No taps found" if total == 0 else f"{total} taps"
        if total > 1:
            duration = offsets[-1]
            if duration > 0.0:
                summary += f" • {duration/60.0:.2f} min"
        self.replicant_status.setText(summary)
        self.replicant_status.setToolTip(path if total else "")
        if self.session.replicant_ready:
            self.session.replicant_enabled = True
            self.live_chart.set_replay_targets(offsets)
            if not quiet:
                self._update_status(f"Replicant script loaded ({total} taps).")
        else:
            self.session.replicant_enabled = False
            self.live_chart.clear_replay_targets()
            if not quiet:
                self._update_status("Selected taps.csv did not contain any tap timestamps.")
        self._mode_changed()
        self._update_replicant_status()
        return True

    def _clear_replicant_csv(self, quiet: bool = False):
        self.session.replicant_path = None
        self.session.replicant_offsets.clear()
        self.session.replicant_delays.clear()
        self.session.replicant_total = 0
        self.session.replicant_progress = 0
        self.session.replicant_ready = False
        self.session.replicant_enabled = False
        self.replicant_status.setText("No script loaded")
        self.replicant_status.setToolTip("")
        self.live_chart.clear_replay_targets()
        if not quiet:
            self._update_status("Replicant mode cleared.")
        self._mode_changed()
        self._update_replicant_status()

    def _parse_replicant_csv(self, path: str) -> tuple[list[float], list[float]]:
        offsets: list[float] = []
        delays: list[float] = []
        base_ms: float | None = None
        with open(path, "r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                raw = row.get("t_host_ms") if row else None
                if raw in (None, ""):
                    continue
                try:
                    host_ms = float(raw)
                except Exception:
                    continue
                if base_ms is None:
                    base_ms = host_ms
                offset = max(0.0, (host_ms - base_ms) / 1000.0)
                offsets.append(offset)
        if not offsets:
            raise ValueError("No t_host_ms entries found")
        previous = 0.0
        for idx, val in enumerate(offsets):
            if idx == 0:
                delays.append(0.0)
            else:
                delays.append(max(0.0, val - previous))
            previous = val
        return offsets, delays

    def _schedule_next_replicant(self):
        if not self.session.replicant_running:
            return
        total = self.session.replicant_total
        idx = self.session.replicant_index
        if idx >= total:
            self._awaiting_replicant_timer = False
            if self.session.replicant_progress >= total:
                self._finish_replicant_sequence()
            return
        delays = self.session.replicant_delays
        while idx < total:
            delay = 0.0
            try:
                delay = max(0.0, float(delays[idx]))
            except Exception:
                delay = 0.0
            if delay <= 0.0005:
                self._fire_replicant_tap()
                idx = self.session.replicant_index
                continue
            if self.session.replicant_progress < idx:
                self._awaiting_replicant_timer = False
                return
            self._awaiting_replicant_timer = True
            self.run_timer.start(max(1, int(delay * 1000)))
            return
        self._awaiting_replicant_timer = False

    def _fire_replicant_tap(self):
        idx = self.session.replicant_index
        if idx >= self.session.replicant_total:
            return
        self._send_serial_char('t', f"Tap (replicant #{idx + 1})")
        self.session.replicant_index += 1
        self._awaiting_replicant_timer = False

    def _finish_replicant_sequence(self):
        if not self.session.replicant_running:
            return
        self.session.replicant_running = False
        self._awaiting_replicant_timer = False
        self.session.replicant_index = self.session.replicant_total
        self._update_replicant_status()
        if self._hardware_run_active:
            self._stop_run(reason="Replicant script completed.")

    def _update_replicant_status(self):
        if not hasattr(self, "replicant_status") or self.replicant_status is None:
            return
        if not self.session.replicant_ready:
            self.replicant_status.setText("No script loaded")
            self.replicant_status.setToolTip("")
            return
        total = self.session.replicant_total
        duration = self.session.replicant_offsets[-1] if self.session.replicant_offsets else 0.0
        if self.session.replicant_running:
            text = f"{self.session.replicant_progress}/{total} taps"
        elif self.session.replicant_progress >= total and total > 0:
            text = f"Completed {total} taps"
        else:
            text = f"{total} taps"
            if duration > 0.0:
                text += f" • {duration/60.0:.2f} min"
        self.replicant_status.setText(text)
        if self.session.replicant_path:
            self.replicant_status.setToolTip(self.session.replicant_path)

    # Recording
    def _start_recording(self):
        if self.cap is None:
            QMessageBox.warning(self, "No Camera", "Open a camera before starting recording."); return
        if self.recorder is not None:
            QMessageBox.information(self, "Recording", "Already recording."); return
        outdir = self.outdir_edit.text().strip() or str(RUNS_DIR)
        Path(outdir).mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        rec_dir = self.run_dir if self.run_dir is not None else Path(outdir)/f"recording_{ts}"
        rec_dir.mkdir(parents=True, exist_ok=True)
        w, h = self.cap.get_size()
        requested_path = rec_dir / "video.mp4"
        self.recorder = video.VideoRecorder(str(requested_path), fps=self.preview_fps, frame_size=(w, h))
        if not self.recorder.is_open():
            self.recorder = None; QMessageBox.warning(self, "Recorder", "Failed to start MP4 recorder."); return
        self._recorded_frame_counter = 0
        # Use the actual path (handles fallback to .avi)
        actual_path = Path(self.recorder.path)
        # If a run is already active, inject path into logger for subsequent rows
        if self.logger:
            self.logger.set_recording_path(str(actual_path))
        self.rec_indicator.setText("● REC ON")
        self._recording_active = True
        self.rec_indicator.setStyleSheet(f"color:{DANGER}; font-weight:bold;")
        self._update_status(f"Recording → {actual_path}")

    def _stop_recording(self):
        if self.recorder:
            self.recorder.close(); self.recorder = None
            self.rec_indicator.setText("● REC OFF")
            self._recording_active = False
            self.rec_indicator.setStyleSheet(f"color:{SUBTXT};")
            self._update_status("Recording stopped.")

    # Config Save/Load
    def _current_config(self) -> dict:
        return {
            "mode": self.mode.currentText(),
            "period_sec": self.period_sec.value(),
            "lambda_rpm": self.lambda_rpm.value(),
            "stepsize": self.current_stepsize,
            "camera_index": self.cam_index.value(),
            "serial_port": self.port_edit.currentText().strip(),
            "output_dir": self.outdir_edit.text().strip(),
            "replicant_path": self.session.replicant_path or "",
            "app_version": APP_VERSION,
        }

    def _apply_config(self, cfg: dict):
        try:
            self.mode.setCurrentIndex(0 if cfg.get("mode","Periodic")=="Periodic" else 1)
            self.period_sec.setValue(float(cfg.get("period_sec", 10.0)))
            self.lambda_rpm.setValue(float(cfg.get("lambda_rpm", 6.0)))
            self._apply_stepsize(int(cfg.get("stepsize", 4)))
            self.cam_index.setValue(int(cfg.get("camera_index", 0)))
            self.port_edit.setCurrentText(cfg.get("serial_port", ""))
            outdir = cfg.get("output_dir", "")
            if outdir: self.outdir_edit.setText(outdir)
            path = cfg.get("replicant_path", "")
            if path:
                if not self._load_replicant_from_path(path, quiet=True):
                    self._clear_replicant_csv(quiet=True)
                else:
                    self.session.replicant_enabled = self.session.replicant_ready
                    self._mode_changed()
                    self._update_replicant_status()
            else:
                self._clear_replicant_csv(quiet=True)
        except Exception as e:
            QMessageBox.warning(self, "Config", f"Failed to apply config: {e}")

    def _save_config_clicked(self):
        try:
            configio.save_config(self._current_config())
            self._update_status("Config saved.")
        except Exception as e:
            QMessageBox.warning(self, "Save Config", f"Failed to save: {e}")

    def _load_config_clicked(self):
        cfg = configio.load_config()
        if not cfg:
            QMessageBox.information(self, "Load Config", "No saved config found."); return
        self._apply_config(cfg); self._update_status("Config loaded.")

    # Scheduler / Run
    def _mode_changed(self):
        is_periodic = (self.mode.currentText() == "Periodic")
        if self._replicant_mode_active():
            self.mode.setEnabled(False)
            self.lbl_mode.setEnabled(False)
            self.period_sec.setEnabled(False)
            self.lbl_period.setEnabled(False)
            self.lambda_rpm.setEnabled(False)
            self.lbl_lambda.setEnabled(False)
        else:
            self.mode.setEnabled(True)
            self.lbl_mode.setEnabled(True)
            self.period_sec.setEnabled(is_periodic)
            self.lbl_period.setEnabled(is_periodic)
            self.lambda_rpm.setEnabled(not is_periodic)
            self.lbl_lambda.setEnabled(not is_periodic)
        # Helpful tooltips to clarify why control is inactive
        self.period_sec.setToolTip("Adjust when Mode is set to Periodic")
        self.lambda_rpm.setToolTip("Adjust when Mode is set to Poisson")

    def _start_run(self):
        # Disk space safety check (soft warning)
        try:
            _total, _used, free = shutil.disk_usage(self.outdir_edit.text().strip() or ".")
            if free < 1024 * 1024 * 1024:  # 1 GB
                QMessageBox.warning(self, "Low Disk Space", f"Free space is low ({free // (1024*1024)} MB). Recording may stop unexpectedly.")
        except Exception:
            pass

        if not self.serial.is_open():
            resp = QMessageBox.warning(self, "Serial Disconnected", 
                "Serial is not connected. The hardware will not move.\n\nStart run anyway (logging only)?", 
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if resp != QMessageBox.Yes:
                return

        self._flash_only_mode = False
        use_replicant = self._replicant_mode_active()
        if use_replicant and not self.session.replicant_ready:
            QMessageBox.warning(self, "Replicant", "Load a taps.csv before starting replicant mode.")
            return
        if use_replicant and self.session.replicant_total <= 0:
            QMessageBox.warning(self, "Replicant", "Loaded taps.csv contains no tap rows.")
            return
        if self._hardware_run_active:
            if self.logger is None:
                if self._pending_run_metadata is None:
                    self._pending_run_metadata = self._compose_hardware_config()[1]
                self._initialize_run_logger(force=True)
                self.run_start = time.monotonic()
                self.taps = 0
                self._reset_tap_history()
                self._reset_frame_counters()
                self._last_run_elapsed = 0.0
                self.counters.setText("Taps: 0 | Elapsed: 0 s | Rate10: -- /min | Overall: 0.0 /min")
                try:
                    self.live_chart.reset()
                except Exception:
                    pass
                self._update_status("Logging enabled for active hardware run.")
            else:
                QMessageBox.information(self, "Run", "A hardware run is already active.")
            self._awaiting_switch_start = False
            return
        if self._awaiting_switch_start:
            self._update_status("Recording armed. Awaiting physical switch to begin logging.")
        
        # Auto-recording countdown
        if self.auto_rec_check.isChecked() and self.recorder is None:
            if self.cap is None:
                QMessageBox.warning(self, "No Camera", "Open a camera to use Auto-Rec.")
                return
            pd = QProgressDialog("Auto-starting recording...", "Cancel", 0, 30, self)
            pd.setWindowModality(Qt.WindowModal)
            pd.setMinimumDuration(0)
            pd.setValue(0)
            aborted = False
            for i in range(30):
                if pd.wasCanceled():
                    aborted = True
                    break
                pd.setValue(i)
                sec = (30 - i + 9) // 10
                pd.setLabelText(f"Starting recording in {sec}s... (Esc to cancel)")
                QApplication.processEvents()
                time.sleep(0.1)
            pd.setValue(30)
            if aborted:
                self._update_status("Run cancelled.")
                return
            self._start_recording()
            if self.recorder is None:
                return

        if self.recorder is None:
            resp = QMessageBox.question(self, "No Recording Active",
                "You're starting a run without recording video. Continue anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if resp == QMessageBox.No:
                return

        while self.serial.read_line_nowait() is not None:
            pass

        message, meta = self._compose_hardware_config()
        self.serial.send_text(message)
        self._record_serial_command("CONFIG", "Run config sent")
        self._hardware_configured = False
        self._awaiting_switch_start = True
        self._hardware_run_active = False
        self._last_hw_tap_ms = None
        self.taps = 0
        self.run_start = None
        self._reset_tap_history()
        self._reset_frame_counters()
        self._last_run_elapsed = 0.0
        self.counters.setText("Taps: 0 | Elapsed: 0 s | Rate10: -- /min | Overall: 0.0 /min")
        try:
            self.live_chart.reset()
        except Exception:
            pass
        try:
            self.run_timer.stop()
        except Exception:
            pass

        meta["source"] = "start_run"
        if use_replicant:
            self.session.replicant_index = 0
            self.session.replicant_progress = 0
            self.session.replicant_running = False
            self._awaiting_replicant_timer = False
            if self.session.replicant_offsets:
                self.live_chart.set_replay_targets(self.session.replicant_offsets)
                self.live_chart.mark_replay_progress(0)
            self._update_replicant_status()
        self._pending_run_metadata = meta
        self._active_serial_port = meta.get("port", self.port_edit.currentText().strip())
        self._initialize_run_logger(force=True)
        self._update_status("Configuration sent. Flip the switch ON to begin the run.")
        self._send_serial_char('e', "Enable motor")

    def _stop_run(self, *_args, from_hardware: bool = False, reason: str | None = None, stop_recording: bool = False):
        try:
            self.run_timer.stop()
        except Exception:
            pass
        
        if stop_recording:
            try:
                self._stop_recording()
            except Exception:
                pass

        try:
            self._finalize_period_calibration()
        except Exception:
            pass
            
        completed_dir = self.run_dir
        completed_meta = self._pending_run_metadata or {}
        completed_run_id = None
        if self.logger:
            try:
                completed_run_id = self.logger.run_id
            except Exception:
                completed_run_id = None
        if completed_run_id is None:
            completed_run_id = completed_meta.get("run_id")
        if self.logger:
            try:
                self.logger.close()
            except Exception:
                pass
            self.logger = None
        
        if self.session.tracking_logger:
            try:
                self.session.tracking_logger.close()
            except Exception:
                pass
            self.session.tracking_logger = None

        if self.run_start is not None:
            try:
                self._last_run_elapsed = max(0.0, time.monotonic() - self.run_start)
            except Exception:
                self._last_run_elapsed = 0.0
        self.run_dir = None
        self.run_start = None
        self._pending_run_metadata = None
        self.session.replicant_running = False
        self.session.replicant_index = 0
        self.session.replicant_progress = 0
        self._awaiting_replicant_timer = False
        self._update_replicant_status()
        
        if not from_hardware:
            try:
                if self.serial.is_open():
                    self._send_serial_char('d', "Disable motor")
            except Exception:
                pass
                
        self._hardware_run_active = False
        self._awaiting_switch_start = False
        self._hardware_configured = False
        self._last_hw_tap_ms = None
        self._flash_only_mode = False
        message = reason or ("Hardware run stopped." if from_hardware else "Run stopped.")
        self._update_status(message)
        self._active_serial_port = ""
        self._first_hw_tap_ms = None
        self._first_host_tap_monotonic = None
        self._last_host_tap_monotonic = None
        self._refresh_statusline()
        if completed_dir and completed_run_id:
            try:
                self.runCompleted.emit(str(completed_run_id), str(completed_dir))
            except Exception:
                pass


class DashboardTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("DashboardRoot")
        self.setAutoFillBackground(True)
        self.library = RunLibrary(RUNS_DIR)
        self.current_summary: Optional[RunSummary] = None
        self.current_times: list[float] = []

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # Run list
        list_panel = QVBoxLayout()
        list_panel.setContentsMargins(0, 0, 0, 0)
        list_panel.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        header_label = QLabel("Runs")
        header_label.setStyleSheet("font-weight:bold;")
        header.addWidget(header_label)
        header.addStretch(1)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_runs)
        header.addWidget(self.refresh_btn)
        list_panel.addLayout(header)

        self.run_list = QListWidget()
        self.run_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.run_list.itemSelectionChanged.connect(self._on_run_selected)
        list_panel.addWidget(self.run_list, 1)

        root.addLayout(list_panel, 0)

        # Detail / chart panel
        detail_panel = QVBoxLayout()
        detail_panel.setContentsMargins(0, 0, 0, 0)
        detail_panel.setSpacing(10)

        self.info_label = QLabel("Select a run to inspect logs and metrics.")
        self.info_label.setWordWrap(True)
        self.info_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        detail_panel.addWidget(self.info_label)

        # Chart reuse LiveChart
        self.chart_frame = QFrame()
        self.chart_frame.setStyleSheet(f"background: {BG}; border: 1px solid {BORDER};")
        self.chart_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        chart_layout = QVBoxLayout(self.chart_frame)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_layout.setSpacing(0)
        self.chart = LiveChart(font_family=_FONT_FAMILY, theme=active_theme())
        chart_layout.addWidget(self.chart.canvas)
        chart_controls = QHBoxLayout()
        chart_controls.setContentsMargins(0, 4, 0, 0)
        chart_controls.setSpacing(6)
        self.long_mode_combo = QComboBox()
        self.long_mode_combo.addItem("Tap Raster", "taps")
        self.long_mode_combo.addItem("Contraction Heatmap", "contraction")
        self.long_mode_combo.currentIndexChanged.connect(self._on_chart_long_mode_changed)
        self.long_mode_combo.setVisible(False)
        chart_controls.addWidget(self.long_mode_combo)
        palette_label = QLabel("Heatmap palette:")
        self.chart_palette_combo = QComboBox()
        for palette in LiveChart.PALETTES:
            self.chart_palette_combo.addItem(palette.capitalize(), palette)
        idx_palette = self.chart_palette_combo.findData(self.chart.heatmap_palette)
        if idx_palette != -1:
            self.chart_palette_combo.setCurrentIndex(idx_palette)
        self.chart_palette_combo.currentIndexChanged.connect(self._on_chart_palette_changed)
        self.chart_palette_combo.setEnabled(self.chart.heatmap_active())
        palette_box = QWidget()
        palette_box_layout = QHBoxLayout(palette_box)
        palette_box_layout.setContentsMargins(0, 0, 0, 0)
        palette_box_layout.setSpacing(6)
        palette_box_layout.addWidget(palette_label)
        palette_box_layout.addWidget(self.chart_palette_combo)
        self.chart_palette_box = palette_box
        palette_box.setVisible(self.chart.heatmap_active())
        self.chart_export_btn = QPushButton("Export Plot…")
        self.chart_export_btn.clicked.connect(self._export_plot_image)
        self.chart_export_btn.setEnabled(False)
        chart_controls.addWidget(palette_box)
        chart_controls.addStretch(1)
        chart_controls.addWidget(self.chart_export_btn)
        chart_layout.addLayout(chart_controls)
        self.chart.add_long_mode_listener(self._on_chart_long_mode_state)
        self.chart.add_heatmap_listener(self._on_chart_heatmap_mode_changed)
        detail_panel.addWidget(self.chart_frame, 1)

        # Action buttons
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        self.open_btn = QPushButton("Open Folder")
        self.open_btn.clicked.connect(self._open_run_folder)
        self.analyze_btn = QPushButton("Analyze Run")
        self.analyze_btn.clicked.connect(self._analyze_run)
        self.export_btn = QPushButton("Export CSV…")
        self.export_btn.clicked.connect(self._export_run_csv)
        self.delete_btn = QPushButton("Delete…")
        self.delete_btn.clicked.connect(self._delete_run)
        for btn in (self.open_btn, self.analyze_btn, self.export_btn, self.delete_btn):
            btn.setEnabled(False)
        action_row.addWidget(self.open_btn)
        action_row.addWidget(self.analyze_btn)
        action_row.addWidget(self.export_btn)
        action_row.addWidget(self.delete_btn)
        action_row.addStretch(1)
        detail_panel.addLayout(action_row)

        root.addLayout(detail_panel, 1)

        self.refresh_runs()
        self.set_theme(active_theme())

    # Run list management

    def _analyze_run(self):
        summary = self.current_summary
        if not summary:
            return
        
        self.info_label.setText(f"Analyzing {summary.run_id}...")
        QApplication.processEvents()
        
        analyzer = RunAnalyzer(summary.path)
        results = analyzer.analyze()
        
        if results:
            self.info_label.setText(f"Analysis complete for {summary.run_id}.\n"
                                    f"Processed {len(results['taps'])} taps.")
            QMessageBox.information(self, "Analysis Complete", 
                                    f"Successfully analyzed {len(results['taps'])} taps.\n"
                                    f"Saved to {summary.path / 'analysis.json'}")
            # Here we could reload the chart with the new data if we parse analysis.json
        else:
            self.info_label.setText("Analysis failed. Check logs.")
            QMessageBox.warning(self, "Analysis Failed", "Could not analyze run. Ensure tracking.csv exists.")

    def refresh_runs(self, *_args, select_run: Optional[str] = None):
        current_target = select_run or (self.current_summary.run_id if self.current_summary else None)
        self.run_list.blockSignals(True)
        self.run_list.clear()
        runs = self.library.list_runs()
        target_row = 0
        for idx, summary in enumerate(runs):
            item = QListWidgetItem(summary.run_id)
            item.setData(Qt.UserRole, summary)
            self.run_list.addItem(item)
            if current_target and (summary.run_id == current_target or summary.path.name == current_target):
                target_row = idx
        self.run_list.blockSignals(False)
        if runs:
            self.run_list.setCurrentRow(target_row)
        else:
            self._set_current_summary(None)

    def _on_run_selected(self):
        items = self.run_list.selectedItems()
        count = len(items)
        self.open_btn.setEnabled(count == 1)
        self.analyze_btn.setEnabled(count == 1)
        self.export_btn.setEnabled(count >= 1)
        self.delete_btn.setEnabled(count >= 1)
        if hasattr(self, "chart_export_btn"):
            self.chart_export_btn.setEnabled(count == 1)
        if count == 0:
            self._set_current_summary(None)
            return
        if count == 1:
            item = items[0]
            summary = item.data(Qt.UserRole) if item else None
            self._set_current_summary(summary)
            return
        summaries = [item.data(Qt.UserRole) for item in items if item and item.data(Qt.UserRole)]
        self.current_summary = None
        self.current_times = []
        self.chart.reset()
        self.chart.set_contraction_heatmap(None)
        if not summaries:
            self.info_label.setText("Select a run to inspect logs and metrics.")
            return
        sample_ids = ", ".join(s.run_id for s in summaries[:4])
        if len(summaries) > 4:
            sample_ids += ", …"
        self.info_label.setText(
            f"{len(summaries)} runs selected. Export creates tap logs for each run; Delete removes their folders.\n"
            f"Selected preview: {sample_ids}"
        )

    def _set_current_summary(self, summary: Optional[RunSummary]):
        self.current_summary = summary
        self.current_times = []
        if summary is None:
            self.info_label.setText("Select a run to inspect logs and metrics.")
            self.chart.reset()
            self.chart.set_contraction_heatmap(None)
            if hasattr(self, "chart_export_btn"):
                self.chart_export_btn.setEnabled(False)
            return

        self.export_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        self.info_label.setText(self._format_summary(summary))
        heatmap = self._load_contraction_heatmap(summary)
        self.chart.set_contraction_heatmap(heatmap)
        self.current_times = self._load_run_times(summary)
        if self.current_times:
            self.chart.set_times(self.current_times)
        else:
            self.chart.reset()
        if hasattr(self, "chart_export_btn"):
            self.chart_export_btn.setEnabled(True)

    def _selected_summaries(self) -> list[RunSummary]:
        summaries: list[RunSummary] = []
        for item in self.run_list.selectedItems():
            if not item:
                continue
            summary = item.data(Qt.UserRole)
            if isinstance(summary, RunSummary):
                summaries.append(summary)
        return summaries

    def _format_summary(self, summary: RunSummary) -> str:
        parts = [f"<b>{summary.run_id}</b>"]
        if summary.started_at:
            parts.append(f"Started: {summary.started_at}")
        if summary.duration_s is not None:
            parts.append(f"Duration: {summary.duration_s/60:.1f} min")
        if summary.taps_count is not None:
            parts.append(f"Taps: {summary.taps_count}")
        if summary.mode:
            if summary.mode == "Periodic" and summary.period_sec:
                parts.append(f"Mode: Periodic ({summary.period_sec:.2f}s)")
            elif summary.mode == "Poisson" and summary.lambda_rpm:
                parts.append(f"Mode: Poisson ({summary.lambda_rpm:.2f}/min)")
            else:
                parts.append(f"Mode: {summary.mode}")
        if summary.stepsize is not None:
            parts.append(f"Stepsize: {summary.stepsize}")
        if summary.serial_port:
            parts.append(f"Serial: {summary.serial_port}")
        return "<br>".join(parts)

    def _load_run_times(self, summary: RunSummary) -> list[float]:
        taps_path = summary.path / "taps.csv"
        times: list[float] = []
        if not taps_path.exists():
            return times
        try:
            with taps_path.open("r", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                first_host = None
                for row in reader:
                    t_ms = float(row.get("t_host_ms", 0.0))
                    if first_host is None:
                        first_host = t_ms
                    times.append((t_ms - first_host) / 1000.0)
        except Exception:
            return []
        return times

    def _on_chart_long_mode_state(self, active: bool):
        if not hasattr(self, "long_mode_combo"):
            return
        combo = self.long_mode_combo
        combo.blockSignals(True)
        if active:
            view = self.chart.long_run_view()
            idx = combo.findData(view)
            if idx < 0:
                idx = 0
            combo.setCurrentIndex(idx)
            combo.setVisible(True)
        else:
            combo.setCurrentIndex(0)
            combo.setVisible(False)
        combo.blockSignals(False)

    def _on_chart_long_mode_changed(self, index: int):
        if not hasattr(self, "long_mode_combo"):
            return
        combo = self.long_mode_combo
        if not combo.isVisible():
            return
        view = combo.itemData(index)
        if not view:
            return
        self.chart.set_long_run_view(str(view))


    def _load_contraction_heatmap(self, summary: RunSummary):
        analysis_path = summary.path / "analysis.json"
        if analysis_path.exists():
            try:
                with analysis_path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                matrix = data.get("contraction_heatmap")
                if isinstance(matrix, list):
                    return matrix
            except Exception:
                pass
        csv_path = summary.path / "contraction_heatmap.csv"
        if csv_path.exists():
            try:
                rows: list[list[float]] = []
                with csv_path.open("r", encoding="utf-8", newline="") as fh:
                    reader = csv.reader(fh)
                    for row in reader:
                        if row:
                            rows.append([float(value) for value in row])
                if rows:
                    return rows
            except Exception:
                pass
        return None

    def _on_chart_palette_changed(self, index: int):
        data = self.chart_palette_combo.itemData(index)
        if not data:
            return
        self.chart.set_heatmap_palette(str(data))

    def _on_chart_heatmap_mode_changed(self, active: bool):
        if hasattr(self, "chart_palette_box"):
            self.chart_palette_box.setVisible(active)
        if hasattr(self, "chart_palette_combo"):
            self.chart_palette_combo.setEnabled(active)

    def _export_plot_image(self):
        summary = self.current_summary
        if summary is None:
            QMessageBox.information(self, "Dashboard", "Select a run first.")
            return
        default_path = summary.path / f"{summary.run_id}_plot.png"
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Export plot",
            str(default_path),
            "PNG Image (*.png);;PDF Document (*.pdf);;SVG Vector (*.svg)"
        )
        if not dest:
            return
        try:
            self.chart.save(dest)
        except Exception as exc:
            QMessageBox.warning(self, "Export Plot", f"Failed to export plot: {exc}")
            return
        QMessageBox.information(self, "Export Plot", f"Plot exported → {dest}")

    # Actions

    def _open_run_folder(self):
        summaries = self._selected_summaries()
        if not summaries:
            QMessageBox.information(self, "Dashboard", "Select a run first.")
            return
        target = summaries[0]
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.path.resolve())))

    def _export_run_csv(self):
        summaries = self._selected_summaries()
        if not summaries:
            QMessageBox.information(self, "Dashboard", "Select at least one run to export.")
            return
        if len(summaries) == 1:
            summary = summaries[0]
            dest, _ = QFileDialog.getSaveFileName(
                self,
                "Export taps.csv",
                str(summary.path / "taps.csv"),
                "CSV Files (*.csv)",
            )
            if not dest:
                return
            try:
                shutil.copy2(summary.path / "taps.csv", dest)
            except Exception as exc:
                QMessageBox.warning(self, "Export", f"Failed to export CSV: {exc}")
            return

        dest_dir = QFileDialog.getExistingDirectory(self, "Choose export folder")
        if not dest_dir:
            return
        export_root = Path(dest_dir)
        failures: list[str] = []
        exported = 0
        for summary in summaries:
            src = summary.path / "taps.csv"
            if not src.exists():
                failures.append(f"{summary.run_id}: taps.csv missing")
                continue
            dest_path = export_root / f"{summary.run_id}.csv"
            try:
                shutil.copy2(src, dest_path)
                exported += 1
            except Exception as exc:
                failures.append(f"{summary.run_id}: {exc}")
        if failures:
            QMessageBox.warning(self, "Export", "Some exports failed:\n" + "\n".join(failures[:6]))
        if exported:
            QMessageBox.information(self, "Export", f"Exported {exported} CSV files to {export_root}")

    def _delete_run(self):
        summaries = self._selected_summaries()
        if not summaries:
            QMessageBox.information(self, "Dashboard", "Select at least one run to delete.")
            return
        if len(summaries) == 1:
            summary = summaries[0]
            prompt = f"Delete run '{summary.run_id}'? This cannot be undone."
        else:
            prompt = f"Delete {len(summaries)} runs? This cannot be undone."
        resp = QMessageBox.question(
            self,
            "Delete Run",
            prompt,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        failures: list[str] = []
        deleted = 0
        for summary in summaries:
            try:
                shutil.rmtree(summary.path)
                deleted += 1
            except Exception as exc:
                failures.append(f"{summary.run_id}: {exc}")
        if failures:
            QMessageBox.warning(self, "Delete", "Some deletions failed:\n" + "\n".join(failures[:6]))
        if deleted:
            self.refresh_runs()

    def set_theme(self, theme: dict[str, str]):
        bg = theme.get("BG", BG)
        text = theme.get("TEXT", TEXT)
        accent = theme.get("ACCENT", ACCENT)
        border = theme.get("BORDER", BORDER)
        mid = theme.get("MID", MID)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(bg))
        self.setPalette(pal)
        self.info_label.setStyleSheet(f"color: {text};")
        self.chart_frame.setStyleSheet(f"background: {bg}; border: 1px solid {border};")
        list_style = (
            f"QListWidget {{background: {mid}; color: {text}; border: 1px solid {border};}}\n"
            f"QListWidget::item:selected {{background: {accent}; color: {bg}; border: 1px solid {accent};}}"
        )
        self.run_list.setStyleSheet(list_style.strip())
        button_style = (
            f"QPushButton {{background: {mid}; color: {text}; border: 1px solid {theme.get('BUTTON_BORDER', border)}; padding: 4px 10px; border-radius: 0px;}}\n"
            f"QPushButton:hover {{background: {accent}; color: {bg}; border-color: {accent}; border-radius: 0px;}}"
        )
        for btn in (self.refresh_btn, self.open_btn, self.analyze_btn, self.export_btn, self.delete_btn):
            btn.setStyleSheet(button_style.strip())
        self.chart.set_theme(theme)


def _run_tab_auto_detect_serial_port(self) -> str | None:
    try:
        ports = list(list_ports.comports())
    except Exception:
        ports = []
    if not ports:
        return None
    preferred = [
        "cu.usbmodem", "tty.usbmodem", "cu.usbserial", "tty.usbserial",
        "ttyacm", "ttyusb"
    ]

    def port_score(name: str) -> int:
        lower = name.lower()
        for idx, prefix in enumerate(preferred):
            if prefix in lower:
                return len(preferred) - idx
        if lower.startswith("com"):
            return 1
        return 0

    best = None
    best_score = -1
    for info in ports:
        name = info.device
        score = port_score(name)
        if score > best_score:
            best_score = score
            best = name
    if best:
        return best
    return ports[0].device


def _run_tab_refresh_serial_ports(self, initial: bool = False):
    try:
        ports = list(list_ports.comports())
    except Exception:
        ports = []
    existing = {self.port_edit.itemText(i) for i in range(self.port_edit.count())}
    for info in ports:
        name = info.device
        if name not in existing:
            self.port_edit.addItem(name)
            existing.add(name)
    if initial and ports:
        autodetected = self._auto_detect_serial_port()
        if autodetected:
            idx = self.port_edit.findText(autodetected, Qt.MatchFixedString)
            if idx == -1:
                self.port_edit.addItem(autodetected)
                idx = self.port_edit.findText(autodetected, Qt.MatchFixedString)
            if idx != -1:
                self.port_edit.setCurrentIndex(idx)


RunTab._auto_detect_serial_port = _run_tab_auto_detect_serial_port
RunTab._refresh_serial_ports = _run_tab_refresh_serial_ports


def _run_tab_adjust_min_window_size(self):
    try:
        content = self.app_view._content if hasattr(self.app_view, '_content') else None
        if content is None:
            return
        min_hint = content.minimumSizeHint()
        if not min_hint.isValid() or min_hint.width() <= 0:
            min_hint = content.sizeHint()
        vw = self.app_view.viewport().width()
        vh = self.app_view.viewport().height()
        aw = self.app_view.width()
        ah = self.app_view.height()
        delta_w = max(0, aw - vw)
        delta_h = max(0, ah - vh)
        extra_w = self.width() - self.centralWidgetWidth() if hasattr(self, 'centralWidgetWidth') else 0
        extra_h = self.height() - self.centralWidgetHeight() if hasattr(self, 'centralWidgetHeight') else 0
        min_w = max(900, min_hint.width() + delta_w + extra_w)
        min_h = max(540, min_hint.height() + delta_h + extra_h)
        self.setMinimumSize(min_w, min_h)
    except Exception:
        pass


def _run_tab_init_splitter_balance(self):
    split = getattr(self, 'splitter', None)
    if split is None:
        return
    try:
        # Give video pane (left) massive preference so it takes all available slack
        # Control pane (right) just needs its minimum width (approx 380)
        split.setSizes([100000, 380])
    except Exception:
        pass


def _run_tab_apply_titlebar_theme(self):
    handle = None
    try:
        handle = self.windowHandle()
    except Exception:
        handle = None
    applied = False
    if handle is not None:
        try:
            handle.setTitleBarColor(QColor(BG))
            if hasattr(handle, "setTitleBarAutoTint"):
                handle.setTitleBarAutoTint(False)
            applied = True
        except Exception:
            applied = False
    if not applied:
        try:
            _set_macos_titlebar_appearance(self, QColor(BG))
        except Exception:
            pass


RunTab._adjust_min_window_size = _run_tab_adjust_min_window_size
RunTab._init_splitter_balance = _run_tab_init_splitter_balance
RunTab._apply_titlebar_theme = _run_tab_apply_titlebar_theme


def _run_tab_refresh_statusline(self):
    run_id = self.logger.run_id if self.logger else "-"
    cam_idx = self.cam_index.value()
    fps = int(self.preview_fps or 0)
    rec = "REC ON" if self.recorder else "REC OFF"
    port = self.port_edit.currentText().strip() if self.serial.is_open() else "—"
    serial_state = f"serial:{port}" if self.serial.is_open() else "serial:DISCONNECTED"
    mode = self.mode.currentText()
    param = f"P={self.period_sec.value():.2f}s" if mode == "Periodic" else f"λ={self.lambda_rpm.value():.2f}/min"
    taps = self.taps
    if self.run_start:
        elapsed = time.monotonic() - self.run_start
    else:
        elapsed = self._last_run_elapsed
    overall_rate = (taps / elapsed * 60.0) if elapsed > 0 else 0.0
    recent_rate = self._recent_rate_per_min()
    recent_str = f"{recent_rate:5.2f}" if recent_rate is not None else "  --"
    overall_str = f"{overall_rate:5.2f}" if elapsed > 0 else "  --"
    elapsed_sec = int(round(elapsed))
    txt = (
        f"{run_id}  •  cam {cam_idx}/{fps}fps  •  {rec}  •  {serial_state}  •  {mode} {param}"
        f"  •  taps:{taps}  •  t+{elapsed_sec:6d}s  •  rate10:{recent_str}/min  •  avg:{overall_str}/min"
    )
    self.statusline.setText(txt)


def _run_tab_update_status(self, msg: str):
    self.status.setText(msg)


RunTab._refresh_statusline = _run_tab_refresh_statusline
RunTab._update_status = _run_tab_update_status


def _run_tab_load_calibration(self) -> dict[str, float]:
    existing_paths: list[Path] = []
    for path in self._calibration_paths:
        try:
            if path.exists():
                existing_paths.append(path)
        except Exception:
            continue
    existing_paths.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)
    for path in existing_paths or self._calibration_paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                calibrated: dict[str, float] = {}
                for key, value in data.items():
                    try:
                        calibrated[str(key)] = float(value)
                    except Exception:
                        continue
                self._active_calibration_path = path
                return calibrated
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return {}


def _run_tab_save_calibration(self) -> None:
    for path in self._calibration_paths:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._period_calibration, f, indent=2)
            self._active_calibration_path = path
            return
        except PermissionError:
            continue
        except OSError:
            continue
    self._update_status("Calibration save failed (check permissions).")


def _run_tab_normalized_port_key(port: str) -> str:
    if not port:
        return ""
    base = port.rstrip('0123456789')
    return base if base else port


def _run_tab_lookup_period_calibration(self, port: str) -> float:
    if not port:
        return 1.0
    if port in self._period_calibration:
        return float(self._period_calibration[port])
    key = _run_tab_normalized_port_key(port)
    if key in self._period_calibration:
        return float(self._period_calibration[key])
    if key:
        for existing_key, value in self._period_calibration.items():
            if existing_key.startswith(key):
                return float(value)
    return 1.0


def _run_tab_finalize_period_calibration(self):
    if self.logger is None:
        return
    port = self._active_serial_port.strip()
    if not port:
        return
    if self.mode.currentText() != "Periodic":
        return
    if self._first_hw_tap_ms is None or self._last_hw_tap_ms is None:
        return
    if self._first_host_tap_monotonic is None or self._last_host_tap_monotonic is None:
        return
    board_elapsed_ms = self._last_hw_tap_ms - self._first_hw_tap_ms
    host_elapsed = self._last_host_tap_monotonic - self._first_host_tap_monotonic
    if board_elapsed_ms <= 0 or host_elapsed <= 0:
        return
    if host_elapsed < 30.0:
        return
    host_elapsed_ms = host_elapsed * 1000.0
    raw_factor = board_elapsed_ms / host_elapsed_ms
    factor = max(0.95, min(1.05, raw_factor))
    existing = float(self._period_calibration.get(port, _run_tab_lookup_period_calibration(self, port)))
    if abs(factor - existing) < 1e-4:
        return
    self._period_calibration[port] = factor
    norm_key = _run_tab_normalized_port_key(port)
    if norm_key and norm_key != port:
        self._period_calibration[norm_key] = factor
    if norm_key:
        for key in list(self._period_calibration.keys()):
            if key not in {port, norm_key} and key.startswith(norm_key):
                self._period_calibration[key] = factor
    _run_tab_save_calibration(self)
    if abs(factor - 1.0) < 1e-4:
        self._update_status(f"Calibration reset for {port} (x{factor:.6f})")
    else:
        self._update_status(f"Calibration updated for {port}: x{factor:.6f} (raw {raw_factor:.6f})")


def _run_tab_handle_frame(self, frame, frame_idx=0, timestamp=0.0):
    if self.cap is None or frame is None:
        return
    
    # Create overlay surface
    overlay = frame.copy()
    rgb = cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    bytes_per_line = ch * w
    qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
    pix = QPixmap.fromImage(qimg)
    
    # Draw CV Results
    self._draw_cv_overlay(pix)
    
    self._preview_frame_counter = frame_idx
    
    # Legacy timestamp (optional, but CV overlay is better)
    try:
        if self.run_start and not self.show_cv_check.isChecked():
             text = f"T+{(time.monotonic()-self.run_start):8.3f}s"
             # We can't draw on pixmap with cv2 logic here, skipping legacy overlay if CV is off
             pass
    except Exception:
        pass

    h, w = overlay.shape[:2]
    if w and h:
        self._maybe_update_preview_aspect(w, h)
        
    self.video_view.set_image(pix)
    if self._pip_window:
        self._pip_window.set_pixmap(pix)
        
    if self.recorder:
        self._recorded_frame_counter = frame_idx
        self.recorder.write(frame) # Write clean frame

def _run_tab_on_cv_results(self, results, frame_idx, timestamp, mask):
    self.session.cv_results = results
    self.session.cv_mask = mask
    if self.session.tracking_logger:
        self.session.tracking_logger.log_frame(frame_idx, timestamp, results)

def _run_tab_draw_cv_overlay(self, pixmap: QPixmap):
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

def _run_tab_start_frame_stream(self):
    worker = getattr(self, "_frame_worker", None)
    if worker is not None and not worker.is_alive():
        self._cleanup_frame_stream()
        worker = self._frame_worker
    if self.cap is None or self._frame_worker is not None:
        return
    interval = int(1000 / max(1, self.preview_fps))
    self._frame_worker = FrameWorker(self.cap, interval)
    self._frame_worker.frameReady.connect(self._handle_frame, Qt.QueuedConnection)
    
    # Feed CV Bot
    if hasattr(self, 'cv_worker'):
            self._frame_worker.frameReady.connect(self.cv_worker.process_frame, Qt.QueuedConnection)
            
    self._frame_worker.error.connect(self._update_status, Qt.QueuedConnection)
    self._frame_worker.stopped.connect(self._cleanup_frame_stream, Qt.QueuedConnection)
    self._frame_worker.start()


def _run_tab_stop_frame_stream(self):
    worker = self._frame_worker
    if worker:
        stopped = worker.stop()
        if stopped:
            self._cleanup_frame_stream()


def _run_tab_cleanup_frame_stream(self):
    worker = self._frame_worker
    if worker is None:
        return
    if worker.is_alive():
        return
    try:
        worker.frameReady.disconnect(self._handle_frame)
    except Exception:
        pass
    try:
        worker.error.disconnect(self._update_status)
    except Exception:
        pass
    try:
        worker.stopped.disconnect(self._cleanup_frame_stream)
    except Exception:
        pass
    try:
        worker.deleteLater()
    except Exception:
        pass
    self._frame_worker = None


def _run_tab_on_port_text_changed(self, text: str):
    text = text.strip()
    self._active_serial_port = text


RunTab._on_port_text_changed = _run_tab_on_port_text_changed
RunTab._load_calibration = _run_tab_load_calibration
RunTab._save_calibration = _run_tab_save_calibration
RunTab._lookup_period_calibration = _run_tab_lookup_period_calibration
RunTab._finalize_period_calibration = _run_tab_finalize_period_calibration
RunTab._normalized_port_key = staticmethod(_run_tab_normalized_port_key)
RunTab._handle_frame = _run_tab_handle_frame
RunTab._start_frame_stream = _run_tab_start_frame_stream
RunTab._stop_frame_stream = _run_tab_stop_frame_stream
RunTab._cleanup_frame_stream = _run_tab_cleanup_frame_stream
RunTab._on_cv_results = _run_tab_on_cv_results
RunTab._draw_cv_overlay = _run_tab_draw_cv_overlay


def _run_tab_shutdown(self):
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


RunTab.shutdown = _run_tab_shutdown


class App(QWidget):
    def __init__(self):
        super().__init__()
        global _APP_ICON
        self.setWindowTitle(f"NEMESIS {APP_VERSION} — Non-periodic Event Monitoring & Evaluation of Stimulus-Induced States")
        if _APP_ICON is not None:
            self.setWindowIcon(_APP_ICON)
        self.resize(1320, 820)
        self.setMinimumSize(1280, 780)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.resource_registry = ResourceRegistry()
        self._run_tab_counter = 1
        self._run_tab_custom_names: dict[RunTab, Optional[str]] = {}
        self._data_tabs: list[DashboardTab] = []
        self._data_tab_custom_names: dict[DashboardTab, Optional[str]] = {}

        self.tab_widget = QTabWidget()
        self.tab_widget.setDocumentMode(False)
        self.tab_widget.setTabsClosable(True)
        try:
            self.tab_widget.tabCloseRequested.connect(self._handle_tab_close_requested)
        except Exception:
            pass
        try:
            self.tab_widget.tabBarDoubleClicked.connect(self._on_tab_double_clicked)
        except Exception:
            pass
        tab_bar = LeftAlignTabBar()
        self.tab_widget.setTabBar(tab_bar)
        tab_bar.setDrawBase(False)
        tab_bar.setElideMode(Qt.ElideNone)

        run_tab = RunTab(resource_registry=self.resource_registry)
        self._register_run_tab(run_tab)
        self.tab_widget.addTab(run_tab, self._format_run_tab_title(self._run_tab_counter))
        self._run_tab_custom_names[run_tab] = None
        self._run_tab_counter += 1

        self._create_dashboard_tab(initial=True)
        self.tab_widget.setCurrentIndex(0)
        self._refresh_tab_close_buttons()

        self.new_tab_btn = QPushButton("+ Tab")
        self.new_tab_btn.setCursor(Qt.PointingHandCursor)
        self.new_tab_btn.setToolTip("Open a new tab")
        self.new_tab_btn.clicked.connect(self._show_new_tab_menu)
        self.tab_widget.setCornerWidget(self.new_tab_btn, Qt.TopRightCorner)
        self._apply_theme_to_corner_button()
        layout.addWidget(self.tab_widget)
        self._tab_chord_active = False
        self._tab_chord_triggered = False

    def keyPressEvent(self, event):
        modifiers = event.modifiers()
        key = event.key()
        is_cmd = bool(modifiers & Qt.MetaModifier)
        is_ctrl = bool(modifiers & Qt.ControlModifier)
        is_alt = bool(modifiers & Qt.AltModifier)
        handled = False
        if is_cmd or is_ctrl:
            if self._tab_chord_active and key in (Qt.Key_R, Qt.Key_F):
                if key == Qt.Key_R:
                    self._create_run_tab()
                else:
                    self._create_dashboard_tab()
                self._tab_chord_active = False
                self._tab_chord_triggered = True
                handled = True
            elif key == Qt.Key_T:
                self._tab_chord_active = True
                self._tab_chord_triggered = False
                handled = True
            elif key == Qt.Key_W:
                self._close_current_tab_with_prompt()
                handled = True
            elif is_alt and key in (Qt.Key_Left, Qt.Key_Right):
                self._cycle_tabs(-1 if key == Qt.Key_Left else 1)
                handled = True
            else:
                if self._tab_chord_active:
                    self._tab_chord_active = False
                    self._tab_chord_triggered = False
        else:
            if self._tab_chord_active:
                self._tab_chord_active = False
                self._tab_chord_triggered = False
        if handled:
            event.accept()
            return
        widget = self.tab_widget.currentWidget()
        if isinstance(widget, RunTab):
            widget.keyPressEvent(event)
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        key = event.key()
        if self._tab_chord_active and key == Qt.Key_T:
            if not self._tab_chord_triggered:
                self._tab_chord_active = False
                self._tab_chord_triggered = False
                self._show_new_tab_menu()
            else:
                self._tab_chord_active = False
                self._tab_chord_triggered = False
            event.accept()
            return
        if key in (Qt.Key_Meta, Qt.Key_Control):
            self._tab_chord_active = False
            self._tab_chord_triggered = False
        super().keyReleaseEvent(event)

    def _register_run_tab(self, tab: RunTab):
        try:
            tab.runCompleted.connect(self._on_run_completed)
        except Exception:
            pass
        try:
            tab.themeChanged.connect(self._on_theme_changed)
        except Exception:
            pass
        try:
            tab.apply_theme_external(_ACTIVE_THEME_NAME)
        except Exception:
            pass

    @Slot(str, str)
    def _on_run_completed(self, run_id: str, run_path: str):
        if self._data_tabs:
            try:
                self._data_tabs[0].refresh_runs(select_run=run_id)
            except Exception:
                pass

    @Slot(str)
    def _on_theme_changed(self, name: str):
        self._propagate_theme(name, source=self.sender())

    def _propagate_theme(self, name: str, source: Optional[QObject] = None):
        for idx in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(idx)
            if isinstance(widget, RunTab) and widget is not source:
                try:
                    widget.apply_theme_external(name)
                except Exception:
                    pass
            elif isinstance(widget, DashboardTab):
                try:
                    widget.set_theme(active_theme())
                except Exception:
                    pass
        self._apply_theme_to_corner_button()
        tab_bar = self.tab_widget.tabBar()
        if tab_bar is not None:
            tab_bar.setDrawBase(False)
            tab_bar.setElideMode(Qt.ElideNone)
            tab_bar.update()
        self._update_tab_close_button_styles()

    def _format_run_tab_title(self, index: int) -> str:
        return f"Run {index}"

    def _format_dashboard_tab_title(self, index: int) -> str:
        return f"Data {index}"

    @Slot()
    def _show_new_tab_menu(self):
        menu = QMenu(self)
        action_run = menu.addAction("Run Tab")
        action_dash = menu.addAction("Data Tab")
        global_pos = self.new_tab_btn.mapToGlobal(QPoint(self.new_tab_btn.width(), self.new_tab_btn.height()))
        chosen = menu.exec(global_pos)
        if chosen is action_run:
            self._create_run_tab()
        elif chosen is action_dash:
            self._create_dashboard_tab()

    def _create_run_tab(self):
        tab = RunTab(resource_registry=self.resource_registry)
        self._register_run_tab(tab)
        insert_index = self._first_data_tab_index()
        if insert_index == -1:
            insert_index = self.tab_widget.count()
        self.tab_widget.insertTab(insert_index, tab, self._format_run_tab_title(self._run_tab_counter))
        self.tab_widget.setCurrentWidget(tab)
        self._run_tab_custom_names[tab] = None
        self._run_tab_counter += 1
        self._refresh_tab_close_buttons()

    def _create_dashboard_tab(self, initial: bool = False):
        tab = DashboardTab()
        try:
            tab.set_theme(active_theme())
        except Exception:
            pass
        self._data_tabs.append(tab)
        self._data_tab_custom_names[tab] = None
        default_title = self._format_dashboard_tab_title(len(self._data_tabs))
        self.tab_widget.addTab(tab, default_title)
        if not initial:
            self.tab_widget.setCurrentWidget(tab)
        self._refresh_tab_close_buttons()
        return tab

    @Slot(int)
    def _handle_tab_close_requested(self, index: int):
        self._request_close_tab(index, prompt=True)

    def _request_close_tab(self, index: int, prompt: bool = True):
        if self.tab_widget.count() <= 1:
            return
        widget = self.tab_widget.widget(index)
        if widget is None:
            return
        if isinstance(widget, RunTab) and prompt and self._run_tab_has_active_state(widget):
            reply = QMessageBox.question(
                self,
                "Close Run Tab",
                "Closing this run tab will stop any active hardware links, recording, or logging. Continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                self._refresh_tab_close_buttons()
                return
        if isinstance(widget, RunTab):
            try:
                widget.shutdown()
            except Exception:
                pass
        self.tab_widget.removeTab(index)
        if isinstance(widget, RunTab):
            self._run_tab_custom_names.pop(widget, None)
        elif isinstance(widget, DashboardTab):
            if widget in self._data_tabs:
                self._data_tabs.remove(widget)
            self._data_tab_custom_names.pop(widget, None)
        if widget is not None:
            widget.deleteLater()
        self._refresh_tab_close_buttons()

    def _run_tab_has_active_state(self, tab: RunTab) -> bool:
        try:
            session = tab.session
        except Exception:
            return False
        return bool(
            getattr(session, "hardware_run_active", False)
            or getattr(session, "awaiting_switch_start", False)
            or getattr(session, "logger", None)
            or tab.cap is not None
            or tab.recorder is not None
            or tab.serial.is_open()
        )

    def _close_current_tab_with_prompt(self):
        index = self.tab_widget.currentIndex()
        self._request_close_tab(index, prompt=True)

    def _cycle_tabs(self, direction: int):
        count = self.tab_widget.count()
        if count <= 1:
            return
        current = self.tab_widget.currentIndex()
        next_index = (current + direction) % count
        self.tab_widget.setCurrentIndex(next_index)

    def _refresh_tab_close_buttons(self):
        tab_bar = self.tab_widget.tabBar()
        if tab_bar is None:
            return
        total = self.tab_widget.count()
        for idx in range(total):
            widget = self.tab_widget.widget(idx)
            if widget is None:
                continue
            if total <= 1:
                tab_bar.setTabButton(idx, QTabBar.RightSide, None)
                continue
            self._ensure_close_button(idx, widget)
        self._update_run_tab_titles()
        self._update_data_tab_titles()
        self._update_tab_close_button_styles()
        self._apply_theme_to_corner_button()

    def _apply_theme_to_corner_button(self):
        if not hasattr(self, "new_tab_btn") or self.new_tab_btn is None:
            return
        theme = active_theme()
        border = theme.get("BUTTON_BORDER", BORDER)
        text = theme.get("TEXT", TEXT)
        base = theme.get("MID", MID)
        accent = theme.get("ACCENT", ACCENT)
        base_bg = base
        hover_fg = theme.get("BG", BG)
        style = f"""
        QPushButton {{
            margin: 6px;
            padding: 4px 12px;
            border-radius: 0px;
            border: 1px solid {border};
            background: {base_bg};
            color: {text};
        }}
        QPushButton:hover {{
            background: {accent};
            color: {hover_fg};
            border-color: {accent};
        }}
        """
        self.new_tab_btn.setStyleSheet(style.strip())
        self._update_tab_close_button_styles()

    def _ensure_close_button(self, index: int, widget: QWidget):
        tab_bar = self.tab_widget.tabBar()
        if tab_bar is None:
            return
        button = tab_bar.tabButton(index, QTabBar.RightSide)
        if not isinstance(button, QToolButton):
            button = QToolButton(tab_bar)
            button.setAutoRaise(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setText("×")
            button.setToolTip("Close tab")
            button.clicked.connect(lambda _=False, w=widget: self._request_close_widget(w))
            tab_bar.setTabButton(index, QTabBar.RightSide, button)
        self._style_tab_close_button(button)

    def _style_tab_close_button(self, button: QToolButton):
        theme = active_theme()
        button.setFixedSize(12, 12)
        button.setStyleSheet(
            "QToolButton {"
            "border: none;"
            "background: transparent;"
            f"color: {theme.get('TEXT', TEXT)};"
            "font-size: 10px;"
            "padding: 0px;"
            "margin: 0px;"
            "}"
            "QToolButton:hover {"
            f"background: {theme.get('ACCENT', ACCENT)};"
            f"color: {theme.get('BG', BG)};"
            "border-radius: 0px;"
            "}"
        )

    def _update_tab_close_button_styles(self):
        tab_bar = self.tab_widget.tabBar()
        if tab_bar is None:
            return
        for idx in range(self.tab_widget.count()):
            button = tab_bar.tabButton(idx, QTabBar.RightSide)
            if isinstance(button, QToolButton):
                self._style_tab_close_button(button)

    def _request_close_widget(self, widget: QWidget):
        idx = self.tab_widget.indexOf(widget)
        if idx != -1:
            self._request_close_tab(idx, prompt=True)

    def _first_data_tab_index(self) -> int:
        indices = [self.tab_widget.indexOf(tab) for tab in self._data_tabs]
        indices = [idx for idx in indices if idx != -1]
        return min(indices) if indices else -1

    def _update_data_tab_titles(self):
        ordered = sorted(
            ((self.tab_widget.indexOf(tab), tab) for tab in self._data_tabs),
            key=lambda pair: pair[0],
        )
        for position, (idx, tab) in enumerate(ordered, start=1):
            if idx == -1:
                continue
            custom = self._data_tab_custom_names.get(tab)
            title = custom.strip() if custom else self._format_dashboard_tab_title(position)
            self.tab_widget.setTabText(idx, title)

    def _update_run_tab_titles(self):
        counter = 1
        for idx in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(idx)
            if isinstance(widget, RunTab):
                custom = self._run_tab_custom_names.get(widget)
                title = custom.strip() if custom else self._format_run_tab_title(counter)
                self.tab_widget.setTabText(idx, title)
                counter += 1

    def _get_run_tab_position(self, tab: RunTab) -> Optional[int]:
        counter = 1
        for idx in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(idx)
            if isinstance(widget, RunTab):
                if widget is tab:
                    return counter
                counter += 1
        return None

    def _get_data_tab_position(self, tab: DashboardTab) -> Optional[int]:
        ordered = sorted(
            ((self.tab_widget.indexOf(t), t) for t in self._data_tabs),
            key=lambda pair: pair[0],
        )
        for position, (_, widget) in enumerate(ordered, start=1):
            if widget is tab:
                return position
        return None

    @Slot(int)
    def _on_tab_double_clicked(self, index: int):
        if index < 0:
            return
        widget = self.tab_widget.widget(index)
        if widget is None:
            return
        current_title = self.tab_widget.tabText(index)
        new_title, accepted = QInputDialog.getText(self, "Rename Tab", "Tab name:", QLineEdit.Normal, current_title)
        if not accepted:
            return
        new_title = new_title.strip()
        if not new_title:
            return
        if isinstance(widget, RunTab):
            position = self._get_run_tab_position(widget) or 0
            default_name = self._format_run_tab_title(position)
            self._run_tab_custom_names[widget] = None if new_title == default_name else new_title
        elif isinstance(widget, DashboardTab):
            position = self._get_data_tab_position(widget) or 0
            default_name = self._format_dashboard_tab_title(position)
            self._data_tab_custom_names[widget] = None if new_title == default_name else new_title
        self.tab_widget.setTabText(index, new_title)
        self._refresh_tab_close_buttons()

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
            
            # Draw CV Overlay
            self._draw_cv_overlay(pix)
            
            self._preview_frame_counter = frame_idx
            
            # Legacy time overlay
            try:
                 # Just draw on the pixmap? No, legacy drew on the CV frame. 
                 # For now, let's trust the CV overlay.
                 pass
            except Exception:
                 pass
    
            h, w = overlay.shape[:2]
            if w and h:
                self._maybe_update_preview_aspect(w, h)
                
            self.video_view.set_image(pix)
            if self._pip_window:
                self._pip_window.set_pixmap(pix)
                
            if self.recorder:
                self._recorded_frame_counter = frame_idx
                self.recorder.write(frame) # Write the clean frame (or overlay if desired?) 
                                           # Requirement said "nothing anchoring data to video", implying clean video.
                                           # We keep the video clean.
    
        def _start_frame_stream(self):
            if self.cap is None or self._frame_worker is not None:
                return
            interval = int(1000 / max(1, self.preview_fps))
            self._frame_worker = FrameWorker(self.cap, interval)
            self._frame_worker.frameReady.connect(self._handle_frame, Qt.QueuedConnection)
            
            # Feed CV Bot
            if hasattr(self, 'cv_worker'):
                 self._frame_worker.frameReady.connect(self.cv_worker.process_frame, Qt.QueuedConnection)
                 
            self._frame_worker.error.connect(self._update_status, Qt.QueuedConnection)
            self._frame_worker.stopped.connect(self._cleanup_frame_stream, Qt.QueuedConnection)
            self._frame_worker.start()

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


    # Status line refresh
    def _refresh_statusline(self):
        run_id = self.logger.run_id if self.logger else "-"
        cam_idx = self.cam_index.value()
        fps = int(self.preview_fps or 0)
        rec = "REC ON" if self.recorder else "REC OFF"
        if self.recorder:
            total = getattr(self.recorder, "total_frames", 0)
            dropped = getattr(self.recorder, "dropped_frames", 0)
            if total > 0:
                pct = (dropped / total) * 100.0
                rec += f" (drop {pct:.1f}%)"
        port = self.port_edit.currentText().strip() if self.serial.is_open() else "—"
        serial_state = f"serial:{port}" if self.serial.is_open() else "serial:DISCONNECTED"
        if self.session.replicant_running or self._replicant_mode_active():
            mode = "Replicant"
            total = self.session.replicant_total
            completed = self.session.replicant_progress
            param = f"{completed}/{total} taps" if total else "no-script"
        else:
            mode = self.mode.currentText()
            param = f"P={self.period_sec.value():.2f}s" if mode=="Periodic" else f"λ={self.lambda_rpm.value():.2f}/min"
        taps = self.taps
        if self.run_start:
            elapsed = time.monotonic() - self.run_start
            # Auto-stop logic (low-overhead check)
            try:
                limit_min = self.auto_stop_min.value()
                # Debug print to verify logic
                except Exception as e:
                    pass
        else:
            elapsed = self._last_run_elapsed
        overall_rate = (taps/elapsed*60.0) if elapsed>0 else 0.0
        recent_rate = self._recent_rate_per_min()
        recent_str = f"{recent_rate:5.2f}" if recent_rate is not None else "  --"
        overall_str = f"{overall_rate:5.2f}" if elapsed > 0 else "  --"
        elapsed_sec = int(round(elapsed))
        txt = (
            f"{run_id}  •  cam {cam_idx}/{fps}fps  •  {rec}  •  {serial_state}  •  {mode} {param}"
            f"  •  taps:{taps}  •  t+{elapsed_sec:6d}s  •  rate10:{recent_str}/min  •  avg:{overall_str}/min"
        )
        self.statusline.setText(txt)

    def _update_status(self, msg): self.status.setText(msg)

    def _auto_detect_serial_port(self) -> str | None:
        try:
            ports = list(list_ports.comports())
        except Exception:
            ports = []
        if not ports:
            return None
        preferred = [
            "cu.usbmodem", "tty.usbmodem", "cu.usbserial", "tty.usbserial",
            "ttyacm", "ttyusb"
        ]

        def port_score(name: str) -> int:
            lower = name.lower()
            for idx, prefix in enumerate(preferred):
                if prefix in lower:
                    return len(preferred) - idx
            if lower.startswith("com"):
                return 1
            return 0

        best = None
        best_score = -1
        for info in ports:
            name = info.device
            score = port_score(name)
            if score > best_score:
                best_score = score
                best = name
        if best:
            return best
        return ports[0].device

    def _refresh_serial_ports(self, initial: bool = False):
        try:
            ports = list(list_ports.comports())
        except Exception:
            ports = []
        existing = {self.port_edit.itemText(i) for i in range(self.port_edit.count())}
        for info in ports:
            name = info.device
            if name not in existing:
                self.port_edit.addItem(name)
                existing.add(name)
        if initial and ports:
            autodetected = self._auto_detect_serial_port()
            if autodetected:
                idx = self.port_edit.findText(autodetected, Qt.MatchFixedString)
                if idx == -1:
                    self.port_edit.addItem(autodetected)
                    idx = self.port_edit.findText(autodetected, Qt.MatchFixedString)
                if idx != -1:
                    self.port_edit.setCurrentIndex(idx)

    def _load_calibration(self) -> dict[str, float]:
        existing_paths: list[Path] = []
        for path in self._calibration_paths:
            try:
                if path.exists():
                    existing_paths.append(path)
            except Exception:
                continue
        existing_paths.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)
        for path in existing_paths or self._calibration_paths:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    calibrated: dict[str, float] = {}
                    for key, value in data.items():
                        try:
                            calibrated[str(key)] = float(value)
                        except Exception:
                            continue
                    self._active_calibration_path = path
                    return calibrated
            except FileNotFoundError:
                continue
            except Exception:
                continue
        return {}

    def _save_calibration(self) -> None:
        for path in self._calibration_paths:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(self._period_calibration, f, indent=2)
                self._active_calibration_path = path
                return
            except PermissionError:
                continue
            except OSError:
                continue
        self._update_status("Calibration save failed (check permissions).")

    @staticmethod
    def _normalized_port_key(port: str) -> str:
        if not port:
            return ""
        base = port.rstrip('0123456789')
        return base if base else port

    def _lookup_period_calibration(self, port: str) -> float:
        if not port:
            return 1.0
        if port in self._period_calibration:
            return float(self._period_calibration[port])
        key = self._normalized_port_key(port)
        if key in self._period_calibration:
            return float(self._period_calibration[key])
        # Legacy fallback: allow prefix match for older files
        if key:
            for existing_key, value in self._period_calibration.items():
                if existing_key.startswith(key):
                    return float(value)
        return 1.0

    def _finalize_period_calibration(self):
        if self.logger is None:
            return
        port = self._active_serial_port.strip()
        if not port:
            return
        if self.mode.currentText() != "Periodic":
            return
        if self._first_hw_tap_ms is None or self._last_hw_tap_ms is None:
            return
        if self._first_host_tap_monotonic is None or self._last_host_tap_monotonic is None:
            return
        board_elapsed_ms = self._last_hw_tap_ms - self._first_hw_tap_ms
        host_elapsed = self._last_host_tap_monotonic - self._first_host_tap_monotonic
        if board_elapsed_ms <= 0 or host_elapsed <= 0:
            return
        if host_elapsed < 30.0:  # require at least 30s of data
            return
        host_elapsed_ms = host_elapsed * 1000.0
        if host_elapsed_ms <= 0:
            return
        raw_factor = board_elapsed_ms / host_elapsed_ms
        factor = max(0.95, min(1.05, raw_factor))
        existing = float(self._period_calibration.get(port, self._lookup_period_calibration(port)))
        if abs(factor - existing) < 1e-4:
            return
        self._period_calibration[port] = factor
        norm_key = self._normalized_port_key(port)
        if norm_key and norm_key != port:
            self._period_calibration[norm_key] = factor
        # Overwrite any legacy entries that share the same normalized prefix
        if norm_key:
            for key in list(self._period_calibration.keys()):
                if key not in {port, norm_key} and key.startswith(norm_key):
                    self._period_calibration[key] = factor
        self._save_calibration()
        if abs(factor - 1.0) < 1e-4:
            self._update_status(f"Calibration reset for {port} (x{factor:.6f})")
        else:
            self._update_status(f"Calibration updated for {port}: x{factor:.6f} (raw {raw_factor:.6f})")

    def _adjust_min_window_size(self):
        try:
            content = self.app_view._content if hasattr(self.app_view, '_content') else None
            if content is None:
                return
            min_hint = content.minimumSizeHint()
            if not min_hint.isValid() or min_hint.width() <= 0:
                min_hint = content.sizeHint()
            # Compute viewport chrome difference
            vw = self.app_view.viewport().width()
            vh = self.app_view.viewport().height()
            aw = self.app_view.width()
            ah = self.app_view.height()
            delta_w = max(0, aw - vw)
            delta_h = max(0, ah - vh)
            # Also include outer window frame vs central widget padding
            extra_w = self.width() - self.centralWidgetWidth() if hasattr(self, 'centralWidgetWidth') else 0
            extra_h = self.height() - self.centralWidgetHeight() if hasattr(self, 'centralWidgetHeight') else 0
            min_w = max(900, min_hint.width() + delta_w + extra_w)
            min_h = max(540, min_hint.height() + delta_h + extra_h)
            self.setMinimumSize(min_w, min_h)
        except Exception:
            pass

    def _init_splitter_balance(self):
        split = getattr(self, 'splitter', None)
        if split is None:
            return
        try:
            total = max(1, self.width())
            right = int(round(total * 0.75))
            left = max(360, total - right)
            split.set_pane_sizes([left, right])
        except Exception:
            pass

    def _apply_titlebar_theme(self):
        handle = None
        try:
            handle = self.windowHandle()
        except Exception:
            handle = None
        applied = False
        if handle is not None:
            try:
                handle.setTitleBarColor(QColor(BG))
                if hasattr(handle, "setTitleBarAutoTint"):
                    handle.setTitleBarAutoTint(False)
                applied = True
            except Exception:
                applied = False
        if not applied:
            try:
                _set_macos_titlebar_appearance(self, QColor(BG))
            except Exception:
                pass

    def closeEvent(self, event):
        for index in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(index)
            if isinstance(widget, RunTab):
                try:
                    widget.shutdown()
                except Exception:
                    pass
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    _apply_global_font(app)
    # Force Fusion style so native controls (e.g., macOS) don't override palette
    try:
        app.setStyle(QStyleFactory.create("Fusion"))
    except Exception:
        pass
    app.setStyleSheet(build_stylesheet(_FONT_FAMILY, 1.0))
    global _APP_ICON
    try:
        _APP_ICON = build_app_icon()
        if _APP_ICON is not None:
            app.setWindowIcon(_APP_ICON)
    except Exception:
        _APP_ICON = None
    w = App()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
