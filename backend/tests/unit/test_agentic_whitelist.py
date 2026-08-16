"""F39 M3 白名单装配 RED 契约测试 — build_agentic_writer 工具/skill 白名单过滤.

spec §5.2 装配点改造 + §5 核心不变式（白名单确定性强制），M3 验收锚点。

被测对象（均已有 F26/F27 实现，本批为签名扩展/新增函数——混合 RED 形态，
非 1c 整模块收集期失败）:
    from inkflow.infrastructure.agent.agentic_writer import (
        AgenticWriterDeps, DeepAgentInvokeAdapter, build_agentic_writer,
    )
    from inkflow.infrastructure.agent.tools.reader_tools import (
        ReaderToolDeps, Tool, build_reader_tools,
    )

父侧定稿契约（spec §5.2，GREEN 按此实现）
----------------------------------------
1. build_agentic_writer 签名扩展（向后兼容）:

       def build_agentic_writer(
           *, model, api_key, base_url, deps, system_prompt,
           tool_ids: list[str] | None = None,   # 新增：None=全部
           skill_ids: list[str] | None = None,  # 新增：None=不拼 skill
           profile_key=None, expected_project_id=None, expected_chapter_id=None,
       )

   - tool_ids=None → 全量 5 只读 + save_draft（现 F27 行为）
   - tool_ids=[...] → build_reader_tools(include=tool_ids) 只返回白名单命中项；
     save_draft 仅当 "save_draft" in tool_ids 时追加
   - skill_ids=None → 不拼 skill，system_prompt 原样传给 build_deep_agent
   - skill_ids=[...] → system_prompt = base + 每个 skill 追加
     '\\n\\n# 技能：<name>\\n\\n<content>\\n\\n---\\n'（base 前 skill 后，顺序固定）

2. build_reader_tools 签名扩展:
       def build_reader_tools(deps, include: list[str] | None = None)
   - include=None → 5 只读全量（顺序不变: search_characters →
     check_foreshadowing → get_prior_summary → audit_chapter → count_words）
   - include=[names] → 只返回白名单命中项（按目录原序，非入参顺序）；
     未知名不命中（跳过）

3. _append_skills 模块级新增:
       def _append_skills(base_prompt, skill_ids, skill_lookup) -> str
   - skill_lookup: Callable[[str], Skill|None]，按 skill id 取 Skill
     （含 content/name）
   - 每个 skill 追加 '\\n\\n# 技能：<name>\\n\\n<content>\\n\\n---\\n'，
     顺序 = skill_ids 列表序
   - 查不到该 id → 跳过（父侧裁定防御语义——spec 未明说，见契约疑点）

契约疑点（交付报告同步，父侧裁定）
----------------------------------
1. skill_lookup 注入缝：父侧签名未列 skill_lookup 参数、spec 只写
   「skill_lookup 由装配层注入」——本测试按 AgenticWriterDeps 可选字段
   skill_lookup 注入（dataclass 非 frozen，deps.skill_lookup = 查表函数）；
   GREEN 若走其他缝（如 build_agentic_writer 新增参数）需父侧裁定适配测试。
2. skill 查不到 id 的行为：spec 未明说，父侧契约裁定「跳过（防御）」；
   用例按跳过锁定，GREEN 若改为报错需父侧再裁定。

patch 注入点（实测验证 2026-08-16）
-----------------------------------
agentic_writer.py 内 build_deep_agent / build_reader_tools / build_save_draft_tool
均为模块级 from-import 绑定名——patch 目标取【调用方模块属性】:
    inkflow.infrastructure.agent.agentic_writer.build_deep_agent
    inkflow.infrastructure.agent.agentic_writer.build_reader_tools
    inkflow.infrastructure.agent.agentic_writer.build_save_draft_tool
（patch 源头模块 reader_tools.build_reader_tools 对 build_agentic_writer 内部
调用零影响——绑定名快照，实测验证；build_reader_tools 直接测试走真实实现。
本文件全部用例为同步函数（被测函数均同步），无需 asyncio mark。）

RED 预期（当前实现: build_agentic_writer 无 tool_ids/skill_ids 参数、
build_reader_tools 无 include 参数、_append_skills 不存在）
----------------------------------------------------------
- 守护用例 PASS（刻意）: tool_ids=None/skill_ids=None 走现签名调用 = F27 行为；
  build_reader_tools 缺省 include = 全量 5 只读
- 目标用例 FAILED: 传 tool_ids/skill_ids/include → TypeError（unexpected
  keyword argument，用例体直接调用故 FAILED 非 ERROR）；_append_skills 用例体
  惰性 import → ImportError（FAILED 非收集 ERROR——禁顶部 import，规则 1c
  混合轨形态）
- 无 ERROR（全部 patch 目标当前实现可解析；无收集期错误）
预期总结行: 2 passed, 16 failed（TypeError 12 + ImportError 4）。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.infrastructure.agent.agentic_writer import (
    AgenticWriterDeps,
    DeepAgentInvokeAdapter,
    build_agentic_writer,
)
from inkflow.infrastructure.agent.tools.reader_tools import (
    ReaderToolDeps,
    Tool,
    build_reader_tools,
)

# ── 常量 ──────────────────────────────────────

MODEL = "zhipu/glm-4.5"
API_KEY = "test-key"
BASE_URL = "https://example.test/v1"
BASE_PROMPT = "你是章节写手，负责按大纲撰写正文。"

EXPECTED_READER_NAMES = [
    "search_characters",
    "check_foreshadowing",
    "get_prior_summary",
    "audit_chapter",
    "count_words",
]

SKILL_ARCH = SimpleNamespace(name="架构方法论", content="架构方法论正文。")
SKILL_WRITE = SimpleNamespace(name="写作方法论", content="写作方法论正文。")


# ── 辅助 ──────────────────────────────────────


def _kwarg_or_positional(call, name: str, index: int, default=None):
    """宽松取 mock 调用参数：优先关键字，回退位置参数（兼容两种 GREEN 形态）."""
    args, kwargs = call
    if name in kwargs:
        return kwargs[name]
    return args[index] if len(args) > index else default


def _fake_tool(name: str) -> Tool:
    """构造最小真实 Tool（spec.name 可断言，func 不执行）."""
    return Tool(
        spec=ToolSpec(name=name, description="", input_schema={}),
        func=MagicMock(),
    )


def _make_deps(**overrides) -> AgenticWriterDeps:
    """构造 AgenticWriterDeps（6 个 AsyncMock service，可按名覆盖）."""
    deps = AgenticWriterDeps(
        character_service=AsyncMock(),
        foreshadowing_service=AsyncMock(),
        summary_service=AsyncMock(),
        chapter_audit_service=AsyncMock(),
        draft_service=AsyncMock(),
        audit_service=AsyncMock(),
    )
    for key, value in overrides.items():
        setattr(deps, key, value)
    return deps


def _make_reader_deps(**overrides) -> ReaderToolDeps:
    """构造 ReaderToolDeps（4 个 AsyncMock service，可按名覆盖）."""
    deps = ReaderToolDeps(
        character_service=AsyncMock(),
        foreshadowing_service=AsyncMock(),
        summary_service=AsyncMock(),
        chapter_audit_service=AsyncMock(),
    )
    for key, value in overrides.items():
        setattr(deps, key, value)
    return deps


def _skill_lookup(mapping: dict):
    """构造 skill_lookup 查表函数：按 skill id 返回 Skill 鸭子对象或 None."""
    return lambda sid: mapping.get(sid)


def _get_append_skills():
    """用例体惰性取 _append_skills——RED 阶段该函数不存在 → ImportError（FAILED）."""
    from inkflow.infrastructure.agent.agentic_writer import _append_skills

    return _append_skills


# ── TestBuildReaderToolsInclude: build_reader_tools include 参数 ──


class TestBuildReaderToolsInclude:
    """build_reader_tools 白名单 include 参数契约（spec §5.2）."""

    def test_include_none_full_tools(self):
        """include 缺省（None）→ 5 只读全量，目录原序（向后兼容守护）."""
        tools = build_reader_tools(_make_reader_deps())
        assert len(tools) == 5
        assert [tool.spec.name for tool in tools] == EXPECTED_READER_NAMES

    def test_include_subset_filters_by_catalog_order(self):
        """include 白名单子集 → 只返回命中项，按目录原序（非入参顺序）."""
        tools = build_reader_tools(
            _make_reader_deps(), include=["count_words", "search_characters"]
        )
        assert [tool.spec.name for tool in tools] == [
            "search_characters",
            "count_words",
        ]

    def test_include_all_names_full_order(self):
        """include 全 5 名 → 全量返回，目录原序不变."""
        tools = build_reader_tools(_make_reader_deps(), include=list(EXPECTED_READER_NAMES))
        assert [tool.spec.name for tool in tools] == EXPECTED_READER_NAMES

    def test_include_empty_list_returns_none(self):
        """include=[] → 无命中项，返回空列表."""
        tools = build_reader_tools(_make_reader_deps(), include=[])
        assert tools == []

    def test_include_unknown_name_skipped(self):
        """include 含目录外工具名 → 不命中（跳过），返回空列表."""
        tools = build_reader_tools(_make_reader_deps(), include=["no_such_tool"])
        assert tools == []


# ── TestBuildAgenticWriterToolWhitelist: tool_ids 白名单 ──


class TestBuildAgenticWriterToolWhitelist:
    """build_agentic_writer tool_ids 白名单过滤契约（spec §5.2）.

    patch 注入点 = agentic_writer 模块属性（from-import 绑定名快照，
    实测验证；patch 源头模块对内部调用零影响）。
    """

    @patch("inkflow.infrastructure.agent.agentic_writer.build_deep_agent")
    @patch("inkflow.infrastructure.agent.agentic_writer.build_save_draft_tool")
    @patch("inkflow.infrastructure.agent.agentic_writer.build_reader_tools")
    def test_tool_ids_none_full_tools_and_prompt_unchanged(self, m_rt, m_sd, m_da):
        """tool_ids=None/skill_ids=None → 现 F27 行为：全量 5 只读 + save_draft，
        system_prompt 原样透传（向后兼容守护，RED 阶段即 PASS）."""
        m_rt.return_value = [_fake_tool(name) for name in EXPECTED_READER_NAMES]
        m_sd.return_value = _fake_tool("save_draft")

        agent = build_agentic_writer(
            model=MODEL,
            api_key=API_KEY,
            base_url=BASE_URL,
            deps=_make_deps(),
            system_prompt=BASE_PROMPT,
        )

        assert m_rt.call_count == 1
        # tool_ids=None → include 语义 None（现实现不传 include，helper 回退默认）
        assert _kwarg_or_positional(m_rt.call_args, "include", 1, None) is None
        assert m_sd.call_count == 1
        assert m_da.call_count == 1
        tools = _kwarg_or_positional(m_da.call_args, "tools", 3, None)
        assert [tool.spec.name for tool in tools] == [*EXPECTED_READER_NAMES, "save_draft"]
        prompt = _kwarg_or_positional(m_da.call_args, "system_prompt", 4, None)
        assert prompt == BASE_PROMPT
        assert isinstance(agent, DeepAgentInvokeAdapter)

    @patch("inkflow.infrastructure.agent.agentic_writer.build_deep_agent")
    @patch("inkflow.infrastructure.agent.agentic_writer.build_save_draft_tool")
    @patch("inkflow.infrastructure.agent.agentic_writer.build_reader_tools")
    def test_tool_ids_passed_to_build_reader_tools(self, m_rt, m_sd, m_da):
        """tool_ids=[...] → build_reader_tools 收到 include=tool_ids（白名单透传）."""
        m_rt.return_value = [_fake_tool("count_words")]
        m_sd.return_value = _fake_tool("save_draft")

        build_agentic_writer(
            model=MODEL,
            api_key=API_KEY,
            base_url=BASE_URL,
            deps=_make_deps(),
            system_prompt=BASE_PROMPT,
            tool_ids=["count_words"],
        )

        assert _kwarg_or_positional(m_rt.call_args, "include", 1, None) == ["count_words"]
        m_sd.assert_not_called()
        tools = _kwarg_or_positional(m_da.call_args, "tools", 3, None)
        assert [tool.spec.name for tool in tools] == ["count_words"]

    @patch("inkflow.infrastructure.agent.agentic_writer.build_deep_agent")
    @patch("inkflow.infrastructure.agent.agentic_writer.build_save_draft_tool")
    @patch("inkflow.infrastructure.agent.agentic_writer.build_reader_tools")
    def test_tool_ids_with_save_draft_appends_save_draft(self, m_rt, m_sd, m_da):
        """白名单含 save_draft → 追加 save_draft 工具."""
        m_rt.return_value = [_fake_tool("count_words")]
        m_sd.return_value = _fake_tool("save_draft")

        build_agentic_writer(
            model=MODEL,
            api_key=API_KEY,
            base_url=BASE_URL,
            deps=_make_deps(),
            system_prompt=BASE_PROMPT,
            tool_ids=["count_words", "save_draft"],
        )

        m_sd.assert_called_once()
        tools = _kwarg_or_positional(m_da.call_args, "tools", 3, None)
        assert [tool.spec.name for tool in tools] == ["count_words", "save_draft"]

    @patch("inkflow.infrastructure.agent.agentic_writer.build_deep_agent")
    @patch("inkflow.infrastructure.agent.agentic_writer.build_save_draft_tool")
    @patch("inkflow.infrastructure.agent.agentic_writer.build_reader_tools")
    def test_tool_ids_without_save_draft_omits_save_draft(self, m_rt, m_sd, m_da):
        """白名单不含 save_draft → 不追加 save_draft（只读工具集）."""
        m_rt.return_value = [_fake_tool("count_words")]

        build_agentic_writer(
            model=MODEL,
            api_key=API_KEY,
            base_url=BASE_URL,
            deps=_make_deps(),
            system_prompt=BASE_PROMPT,
            tool_ids=["count_words"],
        )

        m_sd.assert_not_called()
        tools = _kwarg_or_positional(m_da.call_args, "tools", 3, None)
        assert [tool.spec.name for tool in tools] == ["count_words"]

    @patch("inkflow.infrastructure.agent.agentic_writer.build_deep_agent")
    @patch("inkflow.infrastructure.agent.agentic_writer.build_save_draft_tool")
    @patch("inkflow.infrastructure.agent.agentic_writer.build_reader_tools")
    def test_tool_ids_empty_no_tools(self, m_rt, m_sd, m_da):
        """tool_ids=[] → 无任何工具（readers 空 + 不追加 save_draft）."""
        m_rt.return_value = []

        build_agentic_writer(
            model=MODEL,
            api_key=API_KEY,
            base_url=BASE_URL,
            deps=_make_deps(),
            system_prompt=BASE_PROMPT,
            tool_ids=[],
        )

        assert _kwarg_or_positional(m_rt.call_args, "include", 1, None) == []
        m_sd.assert_not_called()
        tools = _kwarg_or_positional(m_da.call_args, "tools", 3, None)
        assert tools == []


# ── TestBuildAgenticWriterSkillWhitelist: skill_ids 白名单 ──


class TestBuildAgenticWriterSkillWhitelist:
    """build_agentic_writer skill_ids 白名单过滤契约（spec §5.2）.

    skill_lookup 按契约疑点 1 经 deps.skill_lookup 注入（装配层注入缝）。
    """

    @patch("inkflow.infrastructure.agent.agentic_writer.build_deep_agent")
    def test_skill_ids_appends_skill_content(self, m_da):
        """skill_ids=[...] → system_prompt = base + skill 块（base 前 skill 后）."""
        deps = _make_deps(skill_lookup=_skill_lookup({"1": SKILL_ARCH}))

        build_agentic_writer(
            model=MODEL,
            api_key=API_KEY,
            base_url=BASE_URL,
            deps=deps,
            system_prompt=BASE_PROMPT,
            skill_ids=["1"],
        )

        prompt = _kwarg_or_positional(m_da.call_args, "system_prompt", 4, None)
        assert prompt == BASE_PROMPT + "\n\n# 技能：架构方法论\n\n架构方法论正文。\n\n---\n"

    @patch("inkflow.infrastructure.agent.agentic_writer.build_deep_agent")
    def test_skill_ids_order_base_first_skills_after(self, m_da):
        """多 skill 按 skill_ids 列表序追加，base 恒在前（顺序固定）."""
        deps = _make_deps(skill_lookup=_skill_lookup({"3": SKILL_WRITE, "1": SKILL_ARCH}))

        build_agentic_writer(
            model=MODEL,
            api_key=API_KEY,
            base_url=BASE_URL,
            deps=deps,
            system_prompt=BASE_PROMPT,
            skill_ids=["3", "1"],
        )

        prompt = _kwarg_or_positional(m_da.call_args, "system_prompt", 4, None)
        assert prompt == (
            BASE_PROMPT
            + "\n\n# 技能：写作方法论\n\n写作方法论正文。\n\n---\n"
            + "\n\n# 技能：架构方法论\n\n架构方法论正文。\n\n---\n"
        )

    @patch("inkflow.infrastructure.agent.agentic_writer.build_deep_agent")
    def test_skill_ids_missing_lookup_skipped(self, m_da):
        """skill_lookup 查不到的 id → 跳过（防御语义，契约疑点 2）."""
        deps = _make_deps(skill_lookup=_skill_lookup({"1": SKILL_ARCH}))

        build_agentic_writer(
            model=MODEL,
            api_key=API_KEY,
            base_url=BASE_URL,
            deps=deps,
            system_prompt=BASE_PROMPT,
            skill_ids=["1", "999"],
        )

        prompt = _kwarg_or_positional(m_da.call_args, "system_prompt", 4, None)
        assert prompt == BASE_PROMPT + "\n\n# 技能：架构方法论\n\n架构方法论正文。\n\n---\n"

    @patch("inkflow.infrastructure.agent.agentic_writer.build_deep_agent")
    def test_skill_ids_empty_no_append(self, m_da):
        """skill_ids=[] → 不拼任何 skill，prompt 原样透传."""
        deps = _make_deps(skill_lookup=_skill_lookup({}))

        build_agentic_writer(
            model=MODEL,
            api_key=API_KEY,
            base_url=BASE_URL,
            deps=deps,
            system_prompt=BASE_PROMPT,
            skill_ids=[],
        )

        prompt = _kwarg_or_positional(m_da.call_args, "system_prompt", 4, None)
        assert prompt == BASE_PROMPT


# ── TestAppendSkills: _append_skills 纯函数契约 ──


class TestAppendSkills:
    """_append_skills 模块级函数契约（spec §5.2 skill 拼接格式）.

    函数不存在（RED）→ 用例体惰性 import → ImportError（FAILED 非收集 ERROR）。
    """

    def test_append_skills_formats_block(self):
        """单 skill → base + '\\n\\n# 技能：<name>\\n\\n<content>\\n\\n---\\n'."""
        append = _get_append_skills()
        result = append(BASE_PROMPT, ["1"], _skill_lookup({"1": SKILL_ARCH}))
        assert result == BASE_PROMPT + "\n\n# 技能：架构方法论\n\n架构方法论正文。\n\n---\n"

    def test_append_skills_multiple_ordered(self):
        """多 skill 按 skill_ids 列表序拼接，base 恒在前."""
        append = _get_append_skills()
        result = append(
            BASE_PROMPT,
            ["3", "1"],
            _skill_lookup({"3": SKILL_WRITE, "1": SKILL_ARCH}),
        )
        assert result == (
            BASE_PROMPT
            + "\n\n# 技能：写作方法论\n\n写作方法论正文。\n\n---\n"
            + "\n\n# 技能：架构方法论\n\n架构方法论正文。\n\n---\n"
        )

    def test_append_skills_missing_skipped(self):
        """查不到的 id → 跳过（防御语义，契约疑点 2）."""
        append = _get_append_skills()
        result = append(BASE_PROMPT, ["1", "999"], _skill_lookup({"1": SKILL_ARCH}))
        assert result == BASE_PROMPT + "\n\n# 技能：架构方法论\n\n架构方法论正文。\n\n---\n"

    def test_append_skills_empty_noop(self):
        """skill_ids=[] → 原样返回 base（无追加）."""
        append = _get_append_skills()
        assert append(BASE_PROMPT, [], _skill_lookup({})) == BASE_PROMPT
