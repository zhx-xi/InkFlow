"""#107 AgentService 引用式装配 + 角色独立温度链单元测试（RED 批，核心文件）。

直接测 ``AgentService._merge_role_configs`` 改造（spec §9.2.3 引用式生效
机制 + 温度优先级链 + 0.7 哨兵移除，§9.6 M2/M3 验收）:
- 引用式：项目 config.template_id → 运行时读 AgentTemplate → 模板 roles
  模型/温度为装配基础；模板修改即生效（运行时读 = 天然引用式）
- 温度优先级链（每角色独立，首个命中即止，评审 C1 定稿）:
  1) 项目 config 每角色温度字段（role_architect_temperature /
     role_writer_temperature / role_auditor_temperature /
     role_reviser_temperature，非 None 即覆盖）——最高
  2) 项目引用的 AgentTemplate.roles[role].temperature（非 None）
  3) AgentTemplate.default_temperature（非 None，全角色兜底）
  4) 内置管线模板 AgentRole.temperature（**architect=None** /
     writer=0.8 / auditor=0.5 / reviser=0.6 —— pipeline_templates.py
     将改 architect 为 None）
  5) 项目 config.temperature（保底，仅当 1-4 全无值）
- 0.7 哨兵移除：temperature=0.7 的角色不再被项目温度覆盖（旧行为
  ==0.7 就替换）
- M3 旧项目等价（无 template_id、无每角色温度字段）：architect=项目
  config.temperature、writer=0.8、auditor=0.5、reviser=0.6
- 模型装配：模板 roles[role].model 覆盖角色 model（非 None）；
  roles[role].enabled=False → 该角色 model 不覆盖（用内置模板 model，
  spec §9.2.5 评审建议 1）；项目 agent_* 字段仍覆盖模板（用户拍板 Q1=A：
  项目覆盖优先）；role_overrides 参数优先级最高（不变）

依据: specs/f19-gui/spec.md §9.2.3 + §9.6 M2/M3 + §9.7 决策记录。
镜像: backend/tests/unit/test_agent_service.py（Mock 装配模式）。

══════════════════════ 设计假设（GREEN 实现者唯一契约）══════════════════════

1. ``AgentService.__init__`` 新增关键字参数 ``template_repo: Any = None``:
   None 时内部用 ``SQLiteAgentTemplateRepository(db_session)``（既有测试
   不传 → 零破坏）；测试注入 FakeTemplateRepo。**RED 预期失败形态**:
   当前构造签名无该参数 → TypeError。

2. ``_merge_role_configs`` 参数签名不变 ``(stages, project_config,
   role_overrides)``，但**改为 async**（内部需 await template_repo.get）；
   既有调用点 execute L85 由 GREEN 改为 ``await``。测试直接
   ``await service._merge_role_configs(...)`` 调用（当前实现为 sync →
   await 非协程 TypeError，属预期 RED）。

3. 模板读取契约: ``project_config.template_id`` 为 str（config JSON 存储），
   服务层 ``int(template_id)`` 转换后调 ``template_repo.get(int_id)``；
   转换失败 / 模板不存在（get 返回 None）→ 跳过装配（回退内置管线模板，
   行为等价无 template_id 旧项目）。

4. 温度解析实现提示（每角色独立，按 1→5 顺序首个非 None 即止）:
   - 项目每角色字段 = ``getattr(project_config, f"role_{role}_temperature")``
   - 模板 roles 缺省 key → 视为 ``RoleTemplate()``（temperature=None，
     不覆盖；model=None，不覆盖）——「缺省 key 读取返回默认 RoleTemplate()」
     语义落在装配层
   - 角色最终温度 = None 兜底链后仍为 None（模板全 None + 内置 None +
     项目温度 None？项目 temperature 有默认 0.7 且 ge/le 非空 → 链 5 恒有值）

5. 模型装配实现提示: 模板 role 的 model 仅当 ``enabled=True`` 且 model
   非 None 时覆盖；随后项目 agent_* 非空仍覆盖（项目优先）；最后
   role_overrides 覆盖。

6. FakeTemplateRepo 契约: 测试用轻量类，``async def get(self,
   template_id: int) -> AgentTemplate | None``（记录调用参数）；
   AgentTemplate/RoleTemplate 模型不存在 → 本文件收集期
   ModuleNotFoundError 即预期 RED 形态。

7. 既有回归护栏: test_agent_service.py 的 execute 用例（architect=项目温度、
   writer=0.8/auditor=0.5 保持模板值等）在新链下应保持全绿（M6 零回归）；
   本文件 M3 用例即该等价行为的直接锁定。

⚠️ 本批为 RED：不写任何 src/ 实现；GREEN 按上述契约实现后本文件应全绿。
"""

