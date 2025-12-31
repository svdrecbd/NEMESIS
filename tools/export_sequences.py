#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from app.core.sequence_export import export_sequence


def main() -> int:
    parser = argparse.ArgumentParser(description="Export fixed-step ML sequences from a run directory.")
    parser.add_argument("--run-dir", required=True, help="Run directory containing run.json/taps.csv/tracking.csv")
    parser.add_argument("--out", default=None, help="Output CSV path (default: <run-dir>/sequence.csv)")
    parser.add_argument("--step-ms", type=float, default=None, help="Optional resample step in milliseconds")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    out_path = Path(args.out) if args.out else None
    out = export_sequence(run_dir, out_path=out_path, step_ms=args.step_ms)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
