"""F30 1.2 实例类型判定契约（#1153 / ADR-059 ①，spec §2.4.1）。

被测：``inkflow.infrastructure.kernel.instance_kind.resolve_instance_kind()``

判定优先级（spec §2.4.1）：
  1. env ``INKFLOW_INSTANCE_KIND`` ∈ {dev, rc, release} → 该值
  2. ``sys.frozen == True`` → release
  3. ``inkflow.__version__`` 为预发布（packaging Version.is_prerelease）→ rc
  4. 其他 → dev

关键约束（ADR-059 ① 明示）：**禁止按 cwd / 路径形状猜测**——worktree、主仓、
任意 cwd 都可能跑同一份 dev 代码。因此本文件断言「除 env/frozen/version 外
无其他输入影响判定」。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from inkflow.infrastructure.kernel.instance_kind import (
    INSTANCE_KIND_ENV,
    VALID_KINDS,
    resolve_instance_kind,
)


def test_valid_kinds_are_the_three_documented_values():
    """合法 kind 集合 = {dev, rc, release}（spec §2.4.1 表）。"""
    assert set(VALID_KINDS) == {"dev", "rc", "release"}


def test_env_var_name_is_documented_contract_value():
    """env 键名是契约常量（spec §2.4.1 字面量 INKFLOW_INSTANCE_KIND）。"""
    assert INSTANCE_KIND_ENV == "INKFLOW_INSTANCE_KIND"


@pytest.mark.parametrize("kind", ["dev", "rc", "release"])
def test_explicit_env_wins(kind, monkeypatch):
    """优先级 1：env 显式合法值 → 直接采用（覆盖任何推断来源）。"""
    monkeypatch.setenv(INSTANCE_KIND_ENV, kind)
    assert resolve_instance_kind() == kind


@pytest.mark.parametrize("kind", ["dev", "rc", "release"])
def test_explicit_env_wins_even_when_frozen(kind, monkeypatch):
    """优先级 1 高于 frozen 推断（显式 > 推断）。"""
    monkeypatch.setenv(INSTANCE_KIND_ENV, kind)
    with patch("inkflow.infrastructure.kernel.instance_kind.sys") as fake_sys:
        fake_sys.frozen = True
        assert resolve_instance_kind() == kind


def test_env_value_is_trimmed_and_lowercased(monkeypatch):
    """env 值宽松归一：strip + lowercase（防 ' RC ' / 'Release' 误判为非法）。"""
    monkeypatch.setenv(INSTANCE_KIND_ENV, "  RC  ")
    assert resolve_instance_kind() == "rc"


def test_frozen_without_env_is_release(monkeypatch):
    """优先级 2：sys.frozen=True → release（打包版内核 exe）。"""
    monkeypatch.delenv(INSTANCE_KIND_ENV, raising=False)
    with patch("inkflow.infrastructure.kernel.instance_kind.sys") as fake_sys:
        fake_sys.frozen = True
        assert resolve_instance_kind() == "release"


def test_prerelease_version_is_rc(monkeypatch):
    """优先级 3：版本为预发布（如 1.2.0rc3）→ rc。"""
    monkeypatch.delenv(INSTANCE_KIND_ENV, raising=False)
    with (
        patch("inkflow.infrastructure.kernel.instance_kind.sys") as fake_sys,
        patch(
            "inkflow.infrastructure.kernel.instance_kind.version_is_prerelease",
            return_value=True,
        ),
    ):
        fake_sys.frozen = False
        assert resolve_instance_kind() == "rc"


def test_stable_version_is_dev(monkeypatch):
    """优先级 4：非 frozen + 非预发布 → dev（源码/venv 默认形态）。"""
    monkeypatch.delenv(INSTANCE_KIND_ENV, raising=False)
    with (
        patch("inkflow.infrastructure.kernel.instance_kind.sys") as fake_sys,
        patch(
            "inkflow.infrastructure.kernel.instance_kind.version_is_prerelease",
            return_value=False,
        ),
    ):
        fake_sys.frozen = False
        assert resolve_instance_kind() == "dev"


@pytest.mark.parametrize("bad", ["prod", "production", "DEV?", "", "  "])
def test_invalid_or_blank_env_falls_back_to_inference(bad, monkeypatch):
    """非法/空 env 值 → 回落推断（宽松语义，不抛错；spec §2.4.1）。"""
    monkeypatch.setenv(INSTANCE_KIND_ENV, bad)
    with (
        patch("inkflow.infrastructure.kernel.instance_kind.sys") as fake_sys,
        patch(
            "inkflow.infrastructure.kernel.instance_kind.version_is_prerelease",
            return_value=False,
        ),
    ):
        fake_sys.frozen = False
        assert resolve_instance_kind() == "dev"


def test_cwd_does_not_influence_judgement(monkeypatch, tmp_path):
    """🔴 ADR-059 ① 硬约束：cwd 不是判定输入。

    以 worktree 形状的路径为 cwd，判定结果必须与任意其他 cwd 一致——
    防止后续实现「看到 -ft/ 或 worktree 就判 dev」这类猜测逻辑回潮。
    """
    monkeypatch.delenv(INSTANCE_KIND_ENV, raising=False)
    worktree_like = tmp_path / "InkFlow-ft" / "feat-kernel-concurrency"
    worktree_like.mkdir(parents=True)
    monkeypatch.chdir(worktree_like)

    with (
        patch("inkflow.infrastructure.kernel.instance_kind.sys") as fake_sys,
        patch(
            "inkflow.infrastructure.kernel.instance_kind.version_is_prerelease",
            return_value=False,
        ),
    ):
        fake_sys.frozen = False
        assert resolve_instance_kind() == "dev"
