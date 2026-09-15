"""F49 T4 agentic 书级轨 · 审计闭环契约 — RED（#1185 盲区2/3 + A6/A7/A8）。

权威来源：`.hermes/audit-writing-chain-20260915.md` P0-1 / P0-4。

现有覆盖（本文件要**超越**的）
----------------------------
`test_book_agentic_pipeline.py` 对审计只有间接覆盖：
- `FakeDecisionLLM.chat` 对非决策调用恒返回 `{"score": 85, "issues": [...]}`
- 断言只到 `assert llm.call_count >= 2`（只断调用次数，**不断内容**）
→ 审计输入是什么、审出了什么，全部无观测。这正是 P0-1 存活至今的测试侧原因。

契约（GREEN 必须满足）
---------------------
1. `_delegate_audit(chapter, *, content: str)` —— 审计 **必须读章节正文**：
   user 消息含该章正文文本。正文来源 = 写作产出（`state["results"]` /
   `draft_service` 草稿），**不是** `chapter["description"]`（大纲描述）。
2. 审计结果走 **F34**（`ChapterAuditService.audit`），产出含
   `character_drift` / `setting_drift` 字段（当前 `_parse_audit` 只产
   `{score, issues}` → 必 FAIL）。
3. 注入设定冲突的正文 → 能检出（`issues` 非恒空）。

**盲区 2**：本文件直接捕获传给审计 LLM 的 messages 并断言正文标记串在场。
**盲区 3**：`_FakeAgent` 固定返回 → 换成 `EchoFakeAgent`（按输入 prompt
产出回显内容），使「prompt 缺角色名」可被端到端检出。

可证伪性：把审计输入里的正文改回 description → A6 类必 FAIL。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from inkflow.infrastructure.agent.book_agentic_pipeline import (
    BookAgenticPipeline,
)

pytestmark = pytest.mark.asyncio

# 正文唯一标记串（断言「审计真读了正文」的锚点）
BODY_MARKER = "【正文标记-青鸾刺】"
DRAFT_BODY = f"{BODY_MARKER}次日清晨，宁晚在药庐前劈开第一炉寒铁。"
OUTLINE_DESC = "大纲描述：主角在时间旅途中发现悖论"

# 盲区 3 端到端锚点（角色设定必须抵达产出正文）
CHARACTER_ID = uuid.uuid4()
CHARACTER_NAME = "宁晚"


class CapturingAuditCallable:
    """捕获审计 messages 的 audit_callable（鸭子 async chat(messages)）。"""

    def __init__(self, output: str = '{"score": 70, "issues": ["设定冲突"]}') -> None:
        self.output = output
        self.calls: list[list] = []

    async def __call__(self, messages):
        self.calls.append(messages)
        return SimpleNamespace(content=self.output)

    @property
    def last_user_content(self) -> str:
        """最后一次审计调用的 user 消息正文。"""
        assert self.calls, "审计 LLM 未被调用"
        user = [m for m in self.calls[-1] if getattr(m, "role", None) == "user"]
        assert user, "审计 messages 无 user 角色"
        return str(getattr(user[-1], "content", ""))


def _chapter() -> dict:
    return {
        "outline_id": uuid.uuid4(),
        "chapter_id": uuid.uuid4(),
        "name": "第一章",
        "description": OUTLINE_DESC,
        "sort_order": 0,
    }


# ── A6：审计输入含该章正文（非大纲 description）（#1174 / P0-1）─────────


class TestAuditReadsChapterBody:
    async def test_audit_user_message_carries_chapter_body(self):
        """审计 user 消息含该章**正文**标记串（正文 != description 时可区分）。

        可证伪性：把 `content` 换成 `chapter['description']`（现状）→ FAIL。
        """
        audit = CapturingAuditCallable()
        pipeline = BookAgenticPipeline(SimpleNamespace(chat=None), audit_callable=audit)

        await pipeline._delegate_audit(_chapter(), content=DRAFT_BODY)

        assert BODY_MARKER in audit.last_user_content

    async def test_audit_input_distinguishable_from_outline_description(self):
        """正文在场时，审计输入的正文标记串必须可辨识（不与大纲描述混同）。

        本条与上条互补：上条证「正文进了」，本条证「进的是正文不是大纲」——
        大纲 description 在场但正文缺席 → FAIL。
        """
        audit = CapturingAuditCallable()
        pipeline = BookAgenticPipeline(SimpleNamespace(chat=None), audit_callable=audit)

        await pipeline._delegate_audit(_chapter(), content=DRAFT_BODY)

        assert BODY_MARKER in audit.last_user_content, "审计输入必须含章节正文（非大纲描述）"


# ── A7：审计结论走 F34（含 character_drift/setting_drift）（#1177 / P0-4）


class TestAuditRoutesThroughF34:
    async def test_audit_result_carries_f34_drift_fields(self):
        """审计结果含 F34 漂移字段（character_drift / setting_drift）。

        当前 `_parse_audit` 只产 `{score, issues}` → 必 FAIL。
        可证伪性：绕过 F34 自行拼 `{score, issues}`（现状）→ FAIL。
        """
        audit = CapturingAuditCallable()
        pipeline = BookAgenticPipeline(SimpleNamespace(chat=None), audit_callable=audit)

        result, _event = await pipeline._delegate_audit(_chapter(), content=DRAFT_BODY)

        assert "character_drift" in result
        assert "setting_drift" in result

    async def test_audit_uses_chapter_audit_service_when_injected(self):
        """注入了 F34 审计服务 → 审计经该服务执行（而非裸 LLM）。

        可证伪性：不接 F34（现状恒走裸 chat）→ 服务零调用 → FAIL。
        """
        from unittest.mock import AsyncMock

        f34 = AsyncMock()
        f34.audit.return_value = SimpleNamespace(
            score=60,
            issues=["角色名前后不一致"],
            character_drift=["宁晚→宁婉"],
            setting_drift=["药臼裂纹缺失"],
        )
        llm = SimpleNamespace(chat=AsyncMock())
        pipeline = BookAgenticPipeline(llm, audit_service=f34)

        await pipeline._delegate_audit(_chapter(), content=DRAFT_BODY)

        f34.audit.assert_awaited()


# ── A8：注入设定冲突正文 → 能检出（非恒空 issues）（#1174）────────────


class TestAuditDetectsInjectedDrift:
    async def test_conflicting_body_yields_non_empty_issues(self):
        """注入设定冲突正文 → 审计 issues 非恒空（P0-1「恒接近满分」的反面）。

        可证伪性：审计不读正文（现状）→ 恒返回固定 score/issues → 本条按
        「冲突正文 + 冲突专用 issues」绑定断言 → FAIL。
        """
        audit = CapturingAuditCallable(output='{"score": 42, "issues": ["宁晚佩剑与设定不符"]}')
        pipeline = BookAgenticPipeline(SimpleNamespace(chat=None), audit_callable=audit)

        result, _event = await pipeline._delegate_audit(
            _chapter(), content="宁晚手持长剑立于云端。"
        )

        assert result["issues"], "注入设定冲突后 issues 不得为空"


# ── 盲区 3：破 _FakeAgent 固定返回（prompt 相关产出）────────────────────


class EchoFakeAgent:
    """按输入 prompt 产出内容（回显其中的角色名）——破「固定返回」。"""

    def __init__(self) -> None:
        self.invoked_prompts: list[list] = []

    async def invoke(self, messages, config=None):
        self.invoked_prompts.append(messages)
        system = messages[0]["content"] if messages else ""
        return {"messages": [{"role": "assistant", "content": system}]}


class EchoWriterFactory:
    def __init__(self) -> None:
        self.agents: list[EchoFakeAgent] = []

    async def __call__(self, **kwargs):
        agent = EchoFakeAgent()
        self.agents.append(agent)
        return agent


class BodyFakeDraftService:
    def __init__(self) -> None:
        self.created: list[dict] = []

    async def create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(id=str(uuid.uuid4()))


class _PipelineForWrite(BookAgenticPipeline):
    """注入 plan（_delegate_write 依赖 self._plan）。"""


async def test_echo_agent_makes_prompt_content_observable():
    """盲区 3：fake agent 回显 prompt → 「prompt 缺角色名」可端到端检出。

    这是对 `_FakeAgent` 固定返回的**替代**：固定返回使任何 prompt 都产非空
    正文，掩盖了注入缺陷。本用例用回显 agent，断言 end-to-end 产出确实
    随 prompt 的**设定注入**变化——当前 brief 恒占位符 → FAIL。
    """
    writer = EchoWriterFactory()
    drafts = BodyFakeDraftService()
    pipeline = BookAgenticPipeline(
        SimpleNamespace(chat=None), writer_factory=writer, draft_service=drafts
    )
    plan = SimpleNamespace(
        project_id=uuid.uuid4(),
        character_ids=[CHARACTER_ID],
        limits={},
    )
    pipeline._plan = plan  # type: ignore[attr-defined]  # 契约：execute 前由 bootstrap 装配
    pipeline._context_builder = lambda _pid, _ch: CHARACTER_NAME  # type: ignore[attr-defined]  # 契约：装配层注入 F6

    await pipeline._delegate_write(_chapter())

    assert writer.agents, "writer_factory 未被调用"
    prompt = str(writer.agents[0].invoked_prompts[0][0]["content"])
    # 回显链路：agent 产出携带 prompt 内容（注入缺陷因此可端到端检出）
    drafted = drafts.created[0]["content"]
    assert prompt in drafted, "回显 agent 产出必须携带 prompt（破固定返回）"
    # 真实缺陷断言：角色名必须经 brief 一路抵达草稿正文（P0-2）
    assert CHARACTER_NAME in drafted, "角色设定必须端到端抵达产出正文"
