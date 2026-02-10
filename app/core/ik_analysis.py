"""Leighton-style non-Markovian analysis utilities for NEMESIS run artifacts."""

from __future__ import annotations

import csv
import json
import math
import random
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from app.core.logger import APP_LOGGER
from app.core.sequence_export import FrameSample, load_frames, load_taps
from app.core.stimulus_partition import partition_frames_by_taps


CONDITION_ALL = "all_time"
CONDITION_BASELINE = "baseline"
CONDITION_POST_TAP = "post_tap"
VALID_CONDITIONS = (CONDITION_ALL, CONDITION_BASELINE, CONDITION_POST_TAP)

STATE_CONTRACTED = "CONTRACTED"
STATE_EXTENDED = "EXTENDED"
STATE_NONE = "NONE"
STATE_UNDETERMINED = "UNDETERMINED"

DEFAULT_K_MAX = 10
DEFAULT_POST_WINDOW_S = 2.0
DEFAULT_M_FACTORS = (1, 2, 4, 8, 16, 32, 64, 128)
DEFAULT_SEEDS = tuple(range(20))
DEFAULT_NULL_SHUFFLES = 20
DEFAULT_MIN_CONDITION_DURATION_S = 30.0 * 60.0
DEFAULT_MIN_NONMISSING_FRACTION = 0.70
DEFAULT_SUMMARY_K_REQUIRED = 3


def _median_frame_dt(frames: Sequence[FrameSample]) -> float:
    if len(frames) < 2:
        return 0.0
    deltas: list[float] = []
    for prev, curr in zip(frames, frames[1:]):
        dt = curr.timestamp_s - prev.timestamp_s
        if dt > 0:
            deltas.append(dt)
    if not deltas:
        return 0.0
    try:
        return float(statistics.median(deltas))
    except Exception:
        return float(deltas[0])


def _state_to_binary(state: str, edge_reflection: bool) -> Optional[int]:
    if edge_reflection:
        return None
    text = (state or "").strip().upper()
    if text == STATE_CONTRACTED:
        return 1
    if text == STATE_EXTENDED:
        return 0
    if text in {STATE_UNDETERMINED, STATE_NONE, ""}:
        return None
    return None


def _safe_div(num: float, den: float) -> float:
    if den <= 0:
        return 0.0
    return num / den


def _entropy_binary(p1: float) -> float:
    p1 = max(0.0, min(1.0, p1))
    p0 = 1.0 - p1
    out = 0.0
    if p0 > 0:
        out -= p0 * math.log2(p0)
    if p1 > 0:
        out -= p1 * math.log2(p1)
    return out


def _window_valid(mask: Sequence[bool], t: int, k: int) -> bool:
    # Require target + all history points to belong to the condition mask.
    for idx in range(t - k, t + 1):
        if idx < 0 or not mask[idx]:
            return False
    return True


def compute_hk(
    values: Sequence[Optional[int]],
    condition_mask: Sequence[bool],
    k: int,
) -> tuple[Optional[float], int]:
    """
    Estimate H[X_t | X_{t-1},...,X_{t-k}] in bits.

    Missing values are represented by None and excluded via complete-case windows.
    """
    if k < 0:
        raise ValueError("k must be >= 0")
    n = len(values)
    if n == 0 or len(condition_mask) != n:
        return None, 0

    if k == 0:
        n_total = 0
        n_one = 0
        for i, val in enumerate(values):
            if not condition_mask[i] or val is None:
                continue
            n_total += 1
            n_one += int(val)
        if n_total == 0:
            return None, 0
        return _entropy_binary(n_one / n_total), n_total

    # Count p(history, target)
    hist_counts: Dict[tuple[int, ...], list[int]] = {}
    n_eff = 0
    for t in range(k, n):
        if not _window_valid(condition_mask, t, k):
            continue
        window = values[t - k : t + 1]
        if any(v is None for v in window):
            continue
        history = tuple(int(v) for v in window[:-1])
        target = int(window[-1])
        bucket = hist_counts.get(history)
        if bucket is None:
            bucket = [0, 0]
            hist_counts[history] = bucket
        bucket[target] += 1
        n_eff += 1

    if n_eff == 0:
        return None, 0

    h = 0.0
    for counts in hist_counts.values():
        c0, c1 = counts
        c = c0 + c1
        if c <= 0:
            continue
        h += (c / n_eff) * _entropy_binary(c1 / c)
    return h, n_eff


