"""F26 M1 deepagents 集成层 RED 契约测试 — harness 装配 + profiles 注册表。

设计假设（父侧定稿，GREEN 按此实现；infrastructure/agent/deepagents/ 整包新建，
含 __init__.py / harness.py / profiles.py 三文件）：

1. profiles.py（infrastructure/agent/deepagents/profiles.py 新建）：
   - HARNESS_PROFILES: dict[str, HarnessProfile]  # 模块级注册表；
     HarnessProfile 为 deepagents 类型（测试不 import deepagents 库，断言 key 存在即可）
   - ensure_profile(model_name: str) -> str：
     确保 HarnessProfile 已注册。注册 key 格式必须是 openai:<model_name>
     （Spike ③ 实测：ChatOpenAI 实例解析 provider='openai'；anthropic: 前缀
     不匹配会静默用默认 profile）。已注册 → 直接返回 key；未注册 → 注册默认
     profile 后返回 key。

2. harness.py（infrastructure/agent/deepagents/harness.py 新建）：
   def build_deep_agent(*, model: str, api_key: str, base_url: str,
                        tools: list[Tool], system_prompt: str,
                        profile_key: str | None = None) -> Agent:
   - model 可能带 registry 前缀（zhipu/glm-4.5）→ 内部 parse_model_string 剥离
     成 glm-4.5；无前缀（parse_model_string 抛 ValueError）→ 原样使用（防御）
   - ChatOpenAI 构造（镜像既有 _get_chat_model 模式；from-import 绑定 harness
     模块命名空间，测试 patch 目标即 harness.ChatOpenAI）：
     ChatOpenAI(model=<剥离后模型名>, openai_api_base=base_url,
                openai_api_key=api_key, temperature=0.2)
   - create_deep_agent 调用：
     create_deep_agent(model=<ChatOpenAI 实例>, tools=<映射后工具>,
                       system_prompt=system_prompt)
     **不传 excluded_tools kwarg**——0.7.5 真实签名无该参数（Codex GREEN 实测
     TypeError: unexpected keyword argument）；排除语义由 HarnessProfile
     excluded_tools 字段承载（ensure_profile 注册的默认 profile 含 8 项 FS
     工具排除集 + subagent disabled，create_deep_agent 内部按 openai:<model>
     命中该 profile）。测试锁「不传非法 kwarg」+ profile 层排除集断言。
   - 工具映射：Tool.spec.name → 工具名、Tool.spec.description → 描述
     （deepagents @tool 或 BaseTool 形态均可，测试不锁具体类）
   - excluded_tools 默认清单：必须包含 read_file（Spike ③ 实测 read_file 为
     默认 FS 工具之一；完整清单以 deepagents 0.7.5 源码为准，测试只断言
     read_file 在其中 + 长度 >= 1）
   - 返回 create_deep_agent 的返回值

3. __init__.py：导出 build_deep_agent（测试从 harness 直接 import，不依赖
   __init__.py 导出，也不做 hasattr 守卫断言）。

4. profile_key 缺省语义：build_deep_agent 不传 profile_key 时注册表必须出现
   openai:<剥离后模型名>（联动断言见 TestProfiles 第 3 个用例）；显式传入则
   原样使用、只断言不抛错。内部是 ensure_profile(model_name) 还是
   ensure_profile(f"openai:{model_name}") 不锁——两种形态下观测 key 一致。

5. ToolSpec/Tool 惰性 import（GREEN 前两模块均不存在，属 F26 M2 工具集契约）：
   - from inkflow.domain.models.agent_tools import ToolSpec
   - from inkflow.infrastructure.agent.tools import Tool
   - 构造形态：Tool(spec=ToolSpec(name=..., description=..., input_schema={}),
     func=<async callable>)
   惰性理由：两模块顶部 import 会让收集错误报字母序更前的
   inkflow.domain.models.agent_tools，干扰父侧对主契约（deepagents）的 RED
   确认（F21「主模块顶部 + 其余惰性」形态）。

6. model 断言形态：call.kwargs["model"] is mock_chat_cls.return_value（同一性
   断言）——实测 isinstance(x, <MagicMock 实例>) 抛 TypeError: isinstance()
   arg 2 must be a type，不能用 isinstance 断言「ChatOpenAI 实例」；同一性断言
   等价（证明 ChatOpenAI(...) 构造结果被透传）且 GREEN 零风险。

7. 空 tools 列表（[]）为合法输入：装配层只做映射，空集直接透传。

RED 预期（实测形态）：收集期 1 error / exit 2，唯一错误 =
ModuleNotFoundError: No module named 'inkflow.infrastructure.agent.deepagents'
（deepagents 子包整包不存在；父包 inkflow.infrastructure.agent 已存在（F4
既有文件）。顶部仅 import 主契约模块 deepagents.harness / deepagents.profiles，
ToolSpec/Tool 惰性 → 收集错误唯一聚焦 deepagents）。GREEN 落地后本文件自动
收集，14 用例全部转绿。

本文件 build_deep_agent / ensure_profile 均为同步用例（不依赖 pytest-asyncio 模式，
auto/STRICT 均不影响）；_make_sync_wrapper 运行中事件循环路径（独立 worker 线程
桥接）为 async 用例。
"""

