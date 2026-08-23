"""项目 DTO 单元测试 — 无 I/O，纯 Pydantic 验证。

测试范围：ProjectCreate / ProjectUpdate DTO 验证。
"""

import pytest
from pydantic import ValidationError

from inkflow.domain.models.project import (
    ProjectConfig,
    ProjectCreate,
    ProjectUpdate,
)


class TestProjectCreateValidation:
    """Pydantic DTO 层面的创建验证测试."""

    def test_create_with_valid_data(self):
        """正常创建，所有字段合法."""
        project = ProjectCreate(
            name="测试小说",
            tags=["玄幻"],
            language="zh-CN",
            target_words=100000,
        )
        assert project.name == "测试小说"
        assert project.tags == ["玄幻"]
        assert project.language == "zh-CN"
        assert project.target_words == 100000

    def test_create_empty_name_raises(self):
        """空名称应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="项目名称不能为空"):
            ProjectCreate(name="")

    def test_create_whitespace_name_raises(self):
        """纯空格名称应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="项目名称不能为空"):
            ProjectCreate(name="   ")

    def test_create_name_too_long_raises(self):
        """超过 100 字符的名称应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="项目名称不能超过 100 个字符"):
            ProjectCreate(name="长" * 101)

    def test_create_defaults(self):
        """默认值：tags=[], language='zh-CN', target_words=0, model=None（#520 未配置）."""
        project = ProjectCreate(name="默认测试")
        assert project.tags == []
        assert project.language == "zh-CN"
        assert project.target_words == 0
        assert project.config.model is None


class TestProjectUpdateValidation:
    """更新请求 Pydantic 验证测试."""

    def test_update_partial(self):
        """部分更新：未提供的字段应为 None."""
        update = ProjectUpdate(name="新名称")
        assert update.name == "新名称"
        assert update.tags is None
        assert update.language is None
        assert update.target_words is None
        assert update.config is None
        assert update.is_deleted is None

    def test_update_empty_name_raises(self):
        """空名称更新应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="项目名称不能为空"):
            ProjectUpdate(name="")


class TestProjectConfigDefaultWords:
    """ProjectConfig.default_words 字段契约（🔴-4 方案 A）.

    契约：默认 800000，范围 [1000, 10_000_000]，序列化 round-trip 保留。
    评审 finding：前端 PATCH config.default_words 被后端静默丢弃（模型无此字段，
    Pydantic extra='ignore'）——本类测试先锁定字段契约，修复后转 GREEN。
    """

    def test_default_words_default_value(self):
        """未显式赋值时 default_words 默认为 800000."""
        config = ProjectConfig()
        assert config.default_words == 800000

    def test_default_words_explicit_value(self):
        """显式赋值保留：default_words=50000."""
        config = ProjectConfig(default_words=50000)
        assert config.default_words == 50000

    def test_default_words_below_min_raises(self):
        """default_words=0 低于 ge=1000 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="greater than or equal to 1000"):
            ProjectConfig(default_words=0)

    def test_default_words_above_max_raises(self):
        """default_words=10000001 高于 le=10_000_000 应抛出 ValidationError."""
        with pytest.raises(ValidationError, match="less than or equal to 10000000"):
            ProjectConfig(default_words=10000001)

    def test_default_words_serialization_roundtrip(self):
        """model_dump 序列化 round-trip 保留 default_words 字段值."""
        config = ProjectConfig(default_words=50000)
        assert config.model_dump()["default_words"] == 50000


class TestProjectConfigAgentSemantics:
    """ProjectConfig.agent_* 三态语义契约（#225，方案 1 + sentinel 扩展，2026-08-10 拍板）.

    契约（M3）：
    - 显式 null = 关闭（禁用该角色）
    - 字符串 = 开启且指定模型
    - 字符串 "__default__"（AGENT_DEFAULT_SENTINEL 常量）= 跟随默认（预留，前端本期不暴露）
    - 空字符串（含纯空白）无意义 → ValidationError

    RED 预期：常量未实现 → 用例体惰性 import 抛 ImportError（FAILED，非 ERROR）；
    空串校验未实现 → pytest.raises DID NOT RAISE（干净断言 FAIL）。
    """

    def test_agent_sentinel_constant_defined(self):
        """AGENT_DEFAULT_SENTINEL 常量存在且值为 "__default__"（用例体惰性 import = RED 失败点）."""
        from inkflow.domain.models.project import AGENT_DEFAULT_SENTINEL

        assert AGENT_DEFAULT_SENTINEL == "__default__"

    def test_agent_sentinel_accept_and_roundtrip(self):
        """sentinel "__default__" 合法（跟随默认预留）：构造不报错 + model_dump roundtrip 保留."""
        from inkflow.domain.models.project import AGENT_DEFAULT_SENTINEL

        config = ProjectConfig(agent_writer=AGENT_DEFAULT_SENTINEL)
        assert config.agent_writer == AGENT_DEFAULT_SENTINEL
        assert config.model_dump()["agent_writer"] == AGENT_DEFAULT_SENTINEL

    def test_agent_explicit_null_roundtrip(self):
        """显式 null = 关闭：构造保留 + model_dump 序列化保留（null 落库语义）."""
        config = ProjectConfig(agent_architect=None)
        assert config.agent_architect is None
        assert config.model_dump()["agent_architect"] is None

    def test_agent_string_model_roundtrip(self):
        """字符串 = 开启且指定模型：值保留 + 不污染其他 agent_* 字段."""
        config = ProjectConfig(agent_writer="deepseek/deepseek-chat")
        assert config.agent_writer == "deepseek/deepseek-chat"
        assert config.agent_architect is None  # 未指定角色保持默认 None（关闭）

    def test_agent_empty_string_rejected(self):
        """空字符串（含纯空白）作为模型名无意义 → ValidationError（#225 语义：字符串=指定模型）."""
        with pytest.raises(ValidationError):
            ProjectConfig(agent_writer="")
        with pytest.raises(ValidationError):
            ProjectConfig(agent_writer="   ")