def compute_ik_profile(
    values: Sequence[Optional[int]],
    condition_mask: Sequence[bool],
    *,
    k_max: int,
) -> tuple[list[Optional[float]], list[int], list[Optional[float]]]:
    """
    Return hk, n_eff_k, i_k (index 0 is always None for i_k).
    """
    hk: list[Optional[float]] = []
    n_eff_k: list[int] = []
    for k in range(0, max(0, int(k_max)) + 1):
        h_k, n_k = compute_hk(values, condition_mask, k)
        hk.append(h_k)
        n_eff_k.append(n_k)

    ik: list[Optional[float]] = [None]
    for k in range(1, len(hk)):
        h_prev = hk[k - 1]
        h_now = hk[k]
        if h_prev is None or h_now is None:
            ik.append(None)
        else:
            ik.append(max(0.0, h_prev - h_now))
    return hk, n_eff_k, ik


def coarse_grain_random_pick(
    values: Sequence[Optional[int]],
    masks: Dict[str, Sequence[bool]],
    *,
    factor: int,
    rng: random.Random,
) -> tuple[list[Optional[int]], Dict[str, list[bool]]]:
    """
    Coarse-grain by selecting one random index in each bin of `factor` points.
    """
    if factor <= 1:
        return list(values), {k: list(v) for k, v in masks.items()}
    n = len(values)
    out_values: list[Optional[int]] = []
    out_masks: Dict[str, list[bool]] = {k: [] for k in masks}
    for start in range(0, n, factor):
        end = min(n, start + factor)
        pick = rng.randrange(start, end)
        out_values.append(values[pick])
        for name, arr in masks.items():
            out_masks[name].append(bool(arr[pick]))
    return out_values, out_masks


def shuffled_null_distribution(
    values: Sequence[Optional[int]],
    condition_mask: Sequence[bool],
    *,
    k_max: int,
    rng: random.Random,
    n_shuffles: int,
) -> Dict[int, list[float]]:
    """
    Build null distribution for I_k by shuffling observed values within condition.
    Missing pattern and condition mask are preserved.
    """
    valid_positions = [
        i for i, (v, ok) in enumerate(zip(values, condition_mask)) if ok and v is not None
    ]
    observed = [int(values[i]) for i in valid_positions]
    dist: Dict[int, list[float]] = {k: [] for k in range(1, k_max + 1)}
    if not valid_positions or n_shuffles <= 0:
        return dist

    for _ in range(int(n_shuffles)):
        shuffled = list(observed)
        rng.shuffle(shuffled)
        test = list(values)
        for idx, v in zip(valid_positions, shuffled):
            test[idx] = v
        _, _, ik = compute_ik_profile(test, condition_mask, k_max=k_max)
        for k in range(1, k_max + 1):
            if ik[k] is not None:
                dist[k].append(float(ik[k]))
    return dist


def min_windows_threshold(k: int) -> int:
    return int(max(5000, 20 * (2 ** (k + 1))))


@dataclass
class CellSeries:
    stentor_id: str
    values: list[Optional[int]]


@dataclass
class IKConfig:
    k_max: int = DEFAULT_K_MAX
    post_window_s: float = DEFAULT_POST_WINDOW_S
    m_factors: tuple[int, ...] = DEFAULT_M_FACTORS
    seeds: tuple[int, ...] = DEFAULT_SEEDS
    null_shuffles: int = DEFAULT_NULL_SHUFFLES
    min_condition_duration_s: float = DEFAULT_MIN_CONDITION_DURATION_S
    min_nonmissing_fraction: float = DEFAULT_MIN_NONMISSING_FRACTION
    summary_k_required: int = DEFAULT_SUMMARY_K_REQUIRED


@dataclass
class IKOutputs:
    by_k_path: Path
    qc_path: Path
    summary_path: Path


def _read_tracking_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append(row)
    return rows


def _build_cell_series(
    frames: Sequence[FrameSample],
    tracking_rows: Sequence[dict],
) -> dict[str, CellSeries]:
    frame_indices = [int(f.frame_idx) for f in frames]
    frame_pos = {idx: i for i, idx in enumerate(frame_indices)}

    by_id: dict[str, CellSeries] = {}
    for row in tracking_rows:
        sid = (row.get("stentor_id") or "").strip()
        if not sid:
            continue
        state = (row.get("state") or "").strip()
        if state.upper() == STATE_NONE:
            continue
        raw_frame_idx = row.get("frame_idx", "")
        try:
            frame_idx = int(raw_frame_idx)
        except Exception:
            continue
        pos = frame_pos.get(frame_idx)
        if pos is None:
            continue
        edge_flag = str(row.get("edge_reflection", "0")).strip() == "1"
        val = _state_to_binary(state, edge_flag)
        series = by_id.get(sid)
        if series is None:
            series = CellSeries(stentor_id=sid, values=[None] * len(frames))
            by_id[sid] = series
        series.values[pos] = val
    return by_id


