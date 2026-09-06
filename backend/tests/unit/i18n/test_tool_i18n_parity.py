"""#955 F58 §5 i18n 工具键双向守护 — name ↔ tool.<name> (zh/en) bijection + 退役守护.

契约来源：contract-955 §5（i18n/functions/{zh,en}.json：删 tool.create_outline /
tool.update_outline 两键，加 11 新键，ALL_TOOL_SPECS 全体 name ↔ tool.<name> 双向
bijection）+ §8 RED-C（退役守护：ALL_TOOL_SPECS 名集**不含** create_outline/update_outline
【R】；zh/en 两键已退役不在 key 集【R】）。

标记约定（contract §8 每用例标【R】/【G】）：
- 【R】= RED 期 FAIL（当前 src 仍 35 名 / zh-en 键仍含旧名，GREEN 退役后转 PASS）；
- 【G】= 双向守护（RED 阶段即 PASS，GREEN 后继续守护防未来批漏登记）。

文件路径：backend/tests/unit/i18n/ → parents[3] = backend 根
（镜像 test_i18n_s4_domains.py 的 _I18N_SRC 形态）。
"""
from __future__ import annotations

import json
from pathlib import Path

from inkflow.infrastructure.agent.tools.registry import ALL_TOOL_SPECS

_BACKEND = Path(__file__).resolve().parents[3]
_I18N_SRC = _BACKEND / "src" / "inkflow" / "i18n"

RETIRED_TOOL_NAMES = frozenset({"create_outline", "update_outline"})
"""#955 §4 退役根工具（已下线，改由 outline_tools.py 的 10 个新工具承担）。"""


def _tool_keys(locale: str) -> set[str]:
    """读取 i18n/functions/<locale>.json → 该文件所有以 `tool.` 前缀的键集合。"""
    path = _I18N_SRC / "functions" / f"{locale}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k for k in data if k.startswith("tool.")}


def _spec_names() -> set[str]:
    """ALL_TOOL_SPECS 全体 spec.name 集合。"""
    return {spec.name for spec in ALL_TOOL_SPECS}


class TestToolI18nBijection:
    """【G】ALL_TOOL_SPECS 全体 name ↔ `tool.<name>` 键双向 bijection（zh、en 各自）。

    防未来批次漏登记/多登记：任一 spec 缺键、任一多余键都会破坏集合相等 → 断言失败。
    """

    def test_zh_spec_names_exactly_tool_keys(self) -> None:
        """zh.json 的 `tool.<name>` 键集合 == ALL_TOOL_SPECS name 集（双向相等）。"""
        expected = {f"tool.{name}" for name in _spec_names()}
        assert expected == _tool_keys("zh")

    def test_en_spec_names_exactly_tool_keys(self) -> None:
        """en.json 的 `tool.<name>` 键集合 == ALL_TOOL_SPECS name 集（双向相等）。"""
        expected = {f"tool.{name}" for name in _spec_names()}
        assert expected == _tool_keys("en")


class TestRetiredOutlineToolKeys:
    """【R】create_outline/update_outline 退役守护：不在 ALL_TOOL_SPECS 名集、不在 zh/en key 集。

    RED 期（src 仍 35 名 / zh-en 键含旧名）：`test_all_specs_names_exclude_retired` FAIL
    （current ALL_TOOL_SPECS 仍含 create_outline）、`test_*_keys_exclude_retired` FAIL
    （current zh/en.json 仍含 tool.create_outline/update_outline）。
    """

    def test_all_specs_names_exclude_retired(self) -> None:
        """ALL_TOOL_SPECS 名集不得再含 create_outline / update_outline（#955 §4）。"""
        names = _spec_names()
        for n in RETIRED_TOOL_NAMES:
            assert n not in names, f"{n} 应从 ALL_TOOL_SPECS 退役（#955 §4）"

    def test_zh_keys_exclude_retired(self) -> None:
        """zh.json 不得再含 tool.create_outline / tool.update_outline（#955 §5）。"""
        keys = _tool_keys("zh")
        for n in RETIRED_TOOL_NAMES:
            assert f"tool.{n}" not in keys, f"zh.json 应删除 tool.{n}（#955 §5）"

    def test_en_keys_exclude_retired(self) -> None:
        """en.json 不得再含 tool.create_outline / tool.update_outline（#955 §5）。"""
        keys = _tool_keys("en")
        for n in RETIRED_TOOL_NAMES:
            assert f"tool.{n}" not in keys, f"en.json 应删除 tool.{n}（#955 §5）"
