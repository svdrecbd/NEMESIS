import pytest
from app.core.session import RunSession

def test_run_session_reset():
    session = RunSession()
    session.taps = 10
    session.hardware_run_active = True
    session.camera_index = 0
    
    session.reset_runtime_state()
    
    assert session.taps == 0
    assert session.hardware_run_active is False
    assert session.camera_index is None

def test_run_session_tap_intervals():
    session = RunSession()
    
    # First tap
    session.record_tap_interval(100.0)
    assert session.recent_rate_per_min() is None # Need at least 2
    
    # Second tap (10s later)
    session.record_tap_interval(110.0)
    # 1 tap / 10s = 6 taps / min
    assert session.recent_rate_per_min() == 6.0
    
    # Third tap (5s later)
    session.record_tap_interval(115.0)
    # Intervals: 10s, 5s. Avg = 7.5s. Rate = 60 / 7.5 = 8.0
    assert session.recent_rate_per_min() == 8.0

def test_run_session_frame_counters():
    session = RunSession()
    session.preview_frame_counter = 100
    session.recorded_frame_counter = 50
    
    session.reset_frame_counters()
    
    assert session.preview_frame_counter == 0
    assert session.recorded_frame_counter == 0
