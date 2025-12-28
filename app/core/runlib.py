"""Run library utilities for discovering and loading saved runs."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, List
from app.core.logger import APP_LOGGER

RUN_PREFIX = "run_"
MS_PER_SEC = 1000.0


def iter_run_dirs(base: Path) -> Iterable[Path]:
    for child in sorted(base.glob(f"{RUN_PREFIX}*"), reverse=True):
        if child.is_dir():
            yield child


def load_run_json(run_dir: Path) -> dict:
    metadata_path = run_dir / "run.json"
    if metadata_path.exists():
        try:
            with metadata_path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as e:
            APP_LOGGER.error(f"Failed to load run.json from {run_dir}: {e}")
            return {}
    return {}


@dataclass
class RunSummary:
    run_id: str
    path: Path
    started_at: Optional[str] = None
    app_version: Optional[str] = None
    serial_port: Optional[str] = None
    mode: Optional[str] = None
    period_sec: Optional[float] = None
    lambda_rpm: Optional[float] = None
    stepsize: Optional[int] = None
    recording_path: Optional[str] = None
    taps_count: Optional[int] = None
    duration_s: Optional[float] = None

    @classmethod
    def from_dir(cls, run_dir: Path) -> "RunSummary":
        meta = load_run_json(run_dir)
        run_id = meta.get("run_id", run_dir.name)
        summary = cls(
            run_id=run_id,
            path=run_dir,
            started_at=meta.get("started_at"),
            app_version=meta.get("app_version"),
            serial_port=meta.get("serial_port"),
            mode=meta.get("mode"),
            period_sec=meta.get("period_sec"),
            lambda_rpm=meta.get("lambda_rpm"),
            stepsize=meta.get("stepsize"),
            recording_path=meta.get("recording_path"),
        )
        summary._load_tap_stats()
        return summary

    def _load_tap_stats(self) -> None:
        taps_path = self.path / "taps.csv"
        if not taps_path.exists():
            return
        try:
            with taps_path.open("r", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                rows = list(reader)
        except Exception as e:
            APP_LOGGER.error(f"Failed to read taps.csv from {taps_path}: {e}")
            return
        if not rows:
            return
        self.taps_count = len(rows)
        try:
            first = float(rows[0]["t_host_ms"]) / MS_PER_SEC
            last = float(rows[-1]["t_host_ms"]) / MS_PER_SEC
            self.duration_s = max(0.0, last - first)
        except Exception as e:
            APP_LOGGER.error(f"Failed to calculate run duration for {self.run_id}: {e}")
            self.duration_s = None


class RunLibrary:
    """Simple helper for discovering saved runs."""

    def __init__(self, base: Path):
        self.base = base

    def list_runs(self) -> List[RunSummary]:
        summaries: List[RunSummary] = []
        for run_dir in iter_run_dirs(self.base):
            try:
                summaries.append(RunSummary.from_dir(run_dir))
            except Exception as e:
                APP_LOGGER.error(f"Failed to load run summary from {run_dir}: {e}")
                continue
        return summaries

    def delete_run(self, run_id: str) -> bool:
        for run_dir in iter_run_dirs(self.base):
            if run_dir.name == run_id or run_dir.name.endswith(run_id):
                try:
                    for child in run_dir.glob("**/*"):
                        if child.is_file():
                            child.unlink()
                    for child in sorted(run_dir.glob("**"), reverse=True):
                        if child.is_dir():
                            child.rmdir()
                    run_dir.rmdir()
                    return True
                except Exception as e:
                    APP_LOGGER.error(f"Failed to delete run directory {run_dir}: {e}")
                    return False
        return False
