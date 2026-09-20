"""#1318 RED 契约 — 三轨提示词必须显式禁止「正文首行回声章节标题」。

来源: issue #1318 ④「提示词无禁止（3 处）」

现状（实证，rc4）
-----------------
| 轨 | 落点 | 现状 |
|---|---|---|
| book 三轨 | `chapter_brief.py:115-118`（system）+ `:149-154`（user） | ❌ 无禁止 |
| F3 确定性轨 | `writing_service.py:191-192` | ⚠️ 仅禁 markdown `#`/`**` |
| agentic 单章轨 | `i18n/prompts/zh/writer_agent.yaml:18` | ⚠️ 同上 |

（book 三轨的 user 指令 `请撰写章节《<章名>》：<大纲>` **直接给出章名**，是诱导回声的语法位置。）

契约
----
P1 book 三轨 system brief：含「首行不得…标题」禁止措辞（`_NO_TITLE_ECHO_HINT` 落地）
P2 book 三轨 user 指令：不再以「章节《<章名>》」形态直接给出章名（去诱导）
P3 F3 确定性轨 user 指令：含同一禁止措辞
P4 agentic 轨 zh/en 两 locale：含对应禁止措辞（en 漏改是 #1109 已犯过的错）
P5 禁止措辞不得只是裸词 —— 必须是指向「首行 / 标题」的祈使句

基线: main @ ffd825b2
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.project import ProjectConfig
from inkflow.domain.ports.llm_client import LLMClientProtocol
from inkflow.domain.services.chapter_brief import (
    build_chapter_brief,
    chapter_write_messages,
)
from inkflow.domain.services.writing_service import WritingService

PROMPTS_DIR = Path(__file__).resolve().parents[4] / "src" / "inkflow" / "i18n" / "prompts"

# 禁止措辞的**语义核心**（各轨措辞可不同，但必须同时出现「首行」与「标题」）
CORE_MARKERS = ("首行", "标题")

TITLE = "第1章 梦境觉醒"
DESCRIPTION = "主角在异乡醒来，发现记忆残缺。"


class _Chapter:
    """最小章对象（`_chapter_value` 兼容 dict/对象两种形态）。"""

    def __init__(self) -> None:
        self.name = TITLE
        self.description = DESCRIPTION


class TestP1BriefForbidsEcho:
    """P1: book 三轨 system brief 含禁止措辞。"""

    def test_brief_contains_no_title_echo_constraint(self) -> None:
        brief = build_chapter_brief(None, _Chapter())
        for marker in CORE_MARKERS:
            assert marker in brief, f"brief 缺禁止措辞（缺 {marker!r}）:\n{brief}"
        assert "不得" in brief or "不要" in brief, f"brief 未用祈使否定式:\n{brief}"

    def test_brief_constraint_is_not_bare_marker(self) -> None:
        """防止「凑词」：措辞必须落在同一句内（非分散命中）。"""
        brief = build_chapter_brief(None, _Chapter())
        sentence = next(
            (ln for ln in brief.split("\n") if "首行" in ln and "标题" in ln),
            None,
        )
        assert sentence is not None, f"「首行」与「标题」未被写进同一句:\n{brief}"


class TestP2UserInstructionNoInducement:
    """P2: user 指令不再以「章节《<章名>》」形态把章名摆在句首。"""

    def test_user_instruction_does_not_quote_title_verbatim(self) -> None:
        messages = chapter_write_messages("system", _Chapter(), None)
        user = messages[1]["content"]
        assert f"章节《{TITLE}》" not in user, (
            f"user 指令仍以《章名》形态直接给出章名（诱导回声）:\n{user}"
        )

    def test_user_instruction_still_carries_description(self) -> None:
        """去诱导不得丢失大纲/描述（契约保真）。"""
        messages = chapter_write_messages("system", _Chapter(), 2000)
        user = messages[1]["content"]
        assert DESCRIPTION in user, f"user 指令丢失大纲描述:\n{user}"
        assert "2000" in user, f"user 指令丢失字数约束:\n{user}"


class TestP3F3TrackForbidsEcho:
    """P3: F3 确定性轨（writing_service）user 指令含同一禁止措辞。"""

    @pytest.fixture
    def service(self) -> WritingService:
        llm = MagicMock(spec=LLMClientProtocol)
        llm.chat = AsyncMock()
        project = MagicMock()
        project.id = uuid.uuid4()
        project.config = ProjectConfig(model="openai/gpt-4o", writing_style="冷峻克制")
        project_repo = MagicMock()
        project_repo.get = AsyncMock(return_value=project)
        return WritingService(
            llm_client=llm,
            prompt_manager=MagicMock(),
            project_repo=project_repo,
            chapter_repo=MagicMock(),
        )

    def test_generate_prompt_forbids_title_echo(self, service: WritingService) -> None:
        messages = service._build_generate_messages(
            style="冷峻克制",
            outline="主角在异乡醒来。",
            context="",
            min_words=2000,
        )
        user = messages[1].content
        for marker in CORE_MARKERS:
            assert marker in user, f"F3 轨 user 指令缺禁止措辞（缺 {marker!r}）:\n{user}"

    def test_generate_prompt_keeps_existing_plain_text_rules(self, service: WritingService) -> None:
        """#1109 契约不回归：纯文本 + 全角缩进仍在。"""
        messages = service._build_generate_messages(
            style="冷峻克制",
            outline="主角在异乡醒来。",
            context="",
            min_words=2000,
        )
        user = messages[1].content
        assert "纯文本" in user
        assert "全角空格" in user
        for marker in ("Markdown 格式", "章节标题使用", "```", "# 标记"):
            assert marker not in user, f"#1109 回归：命中 {marker!r}"


class TestP4AgenticTrackBothLocales:
    """P4: agentic 轨 zh/en 双 locale 均含禁止措辞（#1109 漏改 en 的教训）。"""

    @pytest.mark.parametrize("locale", ["zh", "en"])
    def test_writer_agent_yaml_forbids_title_echo(self, locale: str) -> None:
        path = PROMPTS_DIR / locale / "writer_agent.yaml"
        assert path.exists(), f"未找到 {path}"
        text = path.read_text(encoding="utf-8")
        if locale == "zh":
            for marker in CORE_MARKERS:
                assert marker in text, f"[zh] writer_agent.yaml 缺禁止措辞（缺 {marker!r}）"
        else:
            lowered = text.lower()
            assert "first line" in lowered, f"[en] 缺 first line 禁止措辞:\n{text}"
            assert "title" in lowered, f"[en] 缺 title 禁止措辞:\n{text}"

    @pytest.mark.parametrize("locale", ["zh", "en"])
    def test_writer_agent_yaml_keeps_existing_rules(self, locale: str) -> None:
        """#1109 契约不回归。"""
        text = (PROMPTS_DIR / locale / "writer_agent.yaml").read_text(encoding="utf-8")
        assert "```" not in text
        if locale == "zh":
            assert "纯文本" in text
        else:
            assert "plain text" in text
