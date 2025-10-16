# logger.py — CSV logger for taps (v1.0 schema, with recording_path setter)
import csv, time, uuid
from pathlib import Path
from typing import Optional, Union

CSV_FIELDS = [
    "run_id","tap_id","tap_uuid","t_host_ms","mode","stepsize","mark","notes","recording_path"
]

class RunLogger:
    def __init__(self, run_dir: Union[Path,str], run_id: Optional[str] = None, recording_path: Optional[str] = None):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or self._default_run_id()
        self._recording_path = recording_path or ""
        self.tap_id = 0
        self._f = open(self.run_dir / "taps.csv", "a", newline="")
        self._w = csv.DictWriter(self._f, fieldnames=CSV_FIELDS)
        if self._f.tell() == 0:
            self._w.writeheader()

    @property
    def recording_path(self) -> str:
        return self._recording_path

    def set_recording_path(self, path: Optional[str]):
        """Set/overwrite recording_path (e.g., if recording starts mid-run)."""
        self._recording_path = path or ""

    def _default_run_id(self) -> str:
        ts = time.strftime("%Y%m%d_%H%M%S")
        return f"run_{ts}"

    def log_tap(self, host_time_s: float, mode: str, mark: str = "scheduled",
                stepsize: Optional[int] = None, notes: Optional[str] = None):
        """Append a tap row to taps.csv. host_time_s should be from a consistent clock."""
        self.tap_id += 1
        row = {
            "run_id": self.run_id,
            "tap_id": self.tap_id,
            "tap_uuid": str(uuid.uuid4()),
            "t_host_ms": int(round(host_time_s * 1000.0)),
            "mode": mode,
            "stepsize": stepsize if stepsize is not None else "",
            "mark": mark,
            "notes": notes or "",
            "recording_path": self._recording_path,
        }
        self._w.writerow(row)
        self._f.flush()

    def close(self):
        try:
            self._f.close()
        except Exception:
            pass
