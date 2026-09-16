"""从 coverage 数据文件导出 function called-set（#1206 方案 B1）。

背景：`function-coverage` job 原先独立跑全量测试第二遍（`sys.settrace` 插件），与
`unit/api/cli/integration` 四个 job 的 `--cov` 重复执行（实测 19.5min/job）。

本模块改从**已有的 coverage 数据**反推 called-set，零额外测试开销：
coverage 只记录行命中、不含 `call` 事件；但「函数体的首个可执行语句被执行」⇒
函数体已被进入 ⇒ 该函数被调用过。与 `func_cov_plugin.py` 的「函数进入」语义
对死代码判定等价。

**首行必须取自 AST 的 body[0].lineno，不能取 `code.co_lines()` 首个 span**——
后者是 def 行本身（模块导入时就执行），会把从未调用的函数误判为已调用
（本机实测：`never_called` 的 def 行落在 measured lines 里）。

键形态与 settrace 版一致（`f"{relpath}:{co_qualname}"`），故门禁脚本
`check_func_coverage.py` 无需改动。

用法: python ci_cd/coverage_called.py <src_root> <out.json> <data.dat> [...]
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import coverage


def body_first_lines(tree: ast.AST) -> dict[str, int]:
    """AST 遍历 → {qualname: 函数体首个**可执行**语句行号}，qualname 口径同 `co_qualname`。

    嵌套函数插 `<locals>`、类插类名（与 `check_func_coverage.py` 的
    `_collect_functions` 同算法，确保键能对上）。

    **必须跳过 docstring / 纯常量表达式**：coverage 不记录无字节码的行，
    docstring 行永远不在 measured lines 里（本机实测 `core/config.py`：
    用 `body[0].lineno` 只命中 1/13，跳过 docstring 后 12/13）。
    装饰器不影响（`body` 不含装饰器，且装饰器行由外层负责）。

    无任何可执行语句（`...` / `pass` / 仅 docstring）→ 不入表，与
    `_is_abstract_body` 的豁免口径天然一致。
    """
    out: dict[str, int] = {}

    def walk(node: ast.AST, qualname: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = f"{qualname}.{node.name}" if qualname else node.name
            lineno = _first_executable_lineno(node)
            if lineno is not None:
                out[name] = lineno
            child = f"{name}.<locals>"
        elif isinstance(node, ast.ClassDef):
            name = f"{qualname}.{node.name}" if qualname else node.name
            child = name
        else:
            child = qualname
        for sub in ast.iter_child_nodes(node):
            walk(sub, child)

    walk(tree, "")
    return out


def _first_executable_lineno(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int | None:
    """函数体内首个会产生字节码的语句行号（跳过 docstring 与纯常量表达式）。"""
    for stmt in node.body:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue  # docstring / 纯常量：coverage 不记录该行
        return stmt.lineno
    return None


def _relpath(filename: str, src_root: Path) -> str | None:
    """coverage 数据里的文件名 → `inkflow/...` posix 相对路径，否则 None。

    **必须在 windows 与 ubuntu 两种 runner 上都成立**：数据由 windows job 产出，
    里面的路径是 `src\\inkflow\\a.py`（反斜杠 + 相对 cwd）；在 ubuntu 上
    `Path("src\\inkflow\\a.py").resolve()` 会把整串当成**单个文件名**，
    于是相对 src_root 解析失败 → 导出 0 条（本 issue CI 实测踩中）。
    故一律先把反斜杠归一为 `/`，再用纯字符串前缀匹配，不依赖平台 Path 语义。
    """
    normalized = filename.replace("\\", "/")
    # 绝对路径（含盘符或前导 /）→ 截取 src_root 之后的片段
    root = src_root.as_posix().replace("\\", "/").rstrip("/")
    if normalized.lower().startswith(root.lower() + "/"):
        return normalized[len(root) + 1 :]
    # 相对路径（如 `src/inkflow/a.py`）→ 去掉前导 `src/` 一类前缀
    for marker in ("inkflow/",):
        idx = normalized.rfind(marker)
        if idx >= 0:
            return normalized[idx:]
    return None


def called_from_coverage_data(data_files: list[str], src_root: str) -> set[str]:
    """多份 coverage 数据文件取并集 → called-set（仅 src_root/inkflow 下）。"""
    src = Path(src_root)
    union: set[str] = set()
    for data_file in data_files:
        cov = coverage.Coverage(data_file=data_file)
        cov.load()
        data = cov.get_data()
        for filename in data.measured_files():
            rel = _relpath(filename, src)
            if rel is None or not rel.startswith("inkflow/"):
                continue
            lines = set(data.lines(filename) or [])
            if lines:
                union |= _keys_for_file(filename, rel, lines, src)
    return union


def _keys_for_file(filename: str, rel: str, exec_lines: set[int], src_root: Path) -> set[str]:
    source = _read_source(filename, rel, src_root)
    if source is None:
        return set()
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()
    return {
        f"{rel}:{qualname}"
        for qualname, first in body_first_lines(tree).items()
        if first in exec_lines
    }


def _read_source(filename: str, rel: str, src_root: Path) -> bytes | None:
    """读函数所在源文件。

    先用数据里的原始路径（本机 / 同平台回放有效）；失败则用 src_root + rel 重组
    （数据由 windows job 产出、在 ubuntu runner 分析时的必经路径——原始串是
    `src\\inkflow\\...` 反斜杠相对路径，ubuntu 上读不到）。
    """
    for candidate in (Path(filename), src_root / rel, Path(rel)):
        try:
            return candidate.read_bytes()
        except OSError:
            continue
    return None


def verify_expected_tracks(files: list[Path], expected: list[str]) -> None:
    """校验各轨 artifact 齐全——缺轨会静默算出偏低但合法的百分比 = 假绿。"""
    if not files:
        raise ValueError("no coverage data files provided")
    names = [Path(f).name for f in files]
    missing = [t for t in expected if not any(t in n for n in names)]
    if missing:
        raise ValueError(f"missing coverage data for track(s): {missing} (got {names})")


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__, file=sys.stderr)
        return 2
    src_root, out_path = sys.argv[1], sys.argv[2]
    data_files = sys.argv[3:]
    called = called_from_coverage_data(data_files, src_root)
    Path(out_path).write_text(json.dumps({"callable": sorted(called)}), encoding="utf-8")
    print(
        f"[coverage_called] {len(called)} called functions from "
        f"{len(data_files)} file(s) -> {out_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
