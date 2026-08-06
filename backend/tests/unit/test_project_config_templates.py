"""#107 ProjectConfig 新字段单元测试 — template_id + 每角色温度（RED 批）。

覆盖 spec §9.2② ProjectConfig 扩展（入 config JSON，零迁移）:
- ``template_id: str | None = None``（引用式：项目引用 AgentTemplate，
  §9.7「template_id 入 config JSON」决策）
- ``role_architect_temperature / role_writer_temperature /
  role_auditor_temperature / role_reviser_temperature:
  float | None = Field(default=None, ge=0.0, le=2.0)``
  （每角色独立温度，§9.2③ 显式 None 语义：None=跟随默认，非 None=独立温度）
- 既有字段零回归（model/temperature/writing_style/default_words/extra）
- model_dump JSON 序列化包含新字段（config JSON 落库路径）

依据: specs/f19-gui/spec.md §9.2② + §9.5 测试策略「后端单元」。
镜像: backend/tests/unit/test_project_dtos.py（ProjectConfig 测试模式）。

══════════════════════ 设计假设（GREEN 实现者唯一契约）══════════════════════

1. ``inkflow.domain.models.project.ProjectConfig``（MODIFY，当前缺字段 →
   构造 TypeError 即预期 RED 形态）新增:
   - ``template_id: str | None = None``（**str 类型**：config JSON 存储，
     无格式校验，YAGNI；agent_service 层 int() 转换后查模板仓储）
   - ``role_architect_temperature`` / ``role_writer_temperature`` /
     ``role_auditor_temperature`` / ``role_reviser_temperature``:
     ``float | None = Field(default=None, ge=0.0, le=2.0)``

2. 温度字段边界契约: -0.1 / 2.1 → ValidationError；0.0 / 2.0 / None 接受
   （四字段独立校验）。

3. JSON 序列化契约: 新字段进入 ``model_dump()`` / ``model_dump(mode="json")``
   产物（零迁移：projects.config JSON 列直接存新键，旧项目读回缺键 →
   默认 None，天然兼容）。

4. 零回归契约: 既有字段（model/temperature/writing_style/default_words/
   extra）默认值与约束不变；ProjectCreate/ProjectUpdate 携带 config 正常。

⚠️ 本批为 RED：不写任何 src/ 实现；GREEN 按上述契约实现后本文件应全绿。
"""

import json

import pytest
from pydantic import ValidationError

from inkflow.domain.models.project import ProjectConfig, ProjectCreate, ProjectUpdate

# 每角色温度字段全集（§9.2③）
ROLE_TEMP_FIELDS = (
    "role_architect_temperature",
    "role_writer_temperature",
    "role_auditor_temperature",
    "role_reviser_temperature",
)


class TestProjectConfigTemplateId:
    """ProjectConfig.template_id 新字段（引用式入口）。"""

    def test_template_id_default_none(self):
        """默认 None（旧项目无引用）。"""
        config = ProjectConfig()
        assert config.template_id is None

    def test_template_id_explicit_value(self):
        """显式赋值保留（str 类型，无格式校验）。"""
        config = ProjectConfig(template_id="5")
        assert config.template_id == "5"
        # str 契约：非数字字符串也接受（YAGNI 不约束格式）
        assert ProjectConfig(template_id="abc").template_id == "abc"

    def test_template_id_in_model_dump(self):
        """model_dump 包含 template_id 键。"""
        dumped = ProjectConfig(template_id="7").model_dump()
        assert dumped["template_id"] == "7"
        assert ProjectConfig().model_dump()["template_id"] is None


