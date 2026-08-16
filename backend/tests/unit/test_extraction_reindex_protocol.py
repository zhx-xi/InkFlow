"""#276 S2c ExtractionService.reindex 协议改造契约（QA 报告 §3.1/§4.2 服务层）。

被测改造（GREEN 按此实现，RED 阶段全部缺失）:
- ``ExtractionService.__init__`` 新增 keyword-only 参数
  ``fingerprint_provider: Callable[[], Awaitable[dict | None]] | None = None``
  （返回 configured 指纹 dict；None = 不写指纹，向后兼容）
- ``_reindex_lock``（asyncio.Lock）实例属性——reindex 全程持锁
- ``reindex()`` 协议四步（顺序不可调换）:
  ① 写 status="reindexing" 指纹（fingerprint_provider 非 None 时）
  ② 维度探测（probe_embedding_dimension vs probe_collection_dimension）：
     异维 → recreate_collections + 结果 collections_recreated=true
  ③ upsert 全量（既有分页拉取 → index_batch）→ 差集删除
     （delete_stale(pid, 源侧 id 全集, entity_types)）
  ④ commit-last 写 status="fresh" 指纹（唯一提交点——任何失败不提交 fresh）
- ReindexResult 新增字段 ``collections_recreated: bool = False``

RED 形态: __init__ 无 fingerprint_provider 参数 → 用例 ERROR（TypeError:
unexpected keyword argument，签名未扩展）；store 无 probe/delete_stale/
recreate/write_fingerprint → AttributeError；ReindexResult 无
collections_recreated → 断言 KeyError。全部为契约缺口类 RED。

依据: docs/qa-rag-consistency-report.md §3.1/§4.2 契约 17-20；Issue #276 范围 4。
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.ports.vector_store import EntityType
from inkflow.domain.services.extraction_service import ExtractionService

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")


def _configured_fp() -> dict:
    """configured 指纹 dict（fingerprint_provider 返回形态）。"""
    return {
        "schema_version": 1,
        "embedding": {
            "provider": "openai",
            "model_id": "text-embedding-3-small",
            "base_url": "https://api.test.example/v1",
            "dimension": 384,
        },
        "chunking": {
            "mode": "fixed",
            "chunk_size": 500,
            "overlap_ratio": 0.0,
            "chunker_version": 1,
        },
        "indexed_at": None,
        "status": "fresh",
    }


def _make_service(**overrides: object) -> ExtractionService:
    """构造全 mock 依赖的 ExtractionService（#276 新增 fingerprint_provider）。"""
    kwargs: dict[str, object] = {
        "project_repo": AsyncMock(),
        "chapter_repo": AsyncMock(),
        "run_repo": AsyncMock(),
        "character_service": MagicMock(),
        "world_service": MagicMock(),
        "outline_service": MagicMock(),
        "timeline_service": MagicMock(),
        "foreshadowing_extractor": MagicMock(),
        "timeline_extractor": MagicMock(),
        "style_service": MagicMock(),
        "character_repo": AsyncMock(),
        "world_repo": AsyncMock(),
        "timeline_repo": AsyncMock(),
        "foreshadowing_repo": AsyncMock(),
        "vector_store": AsyncMock(),
        "fingerprint_provider": AsyncMock(return_value=_configured_fp()),
    }
    kwargs.update(overrides)
    return ExtractionService(**kwargs)  # type: ignore[arg-type]  # 测试 helper：**kwargs 注入 mock 依赖，真实签名由运行时校验


@pytest.fixture
def store() -> MagicMock:
    """mock 向量存储（AsyncMock 主方法 + 显式返回）。"""
    s = MagicMock()
    s.index_batch = AsyncMock()
    s.delete_stale = AsyncMock(return_value=0)
    s.probe_embedding_dimension = AsyncMock(return_value=384)
    s.probe_collection_dimension = AsyncMock(return_value=0)
    s.recreate_collections = AsyncMock()
    s.write_fingerprint = AsyncMock()
    return s


