"""F39 M3 白名单装配 RED 契约测试 — build_agentic_writer 工具/skill 白名单过滤.

spec §5.2 装配点改造 + §5 核心不变式（白名单确定性强制），M3 验收锚点。

被测对象（#258 F39 M3 已实现；本批为 #522 skill_ids 目录名语义变更锁定——
_append_skills 为字符串透传纯函数，目录名/DB id 对其不可区分，语义锁定依赖
mock 数据 + 内置 BUILTIN_SKILL_NAMES 英文 slug 守卫用例）:
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
           skill_ids: list[str] | None = None,  # skill 目录名列表；None=不拼 skill
           profile_key=None, expected_project_id=None, expected_chapter_id=None,
       )

   - tool_ids=None → writer 轨显式锁旧 5 只读 + save_draft（#956 §4）
   - tool_ids=[...] → build_reader_tools(include=tool_ids) 只返回白名单命中项；
     save_draft 仅当 "save_draft" in tool_ids 时追加
   - skill_ids=None → 不拼 skill，system_prompt 原样传给 build_deep_agent
   - skill_ids=[目录名...] → system_prompt = base + 每个命中 skill 追加
     '\n\n# 技能：<name>\n\n<content>\n\n---\n'（base 前 skill 后，顺序 =
     skill_ids 列表序；name = 目录名）

2. build_reader_tools 签名扩展:
       def build_reader_tools(deps, include: list[str] | None = None)
   - include=None → 8 只读全量（deps 无 world_service，§1.3 序去 world 2）
   - include=[names] → 只返回白名单命中项（按目录原序，非入参顺序）；
     未知名不命中（跳过）

3. _append_skills 模块级函数（F39 M3 已建；#522 语义变更）:
       def _append_skills(base_prompt, skill_ids, skill_lookup) -> str
   - skill_ids: list[str]——skill 目录名列表（不再是 DB 主键字符串化）
   - skill_lookup: Callable[[str], object|None]，按目录名取 Skill 鸭子对象
     （SimpleNamespace 含 name/content）；查不到该目录名 → 跳过（防御语义）
   - 每个命中 skill 追加 '\n\n# 技能：<name>\n\n<content>\n\n---\n'，
     顺序 = skill_ids 列表序；name = 目录名

注入缝（2026-08-16 已裁定并实现）: skill_lookup 经 AgenticWriterDeps 可选字段
skill_lookup 注入（dataclass 非 frozen，deps.skill_lookup = 查表函数）。
#522 变更: skill_lookup 按目录名查表（不再是 skill id），查不到 → 跳过（防御）。

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

RED 预期（当前旧实现: BUILTIN_SKILL_NAMES 仍为中文名，skill_ids 语义为 DB id）
----------------------------------------------------------------------------
- test_builtin_skill_names_english_slugs 断言失败（FAILED）——#522 语义锁定
  的确定性 RED 锚点
- _append_skills / build_agentic_writer 目录名用例在旧实现下 PASS（字符串
  透传对 id/目录名不可区分）——语义锁定用例，GREEN 阶段若实现偏离目录名语义
  （如把 skill_ids 当 DB id 解析后查表）即 FAIL
- 守护用例（tool_ids=None/skill_ids=None）PASS（刻意）
预期总结行: 1 failed, 其余 passed。
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

MODEL = "deepseek/deepseek-v4-flash"  # #415 G3 伪契约同步：mock 参数非语义断言
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

# #956 §1.3：deps 无 world_service（4 字段）时 include=None 全量 = §1.3 序去 world 2 的 8 名
READER_NAMES_NO_WORLD = [
    "search_characters",
    "get_character",
    "check_foreshadowing",
    "list_foreshadowing",
    "get_foreshadowing",
    "get_prior_summary",
    "audit_chapter",
    "count_words",
]

# #522: skill_ids = skill 目录名（英文 slug）；鸭子对象 name = 目录名
# （渲染进 prompt 的「# 技能：<name>」块头）
SKILL_ARCH = SimpleNamespace(name="architecture-methodology", content="架构方法论正文。")
SKILL_WRITE = SimpleNamespace(name="writing-methodology", content="写作方法论正文。")


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
    """构造 skill_lookup 查表函数：按 skill 目录名返回 Skill 鸭子对象或 None（#522）."""
    return lambda name: mapping.get(name)


def _get_append_skills():
    """用例体惰性取 _append_skills——RED 阶段该函数不存在 → ImportError（FAILED）."""
    from inkflow.infrastructure.agent.agentic_writer import _append_skills

    return _append_skills


# ── TestBuildReaderToolsInclude: build_reader_tools include 参数 ──


