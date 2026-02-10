import csv
import random
from pathlib import Path

from app.core.ik_analysis import (
    IKConfig,
    analyze_ik,
    coarse_grain_random_pick,
    compute_ik_profile,
    shuffled_null_distribution,
)


def test_compute_ik_profile_markov_first_order():
    rng = random.Random(7)
    n = 8000
    flip_p = 0.1
    values = [rng.choice([0, 1])]
    for _ in range(1, n):
        prev = values[-1]
        if rng.random() < flip_p:
            values.append(1 - prev)
        else:
            values.append(prev)
    mask = [True] * n
    hk, n_eff, ik = compute_ik_profile(values, mask, k_max=3)
    assert hk[0] is not None
    assert n_eff[1] > 0
    assert ik[1] is not None and ik[1] > 0.1
    assert ik[2] is not None and ik[2] < (ik[1] * 0.3)
    assert ik[3] is not None and ik[3] < (ik[1] * 0.3)


def test_compute_ik_profile_second_order_lag2_copy():
    rng = random.Random(11)
    n = 12000
    values = [rng.choice([0, 1]), rng.choice([0, 1])]
    for t in range(2, n):
        base = values[t - 2]
        if rng.random() < 0.9:
            values.append(base)
        else:
            values.append(1 - base)
    mask = [True] * n
    _, _, ik = compute_ik_profile(values, mask, k_max=3)
    assert ik[1] is not None and ik[1] < 0.1
    assert ik[2] is not None and ik[2] > 0.4


def test_coarse_grain_random_pick_seed_reproducible():
    values = [None, 0, 1, 0, 1, None, 0, 1, 1, 0]
    masks = {
        "all_time": [True] * len(values),
        "baseline": [i % 2 == 0 for i in range(len(values))],
        "post_tap": [i % 2 == 1 for i in range(len(values))],
    }
    a_values, a_masks = coarse_grain_random_pick(values, masks, factor=3, rng=random.Random(123))
    b_values, b_masks = coarse_grain_random_pick(values, masks, factor=3, rng=random.Random(123))
    assert a_values == b_values
    assert a_masks == b_masks


def _write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def test_analyze_ik_outputs_smoke(tmp_path: Path):
    run_dir = tmp_path / "run_x"
    run_dir.mkdir()

    frames = []
    for i in range(1, 201):
        ts = (i - 1) * 0.1
        frames.append([i, f"{ts:.3f}"])
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
            ["run_x", "1", "u1", "2000", "", "", "Poisson", "4", "scheduled", "", "20", "20", ""],
            ["run_x", "2", "u2", "8000", "", "", "Poisson", "4", "scheduled", "", "80", "80", ""],
        ],
    )

    tracking_rows = []
    # One cell mostly observed, switching between extended/contracted.
    for i in range(1, 201):
        state = "CONTRACTED" if (i % 7 == 0) else "EXTENDED"
        edge = "1" if (i % 50 == 0) else "0"
        tracking_rows.append(
            [i, f"{(i - 1) * 0.1:.3f}", "1", state, "0.8", "100.0", "100.0", "1000", edge]
        )
    _write_csv(
        run_dir / "tracking.csv",
        ["frame_idx", "timestamp", "stentor_id", "state", "circularity", "x", "y", "area", "edge_reflection"],
        tracking_rows,
    )

    cfg = IKConfig(
        k_max=4,
        post_window_s=1.5,
        m_factors=(1, 2),
        seeds=(0, 1),
        null_shuffles=3,
        min_condition_duration_s=0.0,
        min_nonmissing_fraction=0.0,
        summary_k_required=2,
    )
    outputs = analyze_ik(run_dir, config=cfg)
    assert outputs.by_k_path.exists()
    assert outputs.qc_path.exists()
    assert outputs.summary_path.exists()

    with outputs.by_k_path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows
    assert {row["condition"] for row in rows} == {"all_time", "baseline", "post_tap"}


