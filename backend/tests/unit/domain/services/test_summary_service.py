"""摘要服务测试 — Mock LLM + Mock Repository.

测试范围 (spec §9):
    - 生成调用 F5 chat + context_summary 模板
    - 缓存命中不重复生成
    - 章节更新后重新生成
    - LLM 失败跳过不阻断
    - list_recent 按序号倒序
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from inkflow.domain.models.chapter import Chapter, ChapterStatus
from inkflow.domain.models.context import ChapterSummary
from inkflow.domain.ports.context_errors import SummaryGenerationError
from inkflow.domain.ports.llm_client import ChatMessage, ChatResponse
from inkflow.domain.ports.prompt_template import (
    PromptTemplate,
    RenderedPrompt,
)
from inkflow.domain.services.summary_service import SummaryService

# ── 辅助工厂 ────────────────────────────────────────────────────


def _chapter(**overrides) -> Chapter:
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "volume_id": None,
        "title": "第一章",
        "content": "这是一段测试内容。故事从这里开始..." * 20,
        "status": ChapterStatus.DRAFT,
        "word_count": 500,
        "order_index": 1.0,
        "status_history": [],
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return Chapter(**defaults)


def _summary(chapter_id: uuid.UUID) -> ChapterSummary:
    return ChapterSummary(
        id=uuid.uuid4(),
        chapter_id=chapter_id,
        summary="本章讲述了主人公的冒险故事。",
        model="openai/gpt-4o",
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


# ── Mock 依赖 ───────────────────────────────────────────────────


class MockSummaryRepo:
    """Mock SummaryRepositoryProtocol."""

    def __init__(self, summaries: dict[int, ChapterSummary] | None = None) -> None:
        self._store: dict[int, ChapterSummary] = summaries or {}
        self.upsert_calls: list[tuple[int, str, str]] = []

    async def get(self, chapter_id: int) -> ChapterSummary | None:
        return self._store.get(chapter_id)

    async def upsert(self, chapter_id: int, summary: str, model: str) -> ChapterSummary:
        self.upsert_calls.append((chapter_id, summary, model))
        cid_uuid = uuid.UUID(int=chapter_id) if isinstance(chapter_id, int) else uuid.uuid4()
        cs = ChapterSummary(
            id=uuid.uuid4(),
            chapter_id=cid_uuid,
            summary=summary,
            model=model,
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        )
        self._store[chapter_id] = cs
        return cs

    async def list_recent(self, project_id: int, limit: int = 10) -> list[ChapterSummary]:
        # ⚠️ 补强（#524）：镜像真实 repo order_by desc 语义——Mock 无排序则「排序契约」无法在测试断言
        return sorted(self._store.values(), key=lambda s: s.updated_at, reverse=True)[:limit]


class MockLLMClient:
    """Mock LLMClientProtocol."""

    def __init__(self, response_text: str = "测试摘要") -> None:
        self.response_text = response_text
        self.chat_calls: list[tuple[list[ChatMessage], str]] = []

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: object,
    ) -> ChatResponse:
        self.chat_calls.append((messages, model or ""))
        return ChatResponse(content=self.response_text, model=model or "test")

    async def count_tokens(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
    ) -> int:
        total = sum(len(m.content) for m in messages)
        return max(1, total // 4)


class MockPromptManager:
    """Mock PromptTemplateProtocol."""

    def __init__(self) -> None:
        self.render_calls: list[tuple[str, dict[str, str]]] = []

    def load(self, template_name: str) -> PromptTemplate:
        return PromptTemplate(
            name=template_name,
            description="test",
            system_prompt="Summarize",
            human_prompt="{chapter_title}\n{chapter_content}",
            variables=["chapter_title", "chapter_content"],
        )

    def render(self, template: PromptTemplate, variables: dict[str, str]) -> RenderedPrompt:
        self.render_calls.append((template.name, variables))
        return RenderedPrompt(
            messages=[
                {"role": "system", "content": template.system_prompt},
                {"role": "user", "content": variables.get("chapter_content", "")},
            ]
        )

    def list_templates(self) -> list[str]:
        return ["context_summary"]

    def validate(self, template: PromptTemplate, variables: dict[str, str]) -> list[str]:
        return []


class MockChapterReader:
    """Mock ChapterReaderProtocol."""

    def __init__(self, chapters: dict[int, Chapter] | None = None) -> None:
        self._chapters: dict[int, Chapter] = chapters or {}

    async def get_chapter(self, chapter_id: int) -> Chapter | None:
        return self._chapters.get(chapter_id)


# ── 测试套件 ────────────────────────────────────────────────────


class TestSummaryService:
    """摘要生成/缓存测试."""

    @pytest.fixture
    def repo(self) -> MockSummaryRepo:
        return MockSummaryRepo()

    @pytest.fixture
    def llm(self) -> MockLLMClient:
        return MockLLMClient(response_text="本章摘要：主人公踏上冒险之旅。")

    @pytest.fixture
    def prompts(self) -> MockPromptManager:
        return MockPromptManager()

    @pytest.fixture
    def chapter(self) -> Chapter:
        return _chapter()

    @pytest.fixture
    def svc(
        self,
        repo: MockSummaryRepo,
        llm: MockLLMClient,
        prompts: MockPromptManager,
        chapter: Chapter,
    ) -> SummaryService:
        reader = MockChapterReader({int(chapter.id): chapter})
        return SummaryService(
            summary_repo=repo,
            llm_client=llm,
            prompt_manager=prompts,
            chapter_reader=reader,
        )

    async def test_generate_summary_calls_llm(
        self, svc: SummaryService, chapter: Chapter, llm: MockLLMClient
    ) -> None:
        """首次生成摘要应调用 LLM."""
        result = await svc.ensure_summary(chapter.id, "openai/gpt-4o")
        assert len(result) > 0
        assert len(llm.chat_calls) >= 1

    async def test_cache_hit_no_llm_call(
        self, svc: SummaryService, chapter: Chapter, repo: MockSummaryRepo, llm: MockLLMClient
    ) -> None:
        """缓存命中时不应重新调用 LLM."""
        # 手动添加缓存（使用 int ID）
        chapter_id_int = int(chapter.id) if isinstance(chapter.id, uuid.UUID) else chapter.id
        repo._store[chapter_id_int] = ChapterSummary(
            id=uuid.uuid4(),
            chapter_id=chapter.id,
            summary="已缓存的摘要",
            model="openai/gpt-4o",
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2099-12-31T23:59:59+00:00",  # 未来时间，不会过期
        )
        llm.chat_calls.clear()
        result = await svc.ensure_summary(chapter.id, "openai/gpt-4o")
        assert result == "已缓存的摘要"
        assert len(llm.chat_calls) == 0  # 未调用 LLM

    async def test_cache_expired_triggers_regeneration(
        self, svc: SummaryService, chapter: Chapter, repo: MockSummaryRepo, llm: MockLLMClient
    ) -> None:
        """缓存已过期（章节已更新）时重新生成."""
        chapter_id_int = int(chapter.id) if isinstance(chapter.id, uuid.UUID) else chapter.id
        repo._store[chapter_id_int] = ChapterSummary(
            id=uuid.uuid4(),
            chapter_id=chapter.id,
            summary="过期的摘要",
            model="openai/gpt-4o",
            created_at="2020-01-01T00:00:00+00:00",
            updated_at="2020-01-01T00:00:00+00:00",  # 远早于 chapter.updated_at
        )
        llm.chat_calls.clear()
        result = await svc.ensure_summary(chapter.id, "openai/gpt-4o")
        assert result != "过期的摘要"
        assert len(llm.chat_calls) >= 1  # 重新调用了 LLM

    async def test_force_regenerate(
        self, svc: SummaryService, chapter: Chapter, repo: MockSummaryRepo, llm: MockLLMClient
    ) -> None:
        """force=True 时忽略缓存."""
        chapter_id_int = int(chapter.id) if isinstance(chapter.id, uuid.UUID) else chapter.id
        repo._store[chapter_id_int] = ChapterSummary(
            id=uuid.uuid4(),
            chapter_id=chapter.id,
            summary="缓存摘要",
            model="openai/gpt-4o",
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2099-12-31T23:59:59+00:00",
        )
        llm.chat_calls.clear()
        result = await svc.ensure_summary(chapter.id, "openai/gpt-4o", force=True)
        assert len(llm.chat_calls) >= 1
        # ⚠️ 补强（#524）：force 忽略缓存——返回新生成摘要而非「缓存摘要」
        assert result != "缓存摘要"
        assert result == llm.response_text  # MockLLMClient 默认 response_text="测试摘要"

    async def test_chapter_not_found_raises(self, svc: SummaryService) -> None:
        """章节不存在应抛出 ValueError."""
        non_existent = uuid.uuid4()
        with pytest.raises(ValueError, match="章节不存在"):
            await svc.ensure_summary(non_existent, "openai/gpt-4o")

    async def test_list_recent(
        self, svc: SummaryService, chapter: Chapter, repo: MockSummaryRepo
    ) -> None:
        """list_recent 返回缓存摘要列表."""
        chapter_id_int = int(chapter.id) if isinstance(chapter.id, uuid.UUID) else chapter.id
        older = _summary(chapter.id)
        older.updated_at = "2020-01-01T00:00:00+00:00"
        newer = _summary(chapter.id)
        newer.updated_at = "2099-12-31T23:59:59+00:00"
        repo._store[chapter_id_int] = older
        repo._store[chapter_id_int + 1] = newer
        results = await svc.list_recent(chapter.project_id)
        # ⚠️ 补强（#524）：断言「按最新在前」排序（真实 repo order_by order_index desc 的 Mock 镜像）
        assert [r.updated_at for r in results] == sorted(
            [r.updated_at for r in results], reverse=True
        )
        assert len(results) == 2
        assert isinstance(results[0], ChapterSummary)

    # ── Phase 3 覆盖率补齐（#104）──────────────────────────────────

    async def test_summary_long_output_truncated_to_300(
        self, chapter: Chapter, repo: MockSummaryRepo, prompts: MockPromptManager
    ) -> None:
        """LLM 输出 > 300 字 → 截断为 297 + '...'（≤ 300 字契约）。"""
        long_llm = MockLLMClient(response_text="长" * 500)
        reader = MockChapterReader({int(chapter.id): chapter})
        svc = SummaryService(
            summary_repo=repo,
            llm_client=long_llm,
            prompt_manager=prompts,
            chapter_reader=reader,
        )

        result = await svc.ensure_summary(chapter.id, "openai/gpt-4o")

        assert len(result) == 300
        assert result.endswith("...")
        assert result == "长" * 297 + "..."

    async def test_summary_llm_failure_raises_summary_generation_error(
        self, chapter: Chapter, repo: MockSummaryRepo, prompts: MockPromptManager
    ) -> None:
        """LLM 调用失败 → SummaryGenerationError（含 chapter_id 与 detail）。"""

        class FailingLLM(MockLLMClient):
            async def chat(
                self, messages, *, model=None, temperature=None, max_tokens=None, **kwargs
            ):
                raise RuntimeError("llm down")

        reader = MockChapterReader({int(chapter.id): chapter})
        svc = SummaryService(
            summary_repo=repo,
            llm_client=FailingLLM(),
            prompt_manager=prompts,
            chapter_reader=reader,
        )

        with pytest.raises(SummaryGenerationError) as exc_info:
            await svc.ensure_summary(chapter.id, "openai/gpt-4o")

        assert str(chapter.id) in str(exc_info.value)
        assert "llm down" in str(exc_info.value)

    async def test_utcnow_helper_returns_iso_datetime(self) -> None:
        """模块级 _utcnow() 返回可解析的 ISO 时间字符串（含 UTC 偏移）。"""
        from inkflow.domain.services.summary_service import _utcnow

        value = _utcnow()
        assert datetime.fromisoformat(value)
        assert value.endswith("+00:00")

    async def test_chapter_reader_protocol_stub_returns_none(self) -> None:
        """ChapterReaderProtocol.get_chapter 桩默认返回 None（结构类型可直接调用）。"""
        from inkflow.domain.services.summary_service import ChapterReaderProtocol

        class _BareReader:
            pass

        assert await ChapterReaderProtocol.get_chapter(_BareReader(), 1) is None