class TestBuildReaderToolsInclude:
    """build_reader_tools 白名单 include 参数契约（spec §5.2）."""

    def test_include_none_full_tools(self):
        """include 缺省（None）→ 8 只读全量（deps 无 world_service），§1.3 去 world 2 序."""
        tools = build_reader_tools(_make_reader_deps())
        assert len(tools) == 8
        assert [tool.spec.name for tool in tools] == READER_NAMES_NO_WORLD

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
        # #956 §4：writer 轨 tool_ids=None → 显式锁旧 5（include=_WRITER_READER_NAMES 兜底）
        assert _kwarg_or_positional(m_rt.call_args, "include", 1, None) == EXPECTED_READER_NAMES
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
        """skill_ids=[目录名] → system_prompt = base + skill 块（base 前 skill 后）;
        name = 目录名（#522）."""
        deps = _make_deps(skill_lookup=_skill_lookup({"architecture-methodology": SKILL_ARCH}))

        build_agentic_writer(
            model=MODEL,
            api_key=API_KEY,
            base_url=BASE_URL,
            deps=deps,
            system_prompt=BASE_PROMPT,
            skill_ids=["architecture-methodology"],
        )

        prompt = _kwarg_or_positional(m_da.call_args, "system_prompt", 4, None)
        assert prompt == (
            BASE_PROMPT + "\n\n# 技能：architecture-methodology\n\n架构方法论正文。\n\n---\n"
        )

    @patch("inkflow.infrastructure.agent.agentic_writer.build_deep_agent")
    def test_skill_ids_order_base_first_skills_after(self, m_da):
        """多 skill（目录名）按 skill_ids 列表序追加，base 恒在前（顺序固定）."""
        deps = _make_deps(
            skill_lookup=_skill_lookup(
                {
                    "writing-methodology": SKILL_WRITE,
                    "architecture-methodology": SKILL_ARCH,
                }
            )
        )

        build_agentic_writer(
            model=MODEL,
            api_key=API_KEY,
            base_url=BASE_URL,
            deps=deps,
            system_prompt=BASE_PROMPT,
            skill_ids=["writing-methodology", "architecture-methodology"],
        )

        prompt = _kwarg_or_positional(m_da.call_args, "system_prompt", 4, None)
        assert prompt == (
            BASE_PROMPT
            + "\n\n# 技能：writing-methodology\n\n写作方法论正文。\n\n---\n"
            + "\n\n# 技能：architecture-methodology\n\n架构方法论正文。\n\n---\n"
        )

    @patch("inkflow.infrastructure.agent.agentic_writer.build_deep_agent")
    def test_skill_ids_missing_lookup_skipped(self, m_da):
        """skill_lookup 查不到的目录名 → 跳过（防御语义，#522）."""
        deps = _make_deps(skill_lookup=_skill_lookup({"architecture-methodology": SKILL_ARCH}))

        build_agentic_writer(
            model=MODEL,
            api_key=API_KEY,
            base_url=BASE_URL,
            deps=deps,
            system_prompt=BASE_PROMPT,
            skill_ids=["architecture-methodology", "ghost-skill"],
        )

        prompt = _kwarg_or_positional(m_da.call_args, "system_prompt", 4, None)
        assert prompt == (
            BASE_PROMPT + "\n\n# 技能：architecture-methodology\n\n架构方法论正文。\n\n---\n"
        )

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
        """单 skill（目录名）→ base + '\n\n# 技能：<name>\n\n<content>\n\n---\n'
        （name = 目录名，#522）."""
        append = _get_append_skills()
        result = append(
            BASE_PROMPT,
            ["architecture-methodology"],
            _skill_lookup({"architecture-methodology": SKILL_ARCH}),
        )
        assert result == (
            BASE_PROMPT + "\n\n# 技能：architecture-methodology\n\n架构方法论正文。\n\n---\n"
        )

    def test_append_skills_multiple_ordered(self):
        """多 skill（目录名）按 skill_ids 列表序拼接，base 恒在前."""
        append = _get_append_skills()
        result = append(
            BASE_PROMPT,
            ["writing-methodology", "architecture-methodology"],
            _skill_lookup(
                {
                    "writing-methodology": SKILL_WRITE,
                    "architecture-methodology": SKILL_ARCH,
                }
            ),
        )
        assert result == (
            BASE_PROMPT
            + "\n\n# 技能：writing-methodology\n\n写作方法论正文。\n\n---\n"
            + "\n\n# 技能：architecture-methodology\n\n架构方法论正文。\n\n---\n"
        )

    def test_append_skills_missing_skipped(self):
        """查不到的目录名 → 跳过（防御语义，#522）."""
        append = _get_append_skills()
        result = append(
            BASE_PROMPT,
            ["architecture-methodology", "ghost-skill"],
            _skill_lookup({"architecture-methodology": SKILL_ARCH}),
        )
        assert result == (
            BASE_PROMPT + "\n\n# 技能：architecture-methodology\n\n架构方法论正文。\n\n---\n"
        )

    def test_append_skills_empty_noop(self):
        """skill_ids=[] → 原样返回 base（无追加）."""
        append = _get_append_skills()
        assert append(BASE_PROMPT, [], _skill_lookup({})) == BASE_PROMPT


class TestBuiltinSkillSlugsV522:
    """#522 内置 skill 英文 slug 契约（BUILTIN_SKILL_NAMES 同步改英文目录名）.

    装配层消费的 skill_ids 来自 Agent.skill_ids（目录名），内置 seed 的目录名由
    BUILTIN_SKILL_NAMES 定义——锁定该常量即锁定白名单装配的键空间。
    RED 形态: 旧实现 BUILTIN_SKILL_NAMES 仍为中文名 → 断言失败（确定性 RED）.
    """

    def test_builtin_skill_names_english_slugs(self) -> None:
        """BUILTIN_SKILL_NAMES = 6 英文 slug 目录名（顺序 = seed 插入序，spec §5.3）."""
        from inkflow.domain.services.skill_service import BUILTIN_SKILL_NAMES

        assert BUILTIN_SKILL_NAMES == [
            "architecture-methodology",
            "writing-methodology",
            "audit-methodology",
            "revision-methodology",
            "worldview-methodology",
            "polishing-methodology",
        ]
