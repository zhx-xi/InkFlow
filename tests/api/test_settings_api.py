"""#79 F19-GUI 子任务 C — 设置工具端点 API 测试契约（TDD RED 阶段）。

本文件为 `api/routers/settings.py`（NEW，spec §4.4/§4.6 Q3 拍板，§4.9 决策行）
定义测试契约，覆盖 2 个基础设施工具端点：

- `POST /api/v1/settings/llm-keys` — 包装 APIKeyManager 加密存储 API Key
- `POST /api/v1/settings/llm/test` — LLMClient 最小连通探测

权威来源：specs/f19-gui/spec.md §4.2.3（Agent 配置页表单：apiKeyDraft →
/settings/llm-keys、testStatus 'ok'/'fail' 消费语义）、§4.4/§4.6（Q3 拍板：
新增 2 个基础设施工具端点）、§4.7（集成层：加密落盘回读）、§4.8 M5（验收）。
注：仓库内 spec.md §4 正文仍为占位（待 #79 起草），本文件以任务书口径为准，
消费方契约佐证 = frontend/packages/renderer/src/stores/agent.ts
（apiKeyDraft「提交到 /settings/llm-keys 后清空」+ testStatus 'ok'/'fail'）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

1. 测试方式：fastapi.testclient.TestClient 直连真实 app 对象（import
   inkflow.api.app），验证纯 HTTP 行为；settings 路由为新增模块
   `inkflow.api.routers.settings`，本文件模块级 import 它（RED 阶段该
   模块不存在 → 收集期 ModuleNotFoundError，即预期失败形态）。

2. 【无 token 模式——硬性契约】本文件所有用例依赖 env
   `INKFLOW_SERVER_TOKEN` 未设置时中间件直通（test_token_auth.py 设计
   假设 #6 同款）：client fixture 内显式 monkeypatch.delenv，免疫开发者
   本机 shell 的 env 残留导致假失败。

3. 【模块契约】`inkflow.api.routers.settings` 必须暴露（本文件 patch
   目标 = 最终契约，GREEN 必须匹配）：
   - `router = APIRouter(prefix="/api/v1/settings", tags=["Settings"])`
     （app.py 需 `app.include_router(settings.router)`，与 agent.py 等
     既有 router 模块级模式一致）
   - `_get_key_manager() -> APIKeyManager`：零参模块级工厂函数，镜像
     cli/commands/llm.py 既有 `_get_key_manager()` =
     APIKeyManager(secret_key=config.secret_key, storage_dir=config.data_dir / "keys")
   - `_get_llm_client(provider: str, model: str, api_key: str) ->
     LLMClientProtocol`：按请求参数构造并返回 LLM 客户端（连通探测用）

4. POST /api/v1/settings/llm-keys 请求契约：body 为
   `{provider: str, api_key: str}`，两字段均必填且非空（空白串
   "   " 也拒绝 → 422，GREEN 需 strip 后校验非空，与 F3 WritingRequest
   outline 空白拒绝行为对齐）；多余字段【忽略】（FastAPI/Pydantic v2
   默认行为，不 422）。

5. llm-keys 成功契约：201（资源创建）+ body 精确等于
   `{"provider": <provider>, "status": "saved"}`（镜像 CLI `llm set-key`
   JSON 输出结构）。【安全红线】响应【禁止】回显 api_key 明文——
   assert api_key not in resp.text。调用链 = handler →
   `_get_key_manager()`（零参）→ `.store(provider, api_key)`（同步）。

6. 【llm-keys 集成断言（spec §4.7）】patch `_get_key_manager` 返回
   【真实】APIKeyManager(secret_key=TEST_SECRET_KEY, storage_dir=tmp_path)
   → POST 后：密文文件 `<tmp>/<provider>.json` 落盘存在、文件内容不含
   明文 api_key（AES-256-GCM 密文）、`manager.load(provider)` 回读明文
   与提交值一致（加密落盘 → 解密回读闭环）。

7. llm-keys 错误契约：`_get_key_manager().store(...)` 抛异常 → 500 +
   body `{"detail": "API Key 存储失败，请稍后重试"}`；内部异常细节
   【不得】泄漏进响应（对齐 ADR-012 / test_writing_api.py 500 通用消息
   风格）。

8. POST /api/v1/settings/llm/test 请求契约（#106 F2 评审拍板修订，
   2026-08-06）：body 为 `{provider: str, model?: str, base_url?: str,
   api_key: str}`。
   - provider/api_key 必填非空（空白串拒绝）→ 422
   - model【可选】（`str | None = None`）——【行为变更】旧契约
     「model 必填 → 422」作废：缺失时回退链 = 注册表
     ProviderConfigService.get_by_name(provider).default_model →
     config.llm_default_model（前端 ProviderDialog 只发
     {provider, base_url, api_key}，评审 #106 F2 拍板）
   - model 提供但空白 → 仍 422（「提供即校验」：缺省回退仅对
     【未提供】生效，空白非缺省）
   - base_url【可选】（`str | None = None`）：非空时透传到 LLM
     客户端构造（openai_api_base 探测），空/缺失不传
   - model 为 LiteLLM 格式 `provider/model`（如
     "deepseek/deepseek-chat"，parse_model_string 口径）

9. 【llm/test 工厂契约】`_get_llm_client(provider, model, api_key) ->
   LLMClientProtocol` 被端点调用；model 入参 = 请求体 model 或回退
   解析值（#8 回退链，2026-08-06 #106 F2）；测试 patch 该函数注入
   FakeLLMClient（实现 LLMClientProtocol 的最小 fake：chat 记录
   messages 并返回预置 ChatResponse / 抛预置异常）。

10. llm/test 成功契约：Fake chat 返回
    ChatResponse(content="ok", model=<model>) → HTTP 200 + body
    `{"ok": true, "provider": <provider>, "model": <model>, "message": "连接成功"}`
    （provider 回显；model 回显 = 实际解析值——请求体 model 或回退值）。
    响应【禁止】包含 api_key 明文。

11. 【llm/test 失败语义决策——硬性契约】Fake chat 抛 LLMRequestError →
    HTTP 200（【不是】4xx/5xx）+ body
    `{"ok": false, "message": "LLM 连接失败，请检查 Provider / 模型 / API Key 配置"}`。
    理由：连通探测是【业务语义成功/失败】，不是 HTTP 错误——渲染层
    store testStatus 'ok'/'fail' 直接映射（spec §4.2.3 消费语义），
    200 + ok:false 避免前端把业务失败误判为请求级错误；内部异常细节
    不得泄漏进 message（通用文案）。

12. 【llm/test 不落盘契约】探测端点【禁止】触碰 APIKeyManager——
    api_key 仅用于本次探测（内存），不存储：patch
    `_get_key_manager` 后 POST /llm/test，断言其零调用。

13. lifespan/TestClient：TestClient(app) 触发 lifespan → create_tables()
    在 CWD 写 ./inkflow.db，与 tests/api 既有测试（test_health.py、
    test_token_auth.py 设计假设 #8）行为一致，已接受，不做规避。

14. 【#106 F2 行为变更驱动（2026-08-06 评审）】llm/test 契约修订：
    model 必填 → 可选（缺省回退注册表 default_model → config.
    llm_default_model）、新增可选 base_url（非空透传 LLM 客户端
    openai_api_base 探测）。对应旧用例「model 缺失 → 422」已删除
    （改写为 test_probe_without_model_falls_back 的 200 契约）；
    「model 空白 → 422」保留（提供即校验口径）。

════════════════════════════════════════════════════════════════════
RED 阶段预期：`inkflow.api.routers.settings` 模块不存在 →
本文件【收集期 ModuleNotFoundError】全部用例 ERROR（settings router
未注册，请求亦 404）。GREEN 阶段：按上述契约实现
api/routers/settings.py + app.py include_router 后全绿。
════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from inkflow.api.app import app
from inkflow.api.routers import (
    settings,  # noqa: F401  # RED 收集断言：模块存在性契约（GREEN 实现后即被使用）
)
from inkflow.domain.ports.llm_client import ChatMessage, ChatResponse
from inkflow.domain.ports.llm_errors import LLMRequestError
from inkflow.infrastructure.llm.key_manager import APIKeyManager

# ── 契约常量 ──
ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量（spec §2.3.1）：本文件全部用例依赖未设置 → 直通。"""

