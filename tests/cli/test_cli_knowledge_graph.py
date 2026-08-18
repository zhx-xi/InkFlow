"""F48 知识图谱 CLI 命令 RED 契约测试 — Mock ensure_kernel +
InkFlowHTTPClient（只写测试，不改 src/）.

被测模块: inkflow.cli.commands.knowledge_graph（整模块尚未实现——本文件为 RED 契约）。
镜像 tests/cli/test_cli_world.py（F10）+ tests/cli/test_cli_character_relations.py（F9）形态:
CliRunner + fake_http_client fixture（patch 命令模块命名空间 ensure_kernel / InkFlowHTTPClient）；
路径断言镜像 tests/unit/test_book_cli_paths.py（#458 base_url 双前缀坑）。

【RED 预期】
本文件**不在顶部 import inkflow.cli**（tests/unit 守护契约
test_http_client.py::TestImportSurface::test_no_cli_import_on_http_import 断言
'inkflow.cli' not in sys.modules——顶部 import 在收集期载入 inkflow.cli 会破坏该守护）。
命令模块经 _kg() 执行期 importlib.import_module 惰性加载 → RED 形态 = 每个用例
fixture setup 抛 ModuleNotFoundError（'inkflow.cli.commands.knowledge_graph' 未实现），
全部用例 ERROR = 正确 RED 终态，父侧亲自确认。

【GREEN 必须匹配的契约】依据 specs/f48-knowledge-graph/spec.md §4 + F7 §5 全局约定：

1. 被测模块 inkflow.cli.commands.knowledge_graph:
   - app = typer.Typer(name='knowledge', help='知识图谱管理', no_args_is_help=True)
   - relation_app = typer.Typer(name='relation', help='关系管理', no_args_is_help=True);
     app.add_typer(relation_app, name='relation')
   - 薄层设计（镜像 cli/commands/map.py）: _run(cli_ctx, coro_fn) 统一映射
     HttpApiError（map_http_error）→ print_error 信封；_parse_uuid(ctx, value, message)
     非法 UUID → NOT_FOUND（消息即 detail）；命令内 ensure_kernel() +
     InkFlowHTTPClient(handle) + async with client 调 REST API
   - ⚠️ 请求路径**相对 base_url**（InkFlowHTTPClient base_url 已含 /api/v1，#458
     load-bearing）——一律写 "/projects/..." / "/knowledge-relations/..."，
     **严禁** "/api/v1/..." 双前缀

2. 命令与路径:
   - knowledge graph <project_id> [--json] —— GET /projects/{pid}/knowledge-graph
     → 信封 data = API 原样 {nodes, edges}；文本模式逐边输出摘要行
     f"{source节点名} --{label}--> {target节点名}"（edge.source/target 节点 ID 在
     nodes 中按 id 映射到 name，映射缺失回退节点 ID 原样）
   - knowledge relation list <project_id> [--source-type <type>] [--target-type <type>]
     [--relation-type <text>] —— GET /projects/{pid}/knowledge-relations（params 透传
     有值过滤项）→ 信封 data = {items, total}
   - knowledge relation add <project_id> --source-type <type> --source-id <UUID>
     --target-type <type> --target-id <UUID> --relation-type <text>
     [--description <text>] —— POST /projects/{pid}/knowledge-relations，
     json = {source_type, source_id, target_type, target_id, relation_type,
     description?（仅传时）}
   - knowledge relation get <relation_id> —— GET /knowledge-relations/{rid}
   - knowledge relation update <relation_id> [--relation-type <text>]
     [--description <text>] [--source-id <UUID>] —— PATCH /knowledge-relations/{rid}，
     json 仅含传入字段（六元组可改 + description，spec §4）
   - knowledge relation delete <relation_id> [--force] —— DELETE
     /knowledge-relations/{rid}；真删（无 restore）；无 --force 二次确认
     （typer.confirm）；--json + 无 --force → VALIDATION_ERROR「删除需 --force 或交互确认」

3. 信封与退出码（F7 §5 / F10 §4.2 先例）:
   - 成功 --json: {"ok": true, "data": ...} → 退出码 0
   - 失败 --json: {"ok": false, "error": {"code", "message"}} → 退出码 1
     （NOT_FOUND / VALIDATION_ERROR / DB_ERROR 等业务错误信封统一退出码 1；
     退出码 2 保留给 typer 用法错误——镜像 test_cli_world.py/test_cli_character_relations.py）
   - 错误码映射: HTTP 404 → NOT_FOUND、422 → VALIDATION_ERROR（map_http_error）

依据: specs/f48-knowledge-graph/spec.md §4 + F7 §5（信封/退出码）+ #458（路径前缀）。
"""

