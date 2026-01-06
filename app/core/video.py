# video.py — capture + basic recorder using OpenCV VideoWriter
# Keeps preview and recording simple and cross‑platform.
# - VideoCapture: wraps OpenCV camera access
# - VideoRecorder: wraps OpenCV VideoWriter with MP4→AVI fallback

import cv2
import threading
import queue
from pathlib import Path
from app.core.logger import APP_LOGGER

DEFAULT_CAMERA_FPS = 30
DEFAULT_FRAME_SIZE = (1280, 720)
DEFAULT_RECORDER_FPS = 30
RECORDER_BUFFER_SECONDS = 2.0
RECORDER_JOIN_TIMEOUT_S = 2.0
RECORDER_QUEUE_POLL_TIMEOUT_S = 0.1

class VideoCapture:
    def __init__(self, index=0):
        self.index = index
        self.cap = None

    def open(self) -> bool:
        self.cap = cv2.VideoCapture(self.index)
        # Best-effort defaults (tweak if your camera requires other sizes)
        self.cap.set(cv2.CAP_PROP_FPS, DEFAULT_CAMERA_FPS)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, DEFAULT_FRAME_SIZE[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, DEFAULT_FRAME_SIZE[1])
        return self.cap.isOpened()

    def read(self):
        if not self.cap:
            return False, None
        return self.cap.read()

    def release(self):
        if self.cap:
            self.cap.release()
            self.cap = None

    def get_fps(self):
        if not self.cap:
            return None
        return self.cap.get(cv2.CAP_PROP_FPS)

    def get_size(self):
        if not self.cap:
            return (0, 0)
        w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        return (w, h)


class VideoRecorder:
    """
    Threaded MP4/MJPG recorder. Writes frames in a background thread to
    ensure the main application/preview never stutters due to disk I/O.
    """
    def __init__(self, path: str, fps: int = DEFAULT_RECORDER_FPS, frame_size=DEFAULT_FRAME_SIZE):
        self._path = path
        self.fps = max(1, int(fps))
        self.frame_size = tuple(frame_size)
        self.writer = None
        
        # Buffer up to ~RECORDER_BUFFER_SECONDS seconds of video to absorb disk latency
        queue_max = max(1, int(round(self.fps * RECORDER_BUFFER_SECONDS)))
        self._queue = queue.Queue(maxsize=queue_max)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        
        self.total_frames = 0
        self.dropped_frames = 0
        
        self._open_writer()
        self._thread.start()

    def _open_writer(self):
        # Try MP4 (mp4v) first
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        self.writer = cv2.VideoWriter(self._path, fourcc, self.fps, self.frame_size)
        if not self.writer.isOpened():
            # Fallback: MJPG in .avi (works widely without system codecs)
            alt_path = self._path.rsplit('.', 1)[0] + ".avi"
            self._path = alt_path
            fourcc = cv2.VideoWriter_fourcc(*'MJPG')
            self.writer = cv2.VideoWriter(self._path, fourcc, self.fps, self.frame_size)

    @property
    def path(self) -> str:
        """Final output path (after any codec fallback)."""
        return self._path

    def relocate(self, new_path: str) -> bool:
        """Move the active recording file and update the tracked path."""
        try:
            src = Path(self._path)
            dest = Path(new_path)
            if not src.exists():
                return False
            try:
                if src.resolve() == dest.resolve():
                    return True
            except Exception:
                if src == dest:
                    return True
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                if src.stat().st_dev != dest.parent.stat().st_dev:
                    APP_LOGGER.error("Recording move blocked: source and target are on different devices.")
                    return False
            except Exception:
                return False
            src.replace(dest)
            self._path = str(dest)
            return True
        except Exception as exc:
            APP_LOGGER.error(f"Failed to relocate recording to {new_path}: {exc}")
            return False

    def is_open(self) -> bool:
        return self.writer is not None and self.writer.isOpened()

    def _worker(self):
        """Background loop to process resize and write operations."""
        while True:
            try:
                # Wait for a frame, but check stop_event periodically
                frame = self._queue.get(timeout=RECORDER_QUEUE_POLL_TIMEOUT_S)
            except queue.Empty:
                if self._stop_event.is_set():
                    break
                continue

            if frame is None: # Explicit sentinel to stop
                break

            if self.writer:
                try:
                    # Offload the resize cost to this thread too
                    h, w = frame.shape[:2]
                    if (w, h) != self.frame_size:
                        frame = cv2.resize(frame, self.frame_size)
                    self.writer.write(frame)
                except Exception as e:
                    APP_LOGGER.error(f"Error writing video frame in VideoRecorder worker: {e}") 
            
            self._queue.task_done()

    def write(self, bgr_frame):
        if not self.is_open():
            return
        # Non-blocking put. If buffer fills (disk stalled), drop frame
        # to protect the live UI/preview responsiveness.
        self.total_frames += 1
        try:
            self._queue.put_nowait(bgr_frame)
        except queue.Full:
            self.dropped_frames += 1 

    def close(self):
        self._stop_event.set()
        # Signal worker to drain/stop
        try:
            self._queue.put(None)
        except queue.Full:
            pass # If full, worker will eventually see stop_event
            
        if self._thread.is_alive():
            self._thread.join(timeout=RECORDER_JOIN_TIMEOUT_S)
            
        if self.writer:
            self.writer.release()
            self.writer = None
