"""#107 AgentTemplate 领域模型 + DTO 单元测试 — 无 I/O，纯 Pydantic 验证（RED 批）。

测试范围：RoleTemplate（角色子模型）/ AgentTemplate（模板实体）/
AgentTemplateCreate / AgentTemplateUpdate 请求 DTO。
依据: specs/f19-gui/spec.md §9.2①（实体字段）+ §9.5 测试策略「后端单元」。

══════════════════════ 设计假设（GREEN 实现者唯一契约）══════════════════════

模块: ``inkflow.domain.models.agent_template``（本批新建，当前不存在 →
收集期 ModuleNotFoundError 即预期 RED 形态）。

类与字段（Pydantic v2 BaseModel）:

1. ``RoleTemplate`` — 单个角色子模型:
   - ``model: str | None = None``（角色模型；None = 跟随默认）
   - ``temperature: float | None = Field(default=None, ge=0.0, le=2.0)``
     （None = 跟随默认；独立温度语义，spec §9.2.3 显式 None）
   - ``enabled: bool = True``（False = 该角色 model 不覆盖，用默认模型，
     spec §9.2.5 评审建议 1 Phase 1 语义）

2. ``AgentTemplate`` — 模板实体（§9.2① 字段全集）:
   - ``id: int | None = None``（None = 未落库；repo.add 后由 DB 自增分配）
   - ``name: str``（必填；去空白后非空，失败文案精确为 **"模板名称不能为空"**，
     镜像 ProviderConfigCreate._validate_name 模式）
   - ``description: str = ""``
   - ``main_model: str | None = None``
   - ``default_temperature: float | None = Field(default=None, ge=0.0, le=2.0)``
   - ``roles: dict[str, RoleTemplate] = Field(default_factory=dict)``
     （key ∈ {architect, writer, auditor, reviser}；API JSON 输入 dict 列表
     自动强制转换；**缺省 key 的「读取返回默认 RoleTemplate()」语义属装配层
     （agent_service 温度链/模型装配，见 test_agent_service_templates.py 契约），
     模型层不提供访问器**）
   - ``default_words: int | None = Field(default=None, ge=1000, le=10_000_000)``
   - ``is_default: bool = False``
   - ``created_at: datetime | None = None`` / ``updated_at: datetime | None = None``
   - ``model_config = {"from_attributes": True}``（repo _orm_to_domain 惯例）

3. ``AgentTemplateCreate`` — 创建请求 DTO:
   - ``name: str`` 必填，去空白后非空（文案同上）；其余字段同实体默认值
     （description=""/main_model=None/default_temperature=None/roles={}/
     default_words=None）
   - **无 id / is_default / created_at / updated_at 字段**（id 由 repo 分配、
     is_default 服务层固定 False、时间戳服务层填充）

4. ``AgentTemplateUpdate`` — 更新请求 DTO:
   - 全字段可选，exclude_unset 语义（同 F1/F13）；name 提供时同样非空白校验；
   - ``is_default: bool | None = None`` 允许显式 False 取消默认
     （PATCH {"is_default": false} → exclude_unset 含 False，服务层应用）

JSON roundtrip 契约: 无时间戳的实体 ``model_dump()`` 产物可直接
``json.dumps``（roles 嵌套 dict 结构）；全字段实体 ``model_dump(mode="json")``
产物可被 ``model_validate`` 还原为相等实体（datetime ↔ ISO8601 双向）。

错误类归属: 本文件不定义错误类（纯模型/DTO）；校验失败抛
``pydantic.ValidationError``（422 由 FastAPI 映射）。

⚠️ 本批为 RED：不写任何 src/ 实现；GREEN 按上述签名实现后本文件应全绿。
"""

from datetime import datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from inkflow.domain.models.agent_template import (
    AgentTemplate,
    AgentTemplateCreate,
    AgentTemplateUpdate,
    RoleTemplate,
)

TS = datetime(2026, 8, 1, 10, 0, 0)

# 四角色标准 key 集（spec §9.2①）
ROLE_KEYS = {"architect", "writer", "auditor", "reviser"}


