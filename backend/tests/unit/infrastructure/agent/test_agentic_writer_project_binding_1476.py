"""#1476 RED 契约测试 — 写作轨检索工具的项目上下文注入（装配期 project_id 闭包绑定）.

缺陷形态（issue #1476 实测）：`write next --mode agentic` 时 4 个检索工具里 3 个返回
`{"ok": false, "error": "项目不存在"}`（get_prior_summary 因 summary 服务对 None 宽容而
"假绿"返回 `[]`），Agent 因此盲写、自造人名地名（设定漂移的结构性来源）。

根因（源码定位，非 issue 的疑似方向①）：
`infrastructure/agent/agentic_writer.py::build_agentic_writer` 调
`build_reader_tools(reader_deps, include=...)` 时**从未传 `project_id`** —— 而
`build_reader_tools(deps, project_id=None, ...)`（#680 语义）正是靠该形参把项目绑定
进每个工具闭包（`bound_project_id`）。漏传 → 全部 6 个项目域检索工具以 `None` 查库。
对照：chat 轨经 `tools/registry.py::_build_all_tools` 传了 `project_id=project_id`，
故 chat 轨正常。

契约真相源: specs/f27-writer-agent/spec.md §5.1「工具的项目上下文注入方式」（#1476 融入）。

被测对象（装配层，非 LLM 行为）：
    from inkflow.infrastructure.agent.agentic_writer import build_agentic_writer

patch 注入点（from-import 绑定名快照，patch 调用方模块属性）:
    inkflow.infrastructure.agent.agentic_writer.build_deep_agent

🔴 关于 issue 中的「工具调用参数全为空 args={}」：那是 schema 的**正常形态**，不是缺陷——
#680/#718 明确把 project_id 从工具 schema 移除（防 LLM 编造全零 UUID），工具参数只余
可选过滤项，故 LLM 传 `{}` 是正确行为。真正的判据是「工具闭包是否绑定到请求项目」，
即本文件断言面。把 project_id 塞回 schema 会推翻 #680 并放开孤儿数据面。

pytestmark: 本文件全部用例为同步函数（build_agentic_writer 同步），工具 func 为协程 →
    在用例内用 asyncio.run 驱动（不进事件循环 fixture，避免 conftest 干扰）。

同链路第二缺陷（本 PR 一并修）：`get_prior_summary` 的真实返回是 dataclass
`ChapterSummary`（无 `model_dump`），`reader_tools._serialize_data` 不认识 dataclass →
`json.dumps` 抛 TypeError → **有数据时**信封变 `{"ok": false, "error": "Object of type
ChapterSummary is not JSON serializable"}`（issue #1476 表格里的 `{"ok": true, "data": []}`
是空列表掩盖下的假绿）。R3 锁定。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from inkflow.domain.models.context import ChapterSummary
from inkflow.infrastructure.agent.agentic_writer import (
    AgenticWriterDeps,
    build_agentic_writer,
)
from inkflow.infrastructure.agent.tools.reader_tools import _serialize_data

# ── 常量 ──────────────────────────────────────

MODEL = "deepseek/deepseek-v4-flash"
API_KEY = "test-key"
BASE_URL = "https://example.test/v1"
BASE_PROMPT = "你是章节写手，负责按大纲撰写正文。"

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
OTHER_PROJECT_ID = uuid.UUID("99999999-9999-4999-8999-999999999999")
CHAPTER_ID = uuid.UUID("87654321-4321-8765-4321-876543218765")

# 写作轨 6 个项目域检索工具（get_character/get_foreshadowing/get_world_setting/
# count_words 按 id/文本取数，不依赖项目上下文 → 不在本断言面）。
PROJECT_SCOPED_TOOLS = [
    "search_characters",
    "check_foreshadowing",
    "list_foreshadowing",
    "list_world_settings",
    "get_prior_summary",
    "audit_chapter",
]

# 中文占位名（中性命名，不引任何真实设定素材）。
CHARACTER_NAME = "角色甲"
WORLD_SETTING_NAME = "设定乙"
FORESHADOWING_TEXT = "伏笔丙"

_NOT_FOUND = "项目不存在"


class _ProjectScopedService:
    """记录收到的 project_id 的 service 桩——project_id 为 None 时抛「项目不存在」.

    镜像真实仓储语义（按 None 查库取不到任何项目行 → 上层抛错 → 工具回 _fail 信封）。
    """

    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.received: list[object] = []

    def _record(self, project_id: object) -> None:
        self.received.append(project_id)
        if project_id is None:
            raise ValueError(_NOT_FOUND)

    async def list_characters(self, project_id=None, **_kw: object) -> list[object]:
        self._record(project_id)
        return [{"id": str(uuid.uuid4()), "name": CHARACTER_NAME}]

    async def list(self, project_id=None, **_kw: object) -> list[object]:
        self._record(project_id)
        return [{"id": str(uuid.uuid4()), "content": FORESHADOWING_TEXT}]

    async def list_recent(self, project_id=None, **_kw: object) -> list[object]:
        self._record(project_id)
        return [{"chapter": 1, "summary": "前文摘要"}]

    async def audit(self, project_id=None, chapter_id=None, **_kw: object) -> list[object]:
        self._record(project_id)
        return [{"finding": "ok"}]

    async def list_settings(self, project_id=None, **_kw: object) -> list[object]:
        self._record(project_id)
        return [{"id": str(uuid.uuid4()), "name": WORLD_SETTING_NAME}]


def _make_deps(**overrides: object) -> AgenticWriterDeps:
    """六个 service 桩（项目域各自记录 project_id）+ draft/audit 桩；可按名覆盖。"""
    deps = AgenticWriterDeps(
        character_service=_ProjectScopedService(CHARACTER_NAME),
        foreshadowing_service=_ProjectScopedService(FORESHADOWING_TEXT),
        summary_service=_ProjectScopedService("前文摘要"),
        chapter_audit_service=_ProjectScopedService("ok"),
        draft_service=MagicMock(),
        audit_service=MagicMock(),
        world_service=_ProjectScopedService(WORLD_SETTING_NAME),
    )
    for key, value in overrides.items():
        setattr(deps, key, value)
    return deps


class _RowsService:
    """返回固定行集的异步 service 桩（记录收到的 project_id）."""

    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.received: list[object] = []

    async def list_recent(self, project_id: object = None, **_kw: object) -> list[object]:
        self.received.append(project_id)
        return self.rows


def _assemble(deps: AgenticWriterDeps, *, expected_project_id=None) -> dict[str, object]:
    """跑真实 build_agentic_writer（只 patch build_deep_agent）→ 返回物化工具表.

    Returns:
        {tool_name: Tool} —— 从 build_deep_agent 的 tools 形参取回的真实 Tool 对象。
    """
    with patch("inkflow.infrastructure.agent.agentic_writer.build_deep_agent") as m_da:
        m_da.return_value = MagicMock()
        build_agentic_writer(
            model=MODEL,
            api_key=API_KEY,
            base_url=BASE_URL,
            deps=deps,
            system_prompt=BASE_PROMPT,
            tool_ids=PROJECT_SCOPED_TOOLS,
            expected_project_id=expected_project_id,
        )
        tools = m_da.call_args.kwargs["tools"]
    return {tool.spec.name: tool for tool in tools}


def _call(tool: object, **kwargs: object) -> dict:
    """同步驱动工具协程并解析 JSON 信封。"""
    raw = asyncio.run(tool.func(**kwargs))  # type: ignore[attr-defined]  # Tool.func 为 async 闭包
    return json.loads(raw)


# audit_chapter 需 chapter_id（它是按章取数，非项目级过滤）；其余项目域工具零参调用。
_CALL_ARGS: dict[str, dict[str, object]] = {
    "audit_chapter": {"chapter_id": str(CHAPTER_ID)},
}


# ── R1: 装配期 project_id 绑定（装配层，确定性） ──


class TestReaderToolsBoundToRequestProject:
    """build_agentic_writer 必须把请求项目注入检索工具闭包（#1476 根因）。"""

    def test_all_project_scoped_tools_receive_bound_project_id(self) -> None:
        """6 个项目域工具各自向 service 传的 project_id == 装配期 expected_project_id.

        当前实现：build_reader_tools 未收 project_id → bound_project_id=None →
        每个 service 收到的都是 None（真实仓储 → 「项目不存在」）→ FAILED。
        """
        deps = _make_deps()
        tools = _assemble(deps, expected_project_id=PROJECT_ID)

        assert sorted(tools) == sorted(PROJECT_SCOPED_TOOLS)

        for name in PROJECT_SCOPED_TOOLS:
            envelope = _call(tools[name], **_CALL_ARGS.get(name, {}))
            assert envelope.get("ok") is True, f"{name} 应成功取数，实得 {envelope}"

        for service in (
            deps.character_service,
            deps.foreshadowing_service,
            deps.summary_service,
            deps.chapter_audit_service,
            deps.world_service,
        ):
            received = service.received  # type: ignore[attr-defined]  # 桩实例：AgenticWriterDeps 字段按鸭子类型声明为 object
            assert received, "对应 service 未被调用（工具未物化？）"
            assert set(received) == {PROJECT_ID}, (
                f"service 收到 {received!r}，应全部为绑定项目 {PROJECT_ID}"
            )

    def test_no_project_context_stays_none(self) -> None:
        """未给项目上下文（None）→ 保持既有防御语义（传 None 给 service，走 _fail 信封）."""
        deps = _make_deps()
        tools = _assemble(deps, expected_project_id=None)

        envelope = _call(tools["search_characters"])
        assert envelope == {"ok": False, "error": _NOT_FOUND}
        assert deps.character_service.received == [None]  # type: ignore[attr-defined]  # 桩实例：字段声明为 object