from unittest import mock
from unittest.mock import AsyncMock

import pytest

from inkflow.infrastructure.agent.deepagents.harness import build_deep_agent
from inkflow.infrastructure.agent.deepagents.profiles import (
    DEFAULT_EXCLUDED_TOOLS,
    HARNESS_PROFILES,
    ensure_profile,
)

AGENT_SENTINEL = object()


# ── 构造辅助 ──────────────────────────────────────────────────────────


def _make_tool(name="search_characters", description="搜索角色"):
    """构造一个 F26 只读工具（ToolSpec/Tool 惰性 import，GREEN 前均不存在）。"""
    from inkflow.domain.models.agent_tools import ToolSpec
    from inkflow.infrastructure.agent.tools import Tool

    return Tool(
        spec=ToolSpec(name=name, description=description, input_schema={}),
        func=AsyncMock(),
    )


def _make_tools(count):
    """构造 count 个只读工具（名称/描述自动编号）。"""
    return [_make_tool(name=f"tool_{i}", description=f"工具 {i}") for i in range(count)]


@pytest.fixture
def harness_patches():
    """patch deepagents.harness 模块命名空间：ChatOpenAI + create_deep_agent。"""
    with (
        mock.patch("inkflow.infrastructure.agent.deepagents.harness.ChatOpenAI") as chat_cls,
        mock.patch(
            "inkflow.infrastructure.agent.deepagents.harness.create_deep_agent",
            return_value=AGENT_SENTINEL,
        ) as create,
    ):
        yield chat_cls, create