from __future__ import annotations

import importlib
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
SRC_ID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")
TGT_ID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000003")
RID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000004")


def _kg():
    """执行期惰性 import 命令模块（镜像 tests/unit/test_book_cli_paths.py）。

    不能顶部 import：tests/unit 套件守护契约
    test_http_client.py::TestImportSurface::test_no_cli_import_on_http_import
    断言 'inkflow.cli' not in sys.modules。RED 阶段模块不存在 →
    ModuleNotFoundError（预期 RED 形态）。
    """
    return importlib.import_module("inkflow.cli.commands.knowledge_graph")


def _ctx(json_output: bool):
    """构造 CliContext（惰性 import，避免顶部载入 inkflow.cli）。"""
    from inkflow.cli.context import CliContext

    return CliContext(json_output=json_output)


@pytest.fixture
def cli_runner():
    """click CliRunner（click 8.4 已移除 mix_stderr，默认混合输出）。"""
    return CliRunner()


@pytest.fixture
def fake_http_client():
    """Mock ensure_kernel + InkFlowHTTPClient（命令模块命名空间），绕过真实内核与 HTTP。

    patch 目标 = 命令模块命名空间（GREEN 后命令模块 from-import 绑定自身命名空间，
    F19 #77 先例）；RED 阶段 _kg() 即抛 ModuleNotFoundError → 用例 setup ERROR。
    """
    kg = _kg()
    fake_handle = SimpleNamespace(
        port=38291,
        token="test-token",
        pid=1,
        version="0.1.0",
        started_at="",
        reused=True,
    )
    with (
        patch.object(kg, "ensure_kernel", AsyncMock(return_value=fake_handle)),
        patch.object(kg, "InkFlowHTTPClient", autospec=True) as mock_cls,
    ):
        mock_instance = AsyncMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


def _http_error(status_code: int, detail: str, code: str | None = None):
    """构造 HttpApiError（lazy import：RED 阶段 inkflow.infrastructure.http 正常存在，
    惰性仅为保持与兄弟文件一致形态）。"""
    from inkflow.infrastructure.http import HttpApiError

    return HttpApiError(status_code=status_code, detail=detail, code=code)


def _make_relation(**overrides) -> dict:
    """构造测试用 KnowledgeRelation JSON dict（model_dump(mode='json') 等价物）。"""
    defaults = dict(
        id=str(RID),
        project_id=str(PID),
        source_type="character",
        source_id=str(SRC_ID),
        target_type="world",
        target_id=str(TGT_ID),
        relation_type="属于",
        description="林尘出身清河县",
        source="manual",
        created_at="2026-08-01T10:00:00",
        updated_at="2026-08-01T10:00:00",
    )
    defaults.update(overrides)
    return defaults


def _make_graph(**overrides) -> dict:
    """构造测试用图谱聚合 JSON dict（{nodes, edges}，spec §2.4 形状）。"""
    defaults = dict(
        nodes=[
            {
                "id": f"character:{SRC_ID}",
                "type": "character",
                "entity_id": str(SRC_ID),
                "name": "林尘",
            },
            {
                "id": f"world:{TGT_ID}",
                "type": "world",
                "entity_id": str(TGT_ID),
                "name": "清河县",
            },
        ],
        edges=[
            {
                "id": f"kr:{RID}",
                "source": f"character:{SRC_ID}",
                "target": f"world:{TGT_ID}",
                "label": "属于",
                "description": "林尘出身清河县",
                "source_table": "knowledge_relations",
            }
        ],
    )
    defaults.update(overrides)
    return defaults


def _assert_no_api_v1_prefix(path: str) -> None:
    """#458 load-bearing：请求路径必须相对 base_url（不含 /api/v1 双前缀）。"""
    assert "/api/v1" not in path, f"请求路径 {path!r} 含 /api/v1 双前缀（base_url 已含 /api/v1）"


