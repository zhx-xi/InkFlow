"""#1134 / ADR-060 批 1: new_uuid() 统一身份键 RED 契约测试。

契约（ADR-060 D2/D3/D4）:
  - 返回标准 uuid.UUID（可被 SQLAlchemy/Pydantic 直接消化）
  - version == 7（RFC 9562 时间有序）
  - 时间有序：连续生成的字典序单调递增（v7 前缀=ms 时间戳）
  - 跨实例不重复：注入不同 machine_id 的两个生成器，产物不相交
  - 同毫秒并发不重复：单毫秒内大量生成无碰撞
  - machine_id 派生：<data_dir>/.instance_id 持久化；缺失则生成落盘；已存在绝不重写
  - machine_id 回退：目录不可写时回退 hostname 哈希，不抛异常
  - 64 位表示（用于旧 int PK 内部派生）仍在 int64 范围内
"""

from __future__ import annotations

import itertools
import uuid
from pathlib import Path

import pytest

from inkflow.core.uuid_gen import (
    MACHINE_ID_FILENAME,
    load_or_create_machine_id,
    new_uuid,
    uuid_from_local_id,
)


class TestNewUuidShape:
    """产物形态与版本。"""

    def test_returns_std_uuid(self) -> None:
        got = new_uuid()
        assert isinstance(got, uuid.UUID)

    def test_version_is_7(self) -> None:
        assert new_uuid().version == 7

    def test_variant_is_rfc4122(self) -> None:
        assert new_uuid().variant == uuid.RFC_4122

    def test_str_is_canonical_36(self) -> None:
        assert len(str(new_uuid())) == 36


class TestTimeOrdering:
    """时间有序：v7 前缀 = 48 位毫秒时间戳。

    ⚠️ 契约边界：UUIDv7 只保证 **毫秒级**时间有序；同毫秒内由随机段消歧，
    **不保证**单调递增。跨毫秒的批量生成才体现单调性。
    """

    def test_monotonic_across_milliseconds(self) -> None:
        """跨毫秒生成 → 字典序单调递增。"""
        import time

        seq = []
        for _ in range(5):
            seq.append(new_uuid())
            time.sleep(0.002)  # 保证跨毫秒
        assert all(str(a) < str(b) for a, b in itertools.pairwise(seq))

    def test_later_millisecond_sorts_greater(self) -> None:
        import time

        earlier = new_uuid()
        time.sleep(0.005)
        assert new_uuid() > earlier

    def test_within_same_millisecond_no_ordering_guarantee_but_distinct(self) -> None:
        """同毫秒内：不保证有序，但必须互不相同。"""
        batch = [new_uuid() for _ in range(2000)]
        assert len(set(batch)) == 2000
        # 时间戳前缀（前 12 hex 字符）应高度一致 —— 证明都在同一毫秒附近
        prefixes = {str(u)[:11] for u in batch}
        assert len(prefixes) <= 3  # 允许跨越 1-2 毫秒边界


class TestCrossInstanceUniqueness:
    """跨实例不重复：machine_id 参与随机段。"""

    def test_different_machine_ids_yield_disjoint_sets(self, tmp_path: Path) -> None:
        a = {new_uuid(machine_id="a" * 32) for _ in range(200)}
        b = {new_uuid(machine_id="b" * 32) for _ in range(200)}
        assert not (a & b)

    def test_same_machine_id_same_timestamp_still_distinct(self) -> None:
        mid = "c" * 32
        batch = {new_uuid(machine_id=mid) for _ in range(1000)}
        assert len(batch) == 1000

    def test_all_payloads_are_unique(self) -> None:
        batch = [new_uuid() for _ in range(5000)]
        assert len(set(batch)) == 5000


class TestMachineIdPersistence:
    """machine_id: <data_dir>/.instance_id 持久化（照抄 load_or_create_secret_key 范式）。"""

    def test_creates_file_when_absent(self, tmp_path: Path) -> None:
        mid = load_or_create_machine_id(tmp_path)
        assert (tmp_path / MACHINE_ID_FILENAME).exists()
        assert len(mid) == 32

    def test_stable_across_calls(self, tmp_path: Path) -> None:
        assert load_or_create_machine_id(tmp_path) == load_or_create_machine_id(tmp_path)

    def test_existing_value_never_overwritten(self, tmp_path: Path) -> None:
        f = tmp_path / MACHINE_ID_FILENAME
        f.write_text("f" * 32, encoding="utf-8")
        assert load_or_create_machine_id(tmp_path) == "f" * 32

    def test_whitespace_and_newline_tolerated(self, tmp_path: Path) -> None:
        f = tmp_path / MACHINE_ID_FILENAME
        f.write_text("  abcd1234  \n", encoding="utf-8")
        assert load_or_create_machine_id(tmp_path) == "abcd1234"

    def test_falls_back_when_dir_not_writable(self, tmp_path: Path) -> None:
        """目录不可写 → 回退 hostname 哈希，不抛异常。"""
        missing_parent = tmp_path / "nope" / "deeper"
        mid = load_or_create_machine_id(missing_parent)
        assert len(mid) == 32

    def test_fallback_is_stable(self, tmp_path: Path) -> None:
        bad = tmp_path / "x" / "y"
        assert load_or_create_machine_id(bad) == load_or_create_machine_id(bad)

    def test_none_uses_config_data_dir(self, monkeypatch, tmp_path: Path) -> None:
        """data_dir=None → 走 InkFlowConfig().data_dir（延迟导入分支）。"""
        monkeypatch.setenv("INKFLOW_DATA_DIR", str(tmp_path / "cfg-data"))
        mid = load_or_create_machine_id(None)
        assert len(mid) == 32
        assert (tmp_path / "cfg-data" / MACHINE_ID_FILENAME).exists()


class TestLocalIntDerivation:
    """uuid_from_local_id: 旧 int PK → 可逆 UUID（int64 内），供批 3 前过渡期使用。"""

    def test_roundtrip(self) -> None:
        assert uuid_from_local_id(42).int == 42

    def test_int64_boundary_ok(self) -> None:
        assert uuid_from_local_id(2**63 - 1).int == 2**63 - 1

    def test_overflow_rejected(self) -> None:
        with pytest.raises(ValueError):
            uuid_from_local_id(2**63)

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError):
            uuid_from_local_id(-1)
