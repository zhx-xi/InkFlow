"""F32 设置领域模型契约测试 — AppSettings / AppSettingsUpdate / SettingsKey（RED 批）。

覆盖 spec §2.2（领域模型代码块逐字为准）+ §9.4 契约断言表:
- AppSettings 默认值齐全（model_dump == 6 字段默认字典）
- AppSettingsUpdate 枚举校验（Literal 拒绝非法值 → ValidationError）
- 未知字段 → ValidationError（extra='forbid'）
- 空更新对象（全 None）合法不抛错（路由层负责空 body 422）
- JSON roundtrip（model_validate(model_dump()) 相等）

依据: specs/f32-settings-persistence/spec.md §2.2 + §9.1/§9.4。

══════════════════════ 设计假设（GREEN 实现者唯一契约）══════════════════════

模块（本批新建，当前不存在 → 收集期 ModuleNotFoundError 即预期 RED 形态）:
``inkflow.domain.models.settings``，逐字实现 spec §2.2 代码块:

1. 类型别名:
   - ``ThemeName = Literal["paper", "night", "ink"]``
   - ``ThemeBg = Literal["default", "parchment", "navy", "ochre"]``
   - ``Lang = Literal["zh", "en"]``
   - ``FontKey = Literal["serif", "sans", "mono"]``
   - ``CloseBehavior = Literal["tray", "quit"]``

2. ``class SettingsKey(str, Enum)`` — 6 成员，value = 设置键名:
   THEME="theme" / BG="bg" / LANG="lang" / FONT="font" /
   CLOSE_BEHAVIOR="close_behavior" / TRAY_HINT_DISMISSED="tray_hint_dismissed"

3. ``class AppSettings(BaseModel)``:
   - ``model_config = {"from_attributes": True}``
   - 6 字段全带默认值: theme="paper" / bg="default" / lang="zh" /
     font="sans" / close_behavior="tray" / tray_hint_dismissed=False

4. ``class AppSettingsUpdate(BaseModel)``:
   - ``model_config = {"extra": "forbid"}``（未知字段 → ValidationError）
   - 6 字段全可选（``X | None = None``），空对象（全 None）合法

5. 枚举校验落点 = Pydantic Literal（service 层不重复校验）:
   theme="dark" → ValidationError（§9.4 RED 契约核心）。

⚠️ 本批为 RED：不写任何 src/ 实现；GREEN 按上述签名实现后本文件应全绿。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from inkflow.domain.models.settings import (
    AppSettings,
    AppSettingsUpdate,
    SettingsKey,
)


def _defaults() -> dict:
    """17 字段默认字典（§2.1 表 + §2.2 AppSettings 默认值）。

    F27 扩展（#160 Q2 拍板）：agent_max_steps/agent_token_budget/
    agent_max_total_tool_calls 预算护栏设置键（ADR-C 默认值 12/32K/20；
    #430 语义改造: 单工具连续 → 会话总调用上限）。
    #277 M3 扩展（spec §5.6.1/§5.6.3）：rag_chunk_mode/rag_chunk_size/
    rag_chunk_overlap/rag_chunk_overlap_ratio 切片配置 4 键。
    #479 扩展（spec f48 §5.5.2）：kg_extract_enabled/interval_hours/method
    知识图谱定时提取三键（默认 False/24/rule，开箱零成本零风险）。
    """
    return {
        "theme": "paper",
        "bg": "default",
        "lang": "zh",
        "font": "sans",
        "close_behavior": "tray",
        "tray_hint_dismissed": False,
        "default_words": 800000,
        "agent_max_steps": 12,
        "agent_token_budget": 32000,
        "agent_max_total_tool_calls": 20,
        "rag_chunk_mode": "fixed",
        "rag_chunk_size": 500,
        "rag_chunk_overlap": False,
        "rag_chunk_overlap_ratio": 0.15,
        "kg_extract_enabled": False,
        "kg_extract_interval_hours": 24,
        "kg_extract_method": "rule",
    }


class TestAppSettings:
    """AppSettings 默认值 + 合法字面量 + JSON roundtrip 契约。"""

    def test_defaults_complete(self):
        """空构造 == 10 字段默认字典（§9.4「默认值齐全」）。"""
        assert AppSettings().model_dump() == _defaults()

    def test_accepts_all_valid_literals(self):
        """全部合法字面量可构造（锁 Literal 值域，防实现收窄）。"""
        s = AppSettings(
            theme="night",
            bg="navy",
            lang="en",
            font="mono",
            close_behavior="quit",
            tray_hint_dismissed=True,
            default_words=5000,
            agent_max_steps=8,
            agent_token_budget=16000,
            agent_max_total_tool_calls=5,
            rag_chunk_mode="paragraph",
            rag_chunk_size=600,
            rag_chunk_overlap=True,
            rag_chunk_overlap_ratio=0.18,
        )
        assert s.model_dump() == {
            "theme": "night",
            "bg": "navy",
            "lang": "en",
            "font": "mono",
            "close_behavior": "quit",
            "tray_hint_dismissed": True,
            "default_words": 5000,
            "agent_max_steps": 8,
            "agent_token_budget": 16000,
            "agent_max_total_tool_calls": 5,
            "rag_chunk_mode": "paragraph",
            "rag_chunk_size": 600,
            "rag_chunk_overlap": True,
            "rag_chunk_overlap_ratio": 0.18,
            "kg_extract_enabled": False,
            "kg_extract_interval_hours": 24,
            "kg_extract_method": "rule",
        }

    def test_json_roundtrip(self):
        """model_validate(model_dump()) 相等（默认对象与显式值对象各一）。"""
        assert AppSettings.model_validate(AppSettings().model_dump()) == AppSettings()
        original = AppSettings(theme="night", font="mono", tray_hint_dismissed=True)
        assert AppSettings.model_validate(original.model_dump()) == original

    @pytest.mark.parametrize("chunk_size", [50, 2001, 0, -1])
    def test_rejects_chunk_size_out_of_range(self, chunk_size):
        """rag_chunk_size 越界（非 100-2000）→ ValidationError（spec §5.6.2）。"""
        with pytest.raises(ValidationError):
            AppSettings(rag_chunk_size=chunk_size)

    @pytest.mark.parametrize("ratio", [0.05, 0.25, 0.0, 1.0])
    def test_rejects_overlap_ratio_out_of_range(self, ratio):
        """rag_chunk_overlap_ratio 越界（非 [0.10, 0.20]）→ ValidationError（spec §5.6.3）。"""
        with pytest.raises(ValidationError):
            AppSettings(rag_chunk_overlap_ratio=ratio)

    @pytest.mark.parametrize("hours", [0, 169, -1, 1000])
    def test_rejects_kg_interval_out_of_range(self, hours):
        """kg_extract_interval_hours 越界（非 1-168）→ ValidationError（spec f48 §5.5.2）。"""
        with pytest.raises(ValidationError):
            AppSettings(kg_extract_interval_hours=hours)


class TestAppSettingsUpdate:
    """AppSettingsUpdate DTO 校验契约（枚举 / 未知字段 / 空对象）。"""

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"theme": "dark"},
            {"bg": "neon"},
            {"lang": "fr"},
            {"font": "comic"},
            {"close_behavior": "exit"},
        ],
    )
    def test_rejects_invalid_literals(self, kwargs):
        """非法枚举值 → ValidationError（Literal 拒绝，§9.4「枚举校验」）。"""
        with pytest.raises(ValidationError):
            AppSettingsUpdate(**kwargs)

    def test_rejects_unknown_field(self):
        """未知字段 → ValidationError（extra='forbid'，§9.4「未知字段」）。"""
        with pytest.raises(ValidationError):
            AppSettingsUpdate(themee="night")

    def test_rejects_unknown_field_on_valid_payload(self):
        """合法字段 + 未知字段混搭同样拒绝（extra='forbid' 全局生效）。"""
        with pytest.raises(ValidationError):
            AppSettingsUpdate(theme="night", themee="night")

    def test_empty_update_all_none_valid(self):
        """空更新对象（全 None）合法不抛错——路由层负责空 body 422（§3.4）。"""
        u = AppSettingsUpdate()
        assert u.model_dump() == {k: None for k in _defaults()}
        assert u.model_dump(exclude_none=True) == {}

    def test_partial_update_only_provided_fields(self):
        """部分字段更新：exclude_none 只含显式字段（service/路由层依赖）。"""
        u = AppSettingsUpdate(theme="night")
        assert u.model_dump(exclude_none=True) == {"theme": "night"}


class TestSettingsKey:
    """SettingsKey 枚举契约（§2.2，service 白名单依赖 value 构造）。"""

    def test_members_and_values(self):
        """17 成员 + value 与 §2.1 设置键名一一对应（#479 追加 kg_extract_* 三键）。"""
        assert {k.name: k.value for k in SettingsKey} == {
            "THEME": "theme",
            "BG": "bg",
            "LANG": "lang",
            "FONT": "font",
            "CLOSE_BEHAVIOR": "close_behavior",
            "TRAY_HINT_DISMISSED": "tray_hint_dismissed",
            "DEFAULT_WORDS": "default_words",
            "AGENT_MAX_STEPS": "agent_max_steps",
            "AGENT_TOKEN_BUDGET": "agent_token_budget",
            "AGENT_MAX_TOTAL_TOOL_CALLS": "agent_max_total_tool_calls",
            "RAG_CHUNK_MODE": "rag_chunk_mode",
            "RAG_CHUNK_SIZE": "rag_chunk_size",
            "RAG_CHUNK_OVERLAP": "rag_chunk_overlap",
            "RAG_CHUNK_OVERLAP_RATIO": "rag_chunk_overlap_ratio",
            "KG_EXTRACT_ENABLED": "kg_extract_enabled",
            "KG_EXTRACT_INTERVAL_HOURS": "kg_extract_interval_hours",
            "KG_EXTRACT_METHOD": "kg_extract_method",
        }

    def test_construct_by_value(self):
        """按 value 构造（service 白名单 ``SettingsKey(field)`` 的依赖）。"""
        assert SettingsKey("theme") is SettingsKey.THEME
        assert SettingsKey("tray_hint_dismissed") is SettingsKey.TRAY_HINT_DISMISSED
        assert SettingsKey("rag_chunk_mode") is SettingsKey.RAG_CHUNK_MODE
        assert SettingsKey("rag_chunk_overlap_ratio") is SettingsKey.RAG_CHUNK_OVERLAP_RATIO


