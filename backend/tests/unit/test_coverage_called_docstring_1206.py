"""#1206 B1 口径回归守护 —— 防止「首行判定」退化回 docstring 假阴性。

背景（本 issue 实测根因）：
朴素实现用 `ast` 的 `node.body[0].lineno` 当函数首行 → 撞上 docstring 行。
coverage **不记录 docstring 行**（无字节码）→ 命中率崩塌到 1/13
（`core/config.py` 实测），4 轨合并 called-set 从 3104 掉到 657，门禁大面积误红。

本文件锁死该行为：**首行必须跳过 docstring 与纯常量表达式**。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_CI_CD = Path(__file__).resolve().parents[3] / "ci_cd"
if str(_CI_CD) not in sys.path:
    sys.path.insert(0, str(_CI_CD))

from coverage_called import body_first_lines  # noqa: E402  # ci_cd 导入需先插入 sys.path

_SRC = '''\
def with_docstring():
    """文档字符串——coverage 不记录此行的字节码。"""
    return 1


def no_docstring():
    return 2


def docstring_only():
    """只有 docstring，无可执行语句（等同抽象方法体）。"""


def multi_docstring():
    """一行。"""
    """两行。"""
    x = 3
    return x


class C:
    """类文档字符串。"""

    def m(self):
        """方法文档字符串。"""
        return 4


def outer():
    def inner():
        """嵌套函数的 docstring。"""
        return 5
    return inner
'''


def _lines() -> dict[str, int]:
    return body_first_lines(ast.parse(_SRC))


def test_skips_docstring_line() -> None:
    """首行停在 return，而不是 docstring 行。"""
    tree = ast.parse(_SRC)
    lines = body_first_lines(tree)
    node = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "with_docstring"
    )
    assert node.body[0].lineno == node.body[1].lineno - 1, "固件假设：docstring 紧邻 return"
    assert lines["with_docstring"] == node.body[1].lineno


def test_no_docstring_unaffected() -> None:
    """无 docstring 的函数首行 = body[0]（跳过逻辑不得误跳）。"""
    tree = ast.parse(_SRC)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "no_docstring")
    assert body_first_lines(tree)["no_docstring"] == node.body[0].lineno


def test_docstring_only_function_excluded() -> None:
    """只有 docstring（无可执行语句）→ 不入表（等同抽象方法体豁免）。"""
    assert "docstring_only" not in _lines()


def test_multiple_constant_exprs_all_skipped() -> None:
    """连续多条纯常量表达式（多段 docstring）全部跳过，停在 `x = 3`。"""
    lines = _lines()
    tree = ast.parse(_SRC)
    node = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "multi_docstring"
    )
    assign = next(s for s in node.body if isinstance(s, ast.Assign))
    assert lines["multi_docstring"] == assign.lineno


def test_class_method_docstring_skipped() -> None:
    """类方法同样跳过 docstring。"""
    lines = _lines()
    tree = ast.parse(_SRC)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef))
    assert lines["C.m"] == method.body[1].lineno


def test_nested_function_docstring_skipped() -> None:
    """嵌套函数（qualname 含 <locals>）同样跳过 docstring。"""
    lines = _lines()
    tree = ast.parse(_SRC)
    outer = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "outer")
    inner = next(n for n in outer.body if isinstance(n, ast.FunctionDef))
    assert lines["outer.<locals>.inner"] == inner.body[1].lineno


def test_never_returns_docstring_lineno() -> None:
    """全量守护：任何一条都不能等于自己的 docstring 行（防整体退化）。"""
    tree = ast.parse(_SRC)
    lines = body_first_lines(tree)
    doc_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for stmt in node.body:
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                    doc_lines.add(stmt.lineno)
                else:
                    break
    assert doc_lines, "固件应至少含一个 docstring 行"
    for qualname, lineno in lines.items():
        assert lineno not in doc_lines, f"{qualname} 落在了 docstring 行 {lineno}"
