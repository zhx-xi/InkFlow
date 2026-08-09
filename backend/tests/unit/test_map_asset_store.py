"""LocalMapAssetStore 契约测试（F36 地图资产存储层 RED→GREEN，spec §5.1）.

覆盖 MapAssetStoreProtocol 全部方法:
- save: 布局 base_dir/maps/<map_uuid>/main.<ext>，返回正斜杠相对路径字符串
- delete: 幂等删除（不存在静默）、非法相对路径抛 MapAssetError
- copy: 跨地图目录复制；源缺失抛 MapAssetError
- resolve: 相对路径 → 绝对 Path；路径穿越/绝对路径抛异常

【设计假设】（父侧定稿契约，GREEN 实现按此逐字落地）
1. 被测模块 inkflow.infrastructure.assets.map_asset_store（整模块未实现，RED
   阶段收集期 ModuleNotFoundError = 预期终态）。模块同时导出:
   - LocalMapAssetStore(base_dir: Path) 类
   - MapAssetStoreProtocol（Protocol，纯基础设施端口）
2. 构造: LocalMapAssetStore(base_dir: Path)；base_dir = 数据根（含 maps/ 子目录）。
3. 端口方法签名（save/delete/copy 为 async，resolve 为同步 def）:
   - async def save(self, *, map_id: uuid.UUID, filename: str, content: bytes) -> str
   - async def delete(self, relative_path: str) -> None
   - async def copy(self, relative_path: str, *, map_id: uuid.UUID) -> str
   - def resolve(self, relative_path: str) -> Path
4. save 语义（load-bearing）:
   - 存储布局: base_dir / 'maps' / '<map_uuid>' / 'main.<ext>'；返回相对路径
     'maps/<map_uuid>/main.<ext>'（正斜杠，Windows 兼容）
   - <ext> 取自 filename 扩展名（小写）；白名单 png / jpg / jpeg / webp；
     filename 无扩展名或扩展名不在白名单 → raise MapAssetError
   - 魔数校验（spec §5.1）: PNG = b'\x89PNG\r\n\x1a\n' 前缀；JPEG =
     b'\xff\xd8\xff' 前缀；WEBP = 前 4 字节 b'RIFF' 且 8-12 字节 b'WEBP'。
     content 魔数与 filename 扩展名不一致（如 .png 扩展名 + JPEG 魔数）
     → raise MapAssetError；魔数不识别 → raise MapAssetError
   - 大小上限 10 MB（10 * 1024 * 1024）: len(content) 超限 → raise MapAssetError
   - 成功: 写入文件（父目录自动创建），返回相对路径
   - 同 map_id 重复 save: 覆盖写（同一路径）
5. copy: 读源文件字节 → save 到新 map_id 目录（同样魔数/大小校验，GREEN 可
   复用 save 内部逻辑）；返回新相对路径。源文件缺失 → raise MapAssetError。
6. delete: 删文件；目录若空则连父目录一起删（可选，不强断言）；不存在 → 静默
   （不抛）。相对路径非法（穿越/绝对路径）→ raise MapAssetError。
7. resolve: 'maps/<uuid>/main.png' → base_dir/'maps/<uuid>/main.png'
   （Path 相等断言）。路径穿越拒绝: '../../etc/passwd'、'maps/../main.png'、
   绝对路径（'C:/x' 或 base_dir 外）→ 抛异常。规范化后必须位于 base_dir 内
   （spec §5.1 路径安全）。★ 本文件 resolve 异常统一断言 MapAssetError（父侧
   授权 ValueError 或 MapAssetError 二选一，此处写死 MapAssetError；GREEN
   若抛 ValueError 需同步调整本用例并知会父侧）。
8. 错误类: inkflow.domain.ports.map_errors.MapAssetError（该模块也未实现 →
   模块级 try/except ImportError stub，文件仍可收集；GREEN 落地后自动走真实类）。

【RED 预期】
- 收集期 ModuleNotFoundError: No module named 'inkflow.infrastructure.assets'
  （asset store 整模块缺失，collected 0 items，exit code 2）= 正确 RED 终态；
  map_errors stub 保证收集不被第二个缺失模块阻断。
- GREEN 落地后本文件应全绿（14 个测试函数 / 18 个参数化实例）。
"""

from __future__ import annotations

import uuid

import pytest

try:
    from inkflow.domain.ports.map_errors import MapAssetError
except ImportError:  # pragma: no cover - F36 RED: map_errors 尚未实现
    MapAssetError = type("MapAssetError", (Exception,), {})

from inkflow.infrastructure.assets import map_asset_store

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG_BYTES = b"\xff\xd8\xff" + b"\x00" * 16
WEBP_BYTES = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 8
MAX_BYTES = 10 * 1024 * 1024


@pytest.fixture
def store(tmp_path):
    """临时目录上的 LocalMapAssetStore（tmp_path 即数据根 base_dir）."""
    return map_asset_store.LocalMapAssetStore(tmp_path)


async def test_save_png_writes_file_and_returns_relative_path(store, tmp_path):
    """save 成功: 返回 'maps/<uuid>/main.png'（正斜杠）+ 文件存在 + 内容一致."""
    map_id = uuid.uuid4()
    rel = await store.save(map_id=map_id, filename="main.png", content=PNG_BYTES)

    assert rel == f"maps/{map_id}/main.png"
    assert "\\" not in rel  # 正斜杠相对路径（Windows 兼容）
    target = tmp_path / "maps" / str(map_id) / "main.png"
    assert target.exists()
    assert target.read_bytes() == PNG_BYTES