from __future__ import annotations

from inkflow.domain.models.agent_pipeline import RoleOverride
from inkflow.domain.models.agent_template import AgentTemplate, RoleTemplate
from inkflow.domain.models.project import ProjectConfig
from inkflow.domain.ports.agent_pipeline import PipelineStage
from inkflow.domain.services.agent_service import AgentService
from inkflow.infrastructure.agent.pipeline_templates import get_template

# 内置管线模板默认模型（#415 G1 契约值：deepseek/deepseek-v4-flash，
# pipeline_templates.py 引用 config）
BUILTIN_MODEL = "deepseek/deepseek-v4-flash"
# 内置管线模板温度（GREEN 后 architect=None，其余固定）
BUILTIN_TEMPS = {"writer": 0.8, "auditor": 0.5, "reviser": 0.6}


class FakeTemplateRepo:
    """轻量模板仓储 Mock：get 返回预设 AgentTemplate 或 None，并记录调用。"""

    def __init__(self, template: AgentTemplate | None = None):
        self.template = template
        self.get_calls: list[int] = []

    async def get(self, template_id: int) -> AgentTemplate | None:
        self.get_calls.append(template_id)
        return self.template


class _DummyPipeline:
    """_merge_role_configs 不触碰 pipeline；占位即可。"""

    def validate(self, stages):
        return []


def _builtin_stages() -> list[PipelineStage]:
    """内置 write_chapter 管线阶段（architect→writer→auditor→reviser）。"""
    return get_template("builtin:write_chapter").stages


def _make_template(**kw) -> AgentTemplate:
    """构造测试用 AgentTemplate（缺省字段用模型默认）。"""
    return AgentTemplate(name="测试模板", **kw)


def _build_service(template_repo: FakeTemplateRepo) -> AgentService:
    """装配 AgentService：仅注入 template_repo，其余依赖占位（不触碰 DB）。"""
    return AgentService(
        _DummyPipeline(),
        db_session=None,
        store=object(),
        project_repo=object(),
        chapter_repo=object(),
        template_repo=template_repo,
    )


async def _merge(
    service: AgentService, config: ProjectConfig, overrides=None
) -> dict[str, PipelineStage]:
    """调用 _merge_role_configs 并按键返回 stages。"""
    stages = await service._merge_role_configs(_builtin_stages(), config, overrides)
    return {s.id: s for s in stages}


