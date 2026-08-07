"""F30 内核冷启动基建 — 版本兼容校验测试契约（RED 阶段）。

本文件只为版本兼容校验函数定义测试契约（spec §5.4 版本兼容校验 /
§9 测试策略 M3；Q2 已拍板：major 相同即复用，minor/patch 容忍）。

GREEN 实现契约
--------------
公开名：``is_version_compatible(kernel_version: str, client_version: str)
-> bool``——位于 ``backend/src/inkflow/infrastructure/kernel/state.py``
（与状态读写同模块；spec §8 文件结构无独立 version.py，父侧授权本
docstring 钉死模块路径，GREEN 若拆分独立模块须同步改本文件 import）。

- 语义：两端版本字符串均经 ``packaging.version.Version`` 解析；
  ``major`` 相同 → True；``major`` 不同 → False；任一字符串解析失败
  （``InvalidVersion``）→ False。
- 方向无关：内核旧于/新于客户端均可，只要 major 相同即 True
  （spec §5.4：minor/patch 差异容忍，ADR-019 契约冻结语义）。
- 纯函数：无 I/O 无副作用，不读取 ``inkflow.__version__``——客户端
  版本由调用方传入（spec §3.2 ensure_kernel 内接线）。

RED 状态说明
------------
``inkflow.infrastructure.kernel.state`` 模块尚未实现，模块级 from-import
在收集期抛 ModuleNotFoundError，属预期 RED 信号；GREEN 实现后本文件即全绿。
"""

from inkflow.infrastructure.kernel.state import is_version_compatible


def test_is_version_compatible_same_major_returns_true():
    """① major 相同 → True（minor/patch 任意差异容忍，spec §5.4 / Q2）。"""
    assert is_version_compatible("1.2.0", "1.9.9") is True
    assert is_version_compatible("1.9.9", "1.2.0") is True  # 方向无关
    assert is_version_compatible("1.0.0", "1.0.0") is True


def test_is_version_compatible_different_major_returns_false():
    """② major 不同 → False（内核旧于/新于客户端均拒绝复用）。"""
    assert is_version_compatible("1.2.0", "2.0.0") is False
    assert is_version_compatible("2.0.0", "1.2.0") is False


def test_is_version_compatible_invalid_version_string_returns_false():
    """③ 非法版本字符串 → False（不抛异常，解析失败即不兼容）。"""
    assert is_version_compatible("not-a-version", "1.2.0") is False
    assert is_version_compatible("1.2.0", "not-a-version") is False
    assert is_version_compatible("", "1.2.0") is False
