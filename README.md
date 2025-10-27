NEMESIS — Non-periodic Event Monitoring & Evaluation of Stimulus-Induced States
==================================================================================

Overview
--------
NEMESIS is a desktop tool for Stentor habituation experiments:
- Live microscope preview and recording (photo-booth workflow)
- Host-driven tap scheduling (Periodic or Poisson) with logging
- One-click manual tap and motor enable/disable
- Raise/Lower Arm jog controls for fine positioning (half-step)
- Sync LED in firmware for frame-accurate alignment
- Structured CSV logs and plotting helpers
- Anchored tap telemetry (UTC host timestamps, firmware clock, preview/recorded frame indices)

Current Development Focus
-------------------------
- **Tabbed workspace.** The run control panel lives in dedicated run tabs; open multiple rigs side-by-side and use the new `+ Tab` launcher (or Cmd/Ctrl+T) to add run or data tabs on demand.
- **Session encapsulation.** Each tab owns its own `RunSession`, so camera feeds, serial links, logging, and calibration data stay isolated.
- **Dashboard tabs.** Browse completed runs, preview rasters, open folders, export taps, or delete artifacts from a dedicated data tab — open extras via `+ Tab → Data Tab`.
- **Multi-rig safeguards.** Camera indices and serial ports are coordinated automatically across tabs to prevent hardware collisions.

Hardware/Firmware (upload once)
-------------------------------
Use the headless Arduino sketch (`firmware/arduino/stentor_habituator_stepper_v9/NEMESIS_Firmware.ino`). Serial commands:
  't' → tap once (down+up)
  'e' → enable motor    'd' → disable motor
  'r' → jog up          'l' → jog down
  '1'..'5' → microstep (1=full .. 5=1/16)
  'h' → help
The sync LED on pin 8 lights during a tap for video alignment.

UI & Workflow
-------------
- **Global font:** Typestar OCR (bundled in `assets/fonts/Typestar OCR Regular.otf`).
- **Theme:** launches in **Light Mode** with controls on the **left** (25 % width) and data on the right (75 %). Dark Mode is still available from the menu. Typestar OCR remains the global typeface.
- **Logo:** `assets/images/transparent_logo.png` is auto-cropped and centred for the app icon and header badge.
- **Preview panel:** 16:9 container with a subtle border while idle; as soon as the first real frame arrives the border hides and the preview goes edge‑to‑edge. The container adapts to the camera’s native aspect (4:3/16:9/16:10) to avoid letterboxing artifacts.
- **Live chart:** template‑style stimulus raster (top) embedded under the preview. The timeline expands automatically; after two hours it switches to hours and thins the tick markers so long runs stay readable.
- **Tabbed navigation:** run/data tabs sit on a left-aligned bar with hover-only close buttons, rename-on-double-click, and Cmd/Ctrl+W / Cmd/Ctrl+Opt+Arrow shortcuts.
- **Photo‑booth flow:** connect serial (pick from the dropdown), open camera → adjust focus/POV → optionally **Flash Hardware Config** if you just want to exercise the hardware → press **Start Run** when you’re ready to log. Recording is independent from the run.
- **Timing calibration:** after each periodic run the app compares host vs. controller timing and stores a per-port calibration in `~/.nemesis/calibration.json`; future runs automatically apply the correction so 24 h “ultra” sessions stay aligned with wall-clock time.
- **Sanity check:** if you start a run without recording, you'll be prompted to confirm.
- **Pro Mode:** keyboard-first interaction (toggle in UI). When ON, some chrome hides for density and single-key controls are active:
  space=manual tap | r=rec on/off | s=run start/stop | e/d=enable/disable |
  1..5=microstep | c=serial toggle | v=camera toggle |
  [ / ]=−/+ period (Periodic) | { / }=−/+ λ (Poisson)

Zoom & Navigation
-----------------
- **App‑wide zoom:** browser parity shortcuts Cmd/Ctrl+= (zoom in), Cmd/Ctrl+- (zoom out), Cmd/Ctrl+0 (reset). Pinch-to-zoom is currently disabled while we rework layout bounds.
- **Two‑finger browse:** when zoomed in, pan with two‑finger scroll or drag; slim scrollbars auto‑hide after a short delay. At 1.0× there’s no “give” when the window is at minimum size.

Data & Files
------------
- `run_*`: folder per run (`run_YYYYMMDD_HHMMSS_<token>`, `<token>` = 6 hex chars from UUID4)
- `taps.csv`: run_id, tap_id, tap_uuid, t_host_ms, t_host_iso, t_fw_ms, mode, stepsize, mark, notes, frame_preview_idx, frame_recorded_idx, recording_path
- `app/core/plotter.py`: data-free `make_figure(...)` and `save_figure(...)` for raster+scatter plots
- Planned exports: per-run JSON (config), analysis CSV, plots, and video bundle
- `~/.nemesis/calibration.json`: per-port timing calibration written after each periodic run (used to compensate microsecond drift on future runs)

Recording
---------
- OpenCV VideoWriter MP4 (mp4v) with automatic fallback to MJPG `.avi` if needed.
- Host-clock timestamp overlay on frames (T+seconds since run start).

Install & Run
-------------
1) python -m venv .venv
2) Activate the venv
3) pip install -r requirements.txt
4) python run.py
Then: connect serial (choose from the combo box or type manually), open camera, choose output dir, optionally flash the hardware config to test the rig, start/stop recording, start/stop run.

Legacy Serial Wrapper
---------------------
Need the old manual serial workflow? Use the bundled wrapper instead of leaving the repo:

```bash
python tools/arduino_wrapper.py --port /dev/ttyUSB0
```

Type the standard single-character commands (`e`, `d`, `t`, `1`..`5`). When the firmware
prompts for numeric input, enter the number and press return—the wrapper appends the newline
for you so the Arduino sketch behaves exactly like the pre-NEMESIS setup.

Roadmap (short list)
--------------------
- Top status line (camera idx/fps • REC • serial • taps • elapsed • rate)
- FPS/drop monitor HUD and serial RTT
- Config save/load, reproducible Poisson seed, CSV v2
- ROI-based response detection with review/override UI
- Export bundle (.zip) of run artifacts

Recent Changes (highlights)
---------------------------
- Tabbed run/data workspace with theme-aware styling and keyboard shortcuts.
- Dashboard tab rebuilt for browsing, exports, and deletions.
- Per-tab camera/serial locking to support multi-rig setups.
- Automatic icon generation (cropped transparent logo).
- Right-panel scroll area and minimum window adjustments to keep controls in frame.

Repo Layout (UI-relevant)
-------------------------
run.py
app/
  main.py
  core/
    scheduler.py
    video.py
    plotter.py
    configio.py
    logger.py
  drivers/
    arduino_driver.py
    controller_driver.py
    unit1_driver.py
  ui/
assets/
  fonts/Typestar OCR Regular.otf
  images/transparent_logo.png
firmware/
  arduino/stentor_habituator_stepper_v9/NEMESIS_Firmware.ino
  unit1/UNIT1_firmware/...
docs/
tests/
requirements.txt

License & Attribution
---------------------
Ensure Typestar OCR’s license permits bundling in your distribution. Include license/readme files where appropriate.
