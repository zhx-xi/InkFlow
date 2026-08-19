"""F39 Agent 实体服务单元测试 — Mock Repository（RED 批，#258）。

覆盖 spec §2.1（Agent 实体）/§3.3（异常映射）/§5.6（删除保护）/§7（边界
与错误）的服务层（镜像 test_agent_template_service.py 的 Mock 注入模式，
ADR-015）:
- create：同名查重 → tool_ids 目录外工具名 → skill_ids 含不存在 id →
  构造实体（id=None、builtin=False、时间戳填充）→ repo.add
- get / list 委托 repo；get 不存在 → AgentNotFoundError（404）
- update：exclude_unset 部分合并；builtin=True → AgentBuiltinError（409）；
  改名查重；tool_ids/skill_ids 白名单校验同 create；updated_at 刷新
- delete：不存在 → AgentNotFoundError（404）；builtin=True →
  AgentBuiltinError（409）；成功 repo.delete；repo.delete 返回 False
  （竞态已删）→ NotFound
- 错误类守卫：默认消息逐字 + 继承关系 + 不导出 AgentTemplate 系错误类

依据: specs/f39-multi-agent/spec.md §2.1 + §3.3（异常映射表）+ §5.6
（删除保护）+ §7（边界情况与错误处理）。

══════════════════════ 设计假设（GREEN 实现者唯一契约）══════════════════════

模块与类（本批新建，当前不存在 → 收集期 ModuleNotFoundError 即预期 RED）:

1. ``inkflow.domain.models.agent``（spec §2.1 逐字）:
   - ``Agent``: id:int|None=None / name:str（唯一，去空白非空）/
     description:str="" / icon:str="" / system_prompt:str="" /
     tool_ids:list[str]=[]（工具目录 name 列表）/ skill_ids:list[str]=[]
     （str(skill_id) 字符串化列表）/ model_override:str|None=None /
     temperature_override:float|None=None（ge=0.0 le=2.0）/
     builtin:bool=False / created_at / updated_at
   - ``AgentCreate``: name 必填 + 上述可编辑字段（无 id/builtin/时间戳）
   - ``AgentUpdate``: 全字段可选（exclude_unset 语义；None = 不修改，
     合并前剔除，镜像 AgentTemplateService）

2. ``inkflow.domain.ports.agent_repository.AgentRepositoryProtocol``:
   add / get / get_by_name / list / update / delete / list_agents_by_skill

3. ``inkflow.domain.ports.skill_repository.SkillRepositoryProtocol``:
   add / get / get_by_name / list / update / delete（skill_ids 白名单查询用）

4. ``inkflow.domain.ports.agent_errors`` 错误类（基类 AgentServiceError）:
   - ``AgentServiceError(Exception)`` — 业务校验基类（422/409 映射）
   - ``AgentNotFoundError(Exception)`` — 404；默认消息精确为 **"Agent 不存在"**
     （镜像 agent_template_errors.py：NotFound 不继承 ServiceError）
   - ``AgentNameConflictError(AgentServiceError)`` — 422；默认消息精确为
     **"同名 Agent 已存在（Agent 名称必须唯一）"**
   - ``AgentBuiltinError(AgentServiceError)`` — 409；默认消息精确为
     **"内置 Agent 不可修改或删除"**
   - ``ToolReferenceError(AgentServiceError)`` — 422；默认消息精确为
     **"tool_ids 含目录外工具名"**
   - ``SkillReferenceError(AgentServiceError)`` — 422；默认消息精确为
     **"skill_ids 含不存在的 Skill"**

5. ``inkflow.domain.services.agent_entity_service.AgentEntityService``:
   - ``__init__(self, *, agent_repository: AgentRepositoryProtocol,
     skill_repository: SkillRepositoryProtocol) -> None``
     （双仓储注入：skill_repository 供 skill_ids 白名单校验查询）
   - ``async create(self, data: AgentCreate) -> Agent``:
     先 ``agent_repository.get_by_name(data.name)`` 查重，命中 →
     AgentNameConflictError；tool_ids 逐个对工具目录（服务内部 import
     TOOL_REGISTRY 常量）校验，含目录外工具名 → ToolReferenceError
     （只锁错误语义，不锁校验实现细节）；skill_ids 逐个
     ``skill_repository.get(int(skill_id))`` 查询，任一缺失 →
     SkillReferenceError；构造 ``Agent(id=None, builtin=False, ...)``，
     ``created_at = updated_at = datetime.now(UTC)``；委托 repo.add
   - ``async get(self, agent_id: int) -> Agent``:
     委托 repo.get；None → AgentNotFoundError（404 语义）
   - ``async list(self) -> builtins.list[Agent]``: 委托 repo
   - ``async update(self, agent_id: int, data: AgentUpdate) -> Agent``:
     先 repo.get，None → NotFound；``builtin=True`` → AgentBuiltinError
     （只读保护）；``data.model_fields_set`` 取已设字段且剔除 None 后
     model_copy 合并；仅当 name 变更时 get_by_name 查重（命中且 id 不同 →
     NameConflictError）；tool_ids/skill_ids 白名单校验同 create
     （仅校验本次传入的字段）；updated_at = datetime.now(UTC) 刷新，
     created_at 保留；委托 repo.update(merged)
   - ``async delete(self, agent_id: int) -> None``:
     先 repo.get，None → NotFound；``builtin=True`` → AgentBuiltinError；
     委托 repo.delete(agent_id)，返回 False（竞态已删）→ NotFound；
     成功返回 None（自定义 Agent 无引用面直接删，spec §5.6/§7 ⑧）

6. 时间戳契约: create/update 填充 created_at/updated_at 为时区感知
   datetime（datetime.now(UTC)）；断言 tzinfo 非空 + create 时
   created_at == updated_at / update 时 created_at 保留。

✅ 契约已裁定（2026-08-16 父侧）: F4 已占用
   ``inkflow.domain.services.agent_service``（编排 AgentService），F39 实体服务放新模块
   ``agent_entity_service`` + 类 ``AgentEntityService``（选项 a），本文件 import 已随之更新。

⚠️ RED 预期: 被测新模块全部不存在 → 文件顶部 import 报 ModuleNotFoundError
   （首个缺失 = inkflow.domain.models.agent）→ 收集期错误（pytest exit 2 /
   collected 0 items / 2 errors，两文件各一）。GREEN 后本文件应全绿。
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.agent import Agent, AgentCreate, AgentUpdate
from inkflow.domain.ports.agent_errors import (
    AgentBuiltinError,
    AgentNameConflictError,
    AgentNotFoundError,
    AgentServiceError,
    SkillReferenceError,
    ToolReferenceError,
)
from inkflow.domain.ports.agent_repository import AgentRepositoryProtocol
from inkflow.domain.ports.skill_repository import SkillRepositoryProtocol
from inkflow.domain.services.agent_entity_service import AgentEntityService as AgentService

TS = datetime(2026, 8, 1, 10, 0, 0)
# 工具目录已注册 name（spec §2.3 表；save_draft 为 F39 MODIFY 待补，不引用）
VALID_TOOL_IDS = ("search_characters", "count_words")


def _arg(call, name, pos=None, default=None):
    """宽松取参：kwargs 键优先、位置回退（实现传参形态未定稿，勿锁位置参）。"""
    if name in call.kwargs:
        return call.kwargs[name]
    if pos is not None and len(call.args) > pos:
        return call.args[pos]
    return default


def _agent(agent_id: int, name: str, **kw) -> Agent:
    """构造测试用 Agent 实体（固定时间戳，便于断言）。"""
    return Agent(id=agent_id, name=name, created_at=TS, updated_at=TS, **kw)


def _skill_ref(skill_id: int) -> SimpleNamespace:
    """skill 仓储返回值（鸭子对象：服务层仅判存在性，规则 1m 第三轨）。"""
    return SimpleNamespace(id=skill_id, name=f"skill-{skill_id}")


@pytest.fixture
def mock_agent_repo() -> MagicMock:
    """Mock AgentRepositoryProtocol — 默认全方法可用，测试按需覆盖。"""
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
def mock_skill_repo() -> MagicMock:
    """Mock SkillRepositoryProtocol — skill_ids 白名单校验查询。"""
    repo = MagicMock(spec=SkillRepositoryProtocol)
    repo.add = AsyncMock(side_effect=lambda s: s)
    repo.get = AsyncMock(return_value=None)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.list = AsyncMock(return_value=[])
    repo.update = AsyncMock(side_effect=lambda s: s)
    repo.delete = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def service(mock_agent_repo: MagicMock, mock_skill_repo: MagicMock) -> AgentService:
    """被测服务实例（双 Mock 仓储注入，ADR-015）。"""
    return AgentService(agent_repository=mock_agent_repo, skill_repository=mock_skill_repo)


class TestCreate:
    """创建 — 白名单校验 / 同名冲突 / 默认字段编排。"""

    async def test_create_builds_entity_and_delegates(
        self, service, mock_agent_repo, mock_skill_repo
    ):
        """create：查重未命中 → 白名单全过 → 构造实体（id=None、builtin=False、
        时间戳填充）→ repo.add；skill_ids 逐个查询 skill 仓储。"""
        mock_skill_repo.get = AsyncMock(
            side_effect=lambda sid: _skill_ref(int(sid)) if str(sid) in {"3", "7"} else None
        )
        saved = await service.create(
            AgentCreate(
                name="我的润色师",
                description="专注文笔润色的自定义角色",
                icon="✨",
                system_prompt="你是润色师",
                tool_ids=list(VALID_TOOL_IDS),
                skill_ids=["3", "7"],
                model_override="zhipu/glm-4.5",
                temperature_override=0.6,
            )
        )
        mock_agent_repo.get_by_name.assert_awaited_once()
        assert _arg(mock_agent_repo.get_by_name.await_args, "name", 0) == "我的润色师"
        assert mock_skill_repo.get.await_count == 2  # 逐 id 查询
        mock_agent_repo.add.assert_awaited_once()
        at = _arg(mock_agent_repo.add.await_args, "agent", 0)
        assert at.id is None  # id 由 repo 分配
        assert at.name == "我的润色师"
        assert at.description == "专注文笔润色的自定义角色"
        assert at.icon == "✨"
        assert at.system_prompt == "你是润色师"
        assert at.tool_ids == list(VALID_TOOL_IDS)
        assert at.skill_ids == ["3", "7"]
        assert at.model_override == "zhipu/glm-4.5"
        assert at.temperature_override == 0.6
        assert at.builtin is False  # 用户创建的行默认非内置
        assert at.created_at == at.updated_at
        assert at.created_at.tzinfo is not None  # datetime.now(UTC) 时区感知
        assert saved is at  # 直接返回 repo.add 结果

    async def test_create_defaults_no_whitelist_queries(
        self, service, mock_agent_repo, mock_skill_repo
    ):
        """未传 tool_ids/skill_ids → 实体默认空列表，且不触发白名单查询。"""
        await service.create(AgentCreate(name="默认白名单"))
        at = _arg(mock_agent_repo.add.await_args, "agent", 0)
        assert at.tool_ids == []
        assert at.skill_ids == []
        assert at.builtin is False
        mock_skill_repo.get.assert_not_called()

    async def test_create_name_conflict_raises(self, service, mock_agent_repo):
        """同名已存在 → AgentNameConflictError（422），且不落库。"""
        mock_agent_repo.get_by_name.return_value = _agent(1, "我的润色师")
        with pytest.raises(AgentNameConflictError, match="同名"):
            await service.create(AgentCreate(name="我的润色师"))
        mock_agent_repo.add.assert_not_called()

    async def test_create_unknown_tool_rejected(self, service, mock_agent_repo):
        """tool_ids 含目录外工具名 → ToolReferenceError（422），且不落库。"""
        with pytest.raises(ToolReferenceError, match="目录外"):
            await service.create(AgentCreate(name="a", tool_ids=["count_words", "ghost_tool"]))
        mock_agent_repo.add.assert_not_called()

    async def test_create_unknown_skill_id_rejected(
        self, service, mock_agent_repo, mock_skill_repo
    ):
        """skill_ids 含不存在 skill id → SkillReferenceError（422），且不落库。"""
        mock_skill_repo.get = AsyncMock(
            side_effect=lambda sid: _skill_ref(int(sid)) if str(sid) == "3" else None
        )
        with pytest.raises(SkillReferenceError, match="不存在的 Skill"):
            await service.create(AgentCreate(name="a", skill_ids=["3", "999"]))
        mock_agent_repo.add.assert_not_called()


class TestGet:
    """get 委托与 404 语义。"""

    async def test_get_found(self, service, mock_agent_repo):
        """get 命中返回实体。"""
        entity = _agent(1, "写手")
        mock_agent_repo.get.return_value = entity
        assert await service.get(1) is entity
        mock_agent_repo.get.assert_awaited_once_with(1)

    async def test_get_missing_raises_not_found(self, service, mock_agent_repo):
        """get 不存在 → AgentNotFoundError（消息「Agent 不存在」）。"""
        mock_agent_repo.get.return_value = None
        with pytest.raises(AgentNotFoundError, match="不存在"):
            await service.get(999)


class TestList:
    """list 委托。"""

    async def test_list_delegates(self, service, mock_agent_repo):
        """list 直接返回 repo.list 结果。"""
        items = [_agent(1, "a"), _agent(2, "b")]
        mock_agent_repo.list.return_value = items
        assert await service.list() == items
        mock_agent_repo.list.assert_awaited_once()


class TestUpdate:
    """update — 404 / 内置只读 / 部分合并 / 改名查重 / 白名单校验。"""

    async def test_update_missing_raises_not_found(self, service, mock_agent_repo):
        """update 目标不存在 → AgentNotFoundError。"""
        mock_agent_repo.get.return_value = None
        with pytest.raises(AgentNotFoundError, match="不存在"):
            await service.update(999, AgentUpdate(description="d2"))

    async def test_update_builtin_rejected(self, service, mock_agent_repo):
        """builtin=True（内置只读）→ AgentBuiltinError（409），且不落库。"""
        mock_agent_repo.get.return_value = _agent(1, "内置写手", builtin=True)
        with pytest.raises(AgentBuiltinError, match="内置"):
            await service.update(1, AgentUpdate(description="d2"))
        mock_agent_repo.update.assert_not_called()

    async def test_update_partial_merge_and_refresh_updated_at(self, service, mock_agent_repo):
        """部分更新：仅传入字段合并；created_at 保留；updated_at 刷新为 now(UTC)。"""
        existing = _agent(
            7,
            "旧名",
            description="d1",
            icon="😀",
            tool_ids=["count_words"],
            skill_ids=["3"],
            model_override="zhipu/glm-4.5",
            temperature_override=0.5,
        )
        mock_agent_repo.get.return_value = existing
        merged = await service.update(7, AgentUpdate(description="d2"))

        mock_agent_repo.get.assert_awaited_once_with(7)
        mock_agent_repo.update.assert_awaited_once()
        updated = _arg(mock_agent_repo.update.await_args, "agent", 0)
        assert updated.id == 7
        assert updated.name == "旧名"  # 未传字段不变
        assert updated.description == "d2"
        assert updated.icon == "😀"
        assert updated.tool_ids == ["count_words"]
        assert updated.skill_ids == ["3"]  # 未传 skill_ids → 不校验不修改
        assert updated.model_override == "zhipu/glm-4.5"
        assert updated.temperature_override == 0.5
        assert updated.builtin is False
        assert updated.created_at == TS  # created_at 保留
        assert updated.updated_at.tzinfo is not None  # 刷新为 now(UTC)
        mock_agent_repo.get_by_name.assert_not_called()  # name 未变，不查重
        assert merged is updated

    async def test_update_explicit_none_means_no_change(self, service, mock_agent_repo):
        """显式 None 字段不应用（None = 不修改，同 F13）。"""
        existing = _agent(7, "旧名", model_override="zhipu/glm-4.5")
        mock_agent_repo.get.return_value = existing
        await service.update(7, AgentUpdate(model_override=None))
        updated = _arg(mock_agent_repo.update.await_args, "agent", 0)
        assert updated.model_override == "zhipu/glm-4.5"  # 未被置 None

    async def test_update_rename_conflict_raises(self, service, mock_agent_repo):
        """改名命中其他 Agent → AgentNameConflictError，且不落库。"""
        mock_agent_repo.get.return_value = _agent(7, "旧名")
        mock_agent_repo.get_by_name.return_value = _agent(8, "被占用")  # 其他 id 已占用
        with pytest.raises(AgentNameConflictError, match="同名"):
            await service.update(7, AgentUpdate(name="被占用"))
        mock_agent_repo.update.assert_not_called()

    async def test_update_rename_to_own_name_no_conflict(self, service, mock_agent_repo):
        """name 未变化（与现有值相同）→ 不查重、直接更新。"""
        mock_agent_repo.get.return_value = _agent(7, "旧名")
        await service.update(7, AgentUpdate(name="旧名"))
        mock_agent_repo.get_by_name.assert_not_called()
        mock_agent_repo.update.assert_awaited_once()

    async def test_update_invalid_tool_rejected(self, service, mock_agent_repo):
        """update 传入 tool_ids 含目录外工具名 → ToolReferenceError。"""
        mock_agent_repo.get.return_value = _agent(7, "旧名")
        with pytest.raises(ToolReferenceError, match="目录外"):
            await service.update(7, AgentUpdate(tool_ids=["ghost_tool"]))
        mock_agent_repo.update.assert_not_called()

    async def test_update_invalid_skill_rejected(self, service, mock_agent_repo, mock_skill_repo):
        """update 传入 skill_ids 含不存在 id → SkillReferenceError。"""
        mock_agent_repo.get.return_value = _agent(7, "旧名")
        with pytest.raises(SkillReferenceError, match="不存在的 Skill"):
            await service.update(7, AgentUpdate(skill_ids=["999"]))
        mock_agent_repo.update.assert_not_called()


class TestDelete:
    """delete — 404 / 内置只读保护 / 委托 repo。"""

    async def test_delete_missing_raises_not_found(self, service, mock_agent_repo):
        """repo.get 不存在 → AgentNotFoundError，无任何副作用。"""
        mock_agent_repo.get.return_value = None
        with pytest.raises(AgentNotFoundError, match="不存在"):
            await service.delete(999)
        mock_agent_repo.delete.assert_not_called()

    async def test_delete_builtin_rejected(self, service, mock_agent_repo):
        """builtin=True（内置只读）→ AgentBuiltinError，不删除。"""
        mock_agent_repo.get.return_value = _agent(1, "内置写手", builtin=True)
        with pytest.raises(AgentBuiltinError, match="内置"):
            await service.delete(1)
        mock_agent_repo.delete.assert_not_called()

    async def test_delete_custom_agent_succeeds(self, service, mock_agent_repo):
        """自定义 Agent（无引用面）→ 直接 repo.delete，成功返回 None。"""
        mock_agent_repo.get.return_value = _agent(1, "自定义")
        assert await service.delete(1) is None
        mock_agent_repo.delete.assert_awaited_once()
        assert _arg(mock_agent_repo.delete.await_args, "agent_id", 0) == 1

    async def test_delete_repo_delete_false_raises_not_found(self, service, mock_agent_repo):
        """repo.delete 返回 False（竞态：已被删）→ AgentNotFoundError。"""
        mock_agent_repo.get.return_value = _agent(1, "自定义")
        mock_agent_repo.delete.return_value = False
        with pytest.raises(AgentNotFoundError, match="不存在"):
            await service.delete(1)


class TestAgentErrorsGuard:
    """错误类守卫：默认文案 + 继承关系 + 不导出他域错误类（规则 1m）。"""

    def test_error_default_messages_and_hierarchy(self) -> None:
        """5 错误类默认消息逐字 + 继承关系（镜像 agent_template_errors.py）。"""
        assert str(AgentNotFoundError()) == "Agent 不存在"
        assert str(AgentNameConflictError()) == "同名 Agent 已存在（Agent 名称必须唯一）"
        assert str(AgentBuiltinError()) == "内置 Agent 不可修改或删除"
        assert str(ToolReferenceError()) == "tool_ids 含目录外工具名"
        assert str(SkillReferenceError()) == "skill_ids 含不存在的 Skill"
        # 422/409 类继承 AgentServiceError；404 类独立（镜像 agent_template_errors）
        assert issubclass(AgentNameConflictError, AgentServiceError)
        assert issubclass(AgentBuiltinError, AgentServiceError)
        assert issubclass(ToolReferenceError, AgentServiceError)
        assert issubclass(SkillReferenceError, AgentServiceError)
        assert not issubclass(AgentNotFoundError, AgentServiceError)
        assert issubclass(AgentServiceError, Exception)

    def test_no_foreign_error_classes_leaked(self) -> None:
        """agent_errors 不导出 AgentTemplate 系错误类；不借用 F4 管线同名基类。"""
        import inkflow.domain.ports.agent_errors as agent_errors_module
        from inkflow.domain.services.agent_service import AgentServiceError as F4AgentServiceError

        assert not hasattr(agent_errors_module, "AgentTemplateNotFoundError")
        assert not hasattr(agent_errors_module, "AgentTemplateNameConflictError")
        # F39 基类必须是本模块自有的，禁止复用 F4 管线同名类（遮蔽防护）
        assert agent_errors_module.AgentServiceError is not F4AgentServiceError


class TestRoleKeyV15:
    """v1.5 #484 role_key 契约（spec §5.7.1 + §5.7.2 + §13 M9 ①③）。

    契约：
    1. BUILTIN_AGENT_SPECS role_key 全集 = 6（内置稳定映射）：
       architect/writer/auditor/reviser/worldview/polisher —— 世界观顾问="worldview"、
       润色师="polisher"（v1.5 由 None 扩展，§5.7.1 表）
    2. Agent 领域模型新增 role_key: str | None = None 字段（链角色稳定标识；
       None = 非链角色/未分配）
    3. AgentEntityService.create 自动分配 role_key（§5.7.2）：
       - name slug 化（小写 + 非 [a-z0-9_] 替换为 _ + 去首尾 _）为 base；
         base 为空（全非 ASCII，如「校对助手」）→ 回退 "agent"
       - 与既有 role_key 冲突 → 追加数字后缀（base_1, base_2, ...）；
         查重用 repo.list() 的 role_key 集合
       - role_key 一经分配不可变更：AgentUpdate 无 role_key 字段，
         update 后实体 role_key 保持创建时值（不可变，§5.7.2）
    4. seed_builtin_agents 写入 role_key（新建内置带出厂 role_key；
       存量同名已存在且 role_key 为空 → 补值 UPDATE，§5.7.1 seed 升级钩子）

    RED 形态：Agent 无 role_key 字段 → create 断言 at.role_key AttributeError /
    BUILTIN_AGENT_SPECS worldview/polisher 仍 None → 断言失败（实际为 None）。
    """

    def test_builtin_specs_role_key_fullset(self) -> None:
        """BUILTIN_AGENT_SPECS 6 内置 role_key 全集（世界观顾问/润色师 v1.5 扩展）。"""
        from inkflow.domain.services.agent_entity_service import BUILTIN_AGENT_SPECS

        mapping = {spec["name"]: spec["role_key"] for spec in BUILTIN_AGENT_SPECS}
        assert mapping["架构师"] == "architect"
        assert mapping["写手"] == "writer"
        assert mapping["审校员"] == "auditor"
        assert mapping["修订师"] == "reviser"
        # v1.5 扩展：None → worldview/polisher（6 内置皆可进链）
        assert mapping["世界观顾问"] == "worldview"
        assert mapping["润色师"] == "polisher"
        # 全集恰好 6 个且 role_key 全部非 None 且唯一
        assert len(mapping) == 6
        role_keys = [spec["role_key"] for spec in BUILTIN_AGENT_SPECS]
        assert all(k is not None for k in role_keys)
        assert len(role_keys) == len(set(role_keys))

    def test_agent_model_has_role_key_field(self) -> None:
        """Agent 领域模型新增 role_key 字段（默认 None；非链角色/未分配）。"""
        agent = Agent(name="测试", role_key=None)
        assert agent.role_key is None
        agent2 = Agent(name="测试2", role_key="custom_role")
        assert agent2.role_key == "custom_role"

    async def test_create_assigns_role_key_from_ascii_name(self, service, mock_agent_repo):
        """create 自动分配 role_key：ASCII name slug 化（Proofreader → proofreader）。"""
        saved = await service.create(AgentCreate(name="Proofreader"))
        at = _arg(mock_agent_repo.add.await_args, "agent", 0)
        assert at.role_key == "proofreader"
        assert saved is at

    async def test_create_role_key_conflict_appends_suffix(self, service, mock_agent_repo):
        """role_key 冲突 → 追加数字后缀（已有 proofreader → 新建 proofreader_1）。"""
        existing = _agent(1, "既有角色", role_key="proofreader")
        mock_agent_repo.list.return_value = [existing]
        await service.create(AgentCreate(name="Proofreader"))
        at = _arg(mock_agent_repo.add.await_args, "agent", 0)
        assert at.role_key == "proofreader_1"

    async def test_create_non_ascii_name_falls_back_to_agent(self, service, mock_agent_repo):
        """全非 ASCII name（slug 为空）→ 回退 "agent"（§5.7.2 slug 化规则）。"""
        await service.create(AgentCreate(name="校对助手"))
        at = _arg(mock_agent_repo.add.await_args, "agent", 0)
        assert at.role_key == "agent"

    async def test_create_role_key_stable_on_update(self, service, mock_agent_repo):
        """role_key 不可变：AgentUpdate 无 role_key 字段，update 后保持创建时值。"""
        existing = _agent(7, "研究员", role_key="researcher")
        mock_agent_repo.get.return_value = existing
        merged = await service.update(7, AgentUpdate(description="新描述"))
        assert merged.role_key == "researcher"
        assert "role_key" not in AgentUpdate.model_fields


class TestSeedRoleKeyV15:
    """v1.5 #484 seed_builtin_agents role_key 落库 + 存量补值（spec §5.7.1 seed 升级钩子）。

    契约：seed_builtin_agents 新建内置时写入出厂 role_key（BUILTIN_AGENT_SPECS 透传）；
    存量 DB（v1.5 前已 seed，role_key 列缺省/为空）同名已存在 → 补值 UPDATE（不重复插入）。
    RED 形态：AgentORM 无 role_key 列 → create_all 无该列 / 断言 AttributeError。
    """

    @pytest.fixture
    async def db_session(self):
        """独立 in-memory SQLite（镜像 test_agent_repo fixture；Base.metadata.create_all）。"""
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from inkflow.core.database import Base

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            yield session
        await engine.dispose()

    async def test_seed_writes_role_key(self, db_session) -> None:
        """新建内置 6 Agent → role_key 全部落库（含 worldview/polisher）。"""
        from inkflow.domain.services.agent_entity_service import seed_builtin_agents
        from inkflow.infrastructure.database.repositories.agent_repo import (
            SQLiteAgentRepository,
        )

        inserted = await seed_builtin_agents(db_session)
        assert inserted == 6
        repo = SQLiteAgentRepository(db_session)
        agents = await repo.list()
        by_name = {a.name: a for a in agents}
        assert by_name["世界观顾问"].role_key == "worldview"
        assert by_name["润色师"].role_key == "polisher"
        assert by_name["架构师"].role_key == "architect"
        for a in agents:
            assert a.role_key is not None

    async def test_seed_backfills_existing_role_key(self, db_session) -> None:
        """存量（v1.5 前已 seed，role_key 为空）→ 同名跳过插入 + 补值 UPDATE。"""
        from inkflow.domain.models.agent import Agent
        from inkflow.domain.services.agent_entity_service import seed_builtin_agents
        from inkflow.infrastructure.database.repositories.agent_repo import (
            SQLiteAgentRepository,
        )

        repo = SQLiteAgentRepository(db_session)
        # 模拟存量：世界观顾问已存在但 role_key 为空（v1.5 前 seed 形态）
        await repo.add(Agent(name="世界观顾问", builtin=True, system_prompt="旧 prompt"))
        inserted = await seed_builtin_agents(db_session)
        assert inserted == 5  # 世界观顾问已存在 → 不重复插入，其余 5 个新建

        agents = await repo.list()
        worldview = next(a for a in agents if a.name == "世界观顾问")
        assert worldview.role_key == "worldview"  # 补值


class TestDuplicate:
    """duplicate — 复制 Agent（镜像 agent_template_service.duplicate，#485）。

    契约（设计假设，GREEN 实现者唯一参考）：

    1. 签名: ``async duplicate(self, agent_id: int, *, name: str | None = None)
       -> Agent``。
    2. 语义: ``agent_repository.get(agent_id)`` 目标不存在 →
       AgentNotFoundError（404）；新 name（指定或 f"{原 name} 副本"，空格
       分隔）经 ``agent_repository.get_by_name`` 查重，命中 →
       AgentNameConflictError（422）；成功 → 构造副本并委托
       ``agent_repository.add``，直接返回其结果。
    3. 原样复制字段: description/icon/system_prompt/tool_ids/skill_ids/
       model_override/temperature_override 与源完全一致（tool_ids/skill_ids
       列表内容相等）。⚠️ duplicate 也做白名单校验（同 create）：tool_ids
       目录外 → ToolReferenceError；skill_ids 任一 skill_repository.get 缺失
       → SkillReferenceError。测试构造源时 tool_ids 须用 VALID_TOOL_IDS、
       skill_ids 须 mock skill_repo.get 返回 _skill_ref。
    4. 重置字段: id=None；builtin=False（副本为用户态，可改可删）；
       role_key 不继承源值——按 create 同名逻辑重新分配（_slugify_role_key(
       新 name) 冲突追加数字后缀；「写手 副本」全非 ASCII → slug 空回退
       "agent"）；created_at = updated_at = datetime.now(UTC)（时区感知，
       断言用动态 now 不锁固定值）。

    RED 形态: 当前服务无 duplicate 方法 → 每个用例 AttributeError:
    'AgentEntityService' object has no attribute 'duplicate'。
    """

    async def test_duplicate_default_name_appends_suffix(self, service, mock_agent_repo):
        """duplicate 默认副本名 = f"{源 name} 副本"；id/builtin/role_key/
        时间戳重置（role_key 不继承源值；时间戳同一批次 now 且时区感知）。"""
        mock_agent_repo.get.return_value = _agent(1, "写手", role_key="writer")
        await service.duplicate(1)

        mock_agent_repo.get.assert_awaited_once_with(1)
        mock_agent_repo.get_by_name.assert_awaited_once()
        assert _arg(mock_agent_repo.get_by_name.await_args, "name", 0) == "写手 副本"
        mock_agent_repo.add.assert_awaited_once()
        at = _arg(mock_agent_repo.add.await_args, "agent", 0)
        assert at.id is None  # id 由 repo 分配
        assert at.name == "写手 副本"
        assert at.builtin is False  # 副本为用户态，可改可删
        assert at.role_key != "writer"  # role_key 不继承源值，按 create 逻辑重分配
        assert at.created_at == at.updated_at
        assert at.created_at.tzinfo is not None  # datetime.now(UTC) 时区感知

    async def test_duplicate_copies_all_fields(self, service, mock_agent_repo, mock_skill_repo):
        """复制字段原样：description/icon/system_prompt/tool_ids/skill_ids/
        model_override/temperature_override 与源一致；name 参数指定副本名。"""
        source = _agent(
            1,
            "写手",
            description="正文生成",
            icon="✍️",
            system_prompt="你是写手，负责正文。",
            tool_ids=list(VALID_TOOL_IDS),
            skill_ids=["3"],
            model_override="zhipu/glm-4.5",
            temperature_override=0.6,
        )
        mock_agent_repo.get.return_value = source
        mock_skill_repo.get = AsyncMock(
            side_effect=lambda sid: _skill_ref(int(sid)) if str(sid) == "3" else None
        )
        await service.duplicate(1, name="指定名")

        mock_skill_repo.get.assert_awaited()  # skill_ids 白名单校验查询
        at = _arg(mock_agent_repo.add.await_args, "agent", 0)
        assert at.name == "指定名"  # name 参数生效
        assert at.description == source.description
        assert at.icon == source.icon
        assert at.system_prompt == source.system_prompt
        assert at.tool_ids == list(VALID_TOOL_IDS)  # 列表内容相等
        assert at.skill_ids == ["3"]
        assert at.model_override == source.model_override
        assert at.temperature_override == source.temperature_override
        assert at.id is None
        assert at.builtin is False

    async def test_duplicate_missing_raises_not_found(self, service, mock_agent_repo):
        """目标不存在 → AgentNotFoundError（404），且不落库、不查重。"""
        mock_agent_repo.get.return_value = None
        with pytest.raises(AgentNotFoundError, match="不存在"):
            await service.duplicate(999)
        mock_agent_repo.add.assert_not_called()
        mock_agent_repo.get_by_name.assert_not_called()  # 目标缺失即短路

    async def test_duplicate_name_conflict_raises(self, service, mock_agent_repo):
        """副本名已存在 → AgentNameConflictError（422），且不落库。"""
        mock_agent_repo.get.return_value = _agent(1, "写手")
        mock_agent_repo.get_by_name.return_value = _agent(99, "写手 副本")  # 其他 id 已占用
        with pytest.raises(AgentNameConflictError, match="同名"):
            await service.duplicate(1)
        mock_agent_repo.add.assert_not_called()

    async def test_duplicate_custom_agent_also_works(self, service, mock_agent_repo):
        """复制不区分内置/自定义：builtin=False 源同样可复制，副本保持
        builtin=False（用户态）。"""
        mock_agent_repo.get.return_value = _agent(1, "自定义写手")
        await service.duplicate(1)
        at = _arg(mock_agent_repo.add.await_args, "agent", 0)
        assert at.name == "自定义写手 副本"
        assert at.builtin is False

    async def test_duplicate_unknown_tool_rejected(self, service, mock_agent_repo):
        """源 tool_ids 含目录外工具名 → ToolReferenceError（422），且不落库。"""
        mock_agent_repo.get.return_value = _agent(1, "写手", tool_ids=["ghost_tool"])
        with pytest.raises(ToolReferenceError, match="目录外"):
            await service.duplicate(1)
        mock_agent_repo.add.assert_not_called()

    async def test_duplicate_unknown_skill_rejected(
        self, service, mock_agent_repo, mock_skill_repo
    ):
        """源 skill_ids 含不存在 skill → SkillReferenceError（422），且不落库。"""
        mock_agent_repo.get.return_value = _agent(1, "写手", skill_ids=["999"])
        mock_skill_repo.get.return_value = None  # fixture 默认即 None，显式声明意图
        with pytest.raises(SkillReferenceError, match="不存在的 Skill"):
            await service.duplicate(1)
        mock_agent_repo.add.assert_not_called()

    async def test_duplicate_role_key_reassigned_with_suffix(self, service, mock_agent_repo):
        """role_key 按 create 同名逻辑重新分配：副本名 slug 与既有 role_key
        冲突 → 追加数字后缀（镜像 TestRoleKeyV15 冲突契约）。"""
        mock_agent_repo.get.return_value = _agent(1, "Proofreader", role_key="proofreader")
        mock_agent_repo.list.return_value = [_agent(2, "既有角色", role_key="proofreader")]
        await service.duplicate(1)
        at = _arg(mock_agent_repo.add.await_args, "agent", 0)
        # 副本名 "Proofreader 副本" slug 化 = "proofreader"（非 ASCII 段替换为 _）
        # → 与既有 role_key 冲突 → proofreader_1
        assert at.role_key == "proofreader_1"

    async def test_duplicate_preserves_add_result(self, service, mock_agent_repo):
        """成功路径直接返回 repo.add 结果（不二次包装）。"""
        mock_agent_repo.get.return_value = _agent(1, "写手")
        saved = await service.duplicate(1)
        at = _arg(mock_agent_repo.add.await_args, "agent", 0)
        assert saved is at  # fixture: add side_effect=lambda a: a
