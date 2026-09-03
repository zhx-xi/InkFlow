"""InkFlow i18n 解析器 — resolve_locale + t（F57 / spec §2.1、§5）。

职责
----
- ``resolve_locale(lang)``：按优先级（项目 language > config.lang > OS locale > zh）
  解析并归一化当前生效 locale；per-call 准实时解析，不缓存 boot 单例。
- ``t(domain, msgid, params, locale)``：从 ``inkflow/i18n/<domain>/<locale>.json``
  读取消息模板并按 ``{key}`` 插值；缺键沿 locale 文件 → zh 文件 → msgid 本身回退。
"""

from __future__ import annotations

import json
import locale
import os
from pathlib import Path

from loguru import logger

from inkflow.core.config import config

SUPPORTED_LOCALES: tuple[str, ...] = ("zh", "en")


def _normalize_locale(value: str | None) -> str | None:
    """归一化 locale 到主语言子标签（'zh'/'en'），不支持返回 None。

    接受 'zh-CN'/'zh_CN'/'zh-Hans'/'zh' → 'zh'；'en-US'/'en_GB'/'en' → 'en'；
    其它（'fr'/'ja' 等）返回 None，交由调用方走 fallback 链。大小写不敏感。
    """
    if not value:
        return None
    primary = value.lower().split("-")[0].split("_")[0]
    return primary if primary in SUPPORTED_LOCALES else None


def _os_locale() -> str | None:
    """返回 OS locale（如 'zh_CN'/'en_US'），不可得返回 None。"""
    lang_env = os.environ.get("LANG")
    if lang_env:
        return lang_env
    try:
        return locale.getlocale()[0]
    except Exception:
        return None


def resolve_locale(lang: str | None = None) -> str:
    """解析生效 locale。

    优先级：lang（项目 language）> config.lang（用户/全局）> OS locale > 'zh'；
    归一化到 {'zh', 'en'}。per-call 解析（勿缓存 boot 单例），切换准实时生效。
    """
    candidate = lang or getattr(config, "lang", "")
    normalized = _normalize_locale(candidate)
    if normalized is not None:
        return normalized
    normalized = _normalize_locale(_os_locale())
    if normalized is not None:
        return normalized
    return "zh"


def load_messages(domain: str, locale: str) -> dict[str, str]:
    """读取 ``inkflow/i18n/<domain>/<locale>.json``，返回 msgid -> 模板 dict。

    locale 必须是归一化值（'zh'/'en'）；文件缺失返回 {}。
    路径基于本模块 ``__file__.parent``（即 ``inkflow/i18n/``）定位。
    """
    path = Path(__file__).resolve().parent / domain / f"{locale}.json"
    if not path.is_file():
        return {}
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _interpolate(template: str, params: dict | None) -> str:
    """按 params 逐个替换 ``{key}`` 占位符；缺失占位符保留原样（不崩溃）。"""
    if not params:
        return template
    result = template
    for key, value in params.items():
        result = result.replace("{" + str(key) + "}", str(value))
    return result


def t(domain: str, msgid: str, params: dict | None = None, locale: str | None = None) -> str:
    """按 domain 解析 msgid 模板并插值；缺键沿 fallback 链回退。

    缺键回退链：locale 文件缺键 → 尝试 zh 文件 → 仍缺 → logger.warning + 返回 msgid
    本身（防静默）。插值只替换 params 中存在的键，缺失占位符保留 ``{key}`` 原样。
    """
    effective = resolve_locale(locale)
    template = load_messages(domain, effective).get(msgid)
    if template is None and effective != "zh":
        template = load_messages(domain, "zh").get(msgid)
    if template is None:
        logger.warning("missing i18n key: {}:{}", domain, msgid)
        return msgid
    return _interpolate(template, params)
