# app.py — NEMESIS UI (v1.0-rc1, unified feature set)
import sys, os, time, json, uuid
from pathlib import Path
from collections.abc import Sequence

from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QFileDialog,
    QHBoxLayout, QVBoxLayout, QGridLayout, QComboBox, QSpinBox, QDoubleSpinBox,
    QLineEdit, QMessageBox, QSizePolicy, QListView, QSplitter, QStyleFactory, QFrame,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsProxyWidget, QSplitterHandle
)
from PySide6.QtCore import (
    QTimer, Qt, QEvent, QSize, Signal, QObject, QThread, QMetaObject, Slot
)
from PySide6.QtGui import QImage, QPixmap, QFontDatabase, QFont, QIcon, QPainter, QColor, QPen
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator
import matplotlib as mpl
from matplotlib import font_manager

# Internal modules
from .core import video, scheduler, configio
from .core import logger as runlogger
from .drivers.arduino_driver import SerialLink
import cv2

# ---- Assets & Version ----
# Resolve assets relative to the project root, not the current working directory
BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = BASE_DIR / "assets"
FONT_PATH = ASSETS_DIR / "fonts/Typestar OCR Regular.otf"
LOGO_PATH = ASSETS_DIR / "images/logo.png"
APP_VERSION = "1.0-rc1"
_FONT_FAMILY = None  # set at runtime when font loads

# ---- Theme (dark, information-dense) ----
BG     = "#0d0f12"
MID    = "#161a1f"
TEXT   = "#b8c0cc"
SUBTXT = "#8a93a3"
ACCENT = "#5aa3ff"
DANGER = "#e33"

