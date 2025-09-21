NEMESIS — Non-periodic Event Monitoring & Evaluation of Stimulus-Induced States
==================================================================================

Overview
--------
NEMESIS is a desktop tool for Stentor habituation experiments:
- Live microscope preview and recording (photo-booth workflow)
- Host-driven tap scheduling (Periodic or Poisson) with logging
- One-click manual tap and motor enable/disable
- Sync LED in firmware for frame-accurate alignment
- Structured CSV logs and plotting helpers

Hardware/Firmware (upload once)
-------------------------------
Use the headless Arduino sketch (NEMESIS_Firmware.ino). Serial commands:
  't' → tap once (down+up)
  'e' → enable motor    'd' → disable motor
  'r' → jog up          'l' → jog down
  '1'..'5' → microstep (1=full .. 5=1/16)
  'h' → help
The sync LED on pin 8 lights during a tap for video alignment.

UI & Workflow
-------------
- **Global font:** Typestar OCR (bundled in `assets/fonts/Typestar OCR Regular.otf`).
- **Theme:** instrument-panel palette (bg #0d0f12, panels #161a1f, text #b8c0cc, subtle #8a93a3, accent #5aa3ff, danger #e33).
- **Logo:** `assets/images/logo.png` used as window icon and header badge.
- **Photo-booth flow:** open camera → adjust focus/POV → Start Recording → Start Run. Recording is independent from the run.
- **Sanity check:** if you start a run without recording, you'll be prompted to confirm.
- **Pro Mode:** keyboard-first interaction (toggle in UI). When ON, some chrome hides for density and single-key controls are active:
  space=manual tap | r=rec on/off | s=run start/stop | e/d=enable/disable |
  1..5=microstep | c=serial toggle | v=camera toggle |
  [ / ]=−/+ period (Periodic) | { / }=−/+ λ (Poisson)

Data & Files
------------
- `taps.csv`: tap_id, t_host_s, mode, mark (extendable; future: tap_uuid, run_id, t_host_ms, stepsize, notes)
- `plotter.py`: data-free `make_figure(...)` and `save_figure(...)` for raster+scatter plots
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
4) python app.py
Then: open camera, connect serial, choose output dir, start/stop recording, start/stop run.

Roadmap (short list)
--------------------
- Top status line (camera idx/fps • REC • serial • taps • elapsed • rate)
- FPS/drop monitor HUD and serial RTT
- Config save/load, reproducible Poisson seed, CSV v2
- ROI-based response detection with review/override UI
- Export bundle (.zip) of run artifacts

Repo Layout (UI-relevant)
-------------------------
app.py
video.py
plotter.py
assets/
  fonts/Typestar OCR Regular.otf
  images/logo.png
requirements.txt
(plus your existing scheduler.py, serial_link.py, logger.py)

License & Attribution
---------------------
Ensure Typestar OCR’s license permits bundling in your distribution. Include license/readme files where appropriate.