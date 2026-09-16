"""#1206 跨平台路径契约 —— coverage 数据由 windows job 产出、在 ubuntu runner 分析。

**这是 CI 实测踩到的真 bug**（PR #1207 run 35074319620：`[coverage_called] 0 called
functions`，门禁 0.00% 红）：数据里的文件名是 `src\\inkflow\\api\\deps.py`
（Windows 反斜杠 + 相对 cwd），而 coverage-function job 跑在 **ubuntu** 上——
`Path("src\\inkflow\\api\\deps.py").resolve()` 会把整串当成**单个文件名**，
相对 src_root 解析必然失败 → 导出 0 条 → 门禁假红。

本文件锁死「反斜杠归一 + 不依赖平台 Path 语义」的行为。
"""

from __future__ import annotations

import sys
from pathlib import Path

_CI_CD = Path(__file__).resolve().parents[3] / "ci_cd"
if str(_CI_CD) not in sys.path:
    sys.path.insert(0, str(_CI_CD))

from coverage_called import _relpath  # noqa: E402  # ci_cd 导入需先插入 sys.path


def test_windows_backslash_relative_path() -> None:
    """Windows 相对路径（CI 实际形态）→ inkflow/... posix。"""
    got = _relpath("src\\inkflow\\api\\deps.py", Path("src"))
    assert got == "inkflow/api/deps.py"


def test_posix_relative_path() -> None:
    """POSIX 相对路径（本机/ubuntu 产出）→ 同样归一。"""
    got = _relpath("src/inkflow/api/deps.py", Path("src"))
    assert got == "inkflow/api/deps.py"


def test_windows_absolute_path() -> None:
    """Windows 绝对路径 → 截取 src_root 之后。"""
    got = _relpath(
        r"D:\develop\projects\InkFlow\backend\src\inkflow\core\config.py",
        Path("src"),
    )
    # 绝对路径含盘符，src 前缀匹配不上 → 回退 rfind("inkflow/")
    assert got == "inkflow/core/config.py"


def test_posix_absolute_path_under_src_root() -> None:
    """POSIX 绝对路径恰好在 src_root 下 → 正确剥离前缀。"""
    got = _relpath("/w/backend/src/inkflow/api/app.py", Path("/w/backend/src"))
    assert got == "inkflow/api/app.py"


def test_windows_path_case_insensitive_prefix() -> None:
    """盘符大小写差异不得破坏匹配（Windows 大小写不敏感）。"""
    got = _relpath(r"d:\w\Backend\Src\inkflow\x.py", Path(r"D:\w\backend\src"))
    assert got == "inkflow/x.py"


def test_non_inkflow_file_returns_none() -> None:
    """非 inkflow 路径（如 ci_cd/、第三方包）→ None，不得混入。"""
    assert _relpath("ci_cd/check_coverage.py", Path("src")) is None
    assert _relpath("/usr/lib/python3/site-packages/x.py", Path("src")) is None


def test_backslash_never_leaks_into_key() -> None:
    """键里绝不能出现反斜杠（门禁基线全用 posix，混入即全部误判为新增）。"""
    got = _relpath("src\\inkflow\\a.py", Path("src"))
    assert got is not None
    assert "\\" not in got


# ── ubuntu runner 语义：数据里是 windows 路径，原始串在本机/ubuntu 读不到 ──
def test_read_source_fallback_via_src_root(tmp_path: Path) -> None:
    """原始路径读不到时，用 src_root + rel 重组读到源码（CI ubuntu 的必经路径）。"""
    from coverage_called import _read_source

    pkg = tmp_path / "src" / "inkflow"
    pkg.mkdir(parents=True)
    (pkg / "a.py").write_bytes(b"x = 1\n")

    # 原始路径在不存在的位置（模拟 ubuntu 上的 `src\\inkflow\\a.py` 相对串）
    ghost = str(tmp_path / "nonexistent" / "src\\inkflow\\a.py")
    got = _read_source(ghost, "inkflow/a.py", tmp_path / "src")
    assert got == b"x = 1\n"


def test_read_source_returns_none_when_all_candidates_fail(tmp_path: Path) -> None:
    """全部候选都读不到 → None（不得抛异常中断整轮导出）。"""
    from coverage_called import _read_source

    assert _read_source(str(tmp_path / "ghost.py"), "inkflow/ghost.py", tmp_path / "src") is None


def test_read_source_prefers_original_path(tmp_path: Path) -> None:
    """原始路径可读时优先用它（同平台回放，不经重组）。"""
    from coverage_called import _read_source

    direct = tmp_path / "direct.py"
    direct.write_bytes(b"y = 2\n")
    # src_root/rel 指向另一个文件，原始路径应胜出
    alt = tmp_path / "src" / "inkflow"
    alt.mkdir(parents=True)
    (alt / "direct.py").write_bytes(b"z = 3\n")
    assert _read_source(str(direct), "inkflow/direct.py", tmp_path / "src") == b"y = 2\n"
