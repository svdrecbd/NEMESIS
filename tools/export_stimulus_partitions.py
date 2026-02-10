#!/usr/bin/env python3
"""Export per-frame stimulus conditioning masks for a run."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.sequence_export import load_frames, load_taps
from app.core.stimulus_partition import partition_frames_by_taps


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export per-frame baseline/post-tap labels from frames.csv + taps.csv."
    )
    parser.add_argument(
        "--run-dir",
        required=True,
        help="Run directory containing frames.csv and taps.csv.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output CSV path (default: <run-dir>/stimulus_partitions.csv).",
    )
    parser.add_argument(
        "--post-window-s",
        type=float,
        default=2.0,
        help="Duration after each tap treated as post-tap (seconds).",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    out_path = Path(args.out) if args.out else (run_dir / "stimulus_partitions.csv")

    frames = load_frames(run_dir / "frames.csv")
    if not frames:
        raise FileNotFoundError(f"No frames found at {run_dir / 'frames.csv'}")
    taps = load_taps(run_dir / "taps.csv")

    frame_pairs = [(f.frame_idx, f.timestamp_s) for f in frames]
    labels = partition_frames_by_taps(
        frame_pairs,
        taps,
        post_window_s=float(args.post_window_s),
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "frame_idx",
                "timestamp_s",
                "is_post_tap",
                "is_baseline",
                "active_tap_windows",
            ],
        )
        writer.writeheader()
        for row in labels:
            writer.writerow(
                {
                    "frame_idx": row.frame_idx,
                    "timestamp_s": f"{row.timestamp_s:.3f}",
                    "is_post_tap": 1 if row.is_post_tap else 0,
                    "is_baseline": 1 if row.is_baseline else 0,
                    "active_tap_windows": row.active_tap_windows,
                }
            )

    total = len(labels)
    post_n = sum(1 for row in labels if row.is_post_tap)
    baseline_n = total - post_n
    print(
        f"Wrote {out_path} | total={total} post_tap={post_n} baseline={baseline_n} post_window_s={args.post_window_s:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
