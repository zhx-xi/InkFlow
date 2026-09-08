"""F59-M2 RED (#963): 思考档位 API 面契约（spec §3.1/§3.3/§5.4 回显/§7）。

契约:
1. 【chat 422】POST /chat/agent/stream body ``reasoning_effort`` 非七档 →
   422 + **i18n 自定义文案**（detail 为 str、不泄漏 pydantic 原文 "Input should
   be"，§3.3 行 1；实现必须 chat handler 局部处理，不得加全局 RequestValidationError
   handler——护栏用例锁 /settings 既有 detail=list 形态不破）。
2. 【chat 合法】七档任一 → 200 SSE（mock service override，档位透传契约在
   backend/tests/unit/.../test_deps_chat_agent_reasoning.py 锁定）。
3. 【legacy /stream】不接入（§10）：共用 DTO → 非法值同样 422（校验层）；
   合法值行为与现状一致（handler 不消费该字段，帧协议 delta/done 不变）。
4. 【项目 PATCH】PATCH /projects/{id} config.reasoning_effort 合法 → 200 回显 +
   GET 回读；非法 → 422（Literal，默认校验形态）；null → 200（清除=跟随全局）。
5. 【全局 settings（D-1 方案 A 形态，拍板 B 则翻转本组）】PATCH /settings
   {default_reasoning_effort} → 200 + GET 回显 + config.llm_reasoning_effort
   内存单例同步桥（GUI 即时生效，镜像 #987 方案 A）。
6. 【能力回显】GET /provider-configs models[] 每条含 ``supports_reasoning`` bool：
   手动值（true/false）原样回显；null → 探测链填充（探测点 patch，防 litellm
   表版本漂移）。

RED 预期失败形态:
- ChatStreamRequest/ProjectConfig/AppSettings 无字段 → 非法值请求当前 200/422
  形态不符；models[] 无 supports_reasoning 键 → KeyError/AssertionError。
- settings PATCH default_reasoning_effort → extra=forbid 422（RED 失败）。
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from inkflow.api.app import app
from inkflow.api.deps import get_agent_run_repo, get_chat_agent_service, get_db
from inkflow.api.routers.chat_stream import get_chat_service
from inkflow.domain.models.agent_run import AgentRun

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
ENDPOINT_AGENT = "/api/v1/chat/agent/stream"
ENDPOINT_LEGACY = "/api/v1/chat/stream"
ENDPOINT_SETTINGS = "/api/v1/settings"

ALL_LEVELS = ["none", "minimal", "low", "medium", "high", "xhigh", "default"]


# ── Fixtures ──


@pytest_asyncio.fixture
async def client(db_session, monkeypatch):
    """ASGI 客户端 + get_db → 测试内存库（provider-configs/settings 面共用）。"""
    monkeypatch.delenv(ENV_TOKEN, raising=False)

    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def override_agent_service():
    """mock ChatAgentService：产 done 终帧的最小流（chat 面 200 通道）。"""

    async def _stream_events(prompt, project_id=None, chapter_context=None, cancel_event=None):
        yield MagicMock(
            type="done", delta="", done=True, error=None, id=None, name=None, args=None,
            result=None, payload=None,
        )

    svc = MagicMock()
    svc.stream_events = MagicMock(side_effect=_stream_events)
    svc.consume_trace = MagicMock(return_value=([], "ok", 0))
    app.dependency_overrides[get_chat_agent_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def override_agent_run_repo():
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    run = AgentRun(
        id="chat-run-0001",
        project_id=uuid.UUID("550e8400-e29b-41d4-a716-446655440000"),
        mode="chat",
        created_at=now,
        updated_at=now,
    )
    repo = MagicMock()
    repo.create = AsyncMock(return_value=run)
    repo.save = AsyncMock(return_value=None)
    app.dependency_overrides[get_agent_run_repo] = lambda: repo
    yield repo
    app.dependency_overrides.clear()


def _chat_payload(**overrides) -> dict:
    body = {"project_id": str(uuid.uuid4()), "prompt": "你好"}
    body.update(overrides)
    return body


def _frames_of(resp_text: str) -> list[dict]:
    frames = []
    for block in resp_text.split("\n\n"):
        block = block.strip()
        if block.startswith("data:"):
            frames.append(json.loads(block[len("data:") :].strip()))
    return frames


# ── 1. chat agent/stream 校验 ──


@pytest.mark.asyncio
class TestChatAgentStreamReasoningValidation:
    """POST /chat/agent/stream reasoning_effort 七档校验 + i18n 422 文案（§3.3 行 1）。"""

    async def test_illegal_level_422_no_pydantic_leak(
        self, client, override_agent_service, override_agent_run_repo
    ) -> None:
        resp = await client.post(ENDPOINT_AGENT, json=_chat_payload(reasoning_effort="ultra"))
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        # 自定义文案（str），禁 pydantic 原文/内部类型泄漏
        assert isinstance(detail, str), f"422 必须 i18n 自定义文案（str），实得 {type(detail)}"
        text = resp.text
        assert "Input should be" not in text, "不得泄漏 pydantic 默认枚举文案"
        assert "litellm" not in text.lower(), "不得泄漏 litellm 类型/包名"
        assert detail.strip()

    async def test_null_level_ok(
        self, client, override_agent_service, override_agent_run_repo
    ) -> None:
        """显式 null=未覆盖（按项目>全局解析），200 合法。"""
        resp = await client.post(ENDPOINT_AGENT, json=_chat_payload(reasoning_effort=None))
        assert resp.status_code == 200

    async def test_absent_level_ok(
        self, client, override_agent_service, override_agent_run_repo
    ) -> None:
        resp = await client.post(ENDPOINT_AGENT, json=_chat_payload())
        assert resp.status_code == 200

    @pytest.mark.parametrize("level", ALL_LEVELS)
    async def test_seven_levels_accepted(
        self, client, override_agent_service, override_agent_run_repo, level: str
    ) -> None:
        resp = await client.post(ENDPOINT_AGENT, json=_chat_payload(reasoning_effort=level))
        assert resp.status_code == 200, f"{level} 必须为合法档位"
        assert resp.headers["content-type"].startswith("text/event-stream")


# ── 2. 护栏：全局 422 形态不破（禁全局 RequestValidationError handler）──


@pytest.mark.asyncio
class TestLegacyValidationShapeGuard:
    """护栏用例（合法同批 PASS）：其他端点 422 仍为 pydantic list 形态——
    GREEN 必须 chat handler 局部处理，不得加全局 handler 打崩既有契约。"""

    async def test_settings_unknown_field_422_detail_list(self, client) -> None:
        resp = await client.patch(ENDPOINT_SETTINGS, json={"themee": "night"})
        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], list)

    async def test_project_illegal_config_level_422(self, client) -> None:
        """项目面按 §3.1 字面 Literal 422（默认 list 形态即可，不要求自定义文案）。"""
        pid = str(uuid.uuid4())
        resp = await client.patch(
            f"/api/v1/projects/{pid}", json={"config": {"reasoning_effort": "bogus"}}
        )
        # RED：ProjectConfig 无字段 extra=ignore → 当前可能 200（静默吞）→ 翻红点
        assert resp.status_code == 422, (
            "reasoning_effort 非法值不得被 ProjectConfig 静默吞掉（extra=ignore 通道）"
        )


# ── 3. legacy /stream 不接入（§10 / N-3）──


@pytest.mark.asyncio
class TestLegacyStreamNotWired:
    async def test_illegal_422(self, client) -> None:
        resp = await client.post(ENDPOINT_LEGACY, json=_chat_payload(reasoning_effort="ultra"))
        assert resp.status_code == 422

    async def test_legal_level_behavior_unchanged(self, client) -> None:
        """合法档位 → legacy 帧协议不变（delta/done 两键形态，不消费 reasoning_effort）。"""
        from inkflow.domain.services.chat_service import ChatStreamEvent

        async def _stream(prompt, chapter_context=None):
            yield ChatStreamEvent(delta="你")
            yield ChatStreamEvent(done=True)

        svc = MagicMock()
        svc.stream = MagicMock(side_effect=_stream)
        app.dependency_overrides[get_chat_service] = lambda: svc
        try:
            resp = await client.post(ENDPOINT_LEGACY, json=_chat_payload(reasoning_effort="high"))
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        frames = _frames_of(resp.text)
        assert frames[0] == {"delta": "你", "done": False}, "legacy 帧协议不得引入 type 键"
        assert frames[-1] == {"done": True}


# ── 4. 项目 PATCH / GET 回显 ──


@pytest.mark.asyncio
class TestProjectReasoningRoundtrip:
    async def test_patch_and_get_config_level(self, client) -> None:
        created = await client.post("/api/v1/projects", json={"name": "F59 测试项目"})
        assert created.status_code in (200, 201), created.text
        url = f"/api/v1/projects/{created.json()['id']}"

        resp = await client.patch(
            url, json={"config": {"reasoning_effort": "high"}}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["config"]["reasoning_effort"] == "high"

        readback = await client.get(url)
        assert readback.status_code == 200
        assert readback.json()["config"]["reasoning_effort"] == "high"

    async def test_patch_null_clears_to_follow_global(self, client) -> None:
        created = await client.post("/api/v1/projects", json={"name": "F59 清除项目"})
        pid = created.json()["id"]
        url0 = f"/api/v1/projects/{pid}"
        await client.patch(url0, json={"config": {"reasoning_effort": "low"}})
        resp = await client.patch(url0, json={"config": {"reasoning_effort": None}})
        assert resp.status_code == 200, resp.text
        assert resp.json()["config"]["reasoning_effort"] is None

    async def test_legacy_project_config_without_key_deserializes(self, client) -> None:
        """GET 新建成项目 config 携带 reasoning_effort=null（回显面，零迁移）。"""
        created = await client.post("/api/v1/projects", json={"name": "F59 默认项目"})
        pid = created.json()["id"]
        readback = await client.get(f"/api/v1/projects/{pid}")
        assert "reasoning_effort" in readback.json()["config"]
        assert readback.json()["config"]["reasoning_effort"] is None


# ── 5. 全局 settings 面（D-1 方案 A；拍板 B 则本组翻转）──


@pytest.mark.asyncio
class TestSettingsReasoningSync:
    """D-1 方案 A（拍板 B 则本组翻转）。

    ⚠️ 桥回灌写的是进程级 config 单例——类级 autouse 备份/恢复，防跨文件
    污染（test_settings_api 空表全等断言依赖默认值，全量 api 轨共进程）。
    """

    @pytest.fixture(autouse=True)
    def _restore_config_singleton(self):
        from inkflow.core.config import config

        original = config.llm_reasoning_effort
        yield
        config.llm_reasoning_effort = original

    async def test_patch_and_get(self, client) -> None:
        resp = await client.patch(ENDPOINT_SETTINGS, json={"default_reasoning_effort": "medium"})
        assert resp.status_code == 200, f"D-1 方案 A：F32 字段落 DB（拍板 B 翻转本组）{resp.text}"
        assert resp.json()["default_reasoning_effort"] == "medium"
        got = await client.get(ENDPOINT_SETTINGS)
        assert got.json()["default_reasoning_effort"] == "medium"

    async def test_invalid_level_422(self, client) -> None:
        resp = await client.patch(ENDPOINT_SETTINGS, json={"default_reasoning_effort": "ultra"})
        assert resp.status_code == 422

    async def test_patch_syncs_config_singleton(self, client) -> None:
        """同步桥（#987 方案 A 镜像）：PATCH 后内存 config.llm_reasoning_effort 即更新。"""
        from inkflow.core.config import config

        try:
            await client.patch(ENDPOINT_SETTINGS, json={"default_reasoning_effort": "high"})
            assert config.llm_reasoning_effort == "high", "GUI 全局档位必须即时生效"
        finally:
            config.llm_reasoning_effort = "default"

    async def test_get_default_reflects_config(self, client) -> None:
        """未持久化时 GET 回显启动源现值（读点收口 config）。"""
        got = await client.get(ENDPOINT_SETTINGS)
        assert got.json()["default_reasoning_effort"] in ALL_LEVELS


