"""F59-M4 RED (#965): pipeline/supervisor 角色 LLM 调用点思考档位透传。

（spec §2.3 / contract B3/B4）

本文件只锁「调用点透传」，不测解析链本身（解析链 B2 在
test_agent_service_stream.py 追加用例锁定）：三层消费点共享同一透传语义。

契约
----
- B3 ``_call_llm_node``（角色 LLM 调用，langgraph + supervisor 角色节点共用）：
  ``state[\"context\"].reasoning_effort`` 非 None（含 \"high\" / \"default\"）→ 调用
  ``llm.chat`` 的 kwargs 含 ``reasoning_effort=effort``；None → 不含 ``reasoning_effort`` 键。
- B4 ``_decide_next_action``（supervisor 决策调用）：同口径取自 ``state[\"context\"]`` 透传。

RED 预期失败形态（当前实现）
--------------------------
- ``_call_llm_node`` / ``_decide_next_action`` 均直调 ``llm.chat`` 未传
  ``reasoning_effort`` → mock llm 记录的 kwargs 无该键 → ``llm.calls[0][\"reasoning_effort\"]``
  KeyError（B3/B4 缺功能，非语法错误）。
- ``context.reasoning_effort=None`` 守护用例：当前实现本就不注入该键 → PASS（刻意守护，
  防 GREEN 误把 None 也透传）。

说明：``PipelineContext`` 尚无 ``reasoning_effort`` 字段（B1 未实现），本文件用鸭子类型
context 承载该值，并要求实现经 ``getattr(state[\"context\"], \"reasoning_effort\", None)``
防御读取（B3 明确允许既有 dict 形态测试 state）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from inkflow.domain.models.agent_pipeline import SupervisorExecuteConfig
from inkflow.domain.ports.agent_pipeline import PipelineStage
from inkflow.infrastructure.agent.pipeline_nodes import _call_llm_node
from inkflow.infrastructure.agent.supervisor_pipeline import _decide_next_action


class _RecordingLLM:
    """记录每次 chat 调用收到的 kwargs，返回固定 content（mock 必须记录 kwargs 才能断言）。"""

    def __init__(self, content: str = "输出") -> None:
        self.calls: list[dict[str, Any]] = []
        self._content = content

    async def chat(self, messages: list, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(content=self._content)


def _context(reasoning_effort: str | None) -> SimpleNamespace:
    """构造管线上下文替身（B3 getattr 防御兼容 dict/鸭子形态）。

    PipelineContext 尚无 reasoning_effort 字段（B1 未实现），故用鸭子类型承载；
    实现必须经 getattr 防御读取，且不得改变「None 不发 / 非 None 原样透传」两种行为。
    """
    return SimpleNamespace(
        project_id="proj",
        chapter_id=None,
        variables={},
        reasoning_effort=reasoning_effort,
    )


def _stage() -> PipelineStage:
    """最小 PipelineStage（agent 为 SimpleNamespace，供调用点读 model/temperature/max_tokens）。"""
    return PipelineStage(
        id="writer",
        name="writer",
        agent=SimpleNamespace(
            id="writer",
            name="writer",
            system_prompt="",
            model="m",
            temperature=0.7,
            max_tokens=100,
        ),
        input_from=[],
    )


def _node_state(reasoning_effort: str | None) -> tuple[dict, _RecordingLLM, str]:
    """构造 _call_llm_node 输入 state（context + stages + llm_client + results）。"""
    llm = _RecordingLLM()
    state: dict = {
        "context": _context(reasoning_effort),
        "stages": {"writer": _stage()},
        "llm_client": llm,
        "results": {},
    }
    return state, llm, "writer"


def _supervisor_state(reasoning_effort: str | None) -> tuple[dict, _RecordingLLM]:
    """构造 _decide_next_action 输入 state（决策消息要求 JSON：execute/writer）。"""
    llm = _RecordingLLM(content=json.dumps({"action": "execute", "role": "writer"}))
    state: dict = {
        "context": _context(reasoning_effort),
        "stages": {"writer": _stage()},
        "llm_client": llm,
        "results": {},
        "route_history": [],
        "steps": 0,
        "consecutive": 0,
        "last_role": "",
        "final_output": "",
    }
    return state, llm


# ── B3: _call_llm_node 角色调用透传 ──


class TestCallLlmNodeReasoningEffort:
    """B3 角色 LLM 调用点：context 档位透传到 llm.chat kwargs。"""

    @pytest.mark.asyncio
    async def test_high_passed_through_as_kwarg(self) -> None:
        """context.reasoning_effort='high' → llm.chat 收到 reasoning_effort='high'。"""
        state, llm, stage_id = _node_state("high")
        await _call_llm_node(state, stage_id, [])
        assert llm.calls, "角色节点必须调用 llm.chat"
        assert llm.calls[0]["reasoning_effort"] == "high", (
            f"角色调用必须透传 context 档位（B3），实得 kwargs={llm.calls[0]!r}"
        )

    @pytest.mark.asyncio
    async def test_default_level_also_passed_through(self) -> None:
        """\"default\" 也是显式档位：非 None 即原样透传（剥离归属 capability_probe）。"""
        state, llm, stage_id = _node_state("default")
        await _call_llm_node(state, stage_id, [])
        assert llm.calls, "角色节点必须调用 llm.chat"
        assert llm.calls[0]["reasoning_effort"] == "default", (
            f"default 档位同样透传（B3），实得 kwargs={llm.calls[0]!r}"
        )

    @pytest.mark.asyncio
    async def test_none_omits_reasoning_effort_key(self) -> None:
        """context.reasoning_effort=None → llm.chat kwargs 不含 reasoning_effort 键。"""
        state, llm, stage_id = _node_state(None)
        await _call_llm_node(state, stage_id, [])
        assert llm.calls, "角色节点必须调用 llm.chat"
        assert "reasoning_effort" not in llm.calls[0], (
            f"None 时不得注入 reasoning_effort 键（B3），实得 kwargs={llm.calls[0]!r}"
        )


# ── B4: _decide_next_action 决策调用透传 ──


class TestDecideNextActionReasoningEffort:
    """B4 supervisor 决策调用点：context 档位透传到决策 llm.chat kwargs。"""

    @pytest.mark.asyncio
    async def test_decision_callback_passes_reasoning_effort(self) -> None:
        """state['context'].reasoning_effort='high' → 决策 llm.chat 收到档位。"""
        state, llm = _supervisor_state("high")
        await _decide_next_action(state, SupervisorExecuteConfig())
        assert llm.calls, "决策必须调用 llm.chat"
        assert llm.calls[0]["reasoning_effort"] == "high", (
            f"决策调用必须透传 context 档位（B4），实得 kwargs={llm.calls[0]!r}"
        )

    @pytest.mark.asyncio
    async def test_decision_callback_none_omits_key(self) -> None:
        """state['context'].reasoning_effort=None → 决策 llm.chat 不含档位键。"""
        state, llm = _supervisor_state(None)
        await _decide_next_action(state, SupervisorExecuteConfig())
        assert llm.calls, "决策必须调用 llm.chat"
        assert "reasoning_effort" not in llm.calls[0], (
            f"None 时不得注入 reasoning_effort 键（B4），实得 kwargs={llm.calls[0]!r}"
        )
