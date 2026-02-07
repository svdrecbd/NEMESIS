# cvbot.py — The "Brain" for Stentor tracking and state classification
# Implements the "Green on White" segmentation and "Balloon" tracking logic.

from __future__ import annotations

import multiprocessing
import cv2
import numpy as np
import os  # Added for parent watchdog
from collections import deque
from typing import List, Dict, Tuple
from dataclasses import dataclass
import math
import queue

from app.core.configio import load_config, save_config
from app.core.shared_mem import SharedMemoryManager

DEFAULT_EMPTY_MASK_SHAPE = (100, 100)
DEFAULT_CV_CONFIG = {
    "min_area": 100,
    "max_area": 50000,
    "max_anchor_drift": 100.0,
    "memory_seconds": 60.0,
    "circ_threshold": 0.75,
    "snap_velocity": 0.5,
    "history_len": 10,
    "adaptive_block_size": 31,
    "adaptive_c": -5,
    "edge_margin_frac": 0.05,
    "edge_margin_min_px": 12,
    "edge_ignore": False,
}
MIN_ADAPTIVE_BLOCK = 3
MASK_KERNEL_SIZE = (3, 3)
MASK_OPEN_ITERATIONS = 2
HOME_BASE_ALPHA = 0.001
MIN_CLASSIFY_HISTORY = 3
QUEUE_POLL_TIMEOUT_S = 0.1
BGR_RED_CHANNEL = 2
MASK_MAX_VALUE = 255
COLOR_GREEN = (0, 255, 0)
COLOR_RED = (0, 0, 255)
COLOR_YELLOW = (0, 255, 255)
COLOR_ORANGE = (255, 165, 0)
RGB_COLOR_MAX_EXCLUSIVE = 255

@dataclass
class StentorState:
    id: int
    centroid: Tuple[float, float]
    area: float
    circularity: float
    state: str  # "EXTENDED", "CONTRACTED", "UNDETERMINED"
    timestamp: float
    debug_color: Tuple[int, int, int]
    edge_reflection: bool = False