# ── 6. provider-configs models[] supports_reasoning 回显 ──


@pytest.mark.asyncio
class TestProviderConfigsSupportsReasoningEcho:
    async def _seed(self, client, db_session):
        from inkflow.infrastructure.database.models.provider_config import ProviderConfigORM

        row = ProviderConfigORM(
            name="probe-test",
            base_url="https://x.example/v1",
            default_model="probe-test/m1",
            models=[
                {"id": "m1", "type": "chat", "roles": []},
                {"id": "m2", "type": "chat", "roles": [], "supports_reasoning": True},
                {"id": "m3", "type": "chat", "roles": [], "supports_reasoning": False},
            ],
        )
        db_session.add(row)
        await db_session.commit()

    async def test_models_carry_bool(self, client, db_session, monkeypatch) -> None:
        """每条 chat 模型带 supports_reasoning bool：null→探测填充；手动值原样。"""
        await self._seed(client, db_session)
        # patch 探测链：m1（无手动值）恒 False —— 防 litellm 表版本漂移
        def _probe(model_full, provider=None, manual=None):
            return bool(manual) if manual is not None else False

        monkeypatch.setattr(
            "inkflow.infrastructure.llm.capability_probe.supports_reasoning_for_model",
            _probe,
        )
        resp = await client.get("/api/v1/provider-configs")
        assert resp.status_code == 200
        item = next(i for i in resp.json()["items"] if i["name"] == "probe-test")
        by_id = {m["id"]: m for m in item["models"]}
        assert by_id["m1"]["supports_reasoning"] is False, "手动未设置 → 探测填充 bool"
        assert by_id["m2"]["supports_reasoning"] is True, "手动 True 原样回显"
        assert by_id["m3"]["supports_reasoning"] is False, "手动 False 原样回显"

    async def test_embedding_models_no_probe_needed(self, client, db_session, monkeypatch) -> None:
        """embedding 条目同样回显 bool（False 合理值；思考仅 chat 语义）。"""
        await self._seed(client, db_session)
        monkeypatch.setattr(
            "inkflow.infrastructure.llm.capability_probe.supports_reasoning_for_model",
            lambda model_full, provider=None, manual=None: False,
        )
        resp = await client.get("/api/v1/provider-configs")
        item = next(i for i in resp.json()["items"] if i["name"] == "probe-test")
        assert all(isinstance(m["supports_reasoning"], bool) for m in item["models"])

    async def test_probe_error_does_not_break_endpoint(
        self, client, db_session, monkeypatch
    ) -> None:
        """N-2：探测内部异常不得打崩列表端点（probe 兜底 False 已在单测锁，本处端到端锚）。"""
        await self._seed(client, db_session)
        monkeypatch.setattr(
            "inkflow.infrastructure.llm.capability_probe.supports_reasoning_for_model",
            MagicMock(side_effect=RuntimeError("explode")),
        )
        resp = await client.get("/api/v1/provider-configs")
        # probe 函数本体在 _to_response 装配点被调用；其异常兜底属 probe 契约。
        # 端点必须 200（probe 永不 raise）→ RED 期函数不存在时 ImportError 转 500 亦翻红。
        assert resp.status_code == 200, "探测异常绝不打崩 provider-configs"
