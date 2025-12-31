from __future__ import annotations

import csv
from pathlib import Path

from app.core.sequence_export import export_sequence


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def test_export_sequence_basic(tmp_path):
    run_dir = tmp_path / "run_20250101_000000"
    run_dir.mkdir()

    # frames.csv
    _write_csv(
        run_dir / "frames.csv",
        ["frame_idx", "timestamp"],
        [["1", "1.000"], ["2", "1.033"], ["3", "1.066"]],
    )

    # tracking.csv
    _write_csv(
        run_dir / "tracking.csv",
        ["frame_idx", "timestamp", "stentor_id", "state", "circularity", "x", "y", "area"],
        [
            ["1", "1.000", "1", "EXTENDED", "0.4", "10", "20", "100"],
            ["2", "1.033", "1", "CONTRACTED", "0.9", "11", "21", "120"],
            ["3", "1.066", "", "NONE", "", "", "", ""],
        ],
    )

    # taps.csv
    _write_csv(
        run_dir / "taps.csv",
        ["run_id", "tap_id", "tap_uuid", "t_host_ms", "t_host_iso", "t_fw_ms", "mode", "stepsize", "mark", "notes", "frame_preview_idx", "frame_recorded_idx", "recording_path"],
        [
            ["run", "1", "uuid1", "1033", "", "", "Periodic", "4", "scheduled", "", "2", "2", ""],
        ],
    )

    # run.json
    (run_dir / "run.json").write_text('{"run_start_host_ms": 1000}', encoding="utf-8")

    out_path = export_sequence(run_dir)
    assert out_path.exists()

    with out_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)

    assert len(rows) == 3
    assert rows[0]["frame_idx"] == "1"
    assert rows[1]["n_contracted"] == "1"
    assert rows[1]["tap_count"] == "1"
