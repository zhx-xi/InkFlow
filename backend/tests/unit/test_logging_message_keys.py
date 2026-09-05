"""F57-S2 message_key ↔ i18n 目录对称性契约（spec §5 抽取/校验 + §4.1）。

契约来源
--------
specs/f57-logging-i18n/spec.md §5：「扩展到后端各域键对称性 + 用户 override 键必须
存在于打包默认（防孤儿键）」；§4.1 显式 checkpoint 的 message_key 是语言中立 msgid，
日志页经 t(message_key, params) 渲染 → **每个语义键（log.event.*/log.check.*）必须在
打包默认目录（i18n/messages/{zh,en}.json）有对应词条**，否则前端渲染回退+WARN。

设计假设（GREEN 必须满足）
--------------------------
1. AST 扫描 backend/src/inkflow/ 全部 .py，收集字面量参数中出现的
   message_key="log.event.*" / "log.check.*"（log.call.* 由装饰器动态拼接，不在范围）。
2. 每个收集到的键必须同时存在于 zh.json 与 en.json。
3. zh 与 en 目录键集合完全对称（无单边键）。
4. 模板里的 {param} 占位符，成对词条（zh/en）占位符集合一致。
   （params 实际是否包含该键属行为契约，本测试不强制。）

RED 预期：checkpoint 铺开但目录未登记键 → 孤儿键列表非空 → 失败。
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "inkflow"
MESSAGES_DIR = SRC / "i18n" / "messages"

_PLACEHOLDER = re.compile(r"\{(\w+)[^}]*\}")


def _collect_semantic_keys() -> dict[str, set[str]]:
    """AST 扫 src，返回 {message_key: {出现该键的文件相对路径}}（log.event./log.check.）。"""
    found: dict[str, set[str]] = {}
    for py in SRC.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 源码保证可解析
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg != "message_key":
                    continue
                value = kw.value
                if (
                    isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                    and (
                        value.value.startswith("log.event.")
                        or value.value.startswith("log.check.")
                    )
                ):
                    found.setdefault(value.value, set()).add(str(py.relative_to(SRC)))
    return found


def _load_catalog(lang: str) -> dict[str, str]:
    return json.loads((MESSAGES_DIR / f"{lang}.json").read_text(encoding="utf-8"))


class TestMessageKeyCatalog:
    def test_all_semantic_keys_registered(self) -> None:
        keys = _collect_semantic_keys()
        assert keys, "src 中应存在显式语义 checkpoint（log.event.*/log.check.*）"
        zh, en = _load_catalog("zh"), _load_catalog("en")
        orphans = {k: v for k, v in keys.items() if k not in zh or k not in en}
        assert not orphans, "孤儿 message_key（未登记 zh/en 目录）：" + json.dumps(
            {k: sorted(v)[:3] for k, v in sorted(orphans.items())}, ensure_ascii=False, indent=1
        )

    def test_zh_en_key_symmetry(self) -> None:
        zh, en = _load_catalog("zh"), _load_catalog("en")
        only_zh = sorted(set(zh) - set(en))
        only_en = sorted(set(en) - set(zh))
        assert not only_zh, f"仅 zh 有的键：{only_zh}"
        assert not only_en, f"仅 en 有的键：{only_en}"

    def test_placeholder_sets_match(self) -> None:
        zh, en = _load_catalog("zh"), _load_catalog("en")
        mismatched = {
            k: (sorted(_PLACEHOLDER.findall(zh[k])), sorted(_PLACEHOLDER.findall(en[k])))
            for k in zh
            if k in en and _PLACEHOLDER.findall(zh[k]) != _PLACEHOLDER.findall(en[k])
        }
        assert not mismatched, f"zh/en 占位符不一致：{mismatched}"

    def test_registered_log_keys_used_in_src(self) -> None:
        """目录中 log.event.*/log.check.* 键必须至少被 src 引用一处（防死词条）。

        #496 契约升级：kernel_* 五键的引用方是 **Electron 主进程**（frontend/packages/
        electron/src/main.ts 经 createMainLogger 上报，#892 交付），不在 backend src 的
        AST 扫描面内——日志页消费这些键（GET /i18n/messages 渲染）。列入跨端豁免，
        防误判死词条；豁免清单外的新键仍受本测试守护。
        """
        keys = set(_collect_semantic_keys())
        # 跨端引用豁免（消费者 = Electron 主进程 main.ts，非 backend src）
        cross_surface = {
            "log.event.kernel_ready",
            "log.event.kernel_failure",
            "log.event.kernel_exit",
            "log.event.kernel_spawn_error",
            "log.event.kernel_crash",
        }
        zh = _load_catalog("zh")
        dead = sorted(
            k
            for k in zh
            if (k.startswith("log.event.") or k.startswith("log.check."))
            and k not in keys
            and k not in cross_surface
        )
        assert not dead, f"目录有但 src 未引用的死键：{dead}"

    def test_log_call_generic_entry_registered(self) -> None:
        """#930：目录含 log.call.generic 通用回退词条（zh/en），前端卡片防裸 key。

        log.call.* 由 @instrument 动态拼接（200+ 端点），逐函数登记不现实；目录提供
        一个通用词条，前端在精确词条缺失时回退它（spec §2.2 字段约定 + issue #930）。
        """
        zh, en = _load_catalog("zh"), _load_catalog("en")
        assert "log.call.generic" in zh, "zh.json 缺 log.call.generic"
        assert "log.call.generic" in en, "en.json 缺 log.call.generic"
        assert "{caller_name}" in zh["log.call.generic"]
        assert "{caller_name}" in en["log.call.generic"]
        assert zh["log.call.generic"] != en["log.call.generic"]
