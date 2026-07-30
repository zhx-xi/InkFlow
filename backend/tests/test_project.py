"""项目领域模型、仓储和服务测试 — TDD RED 阶段。

验证内容:
    - ProjectCreate / ProjectUpdate Pydantic DTO 验证（应通过）
    - ProjectRepository CRUD 操作（因 ImportError 失败 — RED 阶段）
    - ProjectService 业务逻辑（因 ImportError 失败 — RED 阶段）
"""

import pytest
from pydantic import ValidationError

from inkflow.domain.models.project import (
    Genre,
    ProjectCreate,
    ProjectUpdate,
)


class TestProjectCreateValidation:
    """Pydantic DTO 层面的创建验证测试 — 应全部通过。"""

    def test_create_with_valid_data(self):
        """正常创建，所有字段合法。"""
        project = ProjectCreate(
            name="测试小说",
            genre=Genre.XUANHUAN,
            language="zh-CN",
            target_words=100000,
        )
        assert project.name == "测试小说"
        assert project.genre == Genre.XUANHUAN
        assert project.language == "zh-CN"
        assert project.target_words == 100000

    def test_create_empty_name_raises(self):
        """空名称应抛出 ValidationError（匹配"项目名称不能为空"）。"""
        with pytest.raises(ValidationError, match="项目名称不能为空"):
            ProjectCreate(name="")

    def test_create_whitespace_name_raises(self):
        """纯空格名称应抛出 ValidationError。"""
        with pytest.raises(ValidationError, match="项目名称不能为空"):
            ProjectCreate(name="   ")

    def test_create_name_too_long_raises(self):
        """超过 100 字符的名称应抛出 ValidationError。"""
        with pytest.raises(ValidationError, match="项目名称不能超过 100 个字符"):
            ProjectCreate(name="长" * 101)

    def test_create_defaults(self):
        """默认值：genre='其他', language='zh-CN', target_words=0, config.model='gpt-4o'。"""
        project = ProjectCreate(name="默认测试")
        assert project.genre == Genre.QITA
        assert project.language == "zh-CN"
        assert project.target_words == 0
        assert project.config.model == "gpt-4o"


class TestProjectUpdateValidation:
    """更新请求 Pydantic 验证测试 — 应全部通过。"""

    def test_update_partial(self):
        """部分更新：未提供的字段应为 None。"""
        update = ProjectUpdate(name="新名称")
        assert update.name == "新名称"
        assert update.genre is None
        assert update.language is None
        assert update.target_words is None
        assert update.config is None
        assert update.is_deleted is None

    def test_update_empty_name_raises(self):
        """空名称更新应抛出 ValidationError。"""
        with pytest.raises(ValidationError, match="项目名称不能为空"):
            ProjectUpdate(name="")


class TestProjectRepository:
    """Repository CRUD 操作测试 — RED 阶段，因 ImportError 失败。

    预期：inkflow.infrastructure.database 包尚不存在，因此所有测试将因
    ImportError 而失败。这是 TDD RED 阶段的正常行为。
    """

    @pytest.mark.asyncio
    async def test_create_project(self, db_session):
        """创建项目 → get 返回带 ID 的 Project（name='测试小说'）。"""
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
    async def test_list_projects(self, db_session):
        """分页列表 — 创建 2 个项目后 total=2, len=2。"""
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
    async def test_list_projects_with_search(self, db_session):
        """按名称搜索 — search='科幻' 返回 total=1。"""
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
    async def test_update_project(self, db_session):
        """更新名称后 result.name == '新名称'。"""
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
    async def test_soft_delete_project(self, db_session):
        """软删除后 get 返回 None。"""
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


class TestProjectService:
    """Service 业务逻辑测试 — RED 阶段，因 ImportError 失败。

    预期：inkflow.domain.services 包尚不存在，因此所有测试将因
    ImportError 而失败。这是 TDD RED 阶段的正常行为。
    """

    @pytest.mark.asyncio
    async def test_create_project(self, db_session):
        """Service 创建返回完整 Project，id 不为空且 is_deleted=False。"""
        from inkflow.domain.services.project_service import ProjectService

        service = ProjectService(db_session)
        project = await service.create_project(
            name="服务测试",
            genre=Genre.XUANHUAN,
            target_words=100000,
        )
        assert project.id is not None
        assert project.is_deleted is False

    @pytest.mark.asyncio
    async def test_list_projects_with_sort(self, db_session):
        """按名称升序排列。"""
        from inkflow.domain.services.project_service import ProjectService

        service = ProjectService(db_session)
        await service.create_project(name="B项目")
        await service.create_project(name="A项目")

        projects, total = await service.list_projects(sort_by="name", sort_desc=False)
        assert total == 2
        assert projects[0].name == "A项目"
        assert projects[1].name == "B项目"

    @pytest.mark.asyncio
    async def test_soft_delete_then_list_excludes(self, db_session):
        """软删除后列表不应包含该项目。"""
        from inkflow.domain.services.project_service import ProjectService

        service = ProjectService(db_session)
        p1 = await service.create_project(name="保留项目")
        p2 = await service.create_project(name="删除项目")
        await service.soft_delete(p2.id)

        projects, total = await service.list_projects()
        ids = [p.id for p in projects]
        assert p1.id in ids
        assert p2.id not in ids
