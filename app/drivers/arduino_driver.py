# arduino_driver.py — Minimal pyserial wrapper with echo helpers
import threading, queue, time
import serial

from .controller_driver import ControllerDriver


class SerialLink(ControllerDriver):
    def __init__(self):
        self.ser = None
        self._rx_thread = None
        self._rx_queue = queue.Queue()
        self._stop = threading.Event()

    def open(self, port: str, baudrate: int = 9600, timeout: float = 0.0):
        if self.ser and self.ser.is_open:
            return
        self.ser = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
        self._start_reader()

    def _start_reader(self):
        self._stop.clear()
        self._rx_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._rx_thread.start()

    def _read_loop(self):
        buf = bytearray()
        while not self._stop.is_set():
            try:
                # ser.read can raise OSError/SerialException if unplugged
                b = self.ser.read(1) if self.ser else b''
                if not b:
                    time.sleep(0.005); continue
                if b in (b'\n', b'\r'):
                    if buf:
                        try:
                            line = bytes(buf).decode(errors='replace')
                            self._rx_queue.put((time.monotonic(), line))
                        finally:
                            buf.clear()
                else:
                    buf.extend(b)
            except Exception as e:
                # Report error and stop reading to avoid spinning
                self._rx_queue.put((time.monotonic(), f"ERROR:Serial read failed: {e}"))
                break

    def is_open(self) -> bool:
        return bool(self.ser and self.ser.is_open)

    def close(self):
        self._stop.set()
        if self._rx_thread:
            self._rx_thread.join(timeout=0.5)
            self._rx_thread = None
        if self.ser:
            self.ser.close()
            self.ser = None

    def send_char(self, ch: str) -> bool:
        return self.send_text(ch[:1])

    def send_text(self, text: str) -> bool:
        if not self.is_open():
            return False
        data = text.encode('ascii', errors='ignore')
        if not data:
            return False
        try:
            self.ser.write(data)
            return True
        except Exception as e:
            # If write fails, likely disconnected.
            self._rx_queue.put((time.monotonic(), f"ERROR:Serial write failed: {e}"))
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

    def wait_for(self, substr: str, timeout_s: float = 1.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout_s)
        while time.monotonic() < deadline:
            line = self.read_line_nowait()
            if line and substr in line:
                return True
            time.sleep(0.01)
        return False
