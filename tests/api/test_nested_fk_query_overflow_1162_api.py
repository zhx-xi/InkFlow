"""#1162 嵌套 FK / 查询参数 UUID 溢出族 RED 契约测试 — 真实 DB 轨。

姊妹文件：
- test_error_semantics_family_api.py（#1139/#1138：路径参数过滤型 + create_ 孤儿行）
- test_uuid_path_param_overflow_api.py（#1106：主键查询路径）

本文件补齐第三类形态：**非路径参数**的 128 位 UUID —— 过滤用查询参数
（query param）与嵌套 FK 值。7 个实测受损端点（父侧 ASGI 探针实测，2026-09-14）：

  ① GET /api/v1/projects/{pid}/chapters?volume_id=<uuid>        500（service
     chapter_service.list_chapters:205-219 `_to_int` 无守卫 → repo.list_chapters:189
     把 128 位 int 绑进 WHERE → SQLite OverflowError）
  ② GET /api/v1/projects/{pid}/characters?group_id=<uuid>       500（character_service
     .list_characters:194-217 同形 → character_repo.list）
  ③ GET /api/v1/projects/{pid}/maps?root_location_id=<uuid>     500（map_service
     .list_maps:210-238 同形 → map_repo.list；注意 map_repo 只有 get/list_pins/
     get_pin/children 有守卫，list 的 root_location_id 无守卫）
  ④ GET /api/v1/projects/{pid}/world-settings?parent_id=<uuid>  500（world_service
     .list_settings:207-245 同形 → world_repo.list:184-185 绑 parent_id；
     注意 world_repo.list:170-171 已有 **project_id** 守卫 #1139，parent_id 漏了）
  ⑤ GET /api/v1/sessions?project_id=<uuid>                      500({"detail":"数据库错误"})
     （session_service.list:175-210 `_to_int_id(project_id)` 透传 → session_repo.list
     绑 project_id；SessionORM.project_id 是 INTEGER 列）
  ⑥ GET /api/v1/chat/messages?conversation_id=<uuid>            500（chat_message_service
     .list_messages_by_conversation:97-114 无守卫 → chat_message_repo
     .list_by_conversation:141 `conversation_id.int` 绑进 WHERE；ChatMessageORM
     .conversation_id 是 INTEGER 列。注：同 service 已有 `_is_random_overflow`
     :22-30 辅助，但只用在 delete/archive/restore 族，list 漏了）
  ⑦ POST /api/v1/chapters/{ch_id}/move?target_volume_id=<uuid>  500（chapter_service
     .move_chapter:339-347 无守卫 → chapter_repo.move_chapter 直接 UPDATE）；
     **并发现同族新缺陷**：范围内不存在的 target（UUID(int=987654321)）→ 200 且
     volume_id 被盲写成孤儿值（同 service delete_volume:138-146 的 move_to
     先例已有「先校验目标卷存在」语义，move_chapter 未对齐）——实测见下。

实测语义契约（父侧定稿，写进本文件即契约）：

面 ①-④（过滤型，project 为路径父资源、FK 为过滤条件）：
- 合法存活 project + 溢出 uuid → 200 + {items: [], total: 0}（不得 500）
- 反例守护 A：范围内不存在的 uuid（UUID(int=987654321)）→ 200 空（既有行为，守卫不得误伤）
- 反例守护 B：真实存在的 FK → 200 且只返回匹配行（过滤功能不得被守卫修坏）

面 ⑤（sessions?project_id）：project 是**过滤条件**而非路径父资源 → 同过滤型，200 空列表。

面 ⑥（chat/messages?conversation_id）：溢出 → 200 + 空列表。**不引入 404**——
chat_message_service 对 conversation 不存在本就无 404 语义（list_messages_by_conversation
是 repo 位置透传，不校验父实体存在性），故按「线程不存在 → 无消息可读 → 200 空」。
范围内不存在的 uuid 仍走正常查询路径（不得被守卫误伤）。

面 ⑦（move?target_volume_id）：目标卷必须真实存在 → 否则 422 且**原 chapter 的
volume_id 不被修改**（DB 真相断言）。溢出与范围内不存在都归 422（对齐同文件
delete_volume(move_to) 先例 chapter_service.delete_volume:138-146 = 校验目标卷存在
→ VolumeMoveError → router 转 422）。真实存在的目标卷 → 200 且移动生效。

**未纳入本文件（留给在途 issue #1151/#1163）**：路径 project_id 自身溢出
（如 GET /projects/{uuid4}/chapters）当前实测仍非 404（chapters/characters/maps → 500、
world-settings → 200 空），该行为尚不存在于主干，故不在此锁死，避免与并行工作冲突。

测试形态：真实 DB 轨（client + db_session + override_get_db + sample_project），
不 patch service / repo —— 真实 service 走 128 位 int 绑定路径（镜像姊妹文件）。

守卫落点（写测试时实测依据，落点由实现方判定，本文件不断言层）：
既有同族守卫（#1106/#1139）**全部落在 repo 层**，见 map_repo.py:142/245/263/308 与
world_repo.py:114/170-171。service 层加守卫会破坏既有透传单测（实测证据见交付报告：
backend/tests/unit/domain/services/test_map_service.py:703-717 断言
`kwargs["root_location_id"] == root.int`，其中 `root = uuid.uuid4()` 即溢出值）。
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from inkflow.api.app import app
from inkflow.infrastructure.database.models.chapter import ChapterORM

pytestmark = pytest.mark.asyncio  # F27 实测必写（asyncio_mode=auto 双保险）

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量：本文件全部用例依赖未设置 → 直通（无 token 模式）。"""


