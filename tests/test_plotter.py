import matplotlib.pyplot as plt
from app.core.plotter import make_figure

def test_make_figure_no_data():
    # Test with empty lists
    fig = make_figure([], [], [], [], [])
    assert fig is not None
    plt.close(fig)

def test_make_figure_with_data():
    fig = make_figure(
        all_tap_times_seconds=[0, 10, 20],
        main_response_times_seconds=[0, 10],
        main_contraction_percent=[100, 80],
        steady_state_times_seconds=[20],
        steady_state_contraction_percent=[50]
    )
    assert fig is not None
    assert len(fig.axes) == 2
    plt.close(fig)