class TestRoleTemplate:
    """RoleTemplate 角色子模型（{model, temperature, enabled}）。"""

    def test_defaults(self):
        """默认值：model=None, temperature=None, enabled=True."""
        r = RoleTemplate()
        assert r.model is None
        assert r.temperature is None
        assert r.enabled is True

    def test_explicit_values(self):
        """显式赋值保留。"""
        r = RoleTemplate(model="openai/gpt-4o", temperature=0.8, enabled=False)
        assert r.model == "openai/gpt-4o"
        assert r.temperature == 0.8
        assert r.enabled is False

    def test_temperature_bounds(self):
        """temperature 范围 [0.0, 2.0]：-0.1 / 2.1 → ValidationError；
        0.0 / 2.0 边界接受。"""
        with pytest.raises(ValidationError):
            RoleTemplate(temperature=-0.1)
        with pytest.raises(ValidationError):
            RoleTemplate(temperature=2.1)
        assert RoleTemplate(temperature=0.0).temperature == 0.0
        assert RoleTemplate(temperature=2.0).temperature == 2.0

    def test_temperature_none_allowed(self):
        """temperature=None 合法（None = 跟随默认，spec §9.2.3 显式语义）。"""
        assert RoleTemplate(temperature=None).temperature is None

    def test_json_roundtrip(self):
        """model_dump(mode='json') → model_validate 还原为相等实体。"""
        r = RoleTemplate(model="deepseek/deepseek-chat", temperature=0.6, enabled=False)
        reloaded = RoleTemplate.model_validate(r.model_dump(mode="json"))
        assert reloaded == r


class TestAgentTemplate:
    """AgentTemplate 实体字段全集与校验。"""

    def test_entity_defaults(self):
        """默认值：id=None, description='', main_model=None,
        default_temperature=None, roles={}, default_words=None,
        is_default=False, created_at=None, updated_at=None."""
        t = AgentTemplate(name="我的模板")
        assert t.id is None
        assert t.name == "我的模板"
        assert t.description == ""
        assert t.main_model is None
        assert t.default_temperature is None
        assert t.roles == {}
        assert t.default_words is None
        assert t.is_default is False
        assert t.created_at is None
        assert t.updated_at is None

    def test_entity_requires_name(self):
        """缺 name → ValidationError."""
        with pytest.raises(ValidationError):
            AgentTemplate()

    def test_name_stripped_and_blank_rejected(self):
        """name 去空白后非空：'  xxx  ' → 'xxx'；'' / '   ' → ValidationError
        （文案精确为「模板名称不能为空」）。"""
        t = AgentTemplate(name="  我的模板  ")
        assert t.name == "我的模板"
        with pytest.raises(ValidationError, match="模板名称不能为空"):
            AgentTemplate(name="")
        with pytest.raises(ValidationError, match="模板名称不能为空"):
            AgentTemplate(name="   ")

    def test_roles_default_factory_isolated(self):
        """roles 使用 default_factory：实例间不共享同一 dict 对象。"""
        a = AgentTemplate(name="a")
        b = AgentTemplate(name="b")
        a.roles["writer"] = RoleTemplate(model="m1")
        assert a.roles == {"writer": RoleTemplate(model="m1")}
        assert b.roles == {}

    def test_roles_coerced_from_dict(self):
        """roles 接受 dict[str, dict] 并强制转换为 RoleTemplate
        （API JSON 输入路径）。"""
        t = AgentTemplate(
            name="t",
            roles={
                "architect": {"model": "openai/gpt-4o", "temperature": 0.7},
                "writer": {},
            },
        )
        assert t.roles["architect"] == RoleTemplate(model="openai/gpt-4o", temperature=0.7)
        assert t.roles["writer"] == RoleTemplate()  # 空 dict → 全默认
        assert set(t.roles) == {"architect", "writer"}

    def test_roles_accept_standard_four_keys(self):
        """四角色 key 集 {architect, writer, auditor, reviser} 均可存放。"""
        t = AgentTemplate(
            name="t",
            roles={key: RoleTemplate(model=f"m/{key}") for key in ROLE_KEYS},
        )
        assert set(t.roles) == ROLE_KEYS

    def test_default_temperature_bounds(self):
        """default_temperature 范围 [0.0, 2.0]：-0.1 / 2.1 → ValidationError；
        0.0 / 2.0 / None 接受。"""
        with pytest.raises(ValidationError):
            AgentTemplate(name="t", default_temperature=-0.1)
        with pytest.raises(ValidationError):
            AgentTemplate(name="t", default_temperature=2.1)
        assert AgentTemplate(name="t", default_temperature=0.0).default_temperature == 0.0
        assert AgentTemplate(name="t", default_temperature=2.0).default_temperature == 2.0
        assert AgentTemplate(name="t", default_temperature=None).default_temperature is None

    def test_default_words_bounds(self):
        """default_words 范围 [1000, 10_000_000]：999 / 10_000_001 →
        ValidationError；1000 / 10_000_000 / None 接受。"""
        with pytest.raises(ValidationError):
            AgentTemplate(name="t", default_words=999)
        with pytest.raises(ValidationError):
            AgentTemplate(name="t", default_words=10_000_001)
        assert AgentTemplate(name="t", default_words=1000).default_words == 1000
        assert AgentTemplate(name="t", default_words=10_000_000).default_words == 10_000_000
        assert AgentTemplate(name="t", default_words=None).default_words is None

    def test_is_default_flag(self):
        """is_default 显式 True / False 均接受（默认 False）。"""
        assert AgentTemplate(name="t", is_default=True).is_default is True
        assert AgentTemplate(name="t", is_default=False).is_default is False

    def test_json_roundtrip_fresh_entity_is_json_serializable(self):
        """无时间戳实体：model_dump() 产物可直接 json.dumps（roles 嵌套 dict）。"""
        import json

        t = AgentTemplate(
            name="t",
            description="desc",
            main_model="openai/gpt-4o",
            default_temperature=0.8,
            roles={"writer": RoleTemplate(model="m/w", temperature=0.6, enabled=False)},
            default_words=50000,
        )
        dumped = t.model_dump()
        assert dumped["roles"] == {
            "writer": {
                "model": "m/w",
                "temperature": 0.6,
                "enabled": False,
                "prompt": None,
                "name": None,
            }
        }
        assert isinstance(json.dumps(dumped, ensure_ascii=False), str)

    def test_json_roundtrip_full_entity(self):
        """全字段实体 model_dump(mode='json') → model_validate 还原相等
        （datetime ↔ ISO8601 字符串，API 序列化契约）。"""
        t = AgentTemplate(
            id=1,
            name="t",
            description="desc",
            main_model="openai/gpt-4o",
            default_temperature=0.8,
            roles={
                "architect": RoleTemplate(model="m/a"),
                "writer": RoleTemplate(model="m/w", temperature=0.6, enabled=False),
            },
            default_words=50000,
            is_default=True,
            created_at=TS,
            updated_at=TS,
        )
        dumped = t.model_dump(mode="json")
        assert dumped["id"] == 1
        assert dumped["is_default"] is True
        assert isinstance(dumped["created_at"], str)
        assert dumped["roles"]["writer"] == {
            "model": "m/w",
            "temperature": 0.6,
            "enabled": False,
            "prompt": None,
            "name": None,
        }
        reloaded = AgentTemplate.model_validate(dumped)
        assert reloaded == t

    def test_from_attributes(self):
        """from_attributes=True：可直接从 ORM 风格对象 model_validate
        （repo _orm_to_domain 转换惯例，同 F13）。"""
        src = SimpleNamespace(
            id=1,
            name="t",
            description="",
            main_model=None,
            default_temperature=None,
            roles={},
            default_words=None,
            is_default=False,
            created_at=None,
            updated_at=None,
        )
        t = AgentTemplate.model_validate(src)
        assert t.id == 1
        assert t.name == "t"


