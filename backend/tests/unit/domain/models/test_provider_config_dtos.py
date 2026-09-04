"""#106 ProviderConfig 领域模型单元测试 — 无 I/O，纯 Pydantic 验证（RED 批，P1 实体）。

测试范围：ProviderModel（模型条目）/ ProviderConfig（注册表实体）/
ProviderConfigCreate / ProviderConfigUpdate 请求 DTO。
依据: specs/f19-gui/spec.md §8.2①（注册表实体字段）+ §8.5 测试策略「后端单元」。

══════════════════════ 设计假设（GREEN 实现者唯一契约）══════════════════════

模块: ``inkflow.domain.models.provider_config``（本批新建，当前不存在 →
收集期 ModuleNotFoundError 即预期 RED 形态）。

类与字段（Pydantic v2 BaseModel）:

1. ``ProviderModel`` — 单个模型条目:
   - ``id: str``（必填，模型标识，如 "gpt-4o"）
   - ``type: Literal["chat", "embedding"]``（必填；§8.2① chat|embedding 二值）
   - ``roles: list[str] = Field(default_factory=list)``（角色用途标记，默认空）

2. ``ProviderConfig`` — 注册表实体（§8.2① 字段全集）:
   - ``id: int | None = None``（None = 未落库；repo.add 后由 DB 自增分配）
   - ``name: str``（必填；provider 名，唯一）
   - ``base_url: str | None = None``
   - ``default_model: str | None = None``
   - ``models: list[ProviderModel] = Field(default_factory=list)``
   - ``max_retries: int = 3``
   - ``timeout: int = 120``
   - ``created_at: datetime | None = None`` / ``updated_at: datetime | None = None``
     （服务层落库时填充；实体本身允许 None）
   - ``model_config = {"from_attributes": True}``（repo _orm_to_domain 惯例）

3. ``ProviderConfigCreate`` — 创建请求 DTO:
   - ``name: str`` 必填，校验规则：去空白后非空，失败文案精确为
     **"Provider 名称不能为空"**（空白 name 拒绝，422 语义）；
   - 其余字段同 ProviderConfig（base_url/default_model/models/max_retries/
     timeout，默认值一致）；**无 id/created_at/updated_at 字段**
   - 不做 provider 名格式校验（小写字母/数字/下划线/连字符等）——本批
     契约仅「非空白」，格式校验不在范围（有意不约束，YAGNI）

4. ``ProviderConfigUpdate`` — 更新请求 DTO:
   - 全字段可选（``str | None = None`` / ``list[ProviderModel] | None = None`` /
     ``int | None = None``），exclude_unset 语义（同 F1/F13）；
   - name 提供时同样做非空白校验（文案同上）。

错误类归属: 本文件不定义错误类（纯 DTO）；空白校验失败抛
``pydantic.ValidationError``（Pydantic 内置，422 由 FastAPI 映射）。

JSON roundtrip 契约: ``model_dump(mode="json")`` 产物可被
``model_validate`` 还原为相等实体（datetime ↔ ISO8601 字符串双向）。

⚠️ 本批为 RED：不写任何 src/ 实现；GREEN 按上述签名实现后本文件应全绿。
"""

from datetime import datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from inkflow.domain.models.provider_config import (
    ProviderConfig,
    ProviderConfigCreate,
    ProviderConfigUpdate,
    ProviderModel,
)

TS = datetime(2026, 8, 1, 10, 0, 0)


class TestProviderModel:
    """ProviderModel 模型条目测试（§8.2①: {id, type: chat|embedding, roles}）。"""

    def test_defaults_roles_empty(self):
        """roles 默认空列表."""
        m = ProviderModel(id="gpt-4o", type="chat")
        assert m.id == "gpt-4o"
        assert m.type == "chat"
        assert m.roles == []

    def test_required_fields(self):
        """id / type 均为必填（缺任一 → ValidationError）."""
        with pytest.raises(ValidationError):
            ProviderModel(type="chat")
        with pytest.raises(ValidationError):
            ProviderModel(id="gpt-4o")

    def test_type_literal_chat_and_embedding(self):
        """type 仅接受 'chat' / 'embedding' 二值；其余 → ValidationError."""
        assert ProviderModel(id="m1", type="chat").type == "chat"
        assert ProviderModel(id="m2", type="embedding").type == "embedding"
        with pytest.raises(ValidationError):
            ProviderModel(id="m3", type="vision")

    def test_json_roundtrip(self):
        """model_dump(mode='json') → model_validate 还原为相等实体."""
        m = ProviderModel(id="gpt-4o", type="chat", roles=["writing", "audit"])
        reloaded = ProviderModel.model_validate(m.model_dump(mode="json"))
        assert reloaded == m


