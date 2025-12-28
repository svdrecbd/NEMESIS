# arduino_driver.py — Robust pyserial wrapper with auto-reconnect
import threading, queue, time
import serial
from typing import Optional

from app.core.logger import APP_LOGGER
from .controller_driver import ControllerDriver

DEFAULT_BAUD = 9600
DEFAULT_TIMEOUT_S = 0.0
RX_THREAD_JOIN_TIMEOUT_S = 1.0
CONNECTION_BACKOFF_START_S = 1.0
CONNECTION_BACKOFF_MAX_S = 10.0
CONNECTION_BACKOFF_MULTIPLIER = 2.0
READ_MIN_BYTES = 1
READ_IDLE_SLEEP_S = 0.005
WAIT_FOR_POLL_S = 0.01
DEFAULT_WAIT_FOR_TIMEOUT_S = 1.0
NEWLINE_BYTES = (10, 13)


class SerialLink(ControllerDriver):
    """
    Robust serial driver with automatic reconnection logic.
    """
    def __init__(self):
        self.ser: Optional[serial.Serial] = None
        self._rx_thread: Optional[threading.Thread] = None
        self._rx_queue = queue.Queue()
        self._stop_event = threading.Event()
        self._port: Optional[str] = None
        self._baudrate: int = DEFAULT_BAUD
        self._timeout: float = DEFAULT_TIMEOUT_S
        self._lock = threading.Lock()

    def open(self, port: str, baudrate: int = DEFAULT_BAUD, timeout: float = DEFAULT_TIMEOUT_S):
        if self.is_open() and self._port == port:
            return

        self.close() # Ensure clean state
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        
        self._stop_event.clear()
        self._rx_thread = threading.Thread(target=self._connection_loop, daemon=True, name=f"SerialLink-{port}")
        self._rx_thread.start()

    def is_open(self) -> bool:
        return bool(self.ser and self.ser.is_open)

    def close(self):
        self._stop_event.set()
        if self._rx_thread:
            if threading.current_thread() != self._rx_thread:
                self._rx_thread.join(timeout=RX_THREAD_JOIN_TIMEOUT_S)
            self._rx_thread = None
        
        self._close_internal()

    def _close_internal(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

    def _connection_loop(self):
        """Main loop that handles connection, reading, and reconnection."""
        backoff = CONNECTION_BACKOFF_START_S
        
        while not self._stop_event.is_set():
            # 1. Connect
            try:
                if not self.is_open():
                    APP_LOGGER.info(f"Connecting to {self._port}...")
                    self.ser = serial.Serial(port=self._port, baudrate=self._baudrate, timeout=self._timeout)
                    APP_LOGGER.info(f"Connected to {self._port}")
                    backoff = CONNECTION_BACKOFF_START_S
            except Exception as e:
                APP_LOGGER.warning(f"Connection failed to {self._port}: {e}. Retrying in {backoff}s")
                time.sleep(backoff)
                backoff = min(backoff * CONNECTION_BACKOFF_MULTIPLIER, CONNECTION_BACKOFF_MAX_S)
                continue

            # 2. Read Loop
            try:
                self._read_loop_inner()
            except (OSError, serial.SerialException) as e:
                APP_LOGGER.error(f"Serial connection lost: {e}")
                self._rx_queue.put((time.monotonic(), f"ERROR:DISCONNECTED:{e}"))
                self._close_internal()
            except Exception as e:
                APP_LOGGER.error(f"Unexpected serial error: {e}")
                self._close_internal()

    def _reader_loop(self):
        """Reader loop for tests or externally-injected serial handles."""
        try:
            self._read_loop_inner()
        except (OSError, serial.SerialException) as e:
            APP_LOGGER.error(f"Serial connection lost: {e}")
            self._rx_queue.put((time.monotonic(), f"ERROR:DISCONNECTED:{e}"))
            self._close_internal()
        except Exception as e:
            APP_LOGGER.error(f"Unexpected serial error: {e}")
            self._rx_queue.put((time.monotonic(), f"ERROR:DISCONNECTED:{e}"))
            self._close_internal()

    def _start_reader(self):
        """Start reader thread for an already-connected serial object (test helper)."""
        if self._rx_thread and self._rx_thread.is_alive():
            return
        self._stop_event.clear()
        self._rx_thread = threading.Thread(target=self._reader_loop, daemon=True, name="SerialLink-Reader")
        self._rx_thread.start()

    def _read_loop_inner(self):
        """Inner loop for reading bytes. raises Exception on disconnect."""
        buf = bytearray()
        while not self._stop_event.is_set() and self.ser and self.ser.is_open:
            try:
                # Read all available bytes to minimize system calls
                try:
                    waiting = int(getattr(self.ser, "in_waiting", 0) or 0)
                except Exception:
                    waiting = 0
                count = max(READ_MIN_BYTES, waiting)
                data = self.ser.read(count)
            except Exception:
                # If checking in_waiting fails, likely disconnected
                raise
            
            if not data:
                time.sleep(READ_IDLE_SLEEP_S)
                continue
                
            # Process chunk
            # Scan for newlines efficiently
            if b'\n' in data or b'\r' in data:
                # Iterate byte by byte for safety (simple state machine)
                # Optimization: Could use split() but byte-by-byte is robust for mixed \r\n
                for b in data:
                    if b in NEWLINE_BYTES:
                        if buf:
                            try:
                                line = bytes(buf).decode(errors='replace')
                                self._rx_queue.put((time.monotonic(), line))
                            finally:
                                buf.clear()
                    else:
                        buf.append(b)
            else:
                buf.extend(data)

    def send_char(self, ch: str) -> bool:
        return self.send_text(ch[:1])

    def send_text(self, text: str) -> bool:
        if not self.is_open():
            return False
        
        with self._lock:
            try:
                data = text.encode('ascii', errors='ignore')
                if not data:
                    return False
                self.ser.write(data)
                return True
            except Exception as e:
                APP_LOGGER.error(f"Write failed: {e}")
                self._rx_queue.put((time.monotonic(), f"ERROR:WRITE:{e}"))
                # Force a reconnect cycle
                self._close_internal() 
                return False

    def read_line_nowait(self, with_timestamp: bool = False):
        try:
            item = self._rx_queue.get_nowait()
        except queue.Empty:
            return None
            
        if with_timestamp:
            if isinstance(item, tuple):
                return item
            return (time.monotonic(), item)
            
        if isinstance(item, tuple):
            return item[1]
        return item

    def wait_for(self, substr: str, timeout_s: float = DEFAULT_WAIT_FOR_TIMEOUT_S) -> bool:
        deadline = time.monotonic() + max(0.0, timeout_s)
        while time.monotonic() < deadline:
            line = self.read_line_nowait()
            if line and substr in line:
                return True
            time.sleep(WAIT_FOR_POLL_S)
        return False
