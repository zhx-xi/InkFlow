"""#996 RED 契约测试 — build_agentic_writer 锚点透传（expected_source_outline_id/volume）.

契约真相源: specs/f27-writer-agent/spec.md §5.2「装配期锚点绑定」+ 拍板契约 H:
build_agentic_writer 新增形参 expected_source_outline_id/expected_volume_outline_id
（默认 None），透传进 SaveDraftToolDeps。

被测对象（当前未实现 H）:
    from inkflow.infrastructure.agent.agentic_writer import build_agentic_writer

patch 注入点（实测验证——from-import 绑定名快照，patch 源头模块对内部调用零影响）:
    inkflow.infrastructure.agent.agentic_writer.build_deep_agent
    inkflow.infrastructure.agent.agentic_writer.build_reader_tools
    inkflow.infrastructure.agent.agentic_writer.build_save_draft_tool

当前实现对照（全部 RED）:
- build_agentic_writer 签名无 expected_source_outline_id/expected_volume_outline_id
  → 传入两形参 → TypeError（unexpected keyword argument）。
- 未传时构建的 SaveDraftToolDeps 无两个锚点字段 → fields 存在性断言 FAILED。

镜像 test_agentic_whitelist.py 的 patch/捕获形态（本文件全部用例为同步函数，无需 asyncio mark）。
"""

from __future__ import annotations

import uuid
from dataclasses import fields
from unittest.mock import AsyncMock, MagicMock, patch

from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.infrastructure.agent.agentic_writer import (
    AgenticWriterDeps,
    build_agentic_writer,
)
from inkflow.infrastructure.agent.tools.reader_tools import Tool

# ── 常量 ──────────────────────────────────────

MODEL = "deepseek/deepseek-v4-flash"
API_KEY = "test-key"
BASE_URL = "https://example.test/v1"
BASE_PROMPT = "你是章节写手，负责按大纲撰写正文。"
SOURCE_OUTLINE_ID = uuid.UUID(int=51)
VOLUME_OUTLINE_ID = uuid.UUID(int=41)


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


def _captured_save_draft_deps(m_sd) -> object:
    """从 build_save_draft_tool 调用取回 SaveDraftToolDeps 实例（单位置参数）。"""
    m_sd.assert_called_once()
    assert m_sd.call_args.args, "build_save_draft_tool 应以位置参数收 SaveDraftToolDeps"
    return m_sd.call_args.args[0]


class TestBuildAgenticWriterAnchorPassthrough:
    """build_agentic_writer 锚点形参 → SaveDraftToolDeps 透传契约（#996 契约 H）。"""

    @patch("inkflow.infrastructure.agent.agentic_writer.build_deep_agent")
    @patch("inkflow.infrastructure.agent.agentic_writer.build_save_draft_tool")
    @patch("inkflow.infrastructure.agent.agentic_writer.build_reader_tools")
    def test_anchor_params_passed_to_save_draft_tool(
        self, m_rt, m_sd, m_da
    ) -> None:
        """【R】expected_source_outline_id/expected_volume_outline_id 透传进 SaveDraftToolDeps。

        当前 build_agentic_writer 无这两形参 → TypeError（RED）。
        """
        m_rt.return_value = []
        m_sd.return_value = _fake_tool("save_draft")
        m_da.return_value = MagicMock()

        build_agentic_writer(
            model=MODEL,
            api_key=API_KEY,
            base_url=BASE_URL,
            deps=_make_deps(),
            system_prompt=BASE_PROMPT,
            expected_source_outline_id=SOURCE_OUTLINE_ID,
            expected_volume_outline_id=VOLUME_OUTLINE_ID,
        )

        sd_deps = _captured_save_draft_deps(m_sd)
        assert getattr(sd_deps, "expected_source_outline_id", None) == SOURCE_OUTLINE_ID
        assert getattr(sd_deps, "expected_volume_outline_id", None) == VOLUME_OUTLINE_ID

    @patch("inkflow.infrastructure.agent.agentic_writer.build_deep_agent")
    @patch("inkflow.infrastructure.agent.agentic_writer.build_save_draft_tool")
    @patch("inkflow.infrastructure.agent.agentic_writer.build_reader_tools")
    def test_no_anchor_defaults_none(self, m_rt, m_sd, m_da) -> None:
        """【R】不传两形参 → SaveDraftToolDeps 两锚点字段存在且为 None（向后兼容默认）。

        当前 SaveDraftToolDeps 无两字段 → fields 存在性断言 FAILED（RED）。
        """
        m_rt.return_value = []
        m_sd.return_value = _fake_tool("save_draft")
        m_da.return_value = MagicMock()

        build_agentic_writer(
            model=MODEL,
            api_key=API_KEY,
            base_url=BASE_URL,
            deps=_make_deps(),
            system_prompt=BASE_PROMPT,
        )

        sd_deps = _captured_save_draft_deps(m_sd)
        field_names = {f.name for f in fields(type(sd_deps))}
        assert "expected_source_outline_id" in field_names
        assert "expected_volume_outline_id" in field_names
        assert getattr(sd_deps, "expected_source_outline_id", None) is None
        assert getattr(sd_deps, "expected_volume_outline_id", None) is None

    @patch("inkflow.infrastructure.agent.agentic_writer.build_deep_agent")
    @patch("inkflow.infrastructure.agent.agentic_writer.build_save_draft_tool")
    @patch("inkflow.infrastructure.agent.agentic_writer.build_reader_tools")
    def test_anchor_params_coexist_with_chapter_ids(self, m_rt, m_sd, m_da) -> None:
        """【R】锚点与既有 expected_project_id/expected_chapter_id 并存透传（无回归）。"""
        m_rt.return_value = []
        m_sd.return_value = _fake_tool("save_draft")
        m_da.return_value = MagicMock()
        project_id = uuid.UUID(int=7)
        chapter_id = uuid.UUID(int=8)

        build_agentic_writer(
            model=MODEL,
            api_key=API_KEY,
            base_url=BASE_URL,
            deps=_make_deps(),
            system_prompt=BASE_PROMPT,
            expected_project_id=project_id,
            expected_chapter_id=chapter_id,
            expected_source_outline_id=SOURCE_OUTLINE_ID,
            expected_volume_outline_id=VOLUME_OUTLINE_ID,
        )

        sd_deps = _captured_save_draft_deps(m_sd)
        assert getattr(sd_deps, "expected_project_id", None) == project_id
        assert getattr(sd_deps, "expected_chapter_id", None) == chapter_id
        assert getattr(sd_deps, "expected_source_outline_id", None) == SOURCE_OUTLINE_ID
        assert getattr(sd_deps, "expected_volume_outline_id", None) == VOLUME_OUTLINE_ID
