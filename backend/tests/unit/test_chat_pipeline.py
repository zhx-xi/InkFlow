"""F47 聊天管线契约（spec §2.2 + §3.2）：builtin:chat 单阶段对话模板 + 执行。

被测：pipeline_templates.py BUILTIN_TEMPLATES["builtin:chat"]（PR 1 新增）
- 单阶段 chat（对话助手），无工具循环（v1 范围）
- 输入 variables.prompt 渲染进 LLM 消息；final_output = LLM 回复
- LangGraphAgentPipeline + MockLLMClient 可执行（不联网）

RED 形态：get_template("builtin:chat") 返回 None → 断言 None 失败
（AttributeError: 'NoneType' object has no attribute 'stages'）；无收集 ERROR。
"""

from __future__ import annotations

from inkflow.core.config import config
from inkflow.domain.ports.agent_pipeline import (
    PipelineContext,
    PipelineStage,
    StageStatus,
)
from inkflow.domain.ports.llm_client import ChatResponse
from inkflow.infrastructure.agent.langgraph_pipeline import LangGraphAgentPipeline
from inkflow.infrastructure.agent.pipeline_templates import BUILTIN_TEMPLATES, get_template


class MockLLMClient:
    """Mock LLM — 返回预设响应（镜像 test_langgraph_pipeline.py）。"""

    def __init__(self, responses=None):
        self.responses = responses or []
        self.call_count = 0
        self.calls = []

    async def chat(self, messages, *, model=None, temperature=None, max_tokens=None, **kwargs):
        self.calls.append({"messages": messages, "model": model, "temperature": temperature})
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            if isinstance(resp, Exception):
                raise resp
            return ChatResponse(content=resp, model=model or "mock", finish_reason="stop")
        self.call_count += 1
        return ChatResponse(content=f"mock_response_{self.call_count}", model=model or "mock")


def _chat_stages() -> list[PipelineStage]:
    tpl = get_template("builtin:chat")
    assert tpl is not None, "builtin:chat 模板未注册"
    return tpl.stages


class TestChatTemplate:
    """builtin:chat 模板契约（spec §2.2）。"""

    def test_get_template_returns_config(self) -> None:
        """get_template("builtin:chat") 返回非 None。"""
        assert get_template("builtin:chat") is not None

    def test_registered_in_builtin_templates(self) -> None:
        """BUILTIN_TEMPLATES 含 builtin:chat。"""
        assert "builtin:chat" in BUILTIN_TEMPLATES

    def test_single_stage(self) -> None:
        """角色链 = [chat]（单阶段对话）。"""
        stages = _chat_stages()
        assert [s.id for s in stages] == ["chat"]

    def test_chat_stage_terminal(self) -> None:
        """chat 为入口 + 终点（input_from=[] / output_to=[]）。"""
        by_id = {s.id: s for s in _chat_stages()}
        assert by_id["chat"].input_from == []
        assert by_id["chat"].output_to == []

    def test_chat_role_prompt_assistant_semantics(self) -> None:
        """system_prompt 为对话助手语义（含「对话」或「助手」关键词，宽松防过度约束）。"""
        prompt = _chat_stages()[0].agent.system_prompt
        assert ("对话" in prompt) or ("助手" in prompt) or ("回答" in prompt)

    def test_chat_model_default(self) -> None:
        """chat 角色 model = config.llm_default_model（#415 默认源唯一）。"""
        assert _chat_stages()[0].agent.model == config.llm_default_model


class TestChatExecution:
    """builtin:chat 管线执行（spec §2.2 输出）。"""

    async def test_chat_executes_returns_reply(self) -> None:
        """LangGraph 执行 chat 模板 → final_output = LLM 回复；stage completed。"""
        llm = MockLLMClient(["回复内容"])
        pipeline = LangGraphAgentPipeline(llm)
        ctx = PipelineContext(project_id="proj-1", variables={"prompt": "帮我写一段打斗场景"})
        result = await pipeline.execute(_chat_stages(), ctx)
        assert result.status.value == "completed"
        assert result.final_output == "回复内容"
        assert result.stages[0].stage_id == "chat"
        assert result.stages[0].status == StageStatus.COMPLETED
        assert result.stages[0].output == "回复内容"

    async def test_chat_prompt_rendered_into_messages(self) -> None:
        """user 消息含 prompt 文本（variables 渲染生效）。"""
        llm = MockLLMClient(["回复"])
        pipeline = LangGraphAgentPipeline(llm)
        ctx = PipelineContext(project_id="proj-1", variables={"prompt": "解释这个角色的动机"})
        await pipeline.execute(_chat_stages(), ctx)
        assert llm.calls, "LLM 未被调用"
        messages = llm.calls[0]["messages"]
        joined = "\n".join(m.content for m in messages)
        assert "解释这个角色的动机" in joined
