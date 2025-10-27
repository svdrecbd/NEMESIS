# app.py — NEMESIS UI (v1.0-rc1, unified feature set)
import sys, os, time, json, uuid, csv, threading
from pathlib import Path
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Optional, Any

from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QFileDialog,
    QHBoxLayout, QVBoxLayout, QGridLayout, QComboBox, QSpinBox, QDoubleSpinBox,
    QLineEdit, QMessageBox, QSizePolicy, QListView, QSplitter, QStyleFactory, QFrame, QSpacerItem,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsProxyWidget, QSplitterHandle, QMenu,
    QGraphicsOpacityEffect, QTabWidget, QListWidget, QListWidgetItem, QInputDialog, QTabBar, QToolButton,
    QStyleOptionTab, QStyle, QScrollArea, QStylePainter
)
from PySide6.QtCore import (
    QTimer, Qt, QEvent, QSize, Signal, QObject, Slot, QUrl, QPoint,
    QPropertyAnimation, QEasingCurve, QAbstractAnimation, QRect
)
from PySide6.QtGui import QImage, QPixmap, QFontDatabase, QFont, QIcon, QPainter, QColor, QPen, QDesktopServices, QCursor, QPalette
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator, AutoLocator, NullLocator
import matplotlib as mpl
from matplotlib import font_manager
from serial.tools import list_ports

# Internal modules
from .core import video, scheduler, configio
from .core import logger as runlogger
from .core.session import RunSession
from .core.runlib import RunLibrary, RunSummary
import shutil
import cv2

# Assets & Version
# Resolve assets relative to the project root, not the current working directory
BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
FONT_PATH = ASSETS_DIR / "fonts/Typestar OCR Regular.otf"
LOGO_PATH = ASSETS_DIR / "images/transparent_logo.png"
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
    except Exception:
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
    except Exception:
        return False
    try:
        objc = cdll.LoadLibrary(util.find_library('objc'))
    except Exception:
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
    except Exception:
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
    except Exception:
        ns_color = None

    try:
        _msg(window, _sel(b"setAppearance:"), appearance, restype=None, argtypes=[c_void_p])
        # Prevent automatic accent recoloring so it stays dark
        _msg(window, _sel(b"setTitlebarAppearsTransparent:"), c_bool(False), restype=None, argtypes=[c_bool])
        if ns_color:
            _msg(window, _sel(b"setBackgroundColor:"), ns_color, restype=None, argtypes=[c_void_p])
    except Exception:
        return False
    return True

class LiveChart:
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
        except Exception:
            pass
        self.canvas = FigureCanvas(self.fig)
        # Reduce minimum height so the preview keeps priority
        self.canvas.setMinimumHeight(160)
        try:
            # Canvas transparent; outer QFrame draws the border/background
            self.canvas.setStyleSheet("background: transparent;")
        except Exception:
            pass
        self.times_sec: list[float] = []
        self._time_unit: str = "minutes"
        self._last_max_elapsed_sec: float = 0.0
        self._init_axes()

    def _init_axes(self):
        text_color = self.color("TEXT")
        self.fig.suptitle("Stentor Habituation to Stimuli", fontsize=10, color=text_color, y=0.98)
        try:
            self.fig.patch.set_alpha(0.0)
            self.fig.patch.set_facecolor('none')
        except Exception:
            pass
        self._configure_axes("minutes", 0.0)
        self.canvas.draw_idle()

    def reset(self):
        self.times_sec.clear()
        self._init_axes()

    def add_tap(self, t_since_start_s: float):
        self.times_sec.append(float(t_since_start_s))
        self._redraw()

    def set_times(self, times_seconds: Sequence[float]):
        self.times_sec = [float(v) for v in times_seconds]
        self._redraw()

    def _redraw(self):
        if not self.times_sec:
            self._configure_axes("minutes", 0.0)
            self.canvas.draw_idle()
            return

        max_elapsed_sec = max(self.times_sec)
        unit = "hours" if max_elapsed_sec >= 2 * 3600 else "minutes"
        self._configure_axes(unit, max_elapsed_sec)

        factor = 3600.0 if unit == "hours" else 60.0
        ts_unit = [t / factor for t in self.times_sec]
        highlighted = [t for i, t in enumerate(ts_unit) if (i + 1) % 10 == 0]
        regular     = [t for i, t in enumerate(ts_unit) if (i + 1) % 10 != 0]

        text_color = self.color("TEXT")
        base_width = 0.9 if unit == "minutes" else 0.9
        highlight_width = 1.6 if unit == "minutes" else 1.6
        if regular:
            self.ax_top.eventplot(regular, orientation="horizontal", colors=text_color, linewidth=base_width)
        if highlighted:
            self.ax_top.eventplot(highlighted, orientation="horizontal", colors=self.color("ACCENT"), linewidth=highlight_width)

        self.canvas.draw_idle()

    def _configure_axes(self, unit: str, max_elapsed_sec: float):
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

        ax_top.set_ylabel("Taps", color=text_color)
        ax_top.set_yticks([])
        ax_top.tick_params(axis='x', colors=text_color)
        ax_top.tick_params(axis='y', colors=text_color)
        for spine in ax_top.spines.values():
            spine.set_color(text_color)

        ax_bot.set_ylabel("% Contracted")
        ax_bot.set_ylim(-5, 105)
        ax_bot.yaxis.set_major_formatter(plt.FuncFormatter("{:.0f}%".format))
        ax_bot.tick_params(axis='x', colors=text_color)
        ax_bot.tick_params(axis='y', colors=text_color)
        for spine in ax_bot.spines.values():
            spine.set_color(text_color)

        factor = 3600.0 if unit == "hours" else 60.0
        default_limit = 2.0 if unit == "hours" else 70.0
        max_unit_val = max(default_limit, (max_elapsed_sec / factor) * 1.1 if max_elapsed_sec else default_limit)

        if unit == "minutes":
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
        else:
            locator_top = AutoLocator()
            locator_bot = AutoLocator()
            ax_top.xaxis.set_major_locator(locator_top)
            ax_top.xaxis.set_minor_locator(NullLocator())
            ax_bot.xaxis.set_major_locator(locator_bot)
            ax_bot.xaxis.set_minor_locator(NullLocator())
            ax_bot.set_xlabel("Time (hours)")
            ax_top.grid(True, which="major", axis="x", linestyle=":", alpha=0.9)
            ax_bot.grid(True, which="major", axis="x", linestyle=":", alpha=0.9)

        ax_top.set_xlim(0, max_unit_val)
        ax_bot.set_xlim(0, max_unit_val)
        self._time_unit = unit
        self._last_max_elapsed_sec = max_elapsed_sec
        try:
            self.fig.subplots_adjust(top=0.82, bottom=0.18, left=0.10, right=0.98, hspace=0.12)
            self.fig.suptitle("Stentor Habituation to Stimuli", fontsize=10, color=text_color, y=0.98)
        except Exception:
            pass

    def color(self, key: str) -> str:
        if key in self.theme:
            return self.theme[key]
        return active_theme().get(key, globals().get(key, "#ffffff"))

    def set_theme(self, theme: dict[str, str]):
        self.theme = theme
        apply_matplotlib_theme(self.font_family, theme)
        if self.times_sec:
            self._redraw()
        else:
            self._configure_axes(self._time_unit, self._last_max_elapsed_sec)
            self.canvas.draw_idle()

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
        except Exception:
            pass
        self._bg_color = bg_color
        self._scrollbar_qss = self._build_scrollbar_qss(theme.get("SCROLLBAR", SCROLLBAR))
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
            except Exception:
                pass
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
            except Exception:
                pass
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
                if gtype == Qt.NativeGestureType.Zoom and val is not None:
                    factor = 1.0 + (float(val) * 0.5)
                    factor = max(0.7, min(factor, 1.3))
                    self._zoom_by(factor)
                    ev.accept()
                    return True
            except Exception:
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
            except Exception:
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


