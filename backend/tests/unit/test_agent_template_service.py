"""#107 AgentTemplateService 单元测试 — Mock Repository（RED 批）。

覆盖 spec §9.2①/§9.3 服务层（镜像 test_provider_config_service.py 的
Mock 注入模式，ADR-015）:
- create：默认字段落库编排（id=None 由 repo 分配；is_default=False；
  created_at/updated_at 填充）；同名 → AgentTemplateNameConflictError（422）
- get / list 委托 repo；get 不存在 → AgentTemplateNotFoundError（404）
- update：exclude_unset 部分合并；name 变更查重；None 值字段不应用
  （None = 不修改，同 F13）；updated_at 刷新；is_default 显式 False 可取消默认
- set_default：委托 repo.set_default（repo 保证单例）；不存在 → NotFound
- duplicate：复制模板（新 name = 「原名称 副本」或调用方指定）；is_default
  强制 False；id/时间戳重置；重名 → NameConflictError
- delete：不存在 → NotFound；**is_default=True → AgentTemplateBuiltinError
  （内置/默认模板不可删）**；被引用模板 → 级联清空引用项目
  config.template_id 后删除（service 注入 template_repo + project_repo）

依据: specs/f19-gui/spec.md §9.2①（service 模块）+ §9.5 测试策略「后端单元」。
删除语义: §9.2.4（评审 C2 定稿：删除被引用模板 = 确认后级联清空引用项目
config.template_id，一次写，回退默认模板装配）+ §9.8 Q3（用户拍板 A）。

══════════════════════ 设计假设（GREEN 实现者唯一契约）══════════════════════

模块与类（本批新建，当前不存在 → 收集期 ModuleNotFoundError 即预期 RED 形态）:

1. ``inkflow.domain.services.agent_template_service.AgentTemplateService``:
   - ``__init__(self, *, template_repository: AgentTemplateRepositoryProtocol,
     project_repository: ProjectRepositoryProtocol) -> None``
     （**双仓储注入**：project_repository 用于删除级联清引用）
   - ``async create(self, data: AgentTemplateCreate) -> AgentTemplate``:
     先 ``repo.get_by_name(data.name)`` 查重，命中 → NameConflictError；
     构造 ``AgentTemplate(id=None, ..., is_default=False)``（id 由 repo 分配），
     ``created_at = updated_at = datetime.now(UTC)``；委托 ``repo.add``
   - ``async get(self, template_id: int) -> AgentTemplate``:
     委托 ``repo.get``；None → AgentTemplateNotFoundError（404 语义）
   - ``async list(self) -> builtins.list[AgentTemplate]``: 委托 repo
   - ``async update(self, template_id: int, data: AgentTemplateUpdate)
     -> AgentTemplate``:
     先 ``repo.get``，None → NotFound；``model_dump(exclude_unset=True)``
     且剔除 None 值（None = 不修改）后 ``model_copy`` 合并；
     仅当 name 变更（!= existing.name）时 ``get_by_name`` 查重
     （命中且 id 不同 → NameConflictError）；
     ``updated_at = datetime.now(UTC)`` 刷新；委托 ``repo.update(merged)``
     （merged.is_default=True 时 repo.update 内部保证单例，服务层零逻辑）
   - ``async set_default(self, template_id: int) -> AgentTemplate``:
     先 ``repo.get``，None → NotFound；委托 ``repo.set_default(template_id)``
     并返回结果（单例由 repo 保证）
   - ``async duplicate(self, template_id: int, *, name: str | None = None)
     -> AgentTemplate``:
     先 ``repo.get``，None → NotFound；新名 = ``name`` 或
     ``f"{template.name} 副本"``；``repo.get_by_name`` 查重 → NameConflictError；
     ``model_copy(update={id: None, name: 新名, is_default: False,
     created_at: None, updated_at: None})`` 后委托 ``repo.add``
   - ``async delete(self, template_id: int) -> None``:
     先 ``repo.get``，None → NotFound；**``template.is_default`` 为 True →
     AgentTemplateBuiltinError（内置/默认模板不可删，spec §9.7「内置模板
     不可删」；本批契约以 is_default 判定，GREEN 可用 builtin_key 细化）**；
     ``refs = await repo.list_projects_by_template(template_id)``；
     对每个引用项目：``project.config.template_id = None`` 后
     ``await project_repository.update(project)``（级联清空，一次写）；
     最后 ``repo.delete(template_id)`` 返回 False（竞态不存在）→ NotFound；
     成功返回 None

2. ``inkflow.domain.ports.agent_template_repository.AgentTemplateRepositoryProtocol``
   （Protocol，方法签名同 repo 测试文件 docstring）:
   add / get / get_by_name / list / update / delete / set_default /
   list_projects_by_template

3. ``inkflow.domain.ports.agent_template_errors`` 错误类归属:
   - ``AgentTemplateServiceError(Exception)`` — 业务校验基类（API 映射 422）
   - ``AgentTemplateNotFoundError(Exception)`` — 404；默认消息精确为
     **"模板不存在"**
   - ``AgentTemplateNameConflictError(AgentTemplateServiceError)`` — 422；
     默认消息精确为 **"同名模板已存在（模板名称必须唯一）"**
   - ``AgentTemplateBuiltinError(AgentTemplateServiceError)`` — 422；
     默认消息精确为 **"内置模板不可删除"**

4. 时间戳契约: create/update 填充的 created_at/updated_at 为时区感知
   datetime（datetime.now(UTC)）；测试断言 tzinfo 非空 + created_at ==
   updated_at（create）/ created_at 保留（update）。

5. 级联契约: delete 对引用项目逐个 ``project_repository.update``；测试用
   MockProjectRepo 记录 update 调用并断言 config.template_id 被置 None；
   service 不直接触碰 template_repo.delete 之外的删除逻辑。

⚠️ 本批为 RED：不写任何 src/ 实现；GREEN 按上述签名实现后本文件应全绿。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.agent_template import (
    AgentTemplate,
    AgentTemplateCreate,
    AgentTemplateUpdate,
    RoleTemplate,
)
from inkflow.domain.models.project import Genre, Project, ProjectConfig
from inkflow.domain.ports.agent_template_errors import (
    AgentTemplateBuiltinError,
    AgentTemplateNameConflictError,
    AgentTemplateNotFoundError,
)
from inkflow.domain.ports.agent_template_repository import AgentTemplateRepositoryProtocol
from inkflow.domain.ports.project_repository import ProjectRepositoryProtocol
from inkflow.domain.services.agent_template_service import AgentTemplateService

TS = datetime(2026, 8, 1, 10, 0, 0)


def _template(template_id: int, name: str, **kw) -> AgentTemplate:
    """构造测试用 AgentTemplate 实体（固定时间戳，便于断言）。"""
    return AgentTemplate(
        id=template_id,
        name=name,
        created_at=TS,
        updated_at=TS,
        **kw,
    )


def _project(project_id: int, name: str, template_id: str | None) -> Project:
    """构造引用指定模板的项目实体（config.template_id 已设）。"""
    return Project(
        id=uuid.UUID(int=project_id),
        name=name,
        genre=Genre.QITA,
        language="zh-CN",
        target_words=0,
        config=ProjectConfig(template_id=template_id),
        created_at=TS,
        updated_at=TS,
    )


@pytest.fixture
def mock_repo() -> MagicMock:
    """Mock AgentTemplateRepositoryProtocol — 默认全方法可用，测试按需覆盖。"""
    repo = MagicMock(spec=AgentTemplateRepositoryProtocol)
    repo.add = AsyncMock(side_effect=lambda at: at)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=[])
    repo.update = AsyncMock(side_effect=lambda at: at)
    repo.delete = AsyncMock(return_value=True)
    repo.set_default = AsyncMock(side_effect=lambda tid: None)
    repo.list_projects_by_template = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_project_repo() -> MagicMock:
    """Mock ProjectRepositoryProtocol — 仅 get/update 被服务层使用。"""
    repo = MagicMock(spec=ProjectRepositoryProtocol)
    repo.get = AsyncMock(return_value=None)
    repo.update = AsyncMock(side_effect=lambda p: p)
    return repo


@pytest.fixture
def service(mock_repo: MagicMock, mock_project_repo: MagicMock) -> AgentTemplateService:
    """被测服务实例（双 Mock 仓储注入，ADR-015）。"""
    return AgentTemplateService(
        template_repository=mock_repo,
        project_repository=mock_project_repo,
    )


class TestCreate:
    """模板创建 — 默认字段编排 / 同名冲突。"""

    async def test_create_builds_entity_and_delegates(self, service, mock_repo):
        """create：查重（未命中）→ 构造实体（id=None、is_default=False、
        时间戳填充）→ repo.add。"""
        saved = await service.create(
            AgentTemplateCreate(
                name="我的模板",
                description="desc",
                main_model="openai/gpt-4o",
                default_temperature=0.8,
                roles={"writer": RoleTemplate(model="m/w", temperature=0.6)},
                default_words=50000,
            )
        )
        mock_repo.get_by_name.assert_awaited_once_with("我的模板")
        mock_repo.add.assert_awaited_once()
        at = mock_repo.add.await_args.args[0]
        assert at.id is None  # id 由 repo 分配
        assert at.name == "我的模板"
        assert at.description == "desc"
        assert at.main_model == "openai/gpt-4o"
        assert at.default_temperature == 0.8
        assert at.roles == {"writer": RoleTemplate(model="m/w", temperature=0.6)}
        assert at.default_words == 50000
        assert at.is_default is False  # 用户创建的行默认非默认
        assert at.created_at == at.updated_at
        assert at.created_at.tzinfo is not None  # datetime.now(UTC) 时区感知
        assert saved is at  # 直接返回 repo.add 结果

    async def test_create_name_conflict_raises(self, service, mock_repo):
        """同名已存在 → AgentTemplateNameConflictError（422），且不落库。"""
        mock_repo.get_by_name.return_value = _template(1, "我的模板")
        with pytest.raises(AgentTemplateNameConflictError, match="同名模板已存在"):
            await service.create(AgentTemplateCreate(name="我的模板"))
        mock_repo.add.assert_not_called()


class TestGet:
    """get / list 委托与 404 语义。"""

    async def test_get_found(self, service, mock_repo):
        """get 命中返回实体."""
        entity = _template(1, "t")
        mock_repo.get.return_value = entity
        assert await service.get(1) is entity
        mock_repo.get.assert_awaited_once_with(1)

    async def test_get_missing_raises_not_found(self, service, mock_repo):
        """get 不存在 → AgentTemplateNotFoundError（消息「模板不存在」）。"""
        mock_repo.get.return_value = None
        with pytest.raises(AgentTemplateNotFoundError, match="模板不存在"):
            await service.get(999)


class TestList:
    """list 委托。"""

    async def test_list_delegates(self, service, mock_repo):
        """list 直接返回 repo.list 结果."""
        items = [_template(1, "a"), _template(2, "b")]
        mock_repo.list.return_value = items
        assert await service.list() == items
        mock_repo.list.assert_awaited_once()


class TestUpdate:
    """update — 404 / 部分合并 / 改名查重 / None 不应用 / is_default 透传。"""

    async def test_update_missing_raises_not_found(self, service, mock_repo):
        """update 目标不存在 → AgentTemplateNotFoundError."""
        mock_repo.get.return_value = None
        with pytest.raises(AgentTemplateNotFoundError, match="模板不存在"):
            await service.update(999, AgentTemplateUpdate(main_model="m1"))

    async def test_update_partial_merge_and_refresh_updated_at(self, service, mock_repo):
        """部分更新：仅传入字段合并；created_at 保留；updated_at 刷新为 now(UTC)."""
        existing = _template(
            7, "旧名", main_model="m/old", roles={"writer": RoleTemplate(model="m/w")}
        )
        mock_repo.get.return_value = existing
        merged = await service.update(7, AgentTemplateUpdate(main_model="m/new"))

        mock_repo.get.assert_awaited_once_with(7)
        mock_repo.update.assert_awaited_once()
        updated = mock_repo.update.await_args.args[0]
        assert updated.id == 7
        assert updated.name == "旧名"  # 未传字段不变
        assert updated.main_model == "m/new"
        assert updated.roles == {"writer": RoleTemplate(model="m/w")}  # 未传字段不变
        assert updated.created_at == TS  # created_at 保留
        assert updated.updated_at.tzinfo is not None  # 刷新为 now(UTC)
        mock_repo.get_by_name.assert_not_called()  # name 未变，不查重
        assert merged is updated

    async def test_update_explicit_none_means_no_change(self, service, mock_repo):
        """显式 None 字段不应用（None = 不修改，同 F13）."""
        existing = _template(7, "旧名", main_model="m/old")
        mock_repo.get.return_value = existing
        await service.update(7, AgentTemplateUpdate(main_model=None))
        updated = mock_repo.update.await_args.args[0]
        assert updated.main_model == "m/old"  # 未被置 None

    async def test_update_roles_wholesale_replace(self, service, mock_repo):
        """roles 为浅合并顶层字段：传入即整体替换（exclude_unset 语义）。"""
        existing = _template(7, "旧名", roles={"writer": RoleTemplate(model="m/w")})
        mock_repo.get.return_value = existing
        await service.update(7, AgentTemplateUpdate(roles={"architect": RoleTemplate(model="m/a")}))
        updated = mock_repo.update.await_args.args[0]
        assert updated.roles == {"architect": RoleTemplate(model="m/a")}  # 整体替换

    async def test_update_rename_conflict_raises(self, service, mock_repo):
        """改名命中其他模板 → AgentTemplateNameConflictError，且不落库。"""
        existing = _template(7, "旧名")
        mock_repo.get.return_value = existing
        mock_repo.get_by_name.return_value = _template(8, "被占用")  # 其他 id 已占用
        with pytest.raises(AgentTemplateNameConflictError, match="同名模板已存在"):
            await service.update(7, AgentTemplateUpdate(name="被占用"))
        mock_repo.update.assert_not_called()

    async def test_update_rename_to_own_name_no_conflict(self, service, mock_repo):
        """name 未变化（与现有值相同）→ 不查重、直接更新。"""
        existing = _template(7, "旧名")
        mock_repo.get.return_value = existing
        await service.update(7, AgentTemplateUpdate(name="旧名"))
        mock_repo.get_by_name.assert_not_called()
        mock_repo.update.assert_awaited_once()

    async def test_update_set_is_default_true_passes_through(self, service, mock_repo):
        """PATCH is_default=True → merged.is_default=True 透传 repo.update
        （单例由 repo 保证，服务层零逻辑）。"""
        existing = _template(7, "旧名")
        mock_repo.get.return_value = existing
        await service.update(7, AgentTemplateUpdate(is_default=True))
        updated = mock_repo.update.await_args.args[0]
        assert updated.is_default is True

    async def test_update_set_is_default_false_cancels_default(self, service, mock_repo):
        """PATCH is_default=False → merged.is_default=False（取消默认语义）。"""
        existing = _template(7, "旧名", is_default=True)
        mock_repo.get.return_value = existing
        await service.update(7, AgentTemplateUpdate(is_default=False))
        updated = mock_repo.update.await_args.args[0]
        assert updated.is_default is False


class TestSetDefault:
    """set_default — 委托 repo（单例）与 404 语义。"""

    async def test_set_default_delegates(self, service, mock_repo):
        """set_default 委托 repo.set_default 并返回其结果。"""
        entity = _template(1, "t", is_default=True)
        mock_repo.get.return_value = entity
        # fixture 的 set_default 默认 side_effect 返回 None（优先于 return_value），
        # 此处覆盖 side_effect
        mock_repo.set_default.side_effect = lambda tid: entity
        assert await service.set_default(1) is entity
        mock_repo.set_default.assert_awaited_once_with(1)

    async def test_set_default_missing_raises_not_found(self, service, mock_repo):
        """目标模板不存在 → AgentTemplateNotFoundError，且不调 set_default。"""
        mock_repo.get.return_value = None
        with pytest.raises(AgentTemplateNotFoundError, match="模板不存在"):
            await service.set_default(999)
        mock_repo.set_default.assert_not_called()


class TestDuplicate:
    """duplicate — 复制模板（新名/重置服务端字段/查重/404）。"""

    async def test_duplicate_copies_with_suffix_name(self, service, mock_repo):
        """默认新名 = 「原名称 副本」；全字段复制；id/is_default/时间戳重置。"""
        src = _template(
            7,
            "玄幻模板",
            description="desc",
            main_model="m/main",
            default_temperature=0.8,
            roles={"writer": RoleTemplate(model="m/w")},
            default_words=50000,
            is_default=True,
        )
        mock_repo.get.return_value = src
        clone = await service.duplicate(7)

        mock_repo.get.assert_awaited_once_with(7)
        mock_repo.get_by_name.assert_awaited_once_with("玄幻模板 副本")
        mock_repo.add.assert_awaited_once()
        added = mock_repo.add.await_args.args[0]
        assert added.id is None  # 新 id 由 repo 分配
        assert added.name == "玄幻模板 副本"
        assert added.description == "desc"
        assert added.main_model == "m/main"
        assert added.default_temperature == 0.8
        assert added.roles == {"writer": RoleTemplate(model="m/w")}
        assert added.default_words == 50000
        assert added.is_default is False  # 副本不继承默认标记
        assert added.created_at is None  # 时间戳由服务层/ORM 重新填充
        assert added.updated_at is None
        assert clone is added

    async def test_duplicate_custom_name(self, service, mock_repo):
        """调用方指定 name 时使用指定名。"""
        mock_repo.get.return_value = _template(7, "原模板")
        await service.duplicate(7, name="我的副本")
        mock_repo.get_by_name.assert_awaited_once_with("我的副本")
        assert mock_repo.add.await_args.args[0].name == "我的副本"

    async def test_duplicate_name_conflict_raises(self, service, mock_repo):
        """副本名已存在 → AgentTemplateNameConflictError，且不落库。"""
        mock_repo.get.return_value = _template(7, "原模板")
        mock_repo.get_by_name.return_value = _template(8, "原模板 副本")
        with pytest.raises(AgentTemplateNameConflictError, match="同名模板已存在"):
            await service.duplicate(7)
        mock_repo.add.assert_not_called()

    async def test_duplicate_missing_raises_not_found(self, service, mock_repo):
        """源模板不存在 → AgentTemplateNotFoundError。"""
        mock_repo.get.return_value = None
        with pytest.raises(AgentTemplateNotFoundError, match="模板不存在"):
            await service.duplicate(999)


class TestDelete:
    """delete — 404 / 内置默认不可删 / 级联清引用。"""

    async def test_delete_missing_raises_not_found(self, service, mock_repo):
        """repo.get 不存在 → AgentTemplateNotFoundError，无任何副作用。"""
        mock_repo.get.return_value = None
        with pytest.raises(AgentTemplateNotFoundError, match="模板不存在"):
            await service.delete(999)
        mock_repo.list_projects_by_template.assert_not_called()
        mock_repo.delete.assert_not_called()

    async def test_delete_is_default_rejected(self, service, mock_repo):
        """is_default=True（内置/默认模板）→ AgentTemplateBuiltinError，
        不级联、不删除。"""
        mock_repo.get.return_value = _template(1, "默认模板", is_default=True)
        with pytest.raises(AgentTemplateBuiltinError, match="内置模板不可删除"):
            await service.delete(1)
        mock_repo.list_projects_by_template.assert_not_called()
        mock_repo.delete.assert_not_called()

    async def test_delete_unreferenced_succeeds(self, service, mock_repo):
        """未被引用：直接 repo.delete，成功返回 None。"""
        mock_repo.get.return_value = _template(1, "普通模板")
        mock_repo.list_projects_by_template.return_value = []
        assert await service.delete(1) is None
        mock_repo.list_projects_by_template.assert_awaited_once_with(1)
        mock_repo.delete.assert_awaited_once_with(1)

    async def test_delete_cascades_clear_template_id_on_referencing_projects(
        self, service, mock_repo, mock_project_repo
    ):
        """被引用：级联清空每个引用项目 config.template_id（project_repo.update）
        后删除模板（spec §9.2.4 评审 C2：一次写，回退默认模板装配）。"""
        mock_repo.get.return_value = _template(1, "被引用模板")
        p1 = _project(11, "项目甲", "1")
        p2 = _project(22, "项目乙", "1")
        mock_repo.list_projects_by_template.return_value = [p1, p2]

        assert await service.delete(1) is None

        mock_repo.delete.assert_awaited_once_with(1)
        # 级联：每个引用项目都走 project_repo.update 且 config.template_id 置 None
        assert mock_project_repo.update.await_count == 2
        updated_configs = [
            call.args[0].config.template_id for call in mock_project_repo.update.await_args_list
        ]
        assert updated_configs == [None, None]
        # 其他项目字段不受影响
        first_updated = mock_project_repo.update.await_args_list[0].args[0]
        assert first_updated.name == "项目甲"
        assert first_updated.id == p1.id

    async def test_delete_repo_delete_false_raises_not_found(self, service, mock_repo):
        """repo.delete 返回 False（竞态：已被删）→ AgentTemplateNotFoundError。"""
        mock_repo.get.return_value = _template(1, "普通模板")
        mock_repo.list_projects_by_template.return_value = []
        mock_repo.delete.return_value = False
        with pytest.raises(AgentTemplateNotFoundError, match="模板不存在"):
            await service.delete(1)