class TestAgentTemplateCreate:
    """AgentTemplateCreate 请求 DTO 验证（name 必填 + 非空白 + 无服务端字段）。"""

    def test_create_valid_strips_name_and_defaults(self):
        """合法创建：name 去空白，其余字段默认（同实体默认值）。"""
        create = AgentTemplateCreate(name="  我的模板  ")
        assert create.name == "我的模板"
        assert create.description == ""
        assert create.main_model is None
        assert create.default_temperature is None
        assert create.roles == {}
        assert create.default_words is None

    def test_create_name_required(self):
        """缺 name → ValidationError."""
        with pytest.raises(ValidationError):
            AgentTemplateCreate()

    def test_create_blank_name_rejected(self):
        """空/纯空白 name → ValidationError，文案精确为「模板名称不能为空」。"""
        with pytest.raises(ValidationError, match="模板名称不能为空"):
            AgentTemplateCreate(name="")
        with pytest.raises(ValidationError, match="模板名称不能为空"):
            AgentTemplateCreate(name="   ")

    def test_create_roles_coerced_from_dict(self):
        """roles 接受 dict 列表并强制转换为 RoleTemplate。"""
        create = AgentTemplateCreate(
            name="t", roles={"writer": {"model": "m/w", "temperature": 1.1}}
        )
        assert create.roles == {"writer": RoleTemplate(model="m/w", temperature=1.1)}
        assert create.roles["writer"].enabled is True

    def test_create_default_temperature_bounds(self):
        """default_temperature 越界 → ValidationError。"""
        with pytest.raises(ValidationError):
            AgentTemplateCreate(name="t", default_temperature=-0.1)
        with pytest.raises(ValidationError):
            AgentTemplateCreate(name="t", default_temperature=2.1)

    def test_create_default_words_bounds(self):
        """default_words 越界 → ValidationError。"""
        with pytest.raises(ValidationError):
            AgentTemplateCreate(name="t", default_words=999)
        with pytest.raises(ValidationError):
            AgentTemplateCreate(name="t", default_words=10_000_001)

    def test_create_has_no_id_is_default_or_timestamps(self):
        """Create DTO 无 id/is_default/created_at/updated_at 字段
        （id 由 repo 分配，is_default 服务层固定 False，时间戳服务层填充）。"""
        assert "id" not in AgentTemplateCreate.model_fields
        assert "is_default" not in AgentTemplateCreate.model_fields
        assert "created_at" not in AgentTemplateCreate.model_fields
        assert "updated_at" not in AgentTemplateCreate.model_fields