@pytest_asyncio.fixture
async def client(monkeypatch):
    """ASGI 测试客户端（函数级，无 token 模式 + 不重抛异常以便断言 500）。"""
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _overflow_uuid() -> uuid.UUID:
    """随机 uuid4（128 位，必 > int64 上限 → 必不存在于任何表）。"""
    value = uuid.uuid4()
    assert value.int >= 2**63, "前提：uuid4 必然超出 SQLite 64 位 INTEGER 范围"
    return value


def _in_range_absent_uuid() -> uuid.UUID:
    """int64 范围内但不存在的 uuid（守卫不得误伤的正常查询路径）。"""
    return uuid.UUID(int=987654321)


def _project_uuid(sample_project) -> uuid.UUID:
    """sample_project 是 ProjectORM（int 主键）；需要 UUID 形状的 body 字段时转换。"""
    return uuid.UUID(int=sample_project.id)


def _assert_empty_page(resp, url: str) -> None:
    """契约：200 + 空列表（不得 500，不得误报 404）。"""
    assert resp.status_code == 200, (
        f"GET {url} 应为 200 + 空列表，实际 {resp.status_code}: {resp.text[:200]}"
    )
    body = resp.json()
    assert body["items"] == [], f"GET {url} items 应为空，实际 {body['items']!r}"
    assert body["total"] == 0, f"GET {url} total 应为 0，实际 {body['total']!r}"


# ── 面 ①-④：过滤用查询参数溢出 ────────────────────────────────────────

FILTER_QUERY_FACES = [
    # (用例标签, url 模板, 过滤参数名)
    ("chapters_volume_id", "/api/v1/projects/{pid}/chapters", "volume_id"),
    ("characters_group_id", "/api/v1/projects/{pid}/characters", "group_id"),
    ("maps_root_location_id", "/api/v1/projects/{pid}/maps", "root_location_id"),
    ("world_settings_parent_id", "/api/v1/projects/{pid}/world-settings", "parent_id"),
]
"""#1162 面 ①-④：FK 作为过滤条件的查询参数（溢出 → 500）。"""


@pytest.mark.api
@pytest.mark.parametrize("label,url_template,param", FILTER_QUERY_FACES, ids=lambda v: str(v))
class TestFilterQueryParamOverflow:
    """#1162 面 ①-④ 逐面：过滤用查询参数溢出 → 200 空列表（不得 500）。

    修复前：真实 DB 轨把 128 位 int 绑进 WHERE → OverflowError → 500 → FAIL。
    url 模板与参数名成对参数化，避免「端点与参数错配」造成假通过。
    """

    async def test_overflow_uuid_returns_200_empty(
        self,
        client,
        db_session,
        override_get_db,
        sample_project,
        label,
        url_template,
        param,
    ):
        """溢出 uuid（随机 uuid4）→ 200 + {items: [], total: 0}（不得 500）。"""
        url = f"{url_template.format(pid=sample_project.id)}?{param}={_overflow_uuid()}"
        _assert_empty_page(await client.get(url), url)

    async def test_in_range_absent_uuid_returns_200_empty(
        self,
        client,
        db_session,
        override_get_db,
        sample_project,
        label,
        url_template,
        param,
    ):
        """反例守护 A：int64 范围内但不存在的 uuid → 200 空（守卫不得误伤）。"""
        url = f"{url_template.format(pid=sample_project.id)}?{param}={_in_range_absent_uuid()}"
        _assert_empty_page(await client.get(url), url)


