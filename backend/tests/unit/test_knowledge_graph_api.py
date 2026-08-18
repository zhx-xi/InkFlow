"""F48 知识图谱 API 层 RED 契约测试 — Mock KnowledgeGraphService（只写测试，不改 src/）.

被测 router: inkflow.api.routers.knowledge_graph（整模块尚未实现——本文件为 RED 契约）。
镜像 tests/unit/test_map_api.py（F36）形态: 模块级 TestClient(app) +
@patch("inkflow.api.routers.knowledge_graph.get_knowledge_graph_service") +
_mock_svc helper + 用例类分组；每个被路由 await 的服务方法显式赋 AsyncMock
（未赋值的同步 MagicMock 子 mock 被 await 会返回 coroutine 导致 500，F4 4.1 实测陷阱）。

【RED 预期】
收集期 ModuleNotFoundError: No module named 'inkflow.api.routers.knowledge_graph'
（router 未实现，collected 0 items / exit 2）= 正确 RED 终态，父侧亲自确认。
knowledge_graph_errors 模块同批缺失 → 用模块级 try/except stub（置于主 import
之前，吞掉自身 ImportError，收集错误唯一聚焦主契约 router；GREEN 落地后 try 走
真实类、stub 自动消解）；领域模型（domain/models/knowledge_graph.py）在工厂函数
体内惰性 import（不参与顶部收集错误）。

【GREEN 必须匹配的契约】依据 specs/f48-knowledge-graph/spec.md §3.1/§3.2/§3.3/§7：

1. 被测模块 inkflow.api.routers.knowledge_graph（整模块未实现）:
   router = APIRouter(prefix='/api/v1', tags=['知识图谱'])
   - _parse_id(id_str, detail='资源不存在'): UUID 或 int 解析，非法 → 404；
     项目路径参数传 detail='项目不存在'、关系参数传 detail='关系不存在'
   - _get_svc(db) → get_knowledge_graph_service(db)（patch 目标）
   - _run_service(coro) catch 链: KnowledgeGraphServiceError 子类 → 422（str(e)
     即 detail）；KnowledgeRelationNotFoundError / ProjectNotFoundError
     （world_errors 复用）→ 404

2. 端点总览（6 个，spec §3.1）:
   - POST /api/v1/projects/{project_id}/knowledge-relations —— body
     KnowledgeRelationCreate {source_type, source_id, target_type, target_id,
     relation_type, description?} → 201 KnowledgeRelation JSON
   - GET /api/v1/projects/{project_id}/knowledge-relations —— 过滤
     ?source_type=&target_type=&relation_type=&source= + 分页 offset/limit
     → {"items", "total", "offset", "limit"}（offset=0 / limit=50 回显）
   - GET /api/v1/projects/{project_id}/knowledge-graph →
     KnowledgeGraphView JSON {"nodes": [...], "edges": [...]}
   - GET /api/v1/knowledge-relations/{relation_id} → 200 KnowledgeRelation
   - PATCH /api/v1/knowledge-relations/{relation_id} —— body
     KnowledgeRelationUpdate 全可选（exclude_unset 语义，同 F1）→ 200
   - DELETE /api/v1/knowledge-relations/{relation_id} → 204 空 body

3. KnowledgeGraphService 方法契约（mock 目标，与兄弟文件 test_knowledge_graph_service.py
   的 docstring 契约一致）:
   create_relation(project_id, data: KnowledgeRelationCreate) -> KnowledgeRelation
     —— router 将请求体解析为 DTO 后透传（本文件断言 await_args 解包兼容位置/关键字）
   list_relations(project_id, source_type=None, target_type=None,
     relation_type=None, source=None, offset=0, limit=50) -> (list, total)
     —— router 恒传 offset/limit 关键字参数；过滤参数仅传有值者
   graph(project_id) -> KnowledgeGraphView
   get_relation(relation_id) -> KnowledgeRelation
   update_relation(relation_id, data: KnowledgeRelationUpdate) -> KnowledgeRelation
     （PATCH 参数断言用 await_args 解包 args[1] / kwargs['data']）
   delete_relation(relation_id) -> bool

4. 领域模型（inkflow.domain.models.knowledge_graph，工厂体内惰性 import）:
   KnowledgeRelation(id, project_id, source_type, source_id, target_type,
     target_id, relation_type, description='', source=RelationSource.MANUAL,
     created_at, updated_at)
   KnowledgeRelationCreate / KnowledgeRelationUpdate（全可选 exclude_unset）
   GraphNode(id, type, entity_id, name)  # id = f"{type}:{entity_id}"
   GraphEdge(id, source, target, label, description='', source_table)
   KnowledgeGraphView(nodes: list[GraphNode], edges: list[GraphEdge])

5. 错误类（inkflow.domain.ports.knowledge_graph_errors，默认消息文案逐字）:
   KnowledgeGraphServiceError(Exception) 基类（422 业务错误基类）
   KnowledgeRelationConflictError(KnowledgeGraphServiceError) 该关系已存在（同键唯一）
   KnowledgeRelationSelfLoopError(KnowledgeGraphServiceError) 关系两端不能是同一实体（自环）
   KnowledgeEntityNotFoundError(KnowledgeGraphServiceError)
     起点/终点实体不存在或不在同一项目（构造传 detail 指明 source/target 端 + 类型）
   KnowledgeRelationValidationError(KnowledgeGraphServiceError) 六元组非法（字段校验）
   KnowledgeRelationNotFoundError(Exception) 关系不存在（404）
   ProjectNotFoundError 复用 inkflow.domain.ports.world_errors → 404「项目不存在」

6. 响应形态: model_dump(mode='json')（id/project_id 等为字符串，枚举为值）。

依据: specs/f48-knowledge-graph/spec.md §3.1/§3.2/§3.3 + 父侧定稿契约（F48 #478）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

try:  # pragma: no cover - F48 RED: knowledge_graph_errors 尚未实现
    from inkflow.domain.ports.knowledge_graph_errors import (
        KnowledgeEntityNotFoundError,
        KnowledgeGraphServiceError,
        KnowledgeRelationConflictError,
        KnowledgeRelationNotFoundError,
        KnowledgeRelationSelfLoopError,
        KnowledgeRelationValidationError,
    )
except ImportError:
    KnowledgeGraphServiceError = type("KnowledgeGraphServiceError", (Exception,), {})
    KnowledgeRelationConflictError = type(
        "KnowledgeRelationConflictError", (KnowledgeGraphServiceError,), {}
    )
    KnowledgeRelationSelfLoopError = type(
        "KnowledgeRelationSelfLoopError", (KnowledgeGraphServiceError,), {}
    )
    KnowledgeEntityNotFoundError = type(
        "KnowledgeEntityNotFoundError", (KnowledgeGraphServiceError,), {}
    )
    KnowledgeRelationValidationError = type(
        "KnowledgeRelationValidationError", (KnowledgeGraphServiceError,), {}
    )
    KnowledgeRelationNotFoundError = type("KnowledgeRelationNotFoundError", (Exception,), {})

import inkflow.api.routers.knowledge_graph  # noqa: F401  # RED 阶段主契约 import（router 未实现 → 收

from inkflow.api.app import app
from inkflow.domain.ports.world_errors import ProjectNotFoundError

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
SRC_ID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")  # 起点实体（character）
TGT_ID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000003")  # 终点实体（world）
RID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000004")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _relation(**kw):
    """构造测试用关系实体（模型惰性 import——RED 阶段 models/knowledge_graph.py 未实现）。"""
    from inkflow.domain.models.knowledge_graph import KnowledgeRelation

    base = dict(
        id=RID,
        project_id=PID,
        source_type="character",
        source_id=SRC_ID,
        target_type="world",
        target_id=TGT_ID,
        relation_type="属于",
        description="林尘出身清河县",
        source="manual",
        created_at=TS,
        updated_at=TS,
    )
    base.update(kw)
    return KnowledgeRelation(**base)


def _graph_view(**kw):
    """构造测试用图谱聚合视图（模型惰性 import）。"""
    from inkflow.domain.models.knowledge_graph import (
        GraphEdge,
        GraphNode,
        KnowledgeGraphView,
    )

    base = dict(
        nodes=[
            GraphNode(
                id=f"character:{SRC_ID}",
                type="character",
                entity_id=SRC_ID,
                name="林尘",
            ),
            GraphNode(
                id=f"world:{TGT_ID}",
                type="world",
                entity_id=TGT_ID,
                name="清河县",
            ),
        ],
        edges=[
            GraphEdge(
                id=f"kr:{RID}",
                source=f"character:{SRC_ID}",
                target=f"world:{TGT_ID}",
                label="属于",
                description="林尘出身清河县",
                source_table="knowledge_relations",
            ),
        ],
    )
    base.update(kw)
    return KnowledgeGraphView(**base)


def _create_dto(**kw):
    """构造创建请求 DTO（模型惰性 import；字段等价比较用）。"""
    from inkflow.domain.models.knowledge_graph import KnowledgeRelationCreate

    base = dict(
        source_type="character",
        source_id=SRC_ID,
        target_type="world",
        target_id=TGT_ID,
        relation_type="属于",
        description="林尘出身清河县",
    )
    base.update(kw)
    return KnowledgeRelationCreate(**base)


def _update_dto(**kw):
    """构造更新请求 DTO（模型惰性 import；exclude_unset 语义）。"""
    from inkflow.domain.models.knowledge_graph import KnowledgeRelationUpdate

    return KnowledgeRelationUpdate(**kw)


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """构造默认可用的 Mock KnowledgeGraphService（被 await 方法逐用例显式赋 AsyncMock）。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    return svc


