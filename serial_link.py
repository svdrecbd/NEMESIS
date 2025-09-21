# serial_link.py — Minimal pyserial wrapper with echo helpers
import threading, queue, time
import serial

class SerialLink:
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
                b = self.ser.read(1) if self.ser else b''
                if not b:
                    time.sleep(0.005); continue
                if b in (b'\n', b'\r'):
                    if buf:
                        try:
                            self._rx_queue.put(bytes(buf).decode(errors='replace'))
                        finally:
                            buf.clear()
                else:
                    buf.extend(b)
            except Exception:
                time.sleep(0.05)

    def is_open(self) -> bool:
        return bool(self.ser and self.ser.is_open)

    def close(self):
        self._stop.set()
        if self._rx_thread:
            self._rx_thread.join(timeout=0.5)
            self._rx_thread = None
        if self.ser:
            try:
                self.ser.close()
            finally:
                self.ser = None

    def send_char(self, ch: str):
        if not self.is_open():
            return
        data = ch.encode('ascii', errors='ignore')[:1]
        try:
            self.ser.write(data)
        except Exception:
            pass

    def read_line_nowait(self):
        try:
            return self._rx_queue.get_nowait()
        except queue.Empty:
            return None

    def wait_for(self, substr: str, timeout_s: float = 1.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout_s)
        while time.monotonic() < deadline:
            line = self.read_line_nowait()
            if line and substr in line:
                return True
            time.sleep(0.01)
        return False
