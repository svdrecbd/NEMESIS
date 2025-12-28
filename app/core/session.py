"""Run session controller encapsulating hardware and per-run state."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Deque

from . import scheduler
from ..drivers.arduino_driver import SerialLink


@dataclass
class RunSession:
    """Owns the hardware/logging state for a single live run tab."""

    scheduler: scheduler.TapScheduler = field(default_factory=scheduler.TapScheduler)
    serial: SerialLink = field(default_factory=SerialLink)

    logger: Optional[object] = None  # Set to RunLogger at runtime
    tracking_logger: Optional[object] = None # Set to TrackingLogger at runtime
    run_dir: Optional[str] = None
    run_start: Optional[float] = None
    taps: int = 0
    
    # CV State
    cv_results: list = field(default_factory=list) # List of StentorState
    cv_mask: Optional[object] = None # Debug mask image

    hardware_run_active: bool = False
    awaiting_switch_start: bool = False
    hardware_configured: bool = False
    hardware_config_message: str = ""

    pending_run_metadata: Optional[dict] = None
    last_hw_tap_ms: Optional[float] = None
    flash_only_mode: bool = False
    first_hw_tap_ms: Optional[float] = None
    first_host_tap_monotonic: Optional[float] = None
    last_host_tap_monotonic: Optional[float] = None
    active_serial_port: str = ""
    camera_index: Optional[int] = None
    preview_size: tuple[int, int] = (0, 0)

    recent_intervals: Deque[float] = field(default_factory=lambda: deque(maxlen=10))
    last_tap_timestamp: Optional[float] = None
    preview_frame_counter: int = 0
    recorded_frame_counter: int = 0
    last_run_elapsed: float = 0.0
    replicant_enabled: bool = False
    replicant_ready: bool = False
    replicant_path: Optional[str] = None
    replicant_offsets: list[float] = field(default_factory=list)
    replicant_delays: list[float] = field(default_factory=list)
    replicant_index: int = 0
    replicant_total: int = 0
    replicant_running: bool = False
    replicant_progress: int = 0

    def reset_runtime_state(self) -> None:
        self.logger = None
        self.run_dir = None
        self.run_start = None
        self.taps = 0
        self.hardware_run_active = False
        self.awaiting_switch_start = False
        self.hardware_configured = False
        self.hardware_config_message = ""
        self.pending_run_metadata = None
        self.last_hw_tap_ms = None
        self.flash_only_mode = False
        self.first_hw_tap_ms = None
        self.first_host_tap_monotonic = None
        self.last_host_tap_monotonic = None
        self.active_serial_port = ""
        self.camera_index = None
        self.preview_size = (0, 0)
        self.recent_intervals.clear()
        self.last_tap_timestamp = None
        self.preview_frame_counter = 0
        self.recorded_frame_counter = 0
        self.last_run_elapsed = 0.0
        self.replicant_enabled = False
        self.replicant_ready = False
        self.replicant_path = None
        self.replicant_offsets.clear()
        self.replicant_delays.clear()
        self.replicant_index = 0
        self.replicant_total = 0
        self.replicant_running = False
        self.replicant_progress = 0

    def reset_tap_history(self) -> None:
        self.recent_intervals.clear()
        self.last_tap_timestamp = None

    def record_tap_interval(self, host_timestamp: float) -> None:
        last = self.last_tap_timestamp
        if last is not None:
            interval = host_timestamp - last
            if interval > 0:
                self.recent_intervals.append(interval)
        self.last_tap_timestamp = host_timestamp

    def recent_rate_per_min(self) -> Optional[float]:
        if not self.recent_intervals:
            return None
        avg_interval = sum(self.recent_intervals) / len(self.recent_intervals)
        if avg_interval <= 0:
            return None
        return 60.0 / avg_interval

    def reset_frame_counters(self) -> None:
        self.preview_frame_counter = 0
        self.recorded_frame_counter = 0
