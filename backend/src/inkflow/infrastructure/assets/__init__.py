"""F36 地图图片资产存储 — 本地文件系统实现与端口."""

from inkflow.infrastructure.assets.map_asset_store import (
    LocalMapAssetStore,
    MapAssetStoreProtocol,
)

__all__ = ["LocalMapAssetStore", "MapAssetStoreProtocol"]
