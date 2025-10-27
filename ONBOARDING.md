# NEMESIS Onboarding

**NEMESIS** — *Non‑periodic Event Monitoring & Evaluation of Stimulus‑Induced States*  
Version: **1.0-preview**

This document gets a new contributor from zero → productive. It summarizes the system, how to run it, how the data flow works, and what’s left to ship v1.0.


## 1) What this is

A desktop acquisition app that:
- Shows a live USB-microscope preview (“photo-booth” style)
- Adapts preview aspect to the camera (4:3/16:9/16:10) and hides the idle border once the first frame arrives
- Drives an Arduino-controlled stepper “tapper” with **Periodic** or **Poisson** schedules
- Records MP4 video independently of tapping (can be on/off at any time)
- Logs **every tap** to CSV (v1.0 schema) and captures **run.json** snapshot for traceability
- Produces publishable plots from CSV via `app/core/plotter.py`
- Anchors each tap to both host UTC and firmware clock and records the preview/recorded frame indices so video and telemetry stay aligned.
- Manages acquisition sessions inside a tabbed workspace with per-tab hardware locking, rename-on-double-click, hover-only close controls, and keyboard shortcuts for tab creation/teardown.

### Current architecture snapshot
- The first tab is a `RunTab`; `+ Tab` (or Cmd/Ctrl+T) opens a chooser to spawn another Run or Data tab. Cmd/Ctrl+W closes the active tab, but the last remaining tab stays pinned.
- Each run tab owns a `RunSession` that wraps camera capture, serial transport, logging, and preview widgets so hardware never leaks across tabs.
- Camera indices and serial ports are claimed per tab; attempts to reuse a claimed resource raise a friendly warning instead of stealing the device.
- Data tabs surface the dashboard view for browsing historical runs, exporting artifacts, and clearing recordings without disturbing live sessions.
- Theme toggles now propagate across run and data tabs; control panels, dashboards, and preview frames stay in sync in Light/Dark modes.
- The tab bar is left-aligned to match the control stack; close icons appear on hover, and tab width is padded (~30%) to support double-click rename.
- Layout minimums are anchored so the control column never disappears; overflow uses scroll areas rather than letting widgets clip.
- App-wide zoom honours Cmd/Ctrl+=/-/0; trackpad pinch is temporarily disabled while we rebuild bounded zoom.

The UI is intentionally **technical & dense** (think Bloomberg/radare2), with a **Pro Mode** for keyboard-first operation. Typestar OCR is the global font; the default loads in **Light Mode** with controls on the **left** and data on the right (75 % of the width). A custom splitter snaps to 25 % / 50 % / 75 % anchors and briefly highlights the handle when you land on a magnet so it’s easy to hit repeatable layouts without pixel hunting.

---

## 2) Repo quick tour

```
run.py                     # Entry point (python run.py)
app/
  main.py                 # Qt application shell (run/data tabs)
  core/                  # state, IO, scheduler, logging
  drivers/               # hardware adapters
  ui/                    # drop .ui/.qss assets as needed
assets/
  fonts/Typestar OCR Regular.otf
  images/transparent_logo.png
firmware/
  arduino/stentor_habituator_stepper_v9/NEMESIS_Firmware.ino
  unit1/UNIT1_firmware/...
docs/
requirements.txt
runs/, recordings/ (gitignored outputs)
```

---

## 3) Install & run

**Python**: 3.10–3.11 recommended.

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
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

1. **Open NEMESIS.** The app launches into a run tab with the tab bar aligned above the control stack.
   - Use `+ Tab` or Cmd/Ctrl+T to open another tab; choose **Run Tab** for live acquisition or **Data Tab** for analysis/history.
   - Double-click a tab title to rename it. Cmd/Ctrl+W closes the active tab only when more than one tab exists; the last tab stays pinned.
   - Navigate tabs with Cmd+Opt+Arrow (macOS) or Ctrl+Alt+Arrow (Windows/Linux). Close icons stay hidden until you hover them, reducing accidental exits.
2. **Connect serial.** Use the combo box above the serial section; pick a detected port or type one manually, then click **Connect Serial**.
   - Tabs coordinate serial ports automatically; if another tab already owns a port you’ll see an “in use” warning instead of stealing the device.
   - Tap power (“stepsize”) is 1..5; change via dropdown or Pro keys `1..5`.
3. **Open camera** (select index, hit “Open Camera”). Preview appears.
   - Camera indices are claimed per tab; trying to reuse one prompts a warning.
   - The preview container shows a subtle box while idle; as soon as the first frame arrives the border hides and the image goes edge-to-edge.
   - The container adapts to the camera aspect; closing the camera freezes the last frame in-place so layout stays stable and the slider remains usable.
   - Drag the vertical splitter to resize the preview vs. control panes; it snaps at 25 % / 50 % / 75 % and briefly highlights the handle when you’re on a target.
4. (Optional) **Start recording** (video is independent of runs; can be toggled live).
5. Choose mode **Periodic** (seconds) or **Poisson** (taps/min); set parameters.  
   - Optional **seed** for reproducible Poisson sequences.
6. *(Optional troubleshooting)* **Flash Hardware Config**. Sends the current settings to the board so you can flip the physical switch and observe motion without logging taps. Status will read “Config flashed for testing…” until you start a run.
7. **Start Run** when you want to record data.  
   - The app resends the configuration, enables logging, and creates `runs/run_YYYYMMDD_HHMMSS_<token>/` with:
      - `run.json` – parameters & environment snapshot
      - `taps.csv` – one row per tap (see schema below)
      - `video.mp4` – if recording was ON at any time