class TestTemperatureChain:
    """温度优先级链 5 级逐级验证（每角色独立，首个命中即止）。"""

    async def test_m3_old_project_equivalence(self):
        """M3 旧项目等价（无 template_id、无每角色温度字段）：
        architect=项目 config.temperature、writer=0.8、auditor=0.5、
        reviser=0.6；且不触碰 template_repo。"""
        fake = FakeTemplateRepo()
        service = _build_service(fake)
        merged = await _merge(service, ProjectConfig(temperature=0.9))

        assert fake.get_calls == []  # 无 template_id 不查模板
        assert merged["architect"].agent.temperature == 0.9  # 链 5 保底
        assert merged["writer"].agent.temperature == 0.8  # 链 4 内置
        assert merged["auditor"].agent.temperature == 0.5
        assert merged["reviser"].agent.temperature == 0.6

    async def test_default_config_falls_back_to_project_temperature(self):
        """默认 config（temperature=0.7）：architect 走链 5 保底 = 0.7；
        其余角色链 4 内置值不变。"""
        fake = FakeTemplateRepo()
        service = _build_service(fake)
        merged = await _merge(service, ProjectConfig())

        assert merged["architect"].agent.temperature == 0.7
        assert merged["writer"].agent.temperature == 0.8
        assert merged["auditor"].agent.temperature == 0.5
        assert merged["reviser"].agent.temperature == 0.6

    async def test_project_per_role_temperature_highest_priority(self):
        """链 1（最高）：项目每角色温度字段非 None 即覆盖，压过内置值。
        RED 预期：ProjectConfig 缺字段 → 构造 TypeError。"""
        fake = FakeTemplateRepo()
        service = _build_service(fake)
        merged = await _merge(
            service,
            ProjectConfig(
                temperature=0.9,
                role_architect_temperature=0.4,
                role_writer_temperature=1.2,
            ),
        )

        assert merged["architect"].agent.temperature == 0.4
        assert merged["writer"].agent.temperature == 1.2
        # 未设每角色温度的 auditor/reviser 仍走链 4 内置值
        assert merged["auditor"].agent.temperature == 0.5
        assert merged["reviser"].agent.temperature == 0.6

    async def test_template_role_temperature_second(self):
        """链 2：模板 roles[role].temperature 非 None 覆盖 default_temperature
        与内置值；缺省 key 的角色走链 3 default_temperature。"""
        fake = FakeTemplateRepo(
            _make_template(
                roles={"writer": RoleTemplate(temperature=1.1)},
                default_temperature=0.6,
            )
        )
        service = _build_service(fake)
        merged = await _merge(service, ProjectConfig(template_id="1", temperature=0.9))

        assert fake.get_calls == [1]  # str id → int 转换后查询
        assert merged["writer"].agent.temperature == 1.1  # 链 2 命中
        assert merged["architect"].agent.temperature == 0.6  # 缺省 key → 链 3

    async def test_template_default_temperature_third(self):
        """链 3：roles 温度全 None → default_temperature 兜底（压过链 4 内置）。"""
        fake = FakeTemplateRepo(
            _make_template(
                roles={"writer": RoleTemplate()},  # temperature=None
                default_temperature=0.6,
            )
        )
        service = _build_service(fake)
        merged = await _merge(service, ProjectConfig(template_id="1", temperature=0.9))

        assert merged["writer"].agent.temperature == 0.6  # 链 3 命中（内置 0.8 被压）
        assert merged["architect"].agent.temperature == 0.6  # 缺省 key 同样走链 3

    async def test_builtin_temperature_fourth_when_template_empty(self):
        """链 4：模板无任何温度配置 → 内置管线值；
        architect（内置 None）→ 链 5 项目温度保底。"""
        fake = FakeTemplateRepo(_make_template())  # roles={}, default_temperature=None
        service = _build_service(fake)
        merged = await _merge(service, ProjectConfig(template_id="1", temperature=0.9))

        assert merged["writer"].agent.temperature == 0.8  # 链 4 内置
        assert merged["auditor"].agent.temperature == 0.5
        assert merged["reviser"].agent.temperature == 0.6
        assert merged["architect"].agent.temperature == 0.9  # 内置 None → 链 5

    async def test_zero_point_seven_not_overridden_by_project_temperature(self):
        """0.7 哨兵移除（核心 RED）：模板 roles writer 温度恰为 0.7 →
        不再被项目 config.temperature=0.9 替换（旧行为 ==0.7 即替换）。"""
        fake = FakeTemplateRepo(_make_template(roles={"writer": RoleTemplate(temperature=0.7)}))
        service = _build_service(fake)
        merged = await _merge(service, ProjectConfig(template_id="1", temperature=0.9))

        assert merged["writer"].agent.temperature == 0.7  # 0.7 是合法独立温度

    async def test_project_per_role_zero_point_seven_wins(self):
        """链 1 的 0.7 同样不被项目顶层温度替换（显式配置即生效）。"""
        fake = FakeTemplateRepo()
        service = _build_service(fake)
        merged = await _merge(service, ProjectConfig(role_writer_temperature=0.7, temperature=0.9))

        assert merged["writer"].agent.temperature == 0.7


