# plotter.py — Data-free plotting template for Stentor habituation figures
# This file defines reusable helpers without bundling any data.
# Import `make_figure` and pass your arrays at runtime.
#
# Rules:
# - matplotlib only (no seaborn)
# - single figure: top raster of taps, bottom scatter of responses
# - no hardcoded datasets or demo section

from typing import Optional, Sequence, Tuple
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator

DEFAULT_TITLE = "Stentor Habituation to Stimuli"
DEFAULT_HIGHLIGHT_EVERY = 10
DEFAULT_FIGSIZE = (15.0, 8.0)
SECONDS_PER_MIN = 60.0
FIG_HEIGHT_RATIOS = (1, 5)
FIG_TITLE_FONT_SIZE = 20
EVENT_LINEWIDTH_REGULAR = 0.75
EVENT_LINEWIDTH_HIGHLIGHT = 1.5
AXIS_LABEL_FONT_SIZE = 14
LEGEND_FONT_SIZE = 12
TICK_LABEL_SIZE = 12
Y_LIMITS = (-5, 105)
X_MAJOR_TICK_MIN = 10
X_MINOR_TICK_MIN = 2
TIGHT_LAYOUT_RECT = (0, 0.03, 1, 0.95)
SAVE_DPI = 300

def make_figure(
    all_tap_times_seconds: Sequence[float],
    main_response_times_seconds: Sequence[float],
    main_contraction_percent: Sequence[float],
    steady_state_times_seconds: Sequence[float],
    steady_state_contraction_percent: Sequence[float],
    title: str = DEFAULT_TITLE,
    highlight_every_n: Optional[int] = DEFAULT_HIGHLIGHT_EVERY,
    figsize: Tuple[float, float] = DEFAULT_FIGSIZE,
) -> "plt.Figure":
    """
    Build the raster+scatter figure.

    Parameters
    ----------
    all_tap_times_seconds : list/array of float
        Absolute tap times (seconds) for the entire run.
    main_response_times_seconds : list/array of float
        Times (seconds) for the habituation phase response measurements.
    main_contraction_percent : list/array of float
        Percent contracted (0..100) for the habituation phase, aligned with `main_response_times_seconds`.
    steady_state_times_seconds : list/array of float
        Times (seconds) for the steady-state phase response measurements.
    steady_state_contraction_percent : list/array of float
        Percent contracted (0..100) for steady-state phase, aligned with `steady_state_times_seconds`.
    title : str
        Figure title.
    highlight_every_n : Optional[int]
        If provided, every N-th tap is highlighted in the raster (e.g., 10 → 10th, 20th, ...).
        If None, no taps are specially highlighted.
    figsize : (width, height)
        Matplotlib figure size in inches.

    Returns
    -------
    matplotlib.figure.Figure
        The assembled figure; caller may show or save it.
    """

    plt.style.use('default')  # white background

    # Convert times to minutes for plotting
    all_tap_times_minutes = [t / SECONDS_PER_MIN for t in all_tap_times_seconds]
    main_response_times_minutes = [t / SECONDS_PER_MIN for t in main_response_times_seconds]
    steady_state_times_minutes = [t / SECONDS_PER_MIN for t in steady_state_times_seconds]

    # Determine regular vs highlighted taps
    if highlight_every_n and highlight_every_n > 0:
        highlighted = [t for i, t in enumerate(all_tap_times_minutes) if (i + 1) % highlight_every_n == 0]
        regular = [t for i, t in enumerate(all_tap_times_minutes) if (i + 1) % highlight_every_n != 0]
    else:
        highlighted = []
        regular = list(all_tap_times_minutes)

    # Layout
    fig, (ax1, ax2) = plt.subplots(
        2, 1, sharex=True, figsize=figsize,
        gridspec_kw={'height_ratios': FIG_HEIGHT_RATIOS}
    )
    fig.suptitle(title, fontsize=FIG_TITLE_FONT_SIZE)

    # --- Top: Stimulus raster ---
    if regular:
        ax1.eventplot(regular, orientation='horizontal', colors='black', linewidth=EVENT_LINEWIDTH_REGULAR)
    if highlighted:
        ax1.eventplot(highlighted, orientation='horizontal', colors='red', linewidth=EVENT_LINEWIDTH_HIGHLIGHT)

    ax1.set_ylabel('Taps', fontsize=AXIS_LABEL_FONT_SIZE)
    ax1.set_yticks([])
    ax1.grid(axis='x', linestyle=':', color='gray')

    # --- Bottom: Response scatter ---
    ax2.scatter(main_response_times_minutes, main_contraction_percent,
                label='Habituation Phase', zorder=5)
    ax2.scatter(steady_state_times_minutes, steady_state_contraction_percent,
                label='Steady State', zorder=5)

    # Formatting
    ax2.set_xlabel('Time (minutes)', fontsize=AXIS_LABEL_FONT_SIZE)
    ax2.set_ylabel('% Contracted', fontsize=AXIS_LABEL_FONT_SIZE)
    ax2.legend(fontsize=LEGEND_FONT_SIZE)
    ax1.tick_params(axis='y', labelsize=TICK_LABEL_SIZE)
    ax2.tick_params(axis='both', labelsize=TICK_LABEL_SIZE)
    ax2.set_ylim(bottom=Y_LIMITS[0], top=Y_LIMITS[1])
    ax2.yaxis.set_major_formatter(plt.FuncFormatter('{:.0f}%'.format))
    ax2.xaxis.set_major_locator(MultipleLocator(X_MAJOR_TICK_MIN))
    ax2.xaxis.set_minor_locator(MultipleLocator(X_MINOR_TICK_MIN))

    plt.tight_layout(rect=TIGHT_LAYOUT_RECT)
    return fig

def save_figure(fig: "plt.Figure", out_path: str) -> None:
    """
    Save the figure to a file. Format inferred from extension (.png, .pdf, etc.).
    """
    fig.savefig(out_path, bbox_inches='tight', dpi=SAVE_DPI)
