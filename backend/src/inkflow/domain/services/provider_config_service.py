"""ProviderConfig 业务服务 — Provider 注册表 CRUD + 内置 seed 委托.

职责（spec §8.2/§8.5）:
- Provider CRUD 编排：委托 ProviderConfigRepositoryProtocol
- 同名唯一性校验（422）: create 前 / update 改名时经 repo.get_by_name 检查，
  命中 → ProviderConfigNameConflictError
- 资源不存在（404 语义）: get/update/delete 目标缺失 → ProviderConfigNotFoundError
- update 为 exclude_unset 浅合并（同 F1/F13）: None 值 = 不修改，予以剔除；
  仅 name 变更时查重；updated_at 刷新为 now(UTC)，created_at 保留
- seed_builtin_providers 委托 repo（幂等由 repo 保证，返回插入数）
- #936 C 项：保存前 type-aware 最小探测门禁（probe 注入；probe=None → 零门禁）

依赖全部通过构造函数注入（ADR-015，测试注入 Mock）。
"""

from __future__ import annotations

import builtins
import logging
from datetime import UTC, datetime
from pathlib import Path

from inkflow.core.config import InkFlowConfig, save_config_json
from inkflow.core.config import config as default_config
from inkflow.domain.models.provider_config import (
    ProviderConfig,
    ProviderConfigCreate,
    ProviderConfigUpdate,
    ProviderModel,
)
from inkflow.domain.ports.llm_probe import LLMProbeProtocol
from inkflow.domain.ports.provider_config_errors import (
    ProviderConfigNameConflictError,
    ProviderConfigNotFoundError,
    ProviderConfigServiceError,
)
from inkflow.domain.ports.provider_config_repository import ProviderConfigRepositoryProtocol

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """返回当前 UTC 时间（时区感知）。"""
    return datetime.now(UTC)


