#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.ik_analysis import IKConfig, analyze_ik


def _parse_int_csv(text: str) -> tuple[int, ...]:
    out: list[int] = []
    for token in (text or "").split(","):
        token = token.strip()
        if not token:
            continue
        out.append(int(token))
    if not out:
        raise ValueError("Expected at least one integer value.")
    return tuple(out)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Leighton-style I_k analysis on NEMESIS run artifacts.",
    )
    parser.add_argument("--run-dir", required=True, help="Run directory containing frames.csv/tracking.csv/taps.csv")
    parser.add_argument("--out-dir", default=None, help="Output directory (default: run-dir)")
    parser.add_argument("--k-max", type=int, default=10, help="Maximum lag order k")
    parser.add_argument(
        "--m-factors",
        default="1,2,4,8,16,32,64,128",
        help="Comma-separated temporal coarse-grain factors",
    )
    parser.add_argument(
        "--seeds",
        default="0,1,2,3,4,5,6,7,8,9",
        help="Comma-separated random seeds for coarse-grain resampling",
    )
    parser.add_argument("--null-shuffles", type=int, default=20, help="Shuffles per (cell,condition,M,seed)")
    parser.add_argument("--post-window-s", type=float, default=2.0, help="Post-tap window duration in seconds")
    parser.add_argument("--min-condition-duration-s", type=float, default=1800.0, help="Per-cell minimum condition duration")
    parser.add_argument("--min-nonmissing-fraction", type=float, default=0.70, help="Per-cell minimum observed fraction")
    parser.add_argument("--summary-k-required", type=int, default=3, help="Require reliable k=1..K for summary inclusion")
    args = parser.parse_args()

    config = IKConfig(
        k_max=max(1, int(args.k_max)),
        post_window_s=max(0.0, float(args.post_window_s)),
        m_factors=_parse_int_csv(args.m_factors),
        seeds=_parse_int_csv(args.seeds),
        null_shuffles=max(0, int(args.null_shuffles)),
        min_condition_duration_s=max(0.0, float(args.min_condition_duration_s)),
        min_nonmissing_fraction=max(0.0, min(1.0, float(args.min_nonmissing_fraction))),
        summary_k_required=max(1, int(args.summary_k_required)),
    )

    run_dir = Path(args.run_dir)
    out_dir = Path(args.out_dir) if args.out_dir else None
    outputs = analyze_ik(run_dir, config=config, out_dir=out_dir)
    print(f"Wrote {outputs.by_k_path}")
    print(f"Wrote {outputs.qc_path}")
    print(f"Wrote {outputs.summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
