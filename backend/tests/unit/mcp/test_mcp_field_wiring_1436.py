"""#1436 MCP 字段接线契约（RED）：声明即消费 + 字段名与内核 DTO 逐字对齐。

Issue #1436（#1233 同族）两条静默失效 —— 调用方拿到 ``{ok: true}``，实际什么都没发生：

A. ``manage_chapter.order`` —— 字段在 MCP 工具层**零消费**，且名字与内核 DTO 不符
   （内核是 ``order_index``）。``action=create/update`` 传 ``order=<n>`` → ``ok=True``、
   HTTP 正常，但章节顺序完全不变。
   拍板：**改名 ``order`` → ``order_index``**（镜像 ``ChapterCreate`` / ``ChapterUpdate``
   逐字对齐，遵循 #1233 定的「字段名与 DTO 逐字对齐」原则；**不做别名**），
   并在 ``_route_chapter`` 的 create/update body 透传。

B. ``write action=generate`` 的 ``target_words`` —— body 确实发了该键，但
   ``POST /writing/generate`` 的 DTO ``WritingRequest`` **没有** ``target_words``
   （只有 ``min_words`` / ``max_words``）且未设 ``model_config`` → pydantic v2 默认
   ``extra="ignore"`` **静默丢弃**，字数目标恒为默认 2000。
   拍板（B1·最小）：``target_words`` **映射为 ``min_words``**（镜像 CLI
   ``write next --min-words``）；``WritingRequest.min_words`` 带 ``ge=2000`` 约束 →
   更小值由内核 422 **显式失败**（对齐「显式失败优于静默错误」）；
   ``action=continue`` 保持不变（``ContinueWritingRequest`` 自身有 ``target_words``）。

C. 通用加固（#1436 建议项）：**「声明即消费」自检测试** —— 遍历 ``*Params`` 模型字段，
   断言每个字段至少在 ``mcp/tools/`` 内被消费一次，并附**变异自证**（对故意造出的
   「声明未接线」合成源码必须 FAIL），机械拦住本族未来所有形态。

── 装配缝（镜像 test_mcp_tool_surface_1233.py）─────────────────
func 内 lazy import 源头模块 → patch ``http_mod.InkFlowHTTPClient`` 恒返回同一记录型
FakeClient。只经公开面触发：``MCP_TOOL_REGISTRY`` 取工具 → ``func(**kwargs)``。

── RED 形态 ────────────────────────────────────────────────────
``ManageChapterParams`` 现为 ``order`` 且 ``_route_chapter`` 不透传 → A 组用例 FAIL
（body 无 ``order_index``）；``_route_write`` 现发 ``target_words``（DTO 无此字段）→
B 组用例 FAIL（``WritingRequest.model_validate(body).min_words`` 恒为 2000）；
C 组静态自检 FAIL（``ManageChapterParams.order`` 零消费）。GREEN 落地后整文件转绿。

── 测试约定 ────────────────────────────────────────────────────
- body/params 断言一律 ``.get(...)``（缺键 → None → AssertionError，而非 KeyError）。
- 落点断言经**内核 DTO 本体**校验（``WritingRequest.model_validate``），
  而非仅比对键名 —— 键名对但值不生效（B 的根因）必须能被抓住。
"""

from __future__ import annotations

import ast
import importlib
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

import inkflow.mcp.tools as _tools_pkg
from inkflow.domain.models.chapter import ChapterCreate, ChapterUpdate
from inkflow.domain.models.writing import ContinueWritingRequest, WritingRequest
from inkflow.mcp.tools import MCP_TOOL_REGISTRY
from inkflow.mcp.tools.schemas import ALL_SCHEMAS, ManageChapterParams

kernel_mod = importlib.import_module("inkflow.infrastructure.kernel")
http_mod = importlib.import_module("inkflow.infrastructure.http")

#: 内核 DTO 里的真实字段名（逐字对齐锚点）
_DTO_ORDER_FIELD = "order_index"


