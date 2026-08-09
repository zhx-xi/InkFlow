"""F36 地图图片资产存储 — 本地文件系统实现（MapAssetStoreProtocol）.

存储布局（spec §5.1）:
  存储根:  <base_dir>/maps/<map_uuid>/main.<ext>   （base_dir = config.data_dir）
  DB 存:  相对路径 "maps/<uuid>/main.<ext>"（正斜杠）
生命周期（D5 拍板）: 删除即删文件；换图先写新成功后删旧（由 service 编排）。

校验（save 入口，spec §5.1）:
- 扩展名白名单: png / jpg / jpeg / webp
- 魔数校验 + 扩展名一致（PNG b"\\x89PNG\\r\\n\\x1a\\n" / JPEG b"\\xff\\xd8\\xff" /
  WEBP 前 4 字节 b"RIFF" 且偏移 8-12 为 b"WEBP"）
- 大小上限 10 MB（10 * 1024 * 1024 字节）
- 路径安全: resolve 拒绝 .. 穿越与绝对路径（本地威胁模型，同 ADR-021）
"""

from __future__ import annotations

import contextlib
import uuid
from pathlib import Path
from typing import Protocol

from inkflow.domain.ports.map_errors import MapAssetError


class MapAssetStoreProtocol(Protocol):
    """地图图片资产存储端口（纯基础设施端口，域层不感知文件系统）."""

    async def save(self, *, map_id: uuid.UUID, filename: str, content: bytes) -> str:
        """保存图片 → 返回相对路径（maps/<uuid>/main.<ext>）."""
        ...

    async def delete(self, relative_path: str) -> None:
        """删除图片文件（真删地图时调用；不存在静默）."""
        ...

    async def copy(self, relative_path: str, *, map_id: uuid.UUID) -> str:
        """复制图片到新地图目录 → 返回新相对路径（#175 复制用；源缺失抛 MapAssetError）."""
        ...

    def resolve(self, relative_path: str) -> Path:
        """相对路径 → 绝对路径（FileResponse 用；穿越/绝对路径抛 MapAssetError）."""
        ...


_ALLOWED_EXT = {"png", "jpg", "jpeg", "webp"}
_MAX_SIZE = 10 * 1024 * 1024

# 魔数 → 可接受的扩展名（jpg/jpeg 同族）.
_MAGIC_EXT = {
    "png": {"png"},
    "jpeg": {"jpg", "jpeg"},
    "webp": {"webp"},
}


def _detect_image_type(content: bytes) -> str | None:
    """识别图片魔数，返回 "png"/"jpeg"/"webp"；无法识别返回 None."""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp"
    return None


class LocalMapAssetStore:
    """本地文件系统实现 — base_dir 即数据根（含 maps/ 子目录）."""

    def __init__(self, base_dir: Path) -> None:
        self._base = Path(base_dir)
        self._maps_dir = self._base / "maps"
        # base_dir 规范化只算一次（路径穿越边界判断用）.
        self._base_resolved = self._base.resolve()

    async def save(self, *, map_id: uuid.UUID, filename: str, content: bytes) -> str:
        """保存图片 → 返回相对路径（maps/<uuid>/main.<ext>，正斜杠）."""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in _ALLOWED_EXT:
            raise MapAssetError("不支持的图片扩展名")
        img_type = _detect_image_type(content)
        if img_type is None:
            raise MapAssetError("无法识别的图片格式（魔数校验失败）")
        if ext not in _MAGIC_EXT[img_type]:
            raise MapAssetError("图片魔数与扩展名不一致")
        if len(content) > _MAX_SIZE:
            raise MapAssetError("图片大小超过 10 MB 上限")
        dest = self._maps_dir / str(map_id) / f"main.{ext}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        return f"maps/{map_id}/main.{ext}"

    async def delete(self, relative_path: str) -> None:
        """删除图片文件（不存在静默）；父目录若空则一并删除."""
        path = self.resolve(relative_path)
        path.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            path.parent.rmdir()

    async def copy(self, relative_path: str, *, map_id: uuid.UUID) -> str:
        """复制图片到新地图目录 → 返回新相对路径（源缺失抛 MapAssetError）."""
        src = self.resolve(relative_path)
        if not src.is_file():
            raise MapAssetError("源图片文件不存在")
        content = src.read_bytes()
        return await self.save(map_id=map_id, filename=src.name, content=content)

    def resolve(self, relative_path: str) -> Path:
        """相对路径 → 绝对路径（穿越/绝对路径抛 MapAssetError）."""
        p = Path(relative_path)
        if p.is_absolute():
            raise MapAssetError("不接受绝对路径")
        if ".." in p.parts:
            raise MapAssetError("路径不允许 .. 穿越")
        resolved = (self._base / p).resolve()
        if not str(resolved).startswith(str(self._base_resolved)):
            raise MapAssetError("路径不在数据目录内")
        return resolved