# ── 反例守护 B：真实 FK 时过滤功能仍生效（不得被守卫修坏）─────────────


@pytest.mark.api
class TestFilterStillWorksWithRealFk:
    """#1162 反例守护 B：真实存在的 FK → 200 且只返回匹配行。"""

    async def test_chapters_filter_by_real_volume_id(
        self, client, db_session, override_get_db, sample_project
    ):
        """真实卷 + 该卷下 1 章 → ?volume_id= 只返回该章（过滤功能不得修坏）。"""
        pid = sample_project.id
        vol = await client.post(f"/api/v1/projects/{pid}/volumes", json={"title": "过滤卷"})
        assert vol.status_code == 201, vol.text[:200]
        vol_id = vol.json()["id"]
        ch = await client.post(
            f"/api/v1/projects/{pid}/chapters",
            json={"title": "被过滤章", "volume_id": vol_id},
        )
        assert ch.status_code == 201, ch.text[:200]
        ch_id = ch.json()["id"]

        resp = await client.get(f"/api/v1/projects/{pid}/chapters?volume_id={vol_id}")
        assert resp.status_code == 200, resp.text[:200]
        body = resp.json()
        assert body["total"] == 1, f"应只命中 1 章，实际 {body['total']}"
        assert [c["id"] for c in body["items"]] == [ch_id]

    async def test_characters_filter_by_real_group_id(
        self, client, db_session, override_get_db, sample_project
    ):
        """真实分组 + 组内 1 角色 → ?group_id= 只返回该角色。"""
        pid = sample_project.id
        grp = await client.post(
            f"/api/v1/projects/{pid}/character-groups",
            json={"name": "过滤组", "description": "", "sort_order": 0},
        )
        assert grp.status_code == 201, grp.text[:200]
        grp_id = grp.json()["id"]
        ch = await client.post(
            f"/api/v1/projects/{pid}/characters",
            json={
                "name": "组内角色",
                "group_ids": [grp_id],
                "extra": {"role_rank": "protagonist"},
            },
        )
        assert ch.status_code == 201, ch.text[:200]
        ch_id = ch.json()["id"]

        resp = await client.get(f"/api/v1/projects/{pid}/characters?group_id={grp_id}")
        assert resp.status_code == 200, resp.text[:200]
        body = resp.json()
        assert body["total"] == 1, f"应只命中 1 角色，实际 {body['total']}"
        assert [c["id"] for c in body["items"]] == [ch_id]

    async def test_maps_filter_by_real_root_location_id(
        self, client, db_session, override_get_db, sample_project
    ):
        """真实根地点 + 挂该地点的 1 图 → ?root_location_id= 只返回该图。"""
        pid = sample_project.id
        loc = await client.post(
            f"/api/v1/projects/{pid}/world-settings",
            json={"name": "过滤地点", "category": "", "content": ""},
        )
        assert loc.status_code == 201, loc.text[:200]
        loc_id = loc.json()["id"]
        mp = await client.post(
            f"/api/v1/projects/{pid}/maps",
            data={"name": "过滤图", "description": "", "root_location_id": loc_id},
            files={"file": ("main.png", b"\x89PNG\r\n\x1a\n")},
        )
        assert mp.status_code == 201, mp.text[:200]
        map_id = mp.json()["id"]

        resp = await client.get(f"/api/v1/projects/{pid}/maps?root_location_id={loc_id}")
        assert resp.status_code == 200, resp.text[:200]
        body = resp.json()
        assert body["total"] == 1, f"应只命中 1 图，实际 {body['total']}"
        assert [m["id"] for m in body["items"]] == [map_id]

    async def test_world_settings_filter_by_real_parent_id(
        self, client, db_session, override_get_db, sample_project
    ):
        """真实父条目 + 子条目 → ?parent_id= 只返回该子条目。"""
        pid = sample_project.id
        root = await client.post(
            f"/api/v1/projects/{pid}/world-settings",
            json={"name": "层根", "category": "", "content": ""},
        )
        assert root.status_code == 201, root.text[:200]
        root_id = root.json()["id"]
        # #1321：非根条目须带已存在的分类 → 先建分类（本用例意图是验 parent_id 过滤，非分类）
        cat = await client.post(
            f"/api/v1/projects/{pid}/world-categories",
            json={"name": "地理"},
        )
        assert cat.status_code == 201, cat.text[:200]
        child = await client.post(
            f"/api/v1/projects/{pid}/world-settings",
            json={"name": "层子", "category": "地理", "content": "", "parent_id": root_id},
        )
        assert child.status_code == 201, child.text[:200]
        child_id = child.json()["id"]

        resp = await client.get(f"/api/v1/projects/{pid}/world-settings?parent_id={root_id}")
        assert resp.status_code == 200, resp.text[:200]
        body = resp.json()
        assert body["total"] == 1, f"应只命中 1 条目，实际 {body['total']}"
        assert [s["id"] for s in body["items"]] == [child_id]