class FakeClient:
    """记录型 fake：预置响应队列，逐次出栈，耗尽后回退 ``default``。"""

    def __init__(self, handle: object) -> None:
        self.handle = handle
        self.calls: list[dict] = []
        self.responses: list[object] = []
        self.default: object = {"id": "x", "name": "resp"}

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def _next(self) -> object:
        if self.responses:
            return self.responses.pop(0)
        return self.default

    def _record(
        self, method: str, path: str, params: object, json_body: object, timeout: object = None
    ) -> None:
        self.calls.append(
            {
                "method": method,
                "path": path,
                "params": params,
                "json": json_body,
                "timeout": timeout,
            }
        )

    async def get(self, path: str, *, params: object = None, json: object = None) -> dict:
        self._record("GET", path, params, json)
        return self._next()  # type: ignore[return-value]  # 测试 fake：预置 dict 响应

    async def post(
        self, path: str, *, params: object = None, json: object = None, timeout: object = None
    ) -> dict:
        self._record("POST", path, params, json, timeout)
        return self._next()  # type: ignore[return-value]  # 测试 fake：预置 dict 响应

    async def patch(self, path: str, *, params: object = None, json: object = None) -> dict:
        self._record("PATCH", path, params, json)
        return self._next()  # type: ignore[return-value]  # 测试 fake：预置 dict 响应

    async def delete(self, path: str, *, params: object = None, json: object = None) -> dict:
        self._record("DELETE", path, params, json)
        return self._next()  # type: ignore[return-value]  # 测试 fake：预置 dict 响应

    async def get_raw(self, path: str, *, params: object = None) -> str:
        self._record("GET_RAW", path, params, None)
        value = self._next()
        return value if isinstance(value, str) else "raw-text"


