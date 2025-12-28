# cvbot.py — The "Brain" for Stentor tracking and state classification
# Implements the "Green on White" segmentation and "Balloon" tracking logic.

import cv2
import numpy as np
from collections import deque
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
import math

@dataclass
class StentorState:
    id: int
    centroid: Tuple[float, float]
    area: float
    circularity: float
    state: str  # "EXTENDED", "CONTRACTED", "UNDETERMINED"
    timestamp: float
    debug_color: Tuple[int, int, int]

class StentorTracker:
    def __init__(self):
        # Configuration (Tweak these based on real feed)
        self.min_area = 100         # Ignore noise < 100 px
        self.max_area = 50000       # Ignore debris > 50k px
        
        # Tracking Config (The "Balloon" Logic)
        self.max_anchor_drift = 100.0 # Pixels. If blob is further than this from Home Base, it's not the same guy.
        self.memory_seconds = 60.0    # Remember a lost Stentor for 60s before forgetting its Home Base
        
        # Classification Config (The "End-on" Speed Trap)
        self.circ_threshold = 0.75    # Above this, it LOOKS contracted (Ball shape)
        self.snap_velocity = 0.5      # Change in circularity per second to qualify as a "Snap"
        self.history_len = 10         # Frames to keep for velocity calc
        
        # State
        self.tracks: Dict[int, dict] = {} 
        # Track structure: 
        # {
        #   'id': int,
        #   'home_base': (x, y),  # Running average of position
        #   'history': deque([(ts, circ), ...]),
        #   'last_seen': float,
        #   'color': (r,g,b)
        # }
        self._next_id = 1
        self._frame_idx = 0

    def process_frame(self, frame: np.ndarray, timestamp: float) -> Tuple[List[StentorState], np.ndarray]:
        """
        Main entry point.
        Returns: 
          1. List of StentorState objects for this frame.
          2. A debug image (binary mask) showing what the CV "sees".
        """
        self._frame_idx += 1
        
        # 1. Segmentation (Green Stentor on White Background)
        # Strategy: Use Red channel. 
        # White BG = High Red (255). Green Stentor = Low Red (0-50).
        # Inverting Red channel makes Stentor bright and BG dark.
        if frame is None:
            return [], np.zeros((100,100), dtype=np.uint8)

        b, g, r = cv2.split(frame)
        
        # Invert Red channel: Stentor (dark in R) becomes bright. BG (bright in R) becomes dark.
        roi = cv2.bitwise_not(r) 
        
        # Adaptive Thresholding to handle lighting drift over weeks
        # Gaussian method handles local shadows better than global threshold
        mask = cv2.adaptiveThreshold(
            roi, 
            255, 
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
            cv2.THRESH_BINARY, 
            31, # Block size (must be odd, tune this based on Stentor size)
            -5  # Constant C (subtracting pushes noise to black)
        )

        # Morphological Cleanup (Erode noise, Dilate to fill holes in Stentor body)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3,3))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=2)
        
        # 2. Blob Detection
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        current_blobs = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < self.min_area or area > self.max_area:
                continue
                
            # Geometry features
            perimeter = cv2.arcLength(cnt, True)
            if perimeter == 0: 
                continue
                
            circularity = (4 * math.pi * area) / (perimeter ** 2)
            
            M = cv2.moments(cnt)
            if M["m00"] != 0:
                cx = float(M["m10"] / M["m00"])
                cy = float(M["m01"] / M["m00"])
            else:
                cx, cy = 0.0, 0.0
                
            current_blobs.append({
                'centroid': (cx, cy),
                'area': area,
                'circularity': circularity,
                'cnt': cnt
            })

        # 3. Tracking (The "Home Base" Anchor)
        # Match current blobs to existing tracks based on distance to Home Base
        active_tracks = []
        
        # Simple greedy matching (O(N^2) but N=20 so it's instant)
        # Cost matrix: Distance between blob centroid and track Home Base
        matched_blob_indices = set()
        matched_track_ids = set()
        
        # Sort potential matches by distance to favor closest locks
        matches = []
        for t_id, track in self.tracks.items():
            hx, hy = track['home_base']
            for b_idx, blob in enumerate(current_blobs):
                bx, by = blob['centroid']
                dist = math.hypot(bx - hx, by - hy)
                if dist < self.max_anchor_drift:
                    matches.append((dist, t_id, b_idx))
        
        matches.sort(key=lambda x: x[0]) # Closest matches first
        
        for dist, t_id, b_idx in matches:
            if t_id in matched_track_ids or b_idx in matched_blob_indices:
                continue
                
            # Found a match
            matched_track_ids.add(t_id)
            matched_blob_indices.add(b_idx)
            
            self._update_track(t_id, current_blobs[b_idx], timestamp)
            active_tracks.append(t_id)

        # 4. Handle New Stentor (Blobs that didn't match any Home Base)
        for b_idx, blob in enumerate(current_blobs):
            if b_idx not in matched_blob_indices:
                # New track
                new_id = self._create_track(blob, timestamp)
                active_tracks.append(new_id)

        # 5. Cleanup Old Tracks
        # If not seen for memory_seconds, delete.
        # But for anchored stentor, they really shouldn't disappear. 
        # We'll just mark them inactive in internal state but keep ID ready.
        t_ids_to_remove = []
        for t_id, track in self.tracks.items():
            if timestamp - track['last_seen'] > self.memory_seconds:
                t_ids_to_remove.append(t_id)
        for t_id in t_ids_to_remove:
            del self.tracks[t_id]

        # 6. Generate Result Objects
        results = []
        for t_id in active_tracks:
            track = self.tracks[t_id]
            
            # Classification Logic
            state, debug_color = self._classify_state(track)
            
            res = StentorState(
                id=t_id,
                centroid=track['current_centroid'],
                area=track['current_area'],
                circularity=track['current_circularity'],
                state=state,
                timestamp=timestamp,
                debug_color=debug_color
            )
            results.append(res)
            
        return results, mask

    def _create_track(self, blob, timestamp) -> int:
        tid = self._next_id
        self._next_id += 1
        
        # Assign random color for debug visualization
        color = tuple(np.random.randint(0, 255, 3).tolist())
        
        self.tracks[tid] = {
            'id': tid,
            'home_base': blob['centroid'], # Initial position is anchor guess
            'current_centroid': blob['centroid'],
            'current_area': blob['area'],
            'current_circularity': blob['circularity'],
            'history': deque([(timestamp, blob['circularity'])], maxlen=self.history_len),
            'last_seen': timestamp,
            'color': color,
            'frame_cnt': 1
        }
        return tid

    def _update_track(self, tid, blob, timestamp):
        track = self.tracks[tid]
        cx, cy = blob['centroid']
        
        # Update current stats
        track['current_centroid'] = (cx, cy)
        track['current_area'] = blob['area']
        track['current_circularity'] = blob['circularity']
        track['last_seen'] = timestamp
        track['history'].append((timestamp, blob['circularity']))
        track['frame_cnt'] += 1
        
        # Update Home Base (Running Average)
        # Stentor "anchor" doesn't move, but the centroid does (it swings).
        # Over time, the average centroid approximates the anchor + swing radius center.
        # We update it slowly to account for slight rig shifts over weeks.
        hx, hy = track['home_base']
        alpha = 0.001 # Very slow update
        track['home_base'] = (hx * (1-alpha) + cx * alpha, hy * (1-alpha) + cy * alpha)

    def _classify_state(self, track) -> Tuple[str, Tuple[int, int, int]]:
        """
        Determines if EXTENDED, CONTRACTED, or UNDETERMINED based on
        circularity AND rate of change (velocity).
        """
        circ = track['current_circularity']
        
        # 1. Base Shape Check
        if circ < self.circ_threshold:
            return "EXTENDED", (0, 255, 0) # Green for Extended/Healthy
            
        # 2. It looks like a ball. Is it a Snap or a Turn?
        # Check derivative
        history = track['history']
        if len(history) < 3:
            return "UNDETERMINED", (0, 255, 255) # Yellow - too new
            
        # Calculate velocity: d(Circ) / d(Time)
        # Look at change over last ~0.5 seconds
        t_now, c_now = history[-1]
        t_prev, c_prev = history[0]
        
        dt = t_now - t_prev
        if dt <= 0:
            return "UNDETERMINED", (0, 255, 255)
            
        d_circ = abs(c_now - c_prev)
        velocity = d_circ / dt # Circ units per second
        
        # Logic: 
        # High Velocity + High Circ = CONTRACTED (Snap)
        # Low Velocity + High Circ = UNDETERMINED (Likely End-on view)
        
        if velocity > self.snap_velocity:
            return "CONTRACTED", (0, 0, 255) # Red for Contraction event
        else:
            return "UNDETERMINED", (0, 255, 255) # Yellow for Ambiguous/End-on


