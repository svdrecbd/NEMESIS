import sys
import os
import time
import json
import csv
import random
import numpy as np
import math
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
sys.path.append(os.getcwd())

from PySide6.QtWidgets import QApplication
from app.ui.widgets.chart import LiveChart
from app.core.logger import RunLogger, TrackingLogger
from app.core.session import RunSession

# Configuration
RUN_DURATION_HOURS = 6.0
ACCLIMATION_MIN = 120.0
WARMUP_SEC = 10.0
SIM_FPS = 30.0
TAP_INTERVAL_SEC = 10.0 # Periodic
OUTPUT_DIR = Path("runs/test_flight_check")

def generate_simulated_data():
    if OUTPUT_DIR.exists():
        import shutil
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    print(f"Generating simulated run in {OUTPUT_DIR}...")
    print(f"Protocol: {ACCLIMATION_MIN}m Acclimation -> {WARMUP_SEC}s Warmup -> {RUN_DURATION_HOURS}h Run")

    # 1. Metadata
    run_meta = {
        "run_id": "PREFLT",
        "schema_version": 6,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "mode": "Periodic",
        "acclimation_min": ACCLIMATION_MIN,
        "warmup_sec": WARMUP_SEC,
        "duration_min": RUN_DURATION_HOURS * 60,
        "camera_fps": SIM_FPS,
        "cv_config": {"threshold": "simulated"},
    }
    with open(OUTPUT_DIR / "run.json", "w") as f:
        json.dump(run_meta, f, indent=2)

    # 2. Taps & Tracking
    # We will simulate the timeline
    # T=0 is when "Run" started (after acclimation)
    
    taps_file = OUTPUT_DIR / "taps.csv"
    tracking_file = OUTPUT_DIR / "tracking.csv"
    
    total_seconds = int(RUN_DURATION_HOURS * 3600)
    warmup_frames = int(WARMUP_SEC * SIM_FPS)
    total_frames = int(total_seconds * SIM_FPS)
    
    print(f"Simulating {total_seconds} seconds of data...")

    # Write Headers
    with open(taps_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["t_host_ms", "t_fw_ms", "mode", "mark", "step", "frame_idx"])
        
    with open(tracking_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["t_host_ms", "frame_idx", "id", "state", "x", "y", "area", "circ", "edge"])

    # Simulation Loop (Fast)
    # We won't iterate every frame, just key events
    
    t_host_ms = 0.0
    frame_idx = 0
    
    # Warmup Phase (No taps)
    # Just skip tracking data for warmup to keep file size small, 
    # but strictly speaking we'd have tracking data.
    t_host_ms += WARMUP_SEC * 1000.0
    frame_idx += warmup_frames
    
    # Run Phase
    next_tap_time = t_host_ms + (TAP_INTERVAL_SEC * 1000.0)
    
    # Use batch writing for speed
    tap_rows = []
    track_rows = []
    
    # Contraction Logic:
    # Stentor contracts on tap, then relaxes.
    # We'll simulate a contraction probability that decreases (habituation).
    habituation_rate = 0.95
    p_contraction = 1.0
    
    current_time_ms = t_host_ms
    end_time_ms = total_seconds * 1000.0
    
    while current_time_ms < end_time_ms:
        # Generate Tap
        tap_rows.append([
            f"{current_time_ms:.1f}", 
            f"{current_time_ms:.1f}", 
            "Periodic", 
            "SCHEDULED", 
            "1", 
            frame_idx
        ])
        
        # Did it contract?
        did_contract = random.random() < p_contraction
        p_contraction = max(0.1, p_contraction * habituation_rate) # Decay
        
        # Add tracking data around the tap
        # If contracted: High Circ, High Velocity (handled by CV, here we just log state)
        # We'll log a few frames of "CONTRACTED" if it contracted
        if did_contract:
            # Reaction latency ~200ms
            reaction_ms = current_time_ms + 200
            track_rows.append([
                f"{reaction_ms:.1f}", 
                frame_idx + 6, # approx 200ms at 30fps
                "1", 
                "CONTRACTED", 
                "500", "500", "1000", "0.95", "0"
            ])
            
        # Move to next tap
        current_time_ms += (TAP_INTERVAL_SEC * 1000.0)
        frame_idx += int(TAP_INTERVAL_SEC * SIM_FPS)

    # Write batches
    with open(taps_file, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(tap_rows)
        
    with open(tracking_file, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(track_rows)
        
    print("Data generation complete.")
    return tap_rows, track_rows

def verify_visualization():
    print("Verifying Visualization (Headless)...")
    app = QApplication(sys.argv) # Needed for Matplotlib QTaggg backend
    
    chart = LiveChart(font_family="Arial", theme={"BG": "#ffffff", "TEXT": "#000000"})
    
    # Load Data
    taps_path = OUTPUT_DIR / "taps.csv"
    tracking_path = OUTPUT_DIR / "tracking.csv"
    
    # Parse Taps
    times = []
    with open(taps_path, "r") as f:
        reader = csv.DictReader(f)
        first_ms = None
        for row in reader:
            t = float(row["t_host_ms"])
            if first_ms is None: first_ms = t
            times.append((t - first_ms) / 1000.0)
            
    # Parse Contractions
    contractions = []
    with open(tracking_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["state"] == "CONTRACTED":
                t = float(row["t_host_ms"])
                contractions.append((t - first_ms) / 1000.0)
                
    print(f"Loaded {len(times)} taps and {len(contractions)} contractions.")
    
    # Feed Chart
    chart.set_times(times)
    for c in contractions:
        chart.add_contraction(c)
        
    # Check Logic
    chart._redraw() # Force update
    
    is_long = chart.long_run_active()
    print(f"Long Run Active: {is_long} (Expected: True, since duration > 3h)")
    
    if not is_long:
        print("FAIL: Chart did not switch to Long Run mode.")
        sys.exit(1)
        
    # Check Heatmap Generation (Analyze)
    # The Chart expects `contraction_heatmap` to be set externally usually (by Analyzer), 
    # OR it might generate it? 
    # Wait, `dashboard.py` loads `analysis.json` and calls `chart.set_contraction_heatmap`.
    # The Chart itself DOES NOT calculate the heatmap from raw points (it's too heavy).
    # It only plots points.
    
    # So we need to Verify that we can SET a heatmap and it draws.
    dummy_heatmap = np.random.rand(6, 60) * 100 # 6 hours, 60 mins
    chart.set_contraction_heatmap(dummy_heatmap)
    chart.set_long_run_view("contraction")
    
    chart._redraw()
    
    # Export
    out_img = OUTPUT_DIR / "chart_verify.png"
    chart.save(str(out_img))
    print(f"Chart exported to {out_img}")
    
    if out_img.exists() and out_img.stat().st_size > 0:
        print("SUCCESS: Pipeline verification passed.")
    else:
        print("FAIL: Chart export failed.")
        sys.exit(1)

if __name__ == "__main__":
    generate_simulated_data()
    verify_visualization()
