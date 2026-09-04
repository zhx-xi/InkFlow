"""F49 M1 #617 ProjectConfig.extra 衰减键契约测试（同步，独立文件避免 asyncio mark 误标）.

依据: specs/f49-memory-decay/spec.md §2.1/§3.1（memory_decay_enabled / memory_decay_half_life）.
RED 预期: 越界/非 int/非 bool 在旧实现下不抛 ValueError → DID NOT RAISE FAIL；
合法值/缺键零迁移 PASS。
"""

from __future__ import annotations

import pytest

from inkflow.domain.models.project import ProjectConfig


def test_config_extra_valid_decay_once() -> None:
    """合法的 memory_decay_enabled/memory_decay_half_life 不抛错."""
    cfg = ProjectConfig(extra={"memory_decay_enabled": True, "memory_decay_half_life": 30})
    assert cfg.extra["memory_decay_enabled"] is True
    assert cfg.extra["memory_decay_half_life"] == 30


def test_config_extra_rejects_half_life_zero() -> None:
    """memory_decay_half_life=0 越界 → ValueError."""
    with pytest.raises(ValueError):
        ProjectConfig(extra={"memory_decay_half_life": 0})


def test_config_extra_rejects_half_life_over() -> None:
    """memory_decay_half_life=366 越界 → ValueError."""
    with pytest.raises(ValueError):
        ProjectConfig(extra={"memory_decay_half_life": 366})


def test_config_extra_rejects_half_life_non_int() -> None:
    """memory_decay_half_life 非 int（如 "30"）→ ValueError."""
    with pytest.raises(ValueError):
        ProjectConfig(extra={"memory_decay_half_life": "30"})


def test_config_extra_rejects_enabled_non_bool() -> None:
    """memory_decay_enabled 非 bool（如 "yes"）→ ValueError."""
    with pytest.raises(ValueError):
        ProjectConfig(extra={"memory_decay_enabled": "yes"})


def test_config_extra_missing_keys_zero_migration() -> None:
    """extra 无 decay 键 → 零迁移（默认行为，不校验不抛错）."""
    cfg = ProjectConfig(extra={})
    assert cfg.extra.get("memory_decay_enabled") is None
