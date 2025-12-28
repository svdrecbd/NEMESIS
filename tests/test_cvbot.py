import pytest
import numpy as np
import cv2
from app.core.cvbot import StentorTracker, StentorState

def create_synthetic_stentor(size=(100, 100), center=(50, 50), radius=10, color=(0, 255, 0)):
    """Creates a white frame with a colored circle (simulating a Stentor)."""
    # BG is white (255, 255, 255)
    frame = np.full((size[1], size[0], 3), 255, dtype=np.uint8)
    # Stentor is green (or whatever color)
    cv2.circle(frame, center, radius, color, -1)
    return frame

def test_segmentation_logic():
    tracker = StentorTracker()
    # Create a frame with a clear green circle
    frame = create_synthetic_stentor(center=(30, 30), radius=15)
    
    results, mask = tracker.process_frame(frame, timestamp=1.0)
    
    assert len(results) == 1
    assert results[0].id == 1
    # Check if centroid is roughly where we put it
    assert abs(results[0].centroid[0] - 30) < 2
    assert abs(results[0].centroid[1] - 30) < 2
    # Check mask - should have non-zero pixels since a result was found
    assert mask.any()
    # Check that the mask is generally in the right area
    assert mask[25:35, 25:35].any()

def test_tracking_persistence():
    tracker = StentorTracker()
    
    # Frame 1: Stentor at (30, 30)
    frame1 = create_synthetic_stentor(center=(30, 30), radius=15)
    results1, _ = tracker.process_frame(frame1, timestamp=1.0)
    assert len(results1) == 1
    first_id = results1[0].id
    
    # Frame 2: Stentor moved slightly to (32, 32)
    frame2 = create_synthetic_stentor(center=(32, 32), radius=15)
    results2, _ = tracker.process_frame(frame2, timestamp=1.1)
    assert len(results2) == 1
    assert results2[0].id == first_id # Identity should be preserved

def test_home_base_anchor():
    tracker = StentorTracker()
    tracker.max_anchor_drift = 50 # Limit for matching
    
    # Frame 1: Stentor at (30, 30)
    frame1 = create_synthetic_stentor(center=(30, 30), radius=15)
    tracker.process_frame(frame1, timestamp=1.0)
    
    # Frame 2: Stentor jumps far away to (150, 150)
    # This should be treated as a new Stentor because it's > max_anchor_drift from (30, 30)
    frame2 = create_synthetic_stentor(size=(200, 200), center=(150, 150), radius=15)
    results2, _ = tracker.process_frame(frame2, timestamp=1.1)
    
    assert len(results2) == 1
    assert results2[0].id != 1 # Should be a new ID

def test_state_classification_extended():
    tracker = StentorTracker()
    # A circle (high circularity) might be seen as UNDETERMINED if velocity is low,
    # or CONTRACTED if it just snapped. 
    # To test EXTENDED, we need something non-circular.
    
    # Create an elongated ellipse (low circularity)
    frame = np.full((200, 200, 3), 255, dtype=np.uint8)
    cv2.ellipse(frame, (100, 100), (40, 10), 0, 0, 360, (0, 255, 0), -1)
    
    results, _ = tracker.process_frame(frame, timestamp=1.0)
    assert len(results) == 1
    assert results[0].state == "EXTENDED"

def test_state_classification_contracted_velocity():
    tracker = StentorTracker()
    tracker.snap_velocity = 0.1 # Lower threshold for test
    
    # Frame 1: Elongated
    frame1 = np.full((200, 200, 3), 255, dtype=np.uint8)
    cv2.ellipse(frame1, (100, 100), (50, 10), 0, 0, 360, (0, 255, 0), -1)
    tracker.process_frame(frame1, timestamp=1.0)
    
    # Frame 2: Quickly becomes circular
    frame2 = np.full((200, 200, 3), 255, dtype=np.uint8)
    cv2.circle(frame2, (100, 100), 20, (0, 255, 0), -1)
    
    # We need a few frames to build history if cvbot requires it
    # cvbot.py: if len(history) < 3: return "UNDETERMINED"
    tracker.process_frame(frame2, timestamp=1.1)
    results, _ = tracker.process_frame(frame2, timestamp=1.2)
    
    assert results[0].state == "CONTRACTED"
