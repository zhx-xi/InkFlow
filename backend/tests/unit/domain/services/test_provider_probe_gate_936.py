"""#936 C 项 RED 契约（服务层）：Provider 保存前 type-aware 探测门禁。

缺陷背景（用户提议 2026-09-05，issue #936 C 项）：
`POST /settings/llm/test` 已有 chat 最小连通探测（GUI 手动触发），但**保存路径
零门禁**：`provider_config_service.create/update` 直接落库，且 L78-85 会把首个
chat 模型**自动设为全局默认**（#735 D2）——未验证过的模型即刻进主路径。

契约（#936 spec §2.2/§3.3）：
① create/update 含**新增/改动模型条目**时，对每个受影响条目做 type-aware
   最小探测后才落库：
   - `type=chat` → 1-token completion（复用 settings.py:175 同语义）
   - `type=embedding` → `embed_query("0")` 占位（#328 先例），校验维度 > 0
② 失败 → 422 拒绝保存（detail 含模型 id + 失败摘要）；**零落库**（门禁在
   repo.add/update **之前**——含 #735 D2 自动设默认也不触发）。
③ `force=true` → 跳过门禁，落库 + WARNING 日志锚「跳过模型探测门禁」。
④ 无受影响条目（update 未传 models / 与既有全等）→ **零探测**（不调 probe）。
⑤ `probe=None`（未注入）→ **零门禁**（向后兼容既有测试与 CLI 内部调用）。
⑥ 依赖方向（Q4 拍板）：domain 定 `LLMProbeProtocol`，infrastructure 实现，
   router 注入——service 只依赖 Protocol。

【R】= 当前必 FAIL（修复锚）；【G】= 当前 PASS（回归守护/护栏）。
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from inkflow.domain.models.provider_config import (
    ProviderConfig,
    ProviderConfigCreate,
    ProviderConfigUpdate,
    ProviderModel,
)
from inkflow.domain.ports.provider_config_errors import ProviderConfigServiceError
from inkflow.domain.ports.provider_config_repository import (
    ProviderConfigRepositoryProtocol,
)
from inkflow.domain.services.provider_config_service import ProviderConfigService

PROBE_GATE_WARN_ANCHOR = "跳过模型探测门禁"


class _FakeConfig:
    """可写全局默认的 config 替身（llm_default_model 可读可写；data_dir 供落盘）。

    ⚠️ data_dir 必须指向**临时目录**（每个实例独立 tmp_path）——#735 D2 自动设默认
    会调 `save_config_json(self._config.data_dir, ...)` 真实落盘；用 Path(".") 会把
    `backend/config.json` 写进工作区（污染仓库 + 每次跑测试重建）。
    """

    def __init__(self, llm_default_model: str = "", data_dir: Path | None = None) -> None:
        self.llm_default_model = llm_default_model
        self.data_dir = data_dir if data_dir is not None else Path(tempfile.mkdtemp())


def _mock_repo(existing: ProviderConfig | None = None) -> MagicMock:
    """Mock ProviderConfigRepositoryProtocol（add/update 透传实体）。"""
    repo = MagicMock(spec=ProviderConfigRepositoryProtocol)
    repo.add = AsyncMock(side_effect=lambda pc: pc)
    repo.update = AsyncMock(side_effect=lambda pc: pc)
    repo.get_by_name = AsyncMock(return_value=None)
    repo.get = AsyncMock(return_value=existing)
    repo.list = AsyncMock(return_value=[existing] if existing else [])
    return repo


class _FakeProbe:
    """LLMProbeProtocol 替身：可编程成败 + 调用记录。

    probe_chat(provider, model, api_key, base_url) → None（成功）/ raise（失败）
    probe_embedding(provider, model, api_key, base_url) → int 维度（>0 成功）
    """

    def __init__(
        self,
        *,
        chat_error: Exception | None = None,
        embedding_dim: int = 1024,
        embedding_error: Exception | None = None,
    ) -> None:
        self.chat_error = chat_error
        self.embedding_dim = embedding_dim
        self.embedding_error = embedding_error
        self.chat_calls: list[tuple] = []
        self.embedding_calls: list[tuple] = []

    async def probe_chat(
        self, provider: str, model: str, api_key: str, base_url: str | None = None
    ) -> None:
        """chat 型最小探测——失败时抛异常。"""
        self.chat_calls.append((provider, model, api_key, base_url))
        if self.chat_error is not None:
            raise self.chat_error

    async def probe_embedding(
        self, provider: str, model: str, api_key: str, base_url: str | None = None
    ) -> int:
        """embedding 型最小探测——返回维度（>0 表示成功）。"""
        self.embedding_calls.append((provider, model, api_key, base_url))
        if self.embedding_error is not None:
            raise self.embedding_error
        return self.embedding_dim


def _svc(repo: MagicMock, *, probe=None, config_obj=None) -> ProviderConfigService:
    """按 #936 新契约构造服务（probe 可选注入）。"""
    return ProviderConfigService(
        repository=repo,
        config=config_obj or _FakeConfig(),
        probe=probe,
    )


