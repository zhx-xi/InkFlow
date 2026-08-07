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
    """6 字段默认字典（§2.1 表 + §2.2 AppSettings 默认值）。"""
    return {
        "theme": "paper",
        "bg": "default",
        "lang": "zh",
        "font": "sans",
        "close_behavior": "tray",
        "tray_hint_dismissed": False,
    }


class TestAppSettings:
    """AppSettings 默认值 + 合法字面量 + JSON roundtrip 契约。"""

    def test_defaults_complete(self):
        """空构造 == 6 字段默认字典（§9.4「默认值齐全」）。"""
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
        )
        assert s.model_dump() == {
            "theme": "night",
            "bg": "navy",
            "lang": "en",
            "font": "mono",
            "close_behavior": "quit",
            "tray_hint_dismissed": True,
        }

    def test_json_roundtrip(self):
        """model_validate(model_dump()) 相等（默认对象与显式值对象各一）。"""
        assert AppSettings.model_validate(AppSettings().model_dump()) == AppSettings()
        original = AppSettings(theme="night", font="mono", tray_hint_dismissed=True)
        assert AppSettings.model_validate(original.model_dump()) == original


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
        """6 成员 + value 与 §2.1 设置键名一一对应。"""
        assert {k.name: k.value for k in SettingsKey} == {
            "THEME": "theme",
            "BG": "bg",
            "LANG": "lang",
            "FONT": "font",
            "CLOSE_BEHAVIOR": "close_behavior",
            "TRAY_HINT_DISMISSED": "tray_hint_dismissed",
        }

    def test_construct_by_value(self):
        """按 value 构造（service 白名单 ``SettingsKey(field)`` 的依赖）。"""
        assert SettingsKey("theme") is SettingsKey.THEME
        assert SettingsKey("tray_hint_dismissed") is SettingsKey.TRAY_HINT_DISMISSED