class TestProjectConfigRoleTemperatures:
    """每角色温度字段：默认 None + 显式值 + [0.0, 2.0] 边界。"""

    def test_role_temperatures_default_none(self):
        """四角色温度字段默认全部 None（None = 跟随默认，显式语义）。"""
        config = ProjectConfig()
        for field in ROLE_TEMP_FIELDS:
            assert getattr(config, field) is None

    def test_role_temperatures_explicit_values(self):
        """显式赋值保留。"""
        config = ProjectConfig(
            role_architect_temperature=0.4,
            role_writer_temperature=1.2,
            role_auditor_temperature=0.5,
            role_reviser_temperature=0.6,
        )
        assert config.role_architect_temperature == 0.4
        assert config.role_writer_temperature == 1.2
        assert config.role_auditor_temperature == 0.5
        assert config.role_reviser_temperature == 0.6

    @pytest.mark.parametrize("field", ROLE_TEMP_FIELDS)
    def test_role_temperature_below_min_raises(self, field):
        """-0.1 低于 ge=0.0 → ValidationError（四字段独立校验）。"""
        with pytest.raises(ValidationError):
            ProjectConfig(**{field: -0.1})

    @pytest.mark.parametrize("field", ROLE_TEMP_FIELDS)
    def test_role_temperature_above_max_raises(self, field):
        """2.1 高于 le=2.0 → ValidationError（四字段独立校验）。"""
        with pytest.raises(ValidationError):
            ProjectConfig(**{field: 2.1})

    @pytest.mark.parametrize("field", ROLE_TEMP_FIELDS)
    def test_role_temperature_boundaries_accepted(self, field):
        """0.0 / 2.0 / None 边界接受。"""
        assert getattr(ProjectConfig(**{field: 0.0}), field) == 0.0
        assert getattr(ProjectConfig(**{field: 2.0}), field) == 2.0
        assert getattr(ProjectConfig(**{field: None}), field) is None

    def test_role_temperatures_in_model_dump(self):
        """model_dump 包含四角色温度键（config JSON 落库路径）。"""
        config = ProjectConfig(role_writer_temperature=1.1)
        dumped = config.model_dump()
        assert dumped["role_writer_temperature"] == 1.1
        for field in ROLE_TEMP_FIELDS:
            assert field in dumped
        assert dumped["role_architect_temperature"] is None

    def test_template_id_and_role_temps_combine(self):
        """template_id + 每角色温度可同时配置（引用模板 + 项目级覆盖，
        用户拍板 Q1=A）。"""
        config = ProjectConfig(template_id="3", role_writer_temperature=0.9)
        assert config.template_id == "3"
        assert config.role_writer_temperature == 0.9


class TestProjectConfigJsonRoundtrip:
    """新字段 JSON 序列化 + 全量 roundtrip（零回归）。"""

    def test_json_serializable_with_new_fields(self):
        """model_dump(mode='json') 产物可 json.dumps（API 输出路径）。"""
        config = ProjectConfig(
            template_id="5",
            role_architect_temperature=0.4,
            role_writer_temperature=1.1,
        )
        dumped = config.model_dump(mode="json")
        assert json.dumps(dumped, ensure_ascii=False)  # 可序列化
        assert dumped["template_id"] == "5"
        assert dumped["role_architect_temperature"] == 0.4

    def test_roundtrip_equality_with_new_fields(self):
        """model_dump(mode='json') → model_validate 还原相等（含新字段）。

        显式断言新字段进入序列化产物——防 Pydantic extra='ignore' 静默丢弃
        新字段导致 RED 空洞通过（空 roundtrip 恒等）。
        """
        config = ProjectConfig(
            template_id="9",
            role_auditor_temperature=0.5,
            role_reviser_temperature=0.6,
        )
        dumped = config.model_dump(mode="json")
        # RED: ProjectConfig 缺新字段 → dumped 无键 → KeyError（真正失败形态）
        assert dumped["template_id"] == "9"
        assert dumped["role_auditor_temperature"] == 0.5
        assert dumped["role_reviser_temperature"] == 0.6
        reloaded = ProjectConfig.model_validate(dumped)
        assert reloaded == config

    def test_existing_fields_zero_regression(self):
        """既有字段默认值与约束零回归。"""
        config = ProjectConfig()
        assert config.model == "gpt-4o"
        assert config.temperature == 0.7
        assert config.writing_style == ""
        assert config.default_words == 800000
        assert config.extra == {}
        with pytest.raises(ValidationError):
            ProjectConfig(temperature=2.1)
        with pytest.raises(ValidationError):
            ProjectConfig(default_words=0)

    def test_project_create_and_update_carry_config(self):
        """ProjectCreate/ProjectUpdate 携带含新字段的 config 正常（DTO 透传）。"""
        create = ProjectCreate(name="测试", config=ProjectConfig(template_id="2"))
        assert create.config.template_id == "2"
        update = ProjectUpdate(config=ProjectConfig(role_writer_temperature=1.3, template_id="4"))
        assert update.config.template_id == "4"
        assert update.config.role_writer_temperature == 1.3
