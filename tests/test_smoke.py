"""Basic smoke test to ensure the package imports cleanly."""

from pathlib import Path
import sys
import pytest


def test_import_main():
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    pytest.importorskip("PySide6")
    import app.main as app_main
    assert app_main is not None
