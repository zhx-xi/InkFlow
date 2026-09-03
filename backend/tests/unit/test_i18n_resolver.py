"""F57 i18n 解析器 — RED 契约测试（任务 #888-S1 / spec §2.1 / §3）。

契约来源
--------
specs/f57-logging-i18n/spec.md §2.1（i18n 目录 + 双层 fallback 链）、
§5（resolve_locale per-call 准实时）、§12 M3（resolver + t + zh/en 键对称）。

目标模块：`backend/src/inkflow/i18n/resolver.py`（resolve_locale + t）+ `messages/{zh,en}.json`。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. resolve_locale(lang: str | None = None) -> str
   - 优先级：lang（项目 language）> config.lang（用户/全局）> OS locale > "zh"。
   - 归一化到支持的 locale 集合 {"zh", "en"}："zh-CN"/"zh_CN"/"zh-Hans"/"zh" → "zh"；
     "en-US"/"en_GB"/"en" → "en"。不支持的 locale（"fr"/"ja" 等）→ 返回 None（走 fallback 链）。
   - config.lang 从 `inkflow.core.config` 读取（默认 "zh"，非空值恒优于 OS locale）；
     OS locale 经模块级 `_os_locale() -> str | None` 读取（测试可 monkeypatch）。
   - per-call 解析（勿缓存 boot 单例）。

2. t(domain: str, msgid: str, params: dict | None = None, locale: str | None = None) -> str
   - 有效 locale = resolve_locale(locale)（locale 传入则归一化后直接使用）。
   - 从 `inkflow/i18n/<domain>/<locale>.json` 读 msgid 模板；params 插值 `{key}` → str(value)。
   - 缺键回退链：locale 文件缺键 → 尝试 zh → 仍缺 → logger.warning 记录后
     返回 msgid 本身（防静默）。
   - 插值：params 中存在的键替换模板占位符；缺失的占位符保留 `{key}` 原样（不崩溃）。

3. messages/{zh,en}.json：zh/en 键集合必须对称；含初始 ``log.event.*`` / ``api.error.*`` 键。

RED 阶段预期：`inkflow.i18n` 包未创建 → import 即失败（整文件收集失败，门禁 M1）。
GREEN 阶段：实现 resolver.py + messages/{zh,en}.json + config.py 增加 `lang` 字段后全绿。
════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import importlib
import json
from contextlib import contextmanager
from pathlib import Path

from loguru import logger

from inkflow.i18n.resolver import resolve_locale, t

# 测试文件 backend/tests/unit/test_i18n_resolver.py → parents[2] = backend 根目录
_MESSAGES_DIR = Path(__file__).resolve().parents[2] / "src" / "inkflow" / "i18n" / "messages"


def _config_mod():
    """真模块对象（import inkflow.core.config 绑定的是实例，须 importlib 取模块）。"""
    return importlib.import_module("inkflow.core.config")


@contextmanager
def _capture_loguru(level: str = "WARNING"):
    """捕获 loguru 指定级别以上的记录（Message 对象列表），按 sink id 精确移除。"""
    records: list = []
    sink_id = logger.add(lambda m: records.append(m), level=level, format="{message}")
    try:
        yield records
    finally:
        logger.remove(sink_id)


# ── resolve_locale：归一化 ──


class TestResolveLocaleNormalize:
    def test_zh_variants_normalize_to_zh(self):
        assert resolve_locale("zh-CN") == "zh"
        assert resolve_locale("zh_CN") == "zh"
        assert resolve_locale("zh-Hans") == "zh"
        assert resolve_locale("zh") == "zh"

    def test_en_variants_normalize_to_en(self):
        assert resolve_locale("en-US") == "en"
        assert resolve_locale("en_GB") == "en"
        assert resolve_locale("en") == "en"


# ── resolve_locale：优先级（lang > config.lang > OS > zh）──


class TestResolveLocalePriority:
    def test_explicit_lang_wins_over_config(self, monkeypatch):
        cfg = _config_mod()
        monkeypatch.setattr(cfg.config, "lang", "zh", raising=False)
        assert resolve_locale("en-US") == "en"

    def test_falls_back_to_config_lang(self, monkeypatch):
        cfg = _config_mod()
        monkeypatch.setattr(cfg.config, "lang", "en", raising=False)
        assert resolve_locale(None) == "en"

    def test_falls_back_to_os_locale(self, monkeypatch):
        cfg = _config_mod()
        monkeypatch.setattr(cfg.config, "lang", "", raising=False)
        import inkflow.i18n.resolver as resolver_mod

        monkeypatch.setattr(resolver_mod, "_os_locale", lambda: "en_US")
        assert resolve_locale(None) == "en"

    def test_defaults_to_zh_when_all_empty(self, monkeypatch):
        cfg = _config_mod()
        monkeypatch.setattr(cfg.config, "lang", "", raising=False)
        import inkflow.i18n.resolver as resolver_mod

        monkeypatch.setattr(resolver_mod, "_os_locale", lambda: None)
        assert resolve_locale(None) == "zh"

    def test_unsupported_locale_falls_back_to_zh(self, monkeypatch):
        cfg = _config_mod()
        monkeypatch.setattr(cfg.config, "lang", "", raising=False)
        import inkflow.i18n.resolver as resolver_mod

        monkeypatch.setattr(resolver_mod, "_os_locale", lambda: None)
        assert resolve_locale("fr") == "zh"


# ── t()：插值 ──


class TestTInterpolation:
    def test_zh_interpolation(self):
        assert (
            t("messages", "log.event.create_chapter", {"title": "第一章"}, locale="zh")
            == "创建章节：第一章"
        )

    def test_en_interpolation(self):
        assert (
            t("messages", "log.event.create_chapter", {"title": "第一章"}, locale="en")
            == "Created chapter: 第一章"
        )

    def test_default_locale_is_zh(self, monkeypatch):
        cfg = _config_mod()
        monkeypatch.setattr(cfg.config, "lang", "zh", raising=False)
        assert t("messages", "log.event.create_chapter", {"title": "第一章"}) == "创建章节：第一章"

    def test_unsupported_locale_falls_back_to_zh(self, monkeypatch):
        cfg = _config_mod()
        monkeypatch.setattr(cfg.config, "lang", "", raising=False)
        import inkflow.i18n.resolver as resolver_mod

        monkeypatch.setattr(resolver_mod, "_os_locale", lambda: None)
        result = t("messages", "log.event.create_chapter", {"title": "第一章"}, locale="fr")
        assert result == "创建章节：第一章"

    def test_missing_param_placeholder_preserved(self):
        # 模板含 {title} 但 params 缺 key → 占位符保留，不崩溃
        assert t("messages", "log.event.create_chapter", {}, locale="zh") == "创建章节：{title}"

    def test_api_error_key_interpolation(self):
        assert (
            t("messages", "api.error.project_not_found", {"project_id": "abc-123"}, locale="zh")
            == "项目不存在：abc-123"
        )


# ── t()：缺键回退（WARN + msgid）──


class TestTMissingKey:
    def test_missing_key_returns_msgid(self):
        assert t("messages", "log.event.nonexistent", locale="zh") == "log.event.nonexistent"

    def test_missing_key_warns(self):
        with _capture_loguru("WARNING") as records:
            result = t("messages", "log.event.nonexistent", locale="zh")
        assert result == "log.event.nonexistent"
        assert any("log.event.nonexistent" in str(m) for m in records)


# ── messages/{zh,en}.json：键对称 + 初始键 ──


class TestMessagesSymmetry:
    def _load(self, locale: str) -> dict:
        path = _MESSAGES_DIR / f"{locale}.json"
        assert path.exists(), f"缺少消息目录文件：{path}"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_zh_en_key_symmetry(self):
        zh = self._load("zh")
        en = self._load("en")
        assert set(zh.keys()) == set(en.keys())

    def test_contains_required_initial_keys(self):
        zh = self._load("zh")
        en = self._load("en")
        required = [
            "log.event.create_chapter",
            "log.event.update_project",
            "log.event.delete_project",
            "api.error.project_not_found",
            "api.error.validation_failed",
        ]
        for key in required:
            assert key in zh, f"zh.json 缺少初始键 {key}"
            assert key in en, f"en.json 缺少初始键 {key}"
