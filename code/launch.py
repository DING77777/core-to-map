"""Open the local workspace using summary CSVs supplied by the user.

Author: Ding Qing
Date: 2026-10-15
"""

import os
from pathlib import Path
import socket
import subprocess
import sys

from datasets import SOURCES


ROOT = Path(__file__).resolve().parent


def has_summaries(data):
    return any((data / "inbox").glob("*.csv")) or any(
        (data / relative).is_file() for relative, _ in SOURCES.values()
    )


def main():
    local_data = ROOT / "data"
    default = local_data if local_data.is_dir() else ROOT.parent / "data"
    data = Path(os.environ.get("HYLOGGER_DATA_ROOT", default)).resolve()
    (data / "inbox").mkdir(parents=True, exist_ok=True)
    while not has_summaries(data):
        print("No summary CSVs found. Nothing will be downloaded.", flush=True)
        print("Place original GSWA Summary Mineral Log CSVs in:", data / "inbox", flush=True)
        try:
            input("Press Enter after adding files, or Ctrl+C to close: ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
    port = 8051
    for candidate in range(8051, 8071):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", candidate))
            except OSError:
                continue
            port = candidate
            break
    command = [sys.executable, "-B", str(ROOT / "app.py"), "--data-root", str(data),
               "--port", str(port), "--open-browser"]
    return subprocess.call(command, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
