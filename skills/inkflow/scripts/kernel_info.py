"""Read kernel.json and print port/token for HTTP API calls.

Usage:
    uv run python kernel_info.py [data_dir]
    # data_dir default: %APPDATA%/InkFlow (packaged) or ./data (dev)

Output (JSON, one line):
    {"port": 4146, "token": "...", "pid": 43300, "version": "0.1.0", "path": "..."}

Exit 1 if kernel.json missing/invalid. Does NOT start the kernel.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def default_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(os.environ.get("APPDATA", Path.home())) / "InkFlow"
    return Path("./data")


def main() -> int:
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else default_data_dir()
    kj = data_dir / "kernel.json"
    if not kj.exists():
        print(f"kernel.json not found: {kj}", file=sys.stderr)
        return 1
    try:
        info = json.loads(kj.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        print(f"kernel.json invalid JSON: {err}", file=sys.stderr)
        return 1
    info["path"] = str(kj)
    print(json.dumps(info))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