class GuideSplitterHandle(QSplitterHandle):
    def __init__(self, orientation: Qt.Orientation, parent=None, theme: dict[str, str] | None = None):
        super().__init__(orientation, parent)
        self.setCursor(Qt.SplitHCursor if orientation == Qt.Horizontal else Qt.SplitVCursor)
        self._theme = theme or active_theme()
        self._apply_theme()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        rect = self.rect()
        painter.fillRect(rect, QColor(self._theme.get("BG", BG)))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self._theme.get("BG", BG)))
        painter.drawRect(rect)
        splitter = self.splitter()
        active_idx = getattr(splitter, "_active_handle_index", None) if splitter else None
        match_idx = None
        if splitter and active_idx is not None:
            try:
                for i in range(1, splitter.count()):
                    if splitter.handle(i) is self:
                        match_idx = i
                        break
            except Exception:
                match_idx = None
        if active_idx is not None and match_idx == active_idx:
            pen = QPen(QColor(self._theme.get("ACCENT", ACCENT)))
            pen.setStyle(Qt.CustomDashLine)
            pen.setDashPattern([1, 4])
            pen.setCosmetic(True)
            pen.setCapStyle(Qt.FlatCap)
            pen.setWidth(1)
            painter.setPen(pen)
            if self.orientation() == Qt.Horizontal:
                x = rect.center().x()
                painter.drawLine(int(x), rect.top(), int(x), rect.bottom())
            else:
                y = rect.center().y()
                painter.drawLine(rect.left(), int(y), rect.right(), int(y))

    def sizeHint(self):
        base = super().sizeHint()
        splitter = self.splitter()
        width = max(1, splitter.handleWidth() if splitter else base.width())
        if self.orientation() == Qt.Horizontal:
            return QSize(width, base.height())
        return QSize(base.width(), width)

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)
        splitter = self.splitter()
        if splitter:
            try:
                splitter.setRubberBand(-1)
            except Exception:
                pass

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        splitter = self.splitter()
        if not splitter:
            return
        try:
            splitter.setRubberBand(-1)
        except Exception:
            pass
        if hasattr(splitter, "_pane_records"):
            panes = splitter._pane_records()
            if len(panes) >= 2:
                _, _, left_now = panes[0]
                _, _, right_now = panes[1]
                total = left_now + right_now
                target_ratio, clamped_px = splitter._nearest_feasible_target(left_now)
                if target_ratio is not None and clamped_px is not None and total > 0:
                    try:
                        splitter.blockSignals(True)
                        splitter._apply_pane_sizes(clamped_px, total - clamped_px)
                    finally:
                        splitter.blockSignals(False)
                    handle_index = splitter._pane_handle_index()
                    splitter._set_active_ratio(target_ratio, handle_index if handle_index is not None else 0)
                    splitter.update()
        QTimer.singleShot(450, lambda: splitter._clear_active_ratio() if hasattr(splitter, "_clear_active_ratio") else None)

    def _apply_theme(self):
        base_color = QColor(self._theme.get("BG", BG))
        self._base = base_color
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), base_color)
        self.setPalette(pal)
        self.update()

    def set_theme(self, theme: dict[str, str]):
        self._theme = theme or active_theme()
        self._apply_theme()


