r"""#1166 族补全 RED 契约 —— 写侧盲落孤儿（病③）+ chat/sessions/extraction 溢出面（病①）。

姊妹文件：#1106 路径主键 / #1139 父主键过滤 / #1151 路径 project_id /
#1162 GET 嵌套 FK。本单两病：

病①（8 个 500 面，traceback 实证抛点）：
  500  GET  /sessions?project_id=<uuid4>            session_repo.list 无守卫
  500  GET  /chat/messages?conversation_id=<uuid4>  chat_message_repo.py:152
  500  POST /chapters/{id}/move?target_volume_id=<uuid4>   chapter_repo.py:285
  500  PATCH /chapters/{id} body.volume_id=<uuid4>         chapter_repo.py:224
  500  POST /chat/conversations body.project_id=<uuid4>    chat_message_repo.py:106
  500  POST /chat/agent/stream body.conversation_id=<uuid4> api/_chat_auth.py:33（DI 层直取 .int）
  500  POST /knowledge/extract body.project_id=<uuid4>     foreshadowing_repo.py:169（规则扫描链）

病③（写侧独有，DB 复读确认的**盲落孤儿**，范围内不存在的 FK 被直接写进库）：
  200 + DB 盲写  POST /chapters/{id}/move?target_volume_id=<notfound>
  200 + DB 盲写  PATCH /chapters/{id} body.volume_id=<notfound>
  201 + 孤儿行   POST /chat/conversations body.project_id=<notfound>

契约语义（行为断言，不指定守卫落点）：
- 读/扫描面：超范围 = 不命中 → 200 + 空 或 404（视端点「父不存在」语义）
- 写目标面（move/PATCH volume 改挂）：目标不存在 → **422**（同域先例
  delete_volume(move_to=) → VolumeMoveError「目标卷不存在」）且 **DB 原值不动**
- 建实体面（conversations）：project 不存在 → **404** 且 **零落库**（#1138 孤儿行口径）
- 反例守护：真实存在的目标 → 行为不变（写侧必须真写成）
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from inkflow.api.app import app
from inkflow.infrastructure.database.models.chapter import ChapterORM
from inkflow.infrastructure.database.models.conversation import ConversationORM

pytestmark = pytest.mark.asyncio  # F27 实测必写（asyncio_mode=auto 双保险）

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"


@pytest_asyncio.fixture
async def client(monkeypatch):
    """ASGI 测试客户端（函数级，无 token 模式）。"""
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _ovf() -> uuid.UUID:
    v = uuid.uuid4()
    assert v.int >= 2**63, "前提：uuid4 溢出 int64"
    return v


MISSING_SMALL = uuid.UUID(int=987654321)
"""int64 范围内、必然不存在的 UUID（不存在 ≠ 溢出，两个子问题都要测）。"""


async def _seed_vol_and_ch(client, pid: str, title: str = "c1") -> tuple[str, str]:
    """建 1 卷 + 1 章，返回 (volume_id, chapter_id)。"""
    vol = await client.post(
        f"/api/v1/projects/{pid}/volumes",
        json={"title": f"vol-{title}", "order_index": 1},
    )
    assert vol.status_code == 201, vol.text[:200]
    vol_id = vol.json()["id"]
    ch = await client.post(
        f"/api/v1/projects/{pid}/chapters",
        json={"title": title, "volume_id": vol_id, "content": "x"},
    )
    assert ch.status_code == 201, ch.text[:200]
    return vol_id, ch.json()["id"]


async def _db_volume_id(db_session, chapter_id: str) -> int:
    """DB 复读章节当前 volume_id（写侧契约的权威判据）。"""
    return (
        await db_session.execute(
            select(ChapterORM.volume_id).where(
                ChapterORM.id == uuid.UUID(chapter_id).int
            )
        )
    ).scalar_one()


# ── 病① 读/扫描面：超范围不得 500 ────────────────────────────────────


@pytest.mark.api
class TestSessionsProjectOverflowNoError:
    """GET /sessions?project_id —— 过滤值超范围 = 不命中 → 200 + 空。"""

    async def test_overflow_project_filter_returns_empty(
        self, client, db_session, override_get_db
    ):
        resp = await client.get("/api/v1/sessions", params={"project_id": str(_ovf())})
        assert (
            resp.status_code != 500
        ), f"不得 500: {resp.status_code} {resp.text[:200]}"
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    async def test_in_range_missing_project_filter_returns_empty(
        self, client, db_session, override_get_db
    ):
        resp = await client.get(
            "/api/v1/sessions", params={"project_id": str(MISSING_SMALL)}
        )
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    async def test_live_project_filter_works(
        self, client, db_session, override_get_db, api_project
    ):
        """反例：真实项目（无会话）→ 200，过滤功能未被守卫误吞。"""
        resp = await client.get(
            "/api/v1/sessions", params={"project_id": api_project["id"]}
        )
        assert resp.status_code == 200


@pytest.mark.api
class TestChatMessagesConversationOverflow:
    """GET /chat/messages?conversation_id —— 溢出 → 200 + 空列表（#1165 定档语义）。

    上游契约 test_nested_fk_query_overflow_1162_api.py 明文「不引入 404」：
    chat_message_service 对父线程本就无存在性校验语义，溢出 500 由
    repo 层守卫短路（线程不存在 → 无消息可读 → 200 空）。
    """

    async def test_overflow_conversation_200_empty(
        self, client, db_session, override_get_db
    ):
        resp = await client.get(
            "/api/v1/chat/messages", params={"conversation_id": str(_ovf())}
        )
        assert (
            resp.status_code != 500
        ), f"不得 500: {resp.status_code} {resp.text[:200]}"
        assert (
            resp.status_code == 200
        ), f"应 200 + 空（#1165 定档），实际 {resp.status_code}"
        assert resp.json()["items"] == []

    async def test_missing_small_conversation_200_empty(
        self, client, db_session, override_get_db
    ):
        resp = await client.get(
            "/api/v1/chat/messages", params={"conversation_id": str(MISSING_SMALL)}
        )
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    async def test_live_conversation_returns_200(
        self, client, db_session, override_get_db, api_project
    ):
        """反例：真实会话（无消息）→ 200 + 空，正常读取路径不受影响。"""
        conv = await client.post(
            "/api/v1/chat/conversations", json={"project_id": api_project["id"]}
        )
        assert conv.status_code == 201, conv.text[:200]
        cid = conv.json()["conversation_id"]
        resp = await client.get(
            "/api/v1/chat/messages", params={"conversation_id": cid}
        )
        assert resp.status_code == 200
        assert resp.json()["items"] == []


@pytest.mark.api
class TestAgentStreamAndExtractOverflowNoError:
    """DI 层（chat/agent/stream）与规则扫描链（knowledge/extract）的溢出 500。"""

    async def test_agent_stream_overflow_not_500(
        self, client, db_session, override_get_db, api_project
    ):
        """body.conversation_id 超范围 → 不得 500（鉴权层 None → 既有 4xx 路径）。"""
        resp = await client.post(
            "/api/v1/chat/agent/stream",
            json={
                "project_id": api_project["id"],
                "conversation_id": str(_ovf()),
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert (
            resp.status_code != 500
        ), f"不得 500: {resp.status_code} {resp.text[:200]}"

    async def test_knowledge_extract_overflow_not_500(
        self, client, db_session, override_get_db
    ):
        """body.project_id 超范围 → 不得 500（404 或 200 空结果均可，扫描链 repo 守卫后必不炸）。"""
        resp = await client.post(
            "/api/v1/knowledge/extract",
            json={"project_id": str(_ovf()), "text": "x" * 10, "source": "manual"},
        )
        assert (
            resp.status_code != 500
        ), f"不得 500: {resp.status_code} {resp.text[:200]}"


# ── 病①+③ 写侧：move / PATCH volume_id ──────────────────────────────


@pytest.mark.api
class TestMoveChapterTargetVolume:
    """POST /chapters/{id}/move?target_volume_id —— 目标卷校验（422）+ DB 不盲写。

    语义锚点 = 同域先例 delete_volume(move_to=)：目标卷不存在 → VolumeMoveError → 422。
    """

    async def test_overflow_target_422_not_500(
        self, client, db_session, override_get_db, api_project
    ):
        pid = api_project["id"]
        vol_id, ch_id = await _seed_vol_and_ch(client, pid, "mv-a")
        resp = await client.post(
            f"/api/v1/chapters/{ch_id}/move", params={"target_volume_id": str(_ovf())}
        )
        assert (
            resp.status_code != 500
        ), f"不得 500: {resp.status_code} {resp.text[:200]}"
        assert resp.status_code == 422, f"目标卷不存在应 422，实际 {resp.status_code}"
        assert (
            await _db_volume_id(db_session, ch_id) == uuid.UUID(vol_id).int
        ), "拒绝后 volume_id 必须保持原值"

    async def test_missing_small_target_422_no_blind_write(
        self, client, db_session, override_get_db, api_project
    ):
        """🔴 病③核心：范围内不存在的目标卷 → 422 且**不得盲写落库**。"""
        pid = api_project["id"]
        vol_id, ch_id = await _seed_vol_and_ch(client, pid, "mv-b")
        resp = await client.post(
            f"/api/v1/chapters/{ch_id}/move",
            params={"target_volume_id": str(MISSING_SMALL)},
        )
        assert (
            resp.status_code == 422
        ), f"应 422，实际 {resp.status_code}: {resp.text[:200]}"
        assert (
            await _db_volume_id(db_session, ch_id) == uuid.UUID(vol_id).int
        ), "盲落孤儿回归！DB volume_id 被写成不存在的卷"

    async def test_real_target_move_works(
        self, client, db_session, override_get_db, api_project
    ):
        """反例：真实目标卷 → 200 且 DB **真的改了**（校验不得把正常 move 挡死）。"""
        pid = api_project["id"]
        _, ch_id = await _seed_vol_and_ch(client, pid, "mv-ok")
        dst = await client.post(
            f"/api/v1/projects/{pid}/volumes", json={"title": "dst", "order_index": 2}
        )
        assert dst.status_code == 201
        dst_id = dst.json()["id"]
        resp = await client.post(
            f"/api/v1/chapters/{ch_id}/move", params={"target_volume_id": dst_id}
        )
        assert resp.status_code == 200, resp.text[:200]
        assert await _db_volume_id(db_session, ch_id) == uuid.UUID(dst_id).int

    async def test_move_to_none_unvolume_still_works(
        self, client, db_session, override_get_db, api_project
    ):
        """反例：不带 target = 出卷（volume_id=NULL），既有语义不得回归。"""
        pid = api_project["id"]
        _, ch_id = await _seed_vol_and_ch(client, pid, "mv-none")
        resp = await client.post(f"/api/v1/chapters/{ch_id}/move")
        assert resp.status_code == 200, resp.text[:200]
        assert await _db_volume_id(db_session, ch_id) is None


@pytest.mark.api
class TestPatchChapterVolume:
    """PATCH /chapters/{id} body.volume_id —— 改挂卷同样要目标校验（同 move 语义）。"""

    async def test_overflow_volume_422_not_500(
        self, client, db_session, override_get_db, api_project
    ):
        pid = api_project["id"]
        vol_id, ch_id = await _seed_vol_and_ch(client, pid, "pt-a")
        resp = await client.patch(
            f"/api/v1/chapters/{ch_id}", json={"volume_id": str(_ovf())}
        )
        assert (
            resp.status_code != 500
        ), f"不得 500: {resp.status_code} {resp.text[:200]}"
        assert resp.status_code == 422, f"应 422，实际 {resp.status_code}"
        assert await _db_volume_id(db_session, ch_id) == uuid.UUID(vol_id).int

    async def test_missing_small_volume_422_no_blind_write(
        self, client, db_session, override_get_db, api_project
    ):
        """🔴 病③核心：PATCH 到范围内不存在的卷 → 422 且不落库。"""
        pid = api_project["id"]
        vol_id, ch_id = await _seed_vol_and_ch(client, pid, "pt-b")
        resp = await client.patch(
            f"/api/v1/chapters/{ch_id}", json={"volume_id": str(MISSING_SMALL)}
        )
        assert (
            resp.status_code == 422
        ), f"应 422，实际 {resp.status_code}: {resp.text[:200]}"
        assert (
            await _db_volume_id(db_session, ch_id) == uuid.UUID(vol_id).int
        ), "盲落孤儿回归！"

    async def test_real_volume_reassign_works(
        self, client, db_session, override_get_db, api_project
    ):
        """反例：改挂到真实存在的卷 → 200 且 DB 真的改。"""
        pid = api_project["id"]
        _, ch_id = await _seed_vol_and_ch(client, pid, "pt-ok")
        dst = await client.post(
            f"/api/v1/projects/{pid}/volumes",
            json={"title": "pt-dst", "order_index": 2},
        )
        dst_id = dst.json()["id"]
        resp = await client.patch(
            f"/api/v1/chapters/{ch_id}", json={"volume_id": dst_id}
        )
        assert resp.status_code == 200, resp.text[:200]
        assert await _db_volume_id(db_session, ch_id) == uuid.UUID(dst_id).int

    async def test_title_only_patch_untouched(
        self, client, db_session, override_get_db, api_project
    ):
        """反例：只改 title 不带 volume_id → 200 且 volume 不变（exclude_unset 语义）。"""
        pid = api_project["id"]
        vol_id, ch_id = await _seed_vol_and_ch(client, pid, "pt-t")
        resp = await client.patch(
            f"/api/v1/chapters/{ch_id}", json={"title": "renamed"}
        )
        assert resp.status_code == 200, resp.text[:200]
        assert await _db_volume_id(db_session, ch_id) == uuid.UUID(vol_id).int


# ── 病①+③ 建实体：chat/conversations ────────────────────────────────


@pytest.mark.api
class TestCreateConversationProjectValidation:
    """POST /chat/conversations —— project 存在性预检（#1138 孤儿行口径：404 + 零落库）。"""

    async def test_overflow_project_404_not_500(
        self, client, db_session, override_get_db
    ):
        resp = await client.post(
            "/api/v1/chat/conversations", json={"project_id": str(_ovf())}
        )
        assert (
            resp.status_code != 500
        ), f"不得 500: {resp.status_code} {resp.text[:200]}"
        assert resp.status_code == 404, f"项目不存在应 404，实际 {resp.status_code}"
        rows = (
            await db_session.execute(select(func.count()).select_from(ConversationORM))
        ).scalar_one()
        assert rows == 0, "拒绝后不得落任何行"

    async def test_missing_small_project_404_no_orphan_row(
        self, client, db_session, override_get_db
    ):
        """🔴 病③核心：范围内不存在的 project → 404 且**零孤儿行**。"""
        resp = await client.post(
            "/api/v1/chat/conversations", json={"project_id": str(MISSING_SMALL)}
        )
        assert (
            resp.status_code == 404
        ), f"应 404，实际 {resp.status_code}: {resp.text[:200]}"
        rows = (
            await db_session.execute(select(func.count()).select_from(ConversationORM))
        ).scalar_one()
        assert rows == 0, "孤儿 conversation 行落库回归！"

    async def test_live_project_201(
        self, client, db_session, override_get_db, api_project
    ):
        """反例：真实项目 → 201 且返回体带 conversation_id。"""
        resp = await client.post(
            "/api/v1/chat/conversations", json={"project_id": api_project["id"]}
        )
        assert resp.status_code == 201, resp.text[:200]
        assert resp.json()["conversation_id"]
        rows = (
            await db_session.execute(select(func.count()).select_from(ConversationORM))
        ).scalar_one()
        assert rows == 1