ENDPOINT_KEYS = "/api/v1/settings/llm-keys"
"""API Key 加密存储端点（spec §4.4，Q3 拍板）。"""

ENDPOINT_TEST = "/api/v1/settings/llm/test"
"""LLM 连通探测端点（spec §4.6，Q3 拍板）。"""

TEST_PROVIDER = "deepseek"
"""测试 Provider 名。"""

TEST_MODEL = "deepseek/deepseek-chat"
"""测试模型（LiteLLM 格式 provider/model，parse_model_string 口径）。"""

TEST_API_KEY = "sk-test-79-9f3aB7c2dE"
"""测试 API Key 明文（断言其不得出现在任何响应/密文文件中）。"""

TEST_SECRET_KEY = "5f4dcc3b5aa765d61d8327deb882cf99" * 2
"""测试 AES-256-GCM 密钥：64 hex 字符 = 32 字节（bytes.fromhex 要求）。"""

TEST_BASE_URL = "https://custom.example.com/v1"
"""测试 base_url（#106 F2：非空时透传 LLM 客户端 openai_api_base 探测）。"""


# ── Fixtures ──


@pytest.fixture
def client(monkeypatch):
    """FastAPI TestClient 实例（函数级，与 tests/api 既有风格一致）。

    设计假设 #2：显式 delenv INKFLOW_SERVER_TOKEN → token 中间件直通，
    全部用例无 token 直连；monkeypatch 自动还原，测试间互不污染。
    触发 lifespan → create_tables()，行为与 test_health.py 相同（#13）。
    """
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    return TestClient(app)


