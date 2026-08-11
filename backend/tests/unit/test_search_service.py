"""SearchService 编排契约测试（F22 RED，spec §9.2 + M5/M6/M10/M11/M13）.

被测模块 ``inkflow.domain.services.search_service`` 尚未实现（RED 阶段）——
顶部 import 首报 ``No module named 'inkflow.domain.services.search_service'``，
收集期整文件失败（collected 0 items + errors）为预期终态；次要缺失模块
（``inkflow.domain.models.search`` / ``inkflow.domain.ports.search_repository``）
一律在 helper 函数体内惰性 import（核心规则 1c：收集错误只报主契约模块单一缺失）。

================================ 设计假设（docstring 即契约） ================================

1. SearchService 模块路径与构造（deps.py 装配，全部关键字参数）::

       from inkflow.domain.services.search_service import SearchService
       SearchService(
           *, project_repo, chapter_repo, character_repo, world_repo, outline_repo,
           timeline_repo, foreshadowing_repo, search_repo, vector_store=None,
       )

2. 公开方法:

   - ``async def search(self, query: SearchQuery) -> SearchResponse``（spec §5.1 管线）:
     ① 逐 project_id 校验项目（``project_repo.get(pid.int)``，None → ProjectNotFoundError）
     ② ``_ensure_index()``（词法索引就绪，见 3）
     ③ 查询词分词 + MATCH 构造（每词 ``"<词>"`` 引号包裹空格连接，隐式 AND）
     ④ ``search_repo.query(match, project_ids=[p.int ...], types, limit, offset)``
     ⑤ 组装 SearchResponse（total/hits/query/types/mode/project_ids 回显，见 9）
   - ``async def rebuild(self, project_id: int | None = None) -> None``（手动全量重建，
     API/CLI 调用；跳过脏检测）:
     - ``project_id=None``: ``project_repo.list_all()``（分页循环，limit=50 默认）
       枚举全部项目 → 合并收集文档一次重建
     - ``project_id=<int>``: 先 ``project_repo.get(pid)`` 校验（None → ProjectNotFoundError）
     - 流程: ``search_repo.ensure_index()``（幂等建表）→ 收集 6 类文档 →
       ``search_repo.rebuild(documents)``

3. 内部装配缝（GREEN 按此实现，测试以 mock 断言行为）:

   - ``_ensure_index()``: ``search_repo.ensure_index()`` →
     ``search_repo.is_stale(TABLES)`` → 新鲜则返回；否则
     ``get_setting('ai_maintenance') == 'true'`` 时走 ``_incremental_sync()``
     （异常 → loguru + 回退全量重建，E13）；其余走 ``_rebuild()``
   - ``_is_stale()``: 调 ``search_repo.is_stale(TABLES)``；
     TABLES = 6 表名列表（父侧裁定 2026-08-09 签名，修正 spec §8.2 草稿）::

       ["chapters", "characters", "world_settings", "outlines",
        "timeline_events", "foreshadowings"]

   - ``_rebuild()``: 拉取 6 类数据源（分页循环，limit=50 默认），排除软删（见 6），
     每实体一条 SearchDocument，调 ``search_repo.rebuild(documents)``
   - ``_incremental_sync()``: 调 ``search_repo.incremental_sync(documents, deleted)``

4. 数据源 repo 调用形态（全部 AsyncMock 注入，int 主键——仓储层惯例，F9 §8.1）:

   - ``project_repo.get(project_id: int) -> Project | None``（None = 不存在/已软删 → 404）
   - ``project_repo.list_all(search=None, sort_by='updated_at', sort_desc=True,
     offset=0, limit=50) -> (list[Project], int)``
   - ``chapter_repo.list_chapters(project_id, volume_id=None, status=None,
     offset=0, limit=50) -> (list[Chapter], int)``
   - ``character_repo.list(project_id, search=None, group_id=None,
     sort_by='updated_at', sort_desc=True, offset=0, limit=50) -> (list[Character], int)``
   - ``world_repo.list(project_id, ...)`` 同 character 形
   - ``outline_repo.list(project_id, ...)`` 分页 + ``outline_repo.list_points(outline_id: int)
     -> list[PlotPoint]``
   - ``timeline_repo.list_all(project_id: int) -> list[TimelineEvent]``
   - ``foreshadowing_repo.list(project_id, ...)`` 分页
   - ``search_repo``（SearchRepositoryProtocol，spec §8.2 父侧裁定签名）::

       async def ensure_index(self) -> None
       async def is_stale(self, tables: list[str]) -> bool   # 表名列表，实现内部查
           # 各表 max(updated_at) 与 search_meta.last_rebuilt_at 比较
       async def rebuild(self, documents: Iterable[SearchDocument]) -> None
       async def incremental_sync(self, documents: Iterable[SearchDocument],
                                  deleted: Iterable[tuple[str, int]]) -> None
       async def query(self, match: str, project_ids: list[int],
                       types: list[str] | None, limit: int, offset: int)
                       -> tuple[int, list[SearchHit]]
       async def get_setting(self, key: str) -> str | None
       async def set_setting(self, key: str, value: str) -> None

   - ``vector_store``（可选，semantic 模式，F14 既有端口）::

       async def retrieve(self, query: str, *, project_id: str,
                          entity_types: list[EntityType] | None = None,
                          top_k: int = 10, min_score: float = 0.0)
                          -> list[RetrievedEntity]
       # project_id 传 str(项目 UUID)（F14 惯例：IndexableEntity.project_id = str(pid)）

5. SearchDocument（``inkflow.domain.ports.search_repository``，dataclass）:

   - ``entity_type: str``（'chapter'/'character'/... 枚举 .value）
   - ``entity_id: int``（实体 UUID 的 ``uuid.int``——陷阱 18：SQLite 存 int，跨实体引用一致）
   - ``project_id: int``（项目 int 主键）
   - ``title: str``（spec §6.1: chapter.title / character.name / setting.name /
     outline.name / event.title / foreshadowing.title）
   - ``body: str``（jieba 分词后空格连接文本，非空）

6. 软删排除（M6，spec §6.2）: 收集文档时对实体做 is_deleted 过滤
   （``getattr(entity, 'is_deleted', False)``——Chapter 领域模型无该字段，视为未删除）

7. semantic 模式（spec §5.8，vector_store 注入时）:

   - 对每个 project_id **循环**调用 ``vector_store.retrieve(q, project_id=str(pid))``
     （retrieve 签名只有单 project_id，多项目 = 多次调用）
   - 映射表: CHAPTER_CHUNK→chapter / CHARACTER→character / SETTING→world /
     TIMELINE_EVENT→timeline / FORESHADOWING→foreshadowing（outline 无向量类型，恒空）
   - SearchHit 组装: ``entity_id = uuid.UUID(RetrievedEntity.entity_id)``；
     ``project_id = uuid.UUID(metadata['project_id'])``（缺省回退本轮查询 pid）；
     ``title = metadata['name']``（缺省 content 前 40 字符）；
     ``snippet = content[:200]``（无词级高亮，§5.4）；``score = relevance_score``
   - types 透传: SearchEntityType 列表 → 映射为 F14 EntityType 列表（无映射类型剔除，
     如 outline）；None → None
   - retrieve 抛异常 → 200 空结果 + mode 回显，不降级 keyword（E12）

8. 错误类: ``ProjectNotFoundError`` import 自 ``inkflow.domain.ports.character_errors``
   （陷阱 16：不导出到 ports/__init__.py，直接 import 错误模块）

9. 关键字模式组装（§2.2 SearchResponse）: total = 词法 total；hits = 词法 hits；
   query/types/mode/project_ids 回显 SearchQuery 原值（types 回显 SearchEntityType 列表）

RED 预期: collected 0 items + 1 error（No module named
'inkflow.domain.services.search_service'）——预期 RED；其他错误 = 测试文件自身缺陷。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.chapter import Chapter, ChapterStatus
from inkflow.domain.models.character import Character
from inkflow.domain.models.foreshadowing import Foreshadowing
from inkflow.domain.models.outline import Outline, PlotPoint
from inkflow.domain.models.project import Project
from inkflow.domain.models.timeline import TimelineEvent
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.ports.vector_store import EntityType, RetrievedEntity
from inkflow.domain.services.search_service import SearchService

_NOW = datetime.now(UTC)

TABLES = [
    "chapters",
    "characters",
    "world_settings",
    "outlines",
    "timeline_events",
    "foreshadowings",
]


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


def _hits(pid: uuid.UUID, count: int = 1) -> list:
    """构造词法命中 SearchHit（惰性 import models.search）."""
    from inkflow.domain.models.search import SearchEntityType, SearchHit

    return [
        SearchHit(
            entity_type=SearchEntityType.CHAPTER,
            entity_id=uuid.UUID(int=1001 + i),
            project_id=pid,
            title=f"第 {i + 1} 章 龙",
            snippet="古井深处，<mark>龙</mark>瞳睁开。",
            score=3.2 - i,
        )
        for i in range(count)
    ]


def _rebuild_docs(repos) -> list:
    """解包 search_repo.rebuild 最近一次调用的文档列表（兼容位置/关键字传参）."""
    from inkflow.domain.ports.search_repository import SearchDocument

    call = repos.search_repo.rebuild.await_args
    docs = call.args[0] if call.args else call.kwargs.get("documents")
    docs = list(docs)
    assert all(isinstance(d, SearchDocument) for d in docs)
    return docs


def _query_call(repos) -> tuple:
    """解包 search_repo.query 最近一次调用（兼容位置/关键字两种 GREEN 形态）."""
    call = repos.search_repo.query.await_args
    args = call.args
    kwargs = call.kwargs
    return (
        args[0] if len(args) > 0 else kwargs.get("match"),
        args[1] if len(args) > 1 else kwargs.get("project_ids"),
        args[2] if len(args) > 2 else kwargs.get("types"),
        args[3] if len(args) > 3 else kwargs.get("limit", 20),
        args[4] if len(args) > 4 else kwargs.get("offset", 0),
    )


def _stale_tables(repos) -> list:
    """解包 search_repo.is_stale 最近一次调用的表名列表."""
    call = repos.search_repo.is_stale.await_args
    return call.args[0] if call.args else call.kwargs.get("tables")


# ────────────────────────────── 领域实体工厂 ──────────────────────────────


def _project(pid: uuid.UUID, name: str = "测试项目") -> Project:
    return Project(id=pid, name=name, created_at=_NOW, updated_at=_NOW)


def _character(pid: uuid.UUID, cid: uuid.UUID, name: str, is_deleted: bool = False) -> Character:
    return Character(
        id=cid,
        project_id=pid,
        name=name,
        personality="冷静",
        is_deleted=is_deleted,
        created_at=_NOW,
        updated_at=_NOW,
    )


# ────────────────────────────── fixtures ──────────────────────────────


@pytest.fixture
def repos():
    """全 mock 数据源 + search_repo 装配缝（spec §5.1 编排；默认空数据 + 索引新鲜）."""
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
    r.chapter_repo.list_chapters.return_value = ([], 0)
    r.character_repo.list.return_value = ([], 0)
    r.world_repo.list.return_value = ([], 0)
    r.outline_repo.list.return_value = ([], 0)
    r.timeline_repo.list_all.return_value = []
    r.foreshadowing_repo.list.return_value = ([], 0)
    r.search_repo.is_stale.return_value = False
    r.search_repo.get_setting.return_value = None
    r.search_repo.query.return_value = (0, [])
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


def _given_project(repos, pid: uuid.UUID, name: str = "测试项目") -> Project:
    """让 project_repo.get 返回指定项目（单项目场景默认形态）."""
    proj = _project(pid, name)
    repos.project_repo.get.return_value = proj
    return proj


# ────────────────────────────── 项目校验（E1） ──────────────────────────────


async def test_project_missing_raises_project_not_found(repos):
    """E1: project_repo.get → None（不存在/已软删）→ ProjectNotFoundError（404）."""
    repos.project_repo.get.return_value = None

    with pytest.raises(ProjectNotFoundError):
        await _make_service(repos).search(_query("龙", [uuid.UUID(int=1000)]))

    repos.search_repo.query.assert_not_awaited()
    repos.search_repo.ensure_index.assert_not_awaited()


# ────────────────────────────── 索引就绪与重建（E4/M5） ──────────────────────────────


async def test_first_search_rebuilds_all_sources_then_queries(repos):
    """E4: 首次搜索（is_stale True）→ 6 类数据源全量收集 → rebuild → query."""
    pid = uuid.UUID(int=1000)
    _given_project(repos, pid)
    chapter = Chapter(
        id=uuid.UUID(int=1001),
        project_id=pid,
        title="第 1 章 龙",
        content="古井深处，龙瞳睁开。它沉睡千年",
        status=ChapterStatus.FINAL,
    )
    character = _character(pid, uuid.UUID(int=1002), "龙女")
    world = WorldSetting(
        id=uuid.UUID(int=1003),
        project_id=pid,
        name="龙族领地",
        content="北境荒原，终年冰雪",
        created_at=_NOW,
        updated_at=_NOW,
    )
    outline = Outline(
        id=uuid.UUID(int=1004),
        project_id=pid,
        name="主线大纲",
        description="龙族崛起",
        created_at=_NOW,
        updated_at=_NOW,
    )
    point = PlotPoint(
        id=uuid.UUID(int=1005),
        outline_id=outline.id,
        project_id=pid,
        name="龙的苏醒",
        description="古井深处传来龙吟",
        created_at=_NOW,
        updated_at=_NOW,
    )
    event = TimelineEvent(
        id=uuid.UUID(int=1006),
        project_id=pid,
        title="龙苏醒之日",
        description="古井深处传来龙吟",
        created_at=_NOW,
        updated_at=_NOW,
    )
    foreshadowing = Foreshadowing(
        id=uuid.UUID(int=1007),
        project_id=pid,
        title="千年沉睡",
        description="龙瞳睁开",
        location="古井",
        created_at=_NOW,
        updated_at=_NOW,
    )
    repos.chapter_repo.list_chapters.return_value = ([chapter], 1)
    repos.character_repo.list.return_value = ([character], 1)
    repos.world_repo.list.return_value = ([world], 1)
    repos.outline_repo.list.return_value = ([outline], 1)
    repos.outline_repo.list_points.return_value = [point]
    repos.timeline_repo.list_all.return_value = [event]
    repos.foreshadowing_repo.list.return_value = ([foreshadowing], 1)
    repos.search_repo.is_stale.return_value = True
    repos.search_repo.query.return_value = (1, _hits(pid))

    resp = await _make_service(repos).search(_query("龙", [pid]))

    repos.search_repo.ensure_index.assert_awaited_once()
    assert set(_stale_tables(repos)) == set(TABLES)
    repos.search_repo.rebuild.assert_awaited_once()
    docs = _rebuild_docs(repos)
    assert len(docs) == 6
    assert {d.entity_type for d in docs} == {
        "chapter",
        "character",
        "world",
        "outline",
        "timeline",
        "foreshadowing",
    }
    chapter_doc = next(d for d in docs if d.entity_type == "chapter")
    assert chapter_doc.entity_id == chapter.id.int
    assert chapter_doc.project_id == pid.int
    assert chapter_doc.title == "第 1 章 龙"
    assert isinstance(chapter_doc.body, str) and chapter_doc.body
    repos.outline_repo.list_points.assert_awaited_once_with(outline.id.int)
    match, pids, types, limit, _ = _query_call(repos)
    assert '"龙"' in match
    assert pids == [pid.int]
    assert types is None
    assert limit == 20
    assert resp.total == 1


async def test_fresh_index_skips_rebuild(repos):
    """M5: 索引新鲜（is_stale False）→ 不重建、不增量，直接 query."""
    pid = uuid.UUID(int=1000)
    _given_project(repos, pid)

    resp = await _make_service(repos).search(_query("龙", [pid]))

    assert resp.total == 0
    repos.search_repo.rebuild.assert_not_awaited()
    repos.search_repo.incremental_sync.assert_not_awaited()
    repos.search_repo.query.assert_awaited_once()


async def test_soft_deleted_entity_excluded_from_documents(repos):
    """M6: 软删实体（is_deleted=True）不进索引文档（spec §6.2）."""
    pid = uuid.UUID(int=1000)
    _given_project(repos, pid)
    active = _character(pid, uuid.UUID(int=1002), "龙女")
    deleted = _character(pid, uuid.UUID(int=1008), "旧角色", is_deleted=True)
    repos.character_repo.list.return_value = ([active, deleted], 2)
    repos.search_repo.is_stale.return_value = True

    await _make_service(repos).search(_query("龙", [pid]))

    docs = _rebuild_docs(repos)
    assert len(docs) == 1
    assert docs[0].entity_id == active.id.int
    assert deleted.id.int not in [d.entity_id for d in docs]


# ────────────────────────────── 多项目（M10/E1） ──────────────────────────────


async def test_multi_project_query_receives_all_project_ids(repos):
    """M10: project_ids 数组 → query 收到全部项目 int id；响应回显 UUID 集合."""
    p1 = uuid.UUID(int=1000)
    p2 = uuid.UUID(int=2000)
    repos.project_repo.get.side_effect = [_project(p1), _project(p2)]

    resp = await _make_service(repos).search(_query("龙", [p1, p2]))

    _, pids, _, _, _ = _query_call(repos)
    assert pids == [p1.int, p2.int]
    assert resp.project_ids == [p1, p2]


async def test_multi_project_one_missing_raises(repos):
    """E1: 多项目其一不存在 → ProjectNotFoundError（404），query 不执行."""
    p1 = uuid.UUID(int=1000)
    p2 = uuid.UUID(int=2000)
    repos.project_repo.get.side_effect = [_project(p1), None]

    with pytest.raises(ProjectNotFoundError):
        await _make_service(repos).search(_query("龙", [p1, p2]))

    repos.search_repo.query.assert_not_awaited()


# ────────────────────────────── types 透传（§6.3） ──────────────────────────────


@pytest.mark.parametrize(
    ("query_types", "expected_types"),
    [
        (None, None),
        (["chapter"], ["chapter"]),
        (["chapter", "world"], ["chapter", "world"]),
    ],
)
async def test_types_passthrough(repos, query_types, expected_types):
    """§6.3: types 透传（None → None；列表 → 枚举 .value 字符串列表）."""
    pid = uuid.UUID(int=1000)
    _given_project(repos, pid)

    await _make_service(repos).search(_query("龙", [pid], types=query_types))

    _, _, types, _, _ = _query_call(repos)
    assert types == expected_types


# ────────────────────────────── 手动 rebuild（M13） ──────────────────────────────


async def test_manual_rebuild_all_projects(repos):
    """M13: rebuild() 全量——跳过脏检测，list_all 枚举项目，合并重建全部项目文档."""
    p1 = uuid.UUID(int=1000)
    p2 = uuid.UUID(int=2000)
    repos.project_repo.list_all.return_value = ([_project(p1, "书一"), _project(p2, "书二")], 2)
    repos.character_repo.list.side_effect = [
        ([_character(p1, uuid.UUID(int=1002), "龙女")], 1),
        ([_character(p2, uuid.UUID(int=2002), "剑客")], 1),
    ]

    await _make_service(repos).rebuild()

    repos.project_repo.list_all.assert_awaited_once()
    repos.search_repo.ensure_index.assert_awaited_once()
    repos.search_repo.rebuild.assert_awaited_once()
    docs = _rebuild_docs(repos)
    assert {d.project_id for d in docs} == {p1.int, p2.int}
    repos.search_repo.is_stale.assert_not_awaited()
    repos.search_repo.get_setting.assert_not_awaited()


async def test_manual_rebuild_single_project_validates(repos):
    """M13: rebuild(123) 单项目——先校验项目存在，再重建该项目文档."""
    pid = uuid.UUID(int=1000)
    _given_project(repos, pid)
    repos.character_repo.list.return_value = ([_character(pid, uuid.UUID(int=1002), "龙女")], 1)

    await _make_service(repos).rebuild(pid.int)

    repos.project_repo.get.assert_awaited_once_with(pid.int)
    repos.search_repo.ensure_index.assert_awaited_once()
    repos.search_repo.rebuild.assert_awaited_once()
    docs = _rebuild_docs(repos)
    assert docs and all(d.project_id == pid.int for d in docs)
    repos.search_repo.is_stale.assert_not_awaited()


async def test_manual_rebuild_missing_project_raises(repos):
    """E1: rebuild 传不存在项目 → ProjectNotFoundError，不重建."""
    repos.project_repo.get.return_value = None

    with pytest.raises(ProjectNotFoundError):
        await _make_service(repos).rebuild(999)

    repos.search_repo.rebuild.assert_not_awaited()


# ────────────────────────────── AI 增量维护（M11/E13） ──────────────────────────────


async def test_ai_maintenance_enabled_uses_incremental_sync(repos):
    """M11: ai_maintenance='true' + 脏 → incremental_sync（不触发全量重建）."""
    pid = uuid.UUID(int=1000)
    _given_project(repos, pid)
    repos.search_repo.is_stale.return_value = True
    repos.search_repo.get_setting.return_value = "true"

    await _make_service(repos).search(_query("龙", [pid]))

    repos.search_repo.incremental_sync.assert_awaited_once()
    repos.search_repo.rebuild.assert_not_awaited()


async def test_incremental_sync_failure_falls_back_to_rebuild(repos):
    """E13: 增量失败 → 回退懒重建，搜索不抛错（下次判脏全量兜底）."""
    pid = uuid.UUID(int=1000)
    _given_project(repos, pid)
    repos.search_repo.is_stale.return_value = True
    repos.search_repo.get_setting.return_value = "true"
    repos.search_repo.incremental_sync.side_effect = RuntimeError("增量同步失败")

    resp = await _make_service(repos).search(_query("龙", [pid]))

    assert resp.total == 0
    repos.search_repo.rebuild.assert_awaited_once()


# ────────────────────────────── keyword 结果组装（§2.2） ──────────────────────────────


async def test_keyword_response_echoes_query(repos):
    """§2.2: SearchResponse 回显 query/types/mode/project_ids 原值（M1 组装）."""
    from inkflow.domain.models.search import SearchResponse

    pid = uuid.UUID(int=1000)
    _given_project(repos, pid)
    hits = _hits(pid, count=3)
    repos.search_repo.query.return_value = (3, hits)
    query = _query("龙", [pid], types=["chapter"], limit=5)

    resp = await _make_service(repos).search(query)

    assert resp == SearchResponse(
        total=3,
        hits=hits,
        query="龙",
        types=query.types,
        mode=query.mode,
        project_ids=[pid],
    )


# ────────────────────────────── semantic 模式（§5.8/E12） ──────────────────────────────


@pytest.mark.parametrize(
    ("vector_type", "expected_entity_type"),
    [
        (EntityType.CHAPTER_CHUNK, "chapter"),
        (EntityType.CHARACTER, "character"),
        (EntityType.SETTING, "world"),
        (EntityType.TIMELINE_EVENT, "timeline"),
        (EntityType.FORESHADOWING, "foreshadowing"),
    ],
)
async def test_semantic_mode_maps_vector_types(repos, vector_type, expected_entity_type):
    """§5.8 映射表: F14 EntityType → SearchEntityType（outline 无向量类型恒空）."""
    pid = uuid.UUID(int=1000)
    _given_project(repos, pid)
    repos.vector_store.retrieve.return_value = [
        RetrievedEntity(
            entity_id="1001",
            entity_type=vector_type,
            content="古井深处，龙瞳睁开。",
            relevance_score=0.9,
            metadata={"project_id": str(pid), "name": "龙的苏醒"},
        )
    ]

    resp = await _make_service(repos, vector_store=repos.vector_store).search(
        _query("龙", [pid], mode="semantic")
    )

    assert resp.total == 1
    assert resp.hits[0].entity_type == expected_entity_type
    repos.search_repo.query.assert_not_awaited()


async def test_semantic_hit_fields_mapped(repos):
    """§5.8: entity_id/project_id/title/snippet/score 从 RetrievedEntity 映射."""
    pid = uuid.UUID(int=1000)
    _given_project(repos, pid)
    repos.vector_store.retrieve.return_value = [
        RetrievedEntity(
            entity_id="1001",
            entity_type=EntityType.CHAPTER_CHUNK,
            content="古井深处，龙瞳睁开。它沉睡千年，龙息如雷。",
            relevance_score=0.92,
            metadata={"project_id": str(pid), "name": "第 3 章 龙的苏醒"},
        )
    ]

    resp = await _make_service(repos, vector_store=repos.vector_store).search(
        _query("龙", [pid], mode="semantic")
    )

    hit = resp.hits[0]
    assert hit.entity_id == uuid.UUID(int=1001)
    assert hit.project_id == pid
    assert hit.title == "第 3 章 龙的苏醒"
    assert hit.snippet == "古井深处，龙瞳睁开。它沉睡千年，龙息如雷。"  # content[:200]
    assert hit.score == 0.92
    assert resp.mode == "semantic"


async def test_semantic_types_mapped_to_vector_types(repos):
    """§6.3: semantic 模式 types → F14 EntityType 列表（无映射类型 outline 剔除）."""
    pid = uuid.UUID(int=1000)
    _given_project(repos, pid)
    repos.vector_store.retrieve.return_value = []

    await _make_service(repos, vector_store=repos.vector_store).search(
        _query("龙", [pid], types=["chapter", "outline"], mode="semantic")
    )

    call = repos.vector_store.retrieve.await_args
    assert call.kwargs.get("entity_types") == [EntityType.CHAPTER_CHUNK]


async def test_semantic_multi_project_loops_retrieve(repos):
    """M10: semantic 多项目 = 对每个 project_id 循环调用 retrieve（签名只有单 project_id）."""
    p1 = uuid.UUID(int=1000)
    p2 = uuid.UUID(int=2000)
    repos.project_repo.get.side_effect = [_project(p1), _project(p2)]
    repos.vector_store.retrieve.return_value = []

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


async def test_semantic_retrieve_failure_returns_empty_not_keyword(repos):
    """E12: embedding 不可用 → 200 空结果 + mode 回显，不降级 keyword、不抛错."""
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


class TestSearchServiceAssembly:
    """#264 装配契约：get_search_service 必须注入 vector_store（非 None——semantic 模式真实可用）。

    rc7 实测：deps.get_search_service 硬编码 vector_store=None → search semantic 恒空
    （同内核 /vector/retrieve 命中）。契约：get_search_service 为 async（Depends 支持），
    注入的 vector_store 来自 get_vector_store（可选——未配置 embedding 时 None 兜底）。
    """

    @pytest.fixture
    async def db_session(self):
        """独立 in-memory SQLite（unit 层无全局 db_session——模块级自建惯例）。"""
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            yield session
        await engine.dispose()

    async def test_get_search_service_injects_vector_store(self, db_session, monkeypatch):
        """装配：get_search_service 返回的实例 vector_store 非 None（mock get_vector_store）。"""
        from inkflow.api.deps import get_search_service

        marker = object()

        async def _fake_get_vector_store():
            return marker

        monkeypatch.setattr("inkflow.api.deps.get_vector_store", _fake_get_vector_store)
        svc = await get_search_service(db_session)
        assert svc._vector_store is marker, "vector_store 未注入（#264）"
