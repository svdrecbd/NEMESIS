# app/ui/theme.py
import sys
from PySide6.QtGui import QColor, QFontDatabase, QFont, QPalette, QIcon, QImage, QPixmap, QPainter
from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtWidgets import QApplication, QWidget, QStylePainter, QStyleOptionTab, QStyle
from pathlib import Path
from app.core.logger import APP_LOGGER

# Constants handled by main usually, but needed here for defaults
# We will define them here to be imported by main
# Colors
BG = "#f4f7fb"
MID = "#e7ecf6"
TEXT = "#1d2334"
SUBTXT = "#4f5a6d"
ACCENT = "#3367ff"
DANGER = "#c0392b"
BORDER = "#cbd4e4"
SCROLLBAR = "#a3b1c7"
OUTLINE = "#9aa7bd"
PLOT_FACE = "#f4f7fb"
GRID = "#cdd5e5"
DISABLED_BG = "#e0e6f2"
DISABLED_TEXT = "#8a94a6"
DISABLED_BORDER = "#c5cedf"
BUTTON_BORDER = "#c0c8da"
BUTTON_CHECKED_BG = "#d6def2"
INPUT_BORDER = "#c0c8da"

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

def active_theme() -> dict[str, str]:
    return THEMES[_ACTIVE_THEME_NAME]

def set_active_theme(name: str) -> dict[str, str]:
    global _ACTIVE_THEME_NAME
    if name not in THEMES:
        raise ValueError(f"Unknown theme '{name}'")
    _ACTIVE_THEME_NAME = name
    return active_theme()

def build_stylesheet(font_family: str | None, scale: float = 1.0, theme: dict = None) -> str:
    if theme is None:
        theme = active_theme()
    
    # Extract colors for local use in f-string
    bg = theme["BG"]
    mid = theme["MID"]
    text = theme["TEXT"]
    accent = theme["ACCENT"]
    btn_border = theme["BUTTON_BORDER"]
    btn_checked = theme["BUTTON_CHECKED_BG"]
    inp_border = theme["INPUT_BORDER"]
    dis_bg = theme["DISABLED_BG"]
    dis_text = theme["DISABLED_TEXT"]
    dis_border = theme["DISABLED_BORDER"]

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
* {{ background: {bg}; color: {text}; font-size: {font_pt}pt; {family_rule} }}
QWidget {{ background: {bg}; }}
QLabel#StatusLine {{ color: {text}; font-size: {status_pt}pt; }}
QPushButton {{ background: {mid}; border:1px solid {btn_border}; padding:{btn_py}px {btn_px}px; border-radius:0px; }}
QPushButton:hover {{ border-color: {accent}; }}
QPushButton:checked {{ background:{btn_checked}; border-color:{accent}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background:{mid}; border:1px solid {inp_border}; padding:{inp_py}px {inp_px}px; border-radius:0px; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    background: {dis_bg};
    color: {dis_text};
    border: 1px solid {dis_border};
}}
QLabel:disabled {{ color: {dis_text}; }}
QTabWidget::pane {{ border: 0px; }}
QTabBar::tab {{
    padding: {tab_py}px {tab_right_px}px {tab_py}px {tab_left_px}px;
    margin: 2px;
    border: 0px;
    border-radius: 0px;
    min-width: {tab_min_w}px;
    background: {bg};
    color: {text};
    text-align: left;
}}
QTabBar::tab:selected {{
    background: {mid};
    color: {text};
    border-bottom: 2px solid {accent};
    text-align: left;
}}
QTabBar::tab:!selected {{
    background: {bg};
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
    background: {accent};
    color: {bg};
    border-radius: 0px;
}}
"""

def set_macos_titlebar_appearance(widget: QWidget, color: QColor) -> bool:
    """Force a dark titlebar on macOS when the Fusion palette looks too light."""
    if sys.platform != "darwin":
        return False
    try:
        from ctypes import cdll, util, c_void_p, c_char_p, c_bool, c_double
    except Exception as e:
        APP_LOGGER.error(f"Failed to import ctypes: {e}")
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
    if ns_name:
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
        _msg(window, _sel(b"setTitlebarAppearsTransparent:"), c_bool(False), restype=None, argtypes=[c_bool])
        if ns_color:
            _msg(window, _sel(b"setBackgroundColor:"), ns_color, restype=None, argtypes=[c_void_p])
    except Exception:
        return False
    return True

HEATMAP_PALETTES = ("inferno", "magma", "cividis", "plasma", "viridis", "turbo")

def apply_matplotlib_theme(font_family: str | None, theme: dict[str, str]):
    """Make Matplotlib match the NEMESIS UI theme."""
    import matplotlib as mpl
    from matplotlib import font_manager
    from app.core.paths import FONT_PATH
    
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
    
    # Defaults from theme or fallback constants
    mid = theme.get("MID", "#e7ecf6")
    face = theme.get("PLOT_FACE", mid)
    text_color = theme.get("TEXT", "#1d2334")
    grid_color = theme.get("GRID", "#cdd5e5")
    
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
