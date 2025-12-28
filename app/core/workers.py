# app/core/workers.py
import threading
import time
import multiprocessing
import queue
import os
import shiboken6
import numpy as np
from typing import Optional
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage, QPainter

from app.core import video
from app.core.logger import APP_LOGGER
from app.core.shared_mem import SharedMemoryManager
from app.core.cvbot import run_cv_process

DEFAULT_FRAME_INTERVAL_MS = 33
MIN_FRAME_INTERVAL_S = 0.005
DEFAULT_BUFFER_COUNT = 3
RENDER_QUEUE_MAX = 2
QUEUE_POLL_TIMEOUT_S = 0.1
THREAD_JOIN_TIMEOUT_S = 0.2
STOP_JOIN_SLICE_S = 0.1
MS_PER_SEC = 1000.0
BYTES_PER_MB = 1024 * 1024

class RenderWorker(QObject):
    """
    Off-thread rendering worker. 
    Composes the camera frame and the CV overlay into a final QImage.
    """
    imageReady = Signal(object, int) # QImage, frame_idx

    def __init__(self):
        super().__init__()
        self._queue = queue.Queue(maxsize=RENDER_QUEUE_MAX) # Backpressure if UI is slow
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._render_loop, name="RenderWorker", daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=THREAD_JOIN_TIMEOUT_S)
            self._thread = None

    def submit_frame(self, frame_bgr: np.ndarray, mask: Optional[np.ndarray], frame_idx: int):
        if not self._running:
            return
        try:
            # Drop old frames if queue is full (Render skipping)
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
            self._queue.put_nowait((frame_bgr, mask, frame_idx))
        except queue.Full:
            pass

    def _render_loop(self):
        while self._running:
            try:
                # Wait for next frame task
                task = self._queue.get(timeout=QUEUE_POLL_TIMEOUT_S)
                bgr, mask, idx = task
                
                # 1. Create Base QImage (Zero copy if possible from buffer)
                # Note: QImage references the buffer. 
                # BGR buffer comes from SharedMemory or VideoCapture. 
                # If it's from SHM, it's stable until overwritten (Seqlock protects read, but this is Render).
                # To be safe against Producer overwriting while we render, we might need a copy.
                # However, FrameWorker emits a 'frame' object. If it's the SHM view, we need a copy.
                # If it's a fresh buffer from Capture, it might be safe.
                # Let's assume input 'bgr' is safe to read for now (it's usually a numpy array).
                
                h, w, ch = bgr.shape
                bytes_per_line = ch * w
                
                # Make a deep copy to QImage.Format_BGR888 to ensure we own the memory for painting
                # converting to RGB888 might be needed for some QPainter operations, but BGR is usually fine.
                # Actually, QPainter on BGR888 works fine.
                
                # We need to copy because we are going to modify it (overlay) or just to detach from source.
                # QImage(data, ...) creates a view. .copy() creates a deep copy.
                base_img = QImage(bgr.data, w, h, bytes_per_line, QImage.Format_BGR888).copy()
                
                # 2. Draw Overlay
                if mask is not None:
                    try:
                        painter = QPainter(base_img)
                        # Tint the mask red and draw it
                        # This is the expensive part (blending)
                        
                        # Optimization: 
                        # If mask is binary, we can use it as a stencil?
                        # Or convert to QImage and draw.
                        
                        mh, mw = mask.shape
                        if mh == h and mw == w:
                            # Create Mask QImage (Grayscale)
                            mask_img = QImage(mask.data, mw, mh, mw, QImage.Format_Grayscale8)
                            
                            # We want to draw red where mask is white.
                            # Method: Set clip region? Or composition mode.
                            # Simpler: Draw the mask image with a Colorize effect? 
                            # QPainter doesn't have simple "colorize".
                            
                            # Alternative: Use the mask as an Alpha Channel for a solid Red image.
                            # But creating that is also work.
                            
                            # Fallback to the previous logic but off-thread:
                            # Just drawing the grayscale mask with opacity is useful for debugging.
                            # Or we can treat it as an alpha map.
                            
                            painter.setCompositionMode(QPainter.CompositionMode_Screen)
                            # Draw mask as a whitish overlay
                            painter.drawImage(0, 0, mask_img)
                            
                        painter.end()
                    except Exception as e:
                        APP_LOGGER.error(f"Render Error: {e}")

                # 3. Emit Result
                if shiboken6.isValid(self):
                    self.imageReady.emit(base_img, idx)

            except queue.Empty:
                continue
            except Exception as e:
                APP_LOGGER.error(f"Render Worker Fatal: {e}")

