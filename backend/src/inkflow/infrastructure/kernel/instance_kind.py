"""实例类型（kind）判定 — 纯函数 resolve_instance_kind（spec §2.4.1 / ADR-059 ①）。"""

from __future__ import annotations

import os
import sys

from packaging.version import InvalidVersion, Version

INSTANCE_KIND_ENV = "INKFLOW_INSTANCE_KIND"
VALID_KINDS = ("dev", "rc", "release")


def version_is_prerelease(version: str) -> bool:
    """版本号是否含预发布段（packaging Version.is_prerelease）；解析失败 → False。"""
    try:
        return bool(Version(version).is_prerelease)
    except InvalidVersion:
        return False


def resolve_instance_kind() -> str:
    """判定当前实例类型（spec §2.4.1 优先级；无副作用纯判定）。

    1. env ``INKFLOW_INSTANCE_KIND``（strip + lower，合法值）→ 该值
    2. ``sys.frozen`` 真值 → release（打包版内核 exe）
    3. ``inkflow.__version__`` 为预发布 → rc
    4. 其他 → dev

    非法/空白 env 值 → 回落推断（宽松语义，不抛错）。**禁止按 cwd / 路径
    形状猜测**（ADR-059 ①）：worktree、主仓、任意 cwd 都可能跑同一份 dev 代码。
    ``sys`` / ``version_is_prerelease`` 均以模块属性访问（测试 patch 点），
    版本以 ``inkflow.__version__`` 属性访问（禁止 import 时固化快照）。
    """
    raw = os.environ.get(INSTANCE_KIND_ENV, "").strip().lower()
    if raw in VALID_KINDS:
        return raw
    if getattr(sys, "frozen", False):
        return "release"
    import inkflow

    if version_is_prerelease(inkflow.__version__):
        return "rc"
    return "dev"