class TestKnowledgeGraphCmd:
    """inkflow knowledge graph <project_id> —— 图谱聚合查询。"""

    def test_graph_json(self, cli_runner, fake_http_client):
        """graph --json → 成功信封 data={nodes, edges}；GET 路径相对 base_url。"""
        fake_http_client.get.return_value = _make_graph()
        result = cli_runner.invoke(
            _kg().app,
            ["graph", str(PID)],
            obj=_ctx(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert set(data["data"].keys()) == {"nodes", "edges"}
        assert data["data"]["nodes"][0]["name"] == "林尘"
        assert data["data"]["edges"][0]["label"] == "属于"
        fake_http_client.get.assert_awaited_once()
        path = fake_http_client.get.await_args.args[0]
        assert path == f"/projects/{PID}/knowledge-graph"
        _assert_no_api_v1_prefix(path)

    def test_graph_text_edges(self, cli_runner, fake_http_client):
        """graph 文本模式 → edges 摘要行 `source --label--> target`（节点显示名映射）。"""
        fake_http_client.get.return_value = _make_graph()
        result = cli_runner.invoke(
            _kg().app,
            ["graph", str(PID)],
            obj=_ctx(json_output=False),
        )
        assert result.exit_code == 0
        assert "林尘 --属于--> 清河县" in result.output


class TestKnowledgeRelationListCmd:
    """inkflow knowledge relation list <project_id> [--source-type --target-type
    --relation-type]。"""

    def test_relation_list_json(self, cli_runner, fake_http_client):
        """list --json → 成功信封 {items, total}；过滤参数透传；GET 路径相对 base_url。"""
        fake_http_client.get.return_value = {"items": [_make_relation()], "total": 1}
        result = cli_runner.invoke(
            _kg().app,
            [
                "relation",
                "list",
                str(PID),
                "--source-type",
                "character",
                "--target-type",
                "world",
                "--relation-type",
                "属于",
            ],
            obj=_ctx(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["total"] == 1
        assert data["data"]["items"][0]["relation_type"] == "属于"
        fake_http_client.get.assert_awaited_once()
        call = fake_http_client.get.await_args
        path = call.args[0]
        assert path == f"/projects/{PID}/knowledge-relations"
        _assert_no_api_v1_prefix(path)
        params = call.kwargs.get("params") or {}
        assert params["source_type"] == "character"
        assert params["target_type"] == "world"
        assert params["relation_type"] == "属于"


class TestKnowledgeRelationAddCmd:
    """inkflow knowledge relation add <project_id> --source-type ... --relation-type ..."""

    def test_relation_add_json(self, cli_runner, fake_http_client):
        """add --json → 成功信封；POST 六元组 body；路径相对 base_url。"""
        fake_http_client.post.return_value = _make_relation()
        result = cli_runner.invoke(
            _kg().app,
            [
                "relation",
                "add",
                str(PID),
                "--source-type",
                "character",
                "--source-id",
                str(SRC_ID),
                "--target-type",
                "world",
                "--target-id",
                str(TGT_ID),
                "--relation-type",
                "属于",
                "--description",
                "林尘出身清河县",
            ],
            obj=_ctx(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["relation_type"] == "属于"
        fake_http_client.post.assert_awaited_once()
        call = fake_http_client.post.await_args
        path = call.args[0]
        assert path == f"/projects/{PID}/knowledge-relations"
        _assert_no_api_v1_prefix(path)
        body = call.kwargs["json"]
        assert body["source_type"] == "character"
        assert body["source_id"] == str(SRC_ID)
        assert body["target_type"] == "world"
        assert body["target_id"] == str(TGT_ID)
        assert body["relation_type"] == "属于"
        assert body["description"] == "林尘出身清河县"

    def test_relation_add_conflict_validation_error(self, cli_runner, fake_http_client):
        """同键冲突（HTTP 422）→ VALIDATION_ERROR 错误信封 + 退出码 1。"""
        fake_http_client.post.side_effect = _http_error(422, "该关系已存在（同键唯一）")
        result = cli_runner.invoke(
            _kg().app,
            [
                "relation",
                "add",
                str(PID),
                "--source-type",
                "character",
                "--source-id",
                str(SRC_ID),
                "--target-type",
                "world",
                "--target-id",
                str(TGT_ID),
                "--relation-type",
                "属于",
            ],
            obj=_ctx(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "该关系已存在（同键唯一）" in data["error"]["message"]


class TestKnowledgeRelationGetCmd:
    """inkflow knowledge relation get <relation_id>。"""

    def test_relation_get_json(self, cli_runner, fake_http_client):
        """get --json → 成功信封；GET 路径相对 base_url。"""
        fake_http_client.get.return_value = _make_relation()
        result = cli_runner.invoke(
            _kg().app,
            ["relation", "get", str(RID)],
            obj=_ctx(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["id"] == str(RID)
        fake_http_client.get.assert_awaited_once()
        path = fake_http_client.get.await_args.args[0]
        assert path == f"/knowledge-relations/{RID}"
        _assert_no_api_v1_prefix(path)

    def test_relation_get_not_found(self, cli_runner, fake_http_client):
        """关系不存在（HTTP 404）→ NOT_FOUND 错误信封 + 退出码 1。"""
        fake_http_client.get.side_effect = _http_error(404, "关系不存在")
        result = cli_runner.invoke(
            _kg().app,
            ["relation", "get", str(RID)],
            obj=_ctx(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"
        assert data["error"]["message"] == "关系不存在"


class TestKnowledgeRelationUpdateCmd:
    """inkflow knowledge relation update <relation_id> [--relation-type ...]"""

    def test_relation_update_json(self, cli_runner, fake_http_client):
        """update --json → 成功信封；PATCH body 仅含传入字段；路径相对 base_url。"""
        fake_http_client.patch.return_value = _make_relation(relation_type="出身")
        result = cli_runner.invoke(
            _kg().app,
            ["relation", "update", str(RID), "--relation-type", "出身"],
            obj=_ctx(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["relation_type"] == "出身"
        fake_http_client.patch.assert_awaited_once()
        call = fake_http_client.patch.await_args
        path = call.args[0]
        assert path == f"/knowledge-relations/{RID}"
        _assert_no_api_v1_prefix(path)
        body = call.kwargs["json"]
        assert body == {"relation_type": "出身"}


class TestKnowledgeRelationDeleteCmd:
    """inkflow knowledge relation delete <relation_id>（真删 + 二次确认，spec §4）。"""

    def test_relation_delete_force_json(self, cli_runner, fake_http_client):
        """delete --force --json → 成功信封 {deleted, id}；DELETE 路径相对 base_url。"""
        fake_http_client.delete.return_value = {}
        result = cli_runner.invoke(
            _kg().app,
            ["relation", "delete", str(RID), "--force"],
            obj=_ctx(json_output=True),
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["ok"] is True
        assert data["data"]["deleted"] is True
        fake_http_client.delete.assert_awaited_once()
        path = fake_http_client.delete.await_args.args[0]
        assert path == f"/knowledge-relations/{RID}"
        _assert_no_api_v1_prefix(path)

    def test_relation_delete_confirm_yes(self, cli_runner, fake_http_client):
        """无 --force 人类模式 → 交互确认，回答 y 继续删除。"""
        fake_http_client.delete.return_value = {}
        result = cli_runner.invoke(
            _kg().app,
            ["relation", "delete", str(RID)],
            input="y\n",
            obj=_ctx(json_output=False),
        )
        assert result.exit_code == 0
        assert "已删除" in result.output
        fake_http_client.delete.assert_awaited()

    def test_relation_delete_confirm_no(self, cli_runner, fake_http_client):
        """无 --force 人类模式 → 回答 n 取消，不调用 DELETE。"""
        result = cli_runner.invoke(
            _kg().app,
            ["relation", "delete", str(RID)],
            input="n\n",
            obj=_ctx(json_output=False),
        )
        assert result.exit_code == 0
        assert "取消" in result.output
        fake_http_client.delete.assert_not_awaited()

    def test_relation_delete_json_no_force(self, cli_runner, fake_http_client):
        """--json 且无 --force → VALIDATION_ERROR + 退出码 1（F7 §7 约定），不调 DELETE。"""
        result = cli_runner.invoke(
            _kg().app,
            ["relation", "delete", str(RID)],
            obj=_ctx(json_output=True),
        )
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"
        fake_http_client.delete.assert_not_awaited()