8. **Stop Run** (or flip the physical switch off) when finished. Use `app/core/plotter.py` or open a Data Tab to browse rasters, export CSVs, or delete artifacts. The app records the observed timing drift and saves a per-port calibration to `~/.nemesis/calibration.json`; future periodic runs automatically apply that factor so multi-hour sessions stay aligned with wall-clock seconds. **If the drift still exceeds 1 s/hour, treat as P0—see Reliable Timing section below.**

> Still prefer the pre-NEMESIS serial console? Run `python tools/arduino_wrapper.py --port <your_port>`
> to get the legacy single-character workflow inside the repo. The wrapper sends digits + newline
> so firmware prompts behave exactly like before.
 
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
- `t_host_iso` – ISO8601 UTC timestamp (wall clock) when the host logged the tap
- `t_fw_ms` – firmware-reported execute time (ms) so you can compare host vs controller
- `mode` – "Periodic" | "Poisson"
- `stepsize` – 1..5 (tap power/microstep profile)
- `mark` – "scheduled" | "manual"
- `notes` – freeform (reserved)
- `frame_preview_idx` – preview frame counter at the time of the tap
- `frame_recorded_idx` – recorded frame index (if recording active)
- `recording_path` – path to MP4 if known when row written

### `run.json`
Snapshot of parameters captured at **Start Run**:
- `run_id`, `started_at` timestamp, `app_version`, `firmware_commit` placeholder
- camera index, serial port, current recording path (if any)
- mode selection with `period_sec` or `lambda_rpm`, seed, stepsize
- scheduler descriptor mirroring the active settings

---

## 7) Current feature set (1.0 preview)

- ✅ Tabbed workspace with run/data tabs, rename-on-double-click, hover-only close icons, Cmd/Ctrl+T to add and Cmd/Ctrl+W to close (with last-tab guard).
- ✅ Each run tab owns an isolated `RunSession`; camera and serial hardware are locked per tab and surfaced via friendly warnings.
- ✅ Dashboard data tabs for browsing, exporting, deleting runs without interrupting live acquisitions.
- ✅ Light/Dark themes stay consistent across run controls, dashboard panels, and preview/chart surfaces.
- ✅ Live camera preview; start/stop recording independent of runs.
- ✅ Preview container adapts to camera aspect, hides the idle border after first frame, and preserves freeze-frame sizing when the camera closes.
- ✅ Periodic & Poisson schedulers (seedable) with the dense status line and timing telemetry.
- ✅ Pro Mode keyboard controls and hover tooltips for parity.
- ✅ Stepsize control wired to firmware + logged per tap.
- ✅ CSV v1.0 logging end-to-end; updates `recording_path` mid-run.
- ✅ Save/Load config (`~/.nemesis/config.json`) per workstation.
- ✅ Run snapshot (`run.json`) in each run directory.
- ✅ Version stamp `1.0-preview`.
- ✅ Live raster chart embedded under the preview (timeline auto-grows and switches to hours after 2 h).
- ✅ Minimum window anchor & scroll areas keep controls reachable on smaller displays.
- ✅ App-wide zoom via keyboard shortcuts (Cmd/Ctrl+=/-/0) with trackpad pinch temporarily disabled.

---

## 8) Roadmap to v1.0

### Must-ship
1. **Reliability guards**
   - Block *Start Run* if serial disconnected (with “Override anyway” option).
   - Block *Start Recording* if camera closed.
   - Soft disk-space warning if free space < **1 GB**.
2. **Auto-recording + countdown**
   - Toggle: “Auto-start recording when run starts.” (3-sec overlay countdown; cancel with `Esc`).
3. **FPS / drop monitor in status line**
   - Display `fps:N (drop:x%)` from capture & write timing.
4. **Minimal crash logging**
   - `runs/<run_id>/app.log` with key events and exception traces.
5. **Packaging**
   - PyInstaller specs for Win/macOS/Linux; bundle font & logo.
   - Smoke test script and short `RUNNING.md` (permissions & driver notes).
6. **Bounded gesture zoom**
   - Re-enable pinch-to-zoom with sane limits and snap-back so layouts remain recoverable.

### Nice-to-have (post-1.0 or if time permits)
7. **Configured OpenCV Bot (baseline)**
   - `cvbot/` with `config.yaml`, ROI picker, `Analyze Run` button.
   - Output: `analysis.json` + QC image; runs offline after acquisition.
8. **Arduino handshake**
   - On connect: firmware string/version + echo test; show in status line.
9. **Template export**
   - Export current config as `nemesis_config_<date>.json` for sharing.

> 🚨 **Urgent**: long-run drift exceeds 1 s/hour on some boards even after calibration. Once timing calibration hits the top of the backlog again, verify firmware scheduling + host factor and update this list.

---

## 9) How to contribute

- Create a feature branch; follow the pinned versions in `requirements.txt`.
- Keep UI changes conservative; favor text density over new widgets.
- Preserve **CSV schema v1.0**. If you must change it, bump to v1.1 and update `app/core/plotter.py` and docs together.
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

- [ ] `python run.py` launches; status line alive.
- [ ] Serial connects; stepsize `1..5` reaches Arduino.
- [ ] Camera preview visible; recording toggles ON/OFF.
- [ ] Start Run → `runs/run_*/{run.json,taps.csv}` created; taps appear in CSV.
- [ ] Plotter renders raster from CSV without edits.

---

Happy hacking. Ship it. 🚀
