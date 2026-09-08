"""#964 F59-M3 chat reasoning 渲染回归 — _text_content delta 归一化 RED 契约测试.

背景（plan E1 实测）：langchain-litellm 在有 `reasoning_content` 时把 `content` 变成
`[{'type':'thinking','thinking':...}, '正文']` 形态的 **list**。chat_agent_service 当前直接
把 `chunk.content` / `output.content` 当 str 塞进 delta 帧 → 前端渲染 `[object Object]`。

契约（GREEN 加 `_text_content(content)->str` 后必须满足）：
1. on_chat_model_end 的 output.content 为 thinking-block 列表 → reasoning 帧先发、
   所有 delta 帧 delta 必须为 str、拼接 == 正文、帧序 reasoning 在 delta 之前。
2. content 为纯 str 时行为不变（回归守护）。
3. content 为纯 thinking 块（无正文）→ 不产出非 str delta；reasoning 帧仍产出。
4. on_chat_model_stream 的 chunk.content 为 thinking-block 列表 → 不产出非 str delta。

当前实现把 list 直接塞 delta → 本批对块路径逐用例 FAIL（delta 是 list / 含 thinking 文本）。
写法镜像 test_chat_agent_service.py 的 `_ReasoningAgent` / `_make_svc` / `_drain` 形态（只读参考，
本文件自带 stub，不改既有文件）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

BASE_PROMPT = "你是 InkFlow 系统级写作 Agent"
PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"

# 思考块（langchain-litellm reasoning 路径实测形态，plan E1）
THINKING_BLOCK = {"type": "thinking", "thinking": "思考A"}
TEXT_BLOCK = {"type": "text", "text": "正文内容"}
PURE_THINKING = [{"type": "thinking", "thinking": "X"}]


class _ReasoningEndAgent:
    """fake agent 只产 on_chat_model_end；content 可含 thinking 块列表（镜像 _ReasoningAgent）。"""

    def __init__(self, output: object) -> None:
        self.output = output

    async def astream_events(self, inputs, version="v2", config=None):
        yield {"event": "on_chat_model_end", "data": {"output": self.output}}


class _ReasoningStreamAgent:
    """fake agent 只产 on_chat_model_stream（run_type=llm）；chunk.content 可含块列表。"""

    def __init__(self, chunk_content: object) -> None:
        self.chunk_content = chunk_content

    async def astream_events(self, inputs, version="v2", config=None):
        yield {
            "event": "on_chat_model_stream",
            "run_type": "llm",
            "data": {"chunk": SimpleNamespace(content=self.chunk_content)},
        }


def _make_svc(agent: object):
    """构造 ChatAgentService（agent=fake + 基础提示词）。"""
    from inkflow.infrastructure.agent.chat_agent_service import ChatAgentService

    return ChatAgentService(agent=agent, system_prompt=BASE_PROMPT)


async def _drain(svc):
    """跑完 stream_events 并返回帧列表。"""
    return [ev async for ev in svc.stream_events(prompt="你好", project_id=PROJECT_ID)]


class TestModelEndThinkingBlockNormalization:
    """契约 1：on_chat_model_end content 为块列表 → delta 归一化 + reasoning 帧先发。"""

    @pytest.mark.asyncio
    async def test_thinking_block_content_normalizes_delta_and_emits_reasoning(self) -> None:
        output = SimpleNamespace(
            content=[THINKING_BLOCK, TEXT_BLOCK],
            additional_kwargs={"reasoning_content": "思考A"},
            tool_calls=[],
        )
        svc = _make_svc(_ReasoningEndAgent(output))
        frames = await _drain(svc)

        reasoning_frames = [ev for ev in frames if ev.type == "reasoning"]
        delta_frames = [ev for ev in frames if ev.type == "delta"]

        # 产出 1 个 reasoning 帧，delta == 思考文本
        assert len(reasoning_frames) == 1
        assert reasoning_frames[0].delta == "思考A"
        # 所有 delta 帧的 delta 必须是 str（不是 list / dict repr）
        assert all(isinstance(f.delta, str) for f in delta_frames), (
            "delta 帧必须为 str（plan E1：list 会被塞进 delta → 前端渲染 [object Object]）"
        )
        # 拼接后 == 正文（不含思考文本 / 不含 [object Object] / 不含 dict repr）
        assert "".join(f.delta for f in delta_frames) == "正文内容"
        # 帧序：reasoning 帧在 delta 帧之前
        assert frames.index(reasoning_frames[0]) < frames.index(delta_frames[0])

    @pytest.mark.asyncio
    async def test_pure_str_content_unchanged(self) -> None:
        """契约 2：content 为纯 str 时行为不变（回归守护）。"""
        output = SimpleNamespace(
            content="六个字正文内容",
            tool_calls=[],
            response_metadata={},
        )
        svc = _make_svc(_ReasoningEndAgent(output))
        frames = await _drain(svc)

        delta_frames = [ev for ev in frames if ev.type == "delta"]
        assert len(delta_frames) > 0
        assert "".join(f.delta for f in delta_frames) == "六个字正文内容"
        # 无 reasoning_content → 无 reasoning 帧
        assert not any(ev.type == "reasoning" for ev in frames)

    @pytest.mark.asyncio
    async def test_pure_thinking_no_text_yields_no_non_str_delta(self) -> None:
        """契约 3：content 为纯 thinking 块（无正文）→ 不产出非 str delta；reasoning 帧仍产出。"""
        output = SimpleNamespace(
            content=PURE_THINKING,
            additional_kwargs={"reasoning_content": "X"},
            tool_calls=[],
        )
        svc = _make_svc(_ReasoningEndAgent(output))
        frames = await _drain(svc)

        reasoning_frames = [ev for ev in frames if ev.type == "reasoning"]
        delta_frames = [ev for ev in frames if ev.type == "delta"]

        assert len(reasoning_frames) == 1
        assert reasoning_frames[0].delta == "X"
        # 不得产出非 str delta（thinking 文本绝不可进 delta 帧）
        assert all(isinstance(f.delta, str) for f in delta_frames), (
            "纯 thinking 无正文时不应产出非 str delta 帧"
        )
        # 无正文 → delta 帧为空（或全为空串），绝不含 thinking 文本
        assert not delta_frames or all(f.delta == "" for f in delta_frames)
        assert "".join(f.delta for f in delta_frames) == ""


class TestStreamThinkingBlockNormalization:
    """契约 4：on_chat_model_stream 的 content 为块列表 → 不产出非 str delta。"""

    @pytest.mark.asyncio
    async def test_stream_thinking_block_skips_non_str_delta(self) -> None:
        agent = _ReasoningStreamAgent([THINKING_BLOCK, TEXT_BLOCK])
        svc = _make_svc(agent)
        frames = await _drain(svc)

        delta_frames = [ev for ev in frames if ev.type == "delta"]
        # 不产出非 str delta（thinking 文本不进 delta 帧）
        assert all(isinstance(f.delta, str) for f in delta_frames), (
            "流式 chunk.content 为 list 时不得把 list 塞进 delta 帧"
        )
        # 流不裸断：仍以 done 终帧收尾
        assert frames[-1].done is True
        assert frames[-1].type == "done"


class TestTextContentDefensive:
    """契约 5（#964）：`_text_content` 防御性分支——真实模型输出形状差异（覆盖率门禁补测）。"""

    @pytest.mark.asyncio
    async def test_plain_str_item_inside_list_is_kept(self) -> None:
        """list 中的裸 str 项必须保留（langchain 合并 chunk 后的实际形态之一）。"""
        output = SimpleNamespace(
            content=["纯文本段", THINKING_BLOCK, TEXT_BLOCK],
            additional_kwargs={"reasoning_content": "思考A"},
            tool_calls=[],
        )
        svc = _make_svc(_ReasoningEndAgent(output))
        frames = await _drain(svc)

        delta_frames = [ev for ev in frames if ev.type == "delta"]
        assert "".join(f.delta for f in delta_frames) == "纯文本段正文内容"
        assert "纯文本段" in "".join(f.delta for f in delta_frames)

    @pytest.mark.asyncio
    async def test_text_block_without_text_key_is_ignored(self) -> None:
        """{"type":"text"} 但缺 text 键 → 忽略该块，不产出非 str delta、不崩溃。"""
        output = SimpleNamespace(
            content=[{"type": "text"}],
            additional_kwargs={},
            tool_calls=[],
        )
        svc = _make_svc(_ReasoningEndAgent(output))
        frames = await _drain(svc)

        delta_frames = [ev for ev in frames if ev.type == "delta"]
        assert all(isinstance(f.delta, str) for f in delta_frames)
        assert "".join(f.delta for f in delta_frames) == ""

    @pytest.mark.asyncio
    async def test_non_str_non_list_content_yields_no_delta(self) -> None:
        """content=None（无正文形态）→ 无 delta 帧、不崩溃、无 reasoning 帧，仍以 done 收尾。"""
        output = SimpleNamespace(content=None, additional_kwargs={}, tool_calls=[])
        svc = _make_svc(_ReasoningEndAgent(output))
        frames = await _drain(svc)

        assert [ev for ev in frames if ev.type == "delta"] == []
        assert not any(ev.type == "reasoning" for ev in frames)
        assert frames[-1].type == "done"
