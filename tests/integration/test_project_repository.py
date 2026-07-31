"""项目仓储层集成测试 — 真实 in-memory SQLite。

测试范围：ProjectRepository CRUD 操作。
需 pytest marker: @pytest.mark.project
"""

import pytest


class TestProjectRepository:
    """Repository CRUD 操作测试."""

    @pytest.mark.asyncio
    @pytest.mark.project
    async def test_create_project(self, db_session):
        """创建项目 → get 返回带 ID 的 Project."""
        from inkflow.infrastructure.database.models.project import ProjectORM
        from inkflow.infrastructure.database.repositories.project_repo import (
            SQLiteProjectRepository,
        )

        repo = SQLiteProjectRepository(db_session)
        orm = ProjectORM(name="测试小说", genre="玄幻", language="zh-CN")
        db_session.add(orm)
        await db_session.commit()
        await db_session.refresh(orm)

        result = await repo.get(orm.id)
        assert result is not None
        assert result.name == "测试小说"

    @pytest.mark.asyncio
    @pytest.mark.project
    async def test_list_projects(self, db_session):
        """分页列表 — 创建 2 个项目后 total=2, len=2."""
        from inkflow.infrastructure.database.models.project import ProjectORM
        from inkflow.infrastructure.database.repositories.project_repo import (
            SQLiteProjectRepository,
        )

        repo = SQLiteProjectRepository(db_session)
        p1 = ProjectORM(name="小说A", genre="玄幻", language="zh-CN")
        p2 = ProjectORM(name="科幻巨作", genre="科幻", language="zh-CN")
        db_session.add_all([p1, p2])
        await db_session.commit()

        projects, total = await repo.list_all()
        assert total == 2
        assert len(projects) == 2

    @pytest.mark.asyncio
    @pytest.mark.project
    async def test_list_projects_with_search(self, db_session):
        """按名称搜索 — search='科幻' 返回 total=1."""
        from inkflow.infrastructure.database.models.project import ProjectORM
        from inkflow.infrastructure.database.repositories.project_repo import (
            SQLiteProjectRepository,
        )

        repo = SQLiteProjectRepository(db_session)
        p1 = ProjectORM(name="小说A", genre="玄幻", language="zh-CN")
        p2 = ProjectORM(name="科幻巨作", genre="科幻", language="zh-CN")
        db_session.add_all([p1, p2])
        await db_session.commit()

        projects, total = await repo.list_all(search="科幻")
        assert total == 1

    @pytest.mark.asyncio
    @pytest.mark.project
    async def test_update_project(self, db_session):
        """更新名称后 result.name == '新名称'."""
        from inkflow.infrastructure.database.models.project import ProjectORM
        from inkflow.infrastructure.database.repositories.project_repo import (
            SQLiteProjectRepository,
        )

        repo = SQLiteProjectRepository(db_session)
        orm = ProjectORM(name="原始名称", genre="其他", language="zh-CN")
        db_session.add(orm)
        await db_session.commit()
        await db_session.refresh(orm)

        orm.name = "新名称"
        result = await repo.update(orm)
        assert result.name == "新名称"

    @pytest.mark.asyncio
    @pytest.mark.project
    async def test_soft_delete_project(self, db_session):
        """软删除后 get 返回 None."""
        from inkflow.infrastructure.database.models.project import ProjectORM
        from inkflow.infrastructure.database.repositories.project_repo import (
            SQLiteProjectRepository,
        )

        repo = SQLiteProjectRepository(db_session)
        orm = ProjectORM(name="待删除项目", genre="其他", language="zh-CN")
        db_session.add(orm)
        await db_session.commit()
        await db_session.refresh(orm)

        success = await repo.soft_delete(orm.id)
        assert success is True
        result = await repo.get(orm.id)
        assert result is None