# ── 面 ⑤：GET /sessions?project_id ────────────────────────────────────


@pytest.mark.api
class TestSessionsProjectIdQueryOverflow:
    """#1162 面 ⑤：sessions 的 project_id 是**过滤条件**（非路径父资源）→ 200 空。"""

    async def test_overflow_uuid_returns_200_empty(self, client, db_session, override_get_db):
        """溢出 project_id → 200 + 空列表（修复前 500 {"detail":"数据库错误"}）。"""
        url = f"/api/v1/sessions?project_id={_overflow_uuid()}"
        _assert_empty_page(await client.get(url), url)

    async def test_in_range_absent_uuid_returns_200_empty(
        self, client, db_session, override_get_db
    ):
        """反例守护 A：范围内不存在的 project_id → 200 空（守卫不得误伤）。"""
        url = f"/api/v1/sessions?project_id={_in_range_absent_uuid()}"
        _assert_empty_page(await client.get(url), url)

    async def test_real_project_filter_still_works(
        self, client, db_session, override_get_db, sample_project
    ):
        """反例守护 B：真实 project 的会话可被滤出（过滤功能不得修坏）。"""
        created = await client.post(
            "/api/v1/sessions",
            json={
                "session_type": "writing",
                "title": "过滤会话",
                "project_id": str(_project_uuid(sample_project)),
            },
        )
        assert created.status_code == 201, created.text[:200]

        resp = await client.get(f"/api/v1/sessions?project_id={sample_project.id}")
        assert resp.status_code == 200, resp.text[:200]
        body = resp.json()
        assert body["total"] == 1, f"应只命中 1 会话，实际 {body['total']}"


# ── 面 ⑥：GET /chat/messages?conversation_id ──────────────────────────


@pytest.mark.api
class TestChatMessagesConversationIdQueryOverflow:
    """#1162 面 ⑥：溢出 conversation_id → 200 + 空列表。

    语义选择说明：chat_message_service.list_messages_by_conversation 对
    conversation 不存在**本就无 404 语义**（纯位置透传 repo，不校验父实体），
    故落「线程不存在 → 无消息可读 → 200 空」而非 404（未引入新语义）。
    """

    async def test_overflow_uuid_returns_200_empty(self, client, db_session, override_get_db):
        """溢出 conversation_id → 200 + {items: [], total: 0}（修复前 500）。"""
        url = f"/api/v1/chat/messages?conversation_id={_overflow_uuid()}"
        _assert_empty_page(await client.get(url), url)

    async def test_in_range_absent_uuid_returns_200_empty(
        self, client, db_session, override_get_db
    ):
        """反例守护 A：范围内不存在 conversation_id 仍走正常查询路径 → 200 空。"""
        url = f"/api/v1/chat/messages?conversation_id={_in_range_absent_uuid()}"
        _assert_empty_page(await client.get(url), url)

    async def test_real_conversation_filter_still_works(
        self, client, db_session, override_get_db, sample_project
    ):
        """反例守护 B：真实 conversation_id → 200（空消息列表，非 500/404）。"""
        conv = await client.post(
            "/api/v1/chat/conversations",
            json={"project_id": str(_project_uuid(sample_project))},
        )
        assert conv.status_code == 201, conv.text[:200]
        conv_id = conv.json()["conversation_id"]

        resp = await client.get(f"/api/v1/chat/messages?conversation_id={conv_id}")
        assert resp.status_code == 200, resp.text[:200]
        assert resp.json()["total"] == 0


