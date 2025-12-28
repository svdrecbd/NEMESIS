import time
from unittest.mock import MagicMock
from app.drivers.arduino_driver import SerialLink

def test_serial_link_reading():
    link = SerialLink()
    mock_ser = MagicMock()
    
    # Simulate reading "HELLO\n"
    mock_ser.read.side_effect = [b'H', b'E', b'L', b'L', b'O', b'\n', b'']
    mock_ser.is_open = True
    
    link.ser = mock_ser
    link._start_reader()
    
    # Give it a moment to process
    time.sleep(0.1)
    
    line = link.read_line_nowait()
    assert line == "HELLO"
    
    link.close()

def test_serial_link_error_handling():
    link = SerialLink()
    mock_ser = MagicMock()
    mock_ser.read.side_effect = Exception("Hardware disconnected")
    mock_ser.is_open = True
    
    link.ser = mock_ser
    link._start_reader()
    
    time.sleep(0.1)
    
    line = link.read_line_nowait()
    assert "ERROR:DISCONNECTED" in line
    
    link.close()

def test_serial_link_wait_for():
    link = SerialLink()
    mock_ser = MagicMock()
    mock_ser.read.side_effect = [b'O', b'K', b'\n', b'']
    mock_ser.is_open = True
    
    link.ser = mock_ser
    link._start_reader()
    
    assert link.wait_for("OK", timeout_s=0.5) is True
    assert link.wait_for("FAIL", timeout_s=0.1) is False
    
    link.close()
