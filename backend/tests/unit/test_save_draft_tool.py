"""F27 M2 写工具 RED 契约测试 — save_draft（agent 唯一写面，草稿落库 + 单事务 + 审计）.

被测模块（全部未实现，1c 整模块 RED 形态；全部顶部 import——全文件收集期失败是
预期（pytest exit 2 / collected 0 items / 1 error），GREEN 落地后整文件自动收集）:
    from inkflow.infrastructure.agent.tools.save_draft_tool import (
        SaveDraftParams, build_save_draft_tool,
    )

设计假设（父侧定稿契约，GREEN 按此实现）
----------------------------------------
1. save_draft 工具（infrastructure/agent/tools/save_draft_tool.py 新建）:

       class SaveDraftParams(BaseModel):
           '''save_draft 工具参数（spec §5.2）.'''
           project_id: uuid.UUID
           chapter_id: uuid.UUID | None = None   # 目标章节（可选，确认时指定）
           content: str                          # 草稿正文（Markdown）
           summary: str | None = None            # 一句话说明（用户确认时展示）

       @dataclass
       class SaveDraftToolDeps:
           '''写工具工厂依赖 — service 实例注入（鸭子类型，镜像 ReaderToolDeps）.'''
           draft_service: object    # 有 create(*, project_id, chapter_id, content,
                                    #   summary="", agent_run_id=None) -> Draft
           audit_service: object    # 有 record(...)（F34 audit 日志）

       def build_save_draft_tool(deps: SaveDraftToolDeps) -> Tool: ...

2. Tool 复用 F26 形态（infrastructure/agent/tools/reader_tools.py 既有）:

       @dataclass
       class Tool:
           spec: ToolSpec
           func: Callable[..., Awaitable[str]]   # 异步执行，返回文本结果

3. 工具契约（spec §5.2 工程约束）:
   - spec.name == "save_draft"（固定，LLM 按名调用）
   - 成功: 返回 {"ok": True, "draft_id": "<id>", "status": "draft", "word_count": N}
     （json.dumps ensure_ascii=False）
   - 失败: 返回 {"ok": False, "error": "<异常消息>"}（工具内部捕获一切 Exception，
     不抛出——F26 工具异常语义，is_error 由循环层判定）
   - 调 service 层不碰 ORM（ADR-F 约束①: 仅经 draft_service.create）
   - 单工具单事务（ADR-F 约束②: 每次调用 draft_service.create 恰一次 =
     独立事务提交点；测试断言 create 恰 await 1 次）
   - 写操作落审计日志（ADR-F 约束③: audit_service.record 被调，含
     actor="agent:writer" 与草稿摘要）

4. word_count 语义: 复用 domain/services/_word_count.count_words（既有纯函数）。

RED 预期
--------
全文件收集期失败（1c 整模块 RED 形态: pytest exit 2 / collected 0 items / 1 error）:
    ModuleNotFoundError: No module named 'inkflow.infrastructure.agent.tools.save_draft_tool'
（字母序: inkflow.infrastructure.agent.tools.save_draft_tool 唯一缺失模块）

asyncio 模式: 本 venv（pytest-asyncio 1.4.0）实测头部 asyncio: mode=Mode.AUTO
（pyproject asyncio_mode = "auto" 生效）；文件级 pytestmark = pytest.mark.asyncio
双保险（STRICT/AUTO 两种模式均成立），全部用例 async def。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from inkflow.domain.models.draft import Draft, DraftStatus
from inkflow.domain.services._word_count import count_words
from inkflow.infrastructure.agent.tools.reader_tools import Tool
from inkflow.infrastructure.agent.tools.save_draft_tool import (
    SaveDraftParams,
    SaveDraftToolDeps,
    build_save_draft_tool,
)

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

# ── 常量 ──────────────────────────────────────

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
CHAPTER_ID = uuid.UUID("87654321-4321-8765-4321-876543218765")

CONTENT = "第一章 测试内容。这是草稿正文，用于验证 save_draft 工具契约。"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _make_draft(**overrides) -> Draft:
    kwargs = dict(
        id="draft-1",
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content=CONTENT,
        status=DraftStatus.DRAFT,
        created_at=_utcnow(),
        confirmed_at=None,
    )
    kwargs.update(overrides)
    return Draft(**kwargs)


def _make_deps(**overrides) -> SaveDraftToolDeps:
    deps = SaveDraftToolDeps(
        draft_service=AsyncMock(),
        audit_service=AsyncMock(),
    )
    for key, value in overrides.items():
        setattr(deps, key, value)
    return deps


# ── 契约: 工具定义 ──


def test_save_draft_tool_spec() -> None:
    """契约①: 工具 spec.name 固定为 save_draft，description 含草稿/确认语义.

    描述应引导 LLM「正文完成后必须调用本工具保存草稿」（spec §5.2 工具描述）.
    """
    deps = _make_deps()
    tool = build_save_draft_tool(deps)

    assert isinstance(tool, Tool)
    assert tool.spec.name == "save_draft"
    assert "草稿" in tool.spec.description
    assert "确认" in tool.spec.description
    # input_schema 由 SaveDraftParams.model_json_schema() 生成
    schema = tool.spec.input_schema
    assert "content" in schema["properties"]
    assert "project_id" in schema["properties"]


def test_save_draft_params_validation() -> None:
    """契约②: SaveDraftParams 字段契约（content 必填，chapter_id 可选）."""
    params = SaveDraftParams(project_id=PROJECT_ID, content=CONTENT)
    assert params.chapter_id is None

    params2 = SaveDraftParams(project_id=PROJECT_ID, chapter_id=CHAPTER_ID, content=CONTENT)
    assert params2.chapter_id == CHAPTER_ID

    with pytest.raises(ValidationError):
        SaveDraftParams(project_id=PROJECT_ID)  # content 必填


# ── 契约: 成功路径（草稿落库 + 审计 + 单事务） ──


async def test_save_draft_success() -> None:
    """契约③: 成功落库 → 返回 ok 信封含 draft_id/status/word_count.

    断言: draft_service.create 恰 await 1 次（单工具单事务，ADR-F 约束②）/
    入参内容正确 / audit_service.record 被调（约束③）.
    """
    deps = _make_deps()
    deps.draft_service.create.return_value = _make_draft()
    tool = build_save_draft_tool(deps)

    result = await tool.func(project_id=PROJECT_ID, chapter_id=CHAPTER_ID, content=CONTENT)

    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["draft_id"] == "draft-1"
    assert payload["status"] == "draft"
    assert payload["word_count"] == count_words(CONTENT)

    # 单事务: create 恰一次，入参正确
    deps.draft_service.create.assert_awaited_once()
    create_call = deps.draft_service.create.await_args
    assert create_call.kwargs["project_id"] == PROJECT_ID
    assert create_call.kwargs["chapter_id"] == CHAPTER_ID
    assert create_call.kwargs["content"] == CONTENT
    # 审计: 写操作落日志（actor=agent:writer）
    deps.audit_service.record.assert_awaited_once()


async def test_save_draft_without_chapter() -> None:
    """契约④: chapter_id 可选（None = 确认时指定目标章节）."""
    deps = _make_deps()
    deps.draft_service.create.return_value = _make_draft(chapter_id=None)
    tool = build_save_draft_tool(deps)

    result = await tool.func(project_id=PROJECT_ID, content=CONTENT)

    payload = json.loads(result)
    assert payload["ok"] is True
    create_call = deps.draft_service.create.await_args
    assert create_call.kwargs["chapter_id"] is None


# ── 契约: 失败路径（service 抛错 → is_error 信封，不中断） ──


async def test_save_draft_service_error() -> None:
    """契约⑤: draft_service 抛异常 → {"ok": false, "error": "..."} 不抛出.

    断言: 返回信封 is_error 语义（ok=False + 错误消息）/ 不向上抛异常 /
    审计仍记录失败（约束③: 成功/失败均落审计）.
    """
    deps = _make_deps()
    deps.draft_service.create.side_effect = RuntimeError("数据库连接失败")
    tool = build_save_draft_tool(deps)

    result = await tool.func(project_id=PROJECT_ID, chapter_id=CHAPTER_ID, content=CONTENT)

    payload = json.loads(result)
    assert payload["ok"] is False
    assert "数据库连接失败" in payload["error"]
    deps.audit_service.record.assert_awaited()  # 失败亦落审计


async def test_save_draft_empty_content_rejected() -> None:
    """契约⑥: 空 content 应被 draft_service 拒绝（service 层校验，工具透传错误）.

    领域规则（字数/内容校验）在 service 层不破（ADR-F 约束①: 工具不自行实现
    领域校验，service 抛 ValueError → 错误信封回填）.
    """
    deps = _make_deps()
    deps.draft_service.create.side_effect = ValueError("草稿内容不能为空")
    tool = build_save_draft_tool(deps)

    result = await tool.func(project_id=PROJECT_ID, content="")

    payload = json.loads(result)
    assert payload["ok"] is False
    assert "不能为空" in payload["error"]