class TestBuildDeepAgent:
    """build_deep_agent 装配契约（patch 目标 = harness 模块命名空间）。"""

    def test_basic_assembly(self, harness_patches):
        """带 registry 前缀模型 + 2 工具 + system_prompt 的基本装配契约。"""
        chat_cls, create = harness_patches
        build_deep_agent(
            model="zhipu/glm-4.5",
            api_key="sk-test",
            base_url="https://x/v1",
            tools=_make_tools(2),
            system_prompt="你是一个助手",
        )
        create.assert_called_once()
        call = create.call_args
        assert call.kwargs["model"] is chat_cls.return_value
        assert call.kwargs["system_prompt"] == "你是一个助手"
        assert len(call.kwargs["tools"]) == 2
        # 0.7.5 真实签名无 excluded_tools（GREEN 实测 TypeError）——排除语义走
        # HarnessProfile（TestExcludedTools 锁 profile 层），此处锁「不传非法 kwarg」
        assert "excluded_tools" not in call.kwargs

    def test_chat_openai_stripped_model(self, harness_patches):
        """前缀剥离：zhipu/glm-4.5 → ChatOpenAI(model='glm-4.5', temperature=0.2)。"""
        chat_cls, _ = harness_patches
        build_deep_agent(
            model="zhipu/glm-4.5",
            api_key="sk-test",
            base_url="https://x/v1",
            tools=_make_tools(2),
            system_prompt="你是一个助手",
        )
        chat_cls.assert_called_once_with(
            model="glm-4.5",
            openai_api_base="https://x/v1",
            openai_api_key="sk-test",
            temperature=0.2,
        )

    def test_model_without_prefix_unchanged(self, harness_patches):
        """无 registry 前缀（parse_model_string 抛 ValueError）→ 模型名原样使用（防御）。"""
        chat_cls, _ = harness_patches
        build_deep_agent(
            model="glm-4.5", api_key="sk-test", base_url="https://x/v1", tools=[], system_prompt="p"
        )
        chat_cls.assert_called_once_with(
            model="glm-4.5",
            openai_api_base="https://x/v1",
            openai_api_key="sk-test",
            temperature=0.2,
        )

    def test_returns_create_deep_agent_result(self, harness_patches):
        """返回 create_deep_agent 的返回值（sentinel 透传，非包装/非 None）。"""
        _, create = harness_patches
        result = build_deep_agent(
            model="glm-4.5", api_key="sk", base_url="https://x/v1", tools=[], system_prompt="p"
        )
        assert result is AGENT_SENTINEL
        create.assert_called_once()

    def test_empty_api_key_and_base_url_omitted(self, harness_patches):
        """api_key/base_url 为空 → 不传 openai_api_key/openai_api_base（空串分支）。"""
        chat_cls, _ = harness_patches
        build_deep_agent(
            model="glm-4.5", api_key="", base_url="", tools=[], system_prompt="p"
        )
        chat_cls.assert_called_once_with(model="glm-4.5", temperature=0.2)

    def test_checkpointer_is_in_memory_saver(self, harness_patches):
        """create_deep_agent 收到 checkpointer=InMemorySaver()（HITL resume thread 隔离）。"""
        from langgraph.checkpoint.memory import InMemorySaver

        _, create = harness_patches
        build_deep_agent(
            model="glm-4.5", api_key="sk", base_url="https://x/v1", tools=[], system_prompt="p"
        )
        checkpointer = create.call_args.kwargs["checkpointer"]
        assert isinstance(checkpointer, InMemorySaver)


class TestProfiles:
    """HARNESS_PROFILES 注册表 + ensure_profile 契约（注册 key = openai:<model>）。"""

    @pytest.fixture(autouse=True)
    def _clean_registry(self):
        """每个用例前清空模块级注册表（HARNESS_PROFILES 跨用例共享）。"""
        HARNESS_PROFILES.clear()
        yield

    def test_ensure_profile_returns_openai_key_and_registers(self):
        """key 格式 openai:<model>；调用后注册表含该 key（Spike ③ 实测格式）。"""
        key = ensure_profile("glm-4.5")
        assert key == "openai:glm-4.5"
        assert "openai:glm-4.5" in HARNESS_PROFILES

    def test_ensure_profile_idempotent(self):
        """幂等：两次调用返回同一 key，注册表长度不变（不重复注册）。"""
        first = ensure_profile("glm-4.5")
        second = ensure_profile("glm-4.5")
        assert first == second
        assert first == "openai:glm-4.5"
        assert len(HARNESS_PROFILES) == 1

    def test_build_deep_agent_registers_default_profile(self, harness_patches):
        """联动：缺省 profile_key → 注册表出现 openai:<剥离后模型名>（glm-4.5）。"""
        build_deep_agent(
            model="zhipu/glm-4.5",
            api_key="sk-test",
            base_url="https://x/v1",
            tools=[],
            system_prompt="p",
        )
        assert "openai:glm-4.5" in HARNESS_PROFILES

    def test_explicit_profile_key_no_error(self, harness_patches):
        """显式 profile_key → 原样使用、不抛错、装配成功（不断言内部注册路径）。"""
        _, create = harness_patches
        result = build_deep_agent(
            model="glm-4.5",
            api_key="sk",
            base_url="https://x/v1",
            tools=[],
            system_prompt="p",
            profile_key="openai:custom",
        )
        assert result is AGENT_SENTINEL
        create.assert_called_once()


