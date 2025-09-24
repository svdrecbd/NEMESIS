# NEMESIS Onboarding

**NEMESIS** — *Non‑periodic Event Monitoring & Evaluation of Stimulus‑Induced States*  
Version: **1.0‑rc1**

This document gets a new contributor from zero → productive. It summarizes the system, how to run it, how the data flow works, and what’s left to ship v1.0.

---

## 1) What this is

A desktop acquisition app that:
- Shows a live USB‑microscope preview (“photo‑booth” style)
- Adapts preview aspect to the camera (4:3/16:9/16:10) and hides the idle border once the first frame arrives
- Drives an Arduino‑controlled stepper “tapper” with **Periodic** or **Poisson** schedules
- Records MP4 video independently of tapping (can be on/off at any time)
- Logs **every tap** to CSV (v1.0 schema) and captures **run.json** snapshot for traceability
- Produces publishable plots from CSV via `plotter.py`

The UI is intentionally **technical & dense** (think Bloomberg/radare2), with a **Pro Mode** for keyboard‑first operation. Typestar OCR is the global font; a minimal dark palette keeps focus on data.
The main window opens with the preview column taking roughly 75 % of the width. A custom splitter snaps to 25 % / 50 % / 75 % anchors and briefly highlights the handle when you land on a magnet so it’s easy to hit repeatable layouts without pixel hunting.

---

## 2) Repo quick tour

```
assets/
  fonts/Typestar OCR Regular.otf
  images/logo.png
app.py            # Main Qt app (PySide6) – v1.0‑rc1
video.py          # Camera preview + MP4 recording (OpenCV)
scheduler.py      # Periodic & Poisson (seedable) tap scheduler
serial_link.py    # Arduino serial (non‑blocking writes)
logger.py         # CSV v1.0 logging + run summaries
plotter.py        # Matplotlib plotting template for rasters & responses
configio.py       # Save/Load config (~/.nemesis/config.json)
runs/             # (gitignored) per-run outputs: run_YYYYMMDD_HHMMSS_<token>/
recordings/       # (gitignored) ad‑hoc recordings when no run active
README.md, .gitignore, requirements.txt
assets/           # Fonts and images (Typestar, logo)
```

---

## 3) Install & run

**Python**: 3.10–3.11 recommended.

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

**Dependencies (pinned):**
- PySide6, OpenCV (opencv‑python), pyserial, numpy, matplotlib

> On Windows/macOS you may need camera/mic permissions. On Linux, ensure your user is in the `video` group; for serial access, add to `dialout` or set proper udev rules.

---

## 4) Hardware hookup (high level)

- USB microscope → host laptop (shows up as a camera in OpenCV).
- Arduino + Big Easy Driver → stepper tapper.
- One USB cable for camera, one for Arduino.
- The Arduino firmware handles: step **enable/disable**, **microstep level (1..5)**, **manual tap**, and two timed modes (Periodic / Poisson).

> NEMESIS doesn’t replace your firmware logic; it **controls** it (serial chars), schedules taps, manages video, and **logs** everything.

---

## 5) Daily workflow

1. **Open NEMESIS.**
2. **Connect serial** (enter COM port or /dev/tty path → “Connect Serial”).  
   - Tap power (“stepsize”) is 1..5; change via dropdown or Pro keys `1..5`.
3. **Open camera** (select index, hit “Open Camera”). Preview appears.
   - The preview container shows a subtle box while idle; as soon as the first frame arrives the border hides and the image goes edge‑to‑edge.
   - The container adapts to the camera aspect; closing the camera restores a 16:9 placeholder.
   - Drag the vertical splitter to resize the preview vs. control panes; it snaps at 25 % / 50 % / 75 % and briefly highlights the handle when you’re on a target.
4. (Optional) **Start recording** (video is independent of runs; can be toggled live).
5. Choose mode **Periodic** (seconds) or **Poisson** (taps/min); set parameters.  
   - Optional **seed** for reproducible Poisson sequences.
6. **Start Run**.  
   - A folder `runs/run_YYYYMMDD_HHMMSS_<token>/` is created with:
     - `run.json` – parameters & environment snapshot
     - `taps.csv` – one row per tap (see schema below)
     - `video.mp4` – if recording was ON at any time
7. **Stop Run** when finished. Use `plotter.py` to generate rasters/plots.

### Pro Mode (keyboard-first)
Toggle **Pro Mode**. Keys:
- `Space` tap, `S` start/stop run, `R` start/stop recording,
- `C` connect/disconnect serial, `V` open/close camera,
- `E` enable motor, `D` disable motor, `Raise/Lower Arm` buttons nudge in half‑steps,
- `1..5` set stepsize; `[`/`]` tweak Periodic; `{`/`}` tweak Poisson.

The top status line updates ~2×/s with:  
`run_id • cam/fps • REC • serial • mode/param • taps • elapsed • rate`

---

## 6) Data model