def _probe_payload(**overrides) -> dict:
    """llm/test 请求体工厂 — 默认全字段合法，可覆盖任意字段。"""
    payload = {
        "provider": TEST_PROVIDER,
        "model": TEST_MODEL,
        "api_key": TEST_API_KEY,
    }
    payload.update(overrides)
    return payload


def _probe_payload_without_model(**overrides) -> dict:
    """llm/test 请求体工厂 — 不带 model（#106 F2：前端 ProviderDialog 口径）。

    前端 ProviderDialog 只发 {provider, base_url, api_key}；model 缺失
    时 GREEN 必须走回退链（注册表 default_model → config.llm_default_model），
    不得 422。
    """
    payload = {
        "provider": TEST_PROVIDER,
        "api_key": TEST_API_KEY,
    }
    payload.update(overrides)
    return payload


class FakeLLMClient:
    """实现 LLMClientProtocol 的最小 fake — 记录调用并返回预置响应/异常。

    设计假设 #9：端点经 `_get_llm_client(provider, model, api_key)` 工厂
    获取客户端后调用 `await client.chat(messages, ...)`；fake 记录
    messages 供断言（探测消息非空），成功返回预置 ChatResponse，
    失败抛预置异常（LLMRequestError）。
    """

    def __init__(
        self,
        *,
        response: ChatResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self._response = response
        self._error = error
        self.messages: list[ChatMessage] = []

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: object,
    ) -> ChatResponse:
        self.messages = list(messages)
        if self._error is not None:
            raise self._error
        if self._response is not None:
            return self._response
        return ChatResponse(content="ok", model=model or "fake/model")


# ── POST /api/v1/settings/llm-keys（spec §4.4 / §4.7 集成）──