def run_cv_process(shm_name: str, shm_shape: Tuple[int, int, int], 
                   input_queue: "multiprocessing.Queue", 
                   output_queue: "multiprocessing.Queue",
                   stop_event: "multiprocessing.Event"):
    """
    Process entry point. Runs in a separate process.
    """
    from .shared_mem import SharedMemoryManager
    import time
    import queue

    # Initialize Tracker
    tracker = StentorTracker()
    
    # Attach to Shared Memory
    try:
        with SharedMemoryManager(shm_name, shm_shape, create=False) as shm:
            while not stop_event.is_set():
                try:
                    # Get next frame task
                    # task: (frame_idx, timestamp)
                    task = input_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                
                if task is None: # Sentinel
                    break
                    
                frame_idx, timestamp = task
                
                # Zero-copy read from shared buffer
                # Note: We must treat this as read-only or copy if we modify it
                # tracker.process_frame DOES modify (for splits), so we copy for safety here
                # Optimization: Modify tracker to not need copy if possible, but 
                # copying a 1280x720 array in memory is still way faster than pickling it.
                # Actually, process_frame uses cv2.split which creates copies anyway.
                # So we can pass the view directly if we are careful.
                frame_view = shm.array
                
                try:
                    results, mask = tracker.process_frame(frame_view, timestamp)
                    
                    # We can't send the mask (numpy array) back efficiently without another SHM
                    # For now, we just skip sending the mask back to keep it fast.
                    # If we need debug mask in UI, we'd use a second SHM buffer.
                    output_queue.put((results, frame_idx, timestamp))
                    
                except Exception as e:
                    # Don't crash the worker
                    print(f"CV Process Error: {e}")
                    
    except Exception as e:
        print(f"CV Process Fatal Error: {e}")