# ── 面 ⑦：POST /chapters/{ch_id}/move?target_volume_id ────────────────


async def _chapter_volume_id_in_db(db_session, chapter_uuid: str) -> uuid.UUID | None:
    """DB 真相：直读 chapters.volume_id（int）→ 领域 UUID（None = 未挂卷）。"""
    orm_id = uuid.UUID(chapter_uuid).int
    result = await db_session.execute(select(ChapterORM.volume_id).where(ChapterORM.id == orm_id))
    raw = result.scalar_one()
    return None if raw is None else uuid.UUID(int=raw)


@pytest.mark.api
class TestMoveChapterTargetVolumeMustExist:
    """#1162 面 ⑦：目标卷必须真实存在 → 否则 422 且 chapter.volume_id 不变。

    实测（修复前）两类同族缺陷：
    - 溢出 target → 500（UPDATE ... values(volume_id=<128位>)）
    - 范围内不存在 target（UUID(int=987654321)）→ **200 且 volume_id 被盲写成孤儿值**
      （先 UPDATE 后无存在性校验；同 service delete_volume(move_to) 先例已有校验）
    """

    async def _setup_chapter_in_v1(self, client, sample_project) -> tuple[str, str, str]:
        """建 V1/V2 + V1 下一章 → (ch_id, v1_id, v2_id)。"""
        pid = sample_project.id
        v1 = await client.post(f"/api/v1/projects/{pid}/volumes", json={"title": "V1"})
        v2 = await client.post(f"/api/v1/projects/{pid}/volumes", json={"title": "V2"})
        assert v1.status_code == 201 and v2.status_code == 201, f"{v1.text[:120]}{v2.text[:120]}"
        v1_id, v2_id = v1.json()["id"], v2.json()["id"]
        ch = await client.post(
            f"/api/v1/projects/{pid}/chapters",
            json={"title": "待移动章", "volume_id": v1_id},
        )
        assert ch.status_code == 201, ch.text[:200]
        return ch.json()["id"], v1_id, v2_id

    async def test_overflow_target_returns_422_and_volume_unchanged(
        self, client, db_session, override_get_db, sample_project
    ):
        """溢出 target_volume_id → 422，且 DB 中 volume_id 仍是原卷（不得 500/盲写）。"""
        ch_id, v1_id, _ = await self._setup_chapter_in_v1(client, sample_project)

        resp = await client.post(
            f"/api/v1/chapters/{ch_id}/move?target_volume_id={_overflow_uuid()}"
        )
        assert resp.status_code == 422, (
            f"溢出目标卷应为 422（目标卷不存在），实际 {resp.status_code}: {resp.text[:200]}"
        )
        assert await _chapter_volume_id_in_db(db_session, ch_id) == uuid.UUID(v1_id)

    async def test_in_range_absent_target_returns_422_and_volume_unchanged(
        self, client, db_session, override_get_db, sample_project
    ):
        """范围内不存在的 target（987654321）→ 422，且 volume_id 不被盲写成孤儿值。"""
        ch_id, v1_id, _ = await self._setup_chapter_in_v1(client, sample_project)

        resp = await client.post(
            f"/api/v1/chapters/{ch_id}/move?target_volume_id={_in_range_absent_uuid()}"
        )
        assert resp.status_code == 422, (
            f"不存在的目标卷应为 422（修复前实测 200 + 孤儿 volume_id），"
            f"实际 {resp.status_code}: {resp.text[:200]}"
        )
        assert await _chapter_volume_id_in_db(db_session, ch_id) == uuid.UUID(v1_id)

    async def test_real_target_volume_moves_successfully(
        self, client, db_session, override_get_db, sample_project
    ):
        """反例守护：真实存在的目标卷 → 200 且移动生效（DB 真相 volume_id 已变）。"""
        ch_id, _, v2_id = await self._setup_chapter_in_v1(client, sample_project)

        resp = await client.post(f"/api/v1/chapters/{ch_id}/move?target_volume_id={v2_id}")
        assert resp.status_code == 200, resp.text[:200]
        assert resp.json()["volume_id"] == v2_id
        assert await _chapter_volume_id_in_db(db_session, ch_id) == uuid.UUID(v2_id)
