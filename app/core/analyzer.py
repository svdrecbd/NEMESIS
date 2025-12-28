import csv
import json
from pathlib import Path
from typing import Optional, Dict, List
from app.core.logger import APP_LOGGER

class RunAnalyzer:
    """
    Correlates stimulus logs (taps.csv) with CV tracking data (tracking.csv)
    to calculate habituation response curves.
    """
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.taps_path = run_dir / "taps.csv"
        self.tracking_path = run_dir / "tracking.csv"
        self.output_path = run_dir / "analysis.json"

    def analyze(self, response_window_s: float = 2.0) -> Optional[Dict]:
        """
        Generates analysis.json containing response rates for each tap.
        response_window_s: Time window after tap to check for contraction.
        """
        if not self.taps_path.exists():
            APP_LOGGER.error(f"Cannot analyze {self.run_dir}: taps.csv missing.")
            return None
        
        if not self.tracking_path.exists():
            APP_LOGGER.error(f"Cannot analyze {self.run_dir}: tracking.csv missing.")
            return None

        # 1. Load Taps
        taps = []
        try:
            with open(self.taps_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        # t_host_ms is monotonic time in ms
                        t_sec = float(row['t_host_ms']) / 1000.0
                        taps.append({
                            'id': row['tap_id'],
                            'time': t_sec,
                            'row': row # Keep original data
                        })
                    except ValueError:
                        continue
        except Exception as e:
            APP_LOGGER.error(f"Error reading taps.csv: {e}")
            return None

        # 2. Load Tracking Data
        # We load into memory. For weeks-long data (GBs), we might need chunking,
        # but for now (MBs) memory is fine.
        track_data = []
        try:
            with open(self.tracking_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        ts = float(row['timestamp'])
                        sid = row['stentor_id']
                        state = row['state']
                        track_data.append((ts, sid, state))
                    except ValueError:
                        continue
        except Exception as e:
            APP_LOGGER.error(f"Error reading tracking.csv: {e}")
            return None
            
        # Ensure tracking data is sorted by time (usually is, but be safe)
        track_data.sort(key=lambda x: x[0])

        analyzed_taps = []
        
        # 3. Correlate (Sliding Window / Filter)
        # Optimization: Track data index cursor
        track_idx = 0
        n_track = len(track_data)
        
        for tap in taps:
            t_start = tap['time']
            t_end = t_start + response_window_s
            
            # Advance cursor to start of window
            while track_idx < n_track and track_data[track_idx][0] < t_start:
                track_idx += 1
            
            # Scan forward until end of window
            # Don't move track_idx permanently because windows might overlap (unlikely for 2s window but good practice)
            temp_idx = track_idx
            
            visible_ids = set()
            contracted_ids = set()
            
            while temp_idx < n_track:
                ts, sid, state = track_data[temp_idx]
                if ts > t_end:
                    break
                
                visible_ids.add(sid)
                if state == "CONTRACTED":
                    contracted_ids.add(sid)
                
                temp_idx += 1
            
            total = len(visible_ids)
            responded = len(contracted_ids)
            pct = (responded / total * 100.0) if total > 0 else 0.0
            
            analyzed_taps.append({
                "tap_id": tap['id'],
                "timestamp": t_start,
                "total_visible": total,
                "responded_count": responded,
                "response_percent": pct,
                "note": tap['row'].get('notes', '')
            })

        results = {
            "run_id": self.run_dir.name,
            "config": {
                "response_window_s": response_window_s
            },
            "taps": analyzed_taps
        }

        # 4. Save
        try:
            with open(self.output_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2)
            APP_LOGGER.info(f"Analysis saved to {self.output_path}")
        except Exception as e:
            APP_LOGGER.error(f"Failed to write analysis.json: {e}")
            return None
            
        return results
