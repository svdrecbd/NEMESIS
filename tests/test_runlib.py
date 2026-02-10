from __future__ import annotations

import json
from pathlib import Path

from app.core.runlib import RunLibrary


def _make_run(
    root: Path,
    run_id: str,
    *,
    t0_ms: int = 1000,
    t1_ms: int = 2000,
    recording_path: str | None = None,
) -> Path:
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "started_at": "2026-01-01T00:00:00+00:00",
                "mode": "Periodic",
                "recording_path": recording_path or "",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "taps.csv").write_text(
        "run_id,tap_id,tap_uuid,t_host_ms,t_host_iso,t_fw_ms,mode,stepsize,mark,notes,frame_preview_idx,frame_recorded_idx,recording_path\n"
        f"{run_id},1,u1,{t0_ms},,,Periodic,4,scheduled,,,0,0,\n"
        f"{run_id},2,u2,{t1_ms},,,Periodic,4,scheduled,,,1,1,\n",
        encoding="utf-8",
    )
    return run_dir


def test_runlibrary_lists_runs_from_multiple_roots(tmp_path: Path):
    root_a = tmp_path / "runs_a"
    root_b = tmp_path / "runs_b"
    _make_run(root_a, "run_20260101_000001_AAAAAA")
    _make_run(root_b, "run_20260101_000002_BBBBBB")

    lib = RunLibrary([root_a, root_b])
    runs = lib.list_runs()
    ids = [r.run_id for r in runs]
    assert "run_20260101_000001_AAAAAA" in ids
    assert "run_20260101_000002_BBBBBB" in ids


def test_runlibrary_dedupes_duplicate_roots(tmp_path: Path):
    root = tmp_path / "runs"
    _make_run(root, "run_20260101_000001_AAAAAA")

    lib = RunLibrary([root, root])
    runs = lib.list_runs()
    assert len(runs) == 1
    assert runs[0].run_id == "run_20260101_000001_AAAAAA"


def test_runlibrary_delete_run_across_roots(tmp_path: Path):
    root_a = tmp_path / "runs_a"
    root_b = tmp_path / "runs_b"
    _make_run(root_a, "run_20260101_000001_AAAAAA")
    target = _make_run(root_b, "run_20260101_000002_BBBBBB")

    lib = RunLibrary([root_a, root_b])
    assert lib.delete_run("run_20260101_000002_BBBBBB")
    assert not target.exists()
    remaining_ids = {r.run_id for r in lib.list_runs()}
    assert remaining_ids == {"run_20260101_000001_AAAAAA"}


def test_runlibrary_delete_run_removes_linked_recording_artifact(tmp_path: Path):
    runs_root = tmp_path / "runs"
    rec_root = tmp_path / "recording_20260101_000000"
    rec_root.mkdir(parents=True, exist_ok=True)
    rec_path = rec_root / "video.mp4"
    rec_path.write_bytes(b"abc")

    target = _make_run(
        runs_root,
        "run_20260101_000001_AAAAAA",
        recording_path=str(rec_path),
    )

    lib = RunLibrary([runs_root])
    assert lib.delete_run("run_20260101_000001_AAAAAA", run_path=target)
    assert not target.exists()
    assert not rec_path.exists()
    assert not rec_root.exists()