class TestProviderConfig:
    """ProviderConfig 注册表实体测试（§8.2① 字段全集）。"""

    def test_entity_defaults(self):
        """默认值：id=None, base_url=None, default_model=None, models=[],
        max_retries=3, timeout=120, created_at=None, updated_at=None."""
        cfg = ProviderConfig(name="openai")
        assert cfg.id is None
        assert cfg.name == "openai"
        assert cfg.base_url is None
        assert cfg.default_model is None
        assert cfg.models == []
        assert cfg.max_retries == 3
        assert cfg.timeout == 120
        assert cfg.created_at is None
        assert cfg.updated_at is None

    def test_entity_requires_name(self):
        """缺 name → ValidationError."""
        with pytest.raises(ValidationError):
            ProviderConfig()

    def test_models_default_factory_isolated(self):
        """models 使用 default_factory：实例间不共享同一列表对象."""
        a = ProviderConfig(name="a")
        b = ProviderConfig(name="b")
        a.models.append(ProviderModel(id="x", type="chat"))
        assert a.models == [ProviderModel(id="x", type="chat")]
        assert b.models == []

    def test_json_roundtrip_full_entity(self):
        """全字段实体 model_dump(mode='json') → model_validate 还原相等
        （datetime ↔ ISO8601 字符串，API 序列化契约）。"""
        cfg = ProviderConfig(
            id=1,
            name="openai",
            base_url="https://api.openai.com/v1",
            default_model="gpt-4o",
            models=[ProviderModel(id="gpt-4o", type="chat", roles=["writing"])],
            max_retries=5,
            timeout=60,
            created_at=TS,
            updated_at=TS,
        )
        dumped = cfg.model_dump(mode="json")
        assert dumped["id"] == 1
        assert dumped["models"] == [{"id": "gpt-4o", "type": "chat", "roles": ["writing"]}]
        assert isinstance(dumped["created_at"], str)
        reloaded = ProviderConfig.model_validate(dumped)
        assert reloaded == cfg
        assert reloaded.models[0].type == "chat"

    def test_from_attributes(self):
        """from_attributes=True：可直接从 ORM 风格对象 model_validate
        （repo _orm_to_domain 转换惯例，同 F13）。"""
        src = SimpleNamespace(
            id=1,
            name="openai",
            base_url=None,
            default_model=None,
            models=[],
            max_retries=3,
            timeout=120,
            created_at=None,
            updated_at=None,
        )
        cfg = ProviderConfig.model_validate(src)
        assert cfg.id == 1
        assert cfg.name == "openai"


class TestProviderConfigCreate:
    """ProviderConfigCreate 请求 DTO 验证（name 必填 + 非空白校验）。"""

    def test_create_valid_strips_name_and_defaults(self):
        """合法创建：name 去空白，其余字段默认（同实体默认值）。"""
        create = ProviderConfigCreate(name="  openai  ")
        assert create.name == "openai"
        assert create.base_url is None
        assert create.default_model is None
        assert create.models == []
        assert create.max_retries == 3
        assert create.timeout == 120

    def test_create_name_required(self):
        """缺 name → ValidationError."""
        with pytest.raises(ValidationError):
            ProviderConfigCreate()

    def test_create_blank_name_rejected(self):
        """空/纯空白 name → ValidationError，文案精确为「Provider 名称不能为空」."""
        with pytest.raises(ValidationError, match="Provider 名称不能为空"):
            ProviderConfigCreate(name="")
        with pytest.raises(ValidationError, match="Provider 名称不能为空"):
            ProviderConfigCreate(name="   ")

    def test_create_models_coerced_from_dict(self):
        """models 接受 dict 列表并强制转换为 ProviderModel（API JSON 输入路径）."""
        create = ProviderConfigCreate(name="openai", models=[{"id": "gpt-4o", "type": "chat"}])
        assert create.models == [ProviderModel(id="gpt-4o", type="chat")]
        assert create.models[0].roles == []

    def test_create_has_no_id_or_timestamps(self):
        """Create DTO 无 id/created_at/updated_at 字段（id 由 repo 分配，
        时间戳由服务层落库时填充）。"""
        assert "id" not in ProviderConfigCreate.model_fields
        assert "created_at" not in ProviderConfigCreate.model_fields
        assert "updated_at" not in ProviderConfigCreate.model_fields


class TestProviderConfigUpdate:
    """ProviderConfigUpdate 部分更新语义测试（exclude_unset，同 F1/F13）。"""

    def test_update_all_optional_empty_by_default(self):
        """全字段可选；未传字段不进 model_fields_set."""
        u = ProviderConfigUpdate()
        assert u.name is None
        assert u.base_url is None
        assert u.default_model is None
        assert u.models is None
        assert u.max_retries is None
        assert u.timeout is None
        assert u.model_fields_set == set()

    def test_update_partial_semantics(self):
        """仅传入字段出现在 model_fields_set."""
        u = ProviderConfigUpdate(name="new-name")
        assert u.model_fields_set == {"name"}
        u2 = ProviderConfigUpdate(max_retries=7, timeout=30)
        assert u2.model_fields_set == {"max_retries", "timeout"}

    def test_update_blank_name_rejected(self):
        """name 提供时同样拒绝空/纯空白（文案同 Create）。"""
        with pytest.raises(ValidationError, match="Provider 名称不能为空"):
            ProviderConfigUpdate(name="")
        with pytest.raises(ValidationError, match="Provider 名称不能为空"):
            ProviderConfigUpdate(name="  ")
