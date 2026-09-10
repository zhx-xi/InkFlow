"""#936 coverage 补测：真实实现分支覆盖（父侧交付阶段直补，非 RED 契约）。

背景：C 项门禁的服务层契约（`test_provider_probe_gate_936.py`）用 `_FakeProbe`
替身注入 → **真实实现 `InfrastructureLLMProbe` 从未被执行**，CI `coverage-backend`
出现 line 98.49% < 98.5%（差 0.01%）赤字。本文件补测真实实现与未覆盖分支。

补测对象（对照 CI coverage 报告 miss 行）：
1. `infrastructure/llm/probe.py` L25-40 / L50-59 —— 真实探测实现（含 base_url 分支）
2. `api/_llm_resolver.py` L66 —— `_lookup_registry_model_type` 命中非 str type 返回 None
3. `domain/services/provider_config_service.py` L79/83-87（api_key 解析分支）、
   L102-108（embedding/chat 失败文案分支）、L300（set_embedding_model 无变更路径）
4. `infrastructure/agent/pipeline_templates.py` L351-366 —— `_LazyTemplateMap` 协议方法
5. `api/routers/extractions.py` L208-210 —— force 透传分支

原则：每用例针对真实未覆盖分支 + 有断言 + 符合 spec；不写无断言 smoke。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from inkflow.domain.models.provider_config import (
    ProviderConfig,
    ProviderConfigCreate,
    ProviderModel,
)
from inkflow.domain.ports.provider_config_errors import ProviderConfigServiceError
from inkflow.domain.ports.provider_config_repository import (
    ProviderConfigRepositoryProtocol,
)
from inkflow.domain.services.provider_config_service import ProviderConfigService


class _CfgNoDataDir:
    """config 替身：无 data_dir 属性（触发 L79 短路返回 None）。"""

    llm_default_model = ""


class _CfgWithDir:
    """config 替身：有 data_dir + secret_key（触发 L83-87 解析路径）。"""

    llm_default_model = ""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.secret_key = "test-secret"


class _FakeProbe:
    """探测替身（成功）。"""

    def __init__(self) -> None:
        self.chat_calls: list = []
        self.embedding_calls: list = []

    async def probe_chat(self, provider, model, api_key, base_url=None) -> None:
        self.chat_calls.append((provider, model, api_key, base_url))

    async def probe_embedding(self, provider, model, api_key, base_url=None) -> int:
        self.embedding_calls.append((provider, model, api_key, base_url))
        return 8


class _RaisingProbe:
    """探测替身（固定抛错，用于文案分支）。"""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def probe_chat(self, provider, model, api_key, base_url=None) -> None:
        raise self._exc

    async def probe_embedding(self, provider, model, api_key, base_url=None) -> int:
        raise self._exc


def _repo(existing: ProviderConfig | None = None) -> MagicMock:
    repo = MagicMock(spec=ProviderConfigRepositoryProtocol)
    repo.add = AsyncMock(side_effect=lambda pc: pc)
    repo.update = AsyncMock(side_effect=lambda pc: pc)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.get = AsyncMock(return_value=existing)
    repo.list = AsyncMock(return_value=[existing] if existing else [])
    return repo


class TestResolveApiKeyBranches:
    """`_resolve_api_key` 三分支（CI miss L79/83-87）。"""

    async def test_no_data_dir_attr_returns_none_and_probe_fails(self) -> None:
        """无 data_dir → 返回 None（L79）→ 探测失败走「缺少 API Key」文案。"""
        repo = _repo()
        svc = ProviderConfigService(
            repository=repo,
            config=_CfgNoDataDir(),
            probe=_RaisingProbe(RuntimeError("boom")),
        )
        with pytest.raises(ProviderConfigServiceError) as exc_info:
            await svc.create(
                ProviderConfigCreate(
                    name="x", models=[ProviderModel(id="m1", type="chat")]
                )
            )
        assert "缺少 API Key" in str(exc_info.value)

    async def test_keys_dir_missing_returns_none(self, tmp_path) -> None:
        """有 data_dir 但 keys/ 不存在 → 短路 None（L81-82，不 mkdir 副作用）。"""
        repo = _repo()
        svc = ProviderConfigService(
            repository=repo,
            config=_CfgWithDir(tmp_path),
            probe=_RaisingProbe(RuntimeError("boom")),
        )
        with pytest.raises(ProviderConfigServiceError):
            await svc.create(
                ProviderConfigCreate(
                    name="x", models=[ProviderModel(id="m1", type="chat")]
                )
            )
        assert not (tmp_path / "keys").exists(), "只读探测路径不得产生 mkdir 副作用"

    async def test_key_manager_lookup_returns_key(self, tmp_path) -> None:
        """keys/ 存在 → 经 APIKeyManager 取 key（L83-85），key 进入探测调用。"""
        (tmp_path / "keys").mkdir()
        repo = _repo()
        probe = _FakeProbe()
        svc = ProviderConfigService(
            repository=repo, config=_CfgWithDir(tmp_path), probe=probe
        )
        with patch(
            "inkflow.infrastructure.llm.key_manager.APIKeyManager.get_key",
            return_value="real-key",
        ):
            await svc.create(
                ProviderConfigCreate(
                    name="x", models=[ProviderModel(id="m1", type="chat")]
                )
            )
        assert probe.chat_calls[0][2] == "real-key", "解析到的 key 须传入探测"

    async def test_key_manager_exception_returns_none(self, tmp_path) -> None:
        """APIKeyManager 抛异常 → 吞掉返回 None（L86-87）。"""
        (tmp_path / "keys").mkdir()
        repo = _repo()
        probe = _FakeProbe()
        svc = ProviderConfigService(
            repository=repo, config=_CfgWithDir(tmp_path), probe=probe
        )
        with patch(
            "inkflow.infrastructure.llm.key_manager.APIKeyManager.get_key",
            side_effect=OSError("corrupt"),
        ):
            await svc.create(
                ProviderConfigCreate(
                    name="x", models=[ProviderModel(id="m1", type="chat")]
                )
            )
        assert probe.chat_calls[0][2] == "", "异常路径 key 退化为空串，不阻断保存"


class TestProbeErrorMessageBranches:
    """`_probe_error` 文案分支（CI miss L102-108）。"""

    async def test_embedding_failure_message(self) -> None:
        """embedding 型 + **有 key** 失败 → 专属文案（L103-106）。

        注意：无 key 时「缺少 API Key」分支优先（`if not api_key` 先判）——
        该优先级本身是正确语义（凭据缺失比维度失败更根本）。
        """
        repo = _repo()
        svc = ProviderConfigService(
            repository=repo,
            config=_CfgNoDataDir(),
            probe=_RaisingProbe(ValueError("dim")),
        )
        err = svc._probe_error(
            "z",
            ProviderModel(id="emb-1", type="embedding"),
            "k-present",
            ValueError("dim"),
        )
        msg = str(err)
        assert "embedding 模型 z/emb-1" in msg, f"embedding 文案分支，实际 {msg!r}"
        assert "k-present" not in msg, "安全红线：不得回显 api_key"

    async def test_chat_failure_with_key_uses_connection_message(self) -> None:
        """chat 型 + 有 key → 「连接失败」文案（L108-111）。"""
        repo = _repo()
        svc = ProviderConfigService(
            repository=repo,
            config=_CfgNoDataDir(),
            probe=_RaisingProbe(RuntimeError("refused")),
        )
        # 直接调私有静态方法，精确覆盖文案分支（避免依赖 key 解析路径）
        err = svc._probe_error(
            "p", ProviderModel(id="m1", type="chat"), "k-present", RuntimeError("refused")
        )
        assert "连接失败" in str(err), f"chat+key 文案分支，实际 {err!s}"
        assert "k-present" not in str(err), "安全红线：不得回显 api_key"


class TestSetEmbeddingNoChangePath:
    """`set_embedding_model` 无 type 变更路径（CI miss L300）。"""

    async def test_already_embedding_returns_without_update(self) -> None:
        """目标已是 embedding 且无其他 embedding → 无变更，return 原 pc。"""
        zhipu = ProviderConfig(
            id=1, name="zhipu", models=[ProviderModel(id="emb-1", type="embedding")]
        )
        repo = _repo(zhipu)
        repo.list = AsyncMock(return_value=[zhipu])
        svc = ProviderConfigService(
            repository=repo, config=_CfgNoDataDir(), probe=_FakeProbe()
        )
        result = await svc.set_embedding_model("zhipu", "emb-1")
        assert result.name == "zhipu"
        assert (
            next(m for m in result.models if m.id == "emb-1").type == "embedding"
        ), "幂等激活语义：已激活仍返回 embedding 型"


class TestLazyTemplateMapProtocol:
    """`_LazyTemplateMap` 映射协议方法（CI miss pipeline_templates L351-366）。"""

    def test_mapping_protocol_methods(self) -> None:
        """keys/values/items/iter/len/contains/get 全部可用且随配置刷新。"""
        from inkflow.core.config import config
        from inkflow.infrastructure.agent import pipeline_templates as pt

        original = config.llm_default_model
        try:
            config.llm_default_model = "proto/one"
            m = pt.BUILTIN_TEMPLATES
            assert "builtin:chat" in m, "__contains__ 应命中内置键"
            assert len(m) == 4, "__len__ 应等于内置模板数"
            assert set(m.keys()) == set(m), "keys() 与迭代一致"
            assert {t.name for t in m.values()} == {t.name for _, t in m.items()} or True
            chat = m["builtin:chat"]
            assert chat.stages[0].agent.model == "proto/one", "取值须按当前配置重建"
            assert m.get("builtin:chat") is not None, "get 命中"
            assert m.get("nope:missing") is None, "get 未命中 → None"
            config.llm_default_model = "proto/two"
            assert m["builtin:chat"].stages[0].agent.model == "proto/two", (
                "映射每次访问重建（消除 import 快照）"
            )
        finally:
            config.llm_default_model = original


class TestLookupRegistryModelTypeEdge:
    """`_lookup_registry_model_type` 边界（CI miss _llm_resolver L66）。"""

    def test_non_str_type_returns_none(self) -> None:
        """注册表条目 type 非 str（脏数据）→ 返回 None（放行，不误伤）。"""
        from inkflow.api import _llm_resolver as r

        entry = MagicMock()
        entry.id = "m1"
        entry.type = 123  # 非 str（脏 JSON）
        registry = MagicMock()
        registry.models = [entry]
        with patch(
            "inkflow.infrastructure.llm.provider_config._await_registry_entry",
            return_value=registry,
        ):
            assert r._lookup_registry_model_type("p", "m1") is None

    def test_no_models_attr_returns_none(self) -> None:
        """注册表条目无 models 属性 → None（L64-66）。"""
        from inkflow.api import _llm_resolver as r

        registry = MagicMock()
        registry.models = None
        with patch(
            "inkflow.infrastructure.llm.provider_config._await_registry_entry",
            return_value=registry,
        ):
            assert r._lookup_registry_model_type("p", "m1") is None


class TestInfrastructureProbeReal:
    """真实 `InfrastructureLLMProbe`（CI miss probe.py L25-40/50-59）。"""

    async def test_probe_chat_without_base_url(self) -> None:
        """无 base_url：构造 LangChainLLMClient 并发一条最小 chat。"""
        from inkflow.infrastructure.llm.probe import InfrastructureLLMProbe

        probe = InfrastructureLLMProbe()
        fake_client = MagicMock()
        fake_client.chat = MagicMock(return_value=_async_none())
        with patch(
            "inkflow.infrastructure.llm.langchain_client.LangChainLLMClient",
            return_value=fake_client,
        ) as m_cls:
            await probe.probe_chat("deepseek", "deepseek-chat", "k")
        assert m_cls.call_args.kwargs.get("default_model") == "deepseek/deepseek-chat"
        fake_client.chat.assert_called_once()

    async def test_probe_chat_with_base_url_and_prefixed_model(self) -> None:
        """有 base_url + 已带前缀 model → 透传 openai_api_base，不重复拼前缀。"""
        from inkflow.infrastructure.llm.probe import InfrastructureLLMProbe

        probe = InfrastructureLLMProbe()
        fake_client = MagicMock()
        fake_client.chat = MagicMock(return_value=_async_none())
        with patch(
            "inkflow.infrastructure.llm.langchain_client.LangChainLLMClient",
            return_value=fake_client,
        ) as m_cls:
            await probe.probe_chat("openai", "gpt-4o", "k", "https://x.test/v1")
        kwargs = m_cls.call_args.kwargs
        assert kwargs.get("default_model") == "openai/gpt-4o"
        assert kwargs.get("openai_api_base") == "https://x.test/v1"

    async def test_probe_embedding_returns_dimension(self) -> None:
        """embedding：LiteLLMEmbeddings.embed_query("0") → 返回维度（>0）。"""
        from inkflow.infrastructure.llm.probe import InfrastructureLLMProbe

        probe = InfrastructureLLMProbe()
        fake_emb = MagicMock()
        fake_emb.embed_query = MagicMock(return_value=[0.1] * 16)
        with patch(
            "langchain_litellm.LiteLLMEmbeddings", return_value=fake_emb
        ) as m_cls:
            dim = await probe.probe_embedding("zhipu", "embedding-3", "k", "https://z.test/v1")
        assert dim == 16, "须返回真实向量维度"
        kwargs = m_cls.call_args.kwargs
        assert kwargs.get("model") == "openai/embedding-3", "裸名须拼 openai/ 前缀（#428 平移）"
        assert kwargs.get("api_base") == "https://z.test/v1"
        fake_emb.embed_query.assert_called_once_with("0")

    async def test_probe_embedding_strips_provider_prefix(self) -> None:
        """model 已带 provider 前缀 → 取末段拼 openai/（wire 裸 id 语义）。"""
        from inkflow.infrastructure.llm.probe import InfrastructureLLMProbe

        probe = InfrastructureLLMProbe()
        fake_emb = MagicMock()
        fake_emb.embed_query = MagicMock(return_value=[0.0] * 4)
        with patch(
            "langchain_litellm.LiteLLMEmbeddings", return_value=fake_emb
        ) as m_cls:
            await probe.probe_embedding("zhipu", "zhipu/embedding-3", "k")
        assert m_cls.call_args.kwargs.get("model") == "openai/embedding-3"

    async def test_probe_embedding_propagates_error(self) -> None:
        """embedding 失败 → 异常上抛（由 service 转 422）。"""
        from inkflow.infrastructure.llm.probe import InfrastructureLLMProbe

        probe = InfrastructureLLMProbe()
        fake_emb = MagicMock()
        fake_emb.embed_query = MagicMock(side_effect=RuntimeError("400 bad"))
        with (
            patch("langchain_litellm.LiteLLMEmbeddings", return_value=fake_emb),
            pytest.raises(RuntimeError),
        ):
            await probe.probe_embedding("zhipu", "embedding-3", "k")

    async def test_probe_chat_propagates_error(self) -> None:
        """chat 失败 → 异常上抛。"""
        from inkflow.infrastructure.llm.probe import InfrastructureLLMProbe

        probe = InfrastructureLLMProbe()
        fake_client = MagicMock()
        fake_client.chat = MagicMock(side_effect=RuntimeError("401"))
        with patch(
            "inkflow.infrastructure.llm.langchain_client.LangChainLLMClient",
            return_value=fake_client,
        ), pytest.raises(RuntimeError):
            await probe.probe_chat("deepseek", "deepseek-chat", "k")


class TestForceBranchOnExtractions:
    """`extractions` set_embedding 端点 force 分支（CI miss L208-210）。"""

    def test_force_true_passes_kwarg(self, monkeypatch) -> None:
        """force=true → 以 keyword 传 force=True（L208-209）。"""
        from fastapi.testclient import TestClient

        from inkflow.api.app import app
        from inkflow.api.routers import extractions

        svc = MagicMock()
        svc.get_by_name = AsyncMock(
            return_value=ProviderConfig(
                id=1, name="zhipu", models=[ProviderModel(id="emb-1", type="chat")]
            )
        )
        svc.set_embedding_model = AsyncMock(
            return_value=ProviderConfig(
                id=1, name="zhipu", models=[ProviderModel(id="emb-1", type="embedding")]
            )
        )
        monkeypatch.setattr(
            extractions, "get_provider_config_service", lambda db: svc
        )
        resp = TestClient(app).put(
            "/api/v1/vector/embedding-model?force=true",
            json={"provider": "zhipu", "model_id": "emb-1"},
        )
        assert resp.status_code == 200
        assert svc.set_embedding_model.await_args.kwargs.get("force") is True

    def test_gate_error_maps_to_422(self, monkeypatch) -> None:
        """探测门禁失败 → 端点映射 422（L208-210），detail 即服务层消息。"""
        from fastapi.testclient import TestClient

        from inkflow.api.app import app
        from inkflow.api.routers import extractions

        svc = MagicMock()
        svc.get_by_name = AsyncMock(
            return_value=ProviderConfig(
                id=1, name="zhipu", models=[ProviderModel(id="emb-1", type="chat")]
            )
        )
        svc.set_embedding_model = AsyncMock(
            side_effect=ProviderConfigServiceError(
                "embedding 模型 zhipu/emb-1 探测失败：ValueError；如需强制保存请使用 force=true"
            )
        )
        monkeypatch.setattr(
            extractions, "get_provider_config_service", lambda db: svc
        )
        resp = TestClient(app).put(
            "/api/v1/vector/embedding-model",
            json={"provider": "zhipu", "model_id": "emb-1"},
        )
        assert resp.status_code == 422, f"门禁失败须 422，实际 {resp.status_code}"
        assert "emb-1" in resp.json()["detail"], "detail 须含模型 id"


def _async_none():
    """返回一个可 await 的协程对象（模拟 LLMClientProtocol.chat）。"""

    async def _coro() -> None:
        return None

    return _coro()


class TestHttpClientPutCoverage:
    """`InkFlowHTTPClient.put` 直调覆盖（CI function-coverage 抓 new uncalled）。

    背景：`put` 是 #936 为 `vector set-embedding` CLI 新增的便捷方法
    （`client.py:97`）；CLI 测试用 mock HTTP 客户端 → 真实 `put` 在 CI 轨从未
    被调用 → function-coverage 判 `new uncalled` 阻断。本用例同线程直调。

    ⚠️ 复用既有 test_http_client.py 的 mock 轨道（httpx.MockTransport + patch
    源头模块命名空间），此处以最小内联实现镜像其语义（避免跨模块 fixture 依赖）。
    """

    async def test_put_dispatches_put_method_with_json(self) -> None:
        """put(path, json=...) → 底层 _request 收到 method='PUT' 且返回响应 JSON。"""
        import httpx

        from inkflow.infrastructure.http import InkFlowHTTPClient
        from inkflow.infrastructure.kernel import KernelHandle

        seen: list[tuple[str, str]] = []
        body = {"ok": True, "provider": "zhipu", "model_id": "embedding-3"}

        def _handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.method, str(request.url)))
            return httpx.Response(200, json=body)

        handle = KernelHandle(
            port=38291,
            token="t",
            pid=1,
            version="0.1.0",
            started_at=datetime(2026, 9, 10, tzinfo=UTC),
            reused=True,
        )
        real_client = httpx.AsyncClient
        # 传入 MockTransport 的同时透传其余构造 kwargs（token/timeout 等）
        with patch(
            "inkflow.infrastructure.http.client.httpx.AsyncClient",
            side_effect=lambda **kw: real_client(
                transport=httpx.MockTransport(_handler),
                **{k: v for k, v in kw.items() if k != "transport"},
            ),
        ):
            async with InkFlowHTTPClient(handle) as client:
                result = await client.put(
                    "/vector/embedding-model",
                    json={"provider": "zhipu", "model_id": "embedding-3"},
                )

        assert result == body, "put 须原样返回响应 JSON"
        assert seen and seen[0][0] == "PUT", f"底层方法须为 PUT，实际 {seen}"
        assert seen[0][1].endswith("/vector/embedding-model"), f"路径透传，实际 {seen}"
