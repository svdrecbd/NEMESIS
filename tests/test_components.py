
import pytest
import time
import shutil
from pathlib import Path
from app.core.scheduler import TapScheduler
from app.core.logger import RunLogger
from app.drivers.arduino_driver import SerialLink

# --- TapScheduler Tests ---
def test_scheduler_periodic():
    sched = TapScheduler()
    sched.configure_periodic(period_s=0.1)
    delay = sched.next_delay_s()
    assert delay == 0.1
    desc = sched.descriptor()
    assert desc["mode"] == "Periodic"
    assert desc["period_s"] == 0.1

def test_scheduler_poisson():
    sched = TapScheduler(seed=42)
    sched.configure_poisson(lambda_per_min=60.0) # 1 tap/sec on average
    delays = [sched.next_delay_s() for _ in range(100)]
    avg = sum(delays) / len(delays)
    # Mean should be close to 1.0
    assert 0.5 < avg < 1.5
    desc = sched.descriptor()
    assert desc["mode"] == "Poisson"
    assert desc["lambda_per_min"] == 60.0

# --- RunLogger Tests ---
def test_run_logger(tmp_path):
    run_dir = tmp_path / "test_run"
    logger = RunLogger(run_dir=run_dir, run_id="test_id")
    
    # Check if directory and file created
    assert run_dir.exists()
    assert (run_dir / "taps.csv").exists()
    
    # Log a tap
    logger.log_tap(
        host_time_s=1000.0,
        mode="Periodic",
        mark="manual",
        stepsize=3,
        notes="test note"
    )
    
    logger.close()
    
    # Read back
    import csv
    with open(run_dir / "taps.csv", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) == 1
        row = rows[0]
        assert row["run_id"] == "test_id"
        assert row["mark"] == "manual"
        assert row["stepsize"] == "3"
        assert row["notes"] == "test note"

# --- SerialLink Tests ---
# Note: Real hardware is not attached, so we test behavior without a real port.
def test_serial_link_init():
    link = SerialLink()
    assert not link.is_open()
    assert link.send_char("t") is False # Should fail safely
