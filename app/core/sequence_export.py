"""Helpers for exporting fixed-step sequences for ML models."""

from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core.logger import APP_LOGGER

FRAME_FIELDS = ["frame_idx", "timestamp"]
TRACKING_FIELDS = ["frame_idx", "timestamp", "stentor_id", "state", "circularity", "x", "y", "area"]


@dataclass
class FrameSample:
    frame_idx: int
    timestamp_s: float


def load_frames(path: Path) -> list[FrameSample]:
    if not path.exists():
        return []
    frames: list[FrameSample] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    frame_idx = int(row["frame_idx"])
                    timestamp = float(row["timestamp"])
                except Exception:
                    continue
                frames.append(FrameSample(frame_idx=frame_idx, timestamp_s=timestamp))
    except Exception as exc:
        APP_LOGGER.error(f"Failed to read frames.csv from {path}: {exc}")
        return []
    return frames


def load_tracking(path: Path) -> dict[int, list[dict]]:
    if not path.exists():
        return {}
    grouped: dict[int, list[dict]] = {}
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                state = (row.get("state") or "").strip()
                stentor_id = (row.get("stentor_id") or "").strip()
                if not stentor_id or state == "NONE":
                    continue
                try:
                    frame_idx = int(row["frame_idx"])
                except Exception:
                    continue
                grouped.setdefault(frame_idx, []).append(row)
    except Exception as exc:
        APP_LOGGER.error(f"Failed to read tracking.csv from {path}: {exc}")
        return {}
    return grouped


def load_taps(path: Path) -> list[float]:
    if not path.exists():
        return []
    taps: list[float] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                raw = row.get("t_host_ms", "")
                if not raw:
                    continue
                try:
                    taps.append(float(raw) / 1000.0)
                except Exception:
                    continue
    except Exception as exc:
        APP_LOGGER.error(f"Failed to read taps.csv from {path}: {exc}")
        return []
    taps.sort()
    return taps


def compute_frame_interval(frames: list[FrameSample]) -> float:
    if len(frames) < 2:
        return 0.0
    diffs = []
    for prev, curr in zip(frames, frames[1:]):
        delta = curr.timestamp_s - prev.timestamp_s
        if delta > 0:
            diffs.append(delta)
    if not diffs:
        return 0.0
    try:
        return statistics.median(diffs)
    except Exception:
        return diffs[0]


def _mean(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def build_sequence(
    frames: list[FrameSample],
    tracking_by_frame: dict[int, list[dict]],
    taps: list[float],
    *,
    run_start_s: Optional[float] = None,
    frame_interval_s: Optional[float] = None,
) -> list[dict]:
    if not frames:
        return []
    interval = frame_interval_s if frame_interval_s is not None else compute_frame_interval(frames)
    half_window = interval / 2 if interval > 0 else 0.0
    tap_idx = 0
    tap_total = len(taps)
    rows: list[dict] = []

    for sample in frames:
        entries = tracking_by_frame.get(sample.frame_idx, [])
        circ_vals: list[float] = []
        area_vals: list[float] = []
        x_vals: list[float] = []
        y_vals: list[float] = []
        n_contracted = 0
        for row in entries:
            state = (row.get("state") or "").strip()
            if state == "CONTRACTED":
                n_contracted += 1
            try:
                circ_vals.append(float(row.get("circularity", "")))
            except Exception:
                pass
            try:
                area_vals.append(float(row.get("area", "")))
            except Exception:
                pass
            try:
                x_vals.append(float(row.get("x", "")))
            except Exception:
                pass
            try:
                y_vals.append(float(row.get("y", "")))
            except Exception:
                pass

        n_visible = len(entries)
        any_contracted = 1 if n_contracted > 0 else 0

        tap_count = 0
        if tap_total:
            if half_window > 0:
                while tap_idx < tap_total and taps[tap_idx] < sample.timestamp_s - half_window:
                    tap_idx += 1
                j = tap_idx
                while j < tap_total and taps[j] <= sample.timestamp_s + half_window:
                    tap_count += 1
                    j += 1
                tap_idx = j
            else:
                # Fallback: assign a tap to the nearest frame only if timestamps match closely.
                if tap_idx < tap_total and abs(taps[tap_idx] - sample.timestamp_s) <= 1e-3:
                    tap_count = 1
                    tap_idx += 1

        row = {
            "frame_idx": sample.frame_idx,
            "timestamp_s": f"{sample.timestamp_s:.3f}",
            "t_rel_s": f"{(sample.timestamp_s - run_start_s):.3f}" if run_start_s is not None else "",
            "n_visible": n_visible,
            "n_contracted": n_contracted,
            "any_contracted": any_contracted,
            "mean_circularity": f"{_mean(circ_vals):.6f}" if n_visible else "",
            "mean_area": f"{_mean(area_vals):.3f}" if n_visible else "",
            "mean_x": f"{_mean(x_vals):.3f}" if n_visible else "",
            "mean_y": f"{_mean(y_vals):.3f}" if n_visible else "",
            "tap_count": tap_count,
        }
        rows.append(row)
    return rows


def resample_sequence(rows: list[dict], step_s: float) -> list[dict]:
    if not rows or step_s <= 0:
        return rows
    times = [float(row["timestamp_s"]) for row in rows]
    start = times[0]
    end = times[-1]
    resampled: list[dict] = []
    idx = 0
    sample_idx = 0
    t = start
    while t <= end:
        while idx + 1 < len(times) and times[idx + 1] <= t:
            idx += 1
        src = dict(rows[idx])
        src["sample_idx"] = sample_idx
        src["timestamp_s"] = f"{t:.3f}"
        src["source_frame_idx"] = src.get("frame_idx", "")
        resampled.append(src)
        sample_idx += 1
        t += step_s
    return resampled


def write_sequence(rows: list[dict], out_path: Path) -> Path:
    if not rows:
        raise ValueError("No rows to write.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return out_path


def export_sequence(
    run_dir: Path,
    *,
    out_path: Optional[Path] = None,
    step_ms: Optional[float] = None,
) -> Path:
    run_dir = Path(run_dir)
    if out_path is None:
        out_path = run_dir / "sequence.csv"
    frames = load_frames(run_dir / "frames.csv")
    tracking_by_frame = load_tracking(run_dir / "tracking.csv")
    taps = load_taps(run_dir / "taps.csv")

    run_start_s = None
    run_meta = run_dir / "run.json"
    if run_meta.exists():
        try:
            with run_meta.open("r", encoding="utf-8") as fh:
                meta = fh.read()
            data = None
            try:
                import json
                data = json.loads(meta)
            except Exception:
                data = None
            if data and data.get("run_start_host_ms") is not None:
                run_start_s = float(data["run_start_host_ms"]) / 1000.0
        except Exception:
            run_start_s = None

    if not frames:
        # Fallback to tracking timestamps if frames.csv is missing.
        fallback = []
        for frame_idx, rows in tracking_by_frame.items():
            ts = None
            for row in rows:
                raw = row.get("timestamp")
                if raw:
                    try:
                        ts = float(raw)
                        break
                    except Exception:
                        continue
            if ts is None:
                continue
            fallback.append(FrameSample(frame_idx=frame_idx, timestamp_s=ts))
        frames = sorted(fallback, key=lambda f: f.frame_idx)

    if not frames:
        raise FileNotFoundError("No frames.csv or tracking timestamps found to build sequence.")

    rows = build_sequence(
        frames,
        tracking_by_frame,
        taps,
        run_start_s=run_start_s,
    )
    if step_ms:
        rows = resample_sequence(rows, step_ms / 1000.0)
    return write_sequence(rows, out_path)