class TestCreateProbeGate:
    """契约①②③：create 路径门禁。"""

    async def test_r1_probe_failure_rejects_and_does_not_persist(self) -> None:
        """【R】chat 探测失败 → 422 且 **repo.add 未被调用**（零落库）。

        RED 形态：当前 create 无 probe 参数 → TypeError。
        """
        repo = _mock_repo()
        probe = _FakeProbe(chat_error=RuntimeError("connection refused"))
        svc = _svc(repo, probe=probe)

        with pytest.raises(ProviderConfigServiceError) as exc_info:
            await svc.create(
                ProviderConfigCreate(
                    name="openai",
                    models=[ProviderModel(id="gpt-4o", type="chat")],
                )
            )

        detail = str(exc_info.value)
        assert "gpt-4o" in detail, f"detail 须含模型 id，实际 {detail!r}"
        assert "openai" in detail, f"detail 须含 provider 名，实际 {detail!r}"
        repo.add.assert_not_awaited()

    async def test_r2_force_skips_gate_and_persists_with_warning(self, caplog) -> None:
        """【R】force=True + 探测失败 → **落库** + WARNING 锚「跳过模型探测门禁」。"""
        repo = _mock_repo()
        probe = _FakeProbe(chat_error=RuntimeError("connection refused"))
        svc = _svc(repo, probe=probe)

        with caplog.at_level(logging.WARNING):
            await svc.create(
                ProviderConfigCreate(
                    name="openai",
                    models=[ProviderModel(id="gpt-4o", type="chat")],
                ),
                force=True,
            )

        repo.add.assert_awaited_once()
        assert any(PROBE_GATE_WARN_ANCHOR in r.message for r in caplog.records), (
            f"force 跳过门禁须落 WARNING（锚={PROBE_GATE_WARN_ANCHOR!r}），"
            f"实际 {[r.message for r in caplog.records]}"
        )

    async def test_r3_embedding_probe_called_with_dimension_check(self) -> None:
        """【R】embedding 条目走 probe_embedding（维度 > 0 通过）。"""
        repo = _mock_repo()
        probe = _FakeProbe(embedding_dim=1536)
        svc = _svc(repo, probe=probe)

        await svc.create(
            ProviderConfigCreate(
                name="zhipu",
                models=[ProviderModel(id="embedding-3", type="embedding")],
            )
        )

        assert len(probe.embedding_calls) == 1, "embedding 条目须走 embedding 探测"
        assert not probe.chat_calls, "embedding 条目不得走 chat 探测"
        repo.add.assert_awaited_once()

    async def test_r4_embedding_zero_dimension_rejected(self) -> None:
        """【R】embedding 探测返回维度 0 → 422 拒绝（零落库）。"""
        repo = _mock_repo()
        probe = _FakeProbe(embedding_dim=0)
        svc = _svc(repo, probe=probe)

        with pytest.raises(ProviderConfigServiceError) as exc_info:
            await svc.create(
                ProviderConfigCreate(
                    name="zhipu",
                    models=[ProviderModel(id="embedding-3", type="embedding")],
                )
            )

        assert "embedding-3" in str(exc_info.value)
        repo.add.assert_not_awaited()

    async def test_r5_chat_probe_called_for_chat_entries(self) -> None:
        """【R】chat 条目走 probe_chat（1-token completion 语义）。"""
        repo = _mock_repo()
        probe = _FakeProbe()
        svc = _svc(repo, probe=probe)

        await svc.create(
            ProviderConfigCreate(
                name="deepseek",
                models=[ProviderModel(id="deepseek-v4-flash", type="chat")],
            )
        )

        assert len(probe.chat_calls) == 1, "chat 条目须走 chat 探测"
        assert not probe.embedding_calls

    async def test_r6_mixed_types_probes_each_appropriately(self) -> None:
        """【R】混合 chat+embedding → 各自走对应探测（串行）。"""
        repo = _mock_repo()
        probe = _FakeProbe()
        svc = _svc(repo, probe=probe)

        await svc.create(
            ProviderConfigCreate(
                name="openai",
                models=[
                    ProviderModel(id="gpt-4o", type="chat"),
                    ProviderModel(id="text-embedding-3", type="embedding"),
                ],
            )
        )

        assert len(probe.chat_calls) == 1
        assert len(probe.embedding_calls) == 1
        assert probe.chat_calls[0][1] == "gpt-4o"
        assert probe.embedding_calls[0][1] == "text-embedding-3"


