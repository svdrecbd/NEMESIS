# app.py — NEMESIS UI (v1.0-rc1, unified feature set)
import sys, os, time, json
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QFileDialog,
    QHBoxLayout, QVBoxLayout, QComboBox, QSpinBox, QDoubleSpinBox,
    QLineEdit, QMessageBox
)
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QPixmap, QFontDatabase, QFont, QIcon

# Internal modules
import video
import scheduler
import serial_link
import logger as runlogger
import configio

# ---- Assets & Version ----
FONT_PATH = "assets/fonts/Typestar OCR Regular.otf"
LOGO_PATH = "assets/images/logo.png"
APP_VERSION = "1.0-rc1"

# ---- Theme (dark, information-dense) ----
BG     = "#0d0f12"
MID    = "#161a1f"
TEXT   = "#b8c0cc"
SUBTXT = "#8a93a3"
ACCENT = "#5aa3ff"
DANGER = "#e33"

APP_STYLESHEET = f"""
* {{ background: {BG}; color: {TEXT}; font-size: 11pt; }}
QWidget {{ background: {BG}; }}
QLabel#StatusLine {{ color: {TEXT}; font-size: 10pt; }}
QPushButton {{ background: {MID}; border:1px solid #252a31; padding:6px 10px; border-radius:6px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:checked {{ background:#1f2731; border-color:{ACCENT}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background:{MID}; border:1px solid #252a31; padding:4px 6px; border-radius:6px; }}
"""

def _apply_global_font(app: QApplication):
    """Load Typestar OCR and apply as app default if present."""
    fid = QFontDatabase.addApplicationFont(FONT_PATH)
    if fid != -1:
        fams = QFontDatabase.applicationFontFamilies(fid)
        if fams:
            app.setFont(QFont(fams[0], 11))


