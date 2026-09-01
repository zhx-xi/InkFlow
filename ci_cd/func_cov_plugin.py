"""pytest plugin: session-level sys.settrace function-call recorder.

Records every function call whose code originates under ``src/inkflow`` using the
standard definition of function coverage (each function called >= 1 time).
The plugin is INERT unless the env var ``INKFLOW_FUNC_COV == "1"`` so it never
conflicts with the coverage.py C tracer used by other CI jobs.

Report format (JSON): {"callable": ["inkflow/<rel>:<qualname>", ...]}.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _get_src_root() -> str:
    """Return INKFLOW_FUNC_COV_SRC if set, else derive it from this file's location.

    Layout: ci_cd/func_cov_plugin.py -> repo root -> backend/src (the inkflow package
    source root). CI always sets INKFLOW_FUNC_COV_SRC explicitly; this fallback keeps
    local runs working without it.
    """
    override = os.environ.get("INKFLOW_FUNC_COV_SRC")
    if override:
        return override
    return str(Path(__file__).resolve().parents[1] / "backend" / "src")


_CALLS: set[str] = set()
_SRC_ROOT = _get_src_root()
_RELCACHE: dict[str, str | None] = {}


def normalize_src_relpath(filename: str, src_root: str) -> str | None:
    """Return posix relpath of `filename` relative to `src_root` (e.g. 'inkflow/a.py').

    Return None if filename is NOT under src_root. Handle Windows backslashes and
    forward slashes. Use Path(filename).resolve().relative_to(Path(src_root).resolve()),
    ValueError -> None. The returned path must use forward slashes (as_posix()).
    """
    try:
        return Path(filename).resolve().relative_to(Path(src_root).resolve()).as_posix()
    except ValueError:
        return None


def build_key(relpath: str, qualname: str) -> str:
    """Return f'{relpath}:{qualname}'."""
    return f"{relpath}:{qualname}"


def should_capture(filename: str, src_root: str) -> bool:
    """Return True iff the file lives under ``src_root/inkflow/``."""
    rel = normalize_src_relpath(filename, src_root)
    return rel is not None and rel.startswith("inkflow/")


def func_trace(frame, event, arg) -> None:
    """sys.settrace callback: record every 'call' event under src/inkflow."""
    if event != "call":
        return
    filename = frame.f_code.co_filename
    rel = _RELCACHE.get(filename)
    if rel is None and filename not in _RELCACHE:  # first time for this file
        rel = normalize_src_relpath(filename, _SRC_ROOT)
        _RELCACHE[filename] = rel
    if rel is None or not rel.startswith("inkflow/"):
        return
    _CALLS.add(build_key(rel, frame.f_code.co_qualname))
    return


def pytest_sessionstart(session) -> None:
    """Arm the tracer (and reset state) only when INKFLOW_FUNC_COV == '1'."""
    if os.environ.get("INKFLOW_FUNC_COV") != "1":
        return
    _CALLS.clear()
    sys.settrace(func_trace)


def pytest_sessionfinish(session, exitstatus) -> None:
    """Stop the tracer and write the called-set to the report JSON file."""
    if os.environ.get("INKFLOW_FUNC_COV") != "1":
        return
    sys.settrace(None)
    report = os.environ.get("INKFLOW_FUNC_COV_REPORT", "func_coverage_called.json")
    with open(report, "w", encoding="utf-8") as f:
        json.dump({"callable": sorted(_CALLS)}, f)
