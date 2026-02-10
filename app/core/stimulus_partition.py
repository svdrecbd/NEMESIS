"""Utilities for partitioning frame timelines into stimulus-conditioned windows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class FrameCondition:
    frame_idx: int
    timestamp_s: float
    is_post_tap: bool
    is_baseline: bool
    active_tap_windows: int


def partition_frames_by_taps(
    frames: Sequence[tuple[int, float]],
    taps_s: Sequence[float],
    *,
    post_window_s: float,
) -> list[FrameCondition]:
    """
    Label each frame timestamp as post-tap or baseline.

    Semantics:
    - Post-tap windows are left-inclusive, right-exclusive: [tap_t, tap_t + post_window_s)
    - Baseline frames are those not covered by any post-tap window.
    - Overlapping windows are counted via `active_tap_windows`.
    """
    if post_window_s <= 0:
        return [
            FrameCondition(
                frame_idx=int(frame_idx),
                timestamp_s=float(ts),
                is_post_tap=False,
                is_baseline=True,
                active_tap_windows=0,
            )
            for frame_idx, ts in frames
        ]

    taps = sorted(float(t) for t in taps_s)
    n_taps = len(taps)
    if n_taps == 0:
        return [
            FrameCondition(
                frame_idx=int(frame_idx),
                timestamp_s=float(ts),
                is_post_tap=False,
                is_baseline=True,
                active_tap_windows=0,
            )
            for frame_idx, ts in frames
        ]

    labels: list[FrameCondition] = []
    # start_idx: first tap whose window has not ended yet
    # end_idx: first tap that starts after current timestamp
    start_idx = 0
    end_idx = 0

    for frame_idx_raw, ts_raw in frames:
        ts = float(ts_raw)
        frame_idx = int(frame_idx_raw)

        while start_idx < n_taps and (taps[start_idx] + post_window_s) <= ts:
            start_idx += 1
        while end_idx < n_taps and taps[end_idx] <= ts:
            end_idx += 1

        active = max(0, end_idx - start_idx)
        is_post = active > 0
        labels.append(
            FrameCondition(
                frame_idx=frame_idx,
                timestamp_s=ts,
                is_post_tap=is_post,
                is_baseline=not is_post,
                active_tap_windows=active,
            )
        )
    return labels
