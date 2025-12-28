# shared_mem.py — Safe wrapper for SharedMemory ring buffers
import multiprocessing.shared_memory
import numpy as np
import time
from dataclasses import dataclass
from typing import Tuple, Optional
from app.core.logger import APP_LOGGER

@dataclass
class SharedBufferLayout:
    """Metadata for the shared buffer."""
    name: str
    shape: Tuple[int, int, int]
    dtype: str
    size_bytes: int

class SharedMemoryManager:
    """
    Manages a shared memory block for video frames.
    
    Architecture:
    - We allocate ONE large block of memory.
    - We wrap it as a NumPy array.
    - 'Writer' (Camera) writes to it.
    - 'Reader' (CV) reads from it.
    
    Safety:
    - SharedMemory persists until explicitly unlinked. 
    - We use a 'resource tracker' pattern to ensure cleanup on crash/exit.
    """
    def __init__(self, name: str, shape: Tuple[int, int, int], dtype=np.uint8, create: bool = False):
        self.name = name
        self.shape = shape
        self.dtype = np.dtype(dtype)
        self.size_bytes = int(np.prod(shape) * self.dtype.itemsize)
        self.shm = None
        self.array = None
        self._is_creator = create

        try:
            if create:
                # Cleanup potentially stale memory from previous run
                try:
                    stm = multiprocessing.shared_memory.SharedMemory(name=self.name, create=False)
                    stm.unlink()
                except FileNotFoundError:
                    pass
                
                self.shm = multiprocessing.shared_memory.SharedMemory(name=self.name, create=True, size=self.size_bytes)
            else:
                # Connect to existing
                self.shm = multiprocessing.shared_memory.SharedMemory(name=self.name, create=False)
            
            # Create numpy view into buffer
            self.array = np.ndarray(self.shape, dtype=self.dtype, buffer=self.shm.buf)
            
        except Exception as e:
            APP_LOGGER.error(f"SharedMemory Init Error ({name}): {e}")
            self.cleanup()
            raise

    def cleanup(self):
        """Release resources. Creator also unlinks (deletes) the memory."""
        if self.array is not None:
            del self.array
            self.array = None
            
        if self.shm is not None:
            try:
                self.shm.close()
                if self._is_creator:
                    self.shm.unlink()
            except Exception:
                pass
            self.shm = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
