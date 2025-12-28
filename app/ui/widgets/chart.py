# app/ui/widgets/chart.py
from typing import Callable, Sequence
import math
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.ticker import MultipleLocator
from PySide6.QtWidgets import QWidget
from app.ui.theme import apply_matplotlib_theme, active_theme, HEATMAP_PALETTES
from app.core.logger import APP_LOGGER

def apply_matplotlib_theme_wrapper(font_family: str | None, theme: dict[str, str]):
    # Wrapper to avoid circular imports or direct dependency on main logic if possible
    # Assuming apply_matplotlib_theme is in app.ui.theme
    from app.ui.theme import apply_matplotlib_theme
    apply_matplotlib_theme(font_family, theme)

class LiveChart:
    PALETTES = HEATMAP_PALETTES
    def __init__(self, font_family: str | None, theme: dict[str, str]):
        self.font_family = font_family
        self.theme = theme
        # Import dynamically or use the passed helper to apply theme
        from app.ui.theme import apply_matplotlib_theme
        apply_matplotlib_theme(font_family, theme)
        
        self.fig, (self.ax_top, self.ax_bot) = plt.subplots(
            2, 1, sharex=True, figsize=(6.2, 3.2),
            gridspec_kw={"height_ratios": [1, 5]}
        )
        # Compact layout and tighter suptitle position to reduce top padding
        try:
            self.fig.subplots_adjust(top=0.82, bottom=0.18, left=0.10, right=0.98, hspace=0.12)
        except Exception as e:
            APP_LOGGER.error(f"LiveChart subplots_adjust error: {e}")
            
        self.canvas = FigureCanvas(self.fig)
        # Reduce minimum height so the preview keeps priority
        self.canvas.setMinimumHeight(160)
        try:
            # Canvas transparent; outer QFrame draws the border/background
            self.canvas.setStyleSheet("background: transparent;")
        except Exception as e:
            APP_LOGGER.error(f"Error setting canvas stylesheet: {e}")
        self.times_sec: list[float] = []
        self._time_unit: str = "minutes"
        self._last_max_elapsed_sec: float = 0.0
        self.replay_targets: list[float] = []
        self.replay_completed: int = 0
        self.heatmap_palette: str = HEATMAP_PALETTES[0]
        self._heatmap_cbar = None
        self._heatmap_im = None
        self._heatmap_active = False
        self._heatmap_listeners: list[Callable[[bool], None]] = []
        self._long_run_active: bool = False
        self._long_run_listeners: list[Callable[[bool], None]] = []
        self._long_run_view: str = "taps"
        self.contraction_heatmap: np.ndarray | None = None
        self._init_axes()

    def _init_axes(self):
        text_color = self.color("TEXT")
        self.fig.suptitle("Stentor Habituation to Stimuli", fontsize=10, color=text_color, y=0.98)
        try:
            self.fig.patch.set_alpha(0.0)
            self.fig.patch.set_facecolor('none')
        except Exception as e:
            APP_LOGGER.error(f"Error setting figure patch properties: {e}")
        self._configure_standard_axes(0.0)
        self.canvas.draw_idle()

    def reset(self):
        self.times_sec.clear()
        self.replay_completed = min(self.replay_completed, len(self.replay_targets))
        self._last_max_elapsed_sec = 0.0
        self._long_run_view = "taps"
        self.contraction_heatmap = None
        self._clear_heatmap_artists()
        self._configure_standard_axes(0.0)
        self._set_long_mode(False)
        self._set_heatmap_state(False)
        self.canvas.draw_idle()

    def add_tap(self, t_since_start_s: float):
        self.times_sec.append(float(t_since_start_s))
        self._redraw()

    def set_times(self, times_seconds: Sequence[float]):
        self.times_sec = [float(v) for v in times_seconds]
        self._redraw()

    def set_replay_targets(self, targets: Sequence[float] | None):
        self.replay_targets = [] if targets is None else [float(v) for v in targets]
        self.replay_completed = 0
        self._redraw()

    def mark_replay_progress(self, completed: int):
        if completed < 0:
            completed = 0
        if completed > len(self.replay_targets):
            completed = len(self.replay_targets)
        self.replay_completed = completed
        self._redraw()

    def clear_replay_targets(self):
        self.replay_targets = []
        self.replay_completed = 0
        self._redraw()

    def set_contraction_heatmap(self, matrix: Sequence[Sequence[float]] | None):
        if matrix is None:
            self.contraction_heatmap = None
        else:
            arr = np.asarray(matrix, dtype=float)
            if arr.ndim != 2 or arr.size == 0:
                self.contraction_heatmap = None
            else:
                self.contraction_heatmap = arr
        if self._long_run_view == "contraction" and self._long_run_active:
            self._redraw()

    def set_long_run_view(self, view: str):
        view_key = (view or "").strip().lower()
        if view_key not in {"taps", "contraction"}:
            return
        if view_key == self._long_run_view:
            return
        self._long_run_view = view_key
        self._redraw()

    def long_run_view(self) -> str:
        return self._long_run_view

    def long_run_active(self) -> bool:
        return self._long_run_active

    def add_long_mode_listener(self, callback: Callable[[bool], None]) -> None:
        if callback in self._long_run_listeners:
            try:
                callback(self._long_run_active)
            except Exception:
                pass
            return
        self._long_run_listeners.append(callback)
        try:
            callback(self._long_run_active)
        except Exception:
            pass


    def _set_long_mode(self, active: bool) -> None:
        if self._long_run_active == active:
            return
        self._long_run_active = active
        if not active:
            self._long_run_view = "taps"
            self._clear_heatmap_artists()
        for callback in list(self._long_run_listeners):
            try:
                callback(active)
            except Exception:
                continue

    def _redraw(self):
        max_elapsed_sec_actual = max(self.times_sec) if self.times_sec else 0.0
        max_elapsed_sec_script = max(self.replay_targets) if self.replay_targets else 0.0
        max_elapsed_sec = max(max_elapsed_sec_actual, max_elapsed_sec_script)
        if max_elapsed_sec <= 0:
            self._configure_standard_axes(0.0)
            self._set_long_mode(False)
            self._set_heatmap_state(False)
            self.canvas.draw_idle()
            return

        long_mode = max_elapsed_sec >= 3 * 3600
        heatmap_on = False
        if long_mode:
            if self._long_run_view == "contraction":
                self._configure_long_heatmap_axes()
                self._draw_contraction_heatmap()
                heatmap_on = True
            else:
                self._configure_long_raster_axes(max_elapsed_sec)
                self._draw_long_raster(max_elapsed_sec)
        else:
            self._configure_standard_axes(max_elapsed_sec)
            self._draw_standard_raster()

        self._set_long_mode(long_mode)
        self._set_heatmap_state(heatmap_on)
        self.canvas.draw_idle()

    def _configure_standard_axes(self, max_elapsed_sec: float) -> None:
        text_color = self.color("TEXT")
        ax_top = self.ax_top
        ax_bot = self.ax_bot

        ax_top.cla()
        ax_bot.cla()
        try:
            ax_top.set_facecolor('none')
            ax_bot.set_facecolor('none')
        except Exception:
            pass

        self._clear_heatmap_artists()

        ax_bot.set_visible(True)
        ax_top.set_ylabel("Taps", color=text_color)
        ax_top.set_yticks([])
        ax_top.tick_params(axis='x', colors=text_color)
        ax_top.tick_params(axis='y', colors=text_color)
        for spine in ax_top.spines.values():
            spine.set_color(text_color)
        ax_top.set_title("")

        ax_bot.set_ylabel("% Contracted")
        ax_bot.set_ylim(-5, 105)
        ax_bot.yaxis.set_major_formatter(plt.FuncFormatter("{:.0f}%".format))
        ax_bot.tick_params(axis='x', colors=text_color)
        ax_bot.tick_params(axis='y', colors=text_color)
        for spine in ax_bot.spines.values():
            spine.set_color(text_color)
        ax_bot.set_title("")

        minutes_span = max_elapsed_sec / 60.0 if max_elapsed_sec else 0.0
        default_limit = 60.0
        target_limit = minutes_span * 1.05 if minutes_span else default_limit
        max_unit_val = max(default_limit, min(180.0, target_limit))

        major = MultipleLocator(10)
        minor = MultipleLocator(1)
        ax_top.xaxis.set_major_locator(major)
        ax_top.xaxis.set_minor_locator(minor)
        ax_bot.xaxis.set_major_locator(MultipleLocator(10))
        ax_bot.xaxis.set_minor_locator(MultipleLocator(1))
        ax_bot.set_xlabel("Time (minutes)")
        ax_top.grid(True, which="major", axis="x", linestyle=":", alpha=0.9)
        ax_top.grid(True, which="minor", axis="x", linestyle=":", alpha=0.35)
        ax_bot.grid(True, which="major", axis="x", linestyle=":", alpha=0.9)
        ax_bot.grid(True, which="minor", axis="x", linestyle=":", alpha=0.35)

        ax_top.set_xlim(0, max_unit_val)
        ax_bot.set_xlim(0, max_unit_val)
        self._time_unit = "minutes"
        self._last_max_elapsed_sec = max_elapsed_sec
        try:
            self.fig.subplots_adjust(top=0.82, bottom=0.18, left=0.10, right=0.98, hspace=0.12)
            self.fig.suptitle("Stentor Habituation to Stimuli", fontsize=10, color=text_color, y=0.98)
        except Exception as e:
            APP_LOGGER.error(f"Error adjusting subplots or suptitle: {e}")

    def _configure_long_raster_axes(self, max_elapsed_sec: float) -> None:
        text_color = self.color("TEXT")
        ax_top = self.ax_top
        ax_bot = self.ax_bot

        ax_top.cla()
        ax_bot.cla()
        try:
            ax_top.set_facecolor('none')
            ax_bot.set_facecolor('none')
        except Exception:
            pass

        ax_bot.set_visible(False)
        ax_bot.set_axis_off()

        ax_top.set_visible(True)
        ax_top.set_ylabel("Hour")
        ax_top.tick_params(axis='x', colors=text_color)
        ax_top.tick_params(axis='y', colors=text_color)
        for spine in ax_top.spines.values():
            spine.set_color(text_color)

        self._clear_heatmap_artists()

        self._time_unit = "hours"
        self._last_max_elapsed_sec = max_elapsed_sec
        try:
            self.fig.subplots_adjust(top=0.90, bottom=0.10, left=0.10, right=0.98)
            self.fig.suptitle("Tap raster by hour", fontsize=10, color=text_color, y=0.97)
        except Exception as e:
            APP_LOGGER.error(f"Error adjusting subplots (long raster): {e}")

    def _configure_long_heatmap_axes(self) -> None:
        text_color = self.color("TEXT")
        ax_top = self.ax_top
        ax_bot = self.ax_bot

        ax_top.cla()
        ax_bot.cla()
        try:
            ax_top.set_facecolor('none')
            ax_bot.set_facecolor('none')
        except Exception:
            pass

        ax_bot.set_visible(False)
        ax_bot.set_axis_off()

        ax_top.set_visible(True)
        ax_top.tick_params(axis='x', colors=text_color)
        ax_top.tick_params(axis='y', colors=text_color)
        for spine in ax_top.spines.values():
            spine.set_color(text_color)

        self._time_unit = "hours"
        try:
            self.fig.subplots_adjust(top=0.90, bottom=0.10, left=0.10, right=0.92)
            self.fig.suptitle("Contraction heatmap", fontsize=10, color=text_color, y=0.97)
        except Exception as e:
            APP_LOGGER.error(f"Error adjusting subplots (long heatmap): {e}")

    def _draw_standard_raster(self) -> None:
        text_color = self.color("TEXT")
        accent_color = self.color("ACCENT")
        remaining_color = self.color("SUBTXT")

        factor = 60.0
        ts_unit = [t / factor for t in self.times_sec]
        highlighted = [t for i, t in enumerate(ts_unit) if (i + 1) % 10 == 0]
        regular = [t for i, t in enumerate(ts_unit) if (i + 1) % 10 != 0]

        if self.replay_targets:
            replay_unit = [t / factor for t in self.replay_targets]
            completed_unit = replay_unit[: self.replay_completed]
            remaining_unit = replay_unit[self.replay_completed :]
            if remaining_unit:
                self.ax_top.eventplot(
                    remaining_unit,
                    orientation="horizontal",
                    colors=remaining_color,
                    linewidth=0.8,
                )
            if completed_unit and not self.times_sec:
                self.ax_top.eventplot(
                    completed_unit,
                    orientation="horizontal",
                    colors=accent_color,
                    linewidth=1.0,
                )

        if regular:
            self.ax_top.eventplot(regular, orientation="horizontal", colors=text_color, linewidth=0.9)
        if highlighted:
            self.ax_top.eventplot(highlighted, orientation="horizontal", colors=accent_color, linewidth=1.6)

    def _draw_long_raster(self, max_elapsed_sec: float) -> None:
        ax = self.ax_top
        text_color = self.color("TEXT")
        accent_color = self.color("ACCENT")
        pending_color = self.color("SUBTXT")

        taps_actual = np.asarray(self.times_sec, dtype=float)
        taps_script = np.asarray(self.replay_targets, dtype=float) if self.replay_targets else np.empty(0, dtype=float)

        taps_actual = taps_actual[np.isfinite(taps_actual)]
        taps_actual = taps_actual[taps_actual >= 0.0]
        taps_script = taps_script[np.isfinite(taps_script)]
        taps_script = taps_script[taps_script >= 0.0]

        reference = taps_actual if taps_actual.size else taps_script
        if reference.size == 0:
            ax.text(
                0.5,
                0.5,
                "No tap data",
                color=self.color("SUBTXT"),
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
            ax.set_axis_off()
            return

        max_sec = max(max_elapsed_sec, float(reference.max()))
        hours = max(1, int(math.ceil((max_sec + 1e-9) / 3600.0)))
        line_offsets = np.arange(hours)

        regular_groups = [[] for _ in range(hours)]
        highlight_groups = [[] for _ in range(hours)]
        pending_groups = [[] for _ in range(hours)]

        for idx, value in enumerate(taps_actual):
            hour = min(int(value // 3600), hours - 1)
            minute_within_hour = (value % 3600.0) / 60.0
            if (idx + 1) % 10 == 0:
                highlight_groups[hour].append(minute_within_hour)
            else:
                regular_groups[hour].append(minute_within_hour)

        if taps_script.size:
            for idx, value in enumerate(taps_script):
                if idx < self.replay_completed:
                    continue
                hour = min(int(value // 3600), hours - 1)
                minute_within_hour = (value % 3600.0) / 60.0
                pending_groups[hour].append(minute_within_hour)

        ax.cla()
        ax.set_visible(True)
        ax.set_ylabel("Hour")
        ax.set_xlabel("Minute within hour")
        ax.tick_params(axis='x', colors=text_color)
        ax.tick_params(axis='y', colors=text_color)
        for spine in ax.spines.values():
            spine.set_color(text_color)

        if any(group for group in pending_groups):
            ax.eventplot(
                pending_groups,
                lineoffsets=line_offsets,
                linelengths=0.7,
                linewidth=0.8,
                colors=pending_color,
            )
        if any(group for group in regular_groups):
            ax.eventplot(
                regular_groups,
                lineoffsets=line_offsets,
                linelengths=0.7,
                linewidth=0.9,
                colors=text_color,
            )
        if any(group for group in highlight_groups):
            ax.eventplot(
                highlight_groups,
                lineoffsets=line_offsets,
                linelengths=0.7,
                linewidth=1.3,
                colors=accent_color,
            )

        ax.set_ylim(-0.5, hours - 0.5)
        ax.set_yticks(line_offsets)
        ax.set_yticklabels([f"H{h:02d}" for h in range(hours)])
        ax.invert_yaxis()
        ax.set_xlim(-0.5, 59.5)
        ax.set_xticks(np.arange(0, 60, 5))
        ax.grid(axis="x", which="major", linestyle=":", alpha=0.25)

    def _draw_contraction_heatmap(self) -> None:
        ax = self.ax_top
        text_color = self.color("TEXT")

        ax.cla()
        ax.set_visible(True)

        data = self.contraction_heatmap
        try:
            self.fig.suptitle(f"Contraction heatmap — {self.heatmap_palette.title()}", fontsize=10, color=text_color, y=0.97)
        except Exception as e:
            APP_LOGGER.error(f"Error setting suptitle: {e}")
        if data is None or data.size == 0:
            ax.text(
                0.5,
                0.5,
                "No contraction data",
                color=self.color("SUBTXT"),
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
            ax.set_axis_off()
            self._clear_heatmap_artists()
            return

        matrix = np.asarray(data, dtype=float)
        if matrix.ndim != 2 or matrix.shape[1] == 0:
            ax.text(
                0.5,
                0.5,
                "Invalid contraction matrix",
                color=self.color("SUBTXT"),
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
            ax.set_axis_off()
            self._clear_heatmap_artists()
            return

        hours = matrix.shape[0]
        cmap_name = self.heatmap_palette if self.heatmap_palette in HEATMAP_PALETTES else HEATMAP_PALETTES[0]
        img = ax.imshow(
            matrix,
            aspect="auto",
            interpolation="nearest",
            cmap=cmap_name,
            vmin=0.0,
            vmax=100.0,
        )
        self._heatmap_im = img
        if self._heatmap_cbar is None:
            self._heatmap_cbar = self.fig.colorbar(img, ax=ax, pad=0.02, fraction=0.05)
        else:
            try:
                self._heatmap_cbar.update_normal(img)
            except Exception:
                self._heatmap_cbar = self.fig.colorbar(img, cax=self._heatmap_cbar.ax)

        try:
            self._heatmap_cbar.set_label("Contraction %", color=text_color)
            self._heatmap_cbar.ax.yaxis.set_tick_params(color=text_color)
            plt.setp(self._heatmap_cbar.ax.get_yticklabels(), color=text_color)
        except Exception:
            pass

        ax.set_ylim(-0.5, hours - 0.5)
        ax.set_yticks(np.arange(hours))
        ax.set_yticklabels([f"H{h:02d}" for h in range(hours)])
        ax.invert_yaxis()
        ax.set_xlim(-0.5, 59.5)
        ax.set_xticks(np.arange(0, 60, 5))
        ax.set_xlabel("Minute within hour")
        ax.set_ylabel("Hour")
        for spine in ax.spines.values():
            spine.set_color(text_color)
        ax.tick_params(axis='x', colors=text_color)
        ax.tick_params(axis='y', colors=text_color)
        for x in range(0, 60, 5):
            ax.axvline(x - 0.5, color=self.color("GRID"), linewidth=0.35, alpha=0.2)

    def set_heatmap_palette(self, palette: str) -> None:
        candidate = (palette or "").strip().lower()
        if candidate not in HEATMAP_PALETTES:
            candidate = HEATMAP_PALETTES[0]
        if candidate == self.heatmap_palette:
            return
        self.heatmap_palette = candidate
        if self._heatmap_active:
            try:
                if self._heatmap_im is not None:
                    self._heatmap_im.set_cmap(candidate)
                    if self._heatmap_cbar is not None:
                        self._heatmap_cbar.update_normal(self._heatmap_im)
                        self._heatmap_cbar.set_label("Contraction %", color=self.color("TEXT"))
                        self._heatmap_cbar.ax.yaxis.set_tick_params(color=self.color("TEXT"))
                        plt.setp(self._heatmap_cbar.ax.get_yticklabels(), color=self.color("TEXT"))
                else:
                    self._redraw()
                try:
                    self.fig.suptitle(f"Contraction heatmap — {self.heatmap_palette.title()}", fontsize=10, color=self.color("TEXT"), y=0.97)
                except Exception:
                    pass
                self.canvas.draw_idle()
            except Exception:
                self._redraw()

    def heatmap_active(self) -> bool:
        return self._heatmap_active

    def save(self, path: str, dpi: int = 300) -> None:
        self.fig.savefig(path, dpi=dpi, bbox_inches='tight')

    def color(self, key: str) -> str:
        if key in self.theme:
            return self.theme[key]
        return active_theme().get(key, "#ffffff")

    def set_theme(self, theme: dict[str, str]):
        self.theme = theme
        from app.ui.theme import apply_matplotlib_theme
        apply_matplotlib_theme(self.font_family, theme)
        if self.times_sec or self.replay_targets:
            self._redraw()
        else:
            if self._long_run_active:
                if self._long_run_view == "contraction":
                    self._configure_long_heatmap_axes()
                    self._draw_contraction_heatmap()
                else:
                    self._configure_long_raster_axes(self._last_max_elapsed_sec)
            else:
                self._configure_standard_axes(self._last_max_elapsed_sec)
            self._set_long_mode(self._long_run_active)
            self._set_heatmap_state(self._long_run_active and self._long_run_view == "contraction")
            self.canvas.draw_idle()

    def add_heatmap_listener(self, callback: Callable[[bool], None]) -> None:
        if callback in self._heatmap_listeners:
            try:
                callback(self._heatmap_active)
            except Exception:
                pass
            return
        self._heatmap_listeners.append(callback)
        try:
            callback(self._heatmap_active)
        except Exception:
            pass

    def _set_heatmap_state(self, active: bool) -> None:
        if self._heatmap_active == active:
            return
        self._heatmap_active = active
        for callback in list(self._heatmap_listeners):
            try:
                callback(active)
            except Exception:
                continue

    def _clear_heatmap_artists(self) -> None:
        if self._heatmap_cbar is not None:
            try:
                self._heatmap_cbar.ax.remove()
            except Exception:
                pass
        self._heatmap_cbar = None
        self._heatmap_im = None
