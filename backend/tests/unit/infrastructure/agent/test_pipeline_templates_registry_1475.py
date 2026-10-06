"""#1475 自定义管线不污染内置模板注册表 —— 负例守护（spec f42 §4.1 / §5.8.4）。

自定义管线是「一次执行携带拓扑」，**不注册**进 `_BUILDERS` / `BUILTIN_TEMPLATES`：
- `agent template pipelines`（→ `GET /agent/pipelines/templates` → `list_templates()`）
  必须恒等于内置 4 条（负例防漂移）；
- `BUILTIN_TEMPLATES` 仍为惰性映射（#936 A 项：每次访问按当前配置重建），
  条目数恒 4；
- 自定义取值（role_key 串 / YAML 路径）**查不到**内置模板（`get_template` → None）。

本文件为**当前 PASS 的守护断言**（非 RED）——实现自定义通道时不得让内置注册表增长。
"""

from __future__ import annotations

import pytest

from inkflow.infrastructure.agent.pipeline_templates import (
    BUILTIN_TEMPLATES,
    get_template,
    list_templates,
)

EXPECTED_TEMPLATE_IDS = [
    "builtin:write_chapter",
    "builtin:write_auto",
    "builtin:write_continue",
    "builtin:chat",
]
EXPECTED_STAGES = {
    "builtin:write_chapter": ["architect", "writer", "auditor", "reviser"],
    "builtin:write_auto": ["architect", "writer", "auditor", "reviser"],
    "builtin:write_continue": ["writer", "auditor", "reviser"],
    "builtin:chat": ["chat"],
}


def test_list_templates_is_exactly_the_four_builtins() -> None:
    items = list_templates()

    assert [item["id"] for item in items] == EXPECTED_TEMPLATE_IDS
    for item in items:
        assert item["stages"] == EXPECTED_STAGES[item["id"]]
        assert item["source"] == "builtin"


def test_builtin_templates_mapping_has_four_entries() -> None:
    assert len(BUILTIN_TEMPLATES) == 4
    assert list(BUILTIN_TEMPLATES) == EXPECTED_TEMPLATE_IDS


@pytest.mark.parametrize(
    "custom_value",
    ["worldview,polisher", "polisher", "builtin:worldview", r".\my-chain.yaml", "ghost"],
)
def test_custom_values_are_not_registered_templates(custom_value: str) -> None:
    """自定义取值不得命中内置模板表（未注册 → None，不静默当内置跑）。"""
    assert get_template(custom_value) is None
    assert custom_value not in BUILTIN_TEMPLATES
