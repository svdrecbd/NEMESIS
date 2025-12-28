# app/core/paths.py
import sys
from pathlib import Path

def get_resource_path(relative_path: str) -> Path:
    """Get absolute path to resource, works for dev and for PyInstaller."""
    try:
        # PyInstaller creates a temporary folder and stores path in _MEIPASS
        base_path = Path(sys._MEIPASS)
    except AttributeError:
        # Fallback to dev mode: main.py is in app/, so two levels up is project root
        base_path = Path(__file__).resolve().parent.parent.parent
    return base_path / relative_path

# Assets & Version
BASE_DIR = get_resource_path(".")
RUNS_DIR = (BASE_DIR / "runs").resolve()
RUNS_DIR.mkdir(parents=True, exist_ok=True)

ASSETS_DIR = get_resource_path("assets")
FONT_PATH = get_resource_path("assets/fonts/Typestar OCR Regular.otf")
LOGO_PATH = get_resource_path("assets/images/transparent_logo.png")
