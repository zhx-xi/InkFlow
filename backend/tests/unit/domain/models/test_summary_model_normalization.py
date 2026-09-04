"""RED 契约（#470）：summary_service 对无 provider 前缀 model 归一化（回退全局默认）。

缺陷背景（0.10.0-rc7 实证 2026-08-18）：新项目默认 config.model="gpt-4o"（无 provider
前缀）→ `summarize_chapter` 直接 `self._llm.chat(messages, model="gpt-4o")` →
`parse_model_string("gpt-4o")` 抛 ValueError → LLMRequestError → 500。

本契约：summarize_chapter 收到无前缀 model（如 "gpt-4o"）时，chat 实际收到的是
**全局默认 llm_default_model（有前缀，如 deepseek/deepseek-v4-flash）**——即做了
归一化回退。修复后全部 PASS。

⚠️ RED 期形态：当前 model 原样透传（chat 收到 "gpt-4o"）→ 断言 FAIL（干净 RED）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from inkflow.domain.models.chapter import Chapter, ChapterStatus
from inkflow.domain.models.context import ChapterSummary
from inkflow.domain.ports.prompt_template import PromptTemplate, RenderedPrompt


class _FakeLLM:
    """记录 chat 收到的 model（断言归一化）。"""

    def __init__(self) -> None:
        self.last_model: str | None = None

    async def chat(
        self, messages, *, model: str | None = None, temperature=None, max_tokens=None, **kwargs
    ):
        self.last_model = model
        from inkflow.domain.ports.llm_client import ChatResponse

        return ChatResponse(content="摘要：主人公的冒险。", model=model or "")


class _FakePrompts:
    def __init__(self) -> None:
        self.template = PromptTemplate(
            name="context_summary",
            system_prompt="你是摘要助手。",
            human_prompt="请为章节「{chapter_title}」生成摘要：{chapter_content}",
        )

    def load(self, name: str) -> PromptTemplate:
        return self.template

    def render(self, template: PromptTemplate, variables: dict) -> RenderedPrompt:
        return RenderedPrompt(
            messages=[
                {"role": "system", "content": template.system_prompt},
                {"role": "user", "content": template.human_prompt.format(**variables)},
            ]
        )


def _make_service(llm: _FakeLLM):
    from inkflow.domain.services.summary_service import SummaryService

    class _Repo:
        def __init__(self) -> None:
            self._store: dict[int, ChapterSummary] = {}

        async def get(self, chapter_id: int) -> ChapterSummary | None:
            return self._store.get(chapter_id)

        async def upsert(self, chapter_id: int, summary: str, model: str) -> ChapterSummary:
            cs = ChapterSummary(
                id=uuid.uuid4(),
                chapter_id=uuid.UUID(int=chapter_id)
                if isinstance(chapter_id, int)
                else uuid.uuid4(),
                summary=summary,
                model=model,
                created_at=datetime.now(UTC).isoformat(),
                updated_at=datetime.now(UTC).isoformat(),
            )
            self._store[chapter_id] = cs
            return cs

    class _Reader:
        async def get_chapter(self, chapter_id: int):
            return None

    return SummaryService(
        summary_repo=_Repo(),
        llm_client=llm,
        prompt_manager=_FakePrompts(),
        chapter_reader=_Reader(),
    )


def _chapter() -> Chapter:
    return Chapter(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        title="第一章",
        content="这是第一章内容。",
        status=ChapterStatus.DRAFT,
        word_count=10,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_summarize_model_without_provider_prefix_falls_back_to_default():
    """无 provider 前缀 model（gpt-4o）→ chat 收到全局默认（有前缀）。"""
    llm = _FakeLLM()
    svc = _make_service(llm)
    summary = await svc.summarize_chapter(_chapter(), model="gpt-4o")
    assert summary.strip(), "摘要为空"
    assert llm.last_model is not None, "chat 未收到 model"
    assert "/" in llm.last_model, (
        "无前缀 model 'gpt-4o' 未归一化——chat 收到 "
        f"{llm.last_model!r}（#470：parse_model_string 会抛 ValueError）"
    )


@pytest.mark.asyncio
async def test_summarize_model_with_prefix_passthrough():
    """有前缀 model 原样透传（不回归）。"""
    llm = _FakeLLM()
    svc = _make_service(llm)
    await svc.summarize_chapter(_chapter(), model="deepseek/deepseek-v4-flash")
    assert llm.last_model == "deepseek/deepseek-v4-flash"
