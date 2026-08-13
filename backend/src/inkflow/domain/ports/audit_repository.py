"""审计仓储端口 — 一致性审计持久化契约.

#211 真删语义：F9/F12/F13 已移除 is_deleted 列（软删→真删），审计不再需要
软删集合补充查询（原 list_deleted 已移除）。AuditRepositoryProtocol 保留为
兼容历史构造签名（audit_service.audit_repo 可选参数），基础设施层不再提供
实现（audit_repo.py 已删除）。

依据: specs/f15-audit-service/spec.md §8.2（#211 适配）。
"""

from __future__ import annotations

from typing import Protocol


class AuditRepositoryProtocol(Protocol):
    """审计仓储端口（#211 真删后无软删集合查询）.

    F9/F12 删除语义已统一为真删，审计引用完整性规则（R-C1/R-C2/R-F1）不再
    需要软删集合——引用目标不在活动集合即悬空 → error，无「软删 → warning」档。
    """