def _base_inclusion(
    values: Sequence[Optional[int]],
    mask: Sequence[bool],
    *,
    dt_s: float,
    min_duration_s: float,
    min_nonmissing_fraction: float,
) -> tuple[bool, float, float]:
    n_cond = sum(1 for ok in mask if ok)
    if n_cond <= 0:
        return False, 0.0, 0.0
    n_obs = sum(1 for v, ok in zip(values, mask) if ok and v is not None)
    duration_s = n_cond * max(0.0, dt_s)
    nonmissing_frac = _safe_div(float(n_obs), float(n_cond))
    ok = duration_s >= min_duration_s and nonmissing_frac >= min_nonmissing_fraction
    return ok, duration_s, nonmissing_frac


def analyze_ik(run_dir: Path, *, config: IKConfig, out_dir: Optional[Path] = None) -> IKOutputs:
    run_dir = Path(run_dir)
    out = out_dir or run_dir
    out.mkdir(parents=True, exist_ok=True)

    frames = load_frames(run_dir / "frames.csv")
    if not frames:
        raise FileNotFoundError(f"frames.csv missing or empty in {run_dir}")
    taps = load_taps(run_dir / "taps.csv")
    tracking_rows = _read_tracking_rows(run_dir / "tracking.csv")
    if not tracking_rows:
        APP_LOGGER.warning(f"tracking.csv missing/empty for {run_dir}")

    dt_s = _median_frame_dt(frames)
    frame_pairs = [(f.frame_idx, f.timestamp_s) for f in frames]
    cond_labels = partition_frames_by_taps(
        frame_pairs,
        taps,
        post_window_s=float(config.post_window_s),
    )
    masks_raw: Dict[str, list[bool]] = {
        CONDITION_ALL: [True for _ in cond_labels],
        CONDITION_BASELINE: [row.is_baseline for row in cond_labels],
        CONDITION_POST_TAP: [row.is_post_tap for row in cond_labels],
    }
    cell_series = _build_cell_series(frames, tracking_rows)

    by_k_rows: list[dict] = []
    qc_rows: list[dict] = []
    for cell_id in sorted(cell_series):
        series = cell_series[cell_id]
        for condition in VALID_CONDITIONS:
            base_ok, duration_s, nonmissing_frac = _base_inclusion(
                series.values,
                masks_raw[condition],
                dt_s=dt_s,
                min_duration_s=float(config.min_condition_duration_s),
                min_nonmissing_fraction=float(config.min_nonmissing_fraction),
            )
            qc_rows.append(
                {
                    "stentor_id": cell_id,
                    "condition": condition,
                    "base_included": 1 if base_ok else 0,
                    "duration_s": f"{duration_s:.3f}",
                    "nonmissing_fraction": f"{nonmissing_frac:.6f}",
                }
            )
            if not base_ok:
                continue

            for m in config.m_factors:
                m_factor = max(1, int(m))
                for seed in config.seeds:
                    rng = random.Random(int(seed))
                    values_cg, masks_cg = coarse_grain_random_pick(
                        series.values,
                        masks_raw,
                        factor=m_factor,
                        rng=rng,
                    )
                    mask = masks_cg[condition]
                    hk, n_eff_k, ik = compute_ik_profile(
                        values_cg,
                        mask,
                        k_max=int(config.k_max),
                    )
                    null_dist = shuffled_null_distribution(
                        values_cg,
                        mask,
                        k_max=int(config.k_max),
                        rng=random.Random((int(seed) * 1_000_003) + m_factor),
                        n_shuffles=int(config.null_shuffles),
                    )

                    for k in range(1, int(config.k_max) + 1):
                        raw = ik[k] if k < len(ik) else None
                        h_k = hk[k] if k < len(hk) else None
                        n_eff = n_eff_k[k] if k < len(n_eff_k) else 0
                        null_vals = null_dist.get(k, [])
                        null_mean = float(statistics.fmean(null_vals)) if null_vals else 0.0
                        null_p95 = float(sorted(null_vals)[int(0.95 * (len(null_vals) - 1))]) if null_vals else 0.0
                        corrected = (float(raw) - null_mean) if raw is not None else None
                        reliable = (
                            raw is not None
                            and n_eff >= min_windows_threshold(k)
                            and float(raw) > null_p95
                        )
                        by_k_rows.append(
                            {
                                "run_id": run_dir.name,
                                "stentor_id": cell_id,
                                "condition": condition,
                                "m_factor": m_factor,
                                "seed": int(seed),
                                "k": k,
                                "h_k": "" if h_k is None else f"{float(h_k):.9f}",
                                "i_k_raw": "" if raw is None else f"{float(raw):.9f}",
                                "i_k_null_mean": f"{null_mean:.9f}",
                                "i_k_null_p95": f"{null_p95:.9f}",
                                "i_k_corrected": "" if corrected is None else f"{float(corrected):.9f}",
                                "n_eff": int(n_eff),
                                "n_eff_threshold": int(min_windows_threshold(k)),
                                "reliable": 1 if reliable else 0,
                                "base_included": 1,
                                "summary_k_required": int(config.summary_k_required),
                            }
                        )

    # Determine summary-eligible cells per condition + M:
    # require reliable k=1..summary_k_required across all seeds.
    reliability_map: dict[tuple[str, str, int, int], bool] = {}
    for row in by_k_rows:
        key = (
            row["stentor_id"],
            row["condition"],
            int(row["m_factor"]),
            int(row["k"]),
        )
        if key not in reliability_map:
            reliability_map[key] = True
        reliability_map[key] = reliability_map[key] and bool(int(row["reliable"]))

    summary_eligible: dict[tuple[str, str, int], bool] = {}
    for row in qc_rows:
        if int(row["base_included"]) != 1:
            continue
        cell_id = row["stentor_id"]
        condition = row["condition"]
        for m in config.m_factors:
            m_factor = int(m)
            ok = True
            for k in range(1, min(int(config.summary_k_required), int(config.k_max)) + 1):
                if not reliability_map.get((cell_id, condition, m_factor, k), False):
                    ok = False
                    break
            summary_eligible[(cell_id, condition, m_factor)] = ok

    for row in by_k_rows:
        key = (
            row["stentor_id"],
            row["condition"],
            int(row["m_factor"]),
        )
        row["summary_included"] = 1 if summary_eligible.get(key, False) else 0

    # Aggregate summary by condition/M/k over summary_included rows.
    grouped: dict[tuple[str, int, int], list[dict]] = {}
    for row in by_k_rows:
        if int(row.get("summary_included", 0)) != 1:
            continue
        key = (
            row["condition"],
            int(row["m_factor"]),
            int(row["k"]),
        )
        grouped.setdefault(key, []).append(row)

    summary_blocks: list[dict] = []
    for (condition, m_factor, k), rows in sorted(grouped.items()):
        corrected = [float(r["i_k_corrected"]) for r in rows if r["i_k_corrected"] != ""]
        raw = [float(r["i_k_raw"]) for r in rows if r["i_k_raw"] != ""]
        n_eff = [int(r["n_eff"]) for r in rows]
        summary_blocks.append(
            {
                "condition": condition,
                "m_factor": m_factor,
                "k": k,
                "rows": len(rows),
                "cells": len({r["stentor_id"] for r in rows}),
                "i_k_corrected_mean": statistics.fmean(corrected) if corrected else None,
                "i_k_raw_mean": statistics.fmean(raw) if raw else None,
                "n_eff_total": int(sum(n_eff)),
                "n_eff_median": int(statistics.median(n_eff)) if n_eff else 0,
            }
        )

    by_k_path = out / "ik_by_k.csv"
    qc_path = out / "ik_qc.csv"
    summary_path = out / "ik_analysis.json"

    by_k_fields = [
        "run_id",
        "stentor_id",
        "condition",
        "m_factor",
        "seed",
        "k",
        "h_k",
        "i_k_raw",
        "i_k_null_mean",
        "i_k_null_p95",
        "i_k_corrected",
        "n_eff",
        "n_eff_threshold",
        "reliable",
        "base_included",
        "summary_included",
        "summary_k_required",
    ]
    with by_k_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=by_k_fields)
        writer.writeheader()
        writer.writerows(by_k_rows)

    qc_fields = ["stentor_id", "condition", "base_included", "duration_s", "nonmissing_fraction"]
    with qc_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=qc_fields)
        writer.writeheader()
        writer.writerows(qc_rows)

    summary = {
        "run_id": run_dir.name,
        "config": {
            "k_max": int(config.k_max),
            "post_window_s": float(config.post_window_s),
            "m_factors": [int(m) for m in config.m_factors],
            "seeds": [int(s) for s in config.seeds],
            "null_shuffles": int(config.null_shuffles),
            "min_condition_duration_s": float(config.min_condition_duration_s),
            "min_nonmissing_fraction": float(config.min_nonmissing_fraction),
            "summary_k_required": int(config.summary_k_required),
        },
        "inputs": {
            "frames": len(frames),
            "taps": len(taps),
            "tracked_rows": len(tracking_rows),
            "cells_seen": len(cell_series),
            "frame_dt_s_median": dt_s,
        },
        "outputs": {
            "ik_by_k_csv": str(by_k_path),
            "ik_qc_csv": str(qc_path),
            "summary_rows": len(summary_blocks),
        },
        "summary": summary_blocks,
    }
    with summary_path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)

    return IKOutputs(by_k_path=by_k_path, qc_path=qc_path, summary_path=summary_path)

