"""云端演进接口 — 对象存储（StorageProtocol）。

本地实现（Phase 1-3）: LocalFileStorage（data_dir 下的文件存储）
云端实现（Phase 4+）: CloudObjectStorage（S3 兼容）

仅定义接口，不实现任何云端功能（PRD §6.5 / spec f52-cloud-protocol）。
"""

from __future__ import annotations

from typing import Protocol


class StorageProtocol(Protocol):
    """对象存储接口。

    本地实现: LocalFileStorage — ``key`` 映射到 data_dir 下的相对路径。
    云端实现: CloudObjectStorage — 对象桶 + 预签名 URL。
    """

    async def save(self, key: str, data: bytes) -> str: ...

    async def load(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...
