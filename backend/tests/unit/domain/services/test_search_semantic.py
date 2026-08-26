"""SearchService semantic 模式映射契约测试（F22 RED，spec §5.8 + §9.2 场景 8 + §13 M12）.

纯 mock 轨（父侧裁定 2026-08-09）：vector_store 用 AsyncMock（mock VectorStoreProtocol 端口），
**不实例化真 chroma**——F22 是 RAG 消费方，测的是映射逻辑；真 chroma 集成已由 F14
test_langchain_vector_store.py 覆盖（且 chromadb 与 coverage 同进程冲突，避免 ci.yml 再加
--ignore）。这等价于 spec §5.8「测试用 FakeEmbeddings（F14 先例，不进真实模型）」的精神
（mock retrieve 返回固定 RetrievedEntity）。

被测模块 ``inkflow.domain.services.search_service`` 尚未实现（RED 阶段）——顶部 import
首报 ``No module named 'inkflow.domain.services.search_service'``，收集期整文件失败
（collected 0 items + 1 error）为预期终态；次要缺失模块（``inkflow.domain.models.search``）
一律在 helper 函数体内惰性 import（核心规则 1c：收集错误只报主契约模块单一缺失）。

================================ 设计假设（docstring 即契约） ================================

1. SearchService 模块路径与构造（同 test_search_service.py，deps.py 装配，全部关键字参数）::

       from inkflow.domain.services.search_service import SearchService
       SearchService(
           *, project_repo, chapter_repo, character_repo, world_repo, outline_repo,
           timeline_repo, foreshadowing_repo, search_repo, vector_store=None,
       )

2. semantic 分支（spec §5.8 ③-④，本文件全部用例的触发前提）:

   - 仅当 ``SearchQuery.mode == SearchMode.SEMANTIC`` 且 vector_store 已注入时走语义分支；
     词法索引（ensure_index / search_repo.query）完全不参与——本文件断言
     ``search_repo.query.assert_not_awaited()`` 锁定「semantic 不触词法」
   - 对每个 project_id **循环**调用 ``vector_store.retrieve(q, project_id=str(pid), ...)``
     （retrieve 签名只有单 project_id，多项目 = 多次调用；F14 惯例 project_id = str(项目 UUID)）
   - retrieve 抛异常 → 200 空结果 + mode 回显，**不降级 keyword**（E12）

3. RetrievedEntity → SearchHit 映射（spec §5.8 ④；entity_id/project_id/title 从 metadata 取，
   键名以 F14 extraction_service.py 实测为准——2026-08-09 源码核实）:

   | F14 EntityType | SearchEntityType | entity_id                | title                     |
   |----------------|------------------|--------------------------|---------------------------|
   | CHAPTER_CHUNK  | chapter          | metadata['chapter_id']   | metadata['chapter_title'] |
   | CHARACTER      | character        | RetrievedEntity.entity_id| metadata['name']          |
   | SETTING        | world            | RetrievedEntity.entity_id| metadata['name']          |
   | TIMELINE_EVENT | timeline         | RetrievedEntity.entity_id| metadata['title']         |
   | FORESHADOWING  | foreshadowing    | RetrievedEntity.entity_id| metadata['name']          |
   | （无）         | outline          | 恒空（见下注）           | —                         |

   键名说明（F14 extraction_service.py 实测，2026-08-09）: CHAPTER_CHUNK 的块 id 形如
   "{chapter_id}:{idx}"（非 UUID），entity_id 须取 metadata['chapter_id']；其余类型
   entity_id = uuid.UUID(RetrievedEntity.entity_id)。outline 恒空 = F14 不索引大纲，
   semantic 模式 outline 恒无命中（覆盖缺口 §5.8 load-bearing）。

   - ``project_id = uuid.UUID(metadata['project_id'])``（缺省回退本轮查询 pid；本文件
     fixture 恒带 project_id 键，锁定优先路径）
   - ``snippet = content[:200]`` 硬截断（无 <mark> 词级高亮，§5.4 semantic 降级）
   - ``score = relevance_score`` 原样透传（无归一化/变换）
   - hits 顺序 = retrieve 返回顺序，semantic **不重排**

4. types 透传映射（§6.3 + §5.8）: SearchEntityType 列表 → F14 EntityType 列表
   （chapter→CHAPTER_CHUNK 等；outline 无映射类型 → 剔除）；None → None；
   全部剔除后为空列表 → semantic 恒空（retrieve 可不调用或调用无结果，total 恒 0）。

5. 跨文件兼容注（GREEN 对照）: test_search_service.py 假设 7 对 CHAPTER_CHUNK 用
   metadata['name'] 作 title 回退、entity_id 用 RetrievedEntity.entity_id 回退——GREEN 对
   chunk 实现「metadata['chapter_id']/['chapter_title'] 优先、缺省回退」语义可同时满足
   两文件（本文件 fixture 恒含 chapter_id/chapter_title 键，锁定优先路径）。

6. 数据源 repo 调用形态（全部 AsyncMock 注入，int 主键——仓储层惯例，F9 §8.1）:

   - ``project_repo.get(project_id: int) -> Project | None``（None = 不存在/已软删 → 404，
     E1 同 keyword，本文件只走存在路径）
   - ``search_repo`` 仅用于断言「未被调用」；is_stale 默认 False（semantic 不触发词法
     索引重建，见 2）
   - ``vector_store``（F14 既有端口 inkflow.domain.ports.vector_store）::

       async def retrieve(self, query: str, *, project_id: str,
                          entity_types: list[EntityType] | None = None,
                          top_k: int = 10, min_score: float = 0.0)
                          -> list[RetrievedEntity]

     project_id / entity_types 为关键字-only 参数（端口签名），断言用 call.kwargs 安全。

7. 领域模型（惰性 import inkflow.domain.models.search）: SearchQuery 构造同兄弟文件
   （q / project_ids / types=[SearchEntityType(t)...] / mode / limit / offset）；
   SearchMode('semantic') 合法；SearchEntityType 为 StrEnum（与 str 可比较，
   ``resp.hits[0].entity_type == 'chapter'`` / ``resp.mode == 'semantic'`` 成立）。

RED 预期: collected 0 items + 1 error（No module named
'inkflow.domain.services.search_service'）——预期 RED；其他错误 = 测试文件自身缺陷。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.project import Project
from inkflow.domain.ports.vector_store import EntityType, RetrievedEntity
from inkflow.domain.services.search_service import SearchService

_NOW = datetime.now(UTC)


# ────────────────────────────── 构造 helper（惰性 import 缺失模块） ──────────────────────────────


def _query(q, project_ids, *, types=None, mode=None, limit=20, offset=0):
    """构造 SearchQuery（惰性 import——RED 阶段 inkflow.domain.models.search 缺失）."""
    from inkflow.domain.models.search import SearchEntityType, SearchMode, SearchQuery

    return SearchQuery(
        q=q,
        project_ids=project_ids,
        types=[SearchEntityType(t) for t in types] if types is not None else None,
        mode=mode if mode is not None else SearchMode.KEYWORD,
        limit=limit,
        offset=offset,
    )


def _entity(
    entity_type: EntityType, entity_id: str, content: str, score: float, metadata: dict
) -> RetrievedEntity:
    """构造 F14 RetrievedEntity（mock 轨固定返回，等效 FakeEmbeddings 固定向量）."""
    return RetrievedEntity(
        entity_id=entity_id,
        entity_type=entity_type,
        content=content,
        relevance_score=score,
        metadata=metadata,
    )


def _chunk_meta(pid: uuid.UUID, chapter_uuid: uuid.UUID, title: str) -> dict:
    """CHAPTER_CHUNK metadata——键名照 F14 extraction_service._project_chapter_chunk 实测."""
    return {"chapter_id": str(chapter_uuid), "chapter_title": title, "project_id": str(pid)}


def _named_meta(pid: uuid.UUID, name: str) -> dict:
    """CHARACTER/SETTING/FORESHADOWING metadata（F14 实测键: name + project_id）."""
    return {"name": name, "project_id": str(pid)}


def _timeline_meta(pid: uuid.UUID, title: str) -> dict:
    """TIMELINE_EVENT metadata（F14 实测键: title + project_id，无 name）."""
    return {"title": title, "project_id": str(pid)}


# ────────────────────────────── fixtures ──────────────────────────────


@pytest.fixture
def repos():
    """全 mock 数据源 + search_repo + vector_store（semantic 轨；默认空检索结果）."""
    r = SimpleNamespace(
        project_repo=AsyncMock(),
        chapter_repo=AsyncMock(),
        character_repo=AsyncMock(),
        world_repo=AsyncMock(),
        outline_repo=AsyncMock(),
        timeline_repo=AsyncMock(),
        foreshadowing_repo=AsyncMock(),
        search_repo=AsyncMock(),
        vector_store=AsyncMock(),
    )
    r.search_repo.is_stale.return_value = False
    r.search_repo.query.return_value = (0, [])
    r.vector_store.retrieve.return_value = []
    return r


def _make_service(repos, **kwargs) -> SearchService:
    """构造被测 SearchService（vector_store 等可选装配缝经 kwargs 注入）."""
    return SearchService(
        project_repo=repos.project_repo,
        chapter_repo=repos.chapter_repo,
        character_repo=repos.character_repo,
        world_repo=repos.world_repo,
        outline_repo=repos.outline_repo,
        timeline_repo=repos.timeline_repo,
        foreshadowing_repo=repos.foreshadowing_repo,
        search_repo=repos.search_repo,
        **kwargs,
    )


def _project(pid: uuid.UUID, name: str = "测试项目") -> Project:
    return Project(id=pid, name=name, created_at=_NOW, updated_at=_NOW)


def _given_project(repos, pid: uuid.UUID, name: str = "测试项目") -> Project:
    """让 project_repo.get 返回指定项目（项目存在路径默认形态）."""
    proj = _project(pid, name)
    repos.project_repo.get.return_value = proj
    return proj


def _retrieve_call(repos) -> tuple:
    """解包 vector_store.retrieve 最近一次调用.

    query 兼容位置/关键字；project_id/entity_types 为端口关键字-only 参数。
    """
    call = repos.vector_store.retrieve.await_args
    args = call.args
    kwargs = call.kwargs
    return (
        args[0] if len(args) > 0 else kwargs.get("query"),
        kwargs.get("project_id"),
        kwargs.get("entity_types"),
    )


# ────────────────────────────── 命中映射（契约 1，§5.8 映射表） ──────────────────────────────


async def test_semantic_mixed_types_mapped(repos):
    """契约 1: 混合类型 RetrievedEntity 列表 → 5 类 SearchHit 逐类映射正确."""
    pid = uuid.UUID(int=1000)
    _given_project(repos, pid)
    chapter_uuid = uuid.UUID(int=1001)
    char_uuid = uuid.UUID(int=1002)
    setting_uuid = uuid.UUID(int=1003)
    event_uuid = uuid.UUID(int=1004)
    fore_uuid = uuid.UUID(int=1005)
    repos.vector_store.retrieve.return_value = [
        _entity(
            EntityType.CHAPTER_CHUNK,
            f"{chapter_uuid}:0",
            "古井深处，龙瞳睁开。",
            0.9,
            _chunk_meta(pid, chapter_uuid, "第 3 章 龙的苏醒"),
        ),
        _entity(
            EntityType.CHARACTER, str(char_uuid), "冷静坚毅的龙女", 0.85, _named_meta(pid, "龙女")
        ),
        _entity(
            EntityType.SETTING,
            str(setting_uuid),
            "北境荒原，终年冰雪",
            0.8,
            _named_meta(pid, "龙族领地"),
        ),
        _entity(
            EntityType.TIMELINE_EVENT,
            str(event_uuid),
            "古井深处传来龙吟",
            0.75,
            _timeline_meta(pid, "龙苏醒之日"),
        ),
        _entity(
            EntityType.FORESHADOWING, str(fore_uuid), "龙瞳睁开", 0.7, _named_meta(pid, "千年沉睡")
        ),
    ]

    resp = await _make_service(repos, vector_store=repos.vector_store).search(
        _query("龙", [pid], mode="semantic")
    )

    assert resp.total == 5
    assert [h.entity_type for h in resp.hits] == [
        "chapter",
        "character",
        "world",
        "timeline",
        "foreshadowing",
    ]
    # CHAPTER_CHUNK → chapter: entity_id 取 metadata['chapter_id']（块 id 非 UUID）
    assert resp.hits[0].entity_id == chapter_uuid
    assert resp.hits[0].title == "第 3 章 龙的苏醒"
    assert resp.hits[0].project_id == pid
    # CHARACTER → character: entity_id = RetrievedEntity.entity_id，title = metadata['name']
    assert resp.hits[1].entity_id == char_uuid
    assert resp.hits[1].title == "龙女"
    # SETTING → world
    assert resp.hits[2].entity_id == setting_uuid
    assert resp.hits[2].title == "龙族领地"
    # TIMELINE_EVENT → timeline（title 取 metadata['title']，F14 无 name 键）
    assert resp.hits[3].entity_id == event_uuid
    assert resp.hits[3].title == "龙苏醒之日"
    # FORESHADOWING → foreshadowing
    assert resp.hits[4].entity_id == fore_uuid
    assert resp.hits[4].title == "千年沉睡"
    assert resp.mode == "semantic"
    repos.search_repo.query.assert_not_awaited()


# ────────────── snippet / score（契约 2/3） ──────────────


async def test_semantic_snippet_truncated_to_200(repos):
    """契约 2: snippet = content[:200] 硬截断，无 <mark>；短内容原样透传."""
    pid = uuid.UUID(int=1000)
    _given_project(repos, pid)
    long_content = "古井深处，龙瞳睁开。" * 30  # 300 字符，超出 200 截断线
    repos.vector_store.retrieve.return_value = [
        _entity(EntityType.CHARACTER, "3001", long_content, 0.8, _named_meta(pid, "龙女")),
        _entity(EntityType.CHARACTER, "3002", "短内容", 0.6, _named_meta(pid, "剑客")),
    ]

    resp = await _make_service(repos, vector_store=repos.vector_store).search(
        _query("龙", [pid], mode="semantic")
    )

    assert resp.hits[0].snippet == long_content[:200]
    assert len(resp.hits[0].snippet) == 200
    assert "<mark>" not in resp.hits[0].snippet
    assert resp.hits[1].snippet == "短内容"


async def test_semantic_score_passthrough(repos):
    """契约 3: relevance_score 原样透传为 hit.score（无变换，含 0.0 边界）."""
    pid = uuid.UUID(int=1000)
    _given_project(repos, pid)
    repos.vector_store.retrieve.return_value = [
        _entity(EntityType.CHARACTER, "4001", "内容甲", 0.9231, _named_meta(pid, "甲")),
        _entity(EntityType.CHARACTER, "4002", "内容乙", 0.0, _named_meta(pid, "乙")),
    ]

    resp = await _make_service(repos, vector_store=repos.vector_store).search(
        _query("龙", [pid], mode="semantic")
    )

    assert resp.hits[0].score == 0.9231
    assert resp.hits[1].score == 0.0


# ────────────────────────────── 多项目循环（契约 4，M10） ──────────────────────────────


async def test_semantic_multi_project_loops_retrieve(repos):
    """契约 4: project_ids=[p1, p2] → retrieve 每 project_id 调用一次（str(pid)）."""
    p1 = uuid.UUID(int=1000)
    p2 = uuid.UUID(int=2000)
    repos.project_repo.get.side_effect = [_project(p1), _project(p2)]

    resp = await _make_service(repos, vector_store=repos.vector_store).search(
        _query("龙", [p1, p2], mode="semantic")
    )

    assert resp.total == 0
    assert resp.project_ids == [p1, p2]
    assert repos.vector_store.retrieve.await_count == 2
    received = sorted(
        call.kwargs["project_id"] for call in repos.vector_store.retrieve.await_args_list
    )
    assert received == [str(p1), str(p2)]
    repos.search_repo.query.assert_not_awaited()


# ───────────── outline 恒空（契约 5，§5.8 覆盖缺口） ─────────────


async def test_semantic_outline_only_returns_empty(repos):
    """契约 5: types=[outline] → 无向量类型映射 → semantic 恒空（total 0）.

    F14 不索引大纲（§5.8 覆盖缺口）：outline 剔除后 entity_types 为空列表 → retrieve 不被
    调用（或调用但无 outline 结果）→ total 0。本用例只锁结果与「不降级 keyword」，
    不锁 retrieve 是否被调（两种 GREEN 形态皆可，见文件头假设 4）。
    """
    pid = uuid.UUID(int=1000)
    _given_project(repos, pid)

    resp = await _make_service(repos, vector_store=repos.vector_store).search(
        _query("龙", [pid], types=["outline"], mode="semantic")
    )

    assert resp.total == 0
    assert resp.hits == []
    assert resp.mode == "semantic"
    repos.search_repo.query.assert_not_awaited()


# ───────────── types 透传映射（契约 6，§6.3/§5.8） ─────────────


@pytest.mark.parametrize(
    ("query_types", "expected_entity_types"),
    [
        (None, None),
        (["chapter"], [EntityType.CHAPTER_CHUNK]),
        (["chapter", "outline"], [EntityType.CHAPTER_CHUNK]),  # outline 无向量类型 → 剔除
        (
            ["chapter", "character", "world", "timeline", "foreshadowing", "outline"],
            [
                EntityType.CHAPTER_CHUNK,
                EntityType.CHARACTER,
                EntityType.SETTING,
                EntityType.TIMELINE_EVENT,
                EntityType.FORESHADOWING,
            ],
        ),
    ],
)
async def test_semantic_types_passthrough_mapping(repos, query_types, expected_entity_types):
    """契约 6: SearchEntityType 列表 → F14 EntityType 列表；None → None."""
    pid = uuid.UUID(int=1000)
    _given_project(repos, pid)

    await _make_service(repos, vector_store=repos.vector_store).search(
        _query("龙", [pid], types=query_types, mode="semantic")
    )

    _, project_id, entity_types = _retrieve_call(repos)
    assert project_id == str(pid)
    assert entity_types == expected_entity_types


# ────────────────────────────── 空库空结果（契约 7，E5/E12） ──────────────────────────────


async def test_semantic_empty_store_returns_empty(repos):
    """契约 7: retrieve 返回 []（向量库为空）→ 200 空结果 total 0 + mode 回显."""
    pid = uuid.UUID(int=1000)
    _given_project(repos, pid)

    resp = await _make_service(repos, vector_store=repos.vector_store).search(
        _query("龙", [pid], mode="semantic")
    )

    assert resp.total == 0
    assert resp.hits == []
    assert resp.mode == "semantic"
    repos.search_repo.query.assert_not_awaited()


# ────────────────────────────── embedding 异常不降级（契约 8，E12） ──────────────────────────────


async def test_semantic_retrieve_failure_returns_empty_not_keyword(repos):
    """契约 8 (E12): retrieve 抛 RuntimeError（embedding 不可用）→ 200 空结果 + mode 回显.

    不抛错、不降级 keyword（模式显式请求，失败空结果比静默换模式诚实，§5.8）。
    loguru 记录不在此断言（本文件只锁响应契约）。
    """
    pid = uuid.UUID(int=1000)
    _given_project(repos, pid)
    repos.vector_store.retrieve.side_effect = RuntimeError("embedding 不可用")

    resp = await _make_service(repos, vector_store=repos.vector_store).search(
        _query("龙", [pid], mode="semantic")
    )

    assert resp.total == 0
    assert resp.hits == []
    assert resp.mode == "semantic"
    repos.search_repo.query.assert_not_awaited()


# ────────────────────────────── 返回顺序（契约 9，§5.7 不重排） ──────────────────────────────


async def test_semantic_preserves_retrieve_order(repos):
    """契约 9: hits 顺序 = retrieve 返回顺序（semantic 不按 score 重排）.

    0.9 分命中排在中间——若 GREEN 按分数重排，本用例即失败。
    """
    pid = uuid.UUID(int=1000)
    _given_project(repos, pid)
    repos.vector_store.retrieve.return_value = [
        _entity(EntityType.CHARACTER, "2001", "内容甲", 0.5, _named_meta(pid, "甲")),
        _entity(EntityType.SETTING, "2002", "内容乙", 0.9, _named_meta(pid, "乙")),
        _entity(EntityType.CHARACTER, "2003", "内容丙", 0.7, _named_meta(pid, "丙")),
    ]

    resp = await _make_service(repos, vector_store=repos.vector_store).search(
        _query("龙", [pid], mode="semantic")
    )

    assert [h.title for h in resp.hits] == ["甲", "乙", "丙"]
    assert [h.score for h in resp.hits] == [0.5, 0.9, 0.7]


# ══ #277 M3 追加段（2026-08-16）: 检索元数据 fallback（spec §5.6.4）══
# 契约源: specs/f14-extraction-service/spec.md §5.6.4「_map_retrieved 延续
# .get() fallback 约定（旧数据缺键不崩：metadata.get("chapter_x") 等，缺失
# 回退现状展示，QA §P2-1）——任何新代码禁止直接 metadata["chapter_x"]
# 下标访问」+ §13 M12「扩展 test_search_service.py 元数据缺键 .get()
# fallback 用例」。
# RED 期实现已用 .get() → 缺键用例守护 PASS（刻意）；新增键展示用例
# （chapter_x 存在时 title 含位置）在实现补展示前 FAIL。


async def test_semantic_chunk_missing_new_metadata_does_not_crash(repos):
    """旧数据缺新键（chapter_x/y/volume_title/chunk_start/indexed_at）→ 不崩。"""
    pid = uuid.UUID(int=1000)
    _given_project(repos, pid)
    repos.vector_store.retrieve.return_value = [
        _entity(
            EntityType.CHAPTER_CHUNK,
            "3001:0",
            "古井深处，龙瞳睁开。",
            0.9,
            # 旧数据：仅有既有键（chapter_id/chapter_title/project_id），无新键
            {"chapter_id": "3001", "chapter_title": "第 3 章 龙的苏醒", "project_id": str(pid)},
        ),
    ]

    resp = await _make_service(repos, vector_store=repos.vector_store).search(
        _query("龙", [pid], mode="semantic")
    )

    assert resp.total == 1
    assert resp.hits[0].title == "第 3 章 龙的苏醒"  # 回退现状展示
    assert resp.hits[0].entity_id == uuid.UUID(int=3001)


async def test_semantic_chunk_shows_position_when_present(repos):
    """新键存在（chapter_x/chapter_y）→ title 含全书位置展示（Q4 拍板：第 x/y 章）。"""
    pid = uuid.UUID(int=1000)
    _given_project(repos, pid)
    repos.vector_store.retrieve.return_value = [
        _entity(
            EntityType.CHAPTER_CHUNK,
            "3001:0",
            "古井深处，龙瞳睁开。",
            0.9,
            {
                "chapter_id": "3001",
                "chapter_title": "龙的苏醒",
                "project_id": str(pid),
                "chapter_x": 3,
                "chapter_y": 10,
                "volume_title": "第一卷",
                "chunk_start": 0,
                "indexed_at": "2026-08-16T08:00:00+00:00",
            },
        ),
    ]

    resp = await _make_service(repos, vector_store=repos.vector_store).search(
        _query("龙", [pid], mode="semantic")
    )

    assert resp.total == 1
    # MVP 展示位置文本（章节 x/y，Q4 拍板：全书级 chapter_x/chapter_y）
    assert "3" in resp.hits[0].title and "10" in resp.hits[0].title
    assert resp.hits[0].entity_id == uuid.UUID(int=3001)
