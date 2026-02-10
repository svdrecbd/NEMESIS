from __future__ import annotations

import csv
from pathlib import Path
import subprocess
import sys


def _write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def _build_run_artifacts(run_dir: Path) -> None:
    frames = [[i, f"{(i - 1) * 0.5:.3f}"] for i in range(1, 13)]
    _write_csv(run_dir / "frames.csv", ["frame_idx", "timestamp"], frames)

    _write_csv(
        run_dir / "taps.csv",
        [
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
        ],
        [
            ["run_cli", "1", "u1", "1000", "", "", "Poisson", "4", "scheduled", "", "3", "3", ""],
            ["run_cli", "2", "u2", "3000", "", "", "Poisson", "4", "scheduled", "", "7", "7", ""],
        ],
    )

    tracking_rows: list[list[object]] = []
    for i in range(1, 13):
        state = "CONTRACTED" if (i % 3 == 0) else "EXTENDED"
        tracking_rows.append([i, f"{(i - 1) * 0.5:.3f}", "1", state, "0.8", "100.0", "100.0", "1000", "0"])
    _write_csv(
        run_dir / "tracking.csv",
        ["frame_idx", "timestamp", "stentor_id", "state", "circularity", "x", "y", "area", "edge_reflection"],
        tracking_rows,
    )


def test_analyze_ik_cli_smoke(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    run_dir = tmp_path / "run_cli"
    out_dir = run_dir / "ik_out"
    run_dir.mkdir()
    _build_run_artifacts(run_dir)

    proc = subprocess.run(
        [
            sys.executable,
            str(root / "tools" / "analyze_ik.py"),
            "--run-dir",
            str(run_dir),
            "--out-dir",
            str(out_dir),
            "--k-max",
            "2",
            "--m-factors",
            "1",
            "--seeds",
            "0",
            "--null-shuffles",
            "2",
            "--min-condition-duration-s",
            "0",
            "--min-nonmissing-fraction",
            "0",
            "--summary-k-required",
            "1",
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr
    assert "Wrote" in proc.stdout
    assert (out_dir / "ik_by_k.csv").exists()
    assert (out_dir / "ik_qc.csv").exists()
    assert (out_dir / "ik_analysis.json").exists()

    with (out_dir / "ik_by_k.csv").open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows


def test_export_stimulus_partitions_cli_smoke(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    run_dir = tmp_path / "run_cli"
    run_dir.mkdir()
    _build_run_artifacts(run_dir)
    out_path = run_dir / "stimulus_partitions.csv"

    proc = subprocess.run(
        [
            sys.executable,
            str(root / "tools" / "export_stimulus_partitions.py"),
            "--run-dir",
            str(run_dir),
            "--out",
            str(out_path),
            "--post-window-s",
            "0.75",
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr
    assert "Wrote" in proc.stdout
    assert out_path.exists()

    with out_path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 12
    post_n = sum(1 for row in rows if row["is_post_tap"] == "1")
    baseline_n = sum(1 for row in rows if row["is_baseline"] == "1")
    assert post_n > 0
    assert baseline_n > 0
