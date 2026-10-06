"""项目服务层集成测试 — 真实 in-memory SQLite。

测试范围：ProjectService 业务逻辑（创建、列表排序、软删除后排除）。
需 pytest marker: @pytest.mark.project
"""

import pytest

from inkflow.domain.ports.world_errors import (
    WorldCategoryMissingError,
    WorldRootConflictError,
)
from inkflow.domain.services.project_service import ProjectService
from inkflow.domain.services.world_service import WorldService
from inkflow.infrastructure.database.repositories.project_repo import SQLiteProjectRepository
from inkflow.infrastructure.database.repositories.world_repo import SQLiteWorldRepository


class TestProjectService:
    """Service 业务逻辑测试."""

    @pytest.mark.asyncio
    @pytest.mark.project
    async def test_create_project(self, db_session):
        """Service 创建返回完整 Project，id 不为空且 is_deleted=False."""
        service = ProjectService(db_session)
        project = await service.create_project(
            name="服务测试",
            tags=["玄幻"],
            target_words=100000,
        )
        assert project.id is not None
        assert project.is_deleted is False

    @pytest.mark.asyncio
    @pytest.mark.project
    async def test_list_projects_with_sort(self, db_session):
        """按名称升序排列."""
        service = ProjectService(db_session)
        await service.create_project(name="B项目")
        await service.create_project(name="A项目")

        projects, total = await service.list_projects(sort_by="name", sort_desc=False)
        assert total == 2
        assert projects[0].name == "A项目"
        assert projects[1].name == "B项目"

    @pytest.mark.asyncio
    @pytest.mark.project
    async def test_soft_delete_then_list_excludes(self, db_session):
        """软删除后列表不应包含该项目."""
        service = ProjectService(db_session)
        p1 = await service.create_project(name="保留项目")
        p2 = await service.create_project(name="删除项目")
        await service.soft_delete(p2.id)

        projects, _ = await service.list_projects()
        ids = [p.id for p in projects]
        assert p1.id in ids
        assert p2.id not in ids


class TestCreateProjectSeedsWorldRoot:
    """#1481 建项目自动建根 —— 真实 SQLite + 真实 WorldService（等价 deps 装配）.

    RED 形态：WorldService 尚无 ensure_root_setting → AttributeError → FAILED。
    """

    @staticmethod
    def _service(db_session) -> ProjectService:
        """装配等价物 = `deps.get_project_service`（注入 `ensure_root_setting` 钩子）."""
        world_svc = WorldService(
            repository=SQLiteWorldRepository(db_session),
            project_repo=SQLiteProjectRepository(db_session),
        )
        return ProjectService(db_session, root_initializer=world_svc.ensure_root_setting)

    @staticmethod
    def _world_svc(db_session) -> WorldService:
        """读侧世界服务（同一 session）."""
        return WorldService(
            repository=SQLiteWorldRepository(db_session),
            project_repo=SQLiteProjectRepository(db_session),
        )

    @pytest.mark.asyncio
    @pytest.mark.project
    async def test_new_project_has_exactly_one_root(self, db_session):
        """新建项目 → 世界观库立即含**恰好 1 个**根条目（category == ""、parent_id is None）."""
        project = await self._service(db_session).create_project(name="自带根的书")

        items, total = await self._world_svc(db_session).list_settings(project.id)

        assert total == 1, "新建项目应立即自带恰好 1 个世界观根条目"
        root = items[0]
        assert root.name == "世界观总纲"
        assert root.category == ""
        assert root.parent_id is None

        roots, root_total = await self._world_svc(db_session).list_settings(
            project.id, top_level_only=True
        )
        assert root_total == 1
        assert roots[0].id == root.id

    @pytest.mark.asyncio
    @pytest.mark.project
    async def test_two_projects_each_own_root(self, db_session):
        """两个新项目各自独立一根（不串根）."""
        svc = self._service(db_session)
        p1 = await svc.create_project(name="甲书")
        p2 = await svc.create_project(name="乙书")

        world_svc = self._world_svc(db_session)
        _, total1 = await world_svc.list_settings(p1.id, top_level_only=True)
        _, total2 = await world_svc.list_settings(p2.id, top_level_only=True)

        assert (total1, total2) == (1, 1)

    @pytest.mark.asyncio
    @pytest.mark.project
    async def test_issue_journey_register_category_then_child_under_root(self, db_session):
        """#1481 复现路径闭环：建项目 → 注册分类 → 在根下建条目**全部成功**（不再手工先建根）."""
        project = await self._service(db_session).create_project(name="闭环书")
        world_svc = self._world_svc(db_session)

        root = await world_svc.get_root_setting(project.id)
        assert root is not None, "建项目后必须能直接取到根（无需先探测/先建）"
        await world_svc.create_category(project.id, "门派设定")

        child = await world_svc.create_setting(
            project.id, "门派甲", category="门派设定", content="x", parent_id=root.id
        )

        assert child.parent_id == root.id
        assert child.category == "门派设定"

    @pytest.mark.asyncio
    @pytest.mark.project
    async def test_non_root_with_unregistered_category_still_422(self, db_session):
        """#834/#1321 分类前置**不回归**：根下建条目而分类未注册 → WorldCategoryMissingError."""
        project = await self._service(db_session).create_project(name="分类前置书")
        world_svc = self._world_svc(db_session)
        root = await world_svc.get_root_setting(project.id)
        assert root is not None

        with pytest.raises(WorldCategoryMissingError):
            await world_svc.create_setting(
                project.id, "门派甲", category="门派设定", parent_id=root.id
            )

    @pytest.mark.asyncio
    @pytest.mark.project
    async def test_second_root_still_rejected(self, db_session):
        """#834 根单例不变量**不回归**：已有根（自动建的）再建根 → WorldRootConflictError（422）."""
        project = await self._service(db_session).create_project(name="单根书")

        with pytest.raises(WorldRootConflictError):
            await self._world_svc(db_session).create_setting(project.id, "又一根")