class TestChunkSettingsValidation:
    """#277 切片配置 4 键校验（spec §5.6.2/§5.6.3：越界 → 422 ValidationError）."""

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"rag_chunk_mode": "char"},  # 非法切片模式（仅 fixed/paragraph/dialogue/llm）
            {"rag_chunk_mode": ""},  # 空串
            {"rag_chunk_size": 99},  # 低于下限 100
            {"rag_chunk_size": 2001},  # 高于上限 2000
            {"rag_chunk_size": 0},  # 非正数
            {"rag_chunk_overlap_ratio": 0.05},  # 低于下限 0.10
            {"rag_chunk_overlap_ratio": 0.25},  # 高于上限 0.20
            {"rag_chunk_overlap_ratio": 0.0},  # 关闭语义应走 overlap=False，不写 ratio
        ],
    )
    def test_rejects_invalid_chunk_settings(self, kwargs):
        """切片配置越界/非法 → ValidationError（app_settings 校验层 422）。"""
        with pytest.raises(ValidationError):
            AppSettingsUpdate(**kwargs)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"rag_chunk_mode": "paragraph"},
            {"rag_chunk_mode": "dialogue"},
            {"rag_chunk_mode": "llm"},
            {"rag_chunk_size": 100},
            {"rag_chunk_size": 2000},
            {"rag_chunk_overlap": True},
            {"rag_chunk_overlap_ratio": 0.10},
            {"rag_chunk_overlap_ratio": 0.20},
        ],
    )
    def test_accepts_valid_chunk_settings(self, kwargs):
        """切片配置合法边界值可构造（防实现收窄）。"""
        AppSettingsUpdate(**kwargs)


