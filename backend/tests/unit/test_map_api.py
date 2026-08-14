"""F36 地图 API 层测试 — Mock MapService（RED 阶段，只写测试不改 src/）.

被测 router: inkflow.api.routers.maps（整模块尚未实现——本文件为 RED 契约）。
镜像 tests/unit/test_world_api.py（F10/F35）形态: 模块级 TestClient(app) +
@patch("inkflow.api.routers.maps.get_map_service") + _mock_svc helper +
用例类分组；每个被路由 await 的服务方法显式赋 AsyncMock（未赋值的同步
MagicMock 子 mock 被 await 会返回 coroutine 导致 500，F4 4.1 实测陷阱）。

【RED 预期】
收集期 ModuleNotFoundError: No module named 'inkflow.api.routers.maps'
（router 未实现，collected 0 items / exit 2）= 正确 RED 终态，父侧亲自确认。
models/map.py 与 map_errors 模块同批缺失 → 领域模型在工厂函数体内惰性
import（不参与顶部收集错误）；map_errors 用模块级 try/except stub（置于主
import 之前，吞掉自身 ImportError，收集错误唯一聚焦主契约 router；GREEN
落地后 try 走真实类、stub 自动消解）。

【设计假设——父侧定稿契约，GREEN 实现按此逐字落地】

1. 被测模块 inkflow.api.routers.maps（整模块未实现）:
   router = APIRouter(prefix='/api/v1', tags=['地图'])
   - _parse_id(id_str, detail='资源不存在'): UUID 或 int 解析，非法 → 404；
     地图端点传 detail='地图不存在'、pin 端点传 'pin 不存在'（非法 UUID 的
     404 detail 按端点语义锁定，同 world_settings.py 惯例）
   - _get_svc(db) → get_map_service(db)（patch 目标）
   - _run_service(coro) catch 链: MapServiceError 子类 → 422（str(e) 即
     detail）；MapNotFoundError / MapPinNotFoundError / ProjectNotFoundError
     （world_errors 复用）→ 404；MapAssetError → 500

2. 端点总览（12 个，spec §3.1）:
   - POST /api/v1/projects/{project_id}/maps —— multipart/form-data
     （file: UploadFile = File(...), name: str = Form(...),
     description: str = Form(''), root_location_id: str | None = Form(None)；
     content = await file.read()）→ 201 WorldMap。root_location_id 非法 UUID
     → 422「父地点不存在或不在同一项目」（router 侧解析，create_map 不被
     调用——本文件锁定行为）
   - GET /api/v1/projects/{project_id}/maps —— ?root_location_id=<uuid>
     （过滤）/ ?root_location_id=none（全局图）/ 缺省全量
     → {"items", "total", "offset", "limit"}（offset=0 / limit=50 回显）
   - GET /api/v1/maps/{map_id} → 200 WorldMap / 404「地图不存在」
   - GET /api/v1/maps/{map_id}/image → 200 FileResponse（bytes）；
     get_image_file 返回 None → 404「地图不存在」；路径不存在
     （not path.is_file()）→ 404「图片文件缺失」
   - GET /api/v1/maps/{map_id}/children → {"items", "total"}
   - PATCH /api/v1/maps/{map_id} —— body: name/description/root_location_id
     全可选；root_location_id null=改全局图（exclude_unset 语义）→ 200 / 404
   - PUT /api/v1/maps/{map_id}/image —— multipart file → 200 WorldMap；
     replace_image 返回 None → 404「地图不存在」（本文件锁定行为）
   - DELETE /api/v1/maps/{map_id} —— ?cascade=true | ?reparent_to=<map_id>
     | 无参 → 204 无 body / 422（MapChildrenActionRequiredError）/
     404（MapNotFoundError）
   - POST /api/v1/maps/{map_id}/pins —— body {location_id, x, y, label}
     → 201 MapPin / 404（MapNotFoundError）/ 422（MapPinLocationNotFoundError）
   - GET /api/v1/maps/{map_id}/pins —— ?location_id=<uuid> 过滤可选
     → {"items", "total"}
   - PATCH /api/v1/map-pins/{pin_id} → 200 / 404「pin 不存在」/
     422（MapPinLocationNotFoundError，location 改挂非法）
   - DELETE /api/v1/map-pins/{pin_id} → 204 / 404「pin 不存在」

3. MapService 方法契约（mock 目标，12 个——与兄弟文件 test_map_service.py
   的 docstring 契约一致）:
   create_map(project_id, name, description, root_location_id,
     image_filename, image_content) -> WorldMap
   list_maps(project_id, root_location_id=None, top_level_only=False,
     offset=0, limit=50) -> (list, total) —— 缺省调用 list_maps(pid) 单参；
     ?root_location_id=<uuid> → list_maps(pid, root_location_id=uuid)；
     ?root_location_id=none → list_maps(pid, top_level_only=True)
   get_map(map_id) -> WorldMap | None
   get_image_file(map_id) -> Path | None
   update_map(map_id, update: WorldMapUpdate) -> WorldMap | None
   replace_image(map_id, image_filename, image_content) -> WorldMap
   delete_map(map_id, cascade=False, reparent_to=None) -> bool —— 无参 →
     delete_map(sid) 单参；?cascade=true → (sid, cascade=True)；
     ?reparent_to=<uuid> → (sid, reparent_to=uuid)
   children(map_id) -> list[WorldMap]
   add_pin(map_id, location_id, x, y, label) -> MapPin
   list_pins(map_id, location_id: uuid.UUID | None = None) -> list[MapPin]
     —— 本文件锁定签名（与兄弟文件 test_map_service.py 的 list_pins(map_id)
     单参形式向后兼容，GREEN 扩展可选 kwarg）；?location_id=<uuid> →
     list_pins(map_id, location_id=uuid)
   update_pin(pin_id, update: MapPinUpdate) -> MapPin | None
   delete_pin(pin_id) -> bool

4. 领域模型（inkflow.domain.models.map，工厂体内惰性 import）:
   WorldMap(id, project_id, name, image_path, description='',
     root_location_id=None, created_at, updated_at)
   MapPin(id, map_id, location_id=None, x, y, label, created_at, updated_at)
   WorldMapUpdate / MapPinUpdate 全可选 exclude_unset 语义。

5. 错误类（inkflow.domain.ports.map_errors，默认消息文案逐字）:
   MapServiceError(Exception) 基类（422 业务错误基类）
   MapNameConflictError(MapServiceError) 同名地图已存在（项目内）
   MapRootLocationConflictError(MapServiceError) 该地点已挂有一张地图
   MapRootLocationNotFoundError(MapServiceError) 父地点不存在或不在同一项目
   MapPinLocationNotFoundError(MapServiceError) pin 关联地点不存在或不在同一项目
   MapChildrenActionRequiredError(MapServiceError)
     该地图存在子地图，必须指定 cascade=true（级联删除）或
     reparent_to=<map_id>（子地图改挂新父）
   MapReparentTargetError(MapServiceError)
     reparent 目标地图不存在/不在同一项目/是自身子孙地图
   MapNotFoundError(Exception) 地图不存在（404）
   MapPinNotFoundError(Exception) pin 不存在（404）
   MapAssetError(Exception)（500，消息自由）
   ProjectNotFoundError 复用 inkflow.domain.ports.world_errors → 404

6. 响应形态: model_dump(mode='json')（id/project_id 等为字符串）。
   PATCH 参数断言用 await_args 解包（args[1] / kwargs['update']，兼容位置/
   关键字两种 GREEN 形态）；map_id/pin_id 由 router 解析为 UUID 后透传。

依据: specs/f36-world-map/spec.md §3.1/§3.3 + 父侧定稿契约（F36 #181/#174）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

try:
    from inkflow.domain.ports.map_errors import (
        MapAssetError,
        MapChildrenActionRequiredError,
        MapNameConflictError,
        MapNotFoundError,
        MapPinLocationNotFoundError,
        MapPinNotFoundError,
        MapReparentTargetError,
        MapRootLocationConflictError,
        MapRootLocationNotFoundError,
        MapServiceError,
    )
except ImportError:  # pragma: no cover - F36 RED: map_errors 尚未实现
    MapServiceError = type("MapServiceError", (Exception,), {})
    MapNameConflictError = type("MapNameConflictError", (MapServiceError,), {})
    MapRootLocationConflictError = type("MapRootLocationConflictError", (MapServiceError,), {})
    MapRootLocationNotFoundError = type("MapRootLocationNotFoundError", (MapServiceError,), {})
    MapPinLocationNotFoundError = type("MapPinLocationNotFoundError", (MapServiceError,), {})
    MapChildrenActionRequiredError = type("MapChildrenActionRequiredError", (MapServiceError,), {})
    MapReparentTargetError = type("MapReparentTargetError", (MapServiceError,), {})
    MapNotFoundError = type("MapNotFoundError", (Exception,), {})
    MapPinNotFoundError = type("MapPinNotFoundError", (Exception,), {})
    MapAssetError = type("MapAssetError", (Exception,), {})

try:  # pragma: no cover - #368 RED: MapParentMapNotFoundError 尚未实现
    from inkflow.domain.ports.map_errors import MapParentMapNotFoundError
except ImportError:
    MapParentMapNotFoundError = type("MapParentMapNotFoundError", (MapServiceError,), {})

import inkflow.api.routers.maps  # noqa: F401  # RED 阶段主契约 import（router 未实现 → 收集期失败点；GREEN 后仍保持显式导入）
from inkflow.api.app import app
from inkflow.domain.ports.world_errors import ProjectNotFoundError

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
LOC_ID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000002")  # 父地点（root_location）
TS = datetime(2026, 8, 1, 10, 0, 0)
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16  # 图片字节（mock 不校验魔数）


def _map(pid: uuid.UUID, name: str = "清河县城图", **kw):
    """构造测试用地图实体（模型惰性 import——RED 阶段 models/map.py 未实现）。"""
    from inkflow.domain.models.map import WorldMap

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


def _pin(map_id: uuid.UUID, **kw):
    """构造测试用 pin 实体（模型惰性 import）。"""
    from inkflow.domain.models.map import MapPin

    base = dict(
        id=uuid.uuid4(),
        map_id=map_id,
        location_id=None,
        x=10.0,
        y=20.0,
        label="城门",
        created_at=TS,
        updated_at=TS,
    )
    base.update(kw)
    return MapPin(**base)


def _mock_svc(mock_get_svc: MagicMock) -> MagicMock:
    """构造默认可用的 Mock MapService（被 await 方法逐用例显式赋 AsyncMock）。"""
    svc = MagicMock()
    mock_get_svc.return_value = svc
    return svc


class TestMapCreateAPI:
    """创建地图端点（POST /api/v1/projects/{project_id}/maps，multipart）。"""

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_create_map_success(self, mock_get_svc: MagicMock) -> None:
        """创建地图返回 201 + WorldMap JSON（root_location_id 解析为 UUID 透传）。"""
        svc = _mock_svc(mock_get_svc)
        m = _map(PID, root_location_id=LOC_ID)
        svc.create_map = AsyncMock(return_value=m)

        response = client.post(
            f"/api/v1/projects/{PID}/maps",
            files={"file": ("main.png", PNG_BYTES, "image/png")},
            data={
                "name": "清河县城图",
                "description": "县城布局",
                "root_location_id": str(LOC_ID),
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == str(m.id)
        assert data["project_id"] == str(PID)
        assert data["name"] == "清河县城图"
        assert data["root_location_id"] == str(LOC_ID)
        svc.create_map.assert_awaited_once_with(
            PID, "清河县城图", "县城布局", LOC_ID, "main.png", PNG_BYTES
        )

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_create_map_without_root_location_id(self, mock_get_svc: MagicMock) -> None:
        """创建不带 root_location_id → 201 + create_map 收到 root_location_id=None."""
        svc = _mock_svc(mock_get_svc)
        svc.create_map = AsyncMock(return_value=_map(PID))

        response = client.post(
            f"/api/v1/projects/{PID}/maps",
            files={"file": ("main.png", PNG_BYTES, "image/png")},
            data={"name": "清河县城图", "description": "县城布局"},
        )
        assert response.status_code == 201
        svc.create_map.assert_awaited_once_with(
            PID, "清河县城图", "县城布局", None, "main.png", PNG_BYTES
        )

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_create_map_name_conflict_422(self, mock_get_svc: MagicMock) -> None:
        """同名地图创建 → 422 + detail 精确「同名地图已存在（项目内）」."""
        svc = _mock_svc(mock_get_svc)
        svc.create_map = AsyncMock(side_effect=MapNameConflictError())

        response = client.post(
            f"/api/v1/projects/{PID}/maps",
            files={"file": ("main.png", PNG_BYTES, "image/png")},
            data={"name": "清河县城图"},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "同名地图已存在（项目内）"

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_create_map_root_location_invalid_422(self, mock_get_svc: MagicMock) -> None:
        """root_location_id 非法 → 422「父地点不存在或不在同一项目」（两条路径）.

        ① service 抛 MapRootLocationNotFoundError（MapServiceError → 422 映射）；
        ② 请求体 root_location_id 非 UUID → router 侧解析失败同 422 同文案，
        且 create_map 不被调用（本文件锁定行为，见文件头设计假设 2）。
        #368 v1.3：错误类 detail 追加引导后缀（③ 修复点）。
        """
        svc = _mock_svc(mock_get_svc)
        svc.create_map = AsyncMock(side_effect=MapRootLocationNotFoundError())
        resp1 = client.post(
            f"/api/v1/projects/{PID}/maps",
            files={"file": ("main.png", PNG_BYTES, "image/png")},
            data={"name": "清河县城图", "root_location_id": str(LOC_ID)},
        )
        assert resp1.status_code == 422
        assert resp1.json()["detail"] == (
            "父地点不存在或不在同一项目（根地点应为世界观条目 id，而非地图 id）"
        )

        svc.create_map = AsyncMock(return_value=_map(PID))
        resp2 = client.post(
            f"/api/v1/projects/{PID}/maps",
            files={"file": ("main.png", PNG_BYTES, "image/png")},
            data={"name": "清河县城图", "root_location_id": "not-a-uuid"},
        )
        assert resp2.status_code == 422
        assert resp2.json()["detail"] == "父地点不存在或不在同一项目"
        svc.create_map.assert_not_awaited()

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_create_map_project_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """项目不存在（ProjectNotFoundError，world_errors 复用）→ 404「项目不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.create_map = AsyncMock(side_effect=ProjectNotFoundError())

        response = client.post(
            f"/api/v1/projects/{PID}/maps",
            files={"file": ("main.png", PNG_BYTES, "image/png")},
            data={"name": "清河县城图"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "项目不存在"

    # ── #368 v1.3：parent_map_id Form 透传（spec §3.1）──

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_create_map_parent_map_id_passthrough(self, mock_get_svc: MagicMock) -> None:
        """POST parent_map_id=UUID → create_map 收到 parent_map_id kwarg（图挂图层级）."""
        svc = _mock_svc(mock_get_svc)
        svc.create_map = AsyncMock(return_value=_map(PID, parent_map_id=LOC_ID))
        parent_id = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000009")

        response = client.post(
            f"/api/v1/projects/{PID}/maps",
            files={"file": ("main.png", PNG_BYTES, "image/png")},
            data={
                "name": "清河县城图",
                "description": "县城布局",
                "parent_map_id": str(parent_id),
            },
        )
        assert response.status_code == 201
        svc.create_map.assert_awaited_once_with(
            PID, "清河县城图", "县城布局", None, "main.png", PNG_BYTES, parent_map_id=parent_id
        )

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_create_map_parent_map_missing_422(self, mock_get_svc: MagicMock) -> None:
        """parent_map_id 父图不存在 → 422 + detail「父地图不存在或不在同一项目」."""
        svc = _mock_svc(mock_get_svc)
        svc.create_map = AsyncMock(side_effect=MapParentMapNotFoundError())

        response = client.post(
            f"/api/v1/projects/{PID}/maps",
            files={"file": ("main.png", PNG_BYTES, "image/png")},
            data={
                "name": "清河县城图",
                "parent_map_id": str(uuid.uuid4()),
            },
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "父地图不存在或不在同一项目"

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_create_map_parent_map_id_invalid_422(self, mock_get_svc: MagicMock) -> None:
        """parent_map_id 非 UUID → 422（router 侧解析失败，create_map 不被调用）."""
        svc = _mock_svc(mock_get_svc)
        svc.create_map = AsyncMock(return_value=_map(PID))

        response = client.post(
            f"/api/v1/projects/{PID}/maps",
            files={"file": ("main.png", PNG_BYTES, "image/png")},
            data={
                "name": "清河县城图",
                "parent_map_id": "not-a-uuid",
            },
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "父地图不存在或不在同一项目"
        svc.create_map.assert_not_awaited()


class TestMapListAPI:
    """地图列表端点（GET /api/v1/projects/{project_id}/maps）。"""

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_list_maps_default(self, mock_get_svc: MagicMock) -> None:
        """缺省列表 → 200 {items, total, offset, limit} + list_maps(pid) 单参调用."""
        svc = _mock_svc(mock_get_svc)
        svc.list_maps = AsyncMock(return_value=([_map(PID)], 1))

        response = client.get(f"/api/v1/projects/{PID}/maps")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["offset"] == 0
        assert data["limit"] == 50
        assert data["items"][0]["name"] == "清河县城图"
        svc.list_maps.assert_awaited_once_with(PID)

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_list_maps_root_location_filter(self, mock_get_svc: MagicMock) -> None:
        """/?root_location_id=<uuid> → list_maps(pid, root_location_id=UUID)（过滤）."""
        svc = _mock_svc(mock_get_svc)
        svc.list_maps = AsyncMock(return_value=([], 0))

        response = client.get(
            f"/api/v1/projects/{PID}/maps", params={"root_location_id": str(LOC_ID)}
        )
        assert response.status_code == 200
        assert response.json()["total"] == 0
        svc.list_maps.assert_awaited_once_with(PID, root_location_id=LOC_ID)

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_list_maps_top_level_only(self, mock_get_svc: MagicMock) -> None:
        """/?root_location_id=none → list_maps(pid, top_level_only=True)（全局图）."""
        svc = _mock_svc(mock_get_svc)
        svc.list_maps = AsyncMock(return_value=([], 0))

        response = client.get(f"/api/v1/projects/{PID}/maps", params={"root_location_id": "none"})
        assert response.status_code == 200
        assert response.json()["total"] == 0
        svc.list_maps.assert_awaited_once_with(PID, top_level_only=True)


class TestMapGetAPI:
    """地图详情端点（GET /api/v1/maps/{map_id}）。"""

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_get_map_success(self, mock_get_svc: MagicMock) -> None:
        """地图详情返回 200 + WorldMap JSON（id/project_id 字符串形态）."""
        svc = _mock_svc(mock_get_svc)
        m = _map(PID)
        svc.get_map = AsyncMock(return_value=m)

        response = client.get(f"/api/v1/maps/{m.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(m.id)
        assert data["project_id"] == str(PID)
        assert data["name"] == "清河县城图"
        svc.get_map.assert_awaited_once_with(m.id)

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_get_map_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """get_map 返回 None → 404「地图不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.get_map = AsyncMock(return_value=None)

        response = client.get(f"/api/v1/maps/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "地图不存在"

    def test_get_map_invalid_uuid_404(self) -> None:
        """非法 UUID → 404「地图不存在」（_parse_id detail 锁定，见设计假设 1）."""
        response = client.get("/api/v1/maps/not-a-uuid")
        assert response.status_code == 404
        assert response.json()["detail"] == "地图不存在"


class TestMapImageAPI:
    """地图图片端点（GET /api/v1/maps/{map_id}/image，FileResponse）。"""

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_get_image_success(self, mock_get_svc: MagicMock, tmp_path: Path) -> None:
        """图片文件存在 → 200 + FileResponse 字节内容一致."""
        svc = _mock_svc(mock_get_svc)
        img = tmp_path / "main.png"
        img.write_bytes(PNG_BYTES)
        map_id = uuid.uuid4()
        svc.get_image_file = AsyncMock(return_value=img)

        response = client.get(f"/api/v1/maps/{map_id}/image")
        assert response.status_code == 200
        assert response.content == PNG_BYTES
        svc.get_image_file.assert_awaited_once_with(map_id)

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_get_image_map_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """get_image_file 返回 None（地图不存在）→ 404「地图不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.get_image_file = AsyncMock(return_value=None)

        response = client.get(f"/api/v1/maps/{uuid.uuid4()}/image")
        assert response.status_code == 404
        assert response.json()["detail"] == "地图不存在"

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_get_image_file_missing_404(self, mock_get_svc: MagicMock, tmp_path: Path) -> None:
        """返回的路径不存在（is_file() False）→ 404「图片文件缺失」."""
        svc = _mock_svc(mock_get_svc)
        svc.get_image_file = AsyncMock(return_value=tmp_path / "missing.png")

        response = client.get(f"/api/v1/maps/{uuid.uuid4()}/image")
        assert response.status_code == 404
        assert response.json()["detail"] == "图片文件缺失"


class TestMapChildrenAPI:
    """地图子地图端点（GET /api/v1/maps/{map_id}/children）。"""

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_get_children_success(self, mock_get_svc: MagicMock) -> None:
        """子地图列表 → 200 {items, total}."""
        svc = _mock_svc(mock_get_svc)
        child = _map(PID, name="清河县城·分图")
        map_id = uuid.uuid4()
        svc.children = AsyncMock(return_value=[child])

        response = client.get(f"/api/v1/maps/{map_id}/children")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "清河县城·分图"
        svc.children.assert_awaited_once_with(map_id)


class TestMapUpdateAPI:
    """地图更新端点（PATCH /api/v1/maps/{map_id}，exclude_unset 语义）。"""

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_update_map_success(self, mock_get_svc: MagicMock) -> None:
        """PATCH name → 200 + WorldMap JSON；update.model_fields_set 含 name."""
        svc = _mock_svc(mock_get_svc)
        m = _map(PID)
        updated = m.model_copy(update={"name": "清河县城图·改"})
        svc.update_map = AsyncMock(return_value=updated)

        response = client.patch(f"/api/v1/maps/{m.id}", json={"name": "清河县城图·改"})
        assert response.status_code == 200
        assert response.json()["name"] == "清河县城图·改"
        svc.update_map.assert_awaited_once()
        args, kwargs = svc.update_map.await_args
        update = args[1] if len(args) > 1 else kwargs["update"]
        assert "name" in update.model_fields_set
        assert update.name == "清河县城图·改"

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_update_map_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """update_map 返回 None → 404「地图不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.update_map = AsyncMock(return_value=None)

        response = client.patch(f"/api/v1/maps/{uuid.uuid4()}", json={"name": "清河县城图·改"})
        assert response.status_code == 404
        assert response.json()["detail"] == "地图不存在"

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_update_map_root_location_null(self, mock_get_svc: MagicMock) -> None:
        """PATCH {root_location_id: null} → fields_set 含 root_location_id（改全局图）."""
        svc = _mock_svc(mock_get_svc)
        m = _map(PID)
        svc.update_map = AsyncMock(return_value=m)

        response = client.patch(f"/api/v1/maps/{m.id}", json={"root_location_id": None})
        assert response.status_code == 200
        args, kwargs = svc.update_map.await_args
        update = args[1] if len(args) > 1 else kwargs["update"]
        assert "root_location_id" in update.model_fields_set
        assert update.root_location_id is None

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_update_map_without_root_location(self, mock_get_svc: MagicMock) -> None:
        """守护: PATCH 未传 root_location_id → fields_set 不含（不修改根地点）."""
        svc = _mock_svc(mock_get_svc)
        m = _map(PID)
        svc.update_map = AsyncMock(return_value=m)

        response = client.patch(f"/api/v1/maps/{m.id}", json={"name": "清河县城图·改"})
        assert response.status_code == 200
        args, kwargs = svc.update_map.await_args
        update = args[1] if len(args) > 1 else kwargs["update"]
        assert "root_location_id" not in update.model_fields_set


class TestMapImagePutAPI:
    """替换地图图片端点（PUT /api/v1/maps/{map_id}/image，multipart）。"""

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_replace_image_success(self, mock_get_svc: MagicMock) -> None:
        """替换图片 → 200 + WorldMap JSON；replace_image 收到新文件名/内容."""
        svc = _mock_svc(mock_get_svc)
        m = _map(PID)
        svc.replace_image = AsyncMock(return_value=m)

        response = client.put(
            f"/api/v1/maps/{m.id}/image",
            files={"file": ("new.png", PNG_BYTES, "image/png")},
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(m.id)
        svc.replace_image.assert_awaited_once_with(m.id, "new.png", PNG_BYTES)

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_replace_image_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """replace_image 返回 None → 404「地图不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.replace_image = AsyncMock(return_value=None)

        response = client.put(
            f"/api/v1/maps/{uuid.uuid4()}/image",
            files={"file": ("new.png", PNG_BYTES, "image/png")},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "地图不存在"

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_replace_image_asset_error_500(self, mock_get_svc: MagicMock) -> None:
        """MapAssetError（文件层）→ 500（_run_service 链，detail 非空字符串）."""
        svc = _mock_svc(mock_get_svc)
        svc.replace_image = AsyncMock(side_effect=MapAssetError("磁盘写入失败"))

        response = client.put(
            f"/api/v1/maps/{uuid.uuid4()}/image",
            files={"file": ("new.png", PNG_BYTES, "image/png")},
        )
        assert response.status_code == 500
        assert response.json()["detail"] != ""


class TestMapDeleteAPI:
    """删除地图端点（DELETE /api/v1/maps/{map_id}，D6 参数矩阵）。"""

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_delete_map_default_204(self, mock_get_svc: MagicMock) -> None:
        """无参删除 → 204 无 body + delete_map(sid) 单参调用."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_map = AsyncMock(return_value=True)

        map_id = uuid.uuid4()
        response = client.delete(f"/api/v1/maps/{map_id}")
        assert response.status_code == 204
        assert response.content == b""
        svc.delete_map.assert_awaited_once_with(map_id)

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_delete_map_cascade_204(self, mock_get_svc: MagicMock) -> None:
        """/?cascade=true → delete_map(sid, cascade=True)."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_map = AsyncMock(return_value=True)

        map_id = uuid.uuid4()
        response = client.delete(f"/api/v1/maps/{map_id}?cascade=true")
        assert response.status_code == 204
        svc.delete_map.assert_awaited_once_with(map_id, cascade=True)

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_delete_map_reparent_to_204(self, mock_get_svc: MagicMock) -> None:
        """/?reparent_to=<uuid> → delete_map(sid, reparent_to=UUID)."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_map = AsyncMock(return_value=True)

        map_id = uuid.uuid4()
        response = client.delete(f"/api/v1/maps/{map_id}?reparent_to={LOC_ID}")
        assert response.status_code == 204
        svc.delete_map.assert_awaited_once_with(map_id, reparent_to=LOC_ID)

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_delete_map_children_action_required_422(self, mock_get_svc: MagicMock) -> None:
        """有子地图无参删除 → 422 + detail 精确（spec §3.3 文案）."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_map = AsyncMock(side_effect=MapChildrenActionRequiredError())

        detail = (
            "该地图存在子地图，必须指定 cascade=true（级联删除）或 "
            "reparent_to=<map_id>（子地图改挂新父）"
        )
        response = client.delete(f"/api/v1/maps/{uuid.uuid4()}")
        assert response.status_code == 422
        assert response.json()["detail"] == detail

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_delete_map_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """MapNotFoundError（非 MapServiceError 子类）→ 404「地图不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_map = AsyncMock(side_effect=MapNotFoundError())

        response = client.delete(f"/api/v1/maps/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "地图不存在"


class TestMapPinCreateAPI:
    """添加 pin 端点（POST /api/v1/maps/{map_id}/pins）。"""

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_add_pin_success(self, mock_get_svc: MagicMock) -> None:
        """添加 pin → 201 + MapPin JSON；add_pin 收到 (map_id, location_id, x, y, label)."""
        svc = _mock_svc(mock_get_svc)
        map_id = uuid.uuid4()
        pin = _pin(map_id, location_id=LOC_ID, x=10.0, y=20.0, label="城门")
        svc.add_pin = AsyncMock(return_value=pin)

        response = client.post(
            f"/api/v1/maps/{map_id}/pins",
            json={"location_id": str(LOC_ID), "x": 10, "y": 20, "label": "城门"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == str(pin.id)
        assert data["map_id"] == str(map_id)
        assert data["location_id"] == str(LOC_ID)
        assert data["label"] == "城门"
        svc.add_pin.assert_awaited_once_with(map_id, LOC_ID, 10, 20, "城门")

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_add_pin_map_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """地图不存在（MapNotFoundError）→ 404「地图不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.add_pin = AsyncMock(side_effect=MapNotFoundError())

        response = client.post(
            f"/api/v1/maps/{uuid.uuid4()}/pins",
            json={"location_id": str(LOC_ID), "x": 10, "y": 20, "label": "城门"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "地图不存在"

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_add_pin_location_not_found_422(self, mock_get_svc: MagicMock) -> None:
        """location 非法（MapPinLocationNotFoundError）→ 422 精确文案."""
        svc = _mock_svc(mock_get_svc)
        svc.add_pin = AsyncMock(side_effect=MapPinLocationNotFoundError())

        response = client.post(
            f"/api/v1/maps/{uuid.uuid4()}/pins",
            json={"location_id": str(LOC_ID), "x": 10, "y": 20, "label": "城门"},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "pin 关联地点不存在或不在同一项目"

    def test_add_pin_coordinate_out_of_bounds_422(self) -> None:
        """坐标超界（x=101，Pydantic ge/le 校验）→ 422 校验错误列表."""
        response = client.post(
            f"/api/v1/maps/{uuid.uuid4()}/pins",
            json={"location_id": str(LOC_ID), "x": 101, "y": 20, "label": "城门"},
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert isinstance(detail, list)
        assert "x" in str(detail)


class TestMapPinListAPI:
    """pin 列表端点（GET /api/v1/maps/{map_id}/pins）。"""

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_list_pins_success(self, mock_get_svc: MagicMock) -> None:
        """pin 列表 → 200 {items, total} + list_pins(map_id) 调用."""
        svc = _mock_svc(mock_get_svc)
        map_id = uuid.uuid4()
        svc.list_pins = AsyncMock(return_value=[_pin(map_id)])

        response = client.get(f"/api/v1/maps/{map_id}/pins")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["map_id"] == str(map_id)
        svc.list_pins.assert_awaited_once_with(map_id)

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_list_pins_location_filter(self, mock_get_svc: MagicMock) -> None:
        """/?location_id=<uuid> → list_pins(map_id, location_id=UUID)（签名锁定，见假设 3）."""
        svc = _mock_svc(mock_get_svc)
        map_id = uuid.uuid4()
        svc.list_pins = AsyncMock(return_value=[])

        response = client.get(f"/api/v1/maps/{map_id}/pins", params={"location_id": str(LOC_ID)})
        assert response.status_code == 200
        assert response.json()["total"] == 0
        svc.list_pins.assert_awaited_once_with(map_id, location_id=LOC_ID)


class TestMapPinUpdateAPI:
    """pin 更新端点（PATCH /api/v1/map-pins/{pin_id}）。"""

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_update_pin_success(self, mock_get_svc: MagicMock) -> None:
        """PATCH label → 200 + MapPin JSON；update.model_fields_set 含 label."""
        svc = _mock_svc(mock_get_svc)
        pin = _pin(uuid.uuid4(), label="北门")
        svc.update_pin = AsyncMock(return_value=pin)

        response = client.patch(f"/api/v1/map-pins/{pin.id}", json={"label": "北门"})
        assert response.status_code == 200
        assert response.json()["label"] == "北门"
        svc.update_pin.assert_awaited_once()
        args, kwargs = svc.update_pin.await_args
        update = args[1] if len(args) > 1 else kwargs["update"]
        assert "label" in update.model_fields_set
        assert update.label == "北门"

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_update_pin_location_invalid_422(self, mock_get_svc: MagicMock) -> None:
        """location 改挂非法（MapPinLocationNotFoundError）→ 422 精确文案."""
        svc = _mock_svc(mock_get_svc)
        svc.update_pin = AsyncMock(side_effect=MapPinLocationNotFoundError())

        response = client.patch(
            f"/api/v1/map-pins/{uuid.uuid4()}", json={"location_id": str(LOC_ID)}
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "pin 关联地点不存在或不在同一项目"

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_update_pin_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """update_pin 返回 None → 404「pin 不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.update_pin = AsyncMock(return_value=None)

        response = client.patch(f"/api/v1/map-pins/{uuid.uuid4()}", json={"label": "北门"})
        assert response.status_code == 404
        assert response.json()["detail"] == "pin 不存在"


class TestMapPinDeleteAPI:
    """pin 删除端点（DELETE /api/v1/map-pins/{pin_id}）。"""

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_delete_pin_success(self, mock_get_svc: MagicMock) -> None:
        """删除 pin → 204 无 body + delete_pin(pin_id) 调用."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_pin = AsyncMock(return_value=True)

        pin_id = uuid.uuid4()
        response = client.delete(f"/api/v1/map-pins/{pin_id}")
        assert response.status_code == 204
        assert response.content == b""
        svc.delete_pin.assert_awaited_once_with(pin_id)

    @patch("inkflow.api.routers.maps.get_map_service")
    def test_delete_pin_not_found_404(self, mock_get_svc: MagicMock) -> None:
        """MapPinNotFoundError → 404「pin 不存在」."""
        svc = _mock_svc(mock_get_svc)
        svc.delete_pin = AsyncMock(side_effect=MapPinNotFoundError())

        response = client.delete(f"/api/v1/map-pins/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["detail"] == "pin 不存在"