class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"NEMESIS {APP_VERSION} — Non-periodic Event Monitoring & Evaluation of Stimulus-Induced States")
        if os.path.exists(LOGO_PATH):
            self.setWindowIcon(QIcon(LOGO_PATH))
        self.resize(1260, 800)

        # ---------- Top dense status line ----------
        self.statusline = QLabel("—")
        self.statusline.setObjectName("StatusLine")
        self.statusline.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # ---------- Video preview ----------
        self.video_label = QLabel("Video preview")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("border:1px solid #333;")

        # ---------- Serial controls ----------
        self.port_edit = QLineEdit(); self.port_edit.setPlaceholderText("COM3 or /dev/ttyUSB0")
        self.serial_btn = QPushButton("Connect Serial")
        self.enable_btn = QPushButton("Enable Motor")
        self.disable_btn = QPushButton("Disable Motor")
        self.tap_btn = QPushButton("Manual Tap")

        # ---------- Camera controls ----------
        self.cam_index = QSpinBox(); self.cam_index.setRange(0, 8); self.cam_index.setValue(0)
        self.cam_btn = QPushButton("Open Camera")

        # ---------- Recording controls (independent) ----------
        self.rec_start_btn = QPushButton("Start Recording")
        self.rec_stop_btn  = QPushButton("Stop Recording")
        self.rec_indicator = QLabel("● REC OFF")

        # ---------- Scheduler controls ----------
        self.mode = QComboBox(); self.mode.addItems(["Periodic", "Poisson"])
        self.period_sec = QDoubleSpinBox(); self.period_sec.setRange(0.1, 3600.0); self.period_sec.setValue(10.0); self.period_sec.setSuffix(" s")
        self.lambda_rpm = QDoubleSpinBox(); self.lambda_rpm.setRange(0.1, 600.0); self.lambda_rpm.setValue(6.0); self.lambda_rpm.setSuffix(" taps/min")

        # Stepsize (1..5) — sent to firmware, logged per-tap
        self.stepsize = QComboBox(); self.stepsize.addItems(["1","2","3","4","5"]); self.stepsize.setCurrentText("4")
        self.stepsize.currentTextChanged.connect(self._on_stepsize_changed)

        # Poisson RNG seed (optional)
        self.seed_edit = QLineEdit(); self.seed_edit.setPlaceholderText("Seed (optional integer)")

        # Run controls
        self.run_start_btn = QPushButton("Start Run")
        self.run_stop_btn  = QPushButton("Stop Run")

        # Output directory
        self.outdir_edit = QLineEdit()
        self.outdir_btn  = QPushButton("Choose Output Dir")

        # Config Save/Load
        self.save_cfg_btn = QPushButton("Save Config")
        self.load_cfg_btn = QPushButton("Load Last Config")

        # Pro Mode (keyboard-first interaction)
        self.pro_btn = QPushButton("Pro Mode: OFF")
        self.pro_btn.setCheckable(True)
        self.pro_btn.toggled.connect(self._toggle_pro_mode)
        self.pro_mode = False

        # Secondary status
        self.status   = QLabel("Idle.")
        self.counters = QLabel("Taps: 0 | Elapsed: 0.0 s | Observed rate: 0.0 /min")

        # ---------- Layout ----------
        left = QVBoxLayout(); left.addWidget(self.video_label, 1)
        right = QVBoxLayout()
        right.addWidget(self.statusline)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Serial:")); r1.addWidget(self.port_edit,1); r1.addWidget(self.serial_btn); r1.addWidget(self.pro_btn)
        right.addLayout(r1)

        r1b = QHBoxLayout(); r1b.addWidget(self.enable_btn); r1b.addWidget(self.disable_btn); r1b.addWidget(self.tap_btn); right.addLayout(r1b)

        r2 = QHBoxLayout(); r2.addWidget(QLabel("Camera idx:")); r2.addWidget(self.cam_index); r2.addWidget(self.cam_btn); right.addLayout(r2)

        r2b = QHBoxLayout(); r2b.addWidget(self.rec_start_btn); r2b.addWidget(self.rec_stop_btn); r2b.addWidget(self.rec_indicator); right.addLayout(r2b)

        r3 = QHBoxLayout()
        r3.addWidget(QLabel("Mode:")); r3.addWidget(self.mode)
        r3.addWidget(QLabel("Period:")); r3.addWidget(self.period_sec)
        r3.addWidget(QLabel("λ (taps/min):")); r3.addWidget(self.lambda_rpm)
        r3.addWidget(QLabel("Stepsize:")); r3.addWidget(self.stepsize)
        right.addLayout(r3)

        r3b = QHBoxLayout(); r3b.addWidget(QLabel("Seed:")); r3b.addWidget(self.seed_edit,1); right.addLayout(r3b)

        r4 = QHBoxLayout(); r4.addWidget(self.run_start_btn); r4.addWidget(self.run_stop_btn); right.addLayout(r4)

        r5 = QHBoxLayout(); r5.addWidget(QLabel("Output dir:")); r5.addWidget(self.outdir_edit,1); r5.addWidget(self.outdir_btn); right.addLayout(r5)

        right.addWidget(self.counters); right.addWidget(self.status)

        root = QHBoxLayout(self); root.addLayout(left, 2); root.addLayout(right, 1)

        # ---------- State ----------
        self.cap = None
        self.recorder = None
        self.frame_timer = QTimer(self); self.frame_timer.timeout.connect(self._grab_frame)
        self.run_timer   = QTimer(self); self.run_timer.setSingleShot(True); self.run_timer.timeout.connect(self._on_tap_due)
        self.scheduler = scheduler.TapScheduler()
        self.serial    = serial_link.SerialLink()
        self.logger    = None
        self.run_dir   = None
        self.run_start = None
        self.taps = 0; self.preview_fps = 30; self.current_stepsize = 4

        # Dense status line updater
        self.status_timer = QTimer(self); self.status_timer.timeout.connect(self._refresh_statusline); self.status_timer.start(400)

        # ---------- Signals ----------
        self.cam_btn.clicked.connect(self._open_camera)
        self.serial_btn.clicked.connect(self._toggle_serial)
        self.enable_btn.clicked.connect(lambda: self.serial.send_char('e'))
        self.disable_btn.clicked.connect(lambda: self.serial.send_char('d'))
        self.tap_btn.clicked.connect(self._manual_tap)
        self.rec_start_btn.clicked.connect(self._start_recording)
        self.rec_stop_btn.clicked.connect(self._stop_recording)
        self.run_start_btn.clicked.connect(self._start_run)
        self.run_stop_btn.clicked.connect(self._stop_run)
        self.outdir_btn.clicked.connect(self._choose_outdir)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.save_cfg_btn.clicked.connect(self._save_config_clicked)
        self.load_cfg_btn.clicked.connect(self._load_config_clicked)

        self._mode_changed(); self._update_status("Ready.")

    # ---------- Pro Mode ----------
    def _toggle_pro_mode(self, on: bool):
        self.pro_mode = on
        self.pro_btn.setText(f"Pro Mode: {'ON' if on else 'OFF'}")
        # Hide some buttons to reduce visual noise in Pro
        for w in [self.enable_btn, self.disable_btn, self.outdir_btn]:
            w.setVisible(not on)

    def keyPressEvent(self, event):
        if not self.pro_mode:
            return super().keyPressEvent(event)
        key = event.key()
        if key == Qt.Key_Space: self._send_tap("manual"); return
        if key == Qt.Key_R: self._stop_recording() if self.recorder else self._start_recording(); return
        if key == Qt.Key_S: self._start_run() if self.logger is None else self._stop_run(); return
        if key == Qt.Key_E: self.serial.send_char('e'); return
        if key == Qt.Key_D: self.serial.send_char('d'); return
        if key in (Qt.Key_1, Qt.Key_2, Qt.Key_3, Qt.Key_4, Qt.Key_5):
            val = int(chr(key)); self._apply_stepsize(val); return
        if key == Qt.Key_C: self._toggle_serial(); return
        if key == Qt.Key_V: self._open_camera(); return
        if key == Qt.Key_BracketLeft and self.mode.currentText()=="Periodic":
            self.period_sec.setValue(max(0.1, self.period_sec.value()-0.5)); return
        if key == Qt.Key_BracketRight and self.mode.currentText()=="Periodic":
            self.period_sec.setValue(self.period_sec.value()+0.5); return
        if key == Qt.Key_BraceLeft and self.mode.currentText()=="Poisson":
            self.lambda_rpm.setValue(max(0.1, self.lambda_rpm.value()-0.5)); return
        if key == Qt.Key_BraceRight and self.mode.currentText()=="Poisson":
            self.lambda_rpm.setValue(self.lambda_rpm.value()+0.5); return
        return super().keyPressEvent(event)

    # ---------- Stepsize ----------
    def _on_stepsize_changed(self, text: str):
        try:
            val = int(text)
        except Exception:
            return
        self._apply_stepsize(val)

    def _apply_stepsize(self, val: int):
        val = max(1, min(val, 5))
        self.current_stepsize = val
        self.stepsize.blockSignals(True)
        self.stepsize.setCurrentText(str(val))
        self.stepsize.blockSignals(False)
        # Send '1'..'5' to firmware; Arduino code already maps this to microstepping profile
        self.serial.send_char(str(val))

    # ---------- Camera ----------
    def _open_camera(self):
        idx = self.cam_index.value()
        if self.cap is None:
            self.cap = video.VideoCapture(idx)
            if not self.cap.open():
                self._update_status("Failed to open camera."); self.cap = None; return
            self.preview_fps = int(self.cap.get_fps() or 30)
            self.frame_timer.start(int(1000 / max(1, self.preview_fps)))
            self.cam_btn.setText("Close Camera"); self._update_status(f"Camera {idx} open. Preview live.")
        else:
            self._stop_recording()
            self.frame_timer.stop(); self.cap.release(); self.cap = None
            self.cam_btn.setText("Open Camera"); self._update_status("Camera closed.")

    # ---------- Serial ----------
    def _toggle_serial(self):
        if not self.serial.is_open():
            port = self.port_edit.text().strip()
            if not port: self._update_status("Enter a serial port first."); return
            try:
                self.serial.open(port, baudrate=9600, timeout=0)
                self.serial_btn.setText("Disconnect Serial"); self._update_status(f"Serial connected on {port}.")
            except Exception as e:
                self._update_status(f"Serial error: {e}")
        else:
            self.serial.close(); self.serial_btn.setText("Connect Serial"); self._update_status("Serial disconnected.")

    # ---------- Output dir ----------
    def _choose_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "Choose output directory")
        if d: self.outdir_edit.setText(d)

    # ---------- Recording ----------
    def _start_recording(self):
        if self.cap is None:
            QMessageBox.warning(self, "No Camera", "Open a camera before starting recording."); return
        if self.recorder is not None:
            QMessageBox.information(self, "Recording", "Already recording."); return
        outdir = self.outdir_edit.text().strip() or os.getcwd()
        Path(outdir).mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        rec_dir = self.run_dir if self.run_dir is not None else Path(outdir)/f"recording_{ts}"
        rec_dir.mkdir(parents=True, exist_ok=True)
        w, h = self.cap.get_size()
        video_path = rec_dir / "video.mp4"
        self.recorder = video.VideoRecorder(str(video_path), fps=self.preview_fps, frame_size=(w, h))
        if not self.recorder.is_open():
            self.recorder = None; QMessageBox.warning(self, "Recorder", "Failed to start MP4 recorder."); return
        # If a run is already active, inject path into logger for subsequent rows
        if self.logger:
            self.logger.set_recording_path(str(video_path))
        self.rec_indicator.setText("● REC ON"); self.rec_indicator.setStyleSheet(f"color:{DANGER}; font-weight:bold;")
        self._update_status(f"Recording → {video_path}")

    def _stop_recording(self):
        if self.recorder:
            self.recorder.close(); self.recorder = None
            self.rec_indicator.setText("● REC OFF"); self.rec_indicator.setStyleSheet(f"color:{SUBTXT};")
            self._update_status("Recording stopped.")

    # ---------- Config Save/Load ----------
    def _current_config(self) -> dict:
        return {
            "mode": self.mode.currentText(),
            "period_sec": self.period_sec.value(),
            "lambda_rpm": self.lambda_rpm.value(),
            "stepsize": self.current_stepsize,
            "camera_index": self.cam_index.value(),
            "serial_port": self.port_edit.text().strip(),
            "seed": self._seed_value_or_none(),
            "output_dir": self.outdir_edit.text().strip(),
            "app_version": APP_VERSION,
        }

    def _apply_config(self, cfg: dict):
        try:
            self.mode.setCurrentIndex(0 if cfg.get("mode","Periodic")=="Periodic" else 1)
            self.period_sec.setValue(float(cfg.get("period_sec", 10.0)))
            self.lambda_rpm.setValue(float(cfg.get("lambda_rpm", 6.0)))
            self._apply_stepsize(int(cfg.get("stepsize", 4)))
            self.cam_index.setValue(int(cfg.get("camera_index", 0)))
            self.port_edit.setText(cfg.get("serial_port", ""))
            seed = cfg.get("seed", None)
            self.seed_edit.setText("" if seed in (None, "") else str(seed))
            outdir = cfg.get("output_dir", "")
            if outdir: self.outdir_edit.setText(outdir)
        except Exception as e:
            QMessageBox.warning(self, "Config", f"Failed to apply config: {e}")

    def _save_config_clicked(self):
        try:
            configio.save_config(self._current_config())
            self._update_status("Config saved.")
        except Exception as e:
            QMessageBox.warning(self, "Save Config", f"Failed to save: {e}")

    def _load_config_clicked(self):
        cfg = configio.load_config()
        if not cfg:
            QMessageBox.information(self, "Load Config", "No saved config found."); return
        self._apply_config(cfg); self._update_status("Config loaded.")

    def _seed_value_or_none(self):
        txt = self.seed_edit.text().strip()
        if txt == "": return None
        try: return int(txt)
        except Exception: return None

    # ---------- Scheduler / Run ----------
    def _mode_changed(self):
        is_periodic = (self.mode.currentText() == "Periodic")
        self.period_sec.setEnabled(is_periodic); self.lambda_rpm.setEnabled(not is_periodic)

    def _start_run(self):
        if self.recorder is None:
            resp = QMessageBox.question(self, "No Recording Active",
                "You're starting a run without recording video. Continue anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if resp == QMessageBox.No: return
        outdir = self.outdir_edit.text().strip() or os.getcwd()
        ts = time.strftime("%Y%m%d_%H%M%S")
        self.run_dir = Path(outdir) / f"run_{ts}"; self.run_dir.mkdir(parents=True, exist_ok=True)
        rec_path = getattr(self.recorder, "path", "") if self.recorder else ""
        self.logger = runlogger.RunLogger(self.run_dir, recording_path=rec_path)
        self.run_start = time.monotonic(); self.taps = 0

        # Seed & scheduler config
        seed = self._seed_value_or_none()
        self.scheduler.set_seed(seed)
        if self.mode.currentText()=="Periodic":
            self.scheduler.configure_periodic(self.period_sec.value())
        else:
            self.scheduler.configure_poisson(self.lambda_rpm.value())

        # Snapshot run.json
        run_json = {
            "run_id": self.logger.run_id,
            "started_at": ts,
            "app_version": APP_VERSION,
            "firmware_commit": "",  # optional
            "camera_index": self.cam_index.value(),
            "recording_path": rec_path,
            "serial_port": self.port_edit.text().strip(),
            "mode": self.mode.currentText(),
            "period_sec": self.period_sec.value(),
            "lambda_rpm": self.lambda_rpm.value(),
            "seed": seed,
            "stepsize": self.current_stepsize,
            "scheduler": self.scheduler.descriptor(),
        }
        try:
            with open(self.run_dir/"run.json", "w", encoding="utf-8") as f:
                json.dump(run_json, f, indent=2)
        except Exception as e:
            self._update_status(f"Failed to write run.json: {e}")

        delay = self.scheduler.next_delay_s()
        self.run_timer.start(int(delay*1000)); self._update_status(f"Run started → next tap in {delay:.3f}s")

    def _stop_run(self):
        self.run_timer.stop()
        if self.logger: self.logger.close(); self.logger = None
        self.run_dir = None; self.run_start = None
        self._update_status("Run stopped.")

    def _manual_tap(self): self._send_tap("manual")

    def _on_tap_due(self):
        self._send_tap("scheduled")
        delay = self.scheduler.next_delay_s()
        self.run_timer.start(int(delay*1000)); self._update_status(f"Tap sent. Next in {delay:.3f}s")

    def _send_tap(self, mark="scheduled"):
        t_host = time.monotonic(); self.serial.send_char('t')
        self.taps += 1
        elapsed = t_host - (self.run_start or t_host)
        rate = (self.taps/elapsed*60.0) if elapsed>0 else 0.0
        self.counters.setText(f"Taps: {self.taps} | Elapsed: {elapsed:.1f} s | Observed rate: {rate:.2f} /min")
        if self.logger:
            self.logger.log_tap(host_time_s=t_host, mode=self.mode.currentText(), mark=mark, stepsize=self.current_stepsize)

    # ---------- Frame loop ----------
    def _grab_frame(self):
        if self.cap is None: return
        ok, frame = self.cap.read()
        if not ok: return
        overlay = frame.copy()
        try:
            import cv2
            text = f"T+{(time.monotonic()-(self.run_start or time.monotonic())):8.3f}s" if self.run_start else "Preview"
            cv2.putText(overlay, text, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2, cv2.LINE_AA)
        except Exception:
            pass
        h, w = overlay.shape[:2]
        qimg = QImage(overlay.data, w, h, 3*w, QImage.Format_BGR888)
        self.video_label.setPixmap(QPixmap.fromImage(qimg).scaled(self.video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        if self.recorder: self.recorder.write(overlay)

    # ---------- Status line refresh ----------
    def _refresh_statusline(self):
        run_id = self.logger.run_id if self.logger else "-"
        cam_idx = self.cam_index.value()
        fps = int(self.preview_fps or 0)
        rec = "REC ON" if self.recorder else "REC OFF"
        port = self.port_edit.text().strip() if self.serial.is_open() else "—"
        serial_state = f"serial:{port}" if self.serial.is_open() else "serial:DISCONNECTED"
        mode = self.mode.currentText()
        param = f"P={self.period_sec.value():.2f}s" if mode=="Periodic" else f"λ={self.lambda_rpm.value():.2f}/min"
        taps = self.taps
        elapsed = (time.monotonic() - self.run_start) if self.run_start else 0.0
        rate = (taps/elapsed*60.0) if elapsed>0 else 0.0
        txt = f"{run_id}  •  cam {cam_idx}/{fps}fps  •  {rec}  •  {serial_state}  •  {mode} {param}  •  taps:{taps}  •  t+{elapsed:6.1f}s  •  rate:{rate:5.2f}/min"
        self.statusline.setText(txt)

    def _update_status(self, msg): self.status.setText(msg)


def main():
    app = QApplication(sys.argv)
    _apply_global_font(app)
    app.setStyleSheet(APP_STYLESHEET)
    w = App(); w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
