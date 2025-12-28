# app/core/workers.py
import threading
import time
import multiprocessing
import queue
import os
import shiboken6
from typing import Optional
from PySide6.QtCore import QObject, Signal, Slot, QTimer

from app.core import video
from app.core.logger import APP_LOGGER
from app.core.shared_mem import SharedMemoryManager
from app.core.cvbot import run_cv_process

class FrameWorker(QObject):
    frameReady = Signal(object, int, float)
    shmReady = Signal(str, object) # name, shape
    error = Signal(str)
    stopped = Signal()

    def __init__(self, capture: video.VideoCapture, interval_ms: int = 33):
        super().__init__()
        self._capture = capture
        self._interval_s = max(0.005, float(interval_ms) / 1000.0)
        self._running = False
        self._thread: threading.Thread | None = None
        self._frame_idx = 0
        self.shm_manager: Optional[SharedMemoryManager] = None
        self.shm_name = f"nemesis_video_shm_{os.getpid()}"

    def _emit_safe(self, signal, *args):
        if not shiboken6.isValid(self):
            return
        try:
            signal.emit(*args)
        except RuntimeError:
            pass

    def _loop(self):
        interval = self._interval_s
        next_tick = time.perf_counter()
        
        # 1. Read first frame to determine size
        try:
            ok, frame = self._capture.read()
        except Exception as exc:
            self._emit_safe(self.error, f"Camera error: {exc}")
            return

        if not ok or frame is None:
             self._emit_safe(self.error, "Camera returned empty initial frame")
             return

        # 2. Setup Shared Memory
        h, w, c = frame.shape
        try:
            self.shm_manager = SharedMemoryManager(self.shm_name, (h, w, c), dtype=frame.dtype, create=True)
            APP_LOGGER.info(f"Shared Memory created: {self.shm_name} {self.shm_manager.size_bytes/1024/1024:.2f}MB")
            self._emit_safe(self.shmReady, self.shm_name, (h, w, c))
        except Exception as e:
            self._emit_safe(self.error, f"SharedMemory Error: {e}")
            return

        while self._running:
            try:
                ok, frame = self._capture.read()
            except Exception as exc:
                self._emit_safe(self.error, f"Camera error: {exc}")
                break
            
            ts = time.monotonic()
            if ok and frame is not None:
                self._frame_idx += 1
                
                # Copy to Shared Memory (Fast memcpy)
                try:
                    self.shm_manager.array[:] = frame[:]
                except Exception as e:
                    APP_LOGGER.error(f"SHM Write Error: {e}")

                self._emit_safe(self.frameReady, frame, self._frame_idx, ts)
            
            if interval > 0:
                next_tick += interval
                sleep_for = next_tick - time.perf_counter()
                if sleep_for > 0:
                    time.sleep(sleep_for)
                else:
                    next_tick = time.perf_counter()
        
        # Cleanup
        if self.shm_manager:
            self.shm_manager.cleanup()
            self.shm_manager = None
            
        self._running = False
        self._thread = None
        self._emit_safe(self.stopped)

    @Slot()
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="FrameWorkerLoop", daemon=True)
        self._thread.start()

    @Slot()
    def stop(self, wait_timeout: float = 1.0) -> bool:
        thread = self._thread
        if thread is None:
            self._running = False
            self._thread = None
            return True
        self._running = False
        if threading.current_thread() is thread:
            return False
        deadline = time.perf_counter() + max(0.0, wait_timeout)
        while thread.is_alive():
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break
            thread.join(timeout=min(0.1, remaining))
        if thread.is_alive():
            return False
        self._thread = None
        return True

    def is_alive(self) -> bool:
        thread = self._thread
        return bool(thread and thread.is_alive())


class ProcessCVWorker(QObject):
    """
    Manages the background multiprocessing CV worker.
    Replaces the old threaded CVWorker.
    """
    resultsReady = Signal(object, int, float, object) # results, frame_idx, timestamp, mask (None)
    
    def __init__(self):
        super().__init__()
        self._process = None
        self._input_queue = multiprocessing.Queue()
        self._output_queue = multiprocessing.Queue()
        self._stop_event = multiprocessing.Event()
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll_results)
        self._shm_name = ""
        self._shm_shape = (0,0,0)

    def start_processing(self, shm_name: str, shm_shape: tuple[int, int, int]):
        if self._process is not None and self._process.is_alive():
            return
            
        self._shm_name = shm_name
        self._shm_shape = shm_shape
        self._stop_event.clear()
        
        # Drain queues
        while not self._input_queue.empty(): self._input_queue.get()
        while not self._output_queue.empty(): self._output_queue.get()
        
        self._process = multiprocessing.Process(
            target=run_cv_process,
            args=(shm_name, shm_shape, self._input_queue, self._output_queue, self._stop_event),
            daemon=True
        )
        self._process.start()
        self._poll_timer.start(10) # Poll every 10ms (UI thread)

    def stop_processing(self):
        self._poll_timer.stop()
        self._stop_event.set()
        # Send sentinel
        self._input_queue.put(None)
        
        if self._process:
            self._process.join(timeout=0.2)
            if self._process.is_alive():
                self._process.terminate()
            self._process = None

    def process_frame(self, frame_idx, timestamp):
        """
        Signal that a new frame is ready in Shared Memory.
        We don't send the frame itself, just the index/timestamp.
        """
        if self._process and self._process.is_alive():
            try:
                self._input_queue.put_nowait((frame_idx, timestamp))
            except Exception:
                pass # Queue full, drop frame (backpressure)

    def _poll_results(self):
        # Read all available results
        while True:
            try:
                res = self._output_queue.get_nowait()
                if res:
                    results, frame_idx, timestamp = res
                    # Pass None for mask since we don't send it over SHM yet
                    self.resultsReady.emit(results, frame_idx, timestamp, None)
            except Exception: # Empty
                break
