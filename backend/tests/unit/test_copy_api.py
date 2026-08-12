"""F37 世界观跨书复制 API 层测试 — Mock WorldCopyService（RED 阶段，只写测试不改 src/）.

被测 router: inkflow.api.routers.world_settings（F10/F35 端点已 GREEN；copy 端点
与 get_copy_service 装配缝尚未实现）。镜像 tests/unit/test_map_api.py 形态：
模块级 TestClient(app) + @patch("inkflow.api.routers.world_settings.get_copy_service")
+ _mock_svc helper；被 await 的 svc.copy 逐用例显式赋 AsyncMock。

【RED 预期】
router 模块已存在 → 顶部 straight import 收集成功（非 F36 整模块缺失形态）；
但模块当前无 get_copy_service 属性 → 每用例 patch setup 抛 AttributeError
（<module 'inkflow.api.routers.world_settings'> does not have the attribute
'get_copy_service'）= 8 用例全部 ERROR 同根因（mock 目标迁移批 1g 形态，
exit 1 为预期终态），父侧确认 RED 时勿误判为测试写错。GREEN 后装配缝落地
自动转绿，断言无需改动。

【设计假设——父侧定稿契约，GREEN 实现按此逐字落地】

1. world_settings.py 新增端点（与 extract 同区，注册在
   /world-settings/{setting_id} 之前，spec §3.1 路由顺序）:
   @router.post("/projects/{target_project_id}/world-settings/copy")
   async def copy_world_settings(target_project_id: str,
       request: WorldCopyRequest, db: AsyncSession = Depends(get_db)):
       tpid = _parse_id(target_project_id, detail="项目不存在")
       svc = _get_copy_svc(db)   # 新装配缝（patch 目标
                                 # inkflow.api.routers.world_settings.get_copy_service）
       result = await _run_service(
           svc.copy(request.source_project_id, tpid, request.root_setting_id))
       return result.model_dump(mode="json")

2. _run_service 错误映射扩展（新增两个 except，str(e) 即 detail）:
   - CopySourceNotFoundError → 404「源项目不存在」
   - CopyRootNotFoundError → 404「复制起点条目不存在或不在源项目」
   - ProjectNotFoundError → 404（既有映射，detail「项目不存在」）

3. deps.py 新增装配缝:
   def get_copy_service(db: AsyncSession) -> WorldCopyService: 装配
   WorldCopyService(repository=SQLiteWorldRepository(db),
   project_repo=SQLiteProjectRepository(db),
   map_repo=SQLiteMapRepository(db),
   asset_store=LocalMapAssetStore(config.data_dir))

4. 领域模型（inkflow.domain.models.copy，工厂体内惰性 import）:
   WorldCopyRequest(source_project_id: uuid.UUID,
       root_setting_id: uuid.UUID | None = None)      # None = 整棵复制
   WorldCopyResult(created: list[WorldSetting], skipped: list[str],
       maps_created: list[WorldMap], pins_created: int, warnings: list[str])
   本文件不直接构造 WorldCopyRequest（body 走原始 JSON），仅 WorldCopyResult
   惰性 import。

5. 错误类（world_errors.py 新增，COPY 前缀；模块级 try/except stub 置于
   主 import 之前，吞掉自身 ImportError 后收集继续）:
   CopySourceNotFoundError(Exception)   默认消息「源项目不存在」
   CopyRootNotFoundError(Exception)     默认消息「复制起点条目不存在或不在源项目」
   ProjectNotFoundError 复用既有 world_errors（顶部 import，非 stub）

6. 响应形态: result.model_dump(mode="json")，五键齐全
   created/skipped/maps_created/pins_created/warnings（宽松断言：
   created 元素含 name 键、pins_created 为 int、warnings 为 list）。
   svc.copy 调用形态 = 三位置参数 (source_project_id, tpid,
   root_setting_id)，source 由 Pydantic 解析、target 由 _parse_id 解析为 UUID。

依据: specs/f37-world-copy/spec.md §3/§13 M5 + 父侧定稿契约（F37 #175）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

try:
    from inkflow.domain.ports.world_errors import (
        CopyRootNotFoundError,
        CopySourceNotFoundError,
    )
except ImportError:  # pragma: no cover - F37 RED: copy 错误类尚未实现
    CopySourceNotFoundError = type("CopySourceNotFoundError", (Exception,), {})
    CopyRootNotFoundError = type("CopyRootNotFoundError", (Exception,), {})

import inkflow.api.routers.world_settings  # noqa: F401  # 主契约模块（router 已存在 → 收集成功）
from inkflow.api.app import app
from inkflow.domain.models.map import WorldMap
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.world_errors import ProjectNotFoundError

client = TestClient(app)

SOURCE_PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
TARGET_PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")
ROOT_ID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000003")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _setting(pid: uuid.UUID, name: str = "大越国", **kw):
    """构造测试用世界观条目（WorldSetting 为既有 F10 模型，顶部可解析）。"""
    base = dict(
        id=uuid.uuid4(),
        project_id=pid,
        name=name,
        parent_id=None,
        category="地理",
        content="",
        created_at=TS,
        updated_at=TS,
    )
    base.update(kw)
    return WorldSetting(**base)


def _map(pid: uuid.UUID, name: str = "清河县城图", **kw):
    """构造测试用地图实体（WorldMap 为既有 F36 模型，顶部可解析）。"""
    base = dict(
        id=uuid.uuid4(),
        project_id=pid,
        name=name,
        image_path="maps/main.png",
        description="",
        root_location_id=None,
        created_at=TS,
        updated_at=TS,
    )
    base.update(kw)
    return WorldMap(**base)


def _result(**kw):
    """构造测试用复制结果（WorldCopyResult 惰性 import——RED 阶段 copy.py 未实现）.

    返回对象经 router model_dump(mode="json") 序列化：id/project_id 为字符串。
    """
    from inkflow.domain.models.copy import WorldCopyResult

    base = dict(
        created=[_setting(TARGET_PID)],
        skipped=[],
        maps_created=[_map(TARGET_PID)],
        pins_created=7,
        warnings=[],
    )
    base.update(kw)
    return WorldCopyResult(**base)


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """构造默认可用的 Mock WorldCopyService（被 await 方法逐用例显式赋 AsyncMock）。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    return svc


