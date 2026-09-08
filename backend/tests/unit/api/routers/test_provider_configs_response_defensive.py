"""F59-M4 (#965) `_to_response` 防御分支契约（B8）。

契约：models[] 中出现**非 dict 条目**（损坏 JSON / 历史脏数据）时，
`_to_response` 跳过该条目不探测、不抛错，其余条目照常回显（分支 133-134）。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from inkflow.api.routers.provider_configs import _to_response
from inkflow.domain.models.provider_config import ProviderConfig


def _pc(models: list) -> ProviderConfig:
    """构造 ProviderConfig（绕过校验，模拟 JSON 列里混入非 dict 条目）。"""
    return ProviderConfig.model_construct(
        id=1,
        name="dirty-provider",
        base_url="https://x.example/v1",
        default_model="dirty-provider/m1",
        models=models,
    )


def test_non_dict_models_entry_is_skipped_without_probe() -> None:
    """非 dict 条目 → 原样保留且不触发探测（防打崩列表端点）。"""
    key_manager = MagicMock()
    key_manager.list_providers.return_value = []
    with patch(
        "inkflow.infrastructure.llm.capability_probe.supports_reasoning_for_model"
    ) as m_probe:
        m_probe.return_value = True
        data = _to_response(
            _pc([{"id": "m1", "type": "chat", "roles": []}, "bogus-entry"]),
            key_manager,
        )

    assert data["models"][1] == "bogus-entry", "非 dict 条目必须原样保留"
    assert m_probe.call_count == 1, "只对 dict 条目探测（脏数据条目跳过）"
    assert data["models"][0]["supports_reasoning"] is True
    assert "supports_reasoning_manual" not in data["models"][0]