class FrameWorker(QObject):
    frameReady = Signal(object, int, float)
    cvTaskReady = Signal(int, float, int) # frame_idx, timestamp, buffer_idx
    shmReady = Signal(str, object, str, object, object, object) # name, shape, mask_name, mask_shape, slot_generations, semaphore
    error = Signal(str)
    stopped = Signal()

    def __init__(self, capture: video.VideoCapture, interval_ms: int = DEFAULT_FRAME_INTERVAL_MS):
        super().__init__()
        self._capture = capture
        self._interval_s = max(MIN_FRAME_INTERVAL_S, float(interval_ms) / MS_PER_SEC)
        self._running = False
        self._thread: threading.Thread | None = None
        self._frame_idx = 0
        self.shm_manager: Optional[SharedMemoryManager] = None
        self.mask_shm_manager: Optional[SharedMemoryManager] = None
        self.shm_name = f"nemesis_video_shm_{os.getpid()}"
        self.mask_shm_name = f"nemesis_mask_shm_{os.getpid()}"
        self.BUFFER_COUNT = DEFAULT_BUFFER_COUNT
        # Semaphore to track free slots. Init to BUFFER_COUNT.
        self._sem = multiprocessing.Semaphore(self.BUFFER_COUNT)
        # Seqlock generation counter (Shared Array)
        # We use 'i' (signed int) to store frame_idx
        self._slot_generations = multiprocessing.Array('i', self.BUFFER_COUNT)

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

        try:
            # 1. Read first frame to determine size
            try:
                ok, frame = self._capture.read()
            except Exception as exc:
                self._emit_safe(self.error, f"Camera error: {exc}")
                return

            if not ok or frame is None:
                self._emit_safe(self.error, "Camera returned empty initial frame")
                return

            # 2. Setup Shared Memory (Ring Buffer)
            # Shape: (BUFFER_COUNT, Height, Width, Channels)
            h, w, c = frame.shape
            shm_shape = (self.BUFFER_COUNT, h, w, c)
            mask_shape = (self.BUFFER_COUNT, h, w) # Single channel for mask

            try:
                self.shm_manager = SharedMemoryManager(self.shm_name, shm_shape, dtype=frame.dtype, create=True)
                self.mask_shm_manager = SharedMemoryManager(self.mask_shm_name, mask_shape, dtype=np.uint8, create=True)

                APP_LOGGER.info(
                    "Shared Memory created: "
                    f"{self.shm_manager.size_bytes / BYTES_PER_MB:.2f}MB + "
                    f"{self.mask_shm_manager.size_bytes / BYTES_PER_MB:.2f}MB Mask"
                )
                # Pass the semaphore to the consumer so it can release slots
                self._emit_safe(
                    self.shmReady,
                    self.shm_name,
                    shm_shape,
                    self.mask_shm_name,
                    mask_shape,
                    self._slot_generations,
                    self._sem,
                )
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

                    # Attempt to acquire a slot (Non-blocking)
                    if self._sem.acquire(block=False):
                        # Calculate Ring Buffer Index
                        buf_idx = self._frame_idx % self.BUFFER_COUNT

                        # Copy raw BGR to Shared Memory slot
                        try:
                            self.shm_manager.array[buf_idx][:] = frame[:]

                            # Update generation for Seqlock (Consumer checks this)
                            self._slot_generations[buf_idx] = self._frame_idx

                            # Emit CV task (lightweight metadata)
                            # The consumer MUST release the semaphore when done
                            self._emit_safe(self.cvTaskReady, self._frame_idx, ts, buf_idx)
                        except Exception as e:
                            APP_LOGGER.error(f"SHM Write Error: {e}")
                            self._sem.release() # Release if write failed
                    else:
                        # Buffer Full! Drop this frame for CV, but still show in UI
                        pass

                    # Emit UI update (Raw BGR - UI will handle format)
                    # Note: UI gets every frame regardless of CV load
                    self._emit_safe(self.frameReady, frame, self._frame_idx, ts)

                if interval > 0:
                    next_tick += interval
                    sleep_for = next_tick - time.perf_counter()
                    if sleep_for > 0:
                        time.sleep(sleep_for)
                    else:
                        next_tick = time.perf_counter()

        finally:
            # Cleanup
            if self.shm_manager:
                self.shm_manager.cleanup()
                self.shm_manager = None
            if self.mask_shm_manager:
                self.mask_shm_manager.cleanup()
                self.mask_shm_manager = None

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
            thread.join(timeout=min(STOP_JOIN_SLICE_S, remaining))
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
    resultsReady = Signal(object, int, float, object) # results, frame_idx, timestamp, mask (numpy array)
    error = Signal(str)
    
    def __init__(self):
        super().__init__()
        self._process = None
        self._input_queue = multiprocessing.Queue()
        self._output_queue = multiprocessing.Queue()
        self._stop_event = multiprocessing.Event()
        
        self._result_thread: Optional[threading.Thread] = None
        self._result_running = False
        
        self._shm_name = ""
        self._shm_shape = (0,0,0)
        self._mask_shm_name = ""
        self._mask_shm_shape = (0,0,0)
        self.mask_shm_manager: Optional[SharedMemoryManager] = None
        self._slot_generations = None
        self._sem: Optional[multiprocessing.Semaphore] = None

    def start_processing(self, shm_name: str, shm_shape: tuple[int, ...], mask_name: str, mask_shape: tuple[int, ...], slot_generations, semaphore):
        if self._process is not None and self._process.is_alive():
            return
            
        self._shm_name = shm_name
        self._shm_shape = shm_shape
        self._mask_shm_name = mask_name
        self._mask_shm_shape = mask_shape
        self._slot_generations = slot_generations
        self._sem = semaphore
        self._stop_event.clear()
        
        # Connect to Mask SHM for reading
        try:
            self.mask_shm_manager = SharedMemoryManager(mask_name, mask_shape, dtype=np.uint8, create=False)
        except Exception as e:
            self.error.emit(f"Failed to attach to mask SHM: {e}")
            return

        # Drain queues
        while not self._input_queue.empty(): self._input_queue.get()
        while not self._output_queue.empty(): self._output_queue.get()
        
        self._process = multiprocessing.Process(
            target=run_cv_process,
            args=(shm_name, shm_shape, mask_name, mask_shape, self._input_queue, self._output_queue, self._stop_event, slot_generations, semaphore),
            daemon=True
        )
        self._process.start()
        
        # Start Result Poller Thread (replacing QTimer)
        self._result_running = True
        self._result_thread = threading.Thread(target=self._result_loop, name="CVResultPoller", daemon=True)
        self._result_thread.start()

    def stop_processing(self):
        self._result_running = False
        self._stop_event.set()
        # Send sentinel
        self._input_queue.put(None)
        
        if self._process:
            self._process.join(timeout=THREAD_JOIN_TIMEOUT_S)
            if self._process.is_alive():
                self._process.terminate()
            self._process = None
        
        if self._result_thread:
            # Wake up thread if stuck on get()
            # We can't interrupt get() easily without a timeout or sentinel in output queue
            # But the process might be dead. 
            # We rely on daemon thread or short timeout in get()
            self._result_thread.join(timeout=THREAD_JOIN_TIMEOUT_S)
            self._result_thread = None
            
        if self.mask_shm_manager:
            self.mask_shm_manager.cleanup()
            self.mask_shm_manager = None
            
        self._sem = None

    def process_frame(self, frame_idx, timestamp, buf_idx):
        """
        Signal that a new frame is ready in Shared Memory.
        We don't send the frame itself, just the index/timestamp/buffer_index.
        """
        if self._process and self._process.is_alive():
            try:
                self._input_queue.put_nowait((frame_idx, timestamp, buf_idx))
            except Exception:
                # Queue full, release semaphore immediately since we won't process it
                if self._sem:
                    self._sem.release()
        else:
            # Not running, release semaphore
            if self._sem:
                self._sem.release()

    def _result_loop(self):
        """Threaded loop to poll results efficiently."""
        while self._result_running:
            try:
                # Blocking get with timeout allows checking _result_running
                res = self._output_queue.get(timeout=QUEUE_POLL_TIMEOUT_S)
                
                if res:
                    # Check if it's a log message
                    if isinstance(res, tuple) and res[0] == "LOG":
                         level, msg = res[1], res[2]
                         if level == "ERROR":
                             # Emit safely to UI thread
                             if shiboken6.isValid(self):
                                 self.error.emit(f"CV Process: {msg}")
                         continue
                         
                    # Normal result
                    # (results, frame_idx, timestamp, buf_idx)
                    results, frame_idx, timestamp, buf_idx = res
                    
                    # Read Mask from SHM (Copy it for UI safety)
                    mask = None
                    if self.mask_shm_manager and buf_idx is not None:
                        try:
                            # Copy from SHM to local memory
                            mask = self.mask_shm_manager.array[buf_idx].copy()
                        except Exception:
                            pass
                    
                    if shiboken6.isValid(self):
                        self.resultsReady.emit(results, frame_idx, timestamp, mask)
                        
                    # CRITICAL: Release the semaphore slot now that we are done reading/copying
                    if self._sem:
                        try:
                            self._sem.release()
                        except ValueError:
                            pass # Already released or boundary error
                            
            except queue.Empty:
                continue
            except Exception: 
                break