@pytest.fixture
def fake_env(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """装配缝：ensure_kernel → 鸭子 handle；InkFlowHTTPClient 恒同一记录型实例。"""
    client = FakeClient(SimpleNamespace(port=1, token="t"))
    fake_ensure = AsyncMock(return_value=SimpleNamespace(port=1, token="t", pid=2, version="0.1.0"))
    monkeypatch.setattr(kernel_mod, "ensure_kernel", fake_ensure)
    monkeypatch.setattr(http_mod, "InkFlowHTTPClient", lambda handle: client)
    return SimpleNamespace(client=client, fake_ensure=fake_ensure)


def _tool(name: str):
    """按名取已装配工具（tools/list 同源）。"""
    return next(tool for tool in MCP_TOOL_REGISTRY if tool.spec.name == name)


def _envelope(text: str) -> dict:
    return json.loads(text)


def _last_body(client: FakeClient) -> dict:
    return client.calls[-1]["json"] or {}


class TestManageChapterOrderIndex1436:
    """A：``order`` → ``order_index`` 改名 + create/update 透传（内核 DTO 逐字对齐）。"""

    @pytest.mark.asyncio
    async def test_create_transmits_order_index(self, fake_env):
        env = _envelope(
            await _tool("manage_chapter").func(
                action="create",
                project_id="p1",
                title="第一章",
                order_index=3.5,
            )
        )
        assert env["ok"] is True
        body = _last_body(fake_env.client)
        assert body.get(_DTO_ORDER_FIELD) == 3.5, "create 未透传 order_index（顺序静默不变）"

    @pytest.mark.asyncio
    async def test_update_transmits_order_index(self, fake_env):
        env = _envelope(await _tool("manage_chapter").func(action="update", id="c1", order_index=7))
        assert env["ok"] is True
        body = _last_body(fake_env.client)
        assert body.get(_DTO_ORDER_FIELD) == 7, "update 未透传 order_index（顺序静默不变）"

    @pytest.mark.asyncio
    async def test_create_roundtrip_lands_in_kernel_dto(self, fake_env):
        """往返一致：透传值经**内核 DTO 本体**校验后落在 ``order_index`` 字段上。"""
        await _tool("manage_chapter").func(
            action="create", project_id="p1", title="第一章", order_index=2.25
        )
        body = _last_body(fake_env.client)
        parsed = ChapterCreate.model_validate(body)
        assert parsed.order_index == 2.25

    @pytest.mark.asyncio
    async def test_update_roundtrip_lands_in_kernel_dto(self, fake_env):
        await _tool("manage_chapter").func(action="update", id="c1", order_index=9.75)
        body = _last_body(fake_env.client)
        parsed = ChapterUpdate.model_validate(body)
        assert parsed.order_index == 9.75

    @pytest.mark.asyncio
    async def test_absent_order_index_omits_key(self, fake_env):
        """未传 → 不发该键（不得凭默认值覆盖内核既有顺序）。"""
        env = _envelope(
            await _tool("manage_chapter").func(action="create", project_id="p1", title="第一章")
        )
        assert env["ok"] is True
        assert _DTO_ORDER_FIELD not in _last_body(fake_env.client)

    def test_schema_declares_order_index_not_order(self):
        """破坏性改名锁：旧名 ``order`` 必须消失（不做别名，遵循 #1233 逐字对齐原则）。"""
        fields = set(ManageChapterParams.model_fields)
        assert _DTO_ORDER_FIELD in fields, "ManageChapterParams 缺 order_index 字段"
        assert "order" not in fields, "order 旧名残留（与内核 DTO 不符，后续必再踩）"
        assert _DTO_ORDER_FIELD in ChapterCreate.model_fields
        assert _DTO_ORDER_FIELD in ChapterUpdate.model_fields

    def test_params_cover_chapter_create_dto_fields(self):
        """漂移护栏（镜像 #933 A8）：MCP 字段面 ⊇ 内核创建章节 DTO 字段面。"""
        params = set(ManageChapterParams.model_fields)
        missing = set(ChapterCreate.model_fields) - params
        assert missing == set(), f"ChapterCreate 字段未进 MCP 面：{sorted(missing)}"

    def test_params_cover_chapter_update_dto_write_fields(self):
        """漂移护栏：update DTO 的写面字段须全部可达（``writing_requirements`` 见下方豁免）。"""
        params = set(ManageChapterParams.model_fields)
        # writing_requirements（#1017 章级写作要求）不在本工具面：它由写作链
        # `_fetch_chapter_requirements` 读取，不属 manage_chapter 写路径，另行跟踪。
        missing = set(ChapterUpdate.model_fields) - params - {"writing_requirements"}
        assert missing == set(), f"ChapterUpdate 字段未进 MCP 面：{sorted(missing)}"
        assert "writing_requirements" not in params, (
            "writing_requirements 已进 MCP 面 → 请移除此豁免并补透传契约用例"
        )


class TestWriteGenerateWordTarget1436:
    """B：``write action=generate`` 的字数目标须落到 ``WritingRequest.min_words``。"""

    def _generate_args(self) -> dict[str, object]:
        return {
            "action": "generate",
            "project_id": str(uuid.uuid4()),
            "chapter_id": str(uuid.uuid4()),
            "outline": "主角在雨夜做出抉择（通用占位大纲）",
        }

    @pytest.mark.asyncio
    async def test_generate_lands_target_words_in_dto_min_words(self, fake_env):
        env = _envelope(
            await _tool("write").func(**{**self._generate_args(), "target_words": 3000})
        )
        assert env["ok"] is True
        call = fake_env.client.calls[-1]
        assert (call["method"], call["path"]) == ("POST", "/writing/generate")
        body = call["json"] or {}
        # 键名对但值不生效是 B 的**根因形态** → 必须经 DTO 本体验落点，而非只比键名
        parsed = WritingRequest.model_validate(body)
        assert parsed.min_words == 3000, "字数目标未落到内核 DTO 有效字段（被静默丢弃）"
        assert "target_words" not in body, "WritingRequest 无 target_words 字段，勿透传"

    @pytest.mark.asyncio
    async def test_generate_without_target_words_keeps_dto_default(self, fake_env):
        env = _envelope(await _tool("write").func(**self._generate_args()))
        assert env["ok"] is True
        parsed = WritingRequest.model_validate(_last_body(fake_env.client))
        assert parsed.min_words == WritingRequest.model_fields["min_words"].default

    def test_root_cause_reproduced_against_real_dto(self):
        """根因取证（反例守护）：``target_words`` 键被内核 DTO **静默忽略**。"""
        bogus = {
            "project_id": str(uuid.uuid4()),
            "chapter_id": str(uuid.uuid4()),
            "outline": "大纲占位",
            "target_words": 3000,
        }
        parsed = WritingRequest.model_validate(bogus)
        assert parsed.min_words == WritingRequest.model_fields["min_words"].default, (
            "WritingRequest 已能识别 target_words → 本映射契约需重新评估"
        )

    def test_below_dto_floor_is_explicit_failure(self):
        """B1 取舍钉死：``min_words`` 带 ``ge=2000`` → 更小值**显式 422**（非静默）。

        由此 MCP ``generate`` 的 ``target_words`` 有效区间 = **[2000, 4000]**：上界来自
        ``WritingRequest.max_words`` 默认 4000 + ``max_words >= min_words`` 校验（CLI
        ``write next --min-words`` 同一 DTO、同一区间）；两端均为显式 422，无静默丢弃。
        """
        assert WritingRequest.model_fields["min_words"].metadata, "min_words 约束缺失"
        with pytest.raises(ValidationError):
            WritingRequest.model_validate(
                {
                    "project_id": str(uuid.uuid4()),
                    "chapter_id": str(uuid.uuid4()),
                    "outline": "大纲占位",
                    "min_words": 1500,
                }
            )

    @pytest.mark.asyncio
    async def test_continue_still_uses_target_words(self, fake_env):
        """反例守护：``action=continue`` 的 ``target_words`` 通道**不得**被改坏。"""
        target = 3000
        env = _envelope(
            await _tool("write").func(
                action="continue",
                project_id=str(uuid.uuid4()),
                chapter_id=str(uuid.uuid4()),
                existing_content="已有正文占位" * 20,
                target_words=target,
            )
        )
        assert env["ok"] is True
        call = fake_env.client.calls[-1]
        assert (call["method"], call["path"]) == ("POST", "/writing/continue")
        body = call["json"] or {}
        assert body.get("target_words") == target
        assert ContinueWritingRequest.model_validate(body).target_words == target


# ── C：通用加固「声明即消费」自检 ────────────────────────────────────
#
# #1437 已接线两处存量豁免（本表清空）：
#   · ``WriteParams.instruction`` → revise 时映射为内核 ``feedback``（CLI 先例）；
#   · ``ExportParams.output_path`` → 内核无路径能力 → 传即显式 ``INVALID_ARGS``。
# 双向断言：豁免表 == 实际未接线集 —— 新形态必红，修好后不删豁免项也必红。

_KNOWN_UNWIRED: dict[str, str] = {}


def _consumed_names(sources: dict[str, str]) -> set[str]:
    """静态收集被消费的字段名。

    覆盖两种既有接线形态：
    ① ``params.<field>`` 属性访问；
    ② ``getattr(params, <field>)``（含经字符串元组/列表变量展开的循环变量，
       如 ``body_fields`` / ``six_tuple``）。
    """
    consumed: set[str] = set()
    for source in sources.values():
        tree = ast.parse(source)
        containers: dict[str, set[str]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(
                node.value, (ast.Tuple, ast.List, ast.Set)
            ):
                names = {
                    element.value
                    for element in node.value.elts
                    if isinstance(element, ast.Constant) and isinstance(element.value, str)
                }
                if names:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            containers[target.id] = names
        linked: dict[str, set[str]] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.comprehension, ast.For)) and isinstance(node.target, ast.Name):
                iterator = node.iter
                if isinstance(iterator, ast.Name) and iterator.id in containers:
                    linked[node.target.id] = containers[iterator.id]
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "params"
            ):
                consumed.add(node.attr)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) == 2
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "params"
            ):
                argument = node.args[1]
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    consumed.add(argument.value)
                elif isinstance(argument, ast.Name) and argument.id in linked:
                    consumed |= linked[argument.id]
    return consumed


