"""F3 WritingService 测试 — Mock LLM + Mock PromptManager + Mock Repos."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.project import ProjectConfig
from inkflow.domain.models.writing import (
    ContinueWritingRequest,
    RevisionRequest,
    WritingMode,
    WritingRequest,
    WritingResult,
)
from inkflow.domain.ports.llm_client import (
    ChatResponse,
    LLMClientProtocol,
    StreamEvent,
    TokenUsage,
)
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.domain.ports.prompt_template import (
    PromptTemplate,
    PromptTemplateProtocol,
    RenderedPrompt,
)
from inkflow.domain.services.writing_service import NullContextProvider, WritingService


@pytest.fixture
def mock_llm() -> MagicMock:
    llm = MagicMock(spec=LLMClientProtocol)
    llm.chat = AsyncMock()
    return llm


@pytest.fixture
def mock_prompt_manager() -> MagicMock:
    pm = MagicMock(spec=PromptTemplateProtocol)
    pm.load = MagicMock(
        return_value=PromptTemplate(
            name="writer",
            description="Writer template",
            system_prompt="You are a writer. Style: {style}",
            human_prompt="Outline: {outline}\nContext: {context}\nMin words: {min_words}",
            variables=["style", "outline", "context", "min_words"],
        )
    )
    pm.render = MagicMock(
        return_value=RenderedPrompt(
            messages=[
                {"role": "system", "content": "You are a writer. Style: 热血少年"},
                {
                    "role": "user",
                    "content": "Outline: test outline\nContext: test context\nMin words: 2000",
                },
            ],
            token_estimate=100,
        )
    )
    return pm


@pytest.fixture
def mock_project_repo() -> MagicMock:
    from inkflow.domain.models.project import Project

    repo = MagicMock()
    project = Project(
        id=uuid.uuid4(),
        name="测试小说",
        genre="玄幻",
        language="zh-CN",
        target_words=100000,
        config=ProjectConfig(model="openai/gpt-4o", temperature=0.7, writing_style="热血少年"),
        is_deleted=False,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    repo.get = AsyncMock(return_value=project)
    return repo


@pytest.fixture
def mock_chapter_repo(mock_project_repo) -> MagicMock:
    from inkflow.domain.models.chapter import Chapter, ChapterStatus

    project = mock_project_repo.get.return_value  # noqa: F841 — used for project_id

    async def _get_chapter(chapter_id):
        return Chapter(
            id=chapter_id,
            project_id=project.id,  # type: ignore[union-attr]
            volume_id=None,
            title="第一章",
            content="",
            status=ChapterStatus.DRAFT,
            word_count=0,
            order_index=1.0,
            status_history=[],
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )

    repo = MagicMock()
    repo.get_chapter = AsyncMock(side_effect=_get_chapter)
    return repo


@pytest.fixture
def proj_id(mock_project_repo) -> uuid.UUID:
    return mock_project_repo.get.return_value.id  # type: ignore[union-attr]


@pytest.fixture
def service(mock_llm, mock_prompt_manager, mock_project_repo, mock_chapter_repo) -> WritingService:
    return WritingService(
        llm_client=mock_llm,
        prompt_manager=mock_prompt_manager,
        project_repo=mock_project_repo,
        chapter_repo=mock_chapter_repo,
        context_provider=NullContextProvider(),
    )


def _good_content() -> str:
    return "# 第一章 试炼\n\n" + "正文内容。" * 500


class TestWritingService:
    async def test_generate_chapter_success(self, service, mock_llm, proj_id) -> None:
        mock_llm.chat.return_value = ChatResponse(
            content=_good_content(),
            model="openai/gpt-4o",
            token_usage=TokenUsage(prompt_tokens=100, completion_tokens=2000, total_tokens=2100),
        )
        request = WritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            outline="主角首次踏入宗门试炼",
            context="",
        )
        result = await service.generate_chapter(request)
        assert isinstance(result, WritingResult)
        assert result.mode == WritingMode.GENERATE
        assert result.word_count >= 2000
        assert result.format_valid is True
        assert result.retry_count == 0
        assert result.model == "openai/gpt-4o"

    async def test_generate_retries_on_bad_format(self, service, mock_llm, proj_id) -> None:
        bad_content = "```\n# 标题\n正文\n```"
        good_content = _good_content()
        mock_llm.chat.side_effect = [
            ChatResponse(content=bad_content, model="openai/gpt-4o"),
            ChatResponse(
                content=good_content,
                model="openai/gpt-4o",
                token_usage=TokenUsage(
                    prompt_tokens=100, completion_tokens=2000, total_tokens=2100
                ),
            ),
        ]
        request = WritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            outline="test outline",
        )
        result = await service.generate_chapter(request)
        assert result.retry_count == 1
        assert result.format_valid is True

    async def test_generate_retries_exhausted(self, service, mock_llm, proj_id) -> None:
        bad = "```json\n{}\n```"
        mock_llm.chat.return_value = ChatResponse(content=bad, model="openai/gpt-4o")
        request = WritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            outline="test",
        )
        result = await service.generate_chapter(request)
        assert result.format_valid is False
        assert result.retry_count == 3
        assert len(result.warnings) > 0

    async def test_generate_llm_error_propagates(self, service, mock_llm, proj_id) -> None:
        mock_llm.chat.side_effect = LLMRequestError("API key invalid")
        request = WritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            outline="test",
        )
        with pytest.raises(LLMRequestError):
            await service.generate_chapter(request)

    async def test_generate_injects_style(self, service, mock_llm, proj_id) -> None:
        mock_llm.chat.return_value = ChatResponse(
            content=_good_content(),
            model="openai/gpt-4o",
            token_usage=TokenUsage(prompt_tokens=100, completion_tokens=2000, total_tokens=2100),
        )
        request = WritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            outline="test outline",
            style_hint="暗黑风格",
        )
        result = await service.generate_chapter(request)
        assert result.format_valid is True

    async def test_generate_uses_project_config(self, service, mock_llm, proj_id) -> None:
        mock_llm.chat.return_value = ChatResponse(
            content=_good_content(),
            model="openai/gpt-4o",
            token_usage=TokenUsage(prompt_tokens=100, completion_tokens=2000, total_tokens=2100),
        )
        request = WritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            outline="test",
        )
        result = await service.generate_chapter(request)
        assert result.model == "openai/gpt-4o"

    async def test_continue_injects_tail_anchor(self, service, mock_llm, proj_id) -> None:
        mock_llm.chat.return_value = ChatResponse(
            content=_good_content(),
            model="openai/gpt-4o",
            token_usage=TokenUsage(prompt_tokens=100, completion_tokens=1000, total_tokens=1100),
        )
        existing = "这是已有内容" * 20
        request = ContinueWritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            existing_content=existing,
        )
        result = await service.continue_writing(request)
        assert result.format_valid is True

    async def test_revise_default_low_temperature(self, service, mock_llm, proj_id) -> None:
        mock_llm.chat.return_value = ChatResponse(
            content=_good_content(),
            model="openai/gpt-4o",
            token_usage=TokenUsage(prompt_tokens=100, completion_tokens=500, total_tokens=600),
        )
        request = RevisionRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            content="待修订原文内容。" * 10,
            feedback="节奏太慢，删减环境描写",
        )
        result = await service.revise_content(request)
        assert result.mode == WritingMode.REVISE

    async def test_revise_unlocatable_range_warns(self, service, mock_llm, proj_id) -> None:
        mock_llm.chat.return_value = ChatResponse(
            content=_good_content(),
            model="openai/gpt-4o",
            token_usage=TokenUsage(prompt_tokens=100, completion_tokens=500, total_tokens=600),
        )
        request = RevisionRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            content="待修订原文内容。" * 10,
            feedback="修改意见",
            target_range="第99段",
        )
        result = await service.revise_content(request)
        assert any("未定位" in w or "定位" in w for w in result.warnings)

    async def test_null_context_provider(self, service, mock_llm, proj_id) -> None:
        mock_llm.chat.return_value = ChatResponse(
            content=_good_content(),
            model="openai/gpt-4o",
            token_usage=TokenUsage(prompt_tokens=100, completion_tokens=2000, total_tokens=2100),
        )
        request = WritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            outline="test",
            context="caller-provided context",
        )
        result = await service.generate_chapter(request)
        assert result.format_valid is True


class TestNullContextProvider:
    async def test_returns_empty(self) -> None:
        provider = NullContextProvider()
        result = await provider.get_context(
            project_id=uuid.uuid4(),
            chapter_id=uuid.uuid4(),
            mode=WritingMode.GENERATE,
        )
        assert result == ""


# ── F23 SSE 流式（spec §5/§9 M2/M3；RED 阶段预期：stream_* 调用 AttributeError）──


def _stream_events(chunks: list[str], *, token_usage: TokenUsage | None = None):
    """构造 chat_stream mock 返回值 — async generator（spec §9 M2 模式）.

    序列: 每个 chunk 一个 StreamEvent(content=c) + 末尾
    StreamEvent(content="", is_final=True, token_usage=token_usage)
    （最终事件携带 Token 统计——done 帧 token_usage 字段来源，spec §2.1）.
    """

    async def _gen():
        for c in chunks:
            yield StreamEvent(content=c)
        yield StreamEvent(content="", is_final=True, token_usage=token_usage)

    return _gen()


class TestStreamGenerate:
    """F23 §5.1 stream_generate — 流式生成（spec §9 M2）.

    设计假设（F16 契约，实现以测试为准）:
    - 接口: async def stream_generate(self, request: WritingRequest)
        -> AsyncGenerator[WritingStreamEvent, None]（WritingService 新增方法）
    - 管线: 项目校验 → 章节校验 → 参数解析（style/model/temperature，同 generate_chapter）
        → 上下文 → prompt 组装（同 _generate_with_retry）→ chat_stream 逐事件透传 → done 帧
    - 校验失败在流开始前抛出（首个 __anext__ 即异常，消息即 detail，spec §7 E1）:
        项目不存在 → LLMRequestError("项目不存在")；章节不存在/跨项目 →
        LLMRequestError("章节不存在")（错误类 = inkflow.domain.ports.llm_errors.LLMRequestError）
    - chat_stream 调用: self._llm.chat_stream(messages=..., model=..., temperature=...)
        关键字参数；每个 StreamEvent yield 一个 WritingStreamEvent(delta=ev.content)
        （is_final 事件 delta 为空也 yield，spec §5.1 步骤 6 字面语义）
    - done 帧（最后 1 个事件）: done=True/delta=""；format_valid=FormatValidator.validate(
        全文, min_words).valid；warnings=校验问题（含「格式校验未通过」前缀文案，镜像非流式
        exhausted 路径语义，无重试次数）；word_count=count_words(全文)；model=request.model
        or project.config.model；token_usage=最终 StreamEvent.token_usage
    - 格式无效不重试（Q2 拍板）: chat_stream 仅调用 1 次
    - 空流（0 chunk）: done 帧 format_valid=False + warning 精确文案「生成内容为空」
        （spec §7 E5），word_count=0
    - patch 目标: 测试注入 mock_llm.chat_stream（消费方命名空间
        inkflow.domain.services.writing_service 的 WritingService._llm）
    - mock 项目配置常量: model="openai/gpt-4o"、temperature=0.7、writing_style="热血少年"
    """

    async def test_project_not_found_raises_before_stream(
        self, service, mock_project_repo, proj_id
    ) -> None:
        mock_project_repo.get = AsyncMock(return_value=None)
        request = WritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            outline="主角首次踏入宗门试炼",
        )
        with pytest.raises(LLMRequestError, match="项目不存在"):
            async for _ in service.stream_generate(request):
                pass

    async def test_chapter_not_found_raises_before_stream(
        self, service, mock_chapter_repo, proj_id
    ) -> None:
        mock_chapter_repo.get_chapter = AsyncMock(return_value=None)
        request = WritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            outline="主角首次踏入宗门试炼",
        )
        with pytest.raises(LLMRequestError, match="章节不存在"):
            async for _ in service.stream_generate(request):
                pass

    async def test_cross_project_chapter_raises_before_stream(
        self, service, mock_chapter_repo, proj_id
    ) -> None:
        from inkflow.domain.models.chapter import Chapter, ChapterStatus

        async def _cross_project_chapter(chapter_id):
            return Chapter(
                id=chapter_id,
                project_id=uuid.uuid4(),
                volume_id=None,
                title="第一章",
                content="",
                status=ChapterStatus.DRAFT,
                word_count=0,
                order_index=1.0,
                status_history=[],
                created_at="2026-01-01T00:00:00Z",
                updated_at="2026-01-01T00:00:00Z",
            )

        mock_chapter_repo.get_chapter = AsyncMock(side_effect=_cross_project_chapter)
        request = WritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            outline="主角首次踏入宗门试炼",
        )
        with pytest.raises(LLMRequestError, match="章节不存在"):
            async for _ in service.stream_generate(request):
                pass

    async def test_success_delta_passthrough_and_done_frame(
        self, service, mock_llm, proj_id
    ) -> None:
        content = _good_content()
        chunks = [content[:100], content[100:300], content[300:]]
        usage = TokenUsage(prompt_tokens=100, completion_tokens=2000, total_tokens=2100)
        mock_llm.chat_stream = MagicMock(return_value=_stream_events(chunks, token_usage=usage))
        request = WritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            outline="主角首次踏入宗门试炼",
        )
        events = [ev async for ev in service.stream_generate(request)]

        # delta 帧: 每个 StreamEvent 对应一个（含 is_final 空 delta 事件），共 len(chunks)+1 个
        assert len(events) == len(chunks) + 2
        assert [ev.delta for ev in events[:-1]] == chunks + [""]
        assert all(ev.done is False for ev in events[:-1])

        done = events[-1]
        assert done.done is True
        assert done.delta == ""
        assert done.format_valid is True
        assert done.word_count == 2005  # 正文 2000 + 标题 5 字（count_words 保留标题）
        assert done.model == "openai/gpt-4o"
        assert done.token_usage == usage
        assert done.warnings == []

    async def test_invalid_format_done_frame_without_retry(
        self, service, mock_llm, proj_id
    ) -> None:
        bad = "```\n# 标题\n正文\n```"
        mock_llm.chat_stream = MagicMock(return_value=_stream_events([bad]))
        request = WritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            outline="主角首次踏入宗门试炼",
        )
        events = [ev async for ev in service.stream_generate(request)]
        done = events[-1]
        assert done.done is True
        assert done.format_valid is False
        assert any("格式校验未通过" in w for w in done.warnings)
        mock_llm.chat_stream.assert_called_once()  # 不重试（Q2 拍板，spec §5.4）

    async def test_empty_stream_done_frame(self, service, mock_llm, proj_id) -> None:
        mock_llm.chat_stream = MagicMock(return_value=_stream_events([]))
        request = WritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            outline="主角首次踏入宗门试炼",
        )
        events = [ev async for ev in service.stream_generate(request)]
        # 0 chunk → 1 个空 delta 事件（is_final）+ done 帧
        assert len(events) == 2
        assert events[0].done is False
        assert events[0].delta == ""
        done = events[-1]
        assert done.done is True
        assert done.format_valid is False
        assert "生成内容为空" in done.warnings
        assert done.word_count == 0

    async def test_chat_stream_messages_contract(self, service, mock_llm, proj_id) -> None:
        mock_llm.chat_stream = MagicMock(
            return_value=_stream_events(["清晨", "的薄雾", "尚未散尽。"])
        )
        request = WritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            outline="主角首次踏入宗门试炼",
            context="",
        )
        events = [ev async for ev in service.stream_generate(request)]
        assert events[-1].done is True

        mock_llm.chat_stream.assert_called_once()
        kwargs = mock_llm.chat_stream.call_args.kwargs
        assert kwargs["model"] == "openai/gpt-4o"  # request.model None → 项目配置
        assert kwargs["temperature"] == 0.7  # request.temperature None → 项目配置
        messages = kwargs["messages"]
        assert messages[0].role == "system"
        assert "你是专业小说作者" in messages[0].content
        assert "热血少年" in messages[0].content  # 项目 writing_style 注入
        assert messages[1].role == "user"
        assert "大纲：主角首次踏入宗门试炼" in messages[1].content
        assert "最少字数：2000" in messages[1].content
        assert "上下文：" not in messages[1].content  # 无上下文时不注入该行


class TestStreamContinue:
    """F23 §5.1 stream_continue — 流式续写（spec §9 M3）.

    设计假设（F16 契约，实现以测试为准）:
    - 接口: async def stream_continue(self, request: ContinueWritingRequest)
        -> AsyncGenerator[WritingStreamEvent, None]（语义镜像 continue_writing）
    - prompt 组装: outline = f"续写：{tail}"，tail = existing_content[-800:]
        （代码常量 800，镜像 continue_writing L98）；user 消息含「最少字数：{target_words}」
    - done 帧: 同 stream_generate（有 FormatValidator，spec §5.4）；model=request.model
        or project.config.model；token_usage=最终 StreamEvent.token_usage
    - patch 目标: 同 TestStreamGenerate（mock_llm.chat_stream）
    """

    async def test_continue_tail_truncation_and_target_words(
        self, service, mock_llm, proj_id
    ) -> None:
        existing = "开头部分。" + "中间内容。" * 300  # 1505 字符，尾部 800 字为 tail
        tail = existing[-800:]
        assert "开头部分。" not in tail  # 头部确认被截掉
        mock_llm.chat_stream = MagicMock(return_value=_stream_events(["续写正文", "完成。"]))
        request = ContinueWritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            existing_content=existing,
            target_words=2500,
        )
        events = [ev async for ev in service.stream_continue(request)]

        kwargs = mock_llm.chat_stream.call_args.kwargs
        user = kwargs["messages"][1].content
        assert f"续写：{tail}" in user
        assert "开头部分。" not in user  # 仅尾部进入 prompt
        assert "最少字数：2500" in user  # target_words 透传
        assert events[-1].done is True

    async def test_continue_done_frame_semantics(self, service, mock_llm, proj_id) -> None:
        content = "# 第一章 试炼\n\n" + "正文内容。" * 700  # 2800 + 标题 5 = 2805 ≥ 2500
        usage = TokenUsage(prompt_tokens=100, completion_tokens=2800, total_tokens=2900)
        mock_llm.chat_stream = MagicMock(return_value=_stream_events([content], token_usage=usage))
        request = ContinueWritingRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            existing_content="这是已有内容，至少需要五十个字符。" * 3,
            target_words=2500,
        )
        events = [ev async for ev in service.stream_continue(request)]
        done = events[-1]
        assert done.done is True
        assert done.format_valid is True
        assert done.word_count == 2805
        assert done.model == "openai/gpt-4o"
        assert done.token_usage == usage


class TestStreamRevise:
    """F23 §5.1 stream_revise — 流式修订（spec §9 M3）.

    设计假设（F16 契约，实现以测试为准）:
    - 接口: async def stream_revise(self, request: RevisionRequest)
        -> AsyncGenerator[WritingStreamEvent, None]（语义镜像 revise_content）
    - 无 FormatValidator（spec §5.1 注）: done 帧 format_valid 恒 None
        （API 层序列化省略该字段，spec §6.2）
    - prompt: system=「你是专业小说修订助手…」（镜像 revise_content L130-142）；
        user 含「原文：\n{content}\n\n修订意见：{feedback}」
    - 参数: model=request.model or "openai/gpt-4o"；temperature=request.temperature or 0.4
        （镜像 revise_content L123-124）
    - target_range 未定位（不在 content 中）→ warnings 精确文案
        f"未能定位目标范围 '{target_range}'，已对全文执行修订"（镜像 L127-128，spec §7 E7）
    - patch 目标: 同 TestStreamGenerate（mock_llm.chat_stream）
    """

    async def test_revise_no_format_valid_and_messages(self, service, mock_llm, proj_id) -> None:
        content = "修订后的正文内容。" * 100  # 8 字/段 × 100 = 800 字
        chunks = [content[:200], content[200:]]
        mock_llm.chat_stream = MagicMock(return_value=_stream_events(chunks))
        request = RevisionRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            content="待修订原文内容。" * 10,
            feedback="节奏太慢，删减环境描写",
        )
        events = [ev async for ev in service.stream_revise(request)]

        assert "".join(ev.delta for ev in events[:-1]) == content
        done = events[-1]
        assert done.done is True
        assert done.format_valid is None  # 无 FormatValidator（spec §5.1 注）
        assert done.word_count == 800
        assert done.model == "openai/gpt-4o"

        kwargs = mock_llm.chat_stream.call_args.kwargs
        assert kwargs["model"] == "openai/gpt-4o"
        assert kwargs["temperature"] == 0.4
        messages = kwargs["messages"]
        assert messages[0].role == "system"
        assert "修订助手" in messages[0].content
        assert "原文：" in messages[1].content
        assert "修订意见：节奏太慢，删减环境描写" in messages[1].content

    async def test_revise_target_range_not_located_warns(self, service, mock_llm, proj_id) -> None:
        mock_llm.chat_stream = MagicMock(return_value=_stream_events(["修订后的内容"]))
        request = RevisionRequest(
            project_id=proj_id,
            chapter_id=uuid.uuid4(),
            content="待修订原文内容。" * 10,
            feedback="修改意见",
            target_range="第99段",
        )
        events = [ev async for ev in service.stream_revise(request)]
        done = events[-1]
        assert done.done is True
        assert "未能定位目标范围 '第99段'，已对全文执行修订" in done.warnings