class TestProjectConfigSupervisor:
    """ProjectConfig.supervisor 字段契约（#343 拍板 2A：项目级 HITL 配置，2026-08-16）.

    契约：
    - 缺省 = None（零迁移，旧 config JSON 无键不报错）
    - supervisor.hitl_roles 合法列表 → roundtrip 保留
    - supervisor.hitl_roles 非 list → ValidationError

    RED 预期：ProjectConfig 无 supervisor 字段 → 构造即 ValidationError（extra
    拒绝或未知字段）→ 断言 FAIL；GREEN 后全部转绿。
    """

    def test_supervisor_default_none(self):
        """未配置 supervisor → None（零迁移语义）."""
        config = ProjectConfig()
        assert config.supervisor is None

    def test_supervisor_hitl_roles_roundtrip(self):
        """supervisor.hitl_roles 合法列表 → 构造 + model_dump roundtrip 保留."""
        config = ProjectConfig(supervisor={"hitl_roles": ["reviser"]})
        assert config.supervisor is not None
        assert config.supervisor.hitl_roles == ["reviser"]
        dumped = config.model_dump()
        assert dumped["supervisor"]["hitl_roles"] == ["reviser"]

    def test_supervisor_hitl_roles_invalid_type(self):
        """supervisor.hitl_roles 非 list → ValidationError（类型安全）."""
        with pytest.raises(ValidationError):
            ProjectConfig(supervisor={"hitl_roles": "reviser"})


class TestProjectTags:
    """#595 tags 多值标签取代 genre 枚举契约（2026-08-23 拍板 D6=B / D7=A）。

    契约：
    - ProjectCreate(tags=[...]) → tags 保留（多选 + 自定义新增）
    - ProjectCreate 默认 tags=[]（不再有 genre 字段）
    - tags 每项 strip 后非空；空白/空串项 → ValidationError「项目标签不能为空」
    - tags 去重（保留首次出现序）；单标签长度 > 50 → ValidationError
    - ProjectUpdate(tags=[...]) → tags 整体替换（全量）

    RED 预期：ProjectCreate/ProjectUpdate 当前只有 genre 字段（无 tags）→ 构造后
    project.tags / update.tags 抛 AttributeError；tags 校验未实现 → pytest.raises
    DID NOT RAISE。干净断言 FAIL，GREEN 后全部转绿。
    """

    def test_create_accepts_tags(self):
        """正常创建携带多值 tags（多选 + 自定义）→ 保留。"""
        project = ProjectCreate(name="测试小说", tags=["玄幻", "热血", "升级流"])
        assert project.tags == ["玄幻", "热血", "升级流"]

    def test_create_default_tags_empty(self):
        """默认 tags=[]，且不再有 genre 字段。"""
        project = ProjectCreate(name="默认测试")
        assert project.tags == []
        assert not hasattr(project, "genre")

    def test_create_tags_whitespace_raises(self):
        """tags 项为纯空白 → ValidationError「项目标签不能为空」。"""
        with pytest.raises(ValidationError, match="项目标签不能为空"):
            ProjectCreate(name="测试小说", tags=["   "])

    def test_create_tags_dedup(self):
        """tags 重复项去重，保留首次出现顺序。"""
        project = ProjectCreate(name="测试小说", tags=["玄幻", "玄幻", "热血"])
        assert project.tags == ["玄幻", "热血"]

    def test_create_tags_too_long_raises(self):
        """单标签长度 > 50 → ValidationError。"""
        with pytest.raises(ValidationError):
            ProjectCreate(name="测试小说", tags=["长" * 51])

    def test_update_tags_replaces_whole(self):
        """ProjectUpdate.tags 整体替换（全量语义，非增量合并）。"""
        update = ProjectUpdate(tags=["仙侠", "东方玄幻"])
        assert update.tags == ["仙侠", "东方玄幻"]
        assert not hasattr(update, "genre")