def _declared_fields(schemas_source: str) -> dict[str, set[str]]:
    """从 schemas.py 源码 AST 抽出 ``*Params`` 类的注解字段名（跳过 ``_`` 私有基类）。"""
    declared: dict[str, set[str]] = {}
    for node in ast.parse(schemas_source).body:
        if (
            isinstance(node, ast.ClassDef)
            and node.name.endswith("Params")
            and not node.name.startswith("_")
        ):
            declared[node.name] = {
                statement.target.id
                for statement in node.body
                if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
            }
    return declared


def _audit(sources: dict[str, str], declared: dict[str, set[str]]) -> set[str]:
    """返回「声明但零消费」字段集（``Model.field`` 形态）。"""
    consumed = _consumed_names(sources)
    return {
        f"{model_name}.{field}"
        for model_name, fields in declared.items()
        for field in sorted(fields)
        if field not in consumed
    }


def _real_tool_sources() -> dict[str, str]:
    tools_dir = Path(_tools_pkg.__file__).parent
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(tools_dir.glob("*.py"))}


class TestDeclaredFieldsAreConsumed1436:
    """通用加固：MCP 参数模型「声明即消费」+ 变异自证（分析器必须有牙）。"""

    def test_no_undeclared_wiring_gaps_beyond_known(self):
        """真实源码审计：未接线集必须恰好等于已登记豁免集（双向，防豁免表僵化）。"""
        sources = _real_tool_sources()
        declared = _declared_fields(sources["schemas.py"])
        assert set(declared) == set(ALL_SCHEMAS), (
            "schemas.py 声明的 *Params 与 ALL_SCHEMAS 不一致（工具面注册漂移）"
        )
        missing = _audit(sources, declared)
        assert missing == set(_KNOWN_UNWIRED), (
            f"「声明了却零消费」字段集变化：{sorted(missing)}"
            f"（已登记豁免 {sorted(_KNOWN_UNWIRED)}）"
            "；新增即 #1436 同族静默失效，修复后须同步移除豁免条目"
        )

    def test_audit_flags_deliberately_unwired_field(self):
        """变异自证：故意造「声明未接线」合成源码 → 分析器必须 FAIL 出该字段。"""
        sources = {
            "schemas.py": (
                "class FooParams(_MCPParams):\n"
                "    action: str\n"
                "    wired: int | None = None\n"
                "    unwired: int | None = None\n"
            ),
            "foo_tools.py": (
                "async def _route_foo(client, params):\n"
                "    return await client.post('/x', json={'action': params.action,"
                " 'wired': params.wired})\n"
            ),
        }
        declared = _declared_fields(sources["schemas.py"])
        assert _audit(sources, declared) == {"FooParams.unwired"}

    def test_audit_recognizes_getattr_container_wiring(self):
        """变异自证 · 反盲区：经字符串元组 + ``getattr`` 循环的接线必须算作已消费。

        （若分析器漏判此形态，就会把真实接线误报为缺口 —— 逼着人往豁免表里塞假条目。）
        """
        sources = {
            "schemas.py": (
                "class BarParams(_MCPParams):\n"
                "    action: str\n"
                "    alpha: str | None = None\n"
                "    beta: str | None = None\n"
            ),
            "bar_tools.py": (
                "async def _route_bar(client, params):\n"
                "    if params.action == 'create':\n"
                "        fields = ('alpha', 'beta')\n"
                "        return await client.post('/y',"
                " json={f: getattr(params, f) for f in fields})\n"
                "    return await client.get('/y')\n"
            ),
        }
        declared = _declared_fields(sources["schemas.py"])
        assert _audit(sources, declared) == set()