def test_analyze_ik_default_thresholds_exclude_short_run(tmp_path: Path):
    run_dir = tmp_path / "run_short"
    run_dir.mkdir()

    frames = []
    for i in range(1, 201):
        frames.append([i, f"{(i - 1) * 0.1:.3f}"])
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
        [["run_short", "1", "u1", "5000", "", "", "Poisson", "4", "scheduled", "", "50", "50", ""]],
    )

    tracking_rows = []
    for i in range(1, 201):
        state = "CONTRACTED" if (i % 2 == 0) else "EXTENDED"
        tracking_rows.append(
            [i, f"{(i - 1) * 0.1:.3f}", "1", state, "0.8", "100.0", "100.0", "1000", "0"]
        )
    _write_csv(
        run_dir / "tracking.csv",
        ["frame_idx", "timestamp", "stentor_id", "state", "circularity", "x", "y", "area", "edge_reflection"],
        tracking_rows,
    )

    cfg = IKConfig(
        k_max=3,
        m_factors=(1,),
        seeds=(0,),
        null_shuffles=0,
    )
    outputs = analyze_ik(run_dir, config=cfg)

    with outputs.by_k_path.open("r", encoding="utf-8", newline="") as fh:
        by_k_rows = list(csv.DictReader(fh))
    with outputs.qc_path.open("r", encoding="utf-8", newline="") as fh:
        qc_rows = list(csv.DictReader(fh))

    assert by_k_rows == []
    assert len(qc_rows) == 3
    assert {row["condition"] for row in qc_rows} == {"all_time", "baseline", "post_tap"}
    assert all(row["base_included"] == "0" for row in qc_rows)


def test_analyze_ik_edge_reflection_and_undetermined_become_missing(tmp_path: Path):
    run_dir = tmp_path / "run_missing_map"
    run_dir.mkdir()

    _write_csv(
        run_dir / "frames.csv",
        ["frame_idx", "timestamp"],
        [[1, "0.0"], [2, "1.0"], [3, "2.0"], [4, "3.0"], [5, "4.0"], [6, "5.0"]],
    )
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
        [],
    )
    _write_csv(
        run_dir / "tracking.csv",
        ["frame_idx", "timestamp", "stentor_id", "state", "circularity", "x", "y", "area", "edge_reflection"],
        [
            [1, "0.0", "1", "EXTENDED", "0.8", "0", "0", "10", "0"],
            [2, "1.0", "1", "CONTRACTED", "0.8", "0", "0", "10", "1"],  # edge => missing
            [3, "2.0", "1", "CONTRACTED", "0.8", "0", "0", "10", "0"],
            [4, "3.0", "1", "UNDETERMINED", "0.8", "0", "0", "10", "0"],  # undetermined => missing
            [5, "4.0", "1", "EXTENDED", "0.8", "0", "0", "10", "0"],
            [6, "5.0", "1", "CONTRACTED", "0.8", "0", "0", "10", "0"],
        ],
    )

    cfg = IKConfig(
        k_max=1,
        m_factors=(1,),
        seeds=(0,),
        null_shuffles=0,
        min_condition_duration_s=0.0,
        min_nonmissing_fraction=0.0,
        summary_k_required=1,
    )
    outputs = analyze_ik(run_dir, config=cfg)

    with outputs.by_k_path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    all_time_k1 = [r for r in rows if r["condition"] == "all_time" and r["k"] == "1"]
    assert len(all_time_k1) == 1
    assert all_time_k1[0]["n_eff"] == "1"


def test_shuffled_null_distribution_emits_per_shuffle_ik_values():
    values = [0, 1, 0, 1, 0, 1]
    mask = [True] * len(values)
    dist = shuffled_null_distribution(
        values,
        mask,
        k_max=2,
        rng=random.Random(23),
        n_shuffles=7,
    )
    assert set(dist.keys()) == {1, 2}
    assert len(dist[1]) == 7
    assert len(dist[2]) == 7
