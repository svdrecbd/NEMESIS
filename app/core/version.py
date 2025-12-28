"""Application version loader shared across UI and runtime."""

from __future__ import annotations

from app.core.logger import APP_LOGGER
from app.core.paths import get_resource_path

DEFAULT_APP_VERSION = "0.0.0"


def get_app_version(default: str = DEFAULT_APP_VERSION) -> str:
    """Resolve the version string from the VERSION file, with a safe fallback."""
    try:
        version_path = get_resource_path("VERSION")
        with version_path.open("r", encoding="utf-8") as fh:
            version = fh.read().strip()
        return version or default
    except Exception as exc:
        APP_LOGGER.warning(f"Failed to load VERSION file: {exc}")
        return default


APP_VERSION = get_app_version()
