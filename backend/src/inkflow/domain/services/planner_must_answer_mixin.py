"""PlannerService 必答项判定/回填混入（#1133）：缺失判定 + 服务端确定性兜底.

拆文件动机：planner_service.py 触 monster file ban（>900 行，check_file_length 门禁）——
#1128 必答项收敛修复（判据同源 D1 / 兜底可达 D2 / 确定性回填 D3）涌入后文件达 953 行。
本组方法构成一条自洽链路：缺失判定（`_missing_must_answer_keys` 与
`_must_answers_ready` 同源互补）→ 本轮问题是否覆盖（`_unasked_must_answer_keys`）→
问题归属（`_leading_must_answer_key`）→ 回答确定性落库（`_record_answered_must_keys`
+ 唯一写入点 `_merge_confirmed_items`）→ 冲突门控（`_has_pending_conflict`）；
连同其依赖常量 `_MUST_ANSWER_KEYS` / `_KEY_NORMALIZE` 一并迁出，判据与唯一写入点留在
同文件，「同源」可读可审（#1128 C1/C3）。

不改类契约：`PlannerService(PlannerMustAnswerMixin)` 后这些方法仍是 `@staticmethod`，
既有调用方按 `PlannerService._missing_must_answer_keys(...)` /
`PlannerService._must_answers_ready(...)` 取值零改动（mixin 机制同 `book_run_mixin.py` /
`memory_supersede_mixin.py`）。

依据: specs/f44-book-orchestrator/spec.md §5.1（LLM 动态提问引擎：服务端必答项强约束）、
    §6 R11 ①（题材/篇幅/主题必答 + 模板补问与确定性回填兜底）。
"""

from __future__ import annotations

import builtins

from inkflow.domain.models.planner_session import PlannerSession

_MUST_ANSWER_KEYS = ("题材", "篇幅", "主题")
"""通用必答项 key（服务端强约束，§6 R11 ①）：LLM 输出必须覆盖未确认必答项."""

_KEY_NORMALIZE = {
    "genre": "题材",
    "length": "篇幅",
    "theme": "主题",
    "ending": "结局",
    "protagonist_name": "主角",
    "protagonist": "主角",
    "worldview": "世界观",
    "sect": "门派",
    "supporting_character": "配角",
}
"""英文 key → 中文必答项（#517 兜底：LLM 输出自由，合并前收敛；未知英文 key 原样保留）."""