def build_stylesheet(font_family: str | None, scale: float = 1.0) -> str:
    s = max(0.7, min(scale, 2.0))
    family_rule = f"font-family: '{font_family}';" if font_family else ""
    font_pt = int(round(11 * s))
    status_pt = int(round(10 * s))
    btn_py = int(round(6 * s)); btn_px = int(round(10 * s)); rad = int(round(6 * s))
    inp_py = int(round(4 * s)); inp_px = int(round(6 * s))
    return f"""
* {{ background: {BG}; color: {TEXT}; font-size: {font_pt}pt; {family_rule} }}
QWidget {{ background: {BG}; }}
QLabel#StatusLine {{ color: {TEXT}; font-size: {status_pt}pt; }}
QPushButton {{ background: {MID}; border:1px solid #252a31; padding:{btn_py}px {btn_px}px; border-radius:{rad}px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:checked {{ background:#1f2731; border-color:{ACCENT}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background:{MID}; border:1px solid #252a31; padding:{inp_py}px {inp_px}px; border-radius:{rad}px; }}
/* Disabled state — strongly greyed out for clarity */
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    background: #0a0d11;        /* darker than BG */
    color: #5e6876;             /* much dimmer text */
    border: 1px solid #11161c;  /* subdued border */
}}
QLabel:disabled {{ color: #5e6876; }}
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

def apply_matplotlib_theme(font_family: str | None):
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
    mpl.rcParams.update({
        "font.family": [family],
        "font.sans-serif": [family, "DejaVu Sans", "Arial"],
        "font.size": base_size,
        "axes.titlesize": base_size,
        "axes.labelsize": base_size,
        "xtick.labelsize": tick_size,
        "ytick.labelsize": tick_size,
        "figure.facecolor": MID,
        "axes.facecolor": MID,
        "axes.edgecolor": TEXT,
        "axes.labelcolor": TEXT,
        "xtick.color": TEXT,
        "ytick.color": TEXT,
        "text.color": TEXT,
        "figure.autolayout": True,
        "grid.color": "#3a414b",
        "grid.linestyle": ":",
        "grid.alpha": 0.8,
        "axes.titleweight": "regular",
        "axes.titlepad": 8,
        "axes.grid": False,
        "savefig.facecolor": MID,
        "savefig.edgecolor": MID,
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
    def __init__(self, font_family: str | None):
        apply_matplotlib_theme(font_family)
        self.fig, (self.ax_top, self.ax_bot) = plt.subplots(
            2, 1, sharex=True, figsize=(6.2, 3.2),
            gridspec_kw={"height_ratios": [1, 5]}
        )
        # Compact layout and tighter suptitle position to reduce top padding
        try:
            self.fig.subplots_adjust(top=0.86, bottom=0.18, left=0.10, right=0.98, hspace=0.08)
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
        self._init_axes()

    def _init_axes(self):
        self.fig.suptitle("Stentor Habituation to Stimuli", fontsize=10, color=TEXT, y=0.96)
        # Make figure/axes transparent so the framed panel shows through
        try:
            self.fig.patch.set_alpha(0.0)
            self.fig.patch.set_facecolor('none')
        except Exception:
            pass
        ax = self.ax_top
        ax.clear()
        try:
            ax.set_facecolor('none')
        except Exception:
            pass
        ax.set_ylabel("Taps", color=TEXT)
        ax.set_yticks([])
        ax.set_xlim(0, 70)
        ax.xaxis.set_major_locator(MultipleLocator(10))
        ax.xaxis.set_minor_locator(MultipleLocator(1))
        ax.grid(True, which="major", axis="x", linestyle=":", alpha=0.9)
        ax.grid(True, which="minor", axis="x", linestyle=":", alpha=0.35)
        for spine in ax.spines.values():
            spine.set_color(TEXT)

        ax2 = self.ax_bot
        ax2.clear()
        try:
            ax2.set_facecolor('none')
        except Exception:
            pass
        ax2.set_xlabel("Time (minutes)")
        ax2.set_ylabel("% Contracted")
        ax2.set_ylim(-5, 105)
        ax2.set_xlim(0, 70)
        ax2.xaxis.set_major_locator(MultipleLocator(10))
        ax2.xaxis.set_minor_locator(MultipleLocator(1))
        ax2.grid(True, which="major", axis="x", linestyle=":", alpha=0.9)
        ax2.grid(True, which="minor", axis="x", linestyle=":", alpha=0.35)
        ax2.yaxis.set_major_formatter(plt.FuncFormatter("{:.0f}%".format))
        for spine in ax2.spines.values():
            spine.set_color(TEXT)
        self.canvas.draw_idle()

    def reset(self):
        self.times_sec.clear()
        self._init_axes()

    def add_tap(self, t_since_start_s: float):
        self.times_sec.append(float(t_since_start_s))
        self._redraw()

    def _redraw(self):
        ts_min = [t / 60.0 for t in self.times_sec]
        highlighted = [t for i, t in enumerate(ts_min) if (i + 1) % 10 == 0]
        regular     = [t for i, t in enumerate(ts_min) if (i + 1) % 10 != 0]

        ax = self.ax_top
        ax.cla()
        try:
            ax.set_facecolor('none')
        except Exception:
            pass
        ax.set_ylabel("Taps", color=TEXT)
        ax.set_yticks([])
        ax.set_xlim(0, 70)
        ax.xaxis.set_major_locator(MultipleLocator(10))
        ax.xaxis.set_minor_locator(MultipleLocator(1))
        ax.grid(True, which="major", axis="x", linestyle=":", alpha=0.9)
        ax.grid(True, which="minor", axis="x", linestyle=":", alpha=0.35)
        for spine in ax.spines.values():
            spine.set_color(TEXT)

        if regular:
            ax.eventplot(regular, orientation="horizontal", colors=TEXT, linewidth=0.9)
        if highlighted:
            ax.eventplot(highlighted, orientation="horizontal", colors=ACCENT, linewidth=1.6)
        self.ax_bot.set_ylim(-5, 105)
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
            "QScrollBar::handle:vertical { background: #2a2f36; border-radius: 3px; }\n"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; background: transparent; }\n"
            "QScrollBar:horizontal { height: 6px; background: transparent; margin: 2px; }\n"
            "QScrollBar::handle:horizontal { background: #2a2f36; border-radius: 3px; }\n"
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
        self._sb_timer = QTimer(self)
        self._sb_timer.setSingleShot(True)
        self._sb_timer.timeout.connect(self._hide_scrollbars)
        # Enable pinch gesture across platforms
        try:
            self.grabGesture(Qt.PinchGesture)
        except Exception:
            pass

    def set_image(self, pix: QPixmap):
        self._pix.setPixmap(pix)
        if not self._has_image:
            self._has_image = True
            try:
                self.fitInView(self._pix, Qt.KeepAspectRatio)
                self._zoom = 1.0
            except Exception:
                pass
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
        self._emitted_first = False
        self._has_image = False

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
            try:
                self.fitInView(self._pix, Qt.KeepAspectRatio)
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
    def __init__(self, orientation: Qt.Orientation, parent=None):
        super().__init__(orientation, parent)
        self.setCursor(Qt.SplitHCursor if orientation == Qt.Horizontal else Qt.SplitVCursor)
        self._base = QColor(BG)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(BG))
        self.setPalette(pal)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        rect = self.rect()
        painter.fillRect(rect, QColor(BG))
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._base)
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
            pen = QPen(QColor(ACCENT))
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


class GuideSplitter(QSplitter):
    def __init__(self, orientation: Qt.Orientation, parent=None, *, snap_targets=None, snap_tolerance: float = 0.03):
        super().__init__(orientation, parent)
        self._snap_targets = sorted(snap_targets or (0.25, 0.5, 0.75))
        self._snap_tolerance = float(max(0.005, snap_tolerance))
        self._active_ratio: float | None = None
        self._active_handle_index: int | None = None
        # Live resize with no rubber-band painter
        self.setOpaqueResize(True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(BG))
        self.setPalette(pal)
        try:
            self.setRubberBand(-1)
        except Exception:
            pass
        self.setStyleSheet(
            f"QSplitter {{ background: {BG}; }}"
            "QSplitter::handle { background: transparent; border: none; image: none; }"
            "QSplitter::rubberBand { background: transparent; border: none; }"
        )
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._clear_active_ratio)
        try:
            self.splitterMoved.connect(self._on_splitter_moved)
        except Exception:
            pass

    def createHandle(self):
        return GuideSplitterHandle(self.orientation(), self)

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
        accent = QColor(ACCENT)
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
        self._interval_ms = max(5, int(interval_ms))
        self._timer: QTimer | None = None
        self._running = False

    @Slot()
    def start(self):
        if self._running:
            return
        self._running = True
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(self._interval_ms)
        self._timer.timeout.connect(self._poll_frame)
        self._timer.start()

    @Slot()
    def stop(self):
        if not self._running:
            return
        self._running = False
        if self._timer:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None
        self.stopped.emit()

    @Slot()
    def _poll_frame(self):
        if not self._running:
            return
        try:
            ok, frame = self._capture.read()
        except Exception as exc:
            self.error.emit(f"Camera error: {exc}")
            return
        if not ok or frame is None:
            return
        self.frameReady.emit(frame)


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

    def _apply_border_style(self):
        border = f"{self._border_px}px solid #333" if self._show_border else "none"
        self.setStyleSheet(f"background: {BG}; border: {border};")

    def set_border_visible(self, on: bool):
        self._show_border = bool(on)
        self._apply_border_style()
        # Relayout to account for changed effective border width
        try:
            self.updateGeometry()
        except Exception:
            pass
        self.update()

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
        self.setStyleSheet("""
            QScrollBar:vertical { width: 6px; background: transparent; margin: 2px; }
            QScrollBar::handle:vertical { background: #2a2f36; border-radius: 3px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; background: transparent; }
            QScrollBar:horizontal { height: 6px; background: transparent; margin: 2px; }
            QScrollBar::handle:horizontal { background: #2a2f36; border-radius: 3px; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; background: transparent; }
        """)
        # State
        self._scale = 1.0
        self._min_scale = 1.0
        self._max_scale = 1.8
        self._sb_timer = QTimer(self)
        self._sb_timer.setSingleShot(True)
        self._sb_timer.timeout.connect(self._hide_scrollbars)
        try:
            self.grabGesture(Qt.PinchGesture)
        except Exception:
            pass

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
            hint = QSize(900, 540)
        self._base_size = hint
        self._apply_geometry_to_proxy()
        self._update_interaction_state()

    def set_scale(self, s: float):
        s = max(self._min_scale, min(s, self._max_scale))
        self._scale = s
        self.resetTransform()
        self.scale(s, s)
        self._show_scrollbars_temporarily()
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
            if self._scale <= 1.0 + 1e-3:
                # At base scale, don't allow panning at all
                e.accept()
                return
            pd = e.pixelDelta(); ad = e.angleDelta()
            dx = pd.x() if not pd.isNull() else ad.x()
            dy = pd.y() if not pd.isNull() else ad.y()
            h = self.horizontalScrollBar(); v = self.verticalScrollBar()
            if h: h.setValue(h.value() - dx)
            if v: v.setValue(v.value() - dy)
            e.accept(); self._show_scrollbars_temporarily(); return
        except Exception:
            pass
        return super().wheelEvent(e)

    def _show_scrollbars_temporarily(self):
        try:
            if self.horizontalScrollBar(): self.horizontalScrollBar().setVisible(True)
            if self.verticalScrollBar(): self.verticalScrollBar().setVisible(True)
            self._sb_timer.start(700)
        except Exception:
            pass

    def _hide_scrollbars(self):
        try:
            if self.horizontalScrollBar(): self.horizontalScrollBar().setVisible(False)
            if self.verticalScrollBar(): self.verticalScrollBar().setVisible(False)
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
            if self._scale <= 1.0 + 1e-3:
                # Disable panning entirely at base scale
                self.setDragMode(QGraphicsView.NoDrag)
                if self.horizontalScrollBar(): self.horizontalScrollBar().setVisible(False)
                if self.verticalScrollBar(): self.verticalScrollBar().setVisible(False)
                # Clamp scroll ranges so two-finger scroll cannot move content
                if self.horizontalScrollBar(): self.horizontalScrollBar().setRange(0, 0)
                if self.verticalScrollBar(): self.verticalScrollBar().setRange(0, 0)
            else:
                self.setDragMode(QGraphicsView.ScrollHandDrag)
                # Let Qt manage ranges normally when zoomed in or content exceeds viewport
                # Ranges will be reset by Qt on sceneRect/resize events
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


class App(QWidget):
    class StyledCombo(QComboBox):
        def __init__(self, popup_qss: str = "", *args, **kwargs):
            super().__init__(*args, **kwargs)
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

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"NEMESIS {APP_VERSION} — Non-periodic Event Monitoring & Evaluation of Stimulus-Induced States")
        if LOGO_PATH.exists():
            self.setWindowIcon(QIcon(str(LOGO_PATH)))
        self.resize(1260, 800)
        self.ui_scale = 1.0
        # Bring back a sensible minimum window size to avoid collapsing
        self.setMinimumSize(900, 540)

        # ---------- Top dense status line + inline logo ----------
        header_row = QHBoxLayout()
        self.statusline = QLabel("—")
        self.statusline.setObjectName("StatusLine")
        self.statusline.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.statusline.setWordWrap(True)
        self.statusline.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        header_row.addWidget(self.statusline, 1)

        # ---------- Video preview (zoomable/pannable) ----------
        self.video_view = ZoomView(bg_color=BG)
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

        # ---------- Serial controls ----------
        self.port_edit = QLineEdit(); self.port_edit.setPlaceholderText("COM3 or /dev/ttyUSB0")
        self.serial_btn = QPushButton("Connect Serial")
        self.enable_btn = QPushButton("Enable Motor")
        self.disable_btn = QPushButton("Disable Motor")
        self.tap_btn = QPushButton("Manual Tap")
        # Jog controls (half‑step moves handled by firmware)
        self.jog_up_btn = QPushButton("Raise Arm ▲")
        self.jog_down_btn = QPushButton("Lower Arm ▼")
        self.jog_up_btn.setToolTip("Raise tapper arm (half step)")
        self.jog_down_btn.setToolTip("Lower tapper arm (half step)")

        # ---------- Camera controls ----------
        self.cam_index = QSpinBox(); self.cam_index.setRange(0, 8); self.cam_index.setValue(0)
        self.cam_btn = QPushButton("Open Camera")

        # ---------- Recording controls (independent) ----------
        self.rec_start_btn = QPushButton("Start Recording")
        self.rec_stop_btn  = QPushButton("Stop Recording")
        self.rec_indicator = QLabel("● REC OFF")

        # ---------- Scheduler controls ----------
        popup_qss = f"""
            QListView {{
                background: {MID};
                color: {TEXT};
                border: 1px solid {BG};
                border-radius: 0px;
                padding: 4px 0;
                outline: none;
            }}
            QListView::item {{
                padding: 6px 12px;
                background: transparent;
            }}
            QListView::item:selected {{
                background: {ACCENT};
                color: {BG};
            }}
        """
        self.mode = App.StyledCombo(popup_qss=popup_qss); self.mode.addItems(["Periodic", "Poisson"])
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
        self.stepsize = App.StyledCombo(popup_qss=popup_qss); self.stepsize.addItems(["1 (Full Step)","2 (Half Step)","3 (1/4 Step)","4 (1/8 Step)","5 (1/16 Step)"]); self.stepsize.setCurrentText("4")
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

        # Output directory
        self.outdir_edit = QLineEdit()
        self.outdir_btn  = QPushButton("Choose Output Dir")

        # Config Save/Load
        self.save_cfg_btn = QPushButton("Save Config")
        self.load_cfg_btn = QPushButton("Load Last Config")

        # Pro Mode (keyboard-first interaction)
        self.pro_btn = QPushButton("Pro Mode: OFF")
        self.pro_btn.setCheckable(True)
        self.pro_btn.toggled.connect(self._toggle_pro_mode)
        self.pro_mode = False

        # Live chart (template-like raster): embedded Matplotlib, Typestar font
        self.live_chart = LiveChart(font_family=_FONT_FAMILY)
        # Wrap chart in a framed panel to match other boxes (use BG to match general background)
        self.chart_frame = QFrame()
        # Match the video preview container styling exactly
        self.chart_frame.setStyleSheet(f"background: {BG}; border: 1px solid #333;")
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
        self.counters = QLabel("Taps: 0 | Elapsed: 0.0 s | Observed rate: 0.0 /min")
        serial_logo_row = QHBoxLayout()
        serial_logo_row.setContentsMargins(0, 0, 0, 0)
        serial_logo_row.setSpacing(12)

        self.serial_status = QLabel("Last serial command: —")
        self.serial_status.setWordWrap(True)
        try:
            self.serial_status.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        except Exception:
            pass
        self.serial_status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        serial_logo_row.addWidget(self.serial_status, 1)

        self.logo_footer = QLabel()
        self.logo_footer.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        footer_pm = None
        if LOGO_PATH.exists():
            candidate = QPixmap(str(LOGO_PATH))
            if not candidate.isNull():
                scale_factor = 0.35
                target_w = max(1, int(candidate.width() * scale_factor))
                target_h = max(1, int(candidate.height() * scale_factor))
                footer_pm = candidate.scaled(target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if footer_pm is not None:
            src = footer_pm.toImage().convertToFormat(QImage.Format_ARGB32)
            w, h = src.width(), src.height()
            cropped = footer_pm.copy(src.rect())
            # Use transparent background to recolor to black while respecting alpha
            masked = QPixmap(w, h)
            masked.fill(Qt.transparent)
            painter = QPainter(masked)
            painter.fillRect(masked.rect(), Qt.black)
            painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            painter.drawPixmap(0, 0, footer_pm)
            painter.end()

            # Outline using alpha edge detection
            outline = QImage(w, h, QImage.Format_ARGB32)
            outline.fill(Qt.transparent)
            for y in range(h):
                for x in range(w):
                    if QColor(src.pixel(x, y)).alpha() == 0:
                        continue
                    edge = False
                    for dx in (-1, 0, 1):
                        for dy in (-1, 0, 1):
                            if dx == 0 and dy == 0:
                                continue
                            nx, ny = x + dx, y + dy
                            if nx < 0 or ny < 0 or nx >= w or ny >= h or QColor(src.pixel(nx, ny)).alpha() == 0:
                                edge = True
                                break
                        if edge:
                            break
                    if edge:
                        outline.setPixelColor(x, y, QColor("#333"))

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
        serial_logo_row.addWidget(self.logo_footer, 0, Qt.AlignLeft | Qt.AlignBottom)

        # ---------- Layout ----------
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
        right = QVBoxLayout(); right.setContentsMargins(0, 0, 0, 0); right.setSpacing(8)
        right.addLayout(header_row)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Serial:")); r1.addWidget(self.port_edit,1); r1.addWidget(self.serial_btn); r1.addWidget(self.pro_btn)
        right.addLayout(r1)

        r1b = QHBoxLayout(); r1b.addWidget(self.enable_btn); r1b.addWidget(self.disable_btn); r1b.addWidget(self.tap_btn); right.addLayout(r1b)
        # Place jog controls directly under Activate/Deactivate row
        r1c = QHBoxLayout(); r1c.addWidget(self.jog_down_btn); r1c.addWidget(self.jog_up_btn); right.addLayout(r1c)

        r2 = QHBoxLayout(); r2.addWidget(QLabel("Camera idx:")); r2.addWidget(self.cam_index); r2.addWidget(self.cam_btn)
        self.popout_btn = QPushButton("Pop-out Preview")
        self.popout_btn.setCheckable(True)
        self.popout_btn.setToolTip("Open a floating always-on-top preview window")
        self.popout_btn.toggled.connect(self._toggle_preview_popout)
        r2.addWidget(self.popout_btn)
        right.addLayout(r2)

        r2b = QHBoxLayout(); r2b.addWidget(self.rec_start_btn); r2b.addWidget(self.rec_stop_btn); r2b.addWidget(self.rec_indicator); right.addLayout(r2b)

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
        right.addLayout(controls_grid)

        r3b = QHBoxLayout(); r3b.addWidget(QLabel("Seed:")); r3b.addWidget(self.seed_edit,1); right.addLayout(r3b)

        r4 = QHBoxLayout(); r4.addWidget(self.run_start_btn); r4.addWidget(self.run_stop_btn); right.addLayout(r4)

        r5 = QHBoxLayout(); r5.addWidget(QLabel("Output dir:")); r5.addWidget(self.outdir_edit,1); r5.addWidget(self.outdir_btn); right.addLayout(r5)
        
        # Config save/load row (was missing from layout)
        r5b = QHBoxLayout(); r5b.addWidget(self.save_cfg_btn); r5b.addWidget(self.load_cfg_btn); right.addLayout(r5b)

        # (chart moved under the video preview)
        right.addWidget(self.counters)
        right.addWidget(self.status)
        right.addLayout(serial_logo_row)
        right.addStretch(1)

        # Decouple panes with a splitter so right-side changes don't tug the preview
        leftw = QWidget(); leftw.setLayout(left)
        leftw.setAutoFillBackground(True)
        pal_left = leftw.palette(); pal_left.setColor(leftw.backgroundRole(), QColor(BG)); leftw.setPalette(pal_left)
        try:
            # Prevent splitter from shrinking left content beneath a usable width
            leftw.setMinimumWidth(max(360, self.video_area.minimumWidth()))
        except Exception:
            pass
        rightw = QWidget(); rightw.setLayout(right)
        rightw.setAutoFillBackground(True)
        pal_right = rightw.palette(); pal_right.setColor(rightw.backgroundRole(), QColor(BG)); rightw.setPalette(pal_right)
        try:
            rightw.setMinimumWidth(360)
        except Exception:
            pass
        splitter = GuideSplitter(Qt.Horizontal, snap_targets=(0.25, 0.5, 0.75))
        splitter.addWidget(leftw)
        splitter.addWidget(rightw)
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

        self.splitter = splitter

        # Wrap entire UI content in a zoomable view for browser-like zoom
        contentw = QWidget(); content_layout = QHBoxLayout(contentw); content_layout.setContentsMargins(0,0,0,0); content_layout.addWidget(splitter)
        self.app_view = AppZoomView(bg_color=BG)
        self.app_view.set_content(contentw)
        # Enforce a minimum window size that encompasses the full UI content
        try:
            min_hint = contentw.minimumSizeHint()
            if not min_hint.isValid() or min_hint.width() <= 0:
                min_hint = contentw.sizeHint()
            min_w = max(900, min_hint.width())
            min_h = max(540, min_hint.height())
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

        # ---------- State ----------
        self.cap = None
        self.recorder = None
        self._frame_thread: QThread | None = None
        self._frame_worker: FrameWorker | None = None
        self.run_timer   = QTimer(self); self.run_timer.setSingleShot(True); self.run_timer.timeout.connect(self._on_tap_due)
        self.scheduler = scheduler.TapScheduler()
        self.serial    = SerialLink()
        self.logger    = None
        self.run_dir   = None
        self.run_start = None
        self.taps = 0; self.preview_fps = 30; self.current_stepsize = 4
        self._pip_window: PinnedPreviewWindow | None = None

        # Dense status line updater
        self.status_timer = QTimer(self); self.status_timer.timeout.connect(self._refresh_statusline); self.status_timer.start(400)

        # ---------- Signals ----------
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
        self.outdir_btn.clicked.connect(self._choose_outdir)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.save_cfg_btn.clicked.connect(self._save_config_clicked)
        self.load_cfg_btn.clicked.connect(self._load_config_clicked)

        # Install global event filter for pinch zoom (app-wide)
        try:
            QApplication.instance().installEventFilter(self)
        except Exception:
            pass
        self._mode_changed(); self._update_status("Ready.")
        self._reset_serial_indicator()

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

    # ---------- Pro Mode ----------
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
        if key == Qt.Key_S: self._start_run() if self.logger is None else self._stop_run(); return
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

    # ---------- Stepsize ----------
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
        val = max(1, min(val, 5))
        self.current_stepsize = val
        self.stepsize.blockSignals(True)
        try:
            self.stepsize.setCurrentIndex(val-1)
        finally:
            self.stepsize.blockSignals(False)
        # Send '1'..'5' to firmware; Arduino code already maps this to microstepping profile
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

    # ---------- Camera ----------
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
        if self.cap is None:
            self.cap = video.VideoCapture(idx)
            if not self.cap.open():
                self._update_status("Failed to open camera."); self.cap = None; return
            try:
                w, h = self.cap.get_size()
                if w and h:
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
            # Reset to 16:9 when closed
            try:
                self.video_area.set_aspect(16, 9)
                self.video_area.set_border_visible(True)
                self.video_view.reset_first_frame()
                self.video_area.update()
                if self._pip_window:
                    self._pip_window.set_aspect(16, 9)
                    self._pip_window.set_border_visible(True)
                    self._pip_window.reset_first_frame()
            except Exception:
                pass
            self.cam_btn.setText("Open Camera"); self._update_status("Camera closed.")

    # ---------- Serial ----------
    def _toggle_serial(self):
        if not self.serial.is_open():
            port = self.port_edit.text().strip()
            if not port: self._update_status("Enter a serial port first."); return
            try:
                self.serial.open(port, baudrate=9600, timeout=0)
                self.serial_btn.setText("Disconnect Serial"); self._update_status(f"Serial connected on {port}.")
                self._reset_serial_indicator("connected")
            except Exception as e:
                self._update_status(f"Serial error: {e}")
                self._reset_serial_indicator("error")
        else:
            self.serial.close(); self.serial_btn.setText("Connect Serial"); self._update_status("Serial disconnected.")
            self._reset_serial_indicator("disconnected")

    # ---------- Output dir ----------
    def _choose_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "Choose output directory")
        if d: self.outdir_edit.setText(d)

    # ---------- Recording ----------
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
        # Use the actual path (handles fallback to .avi)
        actual_path = Path(self.recorder.path)
        # If a run is already active, inject path into logger for subsequent rows
        if self.logger:
            self.logger.set_recording_path(str(actual_path))
        self.rec_indicator.setText("● REC ON"); self.rec_indicator.setStyleSheet(f"color:{DANGER}; font-weight:bold;")
        self._update_status(f"Recording → {actual_path}")

    def _stop_recording(self):
        if self.recorder:
            self.recorder.close(); self.recorder = None
            self.rec_indicator.setText("● REC OFF"); self.rec_indicator.setStyleSheet(f"color:{SUBTXT};")
            self._update_status("Recording stopped.")

    # ---------- Config Save/Load ----------
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

    # ---------- Scheduler / Run ----------
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
        if self.recorder is None:
            resp = QMessageBox.question(self, "No Recording Active",
                "You're starting a run without recording video. Continue anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if resp == QMessageBox.No: return
        outdir = self.outdir_edit.text().strip() or os.getcwd()
        ts = time.strftime("%Y%m%d_%H%M%S")
        run_token = uuid.uuid4().hex[:6].upper()
        run_id = f"run_{ts}_{run_token}"
        self.run_dir = Path(outdir) / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        rec_path = getattr(self.recorder, "path", "") if self.recorder else ""
        self.logger = runlogger.RunLogger(self.run_dir, run_id=run_id, recording_path=rec_path)
        self.run_start = time.monotonic(); self.taps = 0

        # Seed & scheduler config
        seed = self._seed_value_or_none()
        self.scheduler.set_seed(seed)
        if self.mode.currentText()=="Periodic":
            self.scheduler.configure_periodic(self.period_sec.value())
        else:
            self.scheduler.configure_poisson(self.lambda_rpm.value())

        # Snapshot run.json
        run_json = {
            "run_id": self.logger.run_id,
            "started_at": ts,
            "app_version": APP_VERSION,
            "firmware_commit": "",  # optional
            "camera_index": self.cam_index.value(),
            "recording_path": rec_path,
            "serial_port": self.port_edit.text().strip(),
            "mode": self.mode.currentText(),
            "period_sec": self.period_sec.value(),
            "lambda_rpm": self.lambda_rpm.value(),
            "seed": seed,
            "stepsize": self.current_stepsize,
            "scheduler": self.scheduler.descriptor(),
        }
        try:
            with open(self.run_dir/"run.json", "w", encoding="utf-8") as f:
                json.dump(run_json, f, indent=2)
        except Exception as e:
            self._update_status(f"Failed to write run.json: {e}")

        delay = self.scheduler.next_delay_s()
        self.run_timer.start(int(delay*1000)); self._update_status(f"Run started → next tap in {delay:.3f}s")
        # Reset live chart data
        try:
            self.live_chart.reset()
        except Exception:
            pass

    def _stop_run(self):
        self.run_timer.stop()
        if self.logger: self.logger.close(); self.logger = None
        self.run_dir = None; self.run_start = None
        self._update_status("Run stopped.")

    def _manual_tap(self): self._send_tap("manual")

    def _on_tap_due(self):
        self._send_tap("scheduled")
        delay = self.scheduler.next_delay_s()
        self.run_timer.start(int(delay*1000)); self._update_status(f"Tap sent. Next in {delay:.3f}s")

    def _send_tap(self, mark="scheduled"):
        # Do not log or count taps if serial is disconnected
        if not self.serial.is_open():
            self._update_status("Tap skipped: serial disconnected.")
            return
        t_host = time.monotonic();
        self._send_serial_char('t', f"Tap ({mark})")
        self.taps += 1
        elapsed = t_host - (self.run_start or t_host)
        rate = (self.taps/elapsed*60.0) if elapsed>0 else 0.0
        self.counters.setText(f"Taps: {self.taps} | Elapsed: {elapsed:.1f} s | Observed rate: {rate:.2f} /min")
        if self.logger:
            self.logger.log_tap(host_time_s=t_host, mode=self.mode.currentText(), mark=mark, stepsize=self.current_stepsize)
        # Update live chart (raster)
        try:
            if self.run_start:
                self.live_chart.add_tap(elapsed)
        except Exception:
            pass

    # ---------- Frame loop ----------
    def _handle_frame(self, frame):
        if self.cap is None or frame is None:
            return
        overlay = frame.copy()
        try:
            text = f"T+{(time.monotonic()-(self.run_start or time.monotonic())):8.3f}s" if self.run_start else "Preview"
            cv2.putText(overlay, text, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2, cv2.LINE_AA)
        except Exception:
            pass
        h, w = overlay.shape[:2]
        qimg = QImage(overlay.data, w, h, 3*w, QImage.Format_BGR888)
        pix = QPixmap.fromImage(qimg)
        self.video_view.set_image(pix)
        if self._pip_window:
            self._pip_window.set_pixmap(pix)
        if self.recorder: self.recorder.write(overlay)

    def _start_frame_stream(self):
        if self.cap is None or self._frame_worker is not None:
            return
        interval = int(1000 / max(1, self.preview_fps))
        self._frame_thread = QThread(self)
        self._frame_worker = FrameWorker(self.cap, interval)
        self._frame_worker.moveToThread(self._frame_thread)
        self._frame_worker.frameReady.connect(self._handle_frame, Qt.QueuedConnection)
        self._frame_worker.error.connect(self._update_status, Qt.QueuedConnection)
        self._frame_worker.stopped.connect(self._frame_thread.quit)
        self._frame_thread.finished.connect(self._cleanup_frame_stream)
        self._frame_thread.started.connect(self._frame_worker.start)
        self._frame_thread.start()

    def _stop_frame_stream(self):
        worker = self._frame_worker
        thread = self._frame_thread
        if worker:
            QMetaObject.invokeMethod(worker, "stop", Qt.QueuedConnection)
        if thread:
            thread.quit()
            thread.wait(700)
        self._cleanup_frame_stream()

    def _cleanup_frame_stream(self):
        if self._frame_worker is not None:
            try:
                self._frame_worker.deleteLater()
            except Exception:
                pass
            self._frame_worker = None
        if self._frame_thread is not None:
            try:
                self._frame_thread.deleteLater()
            except Exception:
                pass
            self._frame_thread = None

    # ---------- Status line refresh ----------
    def _refresh_statusline(self):
        run_id = self.logger.run_id if self.logger else "-"
        cam_idx = self.cam_index.value()
        fps = int(self.preview_fps or 0)
        rec = "REC ON" if self.recorder else "REC OFF"
        port = self.port_edit.text().strip() if self.serial.is_open() else "—"
        serial_state = f"serial:{port}" if self.serial.is_open() else "serial:DISCONNECTED"
        mode = self.mode.currentText()
        param = f"P={self.period_sec.value():.2f}s" if mode=="Periodic" else f"λ={self.lambda_rpm.value():.2f}/min"
        taps = self.taps
        elapsed = (time.monotonic() - self.run_start) if self.run_start else 0.0
        rate = (taps/elapsed*60.0) if elapsed>0 else 0.0
        txt = f"{run_id}  •  cam {cam_idx}/{fps}fps  •  {rec}  •  {serial_state}  •  {mode} {param}  •  taps:{taps}  •  t+{elapsed:6.1f}s  •  rate:{rate:5.2f}/min"
        self.statusline.setText(txt)

    def _update_status(self, msg): self.status.setText(msg)

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
            left = int(round(total * 0.75))
            right = max(360, total - left)
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
        if self._pip_window:
            try:
                self._pip_window.close()
            except Exception:
                pass
            self._pip_window = None
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
    # Set app-level icon (matters on macOS)
    try:
        if LOGO_PATH.exists():
            app.setWindowIcon(QIcon(str(LOGO_PATH)))
    except Exception:
        pass
    w = App(); w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
