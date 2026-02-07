"""Entry point for launching the NEMESIS desktop app."""

import multiprocessing
from app.main import main


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