class PlannerMustAnswerMixin:
    """必答项判定 + 回填混入（全静态方法，无实例状态，供 PlannerService 混入）."""

    @staticmethod
    def _missing_must_answer_keys(
        session: PlannerSession,
        questions: builtins.list[dict],
        confirmed_items: builtins.list[dict],
    ) -> builtins.list[str]:
        """计算缺失必答项：confirmed_items 未覆盖的通用必答项 key.

        与 `_must_answers_ready` 同源（精确互补）——判定只依据 confirmed_items，
        问题文本（questions）不参与：LLM 的 questions（问什么）与 confirmed_items
        （已知什么）是两个独立输出通道，问到了不等于已知（#1128 D1）。
        """
        confirmed_keys = {str(item.get("key", "")) for item in confirmed_items}
        confirmed_keys.update(str(item.get("key", "")) for item in session.confirmed_items)
        return [key for key in _MUST_ANSWER_KEYS if key not in confirmed_keys]

    @staticmethod
    def _unasked_must_answer_keys(
        session: PlannerSession,
        questions: builtins.list[dict],
        confirmed_items: builtins.list[dict],
        *,
        shown_only: bool = False,
    ) -> builtins.list[str]:
        """缺失必答项中本轮问题未覆盖的 key（重试/补问判据，派生自缺失同源判定）.

        shown_only=True（respond 路径）：只补问「已向用户展示过」的必答项——本轮
        LLM 已给出问题集时，服务端仅对问过却仍未落库的必答项补问，不擅自插入
        用户从未见过的新主题（#1128：冻结契约要求 respond 尊重 LLM 本轮问题集）。
        """
        asked = [str(q.get("text", "")) for q in questions]
        missing = PlannerMustAnswerMixin._missing_must_answer_keys(
            session, questions, confirmed_items
        )
        if shown_only:
            shown = [str(q.get("text", "")) for q in session.asked_questions]
            missing = [key for key in missing if any(key in text for text in shown)]
        return [key for key in missing if not any(key in text for text in asked)]

    @staticmethod
    def _merge_confirmed_items(session: PlannerSession, incoming: builtins.list[dict]) -> None:
        """按 key 合并 confirmed_items：新 key 追加、已存在 key 覆盖 value/source."""
        for item in incoming:
            raw_key = item.get("key")
            key = (
                _KEY_NORMALIZE.get(raw_key, raw_key) if isinstance(raw_key, str) else raw_key
            )  # #517 英文→中文兜底
            existing = next(
                (candidate for candidate in session.confirmed_items if candidate.get("key") == key),
                None,
            )
            if existing is None:
                merged = dict(item)
                merged["key"] = key
                session.confirmed_items.append(merged)
            else:
                existing["value"] = item.get("value")
                existing["source"] = item.get("source", existing.get("source"))

    @staticmethod
    def _leading_must_answer_key(question: dict) -> str | None:
        """问题归属的必答项 key：首个 `：`/`:` 前引导段**唯一**命中的 key，否则 None.

        问题文本遵循「key：…」引导式（ROUND1 模板与 LLM 动态提问一致），故只用
        首个分隔符前的引导段判定归属，不做全文子串匹配；引导段同时含多个必答项
        （如「题材与主题：…」）时归属不明确 → 返回 None，保证一问至多映射一键、
        不把整段回答同时写进多个 key（#1128 对抗探针：静默数据污染）。
        """
        text = str(question.get("text", ""))
        separators = [pos for pos in (text.find("："), text.find(":")) if pos >= 0]
        leading = text[: min(separators)] if separators else text
        matched = [key for key in _MUST_ANSWER_KEYS if key in leading]
        return matched[0] if len(matched) == 1 else None

    @staticmethod
    def _record_answered_must_keys(session: PlannerSession) -> None:
        """缺失必答项但用户已回答对应问题 → 确定性落库，不依赖 LLM 提取（#1128 D3）.

        按「引导段唯一命中必答 key」（`_leading_must_answer_key`）定位已展示问题，
        取其回答原文经 `_merge_confirmed_items` 写入 confirmed_items（source=user，
        可审计、区别于 llm_inferred）；多个候选问题优先当前轮（后展示者）；
        归属不明确则不写该 key——留缺失由正常补问流程兜底，不臆造 value。
        """
        for key in PlannerMustAnswerMixin._missing_must_answer_keys(session, [], []):
            for question in reversed(session.asked_questions):
                if PlannerMustAnswerMixin._leading_must_answer_key(question) != key:
                    continue
                qid = question.get("id")
                answer = session.answers.get(qid, "") if isinstance(qid, str) else ""
                if not answer.strip():
                    continue
                PlannerMustAnswerMixin._merge_confirmed_items(
                    session, [{"key": key, "value": answer, "source": "user"}]
                )
                break

    @staticmethod
    def _must_answers_ready(session: PlannerSession) -> bool:
        """必答项齐备判定：confirmed_items keys 覆盖 题材/篇幅/主题."""
        keys = {str(item.get("key", "")) for item in session.confirmed_items}
        return all(key in keys for key in _MUST_ANSWER_KEYS)

    @staticmethod
    def _has_pending_conflict(session: PlannerSession) -> bool:
        """是否存在 pending 冲突（存在即必答项未齐备，不得进入末尾总体确认）."""
        return any(c.get("resolution") == "pending" for c in session.conflicts)
