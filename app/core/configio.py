# configio.py — simple config save/load for NEMESIS
import json, tempfile
from pathlib import Path
from app.core.logger import APP_LOGGER

DEFAULT_PATH = Path.home() / ".nemesis" / "config.json"

def ensure_dir(p: Path) -> Path:
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    except PermissionError:
        # Fallback to temp dir if home is not writable
        tmp = Path(tempfile.gettempdir()) / ".nemesis" / p.name
        APP_LOGGER.warning(f"Permission denied for {p}, falling back to {tmp}")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        return tmp

def save_config(cfg: dict, path: Path = DEFAULT_PATH):
    target_path = ensure_dir(path)
    try:
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        APP_LOGGER.error(f"Failed to save config to {target_path}: {e}")

def load_config(path: Path = DEFAULT_PATH) -> dict | None:
    # Try loading from primary path, then check if we fell back previously?
    # For now just try the requested path.
    try:
        if not path.exists():
            # Check temp fallback
            tmp = Path(tempfile.gettempdir()) / ".nemesis" / path.name
            if tmp.exists():
                path = tmp
                
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        APP_LOGGER.warning(f"Failed to load config from {path}: {e}")
        return None
