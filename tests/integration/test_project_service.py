"""项目服务层集成测试 — 真实 in-memory SQLite。

测试范围：ProjectService 业务逻辑（创建、列表排序、软删除后排除）。
需 pytest marker: @pytest.mark.project
"""

import pytest

from inkflow.domain.services.project_service import ProjectService


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
