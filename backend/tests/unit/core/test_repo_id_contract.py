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

import inspect
import pathlib
import re
import typing
import uuid

import pytest

from inkflow.domain.ports import character_repository as _character_port
from inkflow.domain.ports import map_repository as _map_port
from inkflow.domain.ports import outline_repository as _outline_port
from inkflow.domain.ports import project_repository as _project_port
from inkflow.domain.ports import world_repository as _world_port
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


# ---------------------------------------------------------------------------
# #1271 批 3-B 实现层：ports 收窄 + 调用点去冗余解包 + 入口接入
# 设计依据 .hermes/plans/w13e-design.md
# ---------------------------------------------------------------------------


def _get_param_annotation(protocol_cls: type, method: str = "get") -> object:
    """取 Protocol.get 第一个位置参数的注解（字符串注解需解析）。"""
    fn = getattr(protocol_cls, method)
    sig = inspect.signature(fn)
    params = [p for p in sig.parameters.values() if p.name != "self"]
    assert params, f"{protocol_cls.__name__}.{method} 无位置参数"
    raw = params[0].annotation
    if raw is inspect.Parameter.empty:
        return None
    if isinstance(raw, str):
        return eval(raw, {"uuid": uuid, "UUID": uuid.UUID})
    return raw


_NARROWED_PORTS = {
    "project": (_project_port.ProjectRepositoryProtocol, "project_id"),
    "character": (_character_port.CharacterRepositoryProtocol, "character_id"),
    "world": (_world_port.WorldRepositoryProtocol, "setting_id"),
    "map": (_map_port.MapRepositoryProtocol, "map_id"),
    "outline": (_outline_port.OutlineRepositoryProtocol, "outline_id"),
}


class TestPortsNarrowedToUuid:
    """断言 1：ports 签名已收窄到 uuid.UUID（不再是 int）。"""

    @pytest.mark.parametrize("domain", sorted(_NARROWED_PORTS))
    def test_get_accepts_uuid_annotation(self, domain: str) -> None:
        proto, _param = _NARROWED_PORTS[domain]
        ann = _get_param_annotation(proto)
        assert ann is uuid.UUID, (
            f"{proto.__name__}.get 首参注解应为 uuid.UUID，实测 {ann!r}"
            "（若为 int → 本批收窄未落地）"
        )

    @pytest.mark.parametrize("domain", sorted(_NARROWED_PORTS))
    def test_get_no_longer_accepts_bare_int(self, domain: str) -> None:
        """反向断言：注解不得再是 int（可证伪 —— 改回 int 则本用例 FAIL）。"""
        proto, _param = _NARROWED_PORTS[domain]
        assert _get_param_annotation(proto) is not int, (
            f"{proto.__name__}.get 仍是 int —— 收窄未生效"
        )


class TestRequireUuidPkWiredIntoImpl:
    """断言 3：`require_uuid_pk` 真的被实现层接入（不再是零消费者）。"""

    def test_has_consumers_outside_definition(self) -> None:
        """B1 交付时它零消费者；本批必须接入，否则本用例 FAIL。"""
        repo_root = pathlib.Path(__file__).resolve().parents[3]
        src = repo_root / "src" / "inkflow"
        guard = src / "infrastructure" / "database" / "repositories" / "_id_guard.py"
        hits: list[str] = []
        for path in src.rglob("*.py"):
            if path == guard:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "require_uuid_pk" in text:
                hits.append(str(path.relative_to(src)))
        assert hits, (
            "require_uuid_pk 在 _id_guard.py 之外零消费者 —— 本批必须把它接入实现层（设计 §4）"
        )


class TestNoRedundantIntUnwrapAtCallSites:
    """断言 4（等价性）：调用点不应再把领域 UUID 解包成 int 传给 repo.get。"""

    def test_src_has_no_get_with_to_int_id_wrapper(self) -> None:
        """`repo.get(_to_int_id(X))` 形态应清零（issue 建议修法：去包裹）。"""
        repo_root = pathlib.Path(__file__).resolve().parents[3]
        src = repo_root / "src" / "inkflow"
        pattern = re.compile(r"\.get\(_to_int_id\(")
        offenders: list[str] = []
        for path in src.rglob("*.py"):
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
            ):
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(src)}:{lineno}: {line.strip()}")
        assert not offenders, (
            "以下调用点仍用 _to_int_id 包裹（本批应收敛为直接传 UUID）：\n"
            + "\n".join(offenders[:20])
        )

    def test_copy_service_dict_lookup_not_regressed(self) -> None:
        """🔴 已知坑守护：`id_map.get(X.int)` 是 **dict** 查询，键本就是 int。

        issue 明示批 3-B 曾因正则过宽误伤它致 12 例回归 ——
        本用例钉住「该处**不得**被改」（dict 查询必须保留 .int）。
        """
        repo_root = pathlib.Path(__file__).resolve().parents[3]
        copy_svc = repo_root / "src" / "inkflow" / "domain" / "services" / "copy_service.py"
        if not copy_svc.exists():
            pytest.skip("copy_service.py 不存在于本基线")
        text = copy_svc.read_text(encoding="utf-8", errors="ignore")
        assert "id_map" in text, "copy_service 结构已变 —— 请复核本守护用例是否仍适用"


class TestEquivalenceUuidVsIntPath:
    """断言 4b：新老入口对同一逻辑 id 结果一致（迁移等价性）。"""

    @pytest.mark.parametrize("n", [1, 42, 999999])
    def test_equivalence(self, n: int) -> None:
        assert require_uuid_pk(uuid.UUID(int=n)) == uuid_to_pk_or_none(n)


class TestFalsifiability:
    """断言 5：可证伪自证 —— 本套件对「收窄被回退」敏感。

    真正的证伪动作 = 把某 repo 的 ports 签名改回 int 后重跑本文件，
    预期 `TestPortsNarrowedToUuid` 全 FAIL。此处另以「注解取值器本身有判别力」
    做低成本自证。
    """

    def test_annotation_reader_distinguishes_int_from_uuid(self) -> None:
        class _IntProto:
            async def get(self, x: int) -> object: ...

        class _UuidProto:
            async def get(self, x: uuid.UUID) -> object: ...

        assert _get_param_annotation(_IntProto) is int
        assert _get_param_annotation(_UuidProto) is uuid.UUID
        assert _get_param_annotation(_IntProto) is not uuid.UUID, (
            "注解取值器失去判别力 —— 上面两个 TestPortsNarrowedToUuid 用例将恒真"
        )

    def test_typing_get_type_hints_stable(self) -> None:
        """兜底：确保 typing 侧解析正确（部分环境依赖 get_type_hints）。"""
        proto = _project_port.ProjectRepositoryProtocol
        hints = typing.get_type_hints(proto.get)
        assert "project_id" in hints
        assert hints["project_id"] is uuid.UUID
