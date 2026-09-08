"""F59-M4 RED (#965): build_agentic_writer 思考档位装配（spec §2.3 / contract B5）。

契约
----
- B5 ``build_agentic_writer`` 新增 keyword-only ``reasoning_effort: str | None = None``，
  透传 ``build_deep_agent(reasoning_effort=reasoning_effort)``：
  - 显式 ``reasoning_effort="high"`` → ``build_deep_agent`` kwargs 含该档位；
  - 缺省（None）→ ``build_deep_agent`` kwargs 的 ``reasoning_effort`` 为 ``None``。

RED 预期失败形态（当前实现）
--------------------------
- ``build_agentic_writer`` 现签名无 ``reasoning_effort`` 参数 → 传该关键字抛
  ``TypeError``（B5 缺功能，非语法错误）。
- 缺省守护用例：当前实现调用 ``build_deep_agent`` 未传 ``reasoning_effort`` → mock 记录
  kwargs 无该键 → ``m_da.call_args.kwargs.get('reasoning_effort')`` 为 ``None`` → PASS（刻意守护）。

patch 注入点 = agentic_writer 模块属性（from-import 绑定名快照，与 test_agentic_whitelist 同源）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.infrastructure.agent.agentic_writer import (
    AgenticWriterDeps,
    build_agentic_writer,
)
from inkflow.infrastructure.agent.tools.reader_tools import Tool

MODEL = "deepseek/deepseek-v4-flash"
API_KEY = "test-key"
BASE_URL = "https://example.test/v1"
BASE_PROMPT = "你是章节写手，负责按大纲撰写正文。"


def _fake_tool(name: str) -> Tool:
    """构造最小真实 Tool（spec.name 可断言，func 不执行）。"""
    return Tool(
        spec=ToolSpec(name=name, description="", input_schema={}),
        func=MagicMock(),
    )


def _make_deps(**overrides) -> AgenticWriterDeps:
    """构造 AgenticWriterDeps（6 个 AsyncMock service，可按名覆盖）。"""
    deps = AgenticWriterDeps(
        character_service=AsyncMock(),
        foreshadowing_service=AsyncMock(),
        summary_service=AsyncMock(),
        chapter_audit_service=AsyncMock(),
        draft_service=AsyncMock(),
        audit_service=AsyncMock(),
    )
    for key, value in overrides.items():
        setattr(deps, key, value)
    return deps


class TestBuildAgenticWriterReasoningEffort:
    """B5 build_agentic_writer → build_deep_agent reasoning_effort 透传。"""

    @patch("inkflow.infrastructure.agent.agentic_writer.build_deep_agent")
    @patch("inkflow.infrastructure.agent.agentic_writer.build_save_draft_tool")
    @patch("inkflow.infrastructure.agent.agentic_writer.build_reader_tools")
    def test_explicit_high_passed_to_deep_agent(self, m_rt, m_sd, m_da) -> None:
        """显式 reasoning_effort='high' → build_deep_agent kwargs 含 reasoning_effort='high'。"""
        m_rt.return_value = [_fake_tool("count_words")]
        m_sd.return_value = _fake_tool("save_draft")

        build_agentic_writer(
            model=MODEL,
            api_key=API_KEY,
            base_url=BASE_URL,
            deps=_make_deps(),
            system_prompt=BASE_PROMPT,
            reasoning_effort="high",
        )

        assert m_da.call_args.kwargs.get("reasoning_effort") == "high", (
            f"build_agentic_writer 必须透传档位给 build_deep_agent（B5），"
            f"实得 kwargs={m_da.call_args.kwargs!r}"
        )

    @patch("inkflow.infrastructure.agent.agentic_writer.build_deep_agent")
    @patch("inkflow.infrastructure.agent.agentic_writer.build_save_draft_tool")
    @patch("inkflow.infrastructure.agent.agentic_writer.build_reader_tools")
    def test_default_none_passed_to_deep_agent(self, m_rt, m_sd, m_da) -> None:
        """缺省（未传 reasoning_effort）→ build_deep_agent kwargs 的 reasoning_effort 为 None。"""
        m_rt.return_value = [_fake_tool("count_words")]
        m_sd.return_value = _fake_tool("save_draft")

        build_agentic_writer(
            model=MODEL,
            api_key=API_KEY,
            base_url=BASE_URL,
            deps=_make_deps(),
            system_prompt=BASE_PROMPT,
        )

        assert m_da.call_args.kwargs.get("reasoning_effort") is None, (
            f"缺省时 build_deep_agent 的 reasoning_effort 应为 None（B5），"
            f"实得 kwargs={m_da.call_args.kwargs!r}"
        )
