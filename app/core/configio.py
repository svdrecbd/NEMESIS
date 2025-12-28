# configio.py — simple config save/load for NEMESIS
import json, os
from pathlib import Path
from app.core.logger import APP_LOGGER

DEFAULT_PATH = Path.home() / ".nemesis" / "config.json"

def ensure_dir(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)

def save_config(cfg: dict, path: Path = DEFAULT_PATH):
    ensure_dir(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

def load_config(path: Path = DEFAULT_PATH) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        APP_LOGGER.warning(f"Failed to load config from {path}: {e}")
        return None