# ── R2: 跨项目隔离不回归（schema 无 project_id + 绑定值恒为请求项目） ──


class TestCrossProjectIsolation:
    """#680/#718 语义不得为「能用」而删除：LLM 无 project_id 可传，绑定值恒为请求项目."""

    def test_project_scoped_schema_exposes_no_project_id(self) -> None:
        """6 个项目域工具 schema 不带 project_id（结构上无法指向别的项目）."""
        tools = _assemble(_make_deps(), expected_project_id=PROJECT_ID)
        for name in PROJECT_SCOPED_TOOLS:
            props = tools[name].spec.input_schema.get("properties", {})  # type: ignore[attr-defined]  # Tool 按鸭子类型声明为 object
            assert "project_id" not in props, f"{name} schema 不应暴露 project_id"

    def test_rebinding_other_project_does_not_leak(self) -> None:
        """装配到项目 A → service 只可能收到 A（即便另有项目 id 存在也无入口传入）."""
        deps_a = _make_deps()
        tools_a = _assemble(deps_a, expected_project_id=PROJECT_ID)
        _call(tools_a["list_world_settings"])
        assert deps_a.world_service.received == [PROJECT_ID]  # type: ignore[attr-defined]  # 桩实例：字段声明为 object
        assert OTHER_PROJECT_ID not in deps_a.world_service.received  # type: ignore[attr-defined]  # 桩实例：字段声明为 object


