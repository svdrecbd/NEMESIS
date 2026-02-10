from app.core.stimulus_partition import partition_frames_by_taps


def test_partition_no_taps_all_baseline():
    frames = [(i, float(i)) for i in range(5)]
    labels = partition_frames_by_taps(frames, [], post_window_s=2.0)
    assert len(labels) == 5
    assert all(row.is_baseline for row in labels)
    assert all(not row.is_post_tap for row in labels)
    assert all(row.active_tap_windows == 0 for row in labels)


def test_partition_window_boundaries():
    frames = [(0, 0.0), (1, 0.999), (2, 1.0), (3, 2.999), (4, 3.0)]
    taps = [1.0]
    labels = partition_frames_by_taps(frames, taps, post_window_s=2.0)
    # [1.0, 3.0): inclusive at start, exclusive at end
    assert labels[0].is_baseline
    assert labels[1].is_baseline
    assert labels[2].is_post_tap
    assert labels[3].is_post_tap
    assert labels[4].is_baseline


def test_partition_overlapping_windows_counts_active():
    frames = [(0, 1.5), (1, 2.0), (2, 2.5), (3, 3.5)]
    taps = [1.0, 2.0]
    labels = partition_frames_by_taps(frames, taps, post_window_s=2.0)
    # Windows are [1,3) and [2,4)
    assert labels[0].active_tap_windows == 1
    assert labels[1].active_tap_windows == 2
    assert labels[2].active_tap_windows == 2
    assert labels[3].active_tap_windows == 1
    assert all(row.is_post_tap for row in labels)
