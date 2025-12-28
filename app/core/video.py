# video.py — capture + basic recorder using OpenCV VideoWriter
# Keeps preview and recording simple and cross‑platform.
# - VideoCapture: wraps OpenCV camera access
# - VideoRecorder: wraps OpenCV VideoWriter with MP4→AVI fallback

import cv2
import threading
import queue
from app.core.logger import APP_LOGGER

class VideoCapture:
    def __init__(self, index=0):
        self.index = index
        self.cap = None

    def open(self) -> bool:
        self.cap = cv2.VideoCapture(self.index)
        # Best-effort defaults (tweak if your camera requires other sizes)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
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
    def __init__(self, path: str, fps: int = 30, frame_size=(1280, 720)):
        self._path = path
        self.fps = max(1, int(fps))
        self.frame_size = tuple(frame_size)
        self.writer = None
        
        # Buffer up to ~2 seconds of video (at 30fps) to absorb disk latency
        self._queue = queue.Queue(maxsize=60)
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

    def is_open(self) -> bool:
        return self.writer is not None and self.writer.isOpened()

    def _worker(self):
        """Background loop to process resize and write operations."""
        while True:
            try:
                # Wait for a frame, but check stop_event periodically
                frame = self._queue.get(timeout=0.1)
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
            self._thread.join(timeout=2.0)
            
        if self.writer:
            self.writer.release()
            self.writer = None
