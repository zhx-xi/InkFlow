"""F10 世界观分类 CRUD 测试（v1.2，issue #389）— 模型 + 服务 + API 三层 RED 契约.

测试范围（specs/f10-world-settings/spec.md v1.2 §2.6/§3.1/§6.1/§7）:
- 领域模型 WorldCategory（id/project_id/name/created_at/updated_at + name 校验）
- 服务层 WorldService 分类方法（Mock Repository）：create_category / list_world_categories /
  rename_category / delete_category + 同名冲突 / 不存在
- API 层四端点（Mock Service）：POST/GET 嵌套项目路径 + PATCH/DELETE 扁平路径 +
  404/422 全路径

GREEN 契约（测试即契约，实现方照此匹配）:
【领域模型】`inkflow.domain.models.world.WorldCategory`：
  id: uuid.UUID / project_id: uuid.UUID / name: str / created_at: datetime / updated_at: datetime；
  model_config = {"from_attributes": True}；共享校验 `_validate_category_name(v)`（去空白非空
  「分类名不能为空」、>50「分类名不能超过 50 个字符」）。

【错误类】`inkflow.domain.ports.world_errors`：
  WorldCategoryNameConflictError(WorldServiceError) 默认「同名世界观分类已存在」（422）
  WorldCategoryNotFoundError(Exception) 默认「世界观分类不存在」（404）

【服务层 WorldService 追加方法】（Mock Repository 契约）：
  async create_category(project_id: uuid.UUID, name: str) -> WorldCategory
    — 同名预检 get_category_by_name → WorldCategoryNameConflictError
  async list_world_categories(project_id: uuid.UUID) -> list[tuple[WorldCategory, int]]
    — 返回 (分类实体, 条目数) 列表
  async rename_category(category_id: uuid.UUID, name: str) -> WorldCategory | None
    — 不存在 → None；同名冲突 → WorldCategoryNameConflictError
  async delete_category(category_id: uuid.UUID) -> bool
    — 不存在 → False

【Repository 端口追加方法】（service mock 锚点）：
  create_category / list_world_categories / get_category / get_category_by_name /
  rename_category / delete_category（签名见服务层契约；rename/delete 反向同步条目 category）

【API 端点】：
  POST   /api/v1/projects/{pid}/world-categories     body {name} → 201 + WorldCategory JSON
  GET    /api/v1/projects/{pid}/world-categories     → 200 {items:[{id,name,count}], total}
  PATCH  /api/v1/world-categories/{cid}              body {name} → 200 + WorldCategory / 404
  DELETE /api/v1/world-categories/{cid}              → 204 / 404

RED 预期：WorldCategory / 错误类 / service 分类方法 / 端点均未实现 → ImportError 占位 stub
（try/except）保证文件可收集；分类用例 FAIL（import 缺失 / 方法不存在 / 端点 404）；零
SyntaxError / ReferenceError。

依据: specs/f10-world-settings/spec.md v1.2 §2.6 + §3.1 + §6.1 + §7 + §9。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.domain.ports.world_errors import WorldServiceError

# ── RED 阶段占位 stub：v1.2 未实现 → ImportError 兜底（GREEN 后自动用真实类）──
try:  # pragma: no cover - RED 阶段占位分支
    from inkflow.domain.models.world import WorldCategory, _validate_category_name
except ImportError:  # pragma: no cover - RED 阶段占位分支
    WorldCategory = None  # type: ignore[assignment]  # RED 占位：v1.2 未实现时置 None
    _validate_category_name = None  # type: ignore[assignment]  # RED 占位：校验函数未实现时置 None

try:  # pragma: no cover - RED 阶段占位分支
    from inkflow.domain.ports.world_errors import (
        WorldCategoryNameConflictError,
        WorldCategoryNotFoundError,
    )
except ImportError:  # pragma: no cover - RED 阶段占位分支
    WorldCategoryNameConflictError = type(
        "WorldCategoryNameConflictError", (WorldServiceError,), {}
    )
    WorldCategoryNotFoundError = type("WorldCategoryNotFoundError", (Exception,), {})

from inkflow.domain.services.world_service import WorldService

client = TestClient(app)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
CID = uuid.UUID("3f2e1d4a-0000-4000-8000-0000000000c1")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _category(name: str, *, project_id: uuid.UUID = PID, kind: str = "geo") -> WorldCategory:
    """构造测试用世界观分类实体（固定时间戳；kind 默认 geo）."""
    assert WorldCategory is not None, "WorldCategory 未实现（RED 预期）"
    return WorldCategory(
        id=uuid.uuid4(),
        project_id=project_id,
        name=name,
        kind=kind,
        created_at=TS,
        updated_at=TS,
    )


# ── 领域模型 ────────────────────────────────────────────────


class TestWorldCategoryModel:
    """WorldCategory 领域模型 + name 校验契约."""

    def test_world_category_fields(self) -> None:
        """WorldCategory 含 id/project_id/name/created_at/updated_at 五字段."""
        c = _category("势力")
        assert c.name == "势力"
        assert c.project_id == PID
        assert c.created_at == TS
        assert c.updated_at == TS
        assert c.id is not None

    def test_world_category_serialization(self) -> None:
        """序列化含六字段（含 kind），无多余字段."""
        c = _category("功法")
        dumped = c.model_dump(mode="json")
        expected_keys = {"id", "project_id", "name", "created_at", "updated_at", "kind"}
        assert set(dumped.keys()) == expected_keys
        assert dumped["name"] == "功法"
        assert dumped["kind"] == "geo"

    def test_world_category_kind_default_geo(self) -> None:
        """未指定 kind → 默认 geo（地理类）."""
        c = _category("势力")
        assert c.kind == "geo"

    def test_world_category_kind_abstract(self) -> None:
        """kind=abstract（抽象类）可显式设置."""
        c = _category("门派", kind="abstract")
        assert c.kind == "abstract"

    def test_validate_category_name_empty(self) -> None:
        """空/全空白分类名 → ValueError「分类名不能为空」."""
        assert _validate_category_name is not None, "_validate_category_name 未实现（RED 预期）"
        with pytest.raises(ValueError, match="分类名不能为空"):
            _validate_category_name("   ")

    def test_validate_category_name_too_long(self) -> None:
        """>50 字符分类名 → ValueError「分类名不能超过 50 个字符」."""
        assert _validate_category_name is not None
        with pytest.raises(ValueError, match="分类名不能超过 50 个字符"):
            _validate_category_name("长" * 51)

    def test_validate_category_name_strips(self) -> None:
        """去空白返回."""
        assert _validate_category_name is not None
        assert _validate_category_name("  势力  ") == "势力"


# ── 错误类 ──────────────────────────────────────────────────


class TestWorldCategoryErrors:
    """分类错误类默认文案契约."""

    def test_name_conflict_default_message(self) -> None:
        """WorldCategoryNameConflictError 默认「同名世界观分类已存在」."""
        assert str(WorldCategoryNameConflictError()) == "同名世界观分类已存在"

    def test_not_found_default_message(self) -> None:
        """WorldCategoryNotFoundError 默认「世界观分类不存在」."""
        assert str(WorldCategoryNotFoundError()) == "世界观分类不存在"


# ── 服务层（Mock Repository）─────────────────────────────────


class TestWorldCategoryService:
    """WorldService 分类方法（Mock Repository）契约."""

    def _svc(self) -> tuple[WorldService, MagicMock]:
        repo = MagicMock()
        svc = WorldService(repository=repo)
        return svc, repo

    async def test_create_category_success(self) -> None:
        """create_category 成功（kind 缺省 geo）→ 返回 WorldCategory（repo 收到 kind='geo'）."""
        svc, repo = self._svc()
        created = _category("势力")
        repo.get_category_by_name = AsyncMock(return_value=None)
        repo.create_category = AsyncMock(return_value=created)
        result = await svc.create_category(PID, "势力")
        assert result == created
        repo.create_category.assert_awaited_once_with(PID, "势力", "geo")

    async def test_create_category_with_kind_abstract(self) -> None:
        """create_category 显式 kind='abstract' → repo 收到 kind='abstract'."""
        svc, repo = self._svc()
        created = _category("势力", kind="abstract")
        repo.get_category_by_name = AsyncMock(return_value=None)
        repo.create_category = AsyncMock(return_value=created)
        result = await svc.create_category(PID, "势力", "abstract")
        assert result == created
        repo.create_category.assert_awaited_once_with(PID, "势力", "abstract")

    async def test_create_category_name_conflict(self) -> None:
        """同名分类已存在 → WorldCategoryNameConflictError."""
        svc, repo = self._svc()
        repo.get_category_by_name = AsyncMock(return_value=_category("势力"))
        with pytest.raises(WorldCategoryNameConflictError):
            await svc.create_category(PID, "势力")

    async def test_list_world_categories(self) -> None:
        """list_world_categories 透传 repo（返回 (实体, count) 列表）."""
        svc, repo = self._svc()
        cat = _category("势力")
        repo.list_world_categories = AsyncMock(return_value=[(cat, 3)])
        result = await svc.list_world_categories(PID)
        assert result == [(cat, 3)]
        repo.list_world_categories.assert_awaited_once_with(PID)

    async def test_rename_category_success(self) -> None:
        """rename_category 成功 → 返回重命名后实体."""
        svc, repo = self._svc()
        renamed = _category("宗门")
        repo.get_category = AsyncMock(return_value=_category("势力"))
        repo.get_category_by_name = AsyncMock(return_value=None)
        repo.rename_category = AsyncMock(return_value=renamed)
        result = await svc.rename_category(CID, "宗门")
        assert result == renamed

    async def test_rename_category_not_found(self) -> None:
        """重命名不存在的分类 → None."""
        svc, repo = self._svc()
        repo.get_category = AsyncMock(return_value=None)
        result = await svc.rename_category(CID, "宗门")
        assert result is None

    async def test_delete_category_success(self) -> None:
        """delete_category 成功 → True."""
        svc, repo = self._svc()
        repo.delete_category = AsyncMock(return_value=True)
        result = await svc.delete_category(CID)
        assert result is True

    async def test_delete_category_not_found(self) -> None:
        """删除不存在的分类 → False."""
        svc, repo = self._svc()
        repo.delete_category = AsyncMock(return_value=False)
        result = await svc.delete_category(CID)
        assert result is False


# ── API 层（Mock Service）────────────────────────────────────


class TestWorldCategoryAPI:
    """分类 CRUD 四端点契约（Mock Service）."""

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_create_category_201(self, mock_get_svc: MagicMock) -> None:
        """POST /projects/{pid}/world-categories → 201 + WorldCategory JSON."""
        svc = MagicMock()
        mock_get_svc.return_value = svc
        svc.create_category = AsyncMock(return_value=_category("势力"))
        resp = client.post(f"/api/v1/projects/{PID}/world-categories", json={"name": "势力"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "势力"
        assert body["kind"] == "geo"
        svc.create_category.assert_awaited_once_with(PID, "势力", "geo")

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_create_category_with_kind_201(self, mock_get_svc: MagicMock) -> None:
        """POST body 含 kind='abstract' → 201 + 响应含 kind + create_category 收到 kind."""
        svc = MagicMock()
        mock_get_svc.return_value = svc
        svc.create_category = AsyncMock(return_value=_category("势力", kind="abstract"))
        resp = client.post(
            f"/api/v1/projects/{PID}/world-categories", json={"name": "势力", "kind": "abstract"}
        )
        assert resp.status_code == 201
        assert resp.json()["kind"] == "abstract"
        svc.create_category.assert_awaited_once_with(PID, "势力", "abstract")

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_create_category_422_conflict(self, mock_get_svc: MagicMock) -> None:
        """同名分类 → 422「同名世界观分类已存在」."""
        svc = MagicMock()
        mock_get_svc.return_value = svc
        svc.create_category = AsyncMock(side_effect=WorldCategoryNameConflictError())
        resp = client.post(f"/api/v1/projects/{PID}/world-categories", json={"name": "势力"})
        assert resp.status_code == 422
        assert resp.json()["detail"] == "同名世界观分类已存在"

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_list_categories_200(self, mock_get_svc: MagicMock) -> None:
        """GET /projects/{pid}/world-categories → 200 {items:[{id,name,count}], total}."""
        svc = MagicMock()
        mock_get_svc.return_value = svc
        cat = _category("势力")
        svc.list_world_categories = AsyncMock(return_value=[(cat, 3)])
        resp = client.get(f"/api/v1/projects/{PID}/world-categories")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["name"] == "势力"
        assert body["items"][0]["count"] == 3
        assert body["items"][0]["kind"] == "geo"

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_rename_category_200(self, mock_get_svc: MagicMock) -> None:
        """PATCH /world-categories/{cid} → 200 + WorldCategory."""
        svc = MagicMock()
        mock_get_svc.return_value = svc
        svc.rename_category = AsyncMock(return_value=_category("宗门"))
        resp = client.patch(f"/api/v1/world-categories/{CID}", json={"name": "宗门"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "宗门"

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_rename_category_404(self, mock_get_svc: MagicMock) -> None:
        """PATCH 不存在的分类 → 404「世界观分类不存在」."""
        svc = MagicMock()
        mock_get_svc.return_value = svc
        svc.rename_category = AsyncMock(return_value=None)
        resp = client.patch(f"/api/v1/world-categories/{CID}", json={"name": "宗门"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "世界观分类不存在"

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_delete_category_204(self, mock_get_svc: MagicMock) -> None:
        """DELETE /world-categories/{cid} → 204."""
        svc = MagicMock()
        mock_get_svc.return_value = svc
        svc.delete_category = AsyncMock(return_value=True)
        resp = client.delete(f"/api/v1/world-categories/{CID}")
        assert resp.status_code == 204

    @patch("inkflow.api.routers.world_settings.get_world_service")
    def test_delete_category_404(self, mock_get_svc: MagicMock) -> None:
        """DELETE 不存在的分类 → 404「世界观分类不存在」."""
        svc = MagicMock()
        mock_get_svc.return_value = svc
        svc.delete_category = AsyncMock(return_value=False)
        resp = client.delete(f"/api/v1/world-categories/{CID}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "世界观分类不存在"