@pytest.mark.parametrize(
    ("filename", "content", "expected"),
    [
        ("main.jpg", JPEG_BYTES, "main.jpg"),
        ("main.jpeg", JPEG_BYTES, "main.jpeg"),
        ("main.webp", WEBP_BYTES, "main.webp"),
    ],
)
async def test_save_supported_extensions(store, tmp_path, filename, content, expected):
    """jpg/jpeg/webp 扩展名 + 对应魔数 → 各自 main.<ext> 落盘."""
    map_id = uuid.uuid4()
    rel = await store.save(map_id=map_id, filename=filename, content=content)

    assert rel == f"maps/{map_id}/{expected}"
    assert (tmp_path / "maps" / str(map_id) / expected).read_bytes() == content


@pytest.mark.parametrize("filename", ["map.gif", "map.exe", "map"])
async def test_save_rejects_unsupported_extension(store, filename):
    """扩展名不在白名单（.gif/.exe/无扩展名）→ MapAssetError."""
    with pytest.raises(MapAssetError):
        await store.save(map_id=uuid.uuid4(), filename=filename, content=PNG_BYTES)


async def test_save_rejects_magic_mismatch(store):
    """.png 扩展名 + JPEG 魔数（魔数与扩展名不一致）→ MapAssetError."""
    with pytest.raises(MapAssetError):
        await store.save(map_id=uuid.uuid4(), filename="main.png", content=JPEG_BYTES)


async def test_save_rejects_unrecognized_magic(store):
    """魔数不识别（GIF 头 + .png 扩展名）→ MapAssetError."""
    with pytest.raises(MapAssetError):
        await store.save(
            map_id=uuid.uuid4(),
            filename="main.png",
            content=b"GIF89a" + b"\x00" * 16,
        )


async def test_save_rejects_oversize_content(store):
    """content 超过 10 MB 上限 → MapAssetError（PNG 头 + 超限填充）."""
    with pytest.raises(MapAssetError):
        await store.save(
            map_id=uuid.uuid4(),
            filename="main.png",
            content=b"\x89PNG\r\n\x1a\n" + b"\x00" * (MAX_BYTES + 1),
        )


async def test_delete_removes_file_and_is_idempotent(store, tmp_path):
    """delete: 存在 → 删除成功（Path.exists() False）；不存在 → 静默不抛."""
    map_id = uuid.uuid4()
    rel = await store.save(map_id=map_id, filename="main.png", content=PNG_BYTES)

    await store.delete(rel)
    assert not (tmp_path / "maps" / str(map_id) / "main.png").exists()

    await store.delete(rel)  # 幂等: 再次删除不存在也不抛


async def test_delete_rejects_illegal_path(store):
    """delete 相对路径非法（穿越/绝对路径）→ MapAssetError."""
    with pytest.raises(MapAssetError):
        await store.delete("../main.png")
    with pytest.raises(MapAssetError):
        await store.delete("C:/x/main.png")


async def test_copy_duplicates_to_new_map(store, tmp_path):
    """copy: 源复制到新 map_id → 新相对路径不同、内容一致、源保留."""
    src_id = uuid.uuid4()
    src_rel = await store.save(map_id=src_id, filename="main.png", content=PNG_BYTES)

    dst_id = uuid.uuid4()
    dst_rel = await store.copy(src_rel, map_id=dst_id)

    assert dst_rel != src_rel
    assert dst_rel == f"maps/{dst_id}/main.png"
    assert (tmp_path / dst_rel).read_bytes() == PNG_BYTES
    assert (tmp_path / "maps" / str(src_id) / "main.png").exists()  # 源保留


async def test_copy_missing_source_raises(store):
    """copy 源文件缺失 → MapAssetError."""
    with pytest.raises(MapAssetError):
        await store.copy(f"maps/{uuid.uuid4()}/main.png", map_id=uuid.uuid4())


async def test_save_overwrites_same_map_id(store, tmp_path):
    """同 map_id 重复 save: 覆盖写（同一路径，内容为最新一次）."""
    map_id = uuid.uuid4()
    first = await store.save(map_id=map_id, filename="main.png", content=PNG_BYTES)
    second_content = b"\x89PNG\r\n\x1a\n" + b"\x01" * 16
    second = await store.save(map_id=map_id, filename="main.png", content=second_content)

    assert first == second == f"maps/{map_id}/main.png"
    assert (tmp_path / first).read_bytes() == second_content


def test_resolve_normal_path(store, tmp_path):
    """resolve: 'maps/<uuid>/main.png' → base_dir 内绝对 Path（相等断言）."""
    rel = f"maps/{uuid.uuid4()}/main.png"
    assert store.resolve(rel) == tmp_path / rel


def test_resolve_rejects_traversal_and_absolute(store):
    """resolve: 路径穿越（'../../etc/passwd'、'maps/../main.png'）与绝对路径
    （'C:/x/main.png'）→ 抛异常（本文件统一断言 MapAssetError）."""
    for bad in ("../../etc/passwd", "maps/../main.png", "C:/x/main.png"):
        with pytest.raises(MapAssetError):
            store.resolve(bad)


def test_module_exports_protocol_symbol():
    """模块同时导出 MapAssetStoreProtocol（端口声明，防 GREEN 只导出实现类）."""
    assert hasattr(map_asset_store, "MapAssetStoreProtocol")