class StentorTracker:
    def __init__(self):
        # Default Configuration
        self.defaults = {"cv": dict(DEFAULT_CV_CONFIG)}
        
        # Load Config
        cfg = load_config()
        if cfg is None:
            cfg = {}
            
        # Ensure CV section exists
        if "cv" not in cfg:
            cfg["cv"] = self.defaults["cv"]
            save_config(cfg) # Save defaults for user to edit
        else:
            # Merge defaults for any missing keys
            dirty = False
            for k, v in self.defaults["cv"].items():
                if k not in cfg["cv"]:
                    cfg["cv"][k] = v
                    dirty = True
            if dirty:
                save_config(cfg)

        cv_cfg = cfg["cv"]

        # Configuration (Loaded from config)
        self.min_area = cv_cfg.get("min_area", DEFAULT_CV_CONFIG["min_area"])
        self.max_area = cv_cfg.get("max_area", DEFAULT_CV_CONFIG["max_area"])
        
        # Tracking Config (The "Balloon" Logic)
        self.max_anchor_drift = cv_cfg.get("max_anchor_drift", DEFAULT_CV_CONFIG["max_anchor_drift"])
        self.memory_seconds = cv_cfg.get("memory_seconds", DEFAULT_CV_CONFIG["memory_seconds"])
        
        # Classification Config (The "End-on" Speed Trap)
        self.circ_threshold = cv_cfg.get("circ_threshold", DEFAULT_CV_CONFIG["circ_threshold"])
        self.snap_velocity = cv_cfg.get("snap_velocity", DEFAULT_CV_CONFIG["snap_velocity"])
        self.history_len = int(cv_cfg.get("history_len", DEFAULT_CV_CONFIG["history_len"]))
        if self.history_len < MIN_CLASSIFY_HISTORY:
            self.history_len = MIN_CLASSIFY_HISTORY
        
        # Adaptive Threshold Parameters
        self.adaptive_block_size = int(cv_cfg.get("adaptive_block_size", DEFAULT_CV_CONFIG["adaptive_block_size"]))
        if self.adaptive_block_size < MIN_ADAPTIVE_BLOCK:
            self.adaptive_block_size = MIN_ADAPTIVE_BLOCK
        if self.adaptive_block_size % 2 == 0:
            self.adaptive_block_size += 1
        self.adaptive_c = int(cv_cfg.get("adaptive_c", DEFAULT_CV_CONFIG["adaptive_c"]))

        # Edge reflection handling
        edge_frac = float(cv_cfg.get("edge_margin_frac", DEFAULT_CV_CONFIG["edge_margin_frac"]))
        self.edge_margin_frac = max(0.0, min(edge_frac, 0.5))
        self.edge_margin_min_px = max(0, int(cv_cfg.get("edge_margin_min_px", DEFAULT_CV_CONFIG["edge_margin_min_px"])))
        self.edge_ignore = bool(cv_cfg.get("edge_ignore", DEFAULT_CV_CONFIG["edge_ignore"]))
        
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
            return [], np.zeros(DEFAULT_EMPTY_MASK_SHAPE, dtype=np.uint8)
        frame_h, frame_w = frame.shape[:2]
        edge_margin = self._edge_margin(frame_w, frame_h)

        # 1. Segmentation (Green Stentor on White Background)
        # Strategy: Use Red channel. 
        # White BG = High Red (255). Green Stentor = Low Red (0-50).
        # Inverting Red channel makes Stentor bright and BG dark.
        
        # Optimize: Extract only Red channel (index 2 in BGR)
        # cv2.split copies all 3 channels. extractChannel copies only 1.
        red_channel = cv2.extractChannel(frame, BGR_RED_CHANNEL)
        
        # Invert Red channel: Stentor (dark in R) becomes bright. BG (bright in R) becomes dark.
        roi = cv2.bitwise_not(red_channel) 
        
        # Adaptive Thresholding to handle lighting drift over weeks
        # Gaussian method handles local shadows better than global threshold
        mask = cv2.adaptiveThreshold(
            roi, 
            MASK_MAX_VALUE, 
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
            cv2.THRESH_BINARY, 
            self.adaptive_block_size,
            self.adaptive_c
        )

        # Morphological Cleanup (Erode noise, Dilate to fill holes in Stentor body)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, MASK_KERNEL_SIZE)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=MASK_OPEN_ITERATIONS)
        
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

            x, y, w, h = cv2.boundingRect(cnt)
            edge_reflection = False
            if edge_margin > 0:
                edge_reflection = (
                    x <= edge_margin
                    or y <= edge_margin
                    or (x + w) >= (frame_w - edge_margin)
                    or (y + h) >= (frame_h - edge_margin)
                )
            if edge_reflection and self.edge_ignore:
                continue
                
            current_blobs.append({
                'centroid': (cx, cy),
                'area': area,
                'circularity': circularity,
                'edge_reflection': edge_reflection,
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
            edge_reflection = bool(track.get("edge_reflection", False))
            if edge_reflection:
                debug_color = COLOR_ORANGE
            
            res = StentorState(
                id=t_id,
                centroid=track['current_centroid'],
                area=track['current_area'],
                circularity=track['current_circularity'],
                state=state,
                timestamp=timestamp,
                debug_color=debug_color,
                edge_reflection=edge_reflection
            )
            results.append(res)
            
        return results, mask

    def _create_track(self, blob, timestamp) -> int:
        tid = self._next_id
        self._next_id += 1
        
        # Assign random color for debug visualization
        color = tuple(np.random.randint(0, RGB_COLOR_MAX_EXCLUSIVE, 3).tolist())
        
        self.tracks[tid] = {
            'id': tid,
            'home_base': blob['centroid'], # Initial position is anchor guess
            'current_centroid': blob['centroid'],
            'current_area': blob['area'],
            'current_circularity': blob['circularity'],
            'history': deque([(timestamp, blob['circularity'])], maxlen=self.history_len),
            'last_seen': timestamp,
            'color': color,
            'frame_cnt': 1,
            'edge_reflection': bool(blob.get("edge_reflection", False)),
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
        track['edge_reflection'] = bool(blob.get("edge_reflection", False))
        
        # Update Home Base (Running Average)
        # Stentor "anchor" doesn't move, but the centroid does (it swings).
        # Over time, the average centroid approximates the anchor + swing radius center.
        # We update it slowly to account for slight arm shifts over weeks.
        hx, hy = track['home_base']
        alpha = HOME_BASE_ALPHA  # Very slow update
        track['home_base'] = (hx * (1-alpha) + cx * alpha, hy * (1-alpha) + cy * alpha)

    def _classify_state(self, track) -> Tuple[str, Tuple[int, int, int]]:
        """
        Determines if EXTENDED, CONTRACTED, or UNDETERMINED based on
        circularity AND rate of change (velocity).
        """
        circ = track['current_circularity']
        
        # 1. Base Shape Check
        if circ < self.circ_threshold:
            return "EXTENDED", COLOR_GREEN # Green for Extended/Healthy
            
        # 2. It looks like a ball. Is it a Snap or a Turn?
        # Check derivative
        history = track['history']
        if len(history) < MIN_CLASSIFY_HISTORY:
            return "UNDETERMINED", COLOR_YELLOW # Yellow - too new
            
        # Calculate velocity: d(Circ) / d(Time)
        # Look at change over last ~0.5 seconds
        t_now, c_now = history[-1]
        t_prev, c_prev = history[0]
        
        dt = t_now - t_prev
        if dt <= 0:
            return "UNDETERMINED", COLOR_YELLOW
            
        d_circ = abs(c_now - c_prev)
        velocity = d_circ / dt # Circ units per second
        
        # Logic: 
        # High Velocity + High Circ = CONTRACTED (Snap)
        # Low Velocity + High Circ = UNDETERMINED (Likely End-on view)
        
        if velocity > self.snap_velocity:
            return "CONTRACTED", COLOR_RED # Red for Contraction event
        else:
            return "UNDETERMINED", COLOR_YELLOW # Yellow for Ambiguous/End-on

    def _edge_margin(self, width: int, height: int) -> int:
        min_dim = min(width, height)
        if min_dim <= 0:
            return 0
        margin = max(self.edge_margin_min_px, int(min_dim * self.edge_margin_frac))
        max_margin = max(0, (min_dim // 2) - 1)
        if max_margin:
            margin = min(margin, max_margin)
        return max(0, margin)


def run_cv_process(shm_name: str, shm_shape: Tuple[int, ...],
                   mask_name: str, mask_shape: Tuple[int, ...],
                   input_queue: multiprocessing.Queue,
                   output_queue: multiprocessing.Queue,
                   stop_event: multiprocessing.Event,
                   slot_generations: multiprocessing.Array,
                   semaphore: multiprocessing.Semaphore | None):
    """
    Process entry point. Runs in a separate process.
    """
    # Initialize Tracker
    tracker = StentorTracker()
    
    # Attach to Shared Memory
    shm = None
    mask_shm = None
    def _release_slot() -> None:
        if semaphore is None:
            return
        try:
            semaphore.release()
        except ValueError:
            pass

    try:
        shm = SharedMemoryManager(shm_name, shm_shape, create=False)
        mask_shm = SharedMemoryManager(mask_name, mask_shape, create=False)
        
        parent_pid = os.getppid()

        while not stop_event.is_set():
            # Watchdog: Exit if parent process dies (reparented to 1 or changed)
            if os.getppid() != parent_pid:
                break

            try:
                # Get next frame task
                # task: (frame_idx, timestamp, buf_idx)
                task = input_queue.get(timeout=QUEUE_POLL_TIMEOUT_S)
            except queue.Empty:
                continue
            
            if task is None: # Sentinel
                break
                
            frame_idx, timestamp, buf_idx = task
            
            # Seqlock: Verify Data Integrity
            # 1. Check generation before reading
            gen_start = slot_generations[buf_idx]
            
            if gen_start != frame_idx:
                # Frame overwritten before we even started!
                # This means we are lagging way behind.
                _release_slot()
                continue

            # 2. Zero-copy read from shared buffer slot
            # shm.array is (BUFFER_COUNT, H, W, C)
            frame_view = shm.array[buf_idx]
            
            # COPY frame to local memory to ensure stability during processing?
            # Actually, if we use Seqlock, we can read directly, but we must check after.
            # Processing takes 10-30ms. If we process directly on SHM, and it gets overwritten
            # halfway through, we get garbage results.
            # Ideally, we make a local copy. It costs memory bandwidth but guarantees atomic analysis.
            try:
                frame_copy = frame_view.copy()
            except Exception:
                _release_slot()
                continue

            # 3. Check generation after reading
            gen_end = slot_generations[buf_idx]
            
            if gen_start != gen_end:
                # Torn frame! Producer wrote to this slot while we were copying.
                # Discard.
                try:
                    output_queue.put(("LOG", "ERROR", f"Dropped torn frame {frame_idx}"))
                except Exception:
                    pass
                _release_slot()
                continue

            try:
                results, mask = tracker.process_frame(frame_copy, timestamp)

                # Write mask to Shared Memory if valid
                if mask is not None and mask_shm is not None:
                    try:
                        # Ensure mask is uint8 and single channel
                        if len(mask.shape) == 2:
                            mask_shm.array[buf_idx][:, :] = mask[:, :]
                        elif len(mask.shape) == 3:
                            mask_shm.array[buf_idx][:, :] = mask[:, :, 0]
                    except Exception as e:
                        output_queue.put(("LOG", "ERROR", f"Mask Write Error: {e}"))

                # Signal completion
                # We send just metadata; consumer reads mask from SHM if needed
                output_queue.put((results, frame_idx, timestamp, buf_idx))

            except Exception as e:
                # Log error back to main process
                try:
                    output_queue.put(("LOG", "ERROR", f"CV Logic Error: {e}"))
                except Exception:
                    pass
                _release_slot()
                    
    except Exception as e:
        # Fatal setup error
        if output_queue:
            output_queue.put(("LOG", "ERROR", f"CV Process Fatal: {e}"))
    finally:
        if shm: shm.cleanup()
        if mask_shm: mask_shm.cleanup()
