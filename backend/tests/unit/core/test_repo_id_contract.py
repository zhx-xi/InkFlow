"""#1134 批 3-B1: `require_uuid_pk` 收窄契约入口测试（ADR-060 D9）。

本批只落**工具契约**（`_id_guard.require_uuid_pk`），不含调用点切换与
ports 收窄 —— 那些随实现层在后续批次推进（见 issue #1134 的拆批说明）。

契约：
  - 入参必须是 `uuid.UUID` 或合法 uuid 字符串；**不接受裸 int**
  - 越界真 uuid → 返 None（404 语义，保持 #1106 行为）
  - None 透传
  - 老入口 `uuid_to_pk_or_none` 行为不变（兼容期）

RED 预期：`_id_guard.require_uuid_pk` 尚不存在 → ImportError。
"""

from __future__ import annotations

import uuid

import pytest

from inkflow.infrastructure.database.repositories._id_guard import (
    require_uuid_pk,
    uuid_to_pk_or_none,
)


class TestRequireUuidPk:
    """新入口：入参必须是 uuid.UUID（收窄契约）。"""

    def test_accepts_uuid(self) -> None:
        assert require_uuid_pk(uuid.UUID(int=7)) == 7

    def test_rejects_bare_int(self) -> None:
        """裸 int 不再接受 —— 强制调用方用 UUID 形态。"""
        with pytest.raises(TypeError):
            require_uuid_pk(7)  # type: ignore[arg-type]  # 故意违例：验证裸 int 被拒

    def test_rejects_str(self) -> None:
        with pytest.raises(TypeError):
            require_uuid_pk("7")  # type: ignore[arg-type]  # 故意违例：非 uuid 字符串

    def test_accepts_string_uuid(self) -> None:
        """str 形态的合法 uuid → 归一（API 边界常见）。"""
        assert require_uuid_pk(str(uuid.UUID(int=9))) == 9

    def test_rejects_malformed_str(self) -> None:
        with pytest.raises(TypeError):
            require_uuid_pk("not-a-uuid")  # type: ignore[arg-type]  # 故意违例：畸形字符串

    def test_out_of_int64_returns_none(self) -> None:
        """越界（真 uuid）→ None（404 语义，保持 #1106 行为）。"""
        assert require_uuid_pk(uuid.uuid4()) is None

    def test_none_passthrough(self) -> None:
        assert require_uuid_pk(None) is None


class TestExistingBehaviourPreserved:
    """老入口 uuid_to_pk_or_none 行为不变（兼容期）。"""

    def test_still_accepts_int(self) -> None:
        assert uuid_to_pk_or_none(5) == 5

    def test_still_accepts_uuid(self) -> None:
        assert uuid_to_pk_or_none(uuid.UUID(int=5)) == 5

    def test_overflow_still_none(self) -> None:
        assert uuid_to_pk_or_none(uuid.uuid4()) is None

    def test_equivalence_int_vs_uuid(self) -> None:
        """新老入口对同一逻辑 id 结果一致（迁移等价性）。"""
        for n in (1, 42, 999999):
            assert require_uuid_pk(uuid.UUID(int=n)) == uuid_to_pk_or_none(n)
