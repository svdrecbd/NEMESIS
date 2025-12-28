"""Interactive CLI to drive the legacy Arduino tapper via NEMESIS drivers.

This keeps the pre-NEMESIS workflow (serial console control) available without
leaving the repository. Usage:

    python tools/arduino_wrapper.py --port /dev/ttyUSB0

Type single-character commands (e.g., `e`, `d`, `t`, `1`..`5`). When the
firmware prompts for numeric input (Periodic/Poisson configuration), type the
value and press enter; the wrapper sends the digits plus a newline so the
Arduino sketch parses them as before.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def _ensure_repo_root_on_path() -> None:
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


_ensure_repo_root_on_path()

from app.drivers.arduino_driver import SerialLink  # noqa: E402

DEFAULT_BAUD = 9600
CHAR_SEND_DELAY_S = 0.01
POST_SEND_DELAY_S = 0.05


def drain_output(link: SerialLink) -> None:
    """Print any buffered lines from the Arduino."""
    while True:
        line = link.read_line_nowait()
        if line is None:
            break
        print(f"[arduino] {line}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Serial port (e.g. COM5 or /dev/ttyUSB0)")
    parser.add_argument(
        "--baud",
        type=int,
        default=DEFAULT_BAUD,
        help=f"Baud rate (default: {DEFAULT_BAUD})",
    )
    parser.add_argument(
        "--no-newline",
        action="store_true",
        help="Do not append newline when sending multi-character input.",
    )
    args = parser.parse_args(argv)

    link = SerialLink()
    try:
        link.open(args.port, baudrate=args.baud, timeout=0)
    except Exception as exc:  # pragma: no cover - I/O setup
        print(f"Failed to open {args.port}: {exc}", file=sys.stderr)
        return 1

    print("Connected. Type commands (e/d/t/r/l/1..5). 'exit' to quit.")
    drain_output(link)

    try:
        while True:
            try:
                user_input = input("arduino> ")
            except EOFError:
                print()
                break

            stripped = user_input.strip()
            if stripped.lower() in {"exit", "quit"}:
                break

            payload = user_input if args.no_newline else user_input + "\n"
            for ch in payload:
                link.send_char(ch)
                # Short delay allows the firmware to process sequential chars.
                time.sleep(CHAR_SEND_DELAY_S)

            time.sleep(POST_SEND_DELAY_S)
            drain_output(link)
    finally:
        link.close()

    return 0


if __name__ == "__main__":  # pragma: no cover - manual entrypoint
    raise SystemExit(main())