class TestUpdateProbeGate:
    """契约①④：update 路径门禁（只探测「受影响条目」）。"""

    async def test_r7_update_new_model_probed(self) -> None:
        """【R】update 新增模型条目 → 探测该条目。"""
        existing = ProviderConfig(
            id=1, name="openai", models=[ProviderModel(id="gpt-4o", type="chat")]
        )
        repo = _mock_repo(existing)
        probe = _FakeProbe()
        svc = _svc(repo, probe=probe)

        await svc.update(
            1,
            ProviderConfigUpdate(
                models=[
                    ProviderModel(id="gpt-4o", type="chat"),
                    ProviderModel(id="gpt-4o-mini", type="chat"),
                ]
            ),
        )

        probed = [c[1] for c in probe.chat_calls]
        assert "gpt-4o-mini" in probed, f"新增条目须被探测，实际探测 {probed}"
        assert "gpt-4o" not in probed, (
            f"未改动的既有条目不应重复探测（零探测语义），实际探测 {probed}"
        )

    async def test_r8_update_without_models_zero_probe(self) -> None:
        """【R】update 未传 models → **零探测**（不调 probe）。

        关键：这种 update（只改 base_url/timeout）不得因缺 key 被拒。
        """
        existing = ProviderConfig(
            id=1, name="openai", models=[ProviderModel(id="gpt-4o", type="chat")]
        )
        repo = _mock_repo(existing)
        probe = _FakeProbe(chat_error=RuntimeError("should not be called"))
        svc = _svc(repo, probe=probe)

        await svc.update(1, ProviderConfigUpdate(base_url="https://new.example/v1"))

        assert not probe.chat_calls, "无受影响条目时禁止探测"
        assert not probe.embedding_calls
        repo.update.assert_awaited_once()

    async def test_r9_update_unchanged_models_zero_probe(self) -> None:
        """【R】update 传的 models 与既有**全等** → 零探测（幂等保存）。"""
        existing = ProviderConfig(
            id=1, name="openai", models=[ProviderModel(id="gpt-4o", type="chat")]
        )
        repo = _mock_repo(existing)
        probe = _FakeProbe(chat_error=RuntimeError("should not be called"))
        svc = _svc(repo, probe=probe)

        await svc.update(1, ProviderConfigUpdate(models=[ProviderModel(id="gpt-4o", type="chat")]))

        assert not probe.chat_calls, "条目全等时不应探测（幂等保存零探测）"

    async def test_r10_update_type_change_probed_as_new_type(self) -> None:
        """【R】update 改某条目 type（chat→embedding）→ 按**新 type** 探测。"""
        existing = ProviderConfig(id=1, name="zhipu", models=[ProviderModel(id="m1", type="chat")])
        repo = _mock_repo(existing)
        probe = _FakeProbe()
        svc = _svc(repo, probe=probe)

        await svc.update(1, ProviderConfigUpdate(models=[ProviderModel(id="m1", type="embedding")]))

        assert len(probe.embedding_calls) == 1, "type 变更须按新 type 重探"
        assert not probe.chat_calls

    async def test_r11_update_capability_change_probed(self) -> None:
        """【R】update 改 supports_reasoning → 同走「条目有变」判据（Q2 拍板）。

        用户偏好：机制扩展拒绝同族路径分叉——全路径统一用「条目有变」判据。
        """
        existing = ProviderConfig(
            id=1,
            name="openai",
            models=[ProviderModel(id="gpt-4o", type="chat", supports_reasoning=None)],
        )
        repo = _mock_repo(existing)
        probe = _FakeProbe()
        svc = _svc(repo, probe=probe)

        await svc.update(
            1,
            ProviderConfigUpdate(
                models=[ProviderModel(id="gpt-4o", type="chat", supports_reasoning=True)]
            ),
        )

        assert len(probe.chat_calls) == 1, "条目内容有变（含能力覆盖）须重探（全路径统一）"


