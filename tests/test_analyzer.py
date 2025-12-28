import csv
import pytest
from app.core.analyzer import RunAnalyzer

@pytest.fixture
def mock_run_dir(tmp_path):
    run_dir = tmp_path / "run_20250101_000000"
    run_dir.mkdir()
    
    # Create taps.csv
    # Fields: run_id,tap_id,tap_uuid,t_host_ms,t_host_iso,t_fw_ms,mode,stepsize,mark,notes,frame_preview_idx,frame_recorded_idx,recording_path
    taps_file = run_dir / "taps.csv"
    with open(taps_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["run_id","tap_id","tap_uuid","t_host_ms","t_host_iso","t_fw_ms","mode","stepsize","mark","notes","frame_preview_idx","frame_recorded_idx","recording_path"])
        # Tap at 1.0s and 5.0s
        writer.writerow(["run", "1", "uuid1", "1000", "", "", "Periodic", "4", "scheduled", "", "10", "10", ""])
        writer.writerow(["run", "2", "uuid2", "5000", "", "", "Periodic", "4", "scheduled", "", "50", "50", ""])
        
    # Create tracking.csv
    # Fields: frame_idx,timestamp,stentor_id,state,circularity,x,y,area
    tracking_file = run_dir / "tracking.csv"
    with open(tracking_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["frame_idx","timestamp","stentor_id","state","circularity","x","y","area"])
        
        # Stentor 1: Contracted after first tap (1.0s)
        writer.writerow(["9", "0.9", "1", "EXTENDED", "0.5", "100", "100", "1000"])
        writer.writerow(["11", "1.1", "1", "CONTRACTED", "0.9", "100", "100", "500"])
        
        # Stentor 1: Extended after second tap (5.0s) - No response
        writer.writerow(["49", "4.9", "1", "EXTENDED", "0.5", "100", "100", "1000"])
        writer.writerow(["51", "5.1", "1", "EXTENDED", "0.5", "100", "100", "1000"])

    return run_dir

def test_analyzer_basic(mock_run_dir):
    analyzer = RunAnalyzer(mock_run_dir)
    results = analyzer.analyze(response_window_s=2.0)
    
    assert results is not None
    assert len(results["taps"]) == 2
    
    # First tap (1.0s) should have 100% response (Stentor 1 contracted at 1.1s)
    assert results["taps"][0]["responded_count"] == 1
    assert results["taps"][0]["response_percent"] == 100.0
    
    # Second tap (5.0s) should have 0% response (Stentor 1 stayed EXTENDED at 5.1s)
    assert results["taps"][1]["responded_count"] == 0
    assert results["taps"][1]["response_percent"] == 0.0

def test_analyzer_missing_files(tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    analyzer = RunAnalyzer(empty_dir)
    assert analyzer.analyze() is None