class TestAgentTemplateUpdate:
    """AgentTemplateUpdate 部分更新语义测试（exclude_unset，同 F1/F13）。"""

    def test_update_all_optional_empty_by_default(self):
        """全字段可选；未传字段不进 model_fields_set。"""
        u = AgentTemplateUpdate()
        assert u.name is None
        assert u.description is None
        assert u.main_model is None
        assert u.default_temperature is None
        assert u.roles is None
        assert u.default_words is None
        assert u.is_default is None
        assert u.model_fields_set == set()

    def test_update_partial_semantics(self):
        """仅传入字段出现在 model_fields_set。"""
        u = AgentTemplateUpdate(name="new-name")
        assert u.model_fields_set == {"name"}
        u2 = AgentTemplateUpdate(main_model="m1", is_default=False)
        assert u2.model_fields_set == {"main_model", "is_default"}

    def test_update_blank_name_rejected(self):
        """name 提供时同样拒绝空/纯空白（文案同 Create）。"""
        with pytest.raises(ValidationError, match="模板名称不能为空"):
            AgentTemplateUpdate(name="")
        with pytest.raises(ValidationError, match="模板名称不能为空"):
            AgentTemplateUpdate(name="  ")

    def test_update_temperature_bounds(self):
        """default_temperature 越界 → ValidationError（提供时校验）。"""
        with pytest.raises(ValidationError):
            AgentTemplateUpdate(default_temperature=2.1)
        assert AgentTemplateUpdate(default_temperature=1.5).default_temperature == 1.5

    def test_update_explicit_false_is_default(self):
        """显式 is_default=False 保留（PATCH 取消默认语义）。"""
        u = AgentTemplateUpdate(is_default=False)
        assert u.is_default is False
        assert "is_default" in u.model_fields_set


class TestRoleTemplatePromptName:
    """F42 #295 RoleTemplate 扩展 prompt/name（spec §5.3.4 数据面第 1 点）。

    契约：prompt/name 均为可选字段，默认 None（零迁移：旧 roles JSON 无键
    → 读回默认 None）；显式赋值保留；model_dump/model_validate roundtrip 含新键。

    RED 形态：RoleTemplate().prompt → AttributeError（字段不存在）。
    GREEN 适配预警（既有测试）：test_json_roundtrip（L110-114）、
    test_json_roundtrip_full_entity（L224-248）等 model_dump 精确 dict 断言
    会因 model_dump 多出 prompt/name 键而翻红——GREEN 阶段同步补键。
    """

    def test_defaults_prompt_name_none(self):
        """默认 prompt=None, name=None（零迁移）。"""
        r = RoleTemplate()
        assert r.prompt is None
        assert r.name is None

    def test_explicit_prompt_name(self):
        """显式赋值 prompt/name 保留。"""
        r = RoleTemplate(prompt="你是自定义研究员", name="研究员")
        assert r.prompt == "你是自定义研究员"
        assert r.name == "研究员"

    def test_json_roundtrip_includes_prompt_name(self):
        """model_dump(mode='json') → model_validate 还原含 prompt/name（API 序列化契约）。"""
        r = RoleTemplate(model="openai/gpt-4o", prompt="p", name="n", enabled=True)
        reloaded = RoleTemplate.model_validate(r.model_dump(mode="json"))
        assert reloaded == r
        assert reloaded.prompt == "p"
        assert reloaded.name == "n"
