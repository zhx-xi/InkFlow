"""#479 定时知识图谱提取 API 契约测试（TDD RED 阶段，只写测试不改 src/）。

被测 router: inkflow.api.routers.knowledge_graph（F48 已交付 6 端点；#479 追加
POST /knowledge/extract + GET /knowledge/extract/status 两个端点，spec §5.5.6）。
镜像 backend/tests/unit/test_knowledge_graph_api.py（F48）模块级 TestClient 形态；
#479 新依赖（get_relation_extraction_service / get_kg_extract_scheduler）RED 期
在 deps 尚不存在 → 用 app.dependency_overrides + fixture 内惰性 import（镜像
test_books_api_background.py F44 形态）——【RED 形态】每用例 fixture setup
ImportError（「依赖 getter 失败」，父侧定稿允许）；守护用例当前 PASS。

【统一契约签名节】（父侧定稿，与 unit 批共享防漂移——mock 断言必须逐字匹配）:

1) POST /api/v1/knowledge/extract（knowledge_graph.py router 追加，tags 不变）:
   - 请求体 {'project_id': '<uuid-str>', 'method'?: 'rule'|'ai'|'both'}；
     method 缺省 = 跟随 settings（端点读 settings_service.get_settings().kg_extract_method）
   - 端点调用链: 依赖注入 RelationExtractionService（deps.get_relation_extraction_service）
     → await svc.extract_for_project(project_id=UUID(...), method=<str>)
     （Keyword 调用，断言 call.args[0] + kwargs 值集合 flat 形态兼容）
   - 200 → ExtractionResult.model_dump() 形态
     （type/status/created/updated/warnings/model/skipped_reason）
   - 404: svc 抛项目不存在错误（ProjectNotFoundError，world_errors 复用——
     镜像 knowledge_graph.py 现有 _run_service 404 映射）
   - 422: svc 抛 LLMNotConfiguredError（knowledge_graph_errors.py 追加，RED 期
     不存在 → 本文件 try/except stub，GREEN 落地后 try 走真实类）
   - 422: method 非法值（'foo'）→ Pydantic Literal 校验
   - 422: 运行中（svc 抛 ValueError('提取正在进行')）→ 422
     （F44 prepare_run 守卫同款语义）

2) GET /api/v1/knowledge/extract/status:
   - 200 → {'running': bool, 'last_run': {'status','created','run_at'} | None}
   - 注入点定稿: KnowledgeExtractScheduler（deps.get_kg_extract_scheduler 装配，
     spec §5.5.3）；scheduler 最小表面 = is_running: bool（F44
     spawn_background_task key 注册表语义）+ last_run: dict | None（最近一次
     knowledge_relation run 摘要 {status, created, run_at}，调度器维护/汇总——
     spec §5.5.3 未列，属 #479 status 端点支撑属性，unit 批不冲突）

【GREEN 装配契约】router 函数签名需含依赖参数名:
  async def extract_knowledge(data: KnowledgeExtractRequest, ...,
      svc: RelationExtractionService = Depends(get_relation_extraction_service),
      settings: SettingsService = Depends(get_settings_service))
  async def extract_status(
      scheduler: KnowledgeExtractScheduler = Depends(get_kg_extract_scheduler))
测试经 app.dependency_overrides 注入 mock（override key = router 模块
from-import 绑定的 deps getter 对象，镜像 test_books_api_background.py）。

【守护】test_get_graph_smoke_guardian 命中既有 F48 端点（当前 PASS）。

依据: specs/f48-knowledge-graph/spec.md §5.5.6/§5.5.8（v1.2 定稿契约，唯一真相）
+ 父侧定稿统一契约签名节（#479）。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.api.deps import get_settings_service
from inkflow.domain.ports.world_errors import ProjectNotFoundError

try:  # pragma: no cover - #479 RED: LLMNotConfiguredError 尚未追加到 knowledge_graph_errors
    from inkflow.domain.ports.knowledge_graph_errors import LLMNotConfiguredError
except ImportError:  # pragma: no cover - RED stub，GREEN 落地后自动消解
    LLMNotConfiguredError = type("LLMNotConfiguredError", (Exception,), {})

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


def _extract_result(**overrides: object) -> dict:
    """构造测试用提取结果 JSON dict（ExtractionResult.model_dump(mode='json') 等价物）。

    #479 契约字段: type/status/created/updated/warnings/model/skipped_reason
    （F14 ExtractionResult 全量 11 字段形状，type=knowledge_relation，spec §5.5.5）。
    """
    defaults = dict(
        type="knowledge_relation",
        status="success",
        skipped_reason=None,
        processed_sources=2,
        skipped_sources=0,
        created=3,
        updated=0,
        warnings=[],
        model=None,
        indexed=False,
        detail={},
    )
    defaults.update(overrides)
    return defaults


def _last_run(**overrides: object) -> dict:
    """构造最近一次 run 摘要 dict（status 端点 last_run 形状，spec §5.5.6）。"""
    defaults = {
        "status": "success",
        "created": 3,
        "run_at": "2026-08-19T10:00:00",
    }
    defaults.update(overrides)
    return defaults


@pytest.fixture
def override_extract_deps(override_get_db):
    """注入 mock RelationExtractionService + SettingsService（dependency_overrides）。

    【RED 形态】get_relation_extraction_service 在 deps 尚不存在 → fixture 内
    from inkflow.api.routers.knowledge_graph import get_relation_extraction_service
    抛 ImportError → 全部契约用例 fixture setup ERROR（「依赖 getter 失败」，
    父侧定稿允许的 RED 形态之一）；守护用例不依赖本 fixture，当前 PASS。

    【GREEN 装配契约】router 签名含
    svc: RelationExtractionService = Depends(get_relation_extraction_service) +
    settings: SettingsService = Depends(get_settings_service)。
    """
    from inkflow.api.routers.knowledge_graph import get_relation_extraction_service

    svc = MagicMock()
    settings = MagicMock()
    settings.get_settings.return_value = SimpleNamespace(kg_extract_method="rule")
    app.dependency_overrides[get_relation_extraction_service] = lambda: svc
    app.dependency_overrides[get_settings_service] = lambda: settings
    yield svc, settings
    app.dependency_overrides.pop(get_relation_extraction_service, None)
    app.dependency_overrides.pop(get_settings_service, None)


@pytest.fixture
def override_scheduler(override_get_db):
    """注入 mock KnowledgeExtractScheduler（dependency_overrides）。

    【RED 形态】同 override_extract_deps: get_kg_extract_scheduler 尚不存在 →
    fixture setup ImportError（「依赖 getter 失败」）。

    【GREEN 装配契约】router 签名含
    scheduler: KnowledgeExtractScheduler = Depends(get_kg_extract_scheduler)。
    """
    from inkflow.api.routers.knowledge_graph import get_kg_extract_scheduler

    scheduler = MagicMock()
    scheduler.is_running = False
    scheduler.last_run = None
    app.dependency_overrides[get_kg_extract_scheduler] = lambda: scheduler
    yield scheduler
    app.dependency_overrides.pop(get_kg_extract_scheduler, None)


class TestKnowledgeExtractAPI:
    """POST /api/v1/knowledge/extract —— 手动触发提取（spec §5.5.6）。

    统一契约: svc.extract_for_project(project_id=UUID(...), method=<str>)。
    """

    def test_extract_success_default_method_follows_settings(
        self, override_extract_deps
    ) -> None:
        """method 缺省 → 端点读 settings.kg_extract_method（mock='rule'）透传给 svc。

        200 + ExtractionResult.model_dump() 形态；svc.extract_for_project 收到
        project_id=UUID + method='rule'（flat 形态兼容断言）。
        """
        svc, _settings = override_extract_deps
        svc.extract_for_project = AsyncMock(return_value=_extract_result())

        response = client.post(
            "/api/v1/knowledge/extract",
            json={"project_id": str(PID)},
        )
        assert response.status_code == 200
        data = response.json()
        contract_keys = {
            "type",
            "status",
            "created",
            "updated",
            "warnings",
            "model",
            "skipped_reason",
        }
        assert contract_keys <= set(data)
        assert data["type"] == "knowledge_relation"
        assert data["status"] == "success"
        assert data["created"] == 3
        assert data["updated"] == 0

        svc.extract_for_project.assert_awaited_once()
        call = svc.extract_for_project.await_args
        flat = [*call.args, *call.kwargs.values()]
        assert PID in flat
        assert "rule" in flat
        if "project_id" in call.kwargs:
            assert call.kwargs["project_id"] == PID
        if "method" in call.kwargs:
            assert call.kwargs["method"] == "rule"

    def test_extract_success_with_method_ai(self, override_extract_deps) -> None:
        """显式 method='ai' → 透传 svc.extract_for_project(method='ai')。"""
        svc, _settings = override_extract_deps
        svc.extract_for_project = AsyncMock(return_value=_extract_result())

        response = client.post(
            "/api/v1/knowledge/extract",
            json={"project_id": str(PID), "method": "ai"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["created"] == 3

        svc.extract_for_project.assert_awaited_once()
        call = svc.extract_for_project.await_args
        flat = [*call.args, *call.kwargs.values()]
        assert PID in flat
        assert "ai" in flat
        if "method" in call.kwargs:
            assert call.kwargs["method"] == "ai"

    def test_extract_llm_not_configured_422(self, override_extract_deps) -> None:
        """svc 抛 LLMNotConfiguredError（未配置模型）→ 422，detail 指明（spec §5.5.6）。"""
        svc, _settings = override_extract_deps
        svc.extract_for_project = AsyncMock(
            side_effect=LLMNotConfiguredError("未配置大模型，无法进行 AI 提取")
        )

        response = client.post(
            "/api/v1/knowledge/extract",
            json={"project_id": str(PID), "method": "ai"},
        )
        assert response.status_code == 422
        assert "未配置" in response.json()["detail"]

    def test_extract_project_not_found_404(self, override_extract_deps) -> None:
        """svc 抛 ProjectNotFoundError → 404「项目不存在」（_run_service 既有映射）。"""
        svc, _settings = override_extract_deps
        svc.extract_for_project = AsyncMock(side_effect=ProjectNotFoundError())

        response = client.post(
            "/api/v1/knowledge/extract",
            json={"project_id": str(PID)},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    def test_extract_invalid_method_422(self, override_extract_deps) -> None:
        """method 非法值（'foo'）→ Pydantic Literal 校验 422（spec §5.5.6）。"""
        response = client.post(
            "/api/v1/knowledge/extract",
            json={"project_id": str(PID), "method": "foo"},
        )
        assert response.status_code == 422

    def test_extract_running_guard_422(self, override_extract_deps) -> None:
        """运行中（svc 抛 ValueError('提取正在进行')）→ 422「提取正在进行」。

        F44 prepare_run 守卫同款语义: ValueError 详情含「不存在」→ 404，否则 → 422。
        """
        svc, _settings = override_extract_deps
        svc.extract_for_project = AsyncMock(side_effect=ValueError("提取正在进行"))

        response = client.post(
            "/api/v1/knowledge/extract",
            json={"project_id": str(PID)},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "提取正在进行"


class TestKnowledgeExtractStatusAPI:
    """GET /api/v1/knowledge/extract/status —— 运行状态 + 最近一次 run 摘要。

    统一契约: 200 → {'running': bool, 'last_run': {'status','created','run_at'} | None}。
    """

    def test_status_running_with_last_run(self, override_scheduler) -> None:
        """运行中 + 有最近 run → {'running': True, 'last_run': {...}}。"""
        scheduler = override_scheduler
        scheduler.is_running = True
        scheduler.last_run = _last_run()

        response = client.get("/api/v1/knowledge/extract/status")
        assert response.status_code == 200
        body = response.json()
        assert body == {"running": True, "last_run": _last_run()}

    def test_status_idle_no_last_run(self, override_scheduler) -> None:
        """空闲 + 无 run 记录 → {'running': False, 'last_run': None}。"""
        response = client.get("/api/v1/knowledge/extract/status")
        assert response.status_code == 200
        assert response.json() == {"running": False, "last_run": None}


class TestKnowledgeGraphGuardian:
    """守护用例（当前 PASS）——既有 F48 端点冒烟，验证测试夹具可用。"""

    @patch("inkflow.api.routers.knowledge_graph.get_knowledge_graph_service")
    def test_get_graph_smoke_guardian(
        self, mock_get_svc: MagicMock, override_get_db
    ) -> None:
        """知识图谱聚合端点冒烟（F48 已交付，RED 期即 PASS）。"""
        from inkflow.domain.models.knowledge_graph import KnowledgeGraphView

        svc = MagicMock()
        mock_get_svc.return_value = svc
        svc.graph = AsyncMock(return_value=KnowledgeGraphView(nodes=[], edges=[]))

        response = client.get(f"/api/v1/projects/{PID}/knowledge-graph")
        assert response.status_code == 200
        assert response.json() == {"nodes": [], "edges": []}
