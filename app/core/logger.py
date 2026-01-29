# logger.py — CSV logger for taps (v1.0 schema, with recording_path setter)
import csv, time, uuid, logging, errno
from pathlib import Path
from typing import Optional, Union

MS_PER_SEC = 1000.0
FIRMWARE_MS_PRECISION = 3
TRACKING_TS_PRECISION = 3
CIRCULARITY_PRECISION = 3
CENTROID_PRECISION = 1
FRAME_TS_PRECISION = 3
# Flush policy (tracking logger uses size + time thresholds to limit I/O)
# ~1 minute at 15fps * 50 organisms ~= 45,000 rows
TRACKING_FLUSH_ROWS = 45000
TRACKING_FLUSH_SEC = 30.0

def _is_no_space_error(exc: Exception) -> bool:
    return isinstance(exc, OSError) and getattr(exc, "errno", None) == errno.ENOSPC
# --- App-wide logger ---
# Use a named logger for general application events and errors.
# Defaults to console, but can be configured to log to file.
APP_LOGGER = logging.getLogger("nemesis_app")
APP_LOGGER.setLevel(logging.INFO)
_formatter = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S")
_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_formatter)
APP_LOGGER.addHandler(_console_handler)

def configure_file_logging(log_path: Path, level=logging.DEBUG):
    """Configures file logging for APP_LOGGER."""
    # Remove existing file handlers first to prevent duplicates
    for handler in list(APP_LOGGER.handlers):
        if isinstance(handler, logging.FileHandler):
            APP_LOGGER.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
    
    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setFormatter(_formatter)
    file_handler.setLevel(level)
    APP_LOGGER.addHandler(file_handler)
    APP_LOGGER.info(f"File logging enabled at: {log_path}")

# --- Run-specific CSV logger ---
CSV_FIELDS = [
    "run_id",
    "tap_id",
    "tap_uuid",
    "t_host_ms",
    "t_host_iso",
    "t_fw_ms",
    "mode",
    "stepsize",
    "mark",
    "notes",
    "frame_preview_idx",
    "frame_recorded_idx",
    "recording_path",
]

class RunLogger:
    def __init__(self, run_dir: Union[Path,str], run_id: Optional[str] = None, recording_path: Optional[str] = None):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or self._default_run_id()
        self._recording_path = recording_path or ""
        self.tap_id = 0
        self._buffer = []
        self._f = None
        self._w = None
        self._flush_error: Exception | None = None
        self._flush_error_no_space = False
        self._init_file()

    def _init_file(self):
        try:
            self._f = open(self.run_dir / "taps.csv", "a", newline="", encoding="utf-8")
            self._w = csv.DictWriter(self._f, fieldnames=CSV_FIELDS)
            if self._f.tell() == 0:
                self._w.writeheader()
        except Exception as e:
            APP_LOGGER.error(f"Failed to open taps.csv for writing: {e}")
            self._f = None
            self._w = None
            self._flush_error = e
            self._flush_error_no_space = _is_no_space_error(e)

    def consume_flush_error(self) -> tuple[Exception | None, bool]:
        err = self._flush_error
        no_space = self._flush_error_no_space
        self._flush_error = None
        self._flush_error_no_space = False
        return err, no_space

    def has_unsaved_data(self) -> bool:
        return len(self._buffer) > 0

    def retry_flush(self) -> bool:
        """Attempts to write the memory buffer to disk. Returns True if successful."""
        if not self._buffer:
            return True
        if self._w is None:
            self._init_file()
        if self._w is None:
            return False
            
        try:
            self._w.writerows(self._buffer)
            self._f.flush()
            self._buffer.clear()
            return True
        except Exception as e:
            APP_LOGGER.error(f"Retry flush failed: {e}")
            self._flush_error = e
            self._flush_error_no_space = _is_no_space_error(e)
            return False

    @property
    def recording_path(self) -> str:
        return self._recording_path

    def set_recording_path(self, path: Optional[str]):
        """Set/overwrite recording_path (e.g., if recording starts mid-run)."""
        self._recording_path = path or ""

    def _default_run_id(self) -> str:
        ts = time.strftime("%Y%m%d_%H%M%S")
        return f"run_{ts}"

    def log_tap(
        self,
        host_time_s: float,
        mode: str,
        mark: str = "scheduled",
        stepsize: Optional[int] = None,
        notes: Optional[str] = None,
        host_iso: Optional[str] = None,
        firmware_ms: Optional[float] = None,
        preview_frame_idx: Optional[int] = None,
        recorded_frame_idx: Optional[int] = None,
    ):
        """Append a tap row to memory and attempt to flush to taps.csv."""
        self.tap_id += 1
        row = {
            "run_id": self.run_id,
            "tap_id": self.tap_id,
            "tap_uuid": str(uuid.uuid4()),
            "t_host_ms": int(round(host_time_s * MS_PER_SEC)),
            "t_host_iso": host_iso or "",
            "t_fw_ms": f"{firmware_ms:.{FIRMWARE_MS_PRECISION}f}" if firmware_ms is not None else "",
            "mode": mode,
            "stepsize": stepsize if stepsize is not None else "",
            "mark": mark,
            "notes": notes or "",
            "frame_preview_idx": "" if preview_frame_idx is None else int(preview_frame_idx),
            "frame_recorded_idx": "" if recorded_frame_idx is None else int(recorded_frame_idx),
            "recording_path": self._recording_path,
        }
        self._buffer.append(row)
        self.retry_flush()

    def close(self):
        self.retry_flush()
        try:
            if self._f and not self._f.closed:
                self._f.close()
        except Exception as e:
            APP_LOGGER.error(f"Failed to close taps.csv: {e}")


