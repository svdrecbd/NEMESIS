import numpy as np
import os
from app.core.video import VideoRecorder

def test_video_recorder_init(tmp_path):
    video_path = str(tmp_path / "test.mp4")
    recorder = VideoRecorder(video_path, fps=30, frame_size=(640, 480))
    
    assert recorder.is_open()
    # Check if file was created (might be .mp4 or .avi depending on codec)
    final_path = recorder.path
    assert os.path.exists(final_path)
    
    # Write a dummy frame
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    recorder.write(frame)
    
    recorder.close()
    assert not recorder.is_open()

def test_video_recorder_resize(tmp_path):
    video_path = str(tmp_path / "test_resize.mp4")
    # Set recorder to 640x480
    recorder = VideoRecorder(video_path, fps=30, frame_size=(640, 480))
    
    # Write a frame of wrong size (100x100)
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    recorder.write(frame)
    
    recorder.close()
    assert recorder.total_frames == 1
    assert recorder.dropped_frames == 0
