"""#1474 chat 管线设定注入 —— RED 契约（spec f47 §2.2 v1.4）。

问题（#1474 根因）：`builtin:chat` 的 stage prompt 模板（`_CHAT_ASSISTANT_PROMPT`）
只含 `{prompt}` 占位符——`_inject_context`（#366 G1）已把角色/世界观/伏笔/大纲摘要
装配进 `variables.setting`，但模板不消费它 → `_render` 时 setting 被忽略，
**LLM 完全看不到项目设定**（Agent 只能索要设定）；与 f47 §2.2「对话助手可感知项目
设定」的承诺相反（spec/实现漂移）。

契约（本文件锁定）：
- chat stage 渲染后的 system 消息含 `{setting}` 块的各设定源条目
  （角色 / 世界观 / 伏笔 / 大纲）——即 chat 走与写作轨同一套 ContextAssembly 产出；
- 对照不回归：`builtin:write_auto` 的 architect stage 仍完整拿到设定块；
- 负例：chat 不引入设定以外的新调用——不带 `chapter_id` 时不得触发前文摘要
  （`summary_service.ensure_summary`），即不跑 plan / 不产生写章副作用。

实现前必须实测 FAIL（当前 setting 探针 0 命中）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.agent_pipeline import PipelineExecuteRequest
from inkflow.domain.models.project import Project, ProjectConfig
from inkflow.domain.services.agent_service import AgentService
from inkflow.infrastructure.agent.pipeline_nodes import _build_messages

PROJECT_ID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
pytestmark = pytest.mark.asyncio

# 各设定源特征词（写入替身，断言渲染后的 system 消息携带）
_CHAR_PROBE = "角色探针CHARPROBE"
_WORLD_PROBE = "世界探针WORLDPROBE"
_FS_PROBE = "伏笔探针FSPROBE"
_OUTLINE_PROBE = "大纲探针OUTLINEPROBE"


def _make_project() -> Project:
    return Project(
        id=PROJECT_ID,
        name="测试项目",
        tags=["玄幻"],
        language="zh-CN",
        target_words=100000,
        config=ProjectConfig(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class _ProjRepo:
    async def get(self, _pid):
        return _make_project()


class _ChapterRepo:
    async def get_chapter(self, _cid):
        return None


class _CharRepo:
    async def list(self, _pid, limit=50):
        return (
            [
                SimpleNamespace(
                    id=uuid.uuid4(),
                    name="角色甲",
                    personality=_CHAR_PROBE,
                    background=None,
                    goals=None,
                )
            ],
            1,
        )


class _WorldRepo:
    async def list(self, _pid, limit=50):
        return (
            [SimpleNamespace(id=uuid.uuid4(), name="世界观甲", content=_WORLD_PROBE)],
            1,
        )


class _FsRepo:
    async def list_open(self, _pid):
        return [SimpleNamespace(id=uuid.uuid4(), title="伏笔甲", description=_FS_PROBE)]


class _OutlineRepo:
    async def list(self, _pid, limit=50):
        return (
            [SimpleNamespace(id=uuid.uuid4(), name="总纲", description=_OUTLINE_PROBE)],
            1,
        )


def _build_svc(*, summary_service=None) -> AgentService:
    """装配 AgentService（stub 仓储：全设定源 + 可注入 summary_service）。"""
    return AgentService(
        pipeline=MagicMock(),
        db_session=None,
        store=MagicMock(),
        project_repo=_ProjRepo(),
        chapter_repo=_ChapterRepo(),
        agent_repo=None,
        character_repo=_CharRepo(),
        world_repo=_WorldRepo(),
        outline_repo=_OutlineRepo(),
        foreshadowing_repo=_FsRepo(),
        summary_service=summary_service,
    )


def _chat_request() -> PipelineExecuteRequest:
    return PipelineExecuteRequest(
        project_id=PROJECT_ID,
        pipeline="builtin:chat",
        variables={"prompt": "请核对主角与师妹的关系是否符合设定"},
        chapter_id=None,
    )


def _render_system_prompt(stages, context) -> str:
    """按 pipeline_nodes 真实渲染链路产出某 stage 的 system 消息内容。"""
    state = {
        "context": context,
        "stages": {s.id: s for s in stages},
        "llm_client": None,
        "results": {},
    }
    stage = stages[0]
    messages = _build_messages(state, stage, list(stage.input_from))
    assert messages[0].role == "system"
    return messages[0].content


async def test_chat_prompt_contains_setting_sources() -> None:
    """chat stage 渲染后的 system 消息含角色/世界观/伏笔/大纲四源设定（#1474 当前 FAIL）。"""
    svc = _build_svc()
    stages, context, *_ = await svc._build_pipeline_context(_chat_request())
    await svc._inject_context(context, continue_context=False)

    system = _render_system_prompt(stages, context)
    for probe in (_CHAR_PROBE, _WORLD_PROBE, _FS_PROBE, _OUTLINE_PROBE):
        assert probe in system, f"chat system prompt 应含设定块（#1474 当前 0 命中）：{probe}"


async def test_chat_prompt_still_renders_user_prompt() -> None:
    """chat 设定注入不破坏既有 `{prompt}` 渲染（user 提问仍在）。"""
    svc = _build_svc()
    stages, context, *_ = await svc._build_pipeline_context(_chat_request())
    await svc._inject_context(context, continue_context=False)

    system = _render_system_prompt(stages, context)
    assert "请核对主角与师妹的关系是否符合设定" in system


async def test_write_auto_stage_still_gets_setting() -> None:
    """对照不回归：write_auto 的 architect stage 仍完整拿到设定块。"""
    svc = _build_svc()
    request = PipelineExecuteRequest(project_id=PROJECT_ID, pipeline="builtin:write_auto")
    stages, context, *_ = await svc._build_pipeline_context(request)
    await svc._inject_context(context, continue_context=False)

    state = {
        "context": context,
        "stages": {s.id: s for s in stages},
        "llm_client": None,
        "results": {},
    }
    architect = next(s for s in stages if s.id == "architect")
    messages = _build_messages(state, architect, list(architect.input_from))
    system = messages[0].content
    for probe in (_CHAR_PROBE, _WORLD_PROBE, _FS_PROBE, _OUTLINE_PROBE):
        assert probe in system, f"write_auto architect 应含设定：{probe}"


async def test_chat_without_chapter_does_not_trigger_summary() -> None:
    """负例：chat 不带 chapter_id → 不触发前文摘要（无 skill 以外的新调用）。"""
    summary_service = MagicMock()
    summary_service.ensure_summary = AsyncMock(return_value="不应被调用")

    svc = _build_svc(summary_service=summary_service)
    _stages, context, *_ = await svc._build_pipeline_context(_chat_request())
    await svc._inject_context(context, continue_context=False)

    summary_service.ensure_summary.assert_not_awaited()
    assert "context" not in context.variables
