"""#1109 RED — 写章 prompt 不得指示 LLM 输出 markdown 标题行。

根因（源码实证）
----------------
`writing_service.py:191` `_build_generate_messages` 原 prompt 要求
「Markdown 格式，章节标题使用 # 标记」→ 直接解释 #1095 两态：
  - 2 章首行带 `#`（prompt 就这么要求）
  - 7/10 章首行重复标题（「章节标题」被写进正文）
服务端 `normalize_chapter_content`（#1095/PR #1108）已兜底，本条属**源头收敛**。

契约（本文件锁定的不变量）
--------------------------
C1 generate prompt 不含 markdown 标题指示（Markdown 格式 / 章节标题使用 / 代码块标记）
C2 generate prompt 要求纯文本 + 每自然段两个全角空格开头
C3 continue prompt 复用同一 builder，契约随 C1/C2 一齐生效
C4 `writer_agent.yaml`（agentic 轨道独立 prompt）同源同病一并收敛

约束：不得改变服务端归一（#1095）行为，幂等仍成立（见
test_chapter_content_idempotent_1095r.py）。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.project import ProjectConfig
from inkflow.domain.models.writing import (
    ContinueWritingRequest,
    WritingRequest,
)
from inkflow.domain.ports.llm_client import LLMClientProtocol, StreamEvent
from inkflow.domain.services.writing_service import WritingService

FULLWIDTH = "\u3000"

# 旧实现（回归失败）会命中的「指示 LLM 输出 markdown」正向短语。
# 注意：不得禁用裸词 markdown —— 新 prompt 合法地以否定式使用它
# （「不要 markdown 标题行」），禁词会误伤正确实现。
FORBIDDEN_MARKERS = ("Markdown 格式", "章节标题使用", "```", "# 标记")

WRITER_AGENT_YAML_DIR = (
    Path(__file__).resolve().parents[4] / "src" / "inkflow" / "i18n" / "prompts"
)

# 两个 locale 都必须收敛：#1109 首轮只改了 zh，en 镜像漏改（同源同病）
WRITER_AGENT_LOCALES = ("zh", "en")

# 各 locale 的 markdown 正向指示短语（en 用 "Markdown format"）
LOCALE_FORBIDDEN = {
    "zh": ("Markdown 格式", "章节标题使用"),
    "en": ("Markdown format", "Markdown 格式"),
}


# ── fixtures（镜像 test_writing_service.py，避免跨模块导入 fixture 的脆弱性）──


@pytest.fixture
def mock_llm() -> MagicMock:
    llm = MagicMock(spec=LLMClientProtocol)
    llm.chat = AsyncMock()
    return llm


def _stream_events(chunks: list[str]) -> object:
    async def _gen():
        for c in chunks:
            yield StreamEvent(content=c, is_final=False)
        yield StreamEvent(content="", is_final=True)

    return _gen()


@pytest.fixture
def service(mock_llm) -> WritingService:
    from inkflow.domain.models.chapter import Chapter, ChapterStatus
    from inkflow.domain.models.project import Project

    project = Project(
        id=uuid.uuid4(),
        name="测试小说",
        tags=["玄幻"],
        language="zh-CN",
        target_words=100000,
        config=ProjectConfig(model="openai/gpt-4o", temperature=0.7, writing_style="热血少年"),
        is_deleted=False,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )

    project_repo = MagicMock()
    project_repo.get = AsyncMock(return_value=project)

    async def _get_chapter(chapter_id):
        return Chapter(
            id=chapter_id,
            project_id=project.id,
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

    chapter_repo = MagicMock()
    chapter_repo.get_chapter = AsyncMock(side_effect=_get_chapter)

    return WritingService(
        llm_client=mock_llm,
        prompt_manager=MagicMock(),
        project_repo=project_repo,
        chapter_repo=chapter_repo,
    )


@pytest.fixture
def proj_id(service) -> uuid.UUID:
    return service._project_repo.get.return_value.id


async def _capture_user_prompt(service, mock_llm, request, stream_method: str) -> str:
    """跑一次流式生成/续写，返回发给 LLM 的 user 消息内容。"""
    mock_llm.chat_stream = MagicMock(return_value=_stream_events(["清晨的薄雾尚未散尽。"]))
    method = getattr(service, stream_method)
    async for _ in method(request):
        pass
    return mock_llm.chat_stream.call_args.kwargs["messages"][1].content


class TestGeneratePromptPlainText:
    """C1/C2: generate prompt 要求纯正文，不得指示 markdown 标题行。"""

    @pytest.mark.asyncio
    async def test_generate_prompt_forbids_markdown_heading_instruction(
        self, service, mock_llm, proj_id
    ) -> None:
        prompt = await _capture_user_prompt(
            service,
            mock_llm,
            WritingRequest(
                project_id=proj_id,
                chapter_id=uuid.uuid4(),
                outline="主角首次踏入宗门试炼",
            ),
            "stream_generate",
        )
        for marker in FORBIDDEN_MARKERS:
            assert marker not in prompt, (
                f"generate prompt 仍指示 markdown（命中 {marker!r}）→ LLM 会输出 # 标题行\n"
                f"  prompt: {prompt!r}"
            )

    @pytest.mark.asyncio
    async def test_generate_prompt_requires_plain_text_and_fullwidth_indent(
        self, service, mock_llm, proj_id
    ) -> None:
        prompt = await _capture_user_prompt(
            service,
            mock_llm,
            WritingRequest(
                project_id=proj_id,
                chapter_id=uuid.uuid4(),
                outline="主角首次踏入宗门试炼",
            ),
            "stream_generate",
        )
        assert "纯文本" in prompt, f"prompt 未要求纯文本: {prompt!r}"
        assert "全角空格" in prompt, f"prompt 未要求段首全角缩进: {prompt!r}"


class TestContinuePromptInheritsPlainText:
    """C3: continue 复用 _build_generate_messages → 契约随之一齐生效。"""

    @pytest.mark.asyncio
    async def test_continue_prompt_forbids_markdown(self, service, mock_llm, proj_id) -> None:
        prompt = await _capture_user_prompt(
            service,
            mock_llm,
            ContinueWritingRequest(
                project_id=proj_id,
                chapter_id=uuid.uuid4(),
                existing_content="这是已有内容，至少需要五十个字符。" * 3,
                target_words=2000,
            ),
            "stream_continue",
        )
        for marker in FORBIDDEN_MARKERS:
            assert (
                marker not in prompt
            ), f"continue prompt 仍指示 markdown（命中 {marker!r}）\n  prompt: {prompt!r}"


class TestWriterAgentPromptPlainText:
    """C4: agentic 轨道 writer_agent.yaml 各 locale 独立 prompt 同源同病。"""

    @pytest.mark.parametrize("locale", WRITER_AGENT_LOCALES)
    def test_writer_agent_prompt_forbids_markdown(self, locale: str) -> None:
        yaml_path = WRITER_AGENT_YAML_DIR / locale / "writer_agent.yaml"
        assert yaml_path.exists(), f"未找到 writer_agent.yaml: {yaml_path}"
        text = yaml_path.read_text(encoding="utf-8")

        for marker in LOCALE_FORBIDDEN[locale]:
            assert marker not in text, (
                f"[{locale}] writer_agent.yaml 仍指示 markdown 标题行（命中 {marker!r}）:\n"
                + "\n".join(
                    f"  {ln}"
                    for ln in text.splitlines()
                    if marker.split()[0] in ln
                )
            )
        assert "```" not in text
        if locale == "zh":
            assert "纯文本" in text, f"[zh] 未要求纯文本:\n{text}"
        else:
            assert "plain text" in text, f"[en] 未要求 plain text:\n{text}"