class TestReferenceModelAssembly:
    """引用式模型装配：模板 roles → 项目 agent_* → role_overrides。"""

    async def test_template_role_model_overrides_builtin(self):
        """模板 roles[role].model 非 None → 覆盖内置模板 model；
        未配置角色保持内置 model。"""
        fake = FakeTemplateRepo(
            _make_template(roles={"writer": RoleTemplate(model="template/writer-model")})
        )
        service = _build_service(fake)
        merged = await _merge(service, ProjectConfig(template_id="1"))

        assert merged["writer"].agent.model == "template/writer-model"
        assert merged["architect"].agent.model == BUILTIN_MODEL  # 未配置 → 内置
        assert merged["auditor"].agent.model == BUILTIN_MODEL

    async def test_disabled_role_model_not_overridden(self):
        """enabled=False → 该角色 model 不覆盖（用内置模板 model，
        spec §9.2.5 评审建议 1 Phase 1 语义）。"""
        fake = FakeTemplateRepo(
            _make_template(
                roles={"writer": RoleTemplate(model="template/writer-model", enabled=False)}
            )
        )
        service = _build_service(fake)
        merged = await _merge(service, ProjectConfig(template_id="1"))

        assert merged["writer"].agent.model == BUILTIN_MODEL  # 关闭 → 默认模型

    async def test_project_agent_field_overrides_template_model(self):
        """用户拍板 Q1=A：项目 agent_* 非空仍覆盖模板 roles model。"""
        fake = FakeTemplateRepo(
            _make_template(roles={"writer": RoleTemplate(model="template/writer-model")})
        )
        service = _build_service(fake)
        merged = await _merge(
            service, ProjectConfig(template_id="1", agent_writer="project/writer")
        )

        assert merged["writer"].agent.model == "project/writer"

    async def test_missing_role_key_uses_default_role(self):
        """roles 缺省 key → RoleTemplate() 默认：model/temperature 均不覆盖
        （无 KeyError）。"""
        fake = FakeTemplateRepo(_make_template(roles={}))
        service = _build_service(fake)
        merged = await _merge(service, ProjectConfig(template_id="1", temperature=0.9))

        assert merged["writer"].agent.model == BUILTIN_MODEL
        assert merged["writer"].agent.temperature == 0.8  # 链 4 内置
        assert merged["auditor"].agent.model == BUILTIN_MODEL
        assert merged["auditor"].agent.temperature == 0.5

    async def test_template_not_found_falls_back_to_builtin(self):
        """template_id 指向不存在的模板（get 返回 None）→ 跳过装配，
        行为等价无 template_id 旧项目（M3）。"""
        fake = FakeTemplateRepo(template=None)
        service = _build_service(fake)
        merged = await _merge(service, ProjectConfig(template_id="999", temperature=0.9))

        assert fake.get_calls == [999]
        assert merged["architect"].agent.temperature == 0.9
        assert merged["writer"].agent.temperature == 0.8
        assert merged["writer"].agent.model == BUILTIN_MODEL

    async def test_template_id_read_as_int(self):
        """template_id（str，JSON 存储）→ int 转换后查 repo。"""
        fake = FakeTemplateRepo(_make_template())
        service = _build_service(fake)
        await _merge(service, ProjectConfig(template_id="5"))
        assert fake.get_calls == [5]


class TestRoleOverridesPriority:
    """role_overrides 优先级最高（既有语义不变，spec §9.2.3 链外参数）。"""

    async def test_role_overrides_beat_template_and_project(self):
        """模板 roles + 项目每角色温度 + 项目 agent_* 全配齐时，
        role_overrides 仍最高。"""
        fake = FakeTemplateRepo(
            _make_template(
                roles={"writer": RoleTemplate(model="template/writer-model", temperature=1.1)}
            )
        )
        service = _build_service(fake)
        merged = await _merge(
            service,
            ProjectConfig(
                template_id="1",
                agent_writer="project/writer",
                role_writer_temperature=1.2,
            ),
            overrides={
                "writer": RoleOverride(
                    prompt="自定义写手提示词", model="override/model", temperature=1.5
                )
            },
        )

        writer = merged["writer"].agent
        assert writer.model == "override/model"
        assert writer.temperature == 1.5
        assert writer.system_prompt == "自定义写手提示词"

    async def test_role_overrides_partial_keeps_chain_values(self):
        """只覆盖 prompt → model/temperature 保持链结果（模板 roles model
        生效、温度链值生效）。"""
        fake = FakeTemplateRepo(
            _make_template(roles={"writer": RoleTemplate(model="template/writer-model")})
        )
        service = _build_service(fake)
        merged = await _merge(
            service,
            ProjectConfig(template_id="1", role_writer_temperature=1.2),
            overrides={"writer": RoleOverride(prompt="只改提示词")},
        )

        writer = merged["writer"].agent
        assert writer.system_prompt == "只改提示词"
        assert writer.model == "template/writer-model"  # 链外模型保持
        assert writer.temperature == 1.2  # 链 1 项目每角色温度


class TestTemplateIdParsing:
    """template_id 非数字 → 跳过装配（#273 覆盖率补测：int() ValueError 分支）。"""

    async def test_invalid_template_id_skips_assembly(self):
        """template_id 非数字字符串 → 转换失败跳过模板读取（fake.get 零调用），
        回退内置管线模板（行为等价无 template_id 旧项目，设计假设 3）。"""
        fake = FakeTemplateRepo(_make_template())
        service = _build_service(fake)
        merged = await _merge(
            service,
            ProjectConfig(template_id="not-a-number", temperature=0.9),
        )

        assert fake.get_calls == []  # int 转换失败 → 不查询模板仓储
        assert merged["writer"].agent.model == BUILTIN_MODEL  # 回退内置模型
        assert merged["writer"].agent.temperature == 0.8  # 内置温度链 4