# ── R3: 摘要域 dataclass 序列化（#1476 同链路第二缺陷） ──


class TestPriorSummarySerializesDataclass:
    """get_prior_summary 的真实返回是 dataclass（ChapterSummary）→ 信封必须可 JSON 序列化.

    issue #1476 里该工具「假绿」返回 `{"ok": true, "data": []}`——空列表掩盖了
    `reader_tools._serialize_data` 不认识 dataclass 的缺陷（`json.dumps` 抛
    TypeError → 信封变 `{"ok": false, "error": "Object of type ChapterSummary is
    not JSON serializable"}`）。项目绑定一修好（列表非空）即暴露。
    """

    def test_prior_summary_with_dataclass_rows_returns_ok(self) -> None:
        """有真实摘要行 → `ok: true` 且字段 JSON 化（UUID → 字符串）."""
        summary = ChapterSummary(
            id=uuid.UUID(int=900),
            chapter_id=CHAPTER_ID,
            summary="前文摘要内容",
            model="test-model",
            created_at="2026-10-06T00:00:00+00:00",
            updated_at="2026-10-06T00:00:00+00:00",
        )
        deps = _make_deps(summary_service=_RowsService([summary]))
        tools = _assemble(deps, expected_project_id=PROJECT_ID)

        envelope = _call(tools["get_prior_summary"])

        assert envelope["ok"] is True, envelope
        assert envelope["data"][0]["summary"] == "前文摘要内容"
        assert envelope["data"][0]["chapter_id"] == str(CHAPTER_ID)  # UUID → str


@dataclass
class _NestedRow:
    """含 UUID / datetime / 容器字段的 dataclass（覆盖 _json_safe 各分支）."""

    id: uuid.UUID
    at: datetime
    tags: list[str]
    pair: tuple[str, ...]
    meta: dict[str, object]


class TestSerializeDataDataclassSupport:
    """`reader_tools._serialize_data` 的 dataclass 分支（#1476）."""

    def test_nested_dataclass_payload_is_json_safe(self) -> None:
        """dataclass 嵌套容器 / UUID / datetime 全部 JSON 化（信封可 json.dumps）."""
        row = _NestedRow(
            id=uuid.UUID(int=1),
            at=datetime(2026, 10, 6, 12, 0, tzinfo=UTC),
            tags=["甲"],
            pair=("乙",),
            meta={"nested_id": uuid.UUID(int=2)},
        )

        payload = _serialize_data([row])

        assert json.loads(json.dumps(payload)) == [
            {
                "id": str(uuid.UUID(int=1)),
                "at": str(row.at),
                "tags": ["甲"],
                "pair": ["乙"],
                "meta": {"nested_id": str(uuid.UUID(int=2))},
            }
        ]

    def test_plain_values_pass_through(self) -> None:
        """非 dataclass / 非 pydantic 值原样透传（零行为漂移）."""
        assert _serialize_data("文本") == "文本"
        assert _serialize_data(7) == 7