class TestLLMKeysStore:
    """API Key 加密存储端点契约（设计假设 #4-#7）。"""

    @pytest.mark.parametrize(
        "body",
        [
            {"api_key": TEST_API_KEY},  # provider 缺失
            {"provider": TEST_PROVIDER},  # api_key 缺失
            {},  # 全缺失
            {"provider": "   ", "api_key": TEST_API_KEY},  # provider 空白
            {"provider": TEST_PROVIDER, "api_key": "   "},  # api_key 空白
            {
                "provider": "../../x",
                "api_key": TEST_API_KEY,
            },  # 路径穿越字符（L5 白名单）
        ],
        ids=[
            "provider_missing",
            "api_key_missing",
            "all_missing",
            "provider_blank",
            "api_key_blank",
            "provider_path_traversal",
        ],
    )
    def test_validation_422(self, client, body):
        """provider/api_key 缺失或空白 → 422（Pydantic 校验，未到达存储层）。

        设计假设 #4：必填非空契约；GREEN 需 strip 后校验非空
        （与 F3 WritingRequest outline 空白拒绝行为对齐）。
        """
        resp = client.post(ENDPOINT_KEYS, json=body)
        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], list)

    def test_extra_fields_ignored(self, client):
        """多余字段忽略（不 422）→ 201（设计假设 #4：Pydantic v2 默认行为）。"""
        with patch("inkflow.api.routers.settings._get_key_manager") as mock_get_km:
            mock_km = MagicMock()
            mock_get_km.return_value = mock_km
            resp = client.post(
                ENDPOINT_KEYS,
                json={
                    "provider": TEST_PROVIDER,
                    "api_key": TEST_API_KEY,
                    "foo": "bar",
                },
            )
        assert resp.status_code == 201
        mock_get_km.assert_called_once_with()
        mock_km.store.assert_called_once_with(TEST_PROVIDER, TEST_API_KEY)

    def test_store_success_contract(self, client):
        """成功：201 + {provider, status: saved}；响应不回显 api_key 明文。

        设计假设 #5：调用链 = `_get_key_manager()`（零参）→
        `.store(provider, api_key)`（同步）；【安全红线】响应体不得含
        api_key 明文。
        """
        with patch("inkflow.api.routers.settings._get_key_manager") as mock_get_km:
            mock_km = MagicMock()
            mock_get_km.return_value = mock_km
            resp = client.post(
                ENDPOINT_KEYS,
                json={"provider": TEST_PROVIDER, "api_key": TEST_API_KEY},
            )
        assert resp.status_code == 201
        assert resp.json() == {"provider": TEST_PROVIDER, "status": "saved"}
        assert TEST_API_KEY not in resp.text
        mock_get_km.assert_called_once_with()
        mock_km.store.assert_called_once_with(TEST_PROVIDER, TEST_API_KEY)

    def test_store_success_real_manager_encrypted_roundtrip(self, client, tmp_path):
        """集成断言（spec §4.7）：真实 APIKeyManager + tmp_path 落盘 → 解密回读。

        设计假设 #6：patch `_get_key_manager` 注入真实
        APIKeyManager(secret_key=TEST_SECRET_KEY, storage_dir=tmp_path)
        → POST 后密文文件 `<tmp>/<provider>.json` 存在、内容不含明文
        api_key（AES-256-GCM 密文）、`manager.load(provider)` 回读明文
        与提交值一致（加密落盘 → 解密回读闭环）。
        """
        manager = APIKeyManager(
            secret_key=TEST_SECRET_KEY,
            storage_dir=tmp_path,
        )
        with patch(
            "inkflow.api.routers.settings._get_key_manager", return_value=manager
        ) as mock_get_km:
            resp = client.post(
                ENDPOINT_KEYS,
                json={"provider": TEST_PROVIDER, "api_key": TEST_API_KEY},
            )
        assert resp.status_code == 201
        assert resp.json() == {"provider": TEST_PROVIDER, "status": "saved"}
        assert TEST_API_KEY not in resp.text
        mock_get_km.assert_called_once_with()

        # 落盘文件 = 密文（.json，AES-256-GCM），非明文
        key_file = tmp_path / f"{TEST_PROVIDER}.json"
        assert key_file.exists()
        on_disk = key_file.read_text(encoding="utf-8")
        assert TEST_API_KEY not in on_disk
        assert "ciphertext_b64" in on_disk and "nonce_b64" in on_disk
        # 回读闭环：decrypt/load 与提交明文一致
        assert manager.load(TEST_PROVIDER) == TEST_API_KEY

    def test_store_error_500_generic_detail(self, client):
        """store 抛异常 → 500 + 通用 detail；内部细节不泄漏（设计假设 #7）。"""
        with patch("inkflow.api.routers.settings._get_key_manager") as mock_get_km:
            mock_km = MagicMock()
            mock_km.store.side_effect = OSError("disk full")
            mock_get_km.return_value = mock_km
            resp = client.post(
                ENDPOINT_KEYS,
                json={"provider": TEST_PROVIDER, "api_key": TEST_API_KEY},
            )
        assert resp.status_code == 500
        assert resp.json()["detail"] == "API Key 存储失败，请稍后重试"
        assert "disk full" not in resp.text
        assert TEST_API_KEY not in resp.text


