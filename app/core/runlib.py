"""Run library utilities for discovering and loading saved runs."""
from __future__ import annotations

import csv
import json
import shutil
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

    def __init__(self, base: Path | str | Iterable[Path | str]):
        if isinstance(base, (str, Path)):
            bases = [Path(base)]
        else:
            bases = [Path(p) for p in base]
        deduped: list[Path] = []
        seen: set[str] = set()
        for candidate in bases:
            try:
                key = str(candidate.resolve())
            except Exception:
                key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
        self.bases = deduped

    def list_runs(self) -> List[RunSummary]:
        summaries_by_path: dict[str, RunSummary] = {}
        for base in self.bases:
            for run_dir in iter_run_dirs(base):
                try:
                    key = str(run_dir.resolve())
                except Exception:
                    key = str(run_dir)
                if key in summaries_by_path:
                    continue
                try:
                    summaries_by_path[key] = RunSummary.from_dir(run_dir)
                except Exception as e:
                    APP_LOGGER.error(f"Failed to load run summary from {run_dir}: {e}")
                    continue
        summaries = list(summaries_by_path.values())
        summaries.sort(key=lambda s: s.path.name, reverse=True)
        return summaries

    @staticmethod
    def _resolve_recording_path(raw_path: str, run_dir: Path) -> Optional[Path]:
        text = str(raw_path or "").strip()
        if not text:
            return None
        try:
            candidate = Path(text).expanduser()
            if not candidate.is_absolute():
                candidate = (run_dir / candidate)
            return candidate.resolve()
        except Exception:
            try:
                return Path(text).expanduser()
            except Exception:
                return None

    @staticmethod
    def _is_within(parent: Path, child: Path) -> bool:
        try:
            child.resolve().relative_to(parent.resolve())
            return True
        except Exception:
            return False

    @staticmethod
    def _delete_recording_artifact(recording_path: Path, run_dir: Path) -> None:
        if not recording_path.exists():
            return

        # If recording lives in run_dir, deleting run_dir is sufficient.
        if RunLibrary._is_within(run_dir, recording_path):
            return

        parent = recording_path.parent
        if recording_path.is_file():
            recording_path.unlink()
        elif recording_path.is_dir():
            shutil.rmtree(recording_path)
            parent = recording_path.parent

        # Clean up legacy recording_<timestamp> folder if it is now empty.
        if (
            parent.exists()
            and parent.is_dir()
            and parent != run_dir
            and parent.name.startswith("recording_")
        ):
            try:
                parent.rmdir()
            except OSError:
                pass

    def delete_run(self, run_id: str, *, run_path: Optional[Path] = None) -> bool:
        for summary in self.list_runs():
            run_dir = summary.path
            if run_path is not None:
                try:
                    if run_dir.resolve() != Path(run_path).resolve():
                        continue
                except Exception:
                    if run_dir != Path(run_path):
                        continue
            elif not (run_dir.name == run_id or run_dir.name.endswith(run_id) or summary.run_id == run_id):
                continue
            try:
                rec_path = self._resolve_recording_path(summary.recording_path or "", run_dir)
                if rec_path is not None:
                    self._delete_recording_artifact(rec_path, run_dir)
                shutil.rmtree(run_dir)
                return True
            except Exception as e:
                APP_LOGGER.error(f"Failed to delete run directory {run_dir}: {e}")
                return False
        return False