class GuideSplitter(QSplitter):
    def __init__(self, orientation: Qt.Orientation, parent=None, *, snap_targets=None, snap_tolerance: float = 0.03, theme: dict[str, str] | None = None):
        super().__init__(orientation, parent)
        self._snap_targets = sorted(snap_targets or (0.25, 0.5, 0.75))
        self._snap_tolerance = float(max(0.005, snap_tolerance))
        self._active_ratio: float | None = None
        self._active_handle_index: int | None = None
        self._theme = theme or active_theme()
        # Live resize with no rubber-band painter
        self.setOpaqueResize(True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)
        self._apply_theme()
        try:
            self.setRubberBand(-1)
        except Exception:
            pass
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._clear_active_ratio)
        try:
            self.splitterMoved.connect(self._on_splitter_moved)
        except Exception:
            pass

    def _apply_theme(self):
        bg = self._theme.get("BG", BG)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(bg))
        self.setPalette(pal)
        try:
            self.setStyleSheet(
                f"QSplitter {{ background: {bg}; }}"
                "QSplitter::handle { background: transparent; border: none; image: none; }"
                "QSplitter::rubberBand { background: transparent; border: none; }"
            )
        except Exception:
            pass
        for idx in range(1, self.count()):
            handle = self.handle(idx)
            if isinstance(handle, GuideSplitterHandle):
                handle.set_theme(self._theme)

    def set_theme(self, theme: dict[str, str]):
        self._theme = theme or active_theme()
        self._apply_theme()
        self.update()

    def createHandle(self):
        return GuideSplitterHandle(self.orientation(), self, theme=self._theme)

    # --- Internal helpers -------------------------------------------------
    def _pane_records(self) -> list[tuple[int, QWidget, int]]:
        """Return [(index, widget, size)] for managed panes (skips overlay label)."""
        records: list[tuple[int, QWidget, int]] = []
        sizes = QSplitter.sizes(self)
        count = QSplitter.count(self)
        for idx in range(count):
            w = QSplitter.widget(self, idx)
            if w is None:
                continue
            size = sizes[idx] if idx < len(sizes) else 0
            records.append((idx, w, size))
        return records

    def _pane_handle_index(self) -> int | None:
        panes = self._pane_records()
        if len(panes) < 2:
            return None
        # Handle index matches the index of the pane on its right
        return panes[1][0]

    def set_pane_sizes(self, sizes: Sequence[int]) -> None:
        panes = self._pane_records()
        if not panes or not sizes:
            return
        full = QSplitter.sizes(self)
        for (idx, _, _), value in zip(panes, sizes):
            needed_len = idx + 1
            if len(full) < needed_len:
                full.extend([0] * (needed_len - len(full)))
            full[idx] = max(0, int(round(value)))
        QSplitter.setSizes(self, full)

    def _apply_pane_sizes(self, left_px: int, right_px: int) -> None:
        self.set_pane_sizes([left_px, right_px])

    def _on_splitter_moved(self, pos: int, index: int):
        try:
            self.setRubberBand(-1)
        except Exception:
            pass
        QTimer.singleShot(0, lambda: self._maybe_snap(self.handle(index)))

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        try:
            self.setRubberBand(-1)
        except Exception:
            pass
        handle_index = 1 if self.count() > 1 else 0
        QTimer.singleShot(0, lambda: self._maybe_snap(self.handle(handle_index)))

    def _nearest_feasible_target(self, current_left: int) -> tuple[float | None, int | None]:
        panes = self._pane_records()
        if len(panes) < 2:
            return None, None
        _, left_widget, left_now = panes[0]
        _, right_widget, right_now = panes[1]
        total = left_now + right_now
        if total <= 0:
            return None, None
        if self.orientation() == Qt.Horizontal:
            min_left = left_widget.minimumWidth() if left_widget else 0
            min_right = right_widget.minimumWidth() if right_widget else 0
        else:
            min_left = left_widget.minimumHeight() if left_widget else 0
            min_right = right_widget.minimumHeight() if right_widget else 0

        best_ratio: float | None = None
        best_px: int | None = None
        best_delta = float("inf")
        for target in self._snap_targets:
            raw_px = int(round(total * target))
            clamped_px = max(min_left, min(raw_px, total - min_right))
            delta = abs(current_left - clamped_px)
            if delta < best_delta:
                best_delta = delta
                best_ratio = target
                best_px = clamped_px
        return best_ratio, best_px

    def _maybe_snap(self, handle: QSplitterHandle | None = None):
        panes = self._pane_records()
        if len(panes) < 2:
            self._clear_active_ratio()
            return

        left_idx, left_widget, left_now = panes[0]
        right_idx, right_widget, right_now = panes[1]
        total = left_now + right_now
        if total <= 0:
            self._clear_active_ratio()
            return

        if self.orientation() == Qt.Horizontal:
            min_left = left_widget.minimumWidth() if left_widget else 0
            min_right = right_widget.minimumWidth() if right_widget else 0
        else:
            min_left = left_widget.minimumHeight() if left_widget else 0
            min_right = right_widget.minimumHeight() if right_widget else 0

        scale = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1.0
        handle_px = max(1, int(round(self.handleWidth() * scale)))
        px_tol = max(handle_px + 2, int(round(total * self._snap_tolerance)))
        snapped_ratio = None
        for target in self._snap_targets:
            raw_px = int(round(total * target))
            clamped_px = max(min_left, min(raw_px, total - min_right))
            if abs(left_now - clamped_px) > px_tol:
                continue
            try:
                self.blockSignals(True)
                self._apply_pane_sizes(clamped_px, total - clamped_px)
            finally:
                self.blockSignals(False)
            refreshed = self._pane_records()
            if len(refreshed) < 2:
                continue
            new_left = refreshed[0][2]
            new_right = refreshed[1][2]
            new_total = max(1, new_left + new_right)
            actual = new_left / new_total
            if (abs(actual - target) <= self._snap_tolerance * 1.2) or (clamped_px != raw_px):
                snapped_ratio = target
            break

        if snapped_ratio is not None:
            handle_index = self._pane_handle_index()
            self._set_active_ratio(snapped_ratio, handle_index if handle_index is not None else 0)
            self.update()
        else:
            self._clear_active_ratio()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._active_ratio is not None:
            self.update()

    def _set_active_ratio(self, ratio: float, handle_index: int):
        self._active_ratio = ratio
        self._active_handle_index = handle_index
        self._flash_timer.start(450)
        self.update()
        handle = self.handle(handle_index)
        if handle:
            handle.update()

    def _clear_active_ratio(self):
        if self._active_ratio is None:
            return
        handle_index = self._active_handle_index
        self._active_ratio = None
        self._active_handle_index = None
        self._flash_timer.stop()
        self.update()
        if handle_index is not None:
            handle = self.handle(handle_index)
            if handle:
                handle.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._active_ratio is None:
            return
        if self._active_handle_index is None:
            return
        handle = self.handle(self._active_handle_index)
        if not handle:
            return
        geo = handle.geometry()
        center = geo.center()
        painter = QPainter(self)
        accent = QColor(self._theme.get("ACCENT", ACCENT))
        pen = QPen(accent)
        pen.setStyle(Qt.CustomDashLine)
        pen.setDashPattern([2, 4])
        pen.setCapStyle(Qt.FlatCap)
        pen.setCosmetic(True)
        pen.setWidth(1)
        painter.setPen(pen)
        painter.setRenderHint(QPainter.Antialiasing, False)
        if self.orientation() == Qt.Horizontal:
            x = center.x()
            painter.drawLine(int(x), 0, int(x), self.height())
        else:
            y = center.y()
            painter.drawLine(0, int(y), self.width(), int(y))


