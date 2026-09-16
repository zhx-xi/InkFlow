"""#1208 口径回归守护 —— 防止「首行判定」退化回无 line event 语句的假阴性。

背景（issue #1208 实测根因）：
`_first_executable_lineno` 只跳过了 docstring / 纯常量表达式，漏掉同族的
另外三类**不发射 line event** 的语句。首语句命中这些语句时，coverage 永不记录
该行 → 函数被**永久误判为未调用**。实测影响 18 个函数（全部有体内命中行，
即真的在跑）：

| 机制 | 条数 | 例 |
|---|---|---|
| `global X` 作函数体首语句 | 12 | `api/deps.py:get_vector_store` |
| `nonlocal X` 作首语句 | 2 | `cli/commands/write.py:next.<locals>._impl` |
| 裸注解 `x: T`（无值）作首语句 | 3 | `core/log.py:InterceptHandler.emit` |
| 多行括号 `if (`（event 落续行） | 1 | `chat_message_service.create_conversation` |

本文件锁死这四类：**首语句必须跳过前三类；传入 exec_lines 时须回退到续行**。
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
G = None
H = None


def global_first():
    """doc."""
    global G
    G = 1
    return G


def global_then_if():
    """doc."""
    global H
    if H is None:
        H = []
    return H


def nonlocal_first():
    """doc."""
    total = 0

    def inner():
        """doc."""
        nonlocal total
        total += 1
        return total

    return inner


def bare_annotation_first():
    """doc."""
    result: int
    result = 7
    return result


def annotation_with_value_first():
    """doc."""
    result: int = 8
    return result


def normal_first():
    """doc."""
    x = 1
    return x


def only_global():
    """doc."""
    global G


def multiline_if_first(flag):
    """doc."""
    if (
        flag
        and flag > 0
    ):
        return 1
    return 0
'''


def _fn(name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(_SRC)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"固件缺函数 {name}")


def test_global_first_stmt_skipped() -> None:
    """`global G` 作首语句 → 跳过，停在 `G = 1`。"""
    node = _fn("global_first")
    assert isinstance(node.body[0], ast.Expr), "固件假设：body[0] 是 docstring"
    assert isinstance(node.body[1], ast.Global), "固件假设：body[1] 是 global"
    assert body_first_lines(ast.parse(_SRC))["global_first"] == node.body[2].lineno


def test_global_then_if_lands_on_if() -> None:
    """`global H` 后紧跟 `if` → 停在 if 行。"""
    node = _fn("global_then_if")
    assert isinstance(node.body[1], ast.Global)
    assert body_first_lines(ast.parse(_SRC))["global_then_if"] == node.body[2].lineno


def test_nonlocal_first_stmt_skipped() -> None:
    """`nonlocal` 作首语句 → 跳过，停在 `total += 1`。"""
    tree = ast.parse(_SRC)
    inner = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "inner"
    )
    assert isinstance(inner.body[1], ast.Nonlocal)
    lines = body_first_lines(tree)
    assert lines["nonlocal_first.<locals>.inner"] == inner.body[2].lineno


def test_bare_annotation_first_stmt_skipped() -> None:
    """裸注解 `result: int`（无值）→ 跳过，停在 `result = 7`。"""
    node = _fn("bare_annotation_first")
    assert isinstance(node.body[1], ast.AnnAssign) and node.body[1].value is None
    assert body_first_lines(ast.parse(_SRC))["bare_annotation_first"] == node.body[2].lineno


def test_annotation_with_value_not_skipped() -> None:
    """带值的注解 `result: int = 8` **有** line event → 不得误跳（防过度跳过）。"""
    node = _fn("annotation_with_value_first")
    assign = node.body[1]
    assert isinstance(assign, ast.AnnAssign) and assign.value is not None
    assert body_first_lines(ast.parse(_SRC))["annotation_with_value_first"] == assign.lineno


def test_only_global_excluded() -> None:
    """函数体只有 `global`（无可记录语句）→ 不入表（等同抽象方法体豁免）。"""
    assert "only_global" not in body_first_lines(ast.parse(_SRC))


def test_normal_function_unaffected() -> None:
    """常规函数不受影响（跳过逻辑不得误伤）。"""
    node = _fn("normal_first")
    assert body_first_lines(ast.parse(_SRC))["normal_first"] == node.body[1].lineno


def test_multiline_condition_falls_back_to_continuation() -> None:
    """传入 exec_lines 时，多行 `if (` 回退到被记录的续行。

    固件显式给出「只记录续行、不记录 if 行」的 measured 集合，模拟真实
    coverage：`if (` 行不发 line event，续行才发。
    """
    node = _fn("multiline_if_first")
    if_stmt = node.body[1]
    assert isinstance(if_stmt, ast.If)
    continuation = if_stmt.test.lineno  # `flag` 所在续行
    assert continuation != if_stmt.lineno, "固件假设：条件跨多行"
    exec_lines = {continuation}
    lines = body_first_lines(ast.parse(_SRC), exec_lines)
    assert lines["multiline_if_first"] == continuation


def test_no_lineno_equals_global_or_nonlocal_line() -> None:
    """全量守护：任何一条都不得落在 global / nonlocal / 裸注解行（防整体退化）。"""
    tree = ast.parse(_SRC)
    lines = body_first_lines(tree)
    banned: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for stmt in node.body:
                if (
                    (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant))
                    or isinstance(stmt, (ast.Global, ast.Nonlocal))
                    or (isinstance(stmt, ast.AnnAssign) and stmt.value is None)
                ):
                    banned.add(stmt.lineno)
                else:
                    break
    assert banned, "固件应至少含一个不可记录行"
    for qualname, lineno in lines.items():
        assert lineno not in banned, f"{qualname} 落在了不可记录行 {lineno}"
