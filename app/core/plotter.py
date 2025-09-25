# plotter.py — Data-free plotting template for Stentor habituation figures
# This file defines reusable helpers without bundling any data.
# Import `make_figure` and pass your arrays at runtime.
#
# Rules:
# - matplotlib only (no seaborn)
# - single figure: top raster of taps, bottom scatter of responses
# - no hardcoded datasets or demo section

from typing import Iterable, Optional, Sequence, Tuple
import matplotlib.pyplot as plt

def make_figure(
    all_tap_times_seconds: Sequence[float],
    main_response_times_seconds: Sequence[float],
    main_contraction_percent: Sequence[float],
    steady_state_times_seconds: Sequence[float],
    steady_state_contraction_percent: Sequence[float],
    title: str = "Stentor Habituation to Stimuli",
    highlight_every_n: Optional[int] = 10,
    figsize: Tuple[float, float] = (15.0, 8.0),
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
    all_tap_times_minutes = [t / 60.0 for t in all_tap_times_seconds]
    main_response_times_minutes = [t / 60.0 for t in main_response_times_seconds]
    steady_state_times_minutes = [t / 60.0 for t in steady_state_times_seconds]

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
        gridspec_kw={'height_ratios': [1, 5]}
    )
    fig.suptitle(title, fontsize=20)

    # --- Top: Stimulus raster ---
    if regular:
        ax1.eventplot(regular, orientation='horizontal', colors='black', linewidth=0.75)
    if highlighted:
        ax1.eventplot(highlighted, orientation='horizontal', colors='red', linewidth=1.5)

    ax1.set_ylabel('Taps', fontsize=14)
    ax1.set_yticks([])
    ax1.grid(axis='x', linestyle=':', color='gray')

    # --- Bottom: Response scatter ---
    ax2.scatter(main_response_times_minutes, main_contraction_percent,
                label='Habituation Phase', zorder=5)
    ax2.scatter(steady_state_times_minutes, steady_state_contraction_percent,
                label='Steady State', zorder=5)

    # Formatting
    ax2.set_xlabel('Time (minutes)', fontsize=14)
    ax2.set_ylabel('% Contracted', fontsize=14)
    ax2.legend(fontsize=12)
    ax1.tick_params(axis='y', labelsize=12)
    ax2.tick_params(axis='both', labelsize=12)
    ax2.set_ylim(bottom=-5, top=105)
    ax2.yaxis.set_major_formatter(plt.FuncFormatter('{:.0f}%'.format))
    ax2.xaxis.set_major_locator(plt.MultipleLocator(10))
    ax2.xaxis.set_minor_locator(plt.MultipleLocator(2))

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    return fig

def save_figure(fig: "plt.Figure", out_path: str) -> None:
    """
    Save the figure to a file. Format inferred from extension (.png, .pdf, etc.).
    """
    fig.savefig(out_path, bbox_inches='tight', dpi=300)