class ProviderConfigService:
    """Provider 注册表业务服务 — CRUD + 内置 seed.

    Args:
        repository: Provider 注册表仓储端口.
        config: 全局配置（默认值源；data_dir/secret_key 供 #936 C 门禁取凭据）.
        probe: LLM 探测端口（#936 C）；None → 零门禁（向后兼容既有调用方）.
    """

    def __init__(
        self,
        *,
        repository: ProviderConfigRepositoryProtocol,
        config: InkFlowConfig = default_config,
        probe: LLMProbeProtocol | None = None,
    ) -> None:
        self._repo = repository
        self._config = config
        self._probe = probe

    # ── #936 C 项：保存前 type-aware 探测门禁 ──────────────────────────

    def _resolve_api_key(self, provider: str) -> str | None:
        """读取已存 API Key（APIKeyManager 工厂模式，镜像 settings.py:119-124）.

        防御：`data_dir/keys` 不存在时不实例化 APIKeyManager（其 __init__ 会
        mkdir），避免只读/测试路径产生目录副作用；无 key/异常 → None。
        """
        from inkflow.infrastructure.llm.key_manager import APIKeyManager

        data_dir = getattr(self._config, "data_dir", None)
        if data_dir is None:
            return None
        storage_dir = Path(data_dir) / "keys"
        if not storage_dir.is_dir():
            return None
        secret_key = getattr(self._config, "secret_key", "")
        try:
            return APIKeyManager(secret_key=secret_key, storage_dir=storage_dir).get_key(provider)
        except Exception:
            return None

    @staticmethod
    def _probe_error(
        provider: str,
        model: ProviderModel,
        api_key: str | None,
        exc: Exception,
    ) -> ProviderConfigServiceError:
        """构造探测失败异常——含模型 id + 摘要，绝不回显 api_key（ADR-012）。"""
        if not api_key:
            message = (
                f"模型 {provider}/{model.id} 缺少 API Key，无法探测；"
                "如需强制保存请使用 force=true"
            )
        elif model.type == "embedding":
            message = (
                f"embedding 模型 {provider}/{model.id} 探测失败：{type(exc).__name__}；"
                "如需强制保存请使用 force=true"
            )
        else:
            message = (
                f"模型 {provider}/{model.id} 连接失败：{type(exc).__name__}；"
                "如需强制保存请使用 force=true"
            )
        return ProviderConfigServiceError(message)

    async def _probe_chat(
        self,
        probe: LLMProbeProtocol,
        provider: str,
        model: ProviderModel,
        api_key: str | None,
        base_url: str | None,
    ) -> None:
        """chat 条目探测；失败 → ProviderConfigServiceError（422 语义）。"""
        try:
            await probe.probe_chat(provider, model.id, api_key or "", base_url)
        except Exception as exc:
            raise self._probe_error(provider, model, api_key, exc) from None

    async def _probe_embedding(
        self,
        probe: LLMProbeProtocol,
        provider: str,
        model: ProviderModel,
        api_key: str | None,
        base_url: str | None,
    ) -> None:
        """embedding 条目探测（维度须 > 0）；失败 → ProviderConfigServiceError."""
        try:
            dim = await probe.probe_embedding(provider, model.id, api_key or "", base_url)
        except Exception as exc:
            raise self._probe_error(provider, model, api_key, exc) from None
        if dim <= 0:
            raise ProviderConfigServiceError(
                f"embedding 模型 {provider}/{model.id} 探测失败：维度为 {dim}；"
                "如需强制保存请使用 force=true"
            )

    async def _gate_models(
        self,
        provider: str,
        models: builtins.list[ProviderModel],
        *,
        force: bool,
        base_url: str | None = None,
    ) -> None:
        """保存前对「受影响模型条目」做 type-aware 最小探测（#936 C 项）.

        probe=None → 零门禁；force=True 且 probe 存在 → 跳过 + WARNING 锚。
        调用方在 `repo.add`/`repo.update` 之前调用 → 探测失败零落库。串行探测
        （配置写路径低频，Issue 权衡点 3）。
        """
        probe = self._probe
        if probe is None or not models:
            return
        if force:
            logger.warning(
                "跳过模型探测门禁（force=true）: provider=%s models=%s",
                provider,
                [m.id for m in models],
            )
            return
        api_key = self._resolve_api_key(provider)
        for model in models:
            if model.type == "embedding":
                await self._probe_embedding(probe, provider, model, api_key, base_url)
            else:
                await self._probe_chat(probe, provider, model, api_key, base_url)

    @staticmethod
    def _affected_models(
        data: ProviderConfigUpdate,
        existing: ProviderConfig,
    ) -> builtins.list[ProviderModel]:
        """update 的「受影响条目」判定（spec §2.2）：新增 或 内容有变的条目.

        对比维度：id 缺失（新增）/ type / roles / supports_reasoning 任一不同。
        未传 models（None）→ 空（零探测）。
        """
        if data.models is None:
            return []
        previous = {m.id: m for m in existing.models}
        affected: builtins.list[ProviderModel] = []
        for model in data.models:
            before = previous.get(model.id)
            if before is None or (
                before.type != model.type
                or before.roles != model.roles
                or before.supports_reasoning != model.supports_reasoning
            ):
                affected.append(model)
        return affected

    async def create(
        self, data: ProviderConfigCreate, *, force: bool = False
    ) -> ProviderConfig:
        """创建 Provider（同名冲突 → 422；时间戳由服务层填充）.

        #936 C：落库前对全部条目过探测门禁（失败零落库，含 #735 D2 自动设默认）。
        """
        existing = await self._repo.get_by_name(data.name)
        if existing is not None:
            raise ProviderConfigNameConflictError()
        await self._gate_models(data.name, data.models, force=force, base_url=data.base_url)
        now = _utcnow()
        pc = ProviderConfig(
            id=None,
            name=data.name,
            base_url=data.base_url,
            default_model=data.default_model,
            models=data.models,
            max_retries=data.max_retries,
            timeout=data.timeout,
            created_at=now,
            updated_at=now,
        )
        logger.info("创建 Provider: name=%s", data.name)
        created: ProviderConfig = await self._repo.add(pc)
        # #735 D2: 首个含 >=1 个 chat 模型的 provider 新增且全局默认为空 → 自动设为该模型。
        if not self._config.llm_default_model:
            chat_models = [m for m in data.models if m.type == "chat"]
            if chat_models:
                model_id = f"{data.name}/{chat_models[0].id}"
                self._config.llm_default_model = model_id
                save_config_json(self._config.data_dir, {"llm_default_model": model_id})
                logger.info("自动设置全局默认模型: %s", model_id)
        return created

    async def get(self, provider_config_id: int) -> ProviderConfig:
        """按主键获取 Provider；不存在 → ProviderConfigNotFoundError（404）."""
        pc = await self._repo.get(provider_config_id)
        if pc is None:
            raise ProviderConfigNotFoundError()
        return pc

    async def get_by_name(self, name: str) -> ProviderConfig | None:
        """按名称查询 Provider（同名唯一检查用）；不存在返回 None."""
        return await self._repo.get_by_name(name)

    async def list(self) -> builtins.list[ProviderConfig]:
        """列出全部 Provider（按 name 升序，委托 repo）."""
        return await self._repo.list()

    async def set_embedding_model(
        self, provider: str, model_id: str, *, force: bool = False
    ) -> ProviderConfig:
        """将指定模型设为唯一激活的 embedding 模型。

        目标 provider/model 必须存在（否则 ProviderConfigNotFoundError）；
        目标模型 type 置为 "embedding"（id/roles 保留）；其他所有 provider
        （含同 provider 其他模型）的 type=="embedding" 条目降级为 "chat"
        （唯一激活语义，对齐装配 _resolve_embedding_spec 取首个 embedding）。
        返回更新后的目标 ProviderConfig。

        #936 C：激活前对目标模型过 embedding 探测门禁（失败零副作用）。
        """
        all_pcs = await self._repo.list()
        target_pc = next((pc for pc in all_pcs if pc.name == provider), None)
        if target_pc is None:
            raise ProviderConfigNotFoundError()
        target_model = next((m for m in target_pc.models if m.id == model_id), None)
        if target_model is None:
            raise ProviderConfigNotFoundError()
        await self._gate_models(
            provider,
            [target_model.model_copy(update={"type": "embedding"})],
            force=force,
            base_url=target_pc.base_url,
        )
        updated_target: ProviderConfig | None = None
        for existing in all_pcs:
            new_models: list[ProviderModel] = []
            changed = False
            for m in existing.models:
                if existing.name == provider and m.id == model_id:
                    if m.type != "embedding":
                        changed = True
                    new_models.append(m.model_copy(update={"type": "embedding"}))
                elif m.type == "embedding":
                    changed = True
                    new_models.append(m.model_copy(update={"type": "chat"}))
                else:
                    new_models.append(m)
            if changed:
                merged_pc = existing.model_copy(
                    update={"models": new_models, "updated_at": _utcnow()}
                )
                updated: ProviderConfig = await self._repo.update(merged_pc)
                if existing.name == provider:
                    updated_target = updated
        if updated_target is None:
            updated_target = target_pc
        return updated_target

    async def update(
        self,
        provider_config_id: int,
        data: ProviderConfigUpdate,
        *,
        force: bool = False,
    ) -> ProviderConfig:
        """部分更新 Provider（exclude_unset 浅合并，同 F1/F13）.

        None 值 = 不修改（与未传入等价，合并前剔除）；name 变更时查重
        （命中其他 id → 422）；updated_at 刷新，created_at 保留。

        #936 C：仅当存在「新增/内容有变」模型条目时才过探测门禁（空 → 零探测）。
        """
        existing = await self._repo.get(provider_config_id)
        if existing is None:
            raise ProviderConfigNotFoundError()
        # 直接取已校验的字段值（避免 model_dump 将嵌套 ProviderModel 摊平为 dict）
        updates = {
            k: getattr(data, k) for k in data.model_fields_set if getattr(data, k) is not None
        }
        if "name" in updates and updates["name"] != existing.name:
            dup = await self._repo.get_by_name(updates["name"])
            if dup is not None and dup.id != existing.id:
                raise ProviderConfigNameConflictError()
        merged = existing.model_copy(update=updates)
        merged.updated_at = _utcnow()
        affected = self._affected_models(data, existing)
        if affected:
            await self._gate_models(merged.name, affected, force=force, base_url=merged.base_url)
        logger.info("更新 Provider: provider_config_id=%s", provider_config_id)
        updated: ProviderConfig = await self._repo.update(merged)
        return updated

    async def delete(self, provider_config_id: int) -> None:
        """删除 Provider；不存在 → ProviderConfigNotFoundError（404）."""
        if not await self._repo.delete(provider_config_id):
            raise ProviderConfigNotFoundError()

    async def seed_builtin_providers(self) -> int:
        """幂等插入内置 4 provider（幂等由 repo 保证，返回插入数）."""
        return await self._repo.seed_builtin_providers()