### CSV v1.0 (`taps.csv`)
Columns:
- `run_id` – timestamped slug with a random suffix (`run_YYYYMMDD_HHMMSS_<token>`, `<token>` = 6 hex chars from UUID4) for this run
- `tap_id` – incremental counter starting at 1
- `tap_uuid` – unique identifier per tap
- `t_host_ms` – host monotonic time (ms) at send
- `mode` – "Periodic" | "Poisson"
- `stepsize` – 1..5 (tap power/microstep profile)
- `mark` – "scheduled" | "manual"
- `notes` – freeform (reserved)
- `recording_path` – path to MP4 if known when row written

### `run.json`
Snapshot of parameters captured at **Start Run**:
- `run_id`, `started_at` timestamp, `app_version`, `firmware_commit` placeholder
- camera index, serial port, current recording path (if any)
- mode selection with `period_sec` or `lambda_rpm`, seed, stepsize
- scheduler descriptor mirroring the active settings

---

## 7) Current progress (rc1)

- ✅ UI with Typestar OCR, dark palette, NEMESIS logo
- ✅ Live camera preview; start/stop recording (independent of runs)
- ✅ Preview box hides after first frame; container matches camera aspect
- ✅ Periodic & Poisson (seedable); dense, technical status line
- ✅ Pro Mode keyboard controls
- ✅ Stepsize control wired to firmware + logged per tap
- ✅ CSV v1.0 logging end‑to‑end; updates `recording_path` mid‑run
- ✅ Save/Load config (`~/.nemesis/config.json`)
- ✅ Run snapshot (`run.json`) in each run directory
- ✅ Version stamp `1.0‑rc1`
- ✅ Live raster chart embedded under the preview (0–70 min)
- ✅ Dark combobox popups, fixed control widths, left/right splitter to eliminate layout tug
- ✅ App‑wide pinch zoom + two‑finger browsing; auto‑hiding slim scrollbars

---

## 8) Roadmap to v1.0

### Must‑ship
1. **Reliability guards**
   - Block *Start Run* if serial disconnected (with “Override anyway” option).
   - Block *Start Recording* if camera closed.
   - Soft disk‑space warning if free space < **1 GB**.
2. **Auto‑recording + countdown**
   - Toggle: “Auto‑start recording when run starts.” (3‑sec overlay countdown; cancel with `Esc`).
3. **FPS / drop monitor in status line**
   - Display `fps:N (drop:x%)` from capture & write timing.
4. **Minimal crash logging**
   - `runs/<run_id>/app.log` with key events and exception traces.
5. **Packaging**
   - PyInstaller specs for Win/macOS/Linux; bundle font & logo.
   - Smoke test script and short `RUNNING.md` (permissions & driver notes).
6. **Docs polish**
   - README: Quick Start, Keyboard Map, CSV schema v1.0, Known Issues.
   - Bump `VERSION` → `1.0.0`, tag release.

### Nice‑to‑have (post‑1.0 or if time permits)
7. **Configured OpenCV Bot (baseline)**
   - `cvbot/` with `config.yaml`, ROI picker, `Analyze Run` button.
   - Output: `analysis.json` + QC image; runs offline after acquisition.
8. **Arduino handshake**
   - On connect: firmware string/version + echo test; show in status line.
9. **Template export**
   - Export current config as `nemesis_config_<date>.json` for sharing.

---

## 9) How to contribute

- Create a feature branch; follow the pinned versions in `requirements.txt`.
- Keep UI changes conservative; favor text density over new widgets.
- Preserve **CSV schema v1.0**. If you must change it, bump to v1.1 and update `plotter.py` and docs together.
- Add brief docstrings and log key actions (start/stop run/recording, serial connect).

---

## 10) Troubleshooting

- **No camera in list** – Try index 0..4. On Windows, check Privacy → Camera allowed. On macOS, grant camera permissions for your terminal/IDE. On Linux, ensure user is in `video` group.
- **Serial won’t open** – Confirm port name (e.g., `COM5`, `/dev/ttyUSB0`/`/dev/ttyACM0`), close the Arduino IDE serial monitor.
- **Recording fails to start** – Codec missing; OpenCV build mismatch. Reinstall `opencv-python` wheels; try a different FourCC if you customized `video.py`.
- **Font not applied** – Verify `assets/fonts/Typestar OCR Regular.otf` exists; check console for font load message.
- **Preview border shows during live feed** – By design, the border hides automatically once the first frame arrives. If you keep a visible border during live video on HiDPI displays, use a 2px stroke to avoid sub‑pixel seams.

---

## 11) Short checklist for a dev day

- [ ] `python app.py` launches; status line alive.
- [ ] Serial connects; stepsize `1..5` reaches Arduino.
- [ ] Camera preview visible; recording toggles ON/OFF.
- [ ] Start Run → `runs/run_*/{run.json,taps.csv}` created; taps appear in CSV.
- [ ] Plotter renders raster from CSV without edits.

---

Happy hacking. Ship it. 🚀