class TestWorldCopyAPI:
    """世界观跨书复制端点（POST /api/v1/projects/{target}/world-settings/copy）。"""

    @patch("inkflow.api.routers.world_settings.get_copy_service")
    def test_copy_success(self, mock_get_svc: MagicMock) -> None:
        """整棵复制成功 → 200 + 报告五键齐全；copy 收到解析后的 (source, target, None)."""
        svc = _mock_svc(mock_get_svc)
        svc.copy = AsyncMock(return_value=_result())

        response = client.post(
            f"/api/v1/projects/{TARGET_PID}/world-settings/copy",
            json={"source_project_id": str(SOURCE_PID), "root_setting_id": None},
        )
        assert response.status_code == 200
        data = response.json()
        for key in ("created", "skipped", "maps_created", "pins_created", "warnings"):
            assert key in data
        assert data["created"][0]["name"] == "大越国"
        assert data["maps_created"][0]["name"] == "清河县城图"
        assert isinstance(data["pins_created"], int)
        assert isinstance(data["warnings"], list)
        svc.copy.assert_awaited_once_with(SOURCE_PID, TARGET_PID, None, self_only=False)

    @patch("inkflow.api.routers.world_settings.get_copy_service")
    def test_copy_without_root_key(self, mock_get_svc: MagicMock) -> None:
        """body 无 root_setting_id 键（缺省整棵）→ copy(..., None) 被调用."""
        svc = _mock_svc(mock_get_svc)
        svc.copy = AsyncMock(return_value=_result())

        response = client.post(
            f"/api/v1/projects/{TARGET_PID}/world-settings/copy",
            json={"source_project_id": str(SOURCE_PID)},
        )
        assert response.status_code == 200
        svc.copy.assert_awaited_once_with(SOURCE_PID, TARGET_PID, None, self_only=False)

    @patch("inkflow.api.routers.world_settings.get_copy_service")
    def test_copy_with_root(self, mock_get_svc: MagicMock) -> None:
        """提供 root_setting_id → copy(..., ROOT_ID)（子树复制起点解析为 UUID）."""
        svc = _mock_svc(mock_get_svc)
        svc.copy = AsyncMock(return_value=_result())

        response = client.post(
            f"/api/v1/projects/{TARGET_PID}/world-settings/copy",
            json={"source_project_id": str(SOURCE_PID), "root_setting_id": str(ROOT_ID)},
        )
        assert response.status_code == 200
        svc.copy.assert_awaited_once_with(SOURCE_PID, TARGET_PID, ROOT_ID, self_only=False)

    @patch("inkflow.api.routers.world_settings.get_copy_service")
    def test_copy_target_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """目标项目不存在（ProjectNotFoundError，world_errors 复用）→ 404「项目不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.copy = AsyncMock(side_effect=ProjectNotFoundError())

        response = client.post(
            f"/api/v1/projects/{TARGET_PID}/world-settings/copy",
            json={"source_project_id": str(SOURCE_PID), "root_setting_id": None},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    @patch("inkflow.api.routers.world_settings.get_copy_service")
    def test_copy_source_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """源项目不存在（CopySourceNotFoundError）→ 404「源项目不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.copy = AsyncMock(side_effect=CopySourceNotFoundError())

        response = client.post(
            f"/api/v1/projects/{TARGET_PID}/world-settings/copy",
            json={"source_project_id": str(SOURCE_PID), "root_setting_id": None},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "源项目不存在"

    @patch("inkflow.api.routers.world_settings.get_copy_service")
    def test_copy_root_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """复制起点不存在/不在源项目（CopyRootNotFoundError）→ 404 精确文案."""
        svc = _mock_svc(mock_get_svc)
        svc.copy = AsyncMock(side_effect=CopyRootNotFoundError())

        response = client.post(
            f"/api/v1/projects/{TARGET_PID}/world-settings/copy",
            json={"source_project_id": str(SOURCE_PID), "root_setting_id": str(ROOT_ID)},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "复制起点条目不存在或不在源项目"

    @patch("inkflow.api.routers.world_settings.get_copy_service")
    def test_copy_route_order(self, mock_get_svc: MagicMock) -> None:
        """路由顺序: /world-settings/copy 命中 copy 端点（200 即证明，spec §3.1）."""
        svc = _mock_svc(mock_get_svc)
        svc.copy = AsyncMock(return_value=_result())

        response = client.post(
            f"/api/v1/projects/{TARGET_PID}/world-settings/copy",
            json={"source_project_id": str(SOURCE_PID)},
        )
        assert response.status_code == 200
        assert response.json()["created"][0]["name"] == "大越国"

    @patch("inkflow.api.routers.world_settings.get_copy_service")
    def test_copy_invalid_target_uuid_404(self, mock_get_svc: MagicMock) -> None:
        """无效 target UUID → 404「项目不存在」且 copy 不被调用（_parse_id 先行）."""
        svc = _mock_svc(mock_get_svc)
        svc.copy = AsyncMock(return_value=_result())

        response = client.post(
            "/api/v1/projects/abc/world-settings/copy",
            json={"source_project_id": str(SOURCE_PID), "root_setting_id": None},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"
        svc.copy.assert_not_awaited()

    def test_get_copy_service_assembles_real_deps(self) -> None:
        """真实 deps 装配: get_copy_service(AsyncMock()) → WorldCopyService 实例."""
        from inkflow.api.deps import get_copy_service
        from inkflow.domain.services.copy_service import WorldCopyService

        svc = get_copy_service(AsyncMock())

        assert isinstance(svc, WorldCopyService)


class TestWorldCopySelfOnly:
    """F43 P1 复制 self_only 契约（spec §2.5/§3.3）— 透传 + root 缺省互斥 422.

    【RED 预期】WorldCopyRequest 尚无 self_only 字段 → body self_only 被 Pydantic
    忽略 → 断言收到调用缺 self_only kwarg（AssertionError）/ 互斥校验缺失返回
    200 而非 422（AssertionError）= 断言失败形态。契约锁定: svc.copy 第 4 参以
    kwargs 形态透传（self_only=request.self_only）。
    """

    @patch("inkflow.api.routers.world_settings.get_copy_service")
    def test_copy_self_only_true_passed(self, mock_get_svc: MagicMock) -> None:
        """body 带 root + self_only=true → svc.copy 收到 self_only=True."""
        svc = _mock_svc(mock_get_svc)
        svc.copy = AsyncMock(return_value=_result())

        response = client.post(
            f"/api/v1/projects/{TARGET_PID}/world-settings/copy",
            json={
                "source_project_id": str(SOURCE_PID),
                "root_setting_id": str(ROOT_ID),
                "self_only": True,
            },
        )
        assert response.status_code == 200
        svc.copy.assert_awaited_once_with(SOURCE_PID, TARGET_PID, ROOT_ID, self_only=True)

    @patch("inkflow.api.routers.world_settings.get_copy_service")
    def test_copy_self_only_without_root_422(self, mock_get_svc: MagicMock) -> None:
        """body 带 self_only=true 但 root_setting_id 缺省（None）→ 422 互斥（spec §3.3 表）."""
        svc = _mock_svc(mock_get_svc)
        svc.copy = AsyncMock(return_value=_result())

        response = client.post(
            f"/api/v1/projects/{TARGET_PID}/world-settings/copy",
            json={"source_project_id": str(SOURCE_PID), "self_only": True},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "仅本体复制必须指定复制起点"
        svc.copy.assert_not_awaited()

    @patch("inkflow.api.routers.world_settings.get_copy_service")
    def test_copy_self_only_defaults_false(self, mock_get_svc: MagicMock) -> None:
        """body 无 self_only 键 → svc.copy 收到 self_only=False（缺省，向后兼容）."""
        svc = _mock_svc(mock_get_svc)
        svc.copy = AsyncMock(return_value=_result())

        response = client.post(
            f"/api/v1/projects/{TARGET_PID}/world-settings/copy",
            json={"source_project_id": str(SOURCE_PID), "root_setting_id": str(ROOT_ID)},
        )
        assert response.status_code == 200
        svc.copy.assert_awaited_once_with(SOURCE_PID, TARGET_PID, ROOT_ID, self_only=False)
