"""Function-coverage gate (standard definition) for src/inkflow.

Usage: python ci_cd/check_func_coverage.py <src_root> <called_json> <exempt_json>
       <baseline_json> [--delta D]

Discovers every function in src/inkflow via AST, diffs the called-set, applies the
exemption list, and gates with the A-rule:
  current % >= baseline_pct - delta  AND  0 new uncalled functions.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path


def _is_abstract_body(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True for an abstract/placeholder body (no executable statements).

    Mirrors ADR-027's exclude_lines for Protocol interface files: methods whose
    body is only a docstring, ``...``, ``pass``, or a bare ``raise NotImplementedError``
    are structurally uncallable and must not count toward function coverage.
    """
    for stmt in node.body:
        if isinstance(stmt, ast.Expr):
            val = stmt.value
            if isinstance(val, ast.Constant) and (
                val.value is Ellipsis or isinstance(val.value, str)
            ):
                continue  # docstring or Ellipsis placeholder
            return False
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Raise):
            exc = stmt.exc
            if (
                isinstance(exc, ast.Call)
                and getattr(exc.func, "attr", None) == "NotImplementedError"
            ):
                continue
            return False
        return False
    return True


def _collect_functions(node: ast.AST, qualname: str, rel: str, out: set[str]) -> None:
    """Recursively collect function keys, mirroring CPython's code.co_qualname."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        name = f"{qualname}.{node.name}" if qualname else node.name
        if not _is_abstract_body(node):
            out.add(f"{rel}:{name}")
        child_qualname = f"{name}.<locals>"
    elif isinstance(node, ast.ClassDef):
        name = f"{qualname}.{node.name}" if qualname else node.name
        child_qualname = name
    else:
        child_qualname = qualname
    for child in ast.iter_child_nodes(node):
        _collect_functions(child, child_qualname, rel, out)


def discover_functions(src_root: str) -> set[str]:
    """Walk src_root/inkflow/**/*.py and return keys for every def/async def.

    Excludes functions whose body is exactly a single Ellipsis (Protocol abstract
    methods). Qualnames match CPython's code.co_qualname: function bodies introduce
    '<locals>' scope, class bodies introduce class scope, other nodes keep the prefix.
    """
    functions: set[str] = set()
    package = Path(src_root) / "inkflow"
    if not package.is_dir():
        return functions
    base = Path(src_root)
    for py_file in sorted(package.rglob("*.py")):
        rel = py_file.relative_to(base).as_posix()
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        _collect_functions(tree, "", rel, functions)
    return functions


def load_called(called_json: str) -> set[str]:
    """Read the called-set JSON: dict with 'callable' list, or a plain list."""
    data = json.loads(Path(called_json).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("callable", [])
    return {str(key) for key in data}


def load_exemption(exempt_json: str) -> dict:
    """Read the exemption config with defaults: patterns=[], qualnames=[], body_ellipsis=True."""
    data = json.loads(Path(exempt_json).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        data = {}
    return {
        "patterns": list(data.get("patterns", [])),
        "qualnames": list(data.get("qualnames", [])),
        "body_ellipsis": bool(data.get("body_ellipsis", True)),
    }


def split_exemption(all_fns: set[str], exempt: dict) -> tuple[set[str], set[str]]:
    """Return (valid_fns, exempted_fns) per the exemption patterns and qualnames."""
    qualnames = set(exempt.get("qualnames", []))
    patterns = list(exempt.get("patterns", []))
    exempted: set[str] = set()
    for key in all_fns:
        qualname = key.rsplit(":", 1)[-1]
        if key in qualnames or any(re.search(pattern, qualname) for pattern in patterns):
            exempted.add(key)
    valid = all_fns - exempted
    return valid, exempted


def compute_uncalled(valid_fns: set[str], called: set[str]) -> tuple[set[str], float]:
    """Return (uncalled, pct) where pct = called among valid / valid, rounded to 2."""
    uncalled = valid_fns - called
    if not valid_fns:
        return uncalled, 0.0
    pct = round(len(valid_fns & called) / len(valid_fns) * 100, 2)
    return uncalled, pct


def apply_gate(
    pct: float,
    baseline_pct: float,
    delta: float,
    uncalled: set[str],
    baseline_uncalled: set[str],
) -> tuple[bool, list[str]]:
    """A-rule gate: pct >= baseline - delta and no new uncalled functions."""
    failures: list[str] = []
    if pct < baseline_pct - delta:
        failures.append(
            f"coverage {pct:.2f}% is below baseline {baseline_pct:.2f}% - delta {delta:.2f}%"
        )
    new_uncalled = uncalled - baseline_uncalled
    if new_uncalled:
        failures.append(f"new uncalled functions: {sorted(new_uncalled)}")
    return failures == [], failures


def main() -> int:
    """CLI entry point; returns 0 when the gate passes, else 1."""
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return 0
    args = list(sys.argv[1:])
    delta = 1.0
    if "--delta" in args:
        idx = args.index("--delta")
        if idx + 1 >= len(args):
            print("error: --delta requires a value", file=sys.stderr)
            return 2
        delta = float(args[idx + 1])
        del args[idx : idx + 2]
    if len(args) != 4:
        print(__doc__, file=sys.stderr)
        return 2
    src_root, called_json, exempt_json, baseline_json = args

    all_fns = discover_functions(src_root)
    called = load_called(called_json)
    exempt = load_exemption(exempt_json)
    valid, exempted = split_exemption(all_fns, exempt)
    uncalled, pct = compute_uncalled(valid, called)

    baseline = json.loads(Path(baseline_json).read_text(encoding="utf-8"))
    baseline_pct = float(baseline.get("baseline_pct", 0.0))
    baseline_uncalled = set(baseline.get("baseline_uncalled", []))

    print(f"total valid functions: {len(valid)}")
    print(f"called count: {len(valid & called)}")
    print(f"exemption count: {len(exempted)}")
    print(f"function coverage: {pct:.2f}% (baseline {baseline_pct:.2f}%, delta {delta:.2f}%)")
    if uncalled:
        print("uncalled functions:")
        for key in sorted(uncalled):
            print(f"  {key}")

    ok, failures = apply_gate(pct, baseline_pct, delta, uncalled, baseline_uncalled)
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    if ok:
        print("OK: function coverage gate passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
