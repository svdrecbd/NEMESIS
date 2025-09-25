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
- **Theme:** instrument-panel palette (bg `#0d0f12`, panels `#161a1f`, text `#b8c0cc`, subtle `#8a93a3`, accent `#5aa3ff`, danger `#e33`).
- **Logo:** `assets/images/logo.png` used as window icon and header badge.
- **Preview panel:** 16:9 container with a subtle border while idle; as soon as the first real frame arrives the border hides and the preview goes edge‑to‑edge. The container adapts to the camera’s native aspect (4:3/16:9/16:10) to avoid letterboxing artifacts.
- **Live chart:** template‑style stimulus raster (top) embedded under the preview, themed to match the UI (Typestar, dark). X‑axis shows 0–70 minutes with 10‑min majors and 1‑min minors. Updates live with each tap.
- **Combobox popups:** dark, padded popup views (no native blue) with fixed control widths to prevent layout nudges.
- **Photo‑booth flow:** open camera → adjust focus/POV → Start Recording → Start Run. Recording is independent from the run.
- **Sanity check:** if you start a run without recording, you'll be prompted to confirm.
- **Pro Mode:** keyboard-first interaction (toggle in UI). When ON, some chrome hides for density and single-key controls are active:
  space=manual tap | r=rec on/off | s=run start/stop | e/d=enable/disable |
  1..5=microstep | c=serial toggle | v=camera toggle |
  [ / ]=−/+ period (Periodic) | { / }=−/+ λ (Poisson)

Zoom & Navigation
-----------------
- **App‑wide zoom:** pinch anywhere to scale the entire UI (pure visual; no reflow). Browser parity: Cmd/Ctrl+= (zoom in), Cmd/Ctrl+- (zoom out), Cmd/Ctrl+0 (reset).
- **Two‑finger browse:** when zoomed in, pan with two‑finger scroll or drag; slim scrollbars auto‑hide after a short delay. At 1.0× there’s no “give” when the window is at minimum size.

Data & Files
------------
- `run_*`: folder per run (`run_YYYYMMDD_HHMMSS_<token>`, `<token>` = 6 hex chars from UUID4)
- `taps.csv`: run_id, tap_id, tap_uuid, t_host_ms, mode, stepsize, mark, notes, recording_path
- `app/core/plotter.py`: data-free `make_figure(...)` and `save_figure(...)` for raster+scatter plots
- Planned exports: per-run JSON (config), analysis CSV, plots, and video bundle

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
Then: open camera, connect serial, choose output dir, start/stop recording, start/stop run.

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
- Preview border hides automatically after first frame; container adapts to camera aspect.
- Live raster chart embedded under the preview (0–70 min, 10‑min majors, 1‑min minors).
- Raise/Lower Arm jog buttons under Enable/Disable for half‑step nudging.
- Dark combobox popups with padding; fixed widths prevent layout jitter.
- App‑wide pinch zoom with auto‑hiding scrollbars; browser shortcuts added.

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
  images/logo.png
firmware/
  arduino/stentor_habituator_stepper_v9/NEMESIS_Firmware.ino
  unit1/UNIT1_firmware/...
docs/
tests/
requirements.txt

License & Attribution
---------------------
Ensure Typestar OCR’s license permits bundling in your distribution. Include license/readme files where appropriate.
