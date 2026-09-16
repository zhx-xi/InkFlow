"""函数覆盖门禁 —— #1206 契约测试（RED 阶段）。

issue: https://github.com/zhx-xi/InkFlow/issues/1206
目标形态：各测试 job 顺带产出 called-set，`function-coverage` job 只「下载 + 合并 + 门禁」。
本文件只契约 **B1 方案**（从现有 `--cov` 数据导出 called-set）所需的新能力。

契约对象（尚不存在 → 本文件 RED：ImportError / AttributeError）：
- `ci_cd/coverage_called.py` —— 从 coverage 数据文件导出 called-set
  - `merge_called(inputs) -> set[str]` 已存在于 merge_func_cov_calls.py（复用，不重复测）

设计约束（来自既有实现，不可破坏）：
- key 形态 = `f"{relpath}:{qualname}"`，relpath 为 `inkflow/...` posix 相对路径
  （`build_key` / `normalize_src_relpath`，func_cov_plugin.py）
- qualname 对齐 CPython `co.code.co_qualname`，含 `Class.m.<locals>.inner`
  （`_collect_functions`，check_func_coverage.py）
- 门禁须能识别「缺轨」——缺轨时静默算出偏低的合法百分比 = 假绿（issue 阻塞 3）
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_CI_CD = Path(__file__).resolve().parents[3] / "ci_cd"
if str(_CI_CD) not in sys.path:
    sys.path.insert(0, str(_CI_CD))

from coverage_called import (  # noqa: E402  # ci_cd 导入需先插入 sys.path
    called_from_coverage_data,
    verify_expected_tracks,
)

# ── 固件：合成源码树 + 真实 coverage 数据 ───────────────────────────
_SRC = '''\
def top():
    return 1


class C:
    def m(self):
        return 2

    def n(self):
        def inner():
            return 3
        return inner


def never_called():
    return 4
'''


@pytest.fixture
def src_root(tmp_path: Path) -> Path:
    """合成 src/inkflow 源码树（src_root = tmp/src）。"""
    src = tmp_path / "src"
    pkg = src / "inkflow"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "a.py").write_text(_SRC, encoding="utf-8")
    return src


@pytest.fixture
def cov_data(tmp_path: Path, src_root: Path) -> str:
    """用真实 coverage API 采集一个只调用 top() 的会话，落盘 .coverage 数据文件。

    直接 `exec` 合成源码（不经 import 系统）——避免与真实 `inkflow` 包在
    sys.modules 里冲突（pytest importlib 模式下必然冲突）。
    """
    import coverage

    data_file = tmp_path / "cov" / "unit.dat"
    data_file.parent.mkdir(parents=True, exist_ok=True)
    src_file = src_root / "inkflow" / "a.py"
    cov = coverage.Coverage(data_file=str(data_file), include=[str(src_file)])
    cov.start()
    code = compile(src_file.read_bytes(), str(src_file), "exec")
    ns: dict = {"__name__": "inkflow.a", "__file__": str(src_file)}
    exec(code, ns)  # 测试固件：执行合成源码
    ns["top"]()
    cov.stop()
    cov.save()
    return str(data_file)


# ── 1. called_from_coverage_data：函数被调用 ⇒ 键进 called-set ──────
def test_called_from_coverage_data_returns_called_keys(cov_data: str, src_root: Path) -> None:
    """被调用的函数出现在 called-set（key 形态 = relpath:qualname）。"""
    called = called_from_coverage_data([cov_data], str(src_root))
    assert "inkflow/a.py:top" in called


def test_called_from_coverage_data_excludes_uncalled(cov_data: str, src_root: Path) -> None:
    """未被调用的函数不得出现（契约核心：这正是门禁要抓的死函数）。"""
    called = called_from_coverage_data([cov_data], str(src_root))
    assert "inkflow/a.py:never_called" not in called


def test_called_from_coverage_data_class_method_qualname(cov_data: str, src_root: Path) -> None:
    """类方法 qualname 与 ast 口径一致（`C.m`）。"""
    called = called_from_coverage_data([cov_data], str(src_root))
    assert "inkflow/a.py:top" in called
    # C.m 本次会话未被调用（只调了 top）→ 不得靠「文件被导入」蒙混过关
    assert "inkflow/a.py:C.m" not in called


def test_called_from_coverage_data_union_across_files(cov_data: str, src_root: Path) -> None:
    """多数据文件取并集（同 merge_func_cov_calls 语义）。"""
    called = called_from_coverage_data([cov_data, cov_data], str(src_root))
    assert "inkflow/a.py:top" in called


def test_called_from_coverage_data_ignores_files_outside_src(cov_data: str, src_root: Path) -> None:
    """src_root 之外的文件不产出键（防 ci_cd/ 自身污染，ADR-027 已约定）。"""
    called = called_from_coverage_data([cov_data], str(src_root))
    assert all(key.startswith("inkflow/") for key in called)


# ── 2. verify_expected_tracks：缺轨必须红（issue 阻塞 3：假绿防护）──
def test_verify_expected_tracks_raises_on_missing(tmp_path: Path) -> None:
    """声明的轨缺一个 → 抛错（缺轨会静默算出偏低合法百分比 = 假绿）。"""
    present = [tmp_path / f"{t}.dat" for t in ("unit", "api", "cli")]
    for p in present:
        p.write_bytes(b"x")
    with pytest.raises(ValueError, match="integration"):
        verify_expected_tracks(present, ["unit", "api", "cli", "integration"])


def test_verify_expected_tracks_passes_when_complete(tmp_path: Path) -> None:
    """四轨齐全 → 不抛错。"""
    files = []
    for t in ("unit", "api", "cli", "integration"):
        p = tmp_path / f"{t}.dat"
        p.write_bytes(b"x")
        files.append(p)
    verify_expected_tracks(files, ["unit", "api", "cli", "integration"])


def test_verify_expected_tracks_raises_on_empty_list() -> None:
    """空列表（artifact 全没下载到）→ 抛错，不得静默通过。"""
    with pytest.raises(ValueError):
        verify_expected_tracks([], ["unit"])