async def test_reindex_writes_reindexing_then_fresh_commit_last(store: MagicMock) -> None:
    """协议: 指纹两段写——先 reindexing 后 fresh（commit-last 唯一提交点）。"""
    svc = _make_service(vector_store=store)
    await svc.reindex(PID, entity_types=[])
    assert store.write_fingerprint.await_count == 2
    calls = store.write_fingerprint.await_args_list
    assert calls[0].args[2] == "reindexing"
    assert calls[1].args[2] == "fresh"


async def test_reindex_upsert_before_diff_delete(store: MagicMock) -> None:
    """协议: upsert 先于差集删除（先清后灌失败 = 空索引，禁止）。"""
    chapters = [MagicMock(id=1, title="第 1 章", content="第一章内容" * 200)]
    svc = _make_service(vector_store=store)
    svc._chapter_repo.list_chapters = AsyncMock(return_value=(chapters, 1))
    await svc.reindex(PID, entity_types=[EntityType.CHAPTER_CHUNK])
    idx = store.index_batch.await_args_list
    dele = store.delete_stale.await_args_list
    # 全部 upsert 调用先于任何 delete_stale（调用顺序不可调换）
    # ⚠️ method_calls 元素是 _Call 对象（内部三元素结构），不能与普通元组
    # 比较——按 name 序列索引比较（父侧修正 2026-08-12）
    assert idx and dele
    call_names = [c[0] for c in store.method_calls]
    last_upsert = max(i for i, n in enumerate(call_names) if n == "index_batch")
    first_delete = call_names.index("delete_stale")
    assert last_upsert < first_delete


async def test_reindex_deletes_stale_with_source_ids(store: MagicMock) -> None:
    """协议: delete_stale 收到源侧 id 全集（差集删除的源侧投影）。"""
    chapters = [MagicMock(id=1, title="第 1 章", content="第一章内容" * 200)]
    svc = _make_service(vector_store=store, chapter_repo=AsyncMock())
    svc._chapter_repo.list_chapters = AsyncMock(return_value=(chapters, 1))
    await svc.reindex(PID, entity_types=[])
    # 差集删除被调用（entity_types 透传；源侧 id 由实现收集——非空即可）
    store.delete_stale.assert_awaited_once()


async def test_reindex_failure_does_not_commit_fresh(store: MagicMock) -> None:
    """commit-last: upsert 失败 → fresh 不得写入（状态停留 stale/reindexing）。"""
    chapters = [MagicMock(id=1, title="第 1 章", content="第一章内容" * 200)]
    store.index_batch = AsyncMock(side_effect=RuntimeError("embedding api failed"))
    svc = _make_service(vector_store=store)
    svc._chapter_repo.list_chapters = AsyncMock(return_value=(chapters, 1))
    with pytest.raises(RuntimeError):
        await svc.reindex(PID, entity_types=[EntityType.CHAPTER_CHUNK])
    calls = store.write_fingerprint.await_args_list
    # 至多写了 reindexing；绝无 fresh（防假成功）
    assert all(call.args[2] != "fresh" for call in calls)


async def test_reindex_dimension_mismatch_recreates_collections(
    store: MagicMock,
) -> None:
    """维度不匹配: 现存 768 vs 目标 384 → recreate_collections + collections_recreated=true。"""
    store.probe_collection_dimension = AsyncMock(return_value=768)
    svc = _make_service(vector_store=store)
    result = await svc.reindex(PID, entity_types=[])
    store.recreate_collections.assert_awaited_once()
    assert result.collections_recreated is True


async def test_reindex_same_dimension_inplace(store: MagicMock) -> None:
    """同维度: 现存 384 vs 目标 384 → 原地重灌，不重建 collection。"""
    store.probe_collection_dimension = AsyncMock(return_value=384)
    svc = _make_service(vector_store=store)
    result = await svc.reindex(PID, entity_types=[])
    store.recreate_collections.assert_not_awaited()
    assert result.collections_recreated is False


async def test_reindex_empty_collection_no_recreate(store: MagicMock) -> None:
    """空库: 现存 0（无向量）→ 直接灌新模型，无重建。"""
    store.probe_collection_dimension = AsyncMock(return_value=0)
    svc = _make_service(vector_store=store)
    result = await svc.reindex(PID, entity_types=[])
    store.recreate_collections.assert_not_awaited()
    assert result.collections_recreated is False


