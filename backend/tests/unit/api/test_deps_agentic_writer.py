"""F59-M4 (#965) deps_agentic_writer 契约（惰性 db 代理 + re-export 同一性）。

契约（镜像 deps_chat_agent.py 先例）：
- `_get_db` 在**调用期**经 `inkflow.api.deps.get_db` 惰性解析（规避 deps ↔ 本模块
  模块级循环 import——deps.py 在 import 本模块时尚未定义 get_db），并原样透传其
  yield 的 session。
- deps.py 的 re-export 必须是**同一函数对象**（writing.py 与单测从
  `inkflow.api.deps` 导入的命名空间契约）。

存在理由：func-coverage 门禁要求新函数被测试执行≥1 次；本文件同时锁定上述两条
架构契约，防未来改回模块级直取（循环 import）或复制函数体（命名空间漂移）。
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_get_db_lazy_proxy_forwards_sessions(monkeypatch) -> None:
    """_get_db 调用期解析 deps.get_db 并透传 session（循环 import 规避契约）。"""
    import inkflow.api.deps as deps_module
    from inkflow.api.deps_agentic_writer import _get_db

    sentinel = object()

    async def _fake_get_db():
        yield sentinel

    monkeypatch.setattr(deps_module, "get_db", _fake_get_db)

    collected = [session async for session in _get_db()]

    assert collected == [sentinel], "惰性代理必须透传 deps.get_db 的 session"


def test_get_agentic_writer_service_reexported_identity() -> None:
    """deps.py 的 re-export 是同一函数对象（writing.py/单测命名空间契约）。"""
    import inkflow.api.deps as deps_module
    import inkflow.api.deps_agentic_writer as module

    assert deps_module.get_agentic_writer_service is module.get_agentic_writer_service, (
        "deps.py 必须 re-export deps_agentic_writer 的同一函数（非复制体）"
    )