class TestToolMapping:
    """Tool.spec → deepagents 工具映射契约（不锁 @tool / BaseTool 具体形态）。"""

    def test_single_tool_mapped_length(self, harness_patches):
        """单个 Tool（search_characters）→ 映射后 tools 长度 1。"""
        _, create = harness_patches
        build_deep_agent(
            model="glm-4.5",
            api_key="sk",
            base_url="https://x/v1",
            tools=[_make_tool()],
            system_prompt="p",
        )
        assert len(create.call_args.kwargs["tools"]) == 1

    def test_two_tools_mapped_length(self, harness_patches):
        """两个 Tool → 映射后 tools 长度 2（数量透传）。"""
        _, create = harness_patches
        build_deep_agent(
            model="glm-4.5",
            api_key="sk",
            base_url="https://x/v1",
            tools=_make_tools(2),
            system_prompt="p",
        )
        assert len(create.call_args.kwargs["tools"]) == 2

    def test_mapped_tool_loose_shape(self, harness_patches):
        """宽松形态：非空 + 每个元素可调用或含 name 属性（兼容 @tool 函数与 BaseTool）。"""
        _, create = harness_patches
        build_deep_agent(
            model="glm-4.5",
            api_key="sk",
            base_url="https://x/v1",
            tools=[_make_tool()],
            system_prompt="p",
        )
        tools = create.call_args.kwargs["tools"]
        assert len(tools) >= 1
        assert all(callable(t) or hasattr(t, "name") for t in tools)

    def test_mapped_tool_sync_invoke_supported(self):
        """真实形态（M5 冒烟实测缺陷）：映射产物必须支持 sync invoke（deepagents ToolNode
        sync 路径）；coroutine-only StructuredTool 抛 NotImplementedError。
        """
        from inkflow.infrastructure.agent.deepagents.harness import _map_tools

        mapped = _map_tools([_make_tool(name="count_words")])
        assert len(mapped) == 1
        result = mapped[0].invoke({"text": "你好"})
        assert result is not None

    @pytest.mark.asyncio
    async def test_mapped_tool_sync_invoke_in_running_loop(self) -> None:
        """运行中事件循环内调 sync wrapper → 独立 worker 线程执行（不 asyncio.run）。"""
        from inkflow.infrastructure.agent.deepagents.harness import _map_tools

        mapped = _map_tools([_make_tool(name="count_words")])
        result = mapped[0].invoke({"text": "你好"})
        assert result is not None

    @pytest.mark.asyncio
    async def test_mapped_tool_sync_invoke_running_loop_error_propagates(self) -> None:
        """运行中事件循环内 async_fn 抛异常 → 原异常经 worker 线程向上传播。"""
        from inkflow.domain.models.agent_tools import ToolSpec
        from inkflow.infrastructure.agent.deepagents.harness import _map_tools
        from inkflow.infrastructure.agent.tools import Tool

        async def _boom(**kwargs) -> str:
            raise ValueError("tool boom")

        mapped = _map_tools(
            [Tool(spec=ToolSpec(name="boom_tool", description="", input_schema={}), func=_boom)]
        )
        with pytest.raises(ValueError, match="tool boom"):
            mapped[0].invoke({"text": "你好"})


class TestExcludedTools:
    """FS 工具排除契约（契约修正 2026-08-10：排除语义走 HarnessProfile.excluded_tools）。"""

    @pytest.fixture(autouse=True)
    def _clean_registry(self):
        """每个用例前清空模块级注册表（HARNESS_PROFILES 跨用例共享）。"""
        HARNESS_PROFILES.clear()
        yield

    def test_profile_excludes_read_file(self):
        """read_file 必须在默认排除集（Spike ③ 实测 read_file 为默认 FS 工具之一）。"""
        ensure_profile("glm-4.5")
        profile = HARNESS_PROFILES["openai:glm-4.5"]
        assert "read_file" in profile.excluded_tools

    def test_profile_excludes_all_fs_tools(self):
        """默认排除集 = deepagents 0.7.5 全量 FS 工具（FsToolName 8 项，Codex 源码确认）。"""
        assert (
            frozenset(
                {"ls", "read_file", "write_file", "edit_file", "delete", "glob", "grep", "execute"}
            )
            == DEFAULT_EXCLUDED_TOOLS
        )
        assert "search_characters" not in DEFAULT_EXCLUDED_TOOLS

    def test_profile_disables_subagent(self):
        """F26 禁用 subagent：默认 profile 关闭 general-purpose subagent（task 工具随之移除）。"""
        ensure_profile("glm-4.5")
        profile = HARNESS_PROFILES["openai:glm-4.5"]
        assert profile.general_purpose_subagent is not None
        assert profile.general_purpose_subagent.enabled is False