class FrameWorker(QObject):
    frameReady = Signal(object)
    error = Signal(str)
    stopped = Signal()

    def __init__(self, capture: video.VideoCapture, interval_ms: int = 33):
        super().__init__()
        self._capture = capture
        self._interval_s = max(0.005, float(interval_ms) / 1000.0)
        self._running = False
        self._thread: threading.Thread | None = None

    def _loop(self):
        interval = self._interval_s
        next_tick = time.perf_counter()
        try:
            while self._running:
                try:
                    ok, frame = self._capture.read()
                except Exception as exc:
                    self.error.emit(f"Camera error: {exc}")
                    break
                if ok and frame is not None:
                    self.frameReady.emit(frame)
                if interval > 0:
                    next_tick += interval
                    sleep_for = next_tick - time.perf_counter()
                    if sleep_for > 0:
                        time.sleep(sleep_for)
                    else:
                        next_tick = time.perf_counter()
        finally:
            self._running = False
            self.stopped.emit()

    @Slot()
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="FrameWorkerLoop", daemon=True)
        self._thread.start()

    @Slot()
    def stop(self):
        if not self._running:
            return
        self._running = False
        thread = self._thread
        if thread and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=0.5)
        self._thread = None


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

    def _set_mirror_mode(self, enabled: bool):
        enabled = bool(enabled)
        if enabled == self._mirror_mode:
            return
        self._mirror_mode = enabled
        self._update_mirror_layout()
        self._sync_logo_menu_checks()

    def _update_mirror_layout(self):
        split = getattr(self, "splitter", None)
        left = getattr(self, "_left_widget", None)
        right = getattr(self, "_right_widget", None)
        if split is None or left is None or right is None:
            return
        desired = (right, left) if self._mirror_mode else (left, right)
        try:
            current_sizes = split.sizes()
        except Exception:
            current_sizes = []
        current_order: list[QWidget] = []
        try:
            for i in range(split.count()):
                widget = split.widget(i)
                if widget is not None:
                    current_order.append(widget)
        except Exception:
            current_order = []
        size_map: dict[QWidget, int] = {}
        for idx, widget in enumerate(current_order):
            if idx < len(current_sizes):
                size_map[widget] = current_sizes[idx]
        for idx, widget in enumerate(desired):
            current_idx = split.indexOf(widget)
            if current_idx == -1 or current_idx == idx:
                continue
            try:
                split.blockSignals(True)
                split.insertWidget(idx, widget)
            finally:
                split.blockSignals(False)
        new_sizes: list[int] = []
        if desired:
            for idx, widget in enumerate(desired):
                size = size_map.get(widget)
                if size is None and idx < len(current_sizes):
                    size = current_sizes[idx]
                if size is None:
                    size = 0
                new_sizes.append(int(size))
        if new_sizes and any(new_sizes):
            try:
                split.setSizes(new_sizes)
            except Exception:
                pass
        try:
            split.setStretchFactor(0, 1)
            split.setStretchFactor(1, 1)
        except Exception:
            pass

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
        self._mirror_mode = True
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

        # Recording controls (independent)
        self.rec_start_btn = QPushButton("Start Recording")
        self.rec_stop_btn  = QPushButton("Stop Recording")
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
        self.period_sec.setMinimumWidth(135)
        self.period_sec.setMaximumWidth(200)
        self.period_sec.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.lambda_rpm = QDoubleSpinBox(); self.lambda_rpm.setRange(0.1, 600.0); self.lambda_rpm.setValue(6.0); self.lambda_rpm.setSuffix(" taps/min")
        self.lambda_rpm.setMinimumWidth(135)
        self.lambda_rpm.setMaximumWidth(200)
        self.lambda_rpm.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

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
        self.stepsize.setMinimumWidth(max(150, s_w))
        self.stepsize.setMaximumWidth(max(210, s_w + 20))
        self.stepsize.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # Poisson RNG seed (optional)
        self.seed_edit = QLineEdit(); self.seed_edit.setPlaceholderText("Seed (optional integer)")

        # Run controls
        self.run_start_btn = QPushButton("Start Run")
        self.run_stop_btn  = QPushButton("Stop Run")
        self.clear_data_btn = QPushButton("Clear Data")
        self.clear_data_btn.setToolTip("Reset the counters and live chart manually.")

        # Output directory
        self.outdir_edit = QLineEdit()
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
        r2.addWidget(self.popout_btn)
        r2b = QHBoxLayout(); r2b.addWidget(self.rec_start_btn); r2b.addWidget(self.rec_stop_btn); r2b.addWidget(self.rec_indicator)
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
        lfm = self.lbl_mode.fontMetrics()
        label_w = max(
            lfm.horizontalAdvance("Mode:"),
            lfm.horizontalAdvance("Period:"),
            lfm.horizontalAdvance("λ (taps/min):"),
            lfm.horizontalAdvance("Stepsize:")
        ) + 8
        for lbl in (self.lbl_mode, self.lbl_period, self.lbl_lambda, self.lbl_stepsize):
            lbl.setFixedWidth(label_w)
        controls_grid = QGridLayout()
        controls_grid.setContentsMargins(0, 0, 0, 0)
        controls_grid.setHorizontalSpacing(6)
        controls_grid.setVerticalSpacing(4)
        controls_grid.addWidget(self.lbl_mode, 0, 0, Qt.AlignLeft)
        controls_grid.addWidget(self.mode, 0, 1)
        controls_grid.addWidget(self.lbl_period, 1, 0, Qt.AlignLeft)
        controls_grid.addWidget(self.period_sec, 1, 1)
        controls_grid.addWidget(self.lbl_lambda, 2, 0, Qt.AlignLeft)
        controls_grid.addWidget(self.lambda_rpm, 2, 1)
        controls_grid.addWidget(self.lbl_stepsize, 3, 0, Qt.AlignLeft)
        controls_grid.addWidget(self.stepsize, 3, 1)
        controls_grid.setColumnStretch(1, 1)
        mode_section = QVBoxLayout()
        mode_section.setContentsMargins(0, 0, 0, 0)
        mode_section.setSpacing(6)
        mode_section.addLayout(controls_grid)
        flash_row = QHBoxLayout(); flash_row.setContentsMargins(0, 0, 0, 0); flash_row.addWidget(self.flash_config_btn, 1)
        mode_section.addLayout(flash_row)

        # Seed / run / output configuration cluster
        r3b = QHBoxLayout(); r3b.addWidget(QLabel("Seed:")); r3b.addWidget(self.seed_edit,1)
        r4 = QHBoxLayout(); r4.addWidget(self.run_start_btn); r4.addWidget(self.run_stop_btn); r4.addWidget(self.clear_data_btn)
        r5 = QHBoxLayout(); r5.addWidget(QLabel("Output dir:")); r5.addWidget(self.outdir_edit,1); r5.addWidget(self.outdir_btn)

        # Config save/load row (was missing from layout)
        r5b = QHBoxLayout(); r5b.addWidget(self.save_cfg_btn); r5b.addWidget(self.load_cfg_btn)
        r5c = QHBoxLayout(); r5c.addWidget(self.flash_config_btn, 1)

        io_section = QVBoxLayout()
        io_section.setContentsMargins(0, 0, 0, 0)
        io_section.setSpacing(6)
        io_section.addLayout(r3b)
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

        section_gap = 54  # triple gap keeps clusters distinct without feeling sparse
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
        splitter = GuideSplitter(Qt.Horizontal, snap_targets=(0.25, 0.5, 0.75), theme=self._theme)
        splitter.addWidget(leftw)
        splitter.addWidget(right_scroll)
        splitter.setChildrenCollapsible(False)
        try:
            splitter.setCollapsible(0, False)
            splitter.setCollapsible(1, False)
        except Exception:
            pass
        splitter.setHandleWidth(10)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        try:
            total = max(1, self.width())
            left = int(round(total * 0.75))
            right = max(360, total - left)
            splitter.set_pane_sizes([left, right])
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
        QTimer.singleShot(0, self._init_splitter_balance)
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
        self.seed_edit.returnPressed.connect(self._on_seed_entered)
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
        self._calibration_paths: tuple[Path, ...] = (
            Path.home() / ".nemesis" / "calibration.json",
            BASE_DIR / "runs" / "calibration.json",
        )
        self._active_calibration_path: Path | None = None
        self._period_calibration: dict[str, float] = self._load_calibration()
        if self._active_calibration_path is None:
            self._active_calibration_path = self._calibration_paths[0]

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

    def _drain_serial_queue(self):
        if not self.serial.is_open():
            return
        while True:
            item = self.serial.read_line_nowait(with_timestamp=True)
            if item is None:
                break
            timestamp, line = item
            cleaned = line.strip()
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
        mode_text = self.mode.currentText()
        mode_token = 'P' if mode_text == "Periodic" else 'R'
        stepsize = max(1, min(int(self.current_stepsize), 5))
        period_s = float(self.period_sec.value())
        lambda_rpm = float(self.lambda_rpm.value())
        port = self.port_edit.currentText().strip()
        if mode_token == 'P':
            period_s = max(0.001, period_s)
            calibration = self._lookup_period_calibration(port)
            adjusted_period = period_s * calibration
            config_value = f"{adjusted_period:.6f}"
        else:
            lambda_rpm = max(0.01, lambda_rpm)
            config_value = f"{lambda_rpm:.6f}"
        message = f"C,{mode_token},{stepsize},{config_value}\n"
        meta = {
            "mode": mode_token,
            "mode_label": mode_text,
            "stepsize": stepsize,
            "value": config_value,
            "period_sec": period_s,
            "lambda_rpm": lambda_rpm,
            "seed": self._seed_value_or_none(),
            "outdir": self.outdir_edit.text().strip() or os.getcwd(),
            "rec_path": getattr(self.recorder, "path", ""),
            "timestamp": time.strftime("%Y%m%d_%H%M%S"),
            "port": port,
            "period_calibration": calibration,
        }
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
        self._send_tap("manual")

    def _on_tap_due(self):
        self._send_tap("scheduled")
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

    def _on_hardware_run_stopped(self):
        if not self.session.hardware_run_active and not self.session.awaiting_switch_start:
            return
        self.session.hardware_run_active = False
        self.session.awaiting_switch_start = False
        self.session.last_hw_tap_ms = None
        self._stop_run(from_hardware=True, reason="Hardware run stopped.")

    def _on_hardware_tap(self, data: str, host_timestamp: float | None = None):
        if not self._hardware_run_active:
            return
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
                mode=self.mode.currentText(),
                mark="hardware",
                stepsize=self.current_stepsize,
                notes=note,
                host_iso=host_iso,
                firmware_ms=value,
                preview_frame_idx=self._preview_frame_counter,
                recorded_frame_idx=self._recorded_frame_counter,
            )

    def _initialize_run_logger(self, force: bool = False):
        if self.logger is not None and not force:
            return
        meta = self._pending_run_metadata or {}
        outdir = meta.get("outdir") or (self.outdir_edit.text().strip() or os.getcwd())
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
        self.logger = runlogger.RunLogger(run_dir, recording_path=rec_path)
        self.run_dir = run_dir

        seed = meta.get("seed", self._seed_value_or_none())
        self.session.scheduler.set_seed(seed)
        mode_token = meta.get("mode", 'P')
        if mode_token == 'P':
            self.session.scheduler.configure_periodic(meta.get("period_sec", float(self.period_sec.value())))
        else:
            self.session.scheduler.configure_poisson(meta.get("lambda_rpm", float(self.lambda_rpm.value())))

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
            self.serial.send_char(ch)
        self._record_serial_command(payload, note)
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
            if registry is not None and port:
                registry.release_serial(self, port)
            self._active_serial_port = ""

    # Output dir
    def _choose_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "Choose output directory")
        if d: self.outdir_edit.setText(d)

    # Recording
    def _start_recording(self):
        if self.cap is None:
            QMessageBox.warning(self, "No Camera", "Open a camera before starting recording."); return
        if self.recorder is not None:
            QMessageBox.information(self, "Recording", "Already recording."); return
        outdir = self.outdir_edit.text().strip() or os.getcwd()
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
            "serial_port": self.port_edit.text().strip(),
            "seed": self._seed_value_or_none(),
            "output_dir": self.outdir_edit.text().strip(),
            "app_version": APP_VERSION,
        }

    def _apply_config(self, cfg: dict):
        try:
            self.mode.setCurrentIndex(0 if cfg.get("mode","Periodic")=="Periodic" else 1)
            self.period_sec.setValue(float(cfg.get("period_sec", 10.0)))
            self.lambda_rpm.setValue(float(cfg.get("lambda_rpm", 6.0)))
            self._apply_stepsize(int(cfg.get("stepsize", 4)))
            self.cam_index.setValue(int(cfg.get("camera_index", 0)))
            self.port_edit.setText(cfg.get("serial_port", ""))
            seed = cfg.get("seed", None)
            self.seed_edit.setText("" if seed in (None, "") else str(seed))
            outdir = cfg.get("output_dir", "")
            if outdir: self.outdir_edit.setText(outdir)
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

    def _seed_value_or_none(self):
        txt = self.seed_edit.text().strip()
        if txt == "": return None
        try: return int(txt)
        except Exception: return None

    def _on_seed_entered(self):
        value = self._seed_value_or_none()
        if value is None:
            self.seed_edit.setText("")
            self._update_status("Seed cleared.")
        else:
            self._update_status(f"Seed set to {value}.")

    # Scheduler / Run
    def _mode_changed(self):
        is_periodic = (self.mode.currentText() == "Periodic")
        self.period_sec.setEnabled(is_periodic)
        self.lbl_period.setEnabled(is_periodic)
        self.lambda_rpm.setEnabled(not is_periodic)
        self.lbl_lambda.setEnabled(not is_periodic)
        # Helpful tooltips to clarify why control is inactive
        self.period_sec.setToolTip("Adjust when Mode is set to Periodic")
        self.lambda_rpm.setToolTip("Adjust when Mode is set to Poisson")

    def _start_run(self):
        if not self.serial.is_open():
            QMessageBox.warning(self, "Serial", "Connect to the controller before starting a run.")
            return
        self._flash_only_mode = False
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
        self._pending_run_metadata = meta
        self._active_serial_port = meta.get("port", self.port_edit.currentText().strip())
        self._initialize_run_logger(force=True)
        self._update_status("Configuration sent. Flip the switch ON to begin the run.")
        self._send_serial_char('e', "Enable motor")

    def _stop_run(self, *_args, from_hardware: bool = False, reason: str | None = None):
        try:
            self.run_timer.stop()
        except Exception:
            pass
        self._finalize_period_calibration()
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
            self.logger.close()
            self.logger = None
        if self.run_start is not None:
            try:
                self._last_run_elapsed = max(0.0, time.monotonic() - self.run_start)
            except Exception:
                self._last_run_elapsed = 0.0
        self.run_dir = None
        self.run_start = None
        self._pending_run_metadata = None
        if not from_hardware and self.serial.is_open():
            self._send_serial_char('d', "Disable motor")
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
        self.library = RunLibrary(BASE_DIR)
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
        detail_panel.addWidget(self.chart_frame, 1)

        # Action buttons
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        self.open_btn = QPushButton("Open Folder")
        self.open_btn.clicked.connect(self._open_run_folder)
        self.export_btn = QPushButton("Export CSV…")
        self.export_btn.clicked.connect(self._export_run_csv)
        self.delete_btn = QPushButton("Delete…")
        self.delete_btn.clicked.connect(self._delete_run)
        for btn in (self.open_btn, self.export_btn, self.delete_btn):
            btn.setEnabled(False)
        action_row.addWidget(self.open_btn)
        action_row.addWidget(self.export_btn)
        action_row.addWidget(self.delete_btn)
        action_row.addStretch(1)
        detail_panel.addLayout(action_row)

        root.addLayout(detail_panel, 1)

        self.refresh_runs()
        self.set_theme(active_theme())

    # Run list management

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
        item = self.run_list.currentItem()
        summary = item.data(Qt.UserRole) if item else None
        self._set_current_summary(summary)

    def _set_current_summary(self, summary: Optional[RunSummary]):
        self.current_summary = summary
        self.current_times = []
        enabled = summary is not None
        for btn in (self.open_btn, self.export_btn, self.delete_btn):
            btn.setEnabled(enabled)
        if summary is None:
            self.info_label.setText("Select a run to inspect logs and metrics.")
            self.chart.reset()
            return

        self.info_label.setText(self._format_summary(summary))
        self.current_times = self._load_run_times(summary)
        if self.current_times:
            self.chart.set_times(self.current_times)
        else:
            self.chart.reset()

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

    # Actions

    def _require_summary(self) -> Optional[RunSummary]:
        if self.current_summary is None:
            QMessageBox.information(self, "Dashboard", "Select a run first.")
            return None
        return self.current_summary

    def _open_run_folder(self):
        summary = self._require_summary()
        if not summary:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(summary.path.resolve())))

    def _export_run_csv(self):
        summary = self._require_summary()
        if not summary:
            return
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

    def _delete_run(self):
        summary = self._require_summary()
        if not summary:
            return
        resp = QMessageBox.question(
            self,
            "Delete Run",
            f"Delete run '{summary.run_id}'? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        try:
            shutil.rmtree(summary.path)
        except Exception as exc:
            QMessageBox.warning(self, "Delete", f"Failed to delete run: {exc}")
            return
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
        for btn in (self.refresh_btn, self.open_btn, self.export_btn, self.delete_btn):
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
        total = max(1, self.width())
        right = int(round(total * 0.75))
        left = max(360, total - right)
        split.set_pane_sizes([left, right])
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


def _run_tab_handle_frame(self, frame):
    if self.cap is None or frame is None:
        return
    overlay = frame.copy()
    self._preview_frame_counter += 1
    try:
        text = f"T+{(time.monotonic()-(self.run_start or time.monotonic())):8.3f}s" if self.run_start else "Preview"
        cv2.putText(overlay, text, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    except Exception:
        pass
    h, w = overlay.shape[:2]
    if w and h:
        self._maybe_update_preview_aspect(w, h)
    qimg = QImage(overlay.data, w, h, 3 * w, QImage.Format_BGR888)
    pix = QPixmap.fromImage(qimg)
    self.video_view.set_image(pix)
    if self._pip_window:
        self._pip_window.set_pixmap(pix)
    if self.recorder:
        self._recorded_frame_counter += 1
        self.recorder.write(overlay)


def _run_tab_start_frame_stream(self):
    if self.cap is None or self._frame_worker is not None:
        return
    interval = int(1000 / max(1, self.preview_fps))
    self._frame_worker = FrameWorker(self.cap, interval)
    self._frame_worker.frameReady.connect(self._handle_frame, Qt.QueuedConnection)
    self._frame_worker.error.connect(self._update_status, Qt.QueuedConnection)
    self._frame_worker.stopped.connect(self._cleanup_frame_stream, Qt.QueuedConnection)
    self._frame_worker.start()


def _run_tab_stop_frame_stream(self):
    worker = self._frame_worker
    if worker:
        worker.stop()
    self._cleanup_frame_stream()


def _run_tab_cleanup_frame_stream(self):
    if self._frame_worker is not None:
        try:
            self._frame_worker.deleteLater()
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

    def keyPressEvent(self, event):
        modifiers = event.modifiers()
        key = event.key()
        is_cmd = bool(modifiers & Qt.MetaModifier)
        is_ctrl = bool(modifiers & Qt.ControlModifier)
        is_alt = bool(modifiers & Qt.AltModifier)
        handled = False
        if is_cmd or is_ctrl:
            if key == Qt.Key_T:
                self._show_new_tab_menu()
                handled = True
            elif key == Qt.Key_W:
                self._close_current_tab_with_prompt()
                handled = True
            elif is_alt and key in (Qt.Key_Left, Qt.Key_Right):
                self._cycle_tabs(-1 if key == Qt.Key_Left else 1)
                handled = True
        if handled:
            event.accept()
            return
        widget = self.tab_widget.currentWidget()
        if isinstance(widget, RunTab):
            widget.keyPressEvent(event)
        else:
            super().keyPressEvent(event)

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

    def _send_tap(self, mark="scheduled"):
        # Do not log or count taps if serial is disconnected
        if not self.serial.is_open():
            self._update_status("Tap skipped: serial disconnected.")
            return
        t_host = time.monotonic();
        self._send_serial_char('t', f"Tap ({mark})")
        self.taps += 1
        elapsed = t_host - (self.run_start or t_host)
        self._record_tap_interval(t_host)
        self._last_run_elapsed = elapsed if elapsed > 0 else self._last_run_elapsed
        overall_rate = (self.taps/elapsed*60.0) if elapsed>0 else 0.0
        recent_rate = self._recent_rate_per_min()
        recent_str = f"{recent_rate:.2f}" if recent_rate is not None else "--"
        overall_str = f"{overall_rate:.2f}" if elapsed > 0 else "--"
        elapsed_display = int(round(elapsed))
        self.counters.setText(
            f"Taps: {self.taps} | Elapsed: {elapsed_display} s | Rate10: {recent_str} /min | Overall: {overall_str} /min"
        )
        if self.logger:
            host_iso = datetime.now(timezone.utc).isoformat()
            self.logger.log_tap(
                host_time_s=t_host,
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

    # Frame loop
    def _handle_frame(self, frame):
        if self.cap is None or frame is None:
            return
        overlay = frame.copy()
        self._preview_frame_counter += 1
        try:
            text = f"T+{(time.monotonic()-(self.run_start or time.monotonic())):8.3f}s" if self.run_start else "Preview"
            cv2.putText(overlay, text, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2, cv2.LINE_AA)
        except Exception:
            pass
        h, w = overlay.shape[:2]
        if w and h:
            self._maybe_update_preview_aspect(w, h)
        qimg = QImage(overlay.data, w, h, 3*w, QImage.Format_BGR888)
        pix = QPixmap.fromImage(qimg)
        self.video_view.set_image(pix)
        if self._pip_window:
            self._pip_window.set_pixmap(pix)
        if self.recorder:
            self._recorded_frame_counter += 1
            self.recorder.write(overlay)

    def _start_frame_stream(self):
        if self.cap is None or self._frame_worker is not None:
            return
        interval = int(1000 / max(1, self.preview_fps))
        self._frame_worker = FrameWorker(self.cap, interval)
        self._frame_worker.frameReady.connect(self._handle_frame, Qt.QueuedConnection)
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
        port = self.port_edit.currentText().strip() if self.serial.is_open() else "—"
        serial_state = f"serial:{port}" if self.serial.is_open() else "serial:DISCONNECTED"
        mode = self.mode.currentText()
        param = f"P={self.period_sec.value():.2f}s" if mode=="Periodic" else f"λ={self.lambda_rpm.value():.2f}/min"
        taps = self.taps
        if self.run_start:
            elapsed = time.monotonic() - self.run_start
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
    w = App(); w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
