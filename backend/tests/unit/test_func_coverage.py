"""函数覆盖门禁（标准定义）——契约测试（RED 阶段）。

契约对象：
- ci_cd/check_func_coverage.py —— 门禁脚本（纯函数，可导入测试）
- ci_cd/func_cov_plugin.py    —— pytest 会话级 sys.settrace 插件（纯路径/key 辅助函数可测）

标准定义：函数覆盖 = 每个函数至少被调用 ≥1 次（非 coverage.py 的 functions 字段）。
门禁规则（A 方案）：当前覆盖率 ≥ 基线−Δ 且 0 新增未调用（豁免清单内除外）。

本文件在实现存在前整个模块 ImportError（RED：无插件时报错/未收集）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# ci_cd 不是包，手动插入 sys.path 供导入（E402 必须带理由）
_CI_CD = Path(__file__).resolve().parents[3] / "ci_cd"
if str(_CI_CD) not in sys.path:
    sys.path.insert(0, str(_CI_CD))

from check_func_coverage import (  # noqa: E402  # ci_cd 导入需先插入 sys.path
    apply_gate,
    compute_uncalled,
    discover_functions,
    load_called,
    load_exemption,
    split_exemption,
)
from func_cov_plugin import (  # noqa: E402  # ci_cd 导入需先插入 sys.path
    build_key,
    normalize_src_relpath,
    should_capture,
)

# ── 固件：合成源码树 ────────────────────────────────────────────────
_SRC_PKG = '''\
def top():
    return 1


class C:
    def m(self):
        return 2

    def n(self):
        def inner():
            return 3
        return inner

    def __init__(self):
        self.x = 0

    def __repr__(self):
        return "C()"


def cond():
    if True:
        def in_if():
            return 4
        return in_if
    return 5


async def a_fn():
    return 6


def proto() -> int: ...
'''


@pytest.fixture
def src_root(tmp_path: Path) -> Path:
    """合成 src/inkflow 源码树（src_root = tmp/src）。"""
    src = tmp_path / "src"
    pkg = src / "inkflow"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "a.py").write_text(_SRC_PKG, encoding="utf-8")
    return src


def _write_json(path: Path, data: object) -> str:
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


# ── 1. discover_functions ──────────────────────────────────────────
def test_discover_includes_nested_class_async(src_root: Path) -> None:
    fns = discover_functions(str(src_root))
    assert fns == {
        "inkflow/a.py:top",
        "inkflow/a.py:C.m",
        "inkflow/a.py:C.n",
        "inkflow/a.py:C.n.<locals>.inner",
        "inkflow/a.py:C.__init__",
        "inkflow/a.py:C.__repr__",
        "inkflow/a.py:cond",
        "inkflow/a.py:cond.<locals>.in_if",
        "inkflow/a.py:a_fn",
    }


def test_discover_excludes_body_ellipsis(src_root: Path) -> None:
    """Protocol 抽象方法体（body 仅 ...）不计数（同 ADR-027 exclude_lines 先例）。"""
    fns = discover_functions(str(src_root))
    assert not any("proto" in k for k in fns)


def test_discover_returns_empty_for_no_python(tmp_path: Path) -> None:
    assert discover_functions(str(tmp_path)) == set()


# ── 2. load_called ─────────────────────────────────────────────────
def test_load_called_dict_shape(tmp_path: Path) -> None:
    p = _write_json(tmp_path / "c.json", {"callable": ["inkflow/a.py:top", "inkflow/a.py:C.m"]})
    assert load_called(p) == {"inkflow/a.py:top", "inkflow/a.py:C.m"}


def test_load_called_plain_list(tmp_path: Path) -> None:
    p = _write_json(tmp_path / "c.json", ["inkflow/a.py:top"])
    assert load_called(p) == {"inkflow/a.py:top"}


def test_load_called_missing_file(tmp_path: Path) -> None:
    with pytest.raises((FileNotFoundError, OSError)):
        load_called(str(tmp_path / "nope.json"))


# ── 3. split_exemption ─────────────────────────────────────────────
def test_split_exemption_by_patterns() -> None:
    all_fns = {"inkflow/a.py:top", "inkflow/a.py:C.__init__", "inkflow/a.py:C.__repr__"}
    exempt = {"patterns": [".*__init__", ".*__repr__"], "qualnames": [], "body_ellipsis": True}
    valid, exempted = split_exemption(all_fns, exempt)
    assert valid == {"inkflow/a.py:top"}
    assert exempted == {"inkflow/a.py:C.__init__", "inkflow/a.py:C.__repr__"}


def test_split_exemption_exact_qualname() -> None:
    all_fns = {"inkflow/a.py:top", "inkflow/a.py:helper"}
    exempt = {"patterns": [], "qualnames": ["inkflow/a.py:helper"], "body_ellipsis": False}
    valid, exempted = split_exemption(all_fns, exempt)
    assert valid == {"inkflow/a.py:top"}
    assert exempted == {"inkflow/a.py:helper"}


def test_load_exemption_defaults(tmp_path: Path) -> None:
    p = _write_json(tmp_path / "e.json", {"patterns": [".*__repr__"]})
    ex = load_exemption(p)
    assert ex["patterns"] == [".*__repr__"]
    assert ex["qualnames"] == []
    assert ex["body_ellipsis"] is True


# ── 4. compute_uncalled ────────────────────────────────────────────
def test_compute_uncalled_and_pct() -> None:
    valid = {"a", "b", "c"}
    called = {"a", "b"}
    uncalled, pct = compute_uncalled(valid, called)
    assert uncalled == {"c"}
    assert pct == round(2 / 3 * 100, 2)


def test_compute_uncalled_empty_valid() -> None:
    uncalled, pct = compute_uncalled(set(), set())
    assert uncalled == set()
    assert pct == 0.0


# ── 5. apply_gate (A 方案：≥基线−Δ 且 0 新增未调用) ─────────────────
def test_gate_pass() -> None:
    ok, failures = apply_gate(66.67, 66.0, 1.0, {"c"}, {"c"})
    assert ok is True
    assert failures == []


def test_gate_fail_low_pct() -> None:
    ok, failures = apply_gate(64.0, 66.0, 1.0, {"c"}, {"c"})
    assert ok is False
    assert any("coverage" in f.lower() for f in failures)


def test_gate_fail_new_uncalled() -> None:
    ok, failures = apply_gate(66.67, 66.0, 1.0, {"c", "d"}, {"c"})
    assert ok is False
    assert any("new" in f.lower() for f in failures)


def test_gate_fail_both() -> None:
    ok, failures = apply_gate(50.0, 66.0, 1.0, {"c", "d"}, {"c"})
    assert ok is False
    assert len(failures) >= 2


# ── 6. plugin 纯辅助函数 ───────────────────────────────────────────
def test_build_key() -> None:
    assert build_key("inkflow/a.py", "C.m") == "inkflow/a.py:C.m"


def test_normalize_src_relpath_windows() -> None:
    assert normalize_src_relpath(r"D:\x\src\inkflow\a.py", r"D:\x\src") == "inkflow/a.py"
    assert normalize_src_relpath(r"D:\x\src\other.py", r"D:\x\src") == "other.py"
    assert normalize_src_relpath(r"D:\elsewhere\a.py", r"D:\x\src") is None


def test_normalize_src_relpath_posix() -> None:
    assert normalize_src_relpath("/x/src/inkflow/a.py", "/x/src") == "inkflow/a.py"


def test_should_capture() -> None:
    assert should_capture(r"D:\x\src\inkflow\a.py", r"D:\x\src") is True
    assert should_capture(r"D:\x\src\other.py", r"D:\x\src") is False
    assert should_capture(r"D:\tests\something.py", r"D:\x\src") is False