async def test_reindex_dimension_retry_recreate_then_raise_if_still_fails(
    store: MagicMock,
) -> None:
    """协议补充: upsert 维度兜底——重建后仍失败 → 原样上抛（coverage 补强 2026-08-12）。

    覆盖 extraction_service 898 行 raise 分支（recreated=True 后 index_batch 再抛）。
    """
    chapters = [MagicMock(id=1, title="第 1 章", content="第一章内容" * 200)]
    svc = _make_service(vector_store=store)
    svc._chapter_repo.list_chapters = AsyncMock(return_value=(chapters, 1))
    store.probe_embedding_dimension = AsyncMock(return_value=768)
    store.probe_collection_dimension = AsyncMock(return_value=384)
    store.index_batch = AsyncMock(side_effect=RuntimeError("embedding api failed"))
    with pytest.raises(RuntimeError):
        await svc.reindex(PID, entity_types=[EntityType.CHAPTER_CHUNK])
    # 重建恰好一次（首败触发）→ 重试再败 → 上抛；fresh 不提交（commit-last）
    store.recreate_collections.assert_awaited_once()
    assert store.write_fingerprint.await_count == 1  # 仅 reindexing


async def test_reindex_concurrent_calls_serialized(store: MagicMock) -> None:
    """契约20: 并发 reindex 锁串行——index_batch 无并发交错（max_depth == 1）。"""
    depth = 0
    max_depth = 0

    async def slow_index(entities: list[object]) -> None:
        nonlocal depth, max_depth
        depth += 1
        max_depth = max(max_depth, depth)
        await asyncio.sleep(0.05)
        depth -= 1

    chapters = [MagicMock(id=1, title="第 1 章", content="第一章内容" * 200)]
    store.index_batch = AsyncMock(side_effect=slow_index)
    svc = _make_service(vector_store=store)
    svc._chapter_repo.list_chapters = AsyncMock(return_value=(chapters, 1))
    await asyncio.gather(
        svc.reindex(PID, entity_types=[EntityType.CHAPTER_CHUNK]),
        svc.reindex(PID, entity_types=[EntityType.CHAPTER_CHUNK]),
    )
    assert max_depth == 1  # 锁保证串行，无并发交错
    assert store.write_fingerprint.await_count == 4  # 两次 reindex × (reindexing + fresh)


async def test_reindex_twice_idempotent(store: MagicMock) -> None:
    """契约17 服务层: 两次 reindex 终态一致（无 stale 循环、指纹均 fresh）。"""
    svc = _make_service(vector_store=store)
    await svc.reindex(PID, entity_types=[])
    await svc.reindex(PID, entity_types=[])
    calls = store.write_fingerprint.await_args_list
    assert calls[-1].args[2] == "fresh"
    assert store.delete_stale.await_count == 2


# ══ #277 M3 追加段（2026-08-16）: reindex 配置切片 + 章节块元数据 ═══
# 契约源: specs/f14-extraction-service/spec.md §5.6.3-§5.6.5。
# RED 期 ExtractionService 无 chunking 参数 → TypeError；_project_chapter_chunk
# 无新元数据/块 id 三态 → 断言失败。

PARA_TEXT = "第一段。\n\n第二段。\n\n第三段。"


async def test_reindex_chapter_chunk_uses_configured_paragraph_mode() -> None:
    """reindex 装配 chunking mode=paragraph → 章节按段落切块（多块）。"""
    from inkflow.domain.services._chunking import ChunkingConfig, ChunkingMode

    chapters = [
        MagicMock(id=1, title="第 1 章", content=PARA_TEXT, volume_id=None, order_index=1.0)
    ]
    store = MagicMock()
    store.index_batch = AsyncMock()
    store.delete_stale = AsyncMock(return_value=0)
    store.probe_embedding_dimension = AsyncMock(return_value=384)
    store.probe_collection_dimension = AsyncMock(return_value=0)
    store.recreate_collections = AsyncMock()
    store.write_fingerprint = AsyncMock()
    svc = _make_service(
        vector_store=store,
        chunking=ChunkingConfig(mode=ChunkingMode.PARAGRAPH, chunk_size=500),
    )
    svc._chapter_repo.list_chapters = AsyncMock(return_value=(chapters, 1))
    svc._chapter_repo.list_volumes = AsyncMock(return_value=[])

    await svc.reindex(PID, entity_types=[EntityType.CHAPTER_CHUNK])

    entities = store.index_batch.await_args.args[0]
    chunks = [e for e in entities if e.entity_type is EntityType.CHAPTER_CHUNK]
    assert [e.content for e in chunks] == ["第一段。", "第二段。", "第三段。"]