class TestKgExtractSettings:
    """#479 知识图谱定时提取三键（spec f48 §5.5.2）— SettingsKey / AppSettings / Update。

    RED 形态: SettingsKey 新枚举成员 / AppSettings 新字段缺失 → AttributeError；
    AppSettingsUpdate 新字段缺失（extra='forbid' 拒绝一切值）→ 合法值用例抛
    ValidationError（假绿防护核心）；默认值断言失败 → AssertionError。
    """

    def test_settings_key_new_members(self):
        """SettingsKey 新增三枚举成员（spec f48 §5.5.2 键名表）。"""
        assert SettingsKey.KG_EXTRACT_ENABLED.value == "kg_extract_enabled"
        assert SettingsKey.KG_EXTRACT_INTERVAL_HOURS.value == "kg_extract_interval_hours"
        assert SettingsKey.KG_EXTRACT_METHOD.value == "kg_extract_method"

    def test_construct_new_keys_by_value(self):
        """新键按 value 构造（service 白名单 SettingsKey(field) 依赖）。"""
        assert SettingsKey("kg_extract_enabled") is SettingsKey.KG_EXTRACT_ENABLED
        assert SettingsKey("kg_extract_method") is SettingsKey.KG_EXTRACT_METHOD

    def test_app_settings_defaults(self):
        """AppSettings 三键默认值: False / 24 / 'rule'（开箱零成本零风险，§5.5.2）。"""
        s = AppSettings()
        assert s.kg_extract_enabled is False
        assert s.kg_extract_interval_hours == 24
        assert s.kg_extract_method == "rule"

    def test_app_settings_custom_values(self):
        """三键显式构造 + JSON roundtrip。"""
        s = AppSettings(
            kg_extract_enabled=True,
            kg_extract_interval_hours=6,
            kg_extract_method="both",
        )
        assert s.kg_extract_enabled is True
        assert s.kg_extract_interval_hours == 6
        assert s.kg_extract_method == "both"
        assert AppSettings.model_validate(s.model_dump()) == s

    def test_guard_existing_defaults_unchanged(self):
        """守护: 既有字段默认值不变（theme/rag_chunk_size/default_words 抽查）——
        当前应 PASS。"""
        s = AppSettings()
        assert s.theme == "paper"
        assert s.rag_chunk_size == 500
        assert s.default_words == 800000

    def test_update_accepts_valid_values(self):
        """AppSettingsUpdate 三键合法值可构造（RED 期字段缺失 + extra='forbid' →
        ValidationError——本用例是假绿防护核心，GREEN 后必须放行）。"""
        u1 = AppSettingsUpdate(kg_extract_enabled=True)
        assert u1.kg_extract_enabled is True
        u2 = AppSettingsUpdate(kg_extract_interval_hours=168)
        assert u2.kg_extract_interval_hours == 168
        u3 = AppSettingsUpdate(kg_extract_method="ai")
        assert u3.kg_extract_method == "ai"

    @pytest.mark.parametrize("interval", [0, 169, -1, 1000])
    def test_update_rejects_interval_out_of_range(self, interval):
        """kg_extract_interval_hours 越界（1 ≤ v ≤ 168，§5.5.2 约束表）→ ValidationError。"""
        with pytest.raises(ValidationError):
            AppSettingsUpdate(kg_extract_interval_hours=interval)

    @pytest.mark.parametrize("method", ["llm", "ai_only", "rule+ai", ""])
    def test_update_rejects_invalid_method(self, method):
        """kg_extract_method 非法值（Literal rule/ai/both 外）→ ValidationError（422）。"""
        with pytest.raises(ValidationError):
            AppSettingsUpdate(kg_extract_method=method)