class TestKnowledgeRelationCreateAPI:
    """创建关系端点（POST /api/v1/projects/{project_id}/knowledge-relations）。"""

    @patch("inkflow.api.routers.knowledge_graph.get_knowledge_graph_service")
    def test_create_relation_success_201(self, mock_get_svc: MagicMock) -> None:
        """创建 character→world「属于」→ 201 完整关系 JSON（source 恒 manual，spec §3.2）。"""
        svc = _mock_svc(mock_get_svc)
        rel = _relation()
        svc.create_relation = AsyncMock(return_value=rel)

        response = client.post(
            f"/api/v1/projects/{PID}/knowledge-relations",
            json={
                "source_type": "character",
                "source_id": str(SRC_ID),
                "target_type": "world",
                "target_id": str(TGT_ID),
                "relation_type": "属于",
                "description": "林尘出身清河县",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == str(RID)
        assert data["project_id"] == str(PID)
        assert data["source_type"] == "character"
        assert data["source_id"] == str(SRC_ID)
        assert data["target_type"] == "world"
        assert data["target_id"] == str(TGT_ID)
        assert data["relation_type"] == "属于"
        assert data["description"] == "林尘出身清河县"
        assert data["source"] == "manual"
        assert data["created_at"] == TS.isoformat()
        assert data["updated_at"] == TS.isoformat()

        # F48 契约（F9 惯例）：router 解包 DTO 后调 service 展开字段（六元组以字符串/UUID 出现，
        # 非 DTO 透传——service 签名见兄弟文件 test_knowledge_graph_service.py）
        svc.create_relation.assert_awaited_once()
        call = svc.create_relation.await_args
        assert call.args[0] == PID  # project_id 恒位置第一参
        flat = [*call.args, *call.kwargs.values()]
        assert "character" in flat
        assert SRC_ID in flat
        assert "world" in flat
        assert TGT_ID in flat
        assert "属于" in flat
        assert "林尘出身清河县" in flat

    @patch("inkflow.api.routers.knowledge_graph.get_knowledge_graph_service")
    def test_create_relation_conflict_422(self, mock_get_svc: MagicMock) -> None:
        """同键重复创建 → 422 + detail「该关系已存在（同键唯一）」（spec §3.3/§7 边界 4）。"""
        svc = _mock_svc(mock_get_svc)
        svc.create_relation = AsyncMock(side_effect=KnowledgeRelationConflictError())

        response = client.post(
            f"/api/v1/projects/{PID}/knowledge-relations",
            json={
                "source_type": "character",
                "source_id": str(SRC_ID),
                "target_type": "world",
                "target_id": str(TGT_ID),
                "relation_type": "属于",
            },
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "该关系已存在（同键唯一）"

    @patch("inkflow.api.routers.knowledge_graph.get_knowledge_graph_service")
    def test_create_relation_self_loop_422(self, mock_get_svc: MagicMock) -> None:
        """自环（同类型同 id）→ 422 + detail「关系两端不能是同一实体（自环）」（§7 边界 3）。"""
        svc = _mock_svc(mock_get_svc)
        svc.create_relation = AsyncMock(side_effect=KnowledgeRelationSelfLoopError())

        response = client.post(
            f"/api/v1/projects/{PID}/knowledge-relations",
            json={
                "source_type": "character",
                "source_id": str(SRC_ID),
                "target_type": "character",
                "target_id": str(SRC_ID),
                "relation_type": "师徒",
            },
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "关系两端不能是同一实体（自环）"

    @patch("inkflow.api.routers.knowledge_graph.get_knowledge_graph_service")
    def test_create_relation_entity_not_found_422(self, mock_get_svc: MagicMock) -> None:
        """起点实体不存在 → 422 + detail 指明 source 端 + 类型（§3.3/§7 边界 1）。"""
        svc = _mock_svc(mock_get_svc)
        svc.create_relation = AsyncMock(
            side_effect=KnowledgeEntityNotFoundError("起点实体不存在或不在同一项目（character）")
        )

        response = client.post(
            f"/api/v1/projects/{PID}/knowledge-relations",
            json={
                "source_type": "character",
                "source_id": str(SRC_ID),
                "target_type": "world",
                "target_id": str(TGT_ID),
                "relation_type": "属于",
            },
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "起点实体不存在或不在同一项目" in detail
        assert "character" in detail

    @patch("inkflow.api.routers.knowledge_graph.get_knowledge_graph_service")
    def test_create_relation_validation_422(self, mock_get_svc: MagicMock) -> None:
        """六元组非法（service 抛 KnowledgeRelationValidationError）→ 422（§3.3）。"""
        svc = _mock_svc(mock_get_svc)
        svc.create_relation = AsyncMock(side_effect=KnowledgeRelationValidationError())

        response = client.post(
            f"/api/v1/projects/{PID}/knowledge-relations",
            json={
                "source_type": "character",
                "source_id": str(SRC_ID),
                "target_type": "world",
                "target_id": str(TGT_ID),
                "relation_type": "属于",
            },
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "六元组非法（字段校验）"

    @patch("inkflow.api.routers.knowledge_graph.get_knowledge_graph_service")
    def test_create_relation_project_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """项目不存在（ProjectNotFoundError，world_errors 复用）→ 404「项目不存在」（§3.3）。"""
        svc = _mock_svc(mock_get_svc)
        svc.create_relation = AsyncMock(side_effect=ProjectNotFoundError())

        response = client.post(
            f"/api/v1/projects/{PID}/knowledge-relations",
            json={
                "source_type": "character",
                "source_id": str(SRC_ID),
                "target_type": "world",
                "target_id": str(TGT_ID),
                "relation_type": "属于",
            },
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    def test_create_relation_invalid_project_uuid_404(self) -> None:
        """项目路径参数非法 UUID → 404「项目不存在」（_parse_id 惯例，create 不被调用）。"""
        response = client.post(
            "/api/v1/projects/not-a-uuid/knowledge-relations",
            json={
                "source_type": "character",
                "source_id": str(SRC_ID),
                "target_type": "world",
                "target_id": str(TGT_ID),
                "relation_type": "属于",
            },
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"


class TestKnowledgeRelationListAPI:
    """关系列表端点（GET /api/v1/projects/{project_id}/knowledge-relations）。"""

    @patch("inkflow.api.routers.knowledge_graph.get_knowledge_graph_service")
    def test_list_relations_default(self, mock_get_svc: MagicMock) -> None:
        """缺省列表 → 200 {items, total, offset, limit} + list_relations(pid, offset=0,
        limit=50)。"""
        svc = _mock_svc(mock_get_svc)
        svc.list_relations = AsyncMock(return_value=([_relation()], 1))

        response = client.get(f"/api/v1/projects/{PID}/knowledge-relations")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["offset"] == 0
        assert data["limit"] == 50
        assert data["items"][0]["relation_type"] == "属于"
        svc.list_relations.assert_awaited_once_with(PID, offset=0, limit=50)

    @patch("inkflow.api.routers.knowledge_graph.get_knowledge_graph_service")
    def test_list_relations_filters(self, mock_get_svc: MagicMock) -> None:
        """过滤参数 ?source_type=&target_type=&relation_type=&source= → kwargs 透传（§3.1）。"""
        svc = _mock_svc(mock_get_svc)
        svc.list_relations = AsyncMock(return_value=([], 0))

        response = client.get(
            f"/api/v1/projects/{PID}/knowledge-relations",
            params={
                "source_type": "character",
                "target_type": "world",
                "relation_type": "属于",
                "source": "ai",
                "offset": 10,
                "limit": 5,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["offset"] == 10
        assert data["limit"] == 5
        svc.list_relations.assert_awaited_once_with(
            PID,
            source_type="character",
            target_type="world",
            relation_type="属于",
            source="ai",
            offset=10,
            limit=5,
        )


class TestKnowledgeGraphAPI:
    """图谱聚合查询端点（GET /api/v1/projects/{project_id}/knowledge-graph）。"""

    @patch("inkflow.api.routers.knowledge_graph.get_knowledge_graph_service")
    def test_get_graph_merged_sources(self, mock_get_svc: MagicMock) -> None:
        """图谱聚合 → 200 {nodes, edges} 形状（节点/边按 spec §2.4，双来源 source_table）。"""
        svc = _mock_svc(mock_get_svc)
        from inkflow.domain.models.knowledge_graph import GraphEdge

        view = _graph_view(
            edges=[
                _graph_view().edges[0],
                GraphEdge(
                    id="cr:5",
                    source="character:7b2d0000-0000-4000-8000-000000000005",
                    target="character:7b2d0000-0000-4000-8000-000000000006",
                    label="师徒",
                    description="",
                    source_table="character_relations",
                ),
            ]
        )
        svc.graph = AsyncMock(return_value=view)

        response = client.get(f"/api/v1/projects/{PID}/knowledge-graph")
        assert response.status_code == 200
        data = response.json()
        assert set(data.keys()) == {"nodes", "edges"}
        assert len(data["nodes"]) == 2
        node = data["nodes"][0]
        assert node["id"] == f"character:{SRC_ID}"
        assert node["type"] == "character"
        assert node["entity_id"] == str(SRC_ID)
        assert node["name"] == "林尘"
        assert len(data["edges"]) == 2
        assert data["edges"][0]["source_table"] == "knowledge_relations"
        assert data["edges"][0]["source"] == f"character:{SRC_ID}"
        assert data["edges"][0]["target"] == f"world:{TGT_ID}"
        assert data["edges"][0]["label"] == "属于"
        assert data["edges"][1]["source_table"] == "character_relations"
        assert data["edges"][1]["label"] == "师徒"
        svc.graph.assert_awaited_once_with(PID)

    @patch("inkflow.api.routers.knowledge_graph.get_knowledge_graph_service")
    def test_get_graph_empty(self, mock_get_svc: MagicMock) -> None:
        """空项目图谱 → 200 {"nodes": [], "edges": []}（§7 边界 14）。"""
        svc = _mock_svc(mock_get_svc)
        svc.graph = AsyncMock(return_value=_graph_view(nodes=[], edges=[]))

        response = client.get(f"/api/v1/projects/{PID}/knowledge-graph")
        assert response.status_code == 200
        assert response.json() == {"nodes": [], "edges": []}


class TestKnowledgeRelationGetAPI:
    """关系详情端点（GET /api/v1/knowledge-relations/{relation_id}）。"""

    @patch("inkflow.api.routers.knowledge_graph.get_knowledge_graph_service")
    def test_get_relation_success(self, mock_get_svc: MagicMock) -> None:
        """关系详情返回 200 + KnowledgeRelation JSON。"""
        svc = _mock_svc(mock_get_svc)
        rel = _relation()
        svc.get_relation = AsyncMock(return_value=rel)

        response = client.get(f"/api/v1/knowledge-relations/{RID}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(RID)
        assert data["relation_type"] == "属于"
        assert data["source"] == "manual"
        svc.get_relation.assert_awaited_once_with(RID)

    @patch("inkflow.api.routers.knowledge_graph.get_knowledge_graph_service")
    def test_get_relation_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """关系不存在 → 404 + detail「关系不存在」（§3.3/§7 边界 8）。"""
        svc = _mock_svc(mock_get_svc)
        svc.get_relation = AsyncMock(side_effect=KnowledgeRelationNotFoundError())

        response = client.get(f"/api/v1/knowledge-relations/{RID}")
        assert response.status_code == 404
        assert response.json()["detail"] == "关系不存在"

    def test_get_relation_invalid_uuid_404(self) -> None:
        """非法 UUID → 404「关系不存在」（_parse_id detail 锁定，get_relation 不被调用）。"""
        response = client.get("/api/v1/knowledge-relations/not-a-uuid")
        assert response.status_code == 404
        assert response.json()["detail"] == "关系不存在"


class TestKnowledgeRelationUpdateAPI:
    """更新关系端点（PATCH /api/v1/knowledge-relations/{relation_id}）。"""

    @patch("inkflow.api.routers.knowledge_graph.get_knowledge_graph_service")
    def test_update_relation_success(self, mock_get_svc: MagicMock) -> None:
        """PATCH {"relation_type": "出身"} → 200 更新后关系（exclude_unset 语义，§3.2）。"""
        svc = _mock_svc(mock_get_svc)
        rel = _relation(relation_type="出身")
        svc.update_relation = AsyncMock(return_value=rel)

        response = client.patch(
            f"/api/v1/knowledge-relations/{RID}", json={"relation_type": "出身"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(RID)
        assert data["relation_type"] == "出身"

        svc.update_relation.assert_awaited_once()
        call = svc.update_relation.await_args
        assert call.args[0] == RID  # relation_id 恒位置第一参
        # F48 契约（F9 惯例）：router 解包 DTO 调 service 展开字段；未传字段不出现（exclude_unset）
        flat = [*call.args, *call.kwargs.values()]
        assert "出身" in flat
        assert "description" not in call.kwargs  # 未传字段不动（exclude_unset 语义）


class TestKnowledgeRelationDeleteAPI:
    """删除关系端点（DELETE /api/v1/knowledge-relations/{relation_id}，真删）。"""

    @patch("inkflow.api.routers.knowledge_graph.get_knowledge_graph_service")
    def test_delete_relation_success_204(self, mock_get_svc: MagicMock) -> None:
        """真删关系 → 204 空 body（§3.2/§7 真删语义）。"""
        svc = _mock_svc(mock_get_svc)
        svc.delete_relation = AsyncMock(return_value=True)

        response = client.delete(f"/api/v1/knowledge-relations/{RID}")
        assert response.status_code == 204
        assert response.content == b""
        svc.delete_relation.assert_awaited_once_with(RID)

    @patch("inkflow.api.routers.knowledge_graph.get_knowledge_graph_service")
    def test_delete_relation_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """关系不存在 → 404 + detail「关系不存在」（§3.3/§7 边界 8）。"""
        svc = _mock_svc(mock_get_svc)
        svc.delete_relation = AsyncMock(side_effect=KnowledgeRelationNotFoundError())

        response = client.delete(f"/api/v1/knowledge-relations/{RID}")
        assert response.status_code == 404
        assert response.json()["detail"] == "关系不存在"
