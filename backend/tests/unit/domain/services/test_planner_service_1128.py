"""F44 #1128 访谈必答项收敛契约（TDD RED 阶段）。

权威来源：specs/f44-book-orchestrator/spec.md §5.1「LLM 动态提问引擎」
（服务端必答项强约束）+ §6 R11 ① + §7 场景 15/16。

缺陷（rc5 干净环境实测，round=15 仍 confirm=False）：
    planner 每轮都在问「题材」「主题」，用户每轮都答，但答案稳定不落库
    （「主题」连答 4 次仍不落）→ confirming 恒 False → confirm 抛 ValueError
    「非确认阶段，请先完成必答项」→ 新用户首次建书永久卡死。

三条独立缺陷（本文件逐条立契约）：
    D1 判据分叉：`_missing_must_answer_keys` 以「问题文本含 key」当作「未缺失」
       （planner_service.py:795）——与 `_must_answers_ready`（:847-851，只看
       confirmed_items）**不同源**。问题文本含「主题」→ 判「未缺失」→ missing 空；
       但提取结果不含「主题」→ 必答项实为缺失 → 两条链路分叉。
    D2 兜底不可达：缺失必答项的整段兜底（重试 + ROUND1 模板补问，:651-669）
       被 `if answers is None:`（:654）门控——仅 start 路径可达；respond 路径
       （访谈真正的推进路径）`answers` 为 dict → 兜底**从不执行**。
    D3 无确定性出路：`session.confirmed_items` 生产代码唯一写入点
       `_merge_confirmed_items`（:799-816）的 key 完全来自 LLM 提取结果，
       用户回答文本**从不直接决定 key** → 提取通道持续不吐「主题」时无出路。

契约（GREEN 必须满足）：
    C1 判据同源：`_missing_must_answer_keys` 判据 = 「该 key 是否在
       confirmed_items 中」，与 `_must_answers_ready` 同源；问题文本是否含
       该 key **不参与**缺失判定。
    C2 兜底可达：必答项未落库时，respond 路径的兜底链真实触发
       （重试 / 模板补问 / 回答直落库），不再被 `answers is None` 门控屏蔽。
    C3 收敛保底：必答键经 N 轮仍未落库时，用户回答经**确定性**路径落库为
       对应 key（不依赖 LLM 提取偶然性）→ confirming 可达成 → confirm 成功。
    C4 反例守护：必答项齐备时不误触兜底（不重复提问、不覆盖既有 value）。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from inkflow.domain.models.planner_session import PlannerSession
from inkflow.domain.services.planner_service import (
    ROUND1_QUESTIONS,
    PlannerService,
)

_MUST_ANSWER_KEYS = ("题材", "篇幅", "主题")
"""通用必答项 key（服务端强约束，spec §6 R11 ①）。"""


def _pid() -> uuid.UUID:
    return uuid.uuid4()


def _sid() -> uuid.UUID:
    return uuid.uuid4()


def _session(**overrides: object) -> PlannerSession:
    base: dict[str, object] = {
        "id": _sid(),
        "project_id": _pid(),
        "status": "drafting",
        "one_liner": "写一本关于时间旅者的悬疑小说",
        "round": 1,
        "asked_questions": list(ROUND1_QUESTIONS),
        "answers": {},
        "authorized": [],
        "writing_plan_id": None,
        "confirmed_items": [],
        "conflicts": [],
        "confirming": False,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    base.update(overrides)
    return PlannerSession(**base)  # type: ignore[arg-type]  # 契约测试字典装配


def _make_repo(session: PlannerSession | None = None):
    from unittest.mock import AsyncMock

    repo = AsyncMock()
    repo.get_planner_session.return_value = session
    repo.get_writing_plan.return_value = None
    return repo


def _llm_json(
    questions: list | None = None,
    confirmed_items: list | None = None,
    conflicts: list | None = None,
) -> str:
    """构造 LLM 结构化 JSON 输出字符串（spec §5.1 prompt 输出形状）。"""
    return json.dumps(
        {
            "questions": questions or [],
            "confirmed_items": confirmed_items or [],
            "conflicts": conflicts or [],
        },
        ensure_ascii=False,
    )


class _ScriptedLLM:
    """脚本化 LLM：按调用次序返回预设 content，末条可重复。

    真实 provider 的不确定性正是 #1128 的触发条件——用脚本化响应把
    「问题文本含 key 但提取结果不含 key」这一具体形态**确定性地**复现出来。
    """

    def __init__(self, contents: list[str]) -> None:
        self._contents = list(contents)
        self.calls: list[list] = []

    async def chat(self, messages, model=None, temperature=None):
        from inkflow.domain.ports.llm_client import ChatResponse

        self.calls.append(list(messages))
        index = min(len(self.calls) - 1, len(self._contents) - 1)
        return ChatResponse(content=self._contents[index], model="test")


def _make_service(repo, llm_client=None) -> PlannerService:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    return PlannerService(
        repo=repo,
        write_auto=AsyncMock(return_value=None),
        outline_service=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4())),
        character_service=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4())),
        llm_client=llm_client,
        project_context_getter=AsyncMock(return_value="设定摘要：时间旅者，悬疑基调"),
        prompt_manager=None,
        llm_default_model="test/model",
    )


# LLM 产出的必答项问题：文本**含**「题材」「主题」关键词
_ASKING_QUESTIONS = [
    {"id": "q1", "text": "题材：悬疑还是科幻？", "template": "___", "kind": "general"},
    {"id": "q3", "text": "主题：能否一句话描述主题？", "template": "主题是 ___", "kind": "general"},
]

# LLM 提取结果：只吐 题材/篇幅，**持续不吐**「主题」——issue 实测形态
_EXTRACTED_WITHOUT_THEME = [
    {"key": "题材", "value": "悬疑", "source": "user"},
    {"key": "篇幅", "value": "20 万字", "source": "user"},
]


# ── C1 判据同源（D1）─────────────────────────────────────────────


def test_missing_must_answer_keys_ignores_question_text() -> None:
    """C1 锚点：问题文本含「主题」但提取结果不含 → 仍判缺失（当前恒空 = 缺陷）。

    issue 复现核心断言：判据必须与 `_must_answers_ready` 同源（只看
    confirmed_items），不得被问题文本「已问到」误导。
    """
    session = _session()
    missing = PlannerService._missing_must_answer_keys(session, _ASKING_QUESTIONS, [])

    assert "主题" in missing, "问题文本含「主题」不得抵消提取结果缺失（D1 判据分叉）"
    assert set(missing) == set(_MUST_ANSWER_KEYS), "confirmed_items 为空 → 三个必答项全缺失"


def test_missing_judgement_shares_source_with_ready_judgement() -> None:
    """C1 同源契约：判据为空的充要条件 = 必答项齐备（两者必须恒等互补）。"""
    for keys in (
        [],
        ["题材"],
        ["题材", "篇幅"],
        ["题材", "篇幅", "主题"],
        ["题材", "篇幅", "other"],
    ):
        session = _session(
            confirmed_items=[{"key": k, "value": "v", "source": "user"} for k in keys]
        )
        confirmed = [{"key": k, "value": "v", "source": "user"} for k in keys]
        missing = PlannerService._missing_must_answer_keys(session, _ASKING_QUESTIONS, confirmed)
        ready = PlannerService._must_answers_ready(session)

        assert (not missing) is ready, f"keys={keys}: missing={missing} 与 ready={ready} 不同源"


# ── C2/C3 场景收敛（D2 + D3）──────────────────────────────────────


@pytest.mark.asyncio
async def test_respond_converges_when_extraction_never_yields_theme() -> None:
    """C3 核心实现：提取通道持续不吐「主题」→ 用户回答仍能确定性收敛。

    issue 验收：主题缺失能被识别 + 兜底触发 + 最终可 confirm（15 轮内收敛）。
    不依赖 LLM 提取偶然性——用户每轮都答，必答键必须落地。
    """
    content = _llm_json(_ASKING_QUESTIONS, _EXTRACTED_WITHOUT_THEME, [])
    session = _session()
    repo = _make_repo(session)
    svc = _make_service(repo, llm_client=_ScriptedLLM([content]))

    result = None
    for round_index in range(1, 16):
        result = await svc.respond(
            session.id,
            {"answer": f"第 {round_index} 轮回答：主题是时间与宿命"},
        )
        if result.confirming:
            break
        assert round_index < 15, "15 轮内未收敛到 confirming（#1128 卡死复现）"

    assert result is not None and result.confirming is True, "主题持续不落库 → 访谈卡死"
    keys = {str(item.get("key", "")) for item in session.confirmed_items}
    assert set(_MUST_ANSWER_KEYS) <= keys, "必答三键必须全部落库"

    confirmed = await svc.respond(session.id, {}, confirm=True)
    assert confirmed.completed is True, "confirming=True 后 confirm 应完成建计划"


@pytest.mark.asyncio
async def test_respond_missing_key_stays_reachable_in_fallback() -> None:
    """C2 锚点：respond 路径必答项缺失时，兜底链真实触发（当前被门控屏蔽）。

    RED 有效性关键：LLM 本轮 questions **完全不含**「主题」——因此若补问问题
    出现在返回值中，只可能来自服务端兜底（ROUND1 模板题），不可能是 LLM 自带。
    断言**无条件**执行（不设 confirming 短路分支），否则该用例会被 LLM 自带
    问题文本偶然满足而失去 RED 信号。
    """
    # LLM 只问题材（兜底前不涉及主题）且提取结果持续缺「主题」
    content = _llm_json(
        [{"id": "q1", "text": "题材：悬疑还是科幻？", "template": "___", "kind": "general"}],
        _EXTRACTED_WITHOUT_THEME,
        [],
    )
    session = _session()
    repo = _make_repo(session)
    svc = _make_service(repo, llm_client=_ScriptedLLM([content]))

    result = await svc.respond(session.id, {"answer": "悬疑为主"})

    assert result.confirming is False, "「主题」未落库不得进入确认阶段"
    asked = [str(q.get("text", "")) for q in result.questions]
    assert any("主题" in text for text in asked), (
        "必答项「主题」本轮未被 LLM 问及 → 服务端兜底补问必须出现在 questions"
        f"（D2 兜底不可达）；实际 questions={asked}"
    )


@pytest.mark.asyncio
async def test_respond_backfill_writes_answer_deterministically() -> None:
    """C3 直落契约：必答键缺失 + 该键问题已被回答 → 回答确定性落库为对应 key。

    复用既有 `_merge_confirmed_items`（key 归一化），source 标记为 user
    以区别于 LLM 推断值，供用户审计（spec §2.2）。
    """
    content = _llm_json(_ASKING_QUESTIONS, _EXTRACTED_WITHOUT_THEME, [])
    session = _session(
        asked_questions=list(_ASKING_QUESTIONS),
        answers={"q3": "主题是时间与宿命的对抗"},
    )
    repo = _make_repo(session)
    svc = _make_service(repo, llm_client=_ScriptedLLM([content]))

    await svc.respond(session.id, {"q3": "主题是时间与宿命的对抗"})

    themes = [item for item in session.confirmed_items if str(item.get("key", "")) == "主题"]
    assert themes, "用户已回答该键问题 → 必须确定性落库，不依赖 LLM 提取"
    assert themes[0].get("value"), "落库 value 不得为空"


# ── C4 反例守护 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_respond_missing_key_triggers_retry_with_hint() -> None:
    """C2 重试通道（§5.1「校验失败重试 1 次」）：必答项缺失 → 真实重试并指名补问。

    旧实现整段兜底被 `if answers is None:` 门控 → respond 路径既不重试也不补问
    （chat 只调 1 次）。本用例断言重试确实发生且提示语含缺失 key。
    """
    asking = [{"id": "q1", "text": "题材：悬疑还是科幻？", "template": "___", "kind": "general"}]
    llm = _ScriptedLLM(
        [
            _llm_json(asking, _EXTRACTED_WITHOUT_THEME, []),
            _llm_json(asking, _EXTRACTED_WITHOUT_THEME, []),
        ]
    )
    session = _session()
    repo = _make_repo(session)
    svc = _make_service(repo, llm_client=llm)

    await svc.respond(session.id, {"answer": "悬疑为主"})

    assert len(llm.calls) == 2, f"必答项缺失应重试 1 次（chat 调用 2 次），实际 {len(llm.calls)}"
    retry_text = " ".join(str(m.get("content", "")) for m in llm.calls[1])
    assert "主题" in retry_text, f"重试提示必须指名缺失必答项「主题」；实际：{retry_text!r}"


@pytest.mark.asyncio
async def test_backfill_one_question_maps_to_one_key_only() -> None:
    """C3 反例：同一问题文本含多个必答 key → 不得把同一答案写进多个 key。

    对抗探针实测缺陷：问题文本「题材与主题：…」同时含两个 key 时，前缀子串
    匹配会把整段回答同时写成 题材 与 主题 → 污染 题材 的 value（后续喂
    extract_limits_from_interview / _complete）。一问至多映射一键。
    """
    question = {
        "id": "qx",
        "text": "题材与主题：请同时说说题材和主题？",
        "template": "___",
        "kind": "general",
    }
    session = _session(
        round=2,
        asked_questions=[dict(question)],
        answers={"qx": "悬疑，主题是宿命"},
        confirmed_items=[{"key": "篇幅", "value": "20 万", "source": "user"}],
    )
    repo = _make_repo(session)
    svc = _make_service(repo, llm_client=_ScriptedLLM([_llm_json([], [], [])]))

    await svc.respond(session.id, {"qx": "悬疑，主题是宿命"})

    values = {str(i.get("key", "")): i.get("value") for i in session.confirmed_items}
    same = [k for k, v in values.items() if v == "悬疑，主题是宿命"]
    assert len(same) <= 1, f"同一答案被写入多个必答 key（应至多一个）：{values}"


@pytest.mark.asyncio
async def test_respond_all_keys_present_no_backfill_interference() -> None:
    """C4 反例：必答项齐备 → 正常进入 confirm，不误触兜底、不覆盖既有 value。"""
    content = _llm_json(
        [],
        [
            {"key": "题材", "value": "悬疑", "source": "user"},
            {"key": "篇幅", "value": "20 万字", "source": "user"},
            {"key": "主题", "value": "时间与宿命", "source": "user"},
        ],
        [],
    )
    session = _session(round=3)
    repo = _make_repo(session)
    svc = _make_service(repo, llm_client=_ScriptedLLM([content]))

    result = await svc.respond(session.id, {"answer": "就这样"})

    assert result.confirming is True, "必答项齐备 → 必须进入确认阶段"
    assert result.questions == [], "确认阶段不得再发问"
    values = {str(i.get("key", "")): i.get("value") for i in session.confirmed_items}
    assert values["主题"] == "时间与宿命", "既有 value 不得被兜底覆盖"
    assert len(session.confirmed_items) == 3, "不得重复追加已存在 key"


def test_must_answer_keys_constant_is_spec_trio() -> None:
    """C4 锚点：必答项范围未被本轮修复扩大/缩小（spec §6 R11 ① 题材/篇幅/主题）。"""
    assert set(_MUST_ANSWER_KEYS) == set(
        __import__(
            "inkflow.domain.services.planner_service",
            fromlist=["_MUST_ANSWER_KEYS"],
        )._MUST_ANSWER_KEYS
    )