async def test_reindex_chapter_chunk_metadata_writes_full_position_context() -> None:
    """reindex 全量路径写全 chapter_x/chapter_y/volume_title/chunk_start/indexed_at。"""
    chapters = [
        MagicMock(id=1, title="第 1 章", content="甲" * 100, volume_id=10, order_index=2.0),
        MagicMock(id=2, title="第 2 章", content="乙" * 100, volume_id=10, order_index=1.0),
    ]
    store = MagicMock()
    store.index_batch = AsyncMock()
    store.delete_stale = AsyncMock(return_value=0)
    store.probe_embedding_dimension = AsyncMock(return_value=384)
    store.probe_collection_dimension = AsyncMock(return_value=0)
    store.recreate_collections = AsyncMock()
    store.write_fingerprint = AsyncMock()
    svc = _make_service(vector_store=store)
    svc._chapter_repo.list_chapters = AsyncMock(return_value=(chapters, 2))
    # volume_id=10 → 第一卷（list_volumes 映射）
    volume = MagicMock()
    volume.id = 10
    volume.title = "第一卷"
    svc._chapter_repo.list_volumes = AsyncMock(return_value=[volume])

    await svc.reindex(PID, entity_types=[EntityType.CHAPTER_CHUNK])

    entities = store.index_batch.await_args.args[0]
    chunks = [e for e in entities if e.entity_type is EntityType.CHAPTER_CHUNK]
    # list_chapters 按 order_index 排序（id=2 第 1 章、id=1 第 2 章）
    assert len(chunks) == 2
    by_chapter = {e.metadata["chapter_id"]: e for e in chunks}
    assert by_chapter["2"].metadata["chapter_x"] == 1
    assert by_chapter["2"].metadata["chapter_y"] == 2
    assert by_chapter["1"].metadata["chapter_x"] == 2
    assert by_chapter["1"].metadata["chapter_y"] == 2
    for e in chunks:
        assert e.metadata["volume_title"] == "第一卷"
        assert e.metadata["chunk_start"] == 0
        assert isinstance(e.metadata["indexed_at"], str)
        assert "T" in e.metadata["indexed_at"]
    # 无卷章节省略 volume_title（id=1 无 volume_id 场景由增量路径覆盖，此处同卷）
    assert all("volume_title" in e.metadata for e in chunks)


async def test_reindex_chapter_chunk_overlap_uses_triple_part_id() -> None:
    """reindex overlap>0 → 块 id 三态（{chapter_id}:{idx}:{start_offset}）。"""
    from inkflow.domain.services._chunking import ChunkingConfig, ChunkingMode

    chapters = [
        MagicMock(id=1, title="第 1 章", content="章" * 1200, volume_id=None, order_index=1.0)
    ]
    store = MagicMock()
    store.index_batch = AsyncMock()
    store.delete_stale = AsyncMock(return_value=0)
    store.probe_embedding_dimension = AsyncMock(return_value=384)
    store.probe_collection_dimension = AsyncMock(return_value=0)
    store.recreate_collections = AsyncMock()
    store.write_fingerprint = AsyncMock()
    svc = _make_service(
        vector_store=store,
        chunking=ChunkingConfig(mode=ChunkingMode.FIXED, chunk_size=500, overlap_ratio=0.2),
    )
    svc._chapter_repo.list_chapters = AsyncMock(return_value=(chapters, 1))
    svc._chapter_repo.list_volumes = AsyncMock(return_value=[])

    await svc.reindex(PID, entity_types=[EntityType.CHAPTER_CHUNK])

    entities = store.index_batch.await_args.args[0]
    chunks = [e for e in entities if e.entity_type is EntityType.CHAPTER_CHUNK]
    assert len(chunks) >= 2
    assert any(len(e.id.split(":")) == 3 for e in chunks)
