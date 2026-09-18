"""#1262 RED 契约：book 轨兜底路径两个缺陷（content-block repr + 兜底草稿占真章节槽位）。

契约来源: Issue #1262（v0.15.0-rc2 打包产物 · 全新用户旅程 stage6 实测）+ specs/f44 §R7/§5.2 锚点节
+ specs/f27 §15.3「LLM 未调 save_draft 自然终止 → 服务层兜底保存草稿（产物保留）」。

【缺陷一】兜底路径产 content-block repr
    真实形态：LLM 返回 structured content blocks（list，含 type=thinking / type=text）
    → 兜底路径 `_extract_final_content` 用 `str(content)` → 落库正文是 **Python list 的 repr**，
    含 `[{'type': 'thinking', ...}]` 与 thinking 内部推理文本（rc2 实测 5637 字，比正常章长）。

    正解方向（Issue 指定）：复用既有 content-block 提取实现（`text` 字段拼接，跳过 `thinking`），
    勿 `str()`。本仓既有一实现 = `inkflow.infrastructure.llm.content_text.content_text`
    （#1045 D5 chat 轨已收敛）。

【缺陷二】兜底草稿冒用「书级委托回执」标记 → 占用真章节槽位
    兜底草稿带 `summary="书级委托保存"`——该标记在 `src/` 内 **零消费者**（只写不读），
    其语义是「书级委托回执（无实体）」；下游（旅程 harness stage6b_promote.py）按该标记分流：
    `summary == "书级委托保存"` → 归入 receipt → **reject**。
    而兜底草稿携带的是 **真实正文**（spec f27 §15.3：兜底 = 「服务层兜底保存草稿（产物保留）」），
    被 reject 后该章节点既无 chapter 行、草稿也被拒 → **正文永久丢失**（rc2 实测 10 章只收 9 章）。

    正解方向：兜底草稿按 spec 本义 = **真草稿**，与 agent 自调 save_draft 路径（同族）语义统一，
    不再冒用回执标记（spec f44 §5.2 #996：「委托兜底路径与 agent 自调 save_draft 路径**必须同锚点**
    （同族路径统一拍板先例）」）。
"""

from __future__ import annotations

from typing import Any

import pytest

from inkflow.domain.models.outline import Outline
from inkflow.domain.models.writing_plan import STAGE1_LIMITS, WritingPlan
from inkflow.domain.services.book_service import BookService
from tests.unit.domain.services.test_book_service import _make_deps, _outline, _plan

# ── 真实形态 fixture：rc2 实测的 content-block list（含 thinking 块） ──
THINKING_TEXT = "The project doesn't exist yet — no context. I'll just write the chapter."
CHAPTER_BODY = "第二章 校勘入日课\n\n清晨，师父把一册残卷推到我面前。"
CONTENT_BLOCKS: list[dict[str, Any]] = [
    {"type": "thinking", "thinking": THINKING_TEXT},
    {"type": "text", "text": CHAPTER_BODY},
]

#: 回执标记——兜底草稿不得使用（下游按它把草稿判为「无实体回执」并 reject）
RECEIPT_MARKER = "书级委托保存"


def _repr_markers(text: str) -> list[str]:
    """正文里的 repr 特征子串（兜底产 repr 时必然命中）。"""
    return [m for m in ("[{'type'", "{'type':", "'thinking'") if m in text]


def _chapter_in(plan: WritingPlan) -> Outline:
    """构造与 plan 同 project 的章 outline（book_service 要求 project_id 一致）。"""
    return _outline(project_id=plan.project_id)


class TestExtractFinalContentNormalizesBlocks1262:
    """缺陷一：各处 `_extract_final_content` 副本 → 全部须产纯文本。"""

    def test_book_service_extract_plain_text(self) -> None:
        """【R】book_service 副本：content-block list 入参 → 纯文本（非 repr）。"""
        from inkflow.domain.services.book_service import _extract_final_content

        out = _extract_final_content({"messages": [{"content": CONTENT_BLOCKS}]})
        assert out == CHAPTER_BODY
        assert _repr_markers(out) == [], f"正文含 repr 特征: {_repr_markers(out)}"
        assert THINKING_TEXT not in out

    def test_book_agentic_helpers_extract_plain_text(self) -> None:
        """【R】book_agentic_helpers 副本：同上（同族路径统一）。"""
        from inkflow.infrastructure.agent.book_agentic_helpers import (
            _extract_final_content,
        )

        out = _extract_final_content({"messages": [{"content": CONTENT_BLOCKS}]})
        assert out == CHAPTER_BODY
        assert _repr_markers(out) == []
        assert THINKING_TEXT not in out

    def test_book_pipeline_extract_plain_text(self) -> None:
        """【R】book_pipeline 副本：同上（同族路径统一）。"""
        from inkflow.infrastructure.agent.book_pipeline import _extract_final_content

        out = _extract_final_content({"messages": [{"content": CONTENT_BLOCKS}]})
        assert out == CHAPTER_BODY
        assert _repr_markers(out) == []
        assert THINKING_TEXT not in out

    def test_plain_str_content_unchanged(self) -> None:
        """回归边界：content 已是 str → 原样返回（不得被归一器改动）。"""
        from inkflow.domain.services.book_service import _extract_final_content

        assert _extract_final_content({"messages": [{"content": "正文A"}]}) == "正文A"

    def test_unknown_shape_yields_empty_not_repr(self) -> None:
        """回归边界：非 str 的意外形态 → ""（不得 str() 出 repr）。"""
        from inkflow.domain.services.book_service import _extract_final_content

        assert _extract_final_content({"messages": [{"content": None}]}) == ""
        assert _extract_final_content({}) == ""
        assert _extract_final_content({"messages": []}) == ""


