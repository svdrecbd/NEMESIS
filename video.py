# video.py — capture + basic recorder using OpenCV VideoWriter
# Keeps preview and recording simple and cross‑platform.
# - VideoCapture: wraps OpenCV camera access
# - VideoRecorder: wraps OpenCV VideoWriter with MP4→AVI fallback

import cv2

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
    Simple MP4/MJPG recorder. Tries MP4V in .mp4; falls back to MJPG .avi if needed.
    Usage:
        rec = VideoRecorder("out.mp4", fps=30, frame_size=(1280,720))
        if rec.is_open():
            rec.write(frame_bgr)
            rec.close()
    """
    def __init__(self, path: str, fps: int = 30, frame_size=(1280, 720)):
        self.path = path
        self.fps = max(1, int(fps))
        self.frame_size = tuple(frame_size)
        self.writer = None
        self._open_writer()

    def _open_writer(self):
        # Try MP4 (mp4v) first
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        self.writer = cv2.VideoWriter(self.path, fourcc, self.fps, self.frame_size)
        if not self.writer.isOpened():
            # Fallback: MJPG in .avi (works widely without system codecs)
            alt_path = self.path.rsplit('.', 1)[0] + ".avi"
            self.path = alt_path
            fourcc = cv2.VideoWriter_fourcc(*'MJPG')
            self.writer = cv2.VideoWriter(self.path, fourcc, self.fps, self.frame_size)

    def is_open(self) -> bool:
        return self.writer is not None and self.writer.isOpened()

    def write(self, bgr_frame):
        if not self.is_open():
            return
        # Ensure size matches output
        h, w = bgr_frame.shape[:2]
        if (w, h) != self.frame_size:
            bgr_frame = cv2.resize(bgr_frame, self.frame_size)
        self.writer.write(bgr_frame)

    def close(self):
        if self.writer:
            self.writer.release()
            self.writer = None