"""Verify target paths exist in the kernel's OpenAPI spec.

Usage:
    uv run python openapi_check.py <port> <token> [path ...]
    # path defaults: /api/v1/writing/stream /api/v1/provider-configs /api/v1/agent-templates

Output: one line per path: OK / MISSING. Exit 0 if all present, 1 otherwise.
Purpose: catches "tests green but router not assembled" defects (release-verification pattern 1).
"""

from __future__ import annotations

import json
import sys
import urllib.request


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    port, token = sys.argv[1], sys.argv[2]
    paths = sys.argv[3:] or [
        "/api/v1/writing/stream",
        "/api/v1/provider-configs",
        "/api/v1/agent-templates",
    ]
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/openapi.json",
        headers={"X-InkFlow-Token": token},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            spec = json.loads(resp.read())
    except Exception as err:  # noqa: BLE001 - report any fetch failure
        print(f"openapi fetch failed: {err}", file=sys.stderr)
        return 1
    known = set(spec.get("paths", {}).keys())
    missing = [p for p in paths if p not in known]
    for p in paths:
        print(f"{'OK' if p in known else 'MISSING'} {p}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
