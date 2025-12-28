import pytest
import multiprocessing
from app.core.shared_mem import SharedMemoryManager

def test_shared_memory_creation_and_access():
    shape = (100, 100, 3)
    name = "test_shm_block"

    # 1. Creator
    try:
        shm_write_ctx = SharedMemoryManager(name, shape, create=True)
    except PermissionError:
        pytest.skip("SharedMemory not permitted in this environment")
    with shm_write_ctx as shm_write:
        assert shm_write.array is not None
        assert shm_write.array.shape == shape
        
        # Write some data
        shm_write.array.fill(128)
        shm_write.array[0, 0, 0] = 255
        
        # 2. Reader (simulating another process, though here in same process for simplicity)
        # In same process, SharedMemory name conflict might occur if we don't manage it carefully,
        # but SharedMemoryManager allows connecting to existing by name.
        with SharedMemoryManager(name, shape, create=False) as shm_read:
            assert shm_read.array is not None
            # Verify data
            assert shm_read.array[0, 0, 0] == 255
            assert shm_read.array[50, 50, 1] == 128
            
            # Verify it is indeed the same memory
            shm_read.array[1, 1, 1] = 42
            assert shm_write.array[1, 1, 1] == 42

def test_shared_memory_cleanup():
    shape = (50, 50)
    name = "test_shm_cleanup"

    try:
        shm = SharedMemoryManager(name, shape, create=True)
    except PermissionError:
        pytest.skip("SharedMemory not permitted in this environment")
    shm.cleanup()
    
    # Try to connect - should fail if unlinked
    # Note: On some OSs, unlinking happens immediately, on others when refcount -> 0.
    # Python's SharedMemory implementation usually unlinks immediately if unlink() is called.
    with pytest.raises(FileNotFoundError):
        multiprocessing.shared_memory.SharedMemory(name=name, create=False)