TRACKING_FIELDS = ["frame_idx", "timestamp", "stentor_id", "state", "circularity", "x", "y", "area", "edge_reflection"]
FRAME_FIELDS = ["frame_idx", "timestamp"]

class TrackingLogger:
    def __init__(self, run_dir: Union[Path,str]):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._buffer = []
        self._f = None
        self._w = None
        self._flush_error: Exception | None = None
        self._flush_error_no_space = False
        self._last_flush_attempt_ts = time.monotonic()
        self._init_file()

    def _init_file(self):
        try:
            self._f = open(self.run_dir / "tracking.csv", "a", newline="", encoding="utf-8")
            self._w = csv.DictWriter(self._f, fieldnames=TRACKING_FIELDS)
            if self._f.tell() == 0:
                self._w.writeheader()
        except Exception as e:
            APP_LOGGER.error(f"Failed to open tracking.csv: {e}")
            self._flush_error = e
            self._flush_error_no_space = _is_no_space_error(e)

    def consume_flush_error(self) -> tuple[Exception | None, bool]:
        err = self._flush_error
        no_space = self._flush_error_no_space
        self._flush_error = None
        self._flush_error_no_space = False
        return err, no_space

    def has_unsaved_data(self) -> bool:
        return len(self._buffer) > 0

    def maybe_flush(self) -> None:
        now = time.monotonic()
        if len(self._buffer) >= TRACKING_FLUSH_ROWS or (now - self._last_flush_attempt_ts) >= TRACKING_FLUSH_SEC:
            self.retry_flush()

    def retry_flush(self) -> bool:
        if not self._buffer:
            return True
        if self._w is None:
            self._init_file()
        if self._w is None:
            return False
        try:
            self._last_flush_attempt_ts = time.monotonic()
            self._w.writerows(self._buffer)
            self._f.flush()
            self._buffer.clear()
            return True
        except Exception as e:
            APP_LOGGER.error(f"Tracking retry flush failed: {e}")
            self._flush_error = e
            self._flush_error_no_space = _is_no_space_error(e)
            return False

    def log_frame(self, frame_idx: int, timestamp: float, states: list):
        """
        Add frames to memory buffer and attempt disk flush.
        """
        rows = []
        if states:
            for s in states:
                rows.append({
                    "frame_idx": frame_idx,
                    "timestamp": f"{timestamp:.{TRACKING_TS_PRECISION}f}",
                    "stentor_id": s.id,
                    "state": s.state,
                    "circularity": f"{s.circularity:.{CIRCULARITY_PRECISION}f}",
                    "x": f"{s.centroid[0]:.{CENTROID_PRECISION}f}",
                    "y": f"{s.centroid[1]:.{CENTROID_PRECISION}f}",
                    "area": int(s.area),
                    "edge_reflection": "1" if getattr(s, "edge_reflection", False) else "0",
                })
        else:
            rows.append({
                "frame_idx": frame_idx,
                "timestamp": f"{timestamp:.{TRACKING_TS_PRECISION}f}",
                "stentor_id": "",
                "state": "NONE",
                "circularity": "",
                "x": "",
                "y": "",
                "area": "",
                "edge_reflection": "0",
            })
        
        self._buffer.extend(rows)
        # Flush periodically to reduce I/O overhead
        self.maybe_flush()

    def close(self):
        self.retry_flush()
        try:
            if self._f:
                self._f.close()
        except Exception as e:
            APP_LOGGER.error(f"Failed to close tracking.csv: {e}")


class FrameLogger:
    def __init__(self, run_dir: Union[Path,str]):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._f = None
        self._w = None
        try:
            self._f = open(self.run_dir / "frames.csv", "a", newline="", encoding="utf-8")
            self._w = csv.DictWriter(self._f, fieldnames=FRAME_FIELDS)
            if self._f.tell() == 0:
                self._w.writeheader()
        except Exception as e:
            APP_LOGGER.error(f"Failed to open frames.csv: {e}")

    def log_frame(self, frame_idx: int, timestamp: float) -> None:
        if self._w is None:
            return
        row = {
            "frame_idx": frame_idx,
            "timestamp": f"{timestamp:.{FRAME_TS_PRECISION}f}",
        }
        try:
            self._w.writerow(row)
        except Exception as e:
            APP_LOGGER.error(f"Failed to write frames row: {e}")

    def close(self):
        try:
            if self._f:
                self._f.flush()
                self._f.close()
        except Exception as e:
            APP_LOGGER.error(f"Failed to close frames.csv: {e}")