class TestFallbackDraftIsRealDraft1262:
    """缺陷二 + 缺陷一端到端：兜底草稿按「真草稿」语义落库。"""

    @pytest.mark.asyncio
    async def test_fallback_summary_is_not_receipt_marker(self) -> None:
        """【R】兜底 create 的 summary 不得等于回执标记（该标记 = 下游 reject 判据）。"""
        deps = _make_deps()
        svc = BookService(**deps)
        plan = _plan()

        execution_id = await svc._delegate_chapter(plan, _chapter_in(plan), STAGE1_LIMITS)

        assert deps["draft_service"].create.await_count == 1
        kwargs = deps["draft_service"].create.await_args.kwargs
        assert kwargs["summary"] != RECEIPT_MARKER, (
            "兜底草稿冒用书级委托回执标记 —— 下游据此判为无实体回执并 reject → 正文本丢失"
        )
        assert execution_id

    @pytest.mark.asyncio
    async def test_fallback_content_is_plain_text_end_to_end(self) -> None:
        """【R】兜底落库正文（端到端）：content-block 入参 → 落库为纯文本。"""
        deps = _make_deps()
        deps["writer_factory"].return_value.invoke.return_value = {
            "messages": [{"content": CONTENT_BLOCKS}]
        }
        svc = BookService(**deps)
        plan = _plan()

        await svc._delegate_chapter(plan, _chapter_in(plan), STAGE1_LIMITS)

        kwargs = deps["draft_service"].create.await_args.kwargs
        assert kwargs["content"] == CHAPTER_BODY
        assert _repr_markers(kwargs["content"]) == []
        assert THINKING_TEXT not in kwargs["content"]

    @pytest.mark.asyncio
    async def test_fallback_keeps_real_chapter_slot_anchor(self) -> None:
        """【R】兜底草稿仍锚定真章节点（source_outline_id 不变）——占位问题靠语义区分，不靠改标识。

        反向断言：source_outline_id 必须仍 = 章节点 id（D4 回填链依赖它，spec f44 §5.2）。
        """
        deps = _make_deps()
        svc = BookService(**deps)
        plan = _plan()
        chapter = _chapter_in(plan)

        await svc._delegate_chapter(plan, chapter, STAGE1_LIMITS)

        kwargs = deps["draft_service"].create.await_args.kwargs
        assert kwargs["source_outline_id"] == chapter.id


class TestSiblingPathAgenticSingle1262:
    """缺陷一姊妹路径：F27 agentic 单章轨 `_msg_content`（同族缺陷，父侧探针取证）。"""

    def test_msg_content_plain_text_from_blocks(self) -> None:
        """【R】AIMessage.content 为 content-block list → 纯文本（非 repr）。

        真实写入通道：agentic_writer_service.run() 第 244-250 行
        `run.final_content = self._final_content(history)` → `draft_service.create(content=...)`。
        """
        from langchain_core.messages import AIMessage

        from inkflow.domain.services.agentic_writer_service import _msg_content

        out = _msg_content(AIMessage(content=CONTENT_BLOCKS))
        assert out == CHAPTER_BODY
        assert _repr_markers(out) == [], f"正文含 repr 特征: {_repr_markers(out)}"
        assert THINKING_TEXT not in out

    def test_msg_content_str_unchanged(self) -> None:
        """回归边界：content 已是 str → 原样返回（行为必须不变）。"""
        from inkflow.domain.services.agentic_writer_service import _msg_content

        assert _msg_content({"content": "正文A"}) == "正文A"

    def test_msg_content_dict_blocks_variant(self) -> None:
        """回归边界：dict 消息形态的 content-block list 同样归一。"""
        from inkflow.domain.services.agentic_writer_service import _msg_content

        out = _msg_content({"content": CONTENT_BLOCKS})
        assert out == CHAPTER_BODY
        assert _repr_markers(out) == []