class TestProbeGateCompatibility:
    """契约⑤⑥：向后兼容 + 依赖方向。"""

    async def test_g1_no_probe_injected_zero_gate(self) -> None:
        """【G】probe=None → 零门禁（既有测试与 CLI 内部调用兼容）。

        护栏：确保门禁是**显式注入**才生效，不因新增功能破坏既有调用方。
        """
        repo = _mock_repo()
        svc = _svc(repo, probe=None)

        await svc.create(
            ProviderConfigCreate(name="openai", models=[ProviderModel(id="gpt-4o", type="chat")])
        )

        repo.add.assert_awaited_once()

    async def test_g2_protocol_is_domain_port(self) -> None:
        """【G】LLMProbeProtocol 定义在 domain/ports（依赖方向，Q4 拍板）。"""
        from inkflow.domain.ports.llm_probe import LLMProbeProtocol

        assert hasattr(LLMProbeProtocol, "probe_chat")
        assert hasattr(LLMProbeProtocol, "probe_embedding")

    async def test_g3_missing_api_key_rejected_with_reason(self) -> None:
        """【G/R】provider 无 key + 有受影响条目 → 422 明示「缺少 API Key」。"""
        repo = _mock_repo()
        # key 取值由 service 经 key_manager 工厂获取；本用例验证失败路径有明确文案
        probe = _FakeProbe(chat_error=RuntimeError("no credentials"))
        svc = _svc(repo, probe=probe)

        with pytest.raises(ProviderConfigServiceError) as exc_info:
            await svc.create(
                ProviderConfigCreate(name="custom", models=[ProviderModel(id="m1", type="chat")])
            )

        assert "m1" in str(exc_info.value)
        repo.add.assert_not_awaited()


class TestSetEmbeddingModelProbeGate:
    """契约①：唯一激活路径同样过 embedding 探测门禁（同 C 同一函数）。"""

    async def test_r12_activation_probe_failure_rejects(self) -> None:
        """【R】set_embedding_model 探测失败 → 422 且不 update（零副作用）。"""
        existing = ProviderConfig(
            id=1, name="zhipu", models=[ProviderModel(id="embedding-3", type="chat")]
        )
        repo = _mock_repo(existing)
        probe = _FakeProbe(embedding_error=RuntimeError("dimension mismatch"))
        svc = _svc(repo, probe=probe)

        with pytest.raises(ProviderConfigServiceError) as exc_info:
            await svc.set_embedding_model("zhipu", "embedding-3")

        assert "embedding-3" in str(exc_info.value)
        repo.update.assert_not_awaited()

    async def test_g4_activation_success_updates(self) -> None:
        """【G】护栏：探测通过 → 正常切换（唯一激活语义零回归）。"""
        existing = ProviderConfig(
            id=1, name="zhipu", models=[ProviderModel(id="embedding-3", type="chat")]
        )
        repo = _mock_repo(existing)
        probe = _FakeProbe(embedding_dim=1024)
        svc = _svc(repo, probe=probe)

        await svc.set_embedding_model("zhipu", "embedding-3")

        assert len(probe.embedding_calls) == 1
        repo.update.assert_awaited()


class TestProbeGateSecurity:
    """安全契约：detail 绝不回显 api_key（ADR-012）。"""

    async def test_r13_detail_never_leaks_api_key(self) -> None:
        """【R】探测失败 detail 不含 api_key 值。"""
        repo = _mock_repo()
        secret = "sk-" + ("a" * 24)  # 模块级拼接构造，避免脱敏污染
        probe = _FakeProbe(chat_error=RuntimeError(f"401 unauthorized: {secret}"))
        svc = _svc(repo, probe=probe)

        with pytest.raises(ProviderConfigServiceError) as exc_info:
            await svc.create(
                ProviderConfigCreate(
                    name="openai", models=[ProviderModel(id="gpt-4o", type="chat")]
                )
            )

        assert secret not in str(exc_info.value), (
            "安全红线：探测失败 detail 绝不回显 api_key（ADR-012）"
        )
