"""Common interfaces and exceptions for tapper controller drivers."""

class ControllerDriverError(RuntimeError):
    """Raised when a tapper controller encounters an unrecoverable fault."""


class ControllerDriver:
    """Abstract interface for hardware backends.

    Concrete drivers (Arduino, UNIT1, etc.) should inherit from this class and
    implement the basic lifecycle methods used by the Qt application.
    """

    def open(self, *args, **kwargs):  # pragma: no cover - interface placeholder
        raise NotImplementedError

    def close(self):  # pragma: no cover - interface placeholder
        raise NotImplementedError

    def send_char(self, ch: str):  # pragma: no cover - interface placeholder
        raise NotImplementedError
