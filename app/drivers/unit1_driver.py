"""UNIT1 controller stub.

This module establishes the entry point for the future UNIT1 "pure mode"
controller. For now it simply mirrors the Arduino driver interface so the rest
of the application can switch backends without code churn once UNIT1 firmware is
ready.
"""

from __future__ import annotations

from .controller_driver import ControllerDriver


class Unit1Driver(ControllerDriver):
    """Placeholder implementation. Real protocol support will land with UNIT1."""

    def __init__(self):
        super().__init__()
        self._opened = False

    def open(self, *args, **kwargs):
        self._opened = True

    def close(self):
        self._opened = False

    def send_char(self, ch: str):
        if not self._opened:
            return
        # TODO: translate high-level request into UNIT1 protocol frame.
        _ = ch  # placeholder to avoid unused-variable warnings
