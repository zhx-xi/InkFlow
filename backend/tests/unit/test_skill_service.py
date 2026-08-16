"""F39 Skill 服务单元测试 — Mock Repository（RED 批，#258）。

覆盖 spec §2.2（Skill 实体）/§3.3（异常映射）/§5.6（删除保护）/§7（边界
与错误）的服务层（镜像 test_agent_template_service.py 的 Mock 注入模式，
ADR-015）:
- create：frontmatter 后端解析（缺失 name/description / name 格式非法 →
  SkillFrontmatterError 422）→ 同名查重 → 构造实体（id=None、
  source="user_upload"、时间戳填充）→ repo.add
- get / list 委托 repo；get 不存在 → SkillNotFoundError（404）
- update：exclude_unset 部分合并；source="builtin" → SkillBuiltinError
  （409）；改名查重；updated_at 刷新
- delete：不存在 → NotFound；source="builtin" → SkillBuiltinError（409）；
  被 N 个 Agent 引用 → 级联清引用（先移除全部 Agent.skill_ids 中的该 id
  再删，调用顺序用 calls 列表锁定）；repo.delete 返回 False → NotFound
- 错误类守卫：默认消息逐字 + 继承关系 + 不导出 Agent 系错误类

依据: specs/f39-multi-agent/spec.md §2.2 + §3.3（异常映射表）+ §5.6
（删除保护）+ §7（边界情况与错误处理）。

══════════════════════ 设计假设（GREEN 实现者唯一契约）══════════════════════

模块与类（本批新建，当前不存在 → 收集期 ModuleNotFoundError 即预期 RED）:

1. ``inkflow.domain.models.skill``（spec §2.2 逐字）:
   - ``Skill``: id:int|None=None / name:str（唯一，frontmatter name 提取）/
     description:str=""（frontmatter description 提取）/ content:str=""
     （完整 SKILL.md，原样存储）/ source:str="user_upload"
     （"builtin"|"user_upload"）/ created_at / updated_at
   - ``SkillCreate``: content 必填（frontmatter 后端解析 name/description，
     非 DTO 字段）
   - ``SkillUpdate``: 全字段可选（exclude_unset 语义；None = 不修改，
     合并前剔除，镜像 AgentTemplateService；content 更新是否重解析
     frontmatter 父侧未定稿，本批用例不覆盖）

2. ``inkflow.domain.ports.skill_repository.SkillRepositoryProtocol``:
   add / get / get_by_name / list / update / delete

3. ``inkflow.domain.ports.agent_repository.AgentRepositoryProtocol``:
   add / get / get_by_name / list / update / delete / list_agents_by_skill
   （级联清引用反查 + 批量 update 用）

4. ``inkflow.domain.ports.skill_errors`` 错误类（基类 SkillServiceError）:
   - ``SkillServiceError(Exception)`` — 业务校验基类（422/409 映射）
   - ``SkillNotFoundError(Exception)`` — 404；默认消息精确为 **"Skill 不存在"**
     （镜像 agent_template_errors.py：NotFound 不继承 ServiceError）
   - ``SkillNameConflictError(SkillServiceError)`` — 422；默认消息精确为
     **"同名 Skill 已存在（Skill 名称必须唯一）"**
   - ``SkillBuiltinError(SkillServiceError)`` — 409；默认消息精确为
     **"内置 Skill 不可修改或删除"**
   - ``SkillFrontmatterError(SkillServiceError)`` — 422；默认消息精确为
     **"frontmatter 缺失 name/description 或 name 格式非法"**

5. ``inkflow.domain.services.skill_service.SkillService``:
   - ``__init__(self, *, skill_repository: SkillRepositoryProtocol,
     agent_repository: AgentRepositoryProtocol) -> None``
     （双仓储注入：agent_repository 供删除级联清引用）
   - ``async create(self, data: SkillCreate) -> Skill``:
     先解析 ``data.content`` 的 frontmatter：缺失 name/description 或
     name 格式非法（1-64 小写字母数字+连字符；「与目录名一致」属 F40
     上传路径契约，服务层不校验）→ SkillFrontmatterError（不查重）；
     再 ``skill_repository.get_by_name(解析名)`` 查重，命中 →
     SkillNameConflictError；构造 ``Skill(id=None, name=解析名,
     description=解析描述, content=data.content 原样, source="user_upload",
     created_at=updated_at=datetime.now(UTC))``；委托 repo.add
   - ``async get(self, skill_id: int) -> Skill``:
     委托 repo.get；None → SkillNotFoundError（404 语义）
   - ``async list(self) -> builtins.list[Skill]``: 委托 repo
   - ``async update(self, skill_id: int, data: SkillUpdate) -> Skill``:
     先 repo.get，None → NotFound；``source == "builtin"`` →
     SkillBuiltinError（只读保护）；``data.model_fields_set`` 取已设字段
     且剔除 None 后 model_copy 合并；仅当 name 变更时 get_by_name 查重
     （命中且 id 不同 → NameConflictError）；updated_at = datetime.now(UTC)
     刷新，created_at 保留；委托 repo.update(merged)
   - ``async delete(self, skill_id: int) -> None``:
     先 repo.get，None → NotFound；``source == "builtin"`` →
     SkillBuiltinError；``refs = await agent_repository.list_agents_by_skill(
     skill_id)`` 反查引用（spec §2.2「agent_ids 反查」）；对每个引用
     Agent：从其 ``skill_ids`` 移除 ``str(skill_id)`` 后
     ``await agent_repository.update(agent)``（**先清引用再删**，spec §5.6）；
     最后 ``skill_repository.delete(skill_id)``，返回 False（竞态已删）→
     NotFound；成功返回 None

6. 时间戳契约: create/update 填充 created_at/updated_at 为时区感知
   datetime（datetime.now(UTC)）；断言 tzinfo 非空 + create 时
   created_at == updated_at / update 时 created_at 保留。

7. 级联契约: delete 对每个引用 Agent 调 agent_repository.update；
   测试用 calls 列表锁定「全部 update 先于 skill delete」的调用顺序；
   断言 update 收到的 Agent.skill_ids 已不含该 id 且其他字段保留。

⚠️ RED 预期: 被测新模块全部不存在 → 文件顶部 import 报 ModuleNotFoundError
   （首个缺失 = inkflow.domain.models.agent，isort 排序先行）→ 收集期错误
   （pytest exit 2 / collected 0 items / 2 errors，两文件各一）。GREEN 后
   本文件应全绿。
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.agent import Agent
from inkflow.domain.models.skill import Skill, SkillCreate, SkillUpdate
from inkflow.domain.ports.agent_repository import AgentRepositoryProtocol
from inkflow.domain.ports.skill_errors import (
    SkillBuiltinError,
    SkillFrontmatterError,
    SkillNameConflictError,
    SkillNotFoundError,
    SkillServiceError,
)
from inkflow.domain.ports.skill_repository import SkillRepositoryProtocol
from inkflow.domain.services.skill_service import SkillService

TS = datetime(2026, 8, 1, 10, 0, 0)

VALID_CONTENT = (
    "---\nname: web-research\ndescription: 网络调研方法论\n---\n"
    "# 调研流程\n1. 明确问题\n2. 检索信源\n"
)
NO_NAME_CONTENT = "---\ndescription: 网络调研方法论\n---\n# 无 name frontmatter"
NO_DESC_CONTENT = "---\nname: web-research\n---\n# 无 description frontmatter"
BAD_NAME_CONTENT = "---\nname: Web Research\ndescription: 网络调研方法论\n---\n# name 格式非法"


def _arg(call, name, pos=None, default=None):
    """宽松取参：kwargs 键优先、位置回退（实现传参形态未定稿，勿锁位置参）。"""
    if name in call.kwargs:
        return call.kwargs[name]
    if pos is not None and len(call.args) > pos:
        return call.args[pos]
    return default


def _skill(skill_id: int, name: str, **kw) -> Skill:
    """构造测试用 Skill 实体（固定时间戳，便于断言）。"""
    return Skill(id=skill_id, name=name, content=VALID_CONTENT, created_at=TS, updated_at=TS, **kw)


def _agent(agent_id: int, name: str, **kw) -> Agent:
    """构造引用 skill 的 Agent 实体（skill_ids 为 str(skill_id) 列表，spec §2.1）。"""
    return Agent(id=agent_id, name=name, created_at=TS, updated_at=TS, **kw)


@pytest.fixture
def mock_skill_repo() -> MagicMock:
    """Mock SkillRepositoryProtocol — 默认全方法可用，测试按需覆盖。"""
    repo = MagicMock(spec=SkillRepositoryProtocol)
    repo.add = AsyncMock(side_effect=lambda s: s)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=[])
    repo.update = AsyncMock(side_effect=lambda s: s)
    repo.delete = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def mock_agent_repo() -> MagicMock:
    """Mock AgentRepositoryProtocol — 删除级联清引用用。"""
    repo = MagicMock(spec=AgentRepositoryProtocol)
    repo.add = AsyncMock(side_effect=lambda a: a)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=[])
    repo.update = AsyncMock(side_effect=lambda a: a)
    repo.delete = AsyncMock(return_value=True)
    repo.list_agents_by_skill = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def service(mock_skill_repo: MagicMock, mock_agent_repo: MagicMock) -> SkillService:
    """被测服务实例（双 Mock 仓储注入，ADR-015）。"""
    return SkillService(skill_repository=mock_skill_repo, agent_repository=mock_agent_repo)


class TestCreate:
    """创建 — frontmatter 解析 / 同名冲突 / 默认字段编排。"""

    async def test_create_parses_frontmatter_and_delegates(self, service, mock_skill_repo):
        """create：frontmatter 解析出 name/description → 查重未命中 → 构造实体
        （id=None、source="user_upload"、content 原样、时间戳填充）→ repo.add。"""
        saved = await service.create(SkillCreate(content=VALID_CONTENT))
        mock_skill_repo.get_by_name.assert_awaited_once()
        assert _arg(mock_skill_repo.get_by_name.await_args, "name", 0) == "web-research"
        mock_skill_repo.add.assert_awaited_once()
        sk = _arg(mock_skill_repo.add.await_args, "skill", 0)
        assert sk.id is None  # id 由 repo 分配
        assert sk.name == "web-research"  # frontmatter name 提取
        assert sk.description == "网络调研方法论"  # frontmatter description 提取
        assert sk.content == VALID_CONTENT  # 完整 SKILL.md 原样存储
        assert sk.source == "user_upload"  # 用户上传默认来源
        assert sk.created_at == sk.updated_at
        assert sk.created_at.tzinfo is not None  # datetime.now(UTC) 时区感知
        assert saved is sk  # 直接返回 repo.add 结果

    async def test_create_missing_name_rejected(self, service, mock_skill_repo):
        """frontmatter 缺失 name → SkillFrontmatterError（422），不查重不落库。"""
        with pytest.raises(SkillFrontmatterError, match="frontmatter"):
            await service.create(SkillCreate(content=NO_NAME_CONTENT))
        mock_skill_repo.get_by_name.assert_not_called()
        mock_skill_repo.add.assert_not_called()

    async def test_create_missing_description_rejected(self, service, mock_skill_repo):
        """frontmatter 缺失 description → SkillFrontmatterError（422）。"""
        with pytest.raises(SkillFrontmatterError, match="frontmatter"):
            await service.create(SkillCreate(content=NO_DESC_CONTENT))
        mock_skill_repo.add.assert_not_called()

    async def test_create_illegal_name_rejected(self, service, mock_skill_repo):
        """frontmatter name 格式非法（大写/空格，须 1-64 小写字母数字+连字符）
        → SkillFrontmatterError（422）。"""
        with pytest.raises(SkillFrontmatterError, match="frontmatter"):
            await service.create(SkillCreate(content=BAD_NAME_CONTENT))
        mock_skill_repo.add.assert_not_called()

    async def test_create_name_conflict_raises(self, service, mock_skill_repo):
        """解析出的 name 已存在 → SkillNameConflictError（422），且不落库。"""
        mock_skill_repo.get_by_name.return_value = _skill(5, "web-research")
        with pytest.raises(SkillNameConflictError, match="同名"):
            await service.create(SkillCreate(content=VALID_CONTENT))
        mock_skill_repo.add.assert_not_called()


class TestGet:
    """get 委托与 404 语义。"""

    async def test_get_found(self, service, mock_skill_repo):
        """get 命中返回实体。"""
        entity = _skill(3, "web-research")
        mock_skill_repo.get.return_value = entity
        assert await service.get(3) is entity
        mock_skill_repo.get.assert_awaited_once_with(3)

    async def test_get_missing_raises_not_found(self, service, mock_skill_repo):
        """get 不存在 → SkillNotFoundError（消息「Skill 不存在」）。"""
        mock_skill_repo.get.return_value = None
        with pytest.raises(SkillNotFoundError, match="不存在"):
            await service.get(999)


class TestList:
    """list 委托。"""

    async def test_list_delegates(self, service, mock_skill_repo):
        """list 直接返回 repo.list 结果。"""
        items = [_skill(1, "a"), _skill(2, "b")]
        mock_skill_repo.list.return_value = items
        assert await service.list() == items
        mock_skill_repo.list.assert_awaited_once()


class TestUpdate:
    """update — 404 / 内置只读 / 部分合并 / 改名查重。"""

    async def test_update_missing_raises_not_found(self, service, mock_skill_repo):
        """update 目标不存在 → SkillNotFoundError。"""
        mock_skill_repo.get.return_value = None
        with pytest.raises(SkillNotFoundError, match="不存在"):
            await service.update(999, SkillUpdate(description="d2"))

    async def test_update_builtin_rejected(self, service, mock_skill_repo):
        """source="builtin"（内置只读）→ SkillBuiltinError（409），且不落库。"""
        mock_skill_repo.get.return_value = _skill(1, "builtin-skill", source="builtin")
        with pytest.raises(SkillBuiltinError, match="内置"):
            await service.update(1, SkillUpdate(description="d2"))
        mock_skill_repo.update.assert_not_called()

    async def test_update_partial_merge_and_refresh_updated_at(self, service, mock_skill_repo):
        """部分更新：仅传入字段合并；created_at 保留；updated_at 刷新为 now(UTC)。"""
        existing = _skill(3, "web-research", description="d1")
        mock_skill_repo.get.return_value = existing
        merged = await service.update(3, SkillUpdate(description="d2"))

        mock_skill_repo.get.assert_awaited_once_with(3)
        mock_skill_repo.update.assert_awaited_once()
        updated = _arg(mock_skill_repo.update.await_args, "skill", 0)
        assert updated.id == 3
        assert updated.name == "web-research"  # 未传字段不变
        assert updated.description == "d2"
        assert updated.content == VALID_CONTENT  # content 原样保留
        assert updated.source == "user_upload"
        assert updated.created_at == TS  # created_at 保留
        assert updated.updated_at.tzinfo is not None  # 刷新为 now(UTC)
        mock_skill_repo.get_by_name.assert_not_called()  # name 未变，不查重
        assert merged is updated

    async def test_update_explicit_none_means_no_change(self, service, mock_skill_repo):
        """显式 None 字段不应用（None = 不修改，同 F13）。"""
        existing = _skill(3, "web-research", description="d1")
        mock_skill_repo.get.return_value = existing
        await service.update(3, SkillUpdate(description=None))
        updated = _arg(mock_skill_repo.update.await_args, "skill", 0)
        assert updated.description == "d1"  # 未被置 None

    async def test_update_rename_conflict_raises(self, service, mock_skill_repo):
        """改名命中其他 Skill → SkillNameConflictError，且不落库。"""
        mock_skill_repo.get.return_value = _skill(3, "a")
        mock_skill_repo.get_by_name.return_value = _skill(9, "b")  # 其他 id 已占用
        with pytest.raises(SkillNameConflictError, match="同名"):
            await service.update(3, SkillUpdate(name="b"))
        mock_skill_repo.update.assert_not_called()

    async def test_update_rename_to_own_name_no_conflict(self, service, mock_skill_repo):
        """name 未变化（与现有值相同）→ 不查重、直接更新。"""
        mock_skill_repo.get.return_value = _skill(3, "web-research")
        await service.update(3, SkillUpdate(name="web-research"))
        mock_skill_repo.get_by_name.assert_not_called()
        mock_skill_repo.update.assert_awaited_once()


class TestDelete:
    """delete — 404 / 内置只读 / 级联清引用（先清引用再删）。"""

    async def test_delete_missing_raises_not_found(self, service, mock_skill_repo, mock_agent_repo):
        """repo.get 不存在 → SkillNotFoundError，无任何副作用。"""
        mock_skill_repo.get.return_value = None
        with pytest.raises(SkillNotFoundError, match="不存在"):
            await service.delete(999)
        mock_agent_repo.list_agents_by_skill.assert_not_called()
        mock_skill_repo.delete.assert_not_called()

    async def test_delete_builtin_rejected(self, service, mock_skill_repo, mock_agent_repo):
        """source="builtin"（内置只读）→ SkillBuiltinError，不级联不删除。"""
        mock_skill_repo.get.return_value = _skill(1, "builtin-skill", source="builtin")
        with pytest.raises(SkillBuiltinError, match="内置"):
            await service.delete(1)
        mock_agent_repo.list_agents_by_skill.assert_not_called()
        mock_skill_repo.delete.assert_not_called()

    async def test_delete_unreferenced_succeeds(self, service, mock_skill_repo, mock_agent_repo):
        """未被引用：直接 repo.delete，成功返回 None。"""
        mock_skill_repo.get.return_value = _skill(3, "web-research")
        assert await service.delete(3) is None
        mock_agent_repo.list_agents_by_skill.assert_awaited_once()
        assert _arg(mock_agent_repo.list_agents_by_skill.await_args, "skill_id", 0) == 3
        mock_skill_repo.delete.assert_awaited_once()
        assert _arg(mock_skill_repo.delete.await_args, "skill_id", 0) == 3
        mock_agent_repo.update.assert_not_called()

    async def test_delete_cascades_clear_skill_ids_before_delete(
        self, service, mock_skill_repo, mock_agent_repo
    ):
        """被 N 个 Agent 引用：先逐个移除 Agent.skill_ids 中的该 id（agent_repo.
        update）再删 skill（spec §5.6 级联清引用，calls 列表锁调用顺序）。"""
        writer = _agent(2, "写手", skill_ids=["3", "9"])
        architect = _agent(6, "架构师", skill_ids=["3"])
        mock_skill_repo.get.return_value = _skill(3, "web-research")

        calls: list[str] = []

        async def _record_update(agent: Agent) -> Agent:
            calls.append(f"update:{agent.name}")
            return agent

        async def _record_delete(skill_id: int) -> bool:
            calls.append(f"delete:{skill_id}")
            return True

        mock_agent_repo.list_agents_by_skill = AsyncMock(
            side_effect=lambda sid: [writer, architect] if sid == 3 else []
        )
        mock_agent_repo.update = AsyncMock(side_effect=_record_update)
        mock_skill_repo.delete = AsyncMock(side_effect=_record_delete)

        assert await service.delete(3) is None

        # 顺序契约：全部 update（清引用）先于 skill delete（spec §5.6）
        assert calls == ["update:写手", "update:架构师", "delete:3"]
        mock_agent_repo.list_agents_by_skill.assert_awaited_once()
        assert _arg(mock_agent_repo.list_agents_by_skill.await_args, "skill_id", 0) == 3
        mock_skill_repo.delete.assert_awaited_once()
        # 每个引用 Agent 的 skill_ids 已移除该 id，其他字段保留
        first = _arg(mock_agent_repo.update.await_args_list[0], "agent", 0)
        assert first is writer
        assert first.skill_ids == ["9"]
        assert first.name == "写手"
        second = _arg(mock_agent_repo.update.await_args_list[1], "agent", 0)
        assert second is architect
        assert second.skill_ids == []

    async def test_delete_repo_delete_false_raises_not_found(self, service, mock_skill_repo):
        """repo.delete 返回 False（竞态：已被删）→ SkillNotFoundError。"""
        mock_skill_repo.get.return_value = _skill(3, "web-research")
        mock_skill_repo.delete.return_value = False
        with pytest.raises(SkillNotFoundError, match="不存在"):
            await service.delete(3)


class TestSkillErrorsGuard:
    """错误类守卫：默认文案 + 继承关系 + 不导出他域错误类（规则 1m）。"""

    def test_error_default_messages_and_hierarchy(self) -> None:
        """4 错误类默认消息逐字 + 继承关系（镜像 agent_template_errors.py）。"""
        assert str(SkillNotFoundError()) == "Skill 不存在"
        assert str(SkillNameConflictError()) == "同名 Skill 已存在（Skill 名称必须唯一）"
        assert str(SkillBuiltinError()) == "内置 Skill 不可修改或删除"
        assert str(SkillFrontmatterError()) == "frontmatter 缺失 name/description 或 name 格式非法"
        # 422/409 类继承 SkillServiceError；404 类独立（镜像 agent_template_errors）
        assert issubclass(SkillNameConflictError, SkillServiceError)
        assert issubclass(SkillBuiltinError, SkillServiceError)
        assert issubclass(SkillFrontmatterError, SkillServiceError)
        assert not issubclass(SkillNotFoundError, SkillServiceError)
        assert issubclass(SkillServiceError, Exception)

    def test_no_foreign_error_classes_leaked(self) -> None:
        """skill_errors 不导出 Agent 系错误类（防复制粘贴残留）。"""
        import inkflow.domain.ports.skill_errors as skill_errors_module

        assert not hasattr(skill_errors_module, "AgentNotFoundError")
        assert not hasattr(skill_errors_module, "AgentNameConflictError")
        assert not hasattr(skill_errors_module, "AgentBuiltinError")
