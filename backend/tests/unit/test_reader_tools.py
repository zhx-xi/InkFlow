"""F26 M2 工具层 RED 契约测试 — 5 只读 Agent 工具（search_characters / check_foreshadowing /
get_prior_summary / audit_chapter / count_words），全 mock 轨（service 实例注入 + AsyncMock）.

被测模块（全部未实现，1c 整模块 RED 形态；全部顶部 import，不需要惰性导入——全文件
收集期失败是预期，GREEN 落地后整文件自动收集）:
    from inkflow.domain.models.agent_tools import ToolSpec
    from inkflow.infrastructure.agent.tools import TOOL_REGISTRY, build_reader_tools
    from inkflow.infrastructure.agent.tools.reader_tools import ReaderToolDeps, Tool

设计假设（父侧定稿契约，GREEN 按此实现）
----------------------------------------
1. ToolSpec（domain/models/agent_tools.py 新建）:

       @dataclass
       class ToolSpec:
           '''工具定义 — 领域层工具契约，不泄漏 LangChain/deepagents 类型.'''
           name: str                    # 工具名（snake_case）
           description: str             # 工具用途描述
           input_schema: dict           # JSON Schema（Pydantic model_json_schema() 产物）

2. Tool / ReaderToolDeps / build_reader_tools（infrastructure/agent/tools/reader_tools.py 新建）:

       @dataclass
       class Tool:
           '''可执行工具 — spec 定义 + 实现函数.'''
           spec: ToolSpec
           func: Callable[..., Awaitable[str]]   # 异步执行，返回文本结果

       @dataclass
       class ReaderToolDeps:
           '''工具工厂依赖 — service 实例注入（鸭子类型）.'''
           character_service: object       # 有 list_characters(project_id, search=None,
                                           #   group_id=None, sort_by='updated_at',
                                           #   sort_desc=True, offset=0, limit=50)
           foreshadowing_service: object   # 有 list(project_id, search=None, status=None,
                                           #   sort_by='priority', sort_desc=True,
                                           #   offset=0, limit=50)
           summary_service: object         # 有 list_recent(project_id, limit=10)
           chapter_audit_service: object   # 有 audit(project_id, chapter_id, *,
                                           #   include_static=True)

       def build_reader_tools(deps: ReaderToolDeps) -> list[Tool]: ...

3. 工具函数签名（父侧定稿，测试通过 Tool.func 调用；内部函数名可不同，对外 spec.name 固定）:

       async def _search_characters(
           project_id: uuid.UUID, search: str | None = None,
           group_id: uuid.UUID | None = None,
       ) -> str
       async def _check_foreshadowing(project_id: uuid.UUID, status: str | None = None) -> str
       async def _get_prior_summary(project_id: uuid.UUID, limit: int = 10) -> str
       async def _audit_chapter(
           project_id: uuid.UUID, chapter_id: uuid.UUID,
           include_static: bool = True,
       ) -> str
       async def _count_words(text: str) -> str

4. TOOL_REGISTRY（infrastructure/agent/tools/__init__.py 新建）:
       - 模块级静态 TOOL_REGISTRY: list[ToolSpec]（5 项，name/description 与
         build_reader_tools 一致）
       - __init__.py 导出: ToolSpec, Tool, ReaderToolDeps, build_reader_tools, TOOL_REGISTRY

5. 输出信封（json.dumps(..., ensure_ascii=False)）:
       - 成功: {"ok": True, "data": <服务结果序列化>}
       - 失败: {"ok": False, "error": "<异常消息>"}（工具内部捕获一切 Exception，不抛出）

6. 分页语义（仅 search_characters / check_foreshadowing）:
       - 必须分页循环取全: limit=50，offset 递增（0, 50, 100, ...），
         直到单次返回 < 50 条或空列表
       - 其余工具（get_prior_summary / audit_chapter / count_words）单次调用

7. count_words 工具: 不依赖 service，直接包装 domain/services/_word_count.py 顶层纯函数
   count_words(content: str) -> int（已实现；本文件直测真实函数，import 形态与
   writing_service.py 既有用法一致）

契约疑点（交付报告同步，GREEN 需兼顾）: 真实 CharacterService.list_characters /
ForeshadowingService.list 返回 tuple[list, int]（当前页, 总数）——本契约分页语义按
裸列表（"返回 < 50 条或空"）mock。GREEN 包装层需同时兼容两种返回形态
（如 items = result[0] if isinstance(result, tuple) else result）。

RED 预期
--------
全文件收集期失败（1c 整模块 RED 形态: pytest exit 2 / collected 0 items / 1 error）:
    ModuleNotFoundError: No module named 'inkflow.domain.models.agent_tools'
字母序原因: isort 强制首方组字母序，inkflow.domain.models.agent_tools 先于
inkflow.infrastructure.agent.tools 执行——收集错误报字母序首个缺失模块
（F34 实测规则）。不需要惰性导入：全部顶部 import，全文件收集失败是预期。

asyncio 模式: 本 venv（pytest-asyncio 1.4.0）实测头部 asyncio: mode=Mode.AUTO
（pyproject asyncio_mode = "auto" 生效）；文件级 pytestmark = pytest.mark.asyncio
双保险（STRICT/AUTO 两种模式均成立），全部用例 async def。
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.agent_tools import ToolSpec
from inkflow.domain.services._word_count import count_words
from inkflow.infrastructure.agent.tools import TOOL_REGISTRY, build_reader_tools
from inkflow.infrastructure.agent.tools.reader_tools import ReaderToolDeps, Tool

pytestmark = pytest.mark.asyncio  # 实测 mode=Mode.AUTO；显式 mark 兼容 STRICT/AUTO

# ── 常量 ──────────────────────────────────────

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
CHAPTER_ID = uuid.UUID("87654321-4321-8765-4321-876543218765")
GROUP_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
EXPECTED_TOOL_NAMES = [
    "search_characters",
    "check_foreshadowing",
    "get_prior_summary",
    "audit_chapter",
    "count_words",
]

# ── 辅助 ──────────────────────────────────────


def _make_deps(**overrides) -> ReaderToolDeps:
    """构造 ReaderToolDeps（默认四个 AsyncMock service，可按名覆盖）."""
    deps = ReaderToolDeps(
        character_service=AsyncMock(),
        foreshadowing_service=AsyncMock(),
        summary_service=AsyncMock(),
        chapter_audit_service=AsyncMock(),
    )
    for key, value in overrides.items():
        setattr(deps, key, value)
    return deps


def _tool(deps: ReaderToolDeps, name: str) -> Tool:
    """按 spec.name 从 build_reader_tools 结果取 Tool（未注册则报错）."""
    for tool in build_reader_tools(deps):
        if tool.spec.name == name:
            return tool
    raise AssertionError(f"工具未注册: {name}")


def _kwarg_or_positional(call, name: str, index: int, default=None):
    """宽松取 mock 调用参数：优先关键字，回退位置参数（兼容两种 GREEN 形态）."""
    args, kwargs = call
    if name in kwargs:
        return kwargs[name]
    return args[index] if len(args) > index else default


# ── TestToolSpec ──────────────────────────────────


class TestToolSpec:
    """ToolSpec 领域契约（domain/models/agent_tools.py）."""

    async def test_construct_and_read_fields(self):
        """构造实例后 name/description/input_schema 可回读."""
        schema = {"type": "object", "properties": {"search": {"type": "string"}}}
        spec = ToolSpec(name="search_characters", description="搜索角色", input_schema=schema)
        assert spec.name == "search_characters"
        assert spec.description == "搜索角色"
        assert spec.input_schema == schema

    async def test_input_schema_accepts_dict(self):
        """input_schema 接受任意 dict 且 roundtrip 相等."""
        spec = ToolSpec(name="count_words", description="统计字数", input_schema={})
        assert isinstance(spec.input_schema, dict)
        assert spec.input_schema == {}


# ── TestToolRegistry ────────────────────────────────


class TestToolRegistry:
    """TOOL_REGISTRY 静态注册表契约（infrastructure/agent/tools/__init__.py）."""

    async def test_registry_has_five_specs(self):
        """注册表长度 5."""
        assert len(TOOL_REGISTRY) == 5

    async def test_registry_names_set(self):
        """注册表工具名集合与契约一致."""
        assert {spec.name for spec in TOOL_REGISTRY} == set(EXPECTED_TOOL_NAMES)

    async def test_registry_spec_fields(self):
        """每项 name/description 非空 str，input_schema 为 dict."""
        for spec in TOOL_REGISTRY:
            assert isinstance(spec.name, str) and spec.name
            assert isinstance(spec.description, str) and spec.description
            assert isinstance(spec.input_schema, dict)


# ── TestSearchCharacters ──────────────────────────────


class TestSearchCharacters:
    """search_characters 工具（分页循环取全 + search/group_id 透传）."""

    async def test_pagination_fetches_all_pages(self):
        """50 条 + 空两页取全：两次调用 offset=0/50，data 含角色名."""
        svc = AsyncMock()
        page1 = [{"id": i, "name": f"角色{i}", "group_id": None} for i in range(50)]
        svc.list_characters.side_effect = [page1, []]
        tool = _tool(_make_deps(character_service=svc), "search_characters")
        payload = json.loads(await tool.func(PROJECT_ID))
        assert payload["ok"] is True
        assert len(payload["data"]) == 50
        assert payload["data"][0]["name"] == "角色0"
        assert payload["data"][-1]["name"] == "角色49"
        assert svc.list_characters.await_count == 2
        offsets = [
            _kwarg_or_positional(call, "offset", 5, 0)
            for call in svc.list_characters.call_args_list
        ]
        assert offsets == [0, 50]

    async def test_search_and_group_id_passthrough(self):
        """search/group_id 透传：service 收到相同值."""
        svc = AsyncMock()
        svc.list_characters.return_value = [{"name": "林晚", "group_id": str(GROUP_ID)}]
        tool = _tool(_make_deps(character_service=svc), "search_characters")
        payload = json.loads(await tool.func(PROJECT_ID, search="林晚", group_id=GROUP_ID))
        assert payload["ok"] is True
        assert payload["data"][0]["name"] == "林晚"
        call = svc.list_characters.await_args
        assert _kwarg_or_positional(call, "search", 1) == "林晚"
        assert _kwarg_or_positional(call, "group_id", 2) == GROUP_ID

    async def test_error_envelope(self):
        """list_characters 抛 RuntimeError → ok:false + error 含消息."""
        svc = AsyncMock()
        svc.list_characters.side_effect = RuntimeError("db down")
        tool = _tool(_make_deps(character_service=svc), "search_characters")
        payload = json.loads(await tool.func(PROJECT_ID))
        assert payload["ok"] is False
        assert "db down" in payload["error"]

    async def test_pydantic_model_serialization(self):
        """真实形态：service 返回 pydantic 模型 → data 序列化为 JSON dict（model_dump 分支）."""
        from datetime import UTC, datetime

        from inkflow.domain.models.character import Character

        now = datetime.now(UTC)
        svc = AsyncMock()
        svc.list_characters.return_value = [
            Character(
                id=PROJECT_ID,
                project_id=PROJECT_ID,
                name="林晚",
                personality="冷静",
                created_at=now,
                updated_at=now,
            ),
        ]
        tool = _tool(_make_deps(character_service=svc), "search_characters")
        payload = json.loads(await tool.func(PROJECT_ID))
        assert payload["ok"] is True
        assert payload["data"][0]["name"] == "林晚"
        assert payload["data"][0]["personality"] == "冷静"
        assert payload["data"][0]["id"] == str(PROJECT_ID)


# ── TestCheckForeshadowing ─────────────────────────────


class TestCheckForeshadowing:
    """check_foreshadowing 工具（分页循环取全 + status 透传）."""

    async def test_pagination_fetches_all_pages(self):
        """50 条 + 空两页取全：两次调用 offset=0/50，data 含伏笔内容/状态."""
        svc = AsyncMock()
        page1 = [{"title": f"伏笔{i}", "status": "active", "content": "内容A"} for i in range(50)]
        svc.list.side_effect = [page1, []]
        tool = _tool(_make_deps(foreshadowing_service=svc), "check_foreshadowing")
        payload = json.loads(await tool.func(PROJECT_ID))
        assert payload["ok"] is True
        assert len(payload["data"]) == 50
        assert payload["data"][0]["status"] == "active"
        assert svc.list.await_count == 2
        offsets = [_kwarg_or_positional(call, "offset", 5, 0) for call in svc.list.call_args_list]
        assert offsets == [0, 50]

    async def test_status_passthrough(self):
        """status 透传：service 收到相同值."""
        svc = AsyncMock()
        svc.list.return_value = [{"title": "伏笔A", "status": "active"}]
        tool = _tool(_make_deps(foreshadowing_service=svc), "check_foreshadowing")
        payload = json.loads(await tool.func(PROJECT_ID, status="active"))
        assert payload["ok"] is True
        assert _kwarg_or_positional(svc.list.await_args, "status", 2) == "active"

    async def test_error_envelope(self):
        """list 抛 RuntimeError → ok:false + error 含消息."""
        svc = AsyncMock()
        svc.list.side_effect = RuntimeError("foreshadowing db down")
        tool = _tool(_make_deps(foreshadowing_service=svc), "check_foreshadowing")
        payload = json.loads(await tool.func(PROJECT_ID))
        assert payload["ok"] is False
        assert "foreshadowing db down" in payload["error"]


# ── TestGetPriorSummary ──────────────────────────────


class TestGetPriorSummary:
    """get_prior_summary 工具（单次调用 + limit 透传，默认 10）."""

    async def test_positive_default_limit_ten(self):
        """默认 limit=10：data 含摘要，service 收到 limit=10."""
        svc = AsyncMock()
        svc.list_recent.return_value = [{"title": "第三章摘要", "summary": "故事梗概"}]
        tool = _tool(_make_deps(summary_service=svc), "get_prior_summary")
        payload = json.loads(await tool.func(PROJECT_ID))
        assert payload["ok"] is True
        assert payload["data"][0]["title"] == "第三章摘要"
        assert _kwarg_or_positional(svc.list_recent.await_args, "limit", 1, None) == 10

    async def test_limit_passthrough(self):
        """显式 limit=5 透传：service 收到 5."""
        svc = AsyncMock()
        svc.list_recent.return_value = []
        tool = _tool(_make_deps(summary_service=svc), "get_prior_summary")
        await tool.func(PROJECT_ID, limit=5)
        assert _kwarg_or_positional(svc.list_recent.await_args, "limit", 1, None) == 5

    async def test_error_envelope(self):
        """list_recent 抛 RuntimeError → ok:false + error 含消息."""
        svc = AsyncMock()
        svc.list_recent.side_effect = RuntimeError("summary boom")
        tool = _tool(_make_deps(summary_service=svc), "get_prior_summary")
        payload = json.loads(await tool.func(PROJECT_ID))
        assert payload["ok"] is False
        assert "summary boom" in payload["error"]


# ── TestAuditChapter ────────────────────────────────


class TestAuditChapter:
    """audit_chapter 工具（单次调用 + include_static 透传，默认 True）."""

    async def test_positive_default_include_static(self):
        """默认 include_static=True：data 含 findings."""
        svc = AsyncMock()
        svc.audit.return_value = {"findings": [{"type": "word_count", "message": "字数不足"}]}
        tool = _tool(_make_deps(chapter_audit_service=svc), "audit_chapter")
        payload = json.loads(await tool.func(PROJECT_ID, CHAPTER_ID))
        assert payload["ok"] is True
        assert len(payload["data"]["findings"]) == 1
        assert _kwarg_or_positional(svc.audit.await_args, "include_static", 2, True) is True

    async def test_include_static_false_passthrough(self):
        """显式 include_static=False 透传：service 收到 False."""
        svc = AsyncMock()
        svc.audit.return_value = {"findings": []}
        tool = _tool(_make_deps(chapter_audit_service=svc), "audit_chapter")
        await tool.func(PROJECT_ID, CHAPTER_ID, include_static=False)
        assert _kwarg_or_positional(svc.audit.await_args, "include_static", 2, True) is False

    async def test_error_envelope(self):
        """audit 抛 RuntimeError → ok:false + error 含消息."""
        svc = AsyncMock()
        svc.audit.side_effect = RuntimeError("audit failed")
        tool = _tool(_make_deps(chapter_audit_service=svc), "audit_chapter")
        payload = json.loads(await tool.func(PROJECT_ID, CHAPTER_ID))
        assert payload["ok"] is False
        assert "audit failed" in payload["error"]


# ── TestCountWords ─────────────────────────────────


class TestCountWords:
    """count_words 纯函数直测（真实 domain/services/_word_count.py）."""

    async def test_mixed_cjk_and_english(self):
        """中文 10 字 + 英文 2 词 → 12."""
        assert count_words("晨光穿过窗棂洒在桌面 hello world") == 12

    async def test_empty_string(self):
        """空串 → 0."""
        assert count_words("") == 0

    async def test_markdown_syntax_not_counted(self):
        """Markdown 标题语法不计入（"# 标题" → 标题 2 字 + 正文 2 字 = 4）."""
        assert count_words("# 标题\n\n正文") == 4

    async def test_numbers_and_punctuation_not_counted(self):
        """数字与标点不计入（"第1章！" → 第/章 2 字）."""
        assert count_words("第1章！") == 2


# ── TestToolEnvelope ────────────────────────────────


class TestToolEnvelope:
    """输出信封契约（成功 ok:true + data / 失败 ok:false + error）."""

    async def test_success_envelope(self):
        """count_words 成功路径：ok=True 且 data 为字数."""
        tool = _tool(_make_deps(), "count_words")
        payload = json.loads(await tool.func("你好 world"))
        assert payload["ok"] is True
        assert payload["data"] == 3

    async def test_failure_envelope(self):
        """get_prior_summary 失败路径：ok=False 且 error 键存在."""
        svc = AsyncMock()
        svc.list_recent.side_effect = RuntimeError("boom")
        tool = _tool(_make_deps(summary_service=svc), "get_prior_summary")
        payload = json.loads(await tool.func(PROJECT_ID))
        assert payload["ok"] is False
        assert "error" in payload
        assert payload["error"] == "boom"


# ── TestBuildReaderTools ──────────────────────────────


class TestBuildReaderTools:
    """build_reader_tools 工厂契约（5 个 Tool，顺序固定）."""

    async def test_returns_five_tools(self):
        """返回 5 个 Tool."""
        tools = build_reader_tools(_make_deps())
        assert len(tools) == 5

    async def test_tool_order_fixed(self):
        """Tool 顺序固定：search_characters → count_words."""
        tools = build_reader_tools(_make_deps())
        assert [tool.spec.name for tool in tools] == EXPECTED_TOOL_NAMES

    async def test_tool_spec_and_func_callable(self):
        """每个 Tool 携带 ToolSpec 且 func 可调用."""
        for tool in build_reader_tools(_make_deps()):
            assert isinstance(tool.spec, ToolSpec)
            assert callable(tool.func)