# ── POST /api/v1/settings/llm/test（spec §4.6 / §4.8 M5）──


class TestLLMTestProbe:
    """LLM 连通探测端点契约（设计假设 #8-#12）。"""

    @pytest.mark.parametrize(
        "body",
        [
            {"model": TEST_MODEL, "api_key": TEST_API_KEY},  # provider 缺失
            {"provider": TEST_PROVIDER, "model": TEST_MODEL},  # api_key 缺失
            {"provider": "   ", "model": TEST_MODEL, "api_key": TEST_API_KEY},
            {"provider": TEST_PROVIDER, "model": "   ", "api_key": TEST_API_KEY},
            {"provider": TEST_PROVIDER, "model": TEST_MODEL, "api_key": "   "},
            {
                "provider": "../../x",
                "model": TEST_MODEL,
                "api_key": TEST_API_KEY,
            },  # 路径穿越（L5）
        ],
        ids=[
            "provider_missing",
            "api_key_missing",
            "provider_blank",
            "model_blank",
            "api_key_blank",
            "provider_path_traversal",
        ],
    )
    def test_validation_422(self, client, body):
        """provider/api_key 缺失或空白、model 空白 → 422（设计假设 #8）。

        【#106 F2 行为变更】model 缺失【不再】422（model 可选，缺省回退
        注册表 default_model → config.llm_default_model）——原
        model_missing 用例已从本表移除，改由
        test_probe_without_model_falls_back 契约 200；model 提供但空白
        仍 422（提供即校验：缺省回退仅对【未提供】生效）。
        """
        resp = client.post(ENDPOINT_TEST, json=body)
        assert resp.status_code == 422
        assert isinstance(resp.json()["detail"], list)

    def test_probe_success_ok_true(self, client):
        """成功：200 + {ok: true, provider, model, message}；api_key 不回显。

        设计假设 #9/#10：`_get_llm_client(provider, model, api_key)` 被
        调用且入参透传三字段；Fake chat 返回 ChatResponse(content="ok",
        model=<model>) → model/provider 回显。
        """
        fake = FakeLLMClient(response=ChatResponse(content="ok", model=TEST_MODEL))
        with patch(
            "inkflow.api.routers.settings._get_llm_client", return_value=fake
        ) as mock_factory:
            resp = client.post(ENDPOINT_TEST, json=_probe_payload())
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["provider"] == TEST_PROVIDER
        assert body["model"] == TEST_MODEL
        assert body["message"] == "连接成功"
        assert TEST_API_KEY not in resp.text
        mock_factory.assert_called_once_with(TEST_PROVIDER, TEST_MODEL, TEST_API_KEY)
        assert fake.messages, "探测消息列表不得为空"

    def test_probe_failure_ok_false(self, client):
        """Fake chat 抛 LLMRequestError → HTTP 200 + {ok: false, message}。

        设计假设 #11：连通探测是【业务语义成功/失败】而非 HTTP 错误
        （渲染层 store testStatus 'ok'/'fail' 直接映射）；内部异常细节
        不泄漏进 message（通用文案）。
        """
        fake = FakeLLMClient(error=LLMRequestError("401 Invalid API key"))
        with patch(
            "inkflow.api.routers.settings._get_llm_client", return_value=fake
        ) as mock_factory:
            resp = client.post(ENDPOINT_TEST, json=_probe_payload())
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert body["message"] == "LLM 连接失败，请检查 Provider / 模型 / API Key 配置"
        assert "401 Invalid API key" not in resp.text
        assert TEST_API_KEY not in resp.text
        mock_factory.assert_called_once_with(TEST_PROVIDER, TEST_MODEL, TEST_API_KEY)

    def test_probe_does_not_store_api_key(self, client):
        """探测端点不落盘：_get_key_manager 零调用（设计假设 #12）。

        api_key 仅用于本次探测（内存），禁止触碰 APIKeyManager——
        即使探测成功也不得触发任何存储路径。
        """
        with (
            patch("inkflow.api.routers.settings._get_key_manager") as mock_get_km,
            patch(
                "inkflow.api.routers.settings._get_llm_client",
                return_value=FakeLLMClient(
                    response=ChatResponse(content="ok", model=TEST_MODEL)
                ),
            ) as mock_factory,
        ):
            resp = client.post(ENDPOINT_TEST, json=_probe_payload())
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock_get_km.assert_not_called()
        mock_factory.assert_called_once_with(TEST_PROVIDER, TEST_MODEL, TEST_API_KEY)

    def test_probe_without_model_falls_back(self, client):
        """不带 model → 200 + ok:true（#106 F2：回退注册表 default_model
        → config.llm_default_model）。

        请求体仅 {provider, api_key}（前端 ProviderDialog 口径）——旧契约
        model 必填 → 422，本用例即 RED 形态（当前实现仍 422）。GREEN：
        端点经回退链解析 model 后仍走 `_get_llm_client` 工厂；断言工厂
        收到非空 model、响应 model 回显与之一致（不契约回退链精确值——
        依赖注册表查询 seam 与数据状态，只约束「回退结果非空且可消费」）。
        """
        fake = FakeLLMClient(
            response=ChatResponse(content="ok", model="resolved/model")
        )
        with patch(
            "inkflow.api.routers.settings._get_llm_client", return_value=fake
        ) as mock_factory:
            resp = client.post(ENDPOINT_TEST, json=_probe_payload_without_model())
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["message"] == "连接成功"
        assert TEST_API_KEY not in resp.text
        mock_factory.assert_called_once()
        call = mock_factory.call_args
        resolved_model = call.args[1] if call.args else call.kwargs.get("model")
        assert (
            isinstance(resolved_model, str) and resolved_model.strip()
        ), "回退解析的 model 不得为空（注册表 default_model → config.llm_default_model）"
        assert body["model"] == resolved_model, "响应 model 回显必须等于实际解析值"
        assert fake.messages, "探测消息列表不得为空"

    def test_probe_base_url_passthrough_to_client(self, client):
        """base_url 非空 → 透传 LangChainLLMClient 构造（#106 F2：openai_api_base 探测）。

        请求体带 base_url（前端 ProviderDialog 必发字段）→ 客户端构造
        必须收到 openai_api_base=base_url。当前实现 LLMTestRequest 无
        base_url 字段（多余字段被忽略）→ 客户端收不到 → 本用例 RED。
        """
        with patch("inkflow.api.routers.settings.LangChainLLMClient") as mock_cls:
            resp = client.post(
                ENDPOINT_TEST,
                json={
                    "provider": TEST_PROVIDER,
                    "model": TEST_MODEL,
                    "api_key": TEST_API_KEY,
                    "base_url": TEST_BASE_URL,
                },
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock_cls.assert_called_once_with(
            default_model=TEST_MODEL,
            api_key=TEST_API_KEY,
            openai_api_base=TEST_BASE_URL,
        )

    def test_probe_real_factory_assembles_provider_model(self, client):
        """真实工厂 + 纯模型名 → default_model 组装 provider/model（评审 L2）。

        前端输入纯模型名（如 deepseek-chat），parse_model_string 要求 provider/model
        格式（无 / 即 ValueError → 恒 ok:false）。工厂必须组装：model 不含 '/' 时
        → f"{provider}/{model}"；已含 '/'（LiteLLM 格式）则原样透传。
        """
        with patch("inkflow.api.routers.settings.LangChainLLMClient") as mock_cls:
            resp = client.post(
                ENDPOINT_TEST,
                json={
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "api_key": TEST_API_KEY,
                },
            )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock_cls.assert_called_once_with(
            default_model="deepseek/deepseek-chat", api_key=TEST_API_KEY
        )

    def test_probe_real_factory_passthrough_litellm_model(self, client):
        """真实工厂 + 已含 '/' 的 LiteLLM 格式模型 → 原样透传（不重复组装）。"""
        with patch("inkflow.api.routers.settings.LangChainLLMClient") as mock_cls:
            resp = client.post(
                ENDPOINT_TEST,
                json={
                    "provider": "deepseek",
                    "model": "deepseek/deepseek-chat",
                    "api_key": TEST_API_KEY,
                },
            )
        assert resp.status_code == 200
        mock_cls.assert_called_once_with(
            default_model="deepseek/deepseek-chat", api_key=TEST_API_KEY
        )
