"""上下文组装服务 — 分层 Token 预算分配 + Prompt 渲染.

ContextService 是 F6 的核心服务，负责:
1. 从多个数据源收集 ContextItem
2. 按分层预算分配 Token 空间
3. 将组装结果渲染为系统提示词

依据: specs/f6-context/spec.md §4, ADR-010.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from inkflow.core.config import config
from inkflow.core.model_registry import calculate_budget, get_layer_cap
from inkflow.domain.models.context import (
    SOURCE_LAYER,
    ContextAssemblyResult,
    ContextBlock,
    ContextItem,
    ContextLayer,
    ContextOverride,
    ContextPreselectRequest,
    ContextPreselectResult,
    ContextRequest,
    ContextSourceType,
    DroppedItem,
    TokenBudgetConfig,
)
from inkflow.domain.ports.context_errors import ContextBudgetExceededError
from inkflow.domain.ports.context_sources import ContextSourceProtocol
from inkflow.domain.ports.summary_repository import SummaryRepositoryProtocol

PreselectFn = Callable[[list[ContextItem], str, str, str], Awaitable[ContextOverride]]
"""预选函数签名（#1379，infrastructure 注入）.

参数顺序: ``(candidates, outline_text, writing_requirements, model)``

- ``candidates``: 三类候选条目（character_setting / world_setting / foreshadowing）
- ``outline_text``: 本章大纲文本（overall + 命中的卷纲/章纲分块）
- ``writing_requirements``: 本章写作要求
- ``model``: 目标模型名（provider/model_name）

返回: 预选出的三类 id 子集（``ContextOverride`` 形状，由服务侧做候选集过滤）。
"""

_PRESELECT_SOURCES: tuple[ContextSourceType, ...] = (
    ContextSourceType.CHARACTER_SETTING,
    ContextSourceType.WORLD_SETTING,
    ContextSourceType.FORESHADOWING,
)
"""可预选的三类来源（与 override 通道一致）；顺序即结果字段顺序。"""

_PRESELECT_ID_KEYS: dict[ContextSourceType, str] = {
    ContextSourceType.CHARACTER_SETTING: "character_id",
    ContextSourceType.WORLD_SETTING: "world_setting_id",
    ContextSourceType.FORESHADOWING: "foreshadowing_id",
}
"""来源 → 条目 metadata 中的 id 键（与 `_apply_override` 同口径）。"""


class ContextService:
    """上下文组装服务.

    依赖（通过构造函数注入，支持 Mock）:
        - sources: dict[ContextSourceType, ContextSourceProtocol] — 数据源集合
        - summary_repo: SummaryRepositoryProtocol — 摘要缓存
        - count_tokens: Callable[[str, str], Awaitable[int]] — Token 计数（F5）
        - compress_fn: Callable[[ContextItem, float], Awaitable[ContextItem]] — LLM 压缩
    """

    def __init__(
        self,
        sources: dict[ContextSourceType, ContextSourceProtocol],
        summary_repo: SummaryRepositoryProtocol | None = None,
        count_tokens: Callable[[str, str], Awaitable[int]] | None = None,
        compress_fn: (Callable[[ContextItem, float], Awaitable[ContextItem]] | None) = None,
        preselect_fn: PreselectFn | None = None,
    ) -> None:
        self._sources = sources
        self._summary_repo = summary_repo
        self._count_tokens = count_tokens or (lambda text, model: _char_count(text))
        self._compress_fn = compress_fn
        self._preselect_fn = preselect_fn

    # ── 公共 API ──────────────────────────────────────────────────

    async def build_context(self, request: ContextRequest) -> ContextAssemblyResult:
        """主入口：收集 → 预算分配 → 组装.

        Args:
            request: 上下文组装请求.

        Returns:
            组装结果，含 blocks / budget / total / dropped.

        Raises:
            ValueError: writing_requirements 为空.
            ContextBudgetExceededError: protected 层超预算.
        """
        if not request.writing_requirements.strip():
            raise ValueError("writing_requirements cannot be empty")

        # 1. 计算预算
        budget = self.get_budget(request.model, request.max_tokens)

        # 2. 收集所有数据源
        all_items: dict[ContextLayer, list[ContextItem]] = {
            ContextLayer.PROTECTED: [],
            ContextLayer.COMPRESSIBLE: [],
            ContextLayer.DYNAMIC: [],
        }

        # writing_requirements 始终作为 protected 第一个条目
        wr_item = ContextItem(
            source=ContextSourceType.WRITING_REQUIREMENTS,
            title="写作要求",
            content=request.writing_requirements,
            priority=100,  # 最高优先级
        )
        all_items[ContextLayer.PROTECTED].append(wr_item)

        # 收集其他数据源
        for source_type, source in self._sources.items():
            try:
                items = await source.collect(request.project_id, request.chapter_id)
                items = _apply_override(items, source_type, request.override)
                layer = SOURCE_LAYER[source_type]
                all_items[layer].extend(items)
            except Exception:
                # 数据源失败不阻断组装（防御性）
                continue

        # 3. 预算分配
        result = await self._allocate(all_items, budget, request.model)
        result.model = request.model
        return result

    async def preselect_context(
        self,
        request: ContextPreselectRequest,
    ) -> ContextPreselectResult:
        """按本章大纲预选相关条目（#1379）.

        流程:
            ① 全量组装（override=None）→ 三类候选 + 本章大纲文本
            ② 无候选 → 空集（没得选，不是回退）
            ③ 无大纲 / 预选未接线 → 回退全选（mode="fallback"），不发起 LLM 调用
            ④ 一次预选调用（``preselect_fn``）→ 结果 ∩ 候选集（防幻觉 id 污染 override）
            ⑤ 预选抛错 / 输出不可解析 → 回退全选（增强项不得阻断面板）

        Args:
            request: 预选请求（project_id / chapter_id / model / writing_requirements）.

        Returns:
            预选结果；``mode="fallback"`` 时三类 id 为全量候选（前端采用即全选）.

        Raises:
            ValueError: writing_requirements 为空（与 build_context 同口径）.
            ContextBudgetExceededError: protected 层超预算（端点映射 400）.
        """
        full = await self.build_context(
            ContextRequest(
                project_id=request.project_id,
                chapter_id=request.chapter_id,
                model=request.model,
                writing_requirements=request.writing_requirements,
            )
        )
        candidates = [
            block.item for block in full.blocks if block.item.source in _PRESELECT_SOURCES
        ]
        if not candidates:
            return ContextPreselectResult(mode="agent")
        all_ids = {src: _collect_source_ids(candidates, src) for src in _PRESELECT_SOURCES}
        outline_text = "\n".join(
            block.item.content
            for block in full.blocks
            if block.item.source == ContextSourceType.OUTLINE
        )
        if not outline_text.strip() or self._preselect_fn is None:
            return _preselect_result(all_ids, mode="fallback")
        try:
            picked = await self._preselect_fn(
                candidates, outline_text, request.writing_requirements, request.model
            )
        except Exception:  # 预选是增强项：任何失败都回退全选（不阻断面板主路径）
            return _preselect_result(all_ids, mode="fallback")
        picked_map = {
            ContextSourceType.CHARACTER_SETTING: picked.character_ids,
            ContextSourceType.WORLD_SETTING: picked.world_ids,
            ContextSourceType.FORESHADOWING: picked.foreshadowing_ids,
        }
        allowed = {src: set(ids) for src, ids in all_ids.items()}
        selected = {
            src: [item_id for item_id in picked_map[src] if item_id in allowed[src]]
            for src in _PRESELECT_SOURCES
        }
        return _preselect_result(selected, mode="agent")

    async def get_context(
        self,
        *,
        project_id: uuid.UUID,
        chapter_id: uuid.UUID | None = None,
        mode: str = "generate",
    ) -> str:
        """ContextProviderProtocol 适配入口 — 返回注入 Prompt 的上下文文本.

        F3 WritingService 通过 Port（`ContextProviderProtocol.get_context`）取上下文，
        而 F6 的组装入口是 `build_context(ContextRequest)`；本方法弥合两者：
        构造 ContextRequest → build_context → render_system_prompt → str。

        Args:
            project_id: 项目 ID。
            chapter_id: 章节 ID（可选；当前 5 源均按项目注入，忽略此参）。
            mode: 写作模式（"generate" / "continue" / "revise"）——仅作为
                writing_requirements 文案来源，真实内容由各数据源决定。

        Returns:
            渲染后的系统提示词分段文本；失败时返回空串（降级路径）。

        Note:
            `_char_count` 已接受可变参（`*args, **kwargs`，见文件末）：

            - 数据源在 `build_context` 内已单独 try/except 兜底；
            - `get_budget` 对未注册模型会 ValueError（单测注入的模型名常见）；
            - protected 层条目（如超长偏好）可能抛 `ContextBudgetExceededError`。

            上述任一都不得让写作主链路失败 → 统一降级为空串（等价 NullContextProvider）。
        """
        from inkflow.domain.models.context import ContextRequest

        try:
            result = await self.build_context(
                ContextRequest(
                    project_id=project_id,
                    chapter_id=chapter_id,
                    model=config.llm_default_model,
                    writing_requirements=f"模式：{mode}",
                )
            )
            return self.render_system_prompt(result)
        except Exception:  # 上下文注入为增强项，任何失败降级为空上下文
            return ""

    def get_budget(self, model: str, max_tokens: int | None = None) -> int:
        """计算上下文预算 = min(模型窗口, max_tokens) × max_ratio.

        Args:
            model: 模型名.
            max_tokens: 显式覆盖.

        Returns:
            预算 Token 数.
        """
        return calculate_budget(model, max_tokens=max_tokens)

    @staticmethod
    def get_layer_cap(
        layer: ContextLayer,
        budget: int,
        config: TokenBudgetConfig | None = None,
    ) -> int:
        """计算分层 cap = budget × layer_ratio[layer].

        Args:
            layer: 上下文层.
            budget: 总预算.
            config: 分层配置 (None = 默认).

        Returns:
            该层的 Token 上限.
        """
        cfg = config or TokenBudgetConfig()
        ratios: dict[str, float] = {}
        for ly, ratio in cfg.layer_ratio.items():
            ratios[ly.value] = ratio
        return get_layer_cap(layer.value, budget, ratios)

    async def _allocate(
        self,
        all_items: dict[ContextLayer, list[ContextItem]],
        budget: int,
        model: str,
    ) -> ContextAssemblyResult:
        """分层预算分配算法（核心）.

        流程:
        1. Protected: 全量注入，超 cap → 硬失败
        2. Compressible: 按 priority 降序，超 cap → LLM 压缩 → 裁剪
        3. Dynamic: 按 priority 降序贪心选择，不压缩

        Args:
            all_items: 三层上下文条目.
            budget: 总预算.
            model: 模型名.

        Returns:
            组装结果.

        Raises:
            ContextBudgetExceededError: protected 层超预算.
        """
        dropped: list[DroppedItem] = []
        blocks: list[ContextBlock] = []
        used = 0

        # Layer order: PROTECTED → COMPRESSIBLE → DYNAMIC
        layer_order = [
            ContextLayer.PROTECTED,
            ContextLayer.COMPRESSIBLE,
            ContextLayer.DYNAMIC,
        ]

        for layer in layer_order:
            items = all_items.get(layer, [])
            layer_cap = self.get_layer_cap(layer, budget)

            if layer == ContextLayer.PROTECTED:
                # Protected: 全量注入，超 cap → 硬失败
                layer_total = 0
                for item in sorted(items, key=lambda i: i.priority, reverse=True):
                    count = await self._count_tokens(item.content, model)
                    layer_total += count
                    blocks.append(ContextBlock(item=item, layer=layer, token_count=count))
                if layer_total > layer_cap:
                    raise ContextBudgetExceededError(
                        budget=layer_cap,
                        required=layer_total,
                        suggestion="精简写作要求或改用更大窗口模型",
                    )
                used += layer_total

            elif layer == ContextLayer.COMPRESSIBLE:
                # Compressible: 放不下的 → 压缩 → 裁剪
                remaining = layer_cap
                for item in sorted(items, key=lambda i: i.priority, reverse=True):
                    count = await self._count_tokens(item.content, model)
                    if count <= remaining:
                        blocks.append(ContextBlock(item=item, layer=layer, token_count=count))
                        remaining -= count
                        used += count
                    elif self._compress_fn is not None:
                        # 尝试压缩
                        try:
                            compressed = await self._compress_fn(item, 0.5)
                            compressed_count = await self._count_tokens(compressed.content, model)
                            if compressed_count <= remaining:
                                blocks.append(
                                    ContextBlock(
                                        item=compressed,
                                        layer=layer,
                                        token_count=compressed_count,
                                        compressed=True,
                                    )
                                )
                                remaining -= compressed_count
                                used += compressed_count
                            else:
                                dropped.append(
                                    DroppedItem(
                                        item=item,
                                        reason="compression_insufficient",
                                    )
                                )
                        except Exception:
                            dropped.append(
                                DroppedItem(item=item, reason="compression_insufficient")
                            )
                    else:
                        dropped.append(DroppedItem(item=item, reason="over_budget"))

            elif layer == ContextLayer.DYNAMIC:
                # Dynamic: 贪心选择，不压缩
                remaining = layer_cap
                for item in sorted(items, key=lambda i: i.priority, reverse=True):
                    count = await self._count_tokens(item.content, model)
                    if count <= remaining:
                        blocks.append(ContextBlock(item=item, layer=layer, token_count=count))
                        remaining -= count
                        used += count
                    else:
                        dropped.append(DroppedItem(item=item, reason="over_budget"))

        return ContextAssemblyResult(
            blocks=blocks,
            budget_tokens=budget,
            total_tokens=used,
            model=model,
            dropped=dropped,
        )

    def render_system_prompt(self, result: ContextAssemblyResult) -> str:
        """将 blocks 渲染为系统提示词分段.

        格式:
            ## 写作要求
            <content>

            ## 大纲
            <content>

            ...

        Args:
            result: 组装结果.

        Returns:
            格式化的系统提示词文本.
        """
        sections: list[str] = []
        for block in result.blocks:
            label = f"## {block.item.title}"
            if block.compressed:
                label += "（已压缩）"
            sections.append(f"{label}\n{block.item.content}")
        return "\n\n".join(sections)


# ── 辅助 ────────────────────────────────────────────────────────────


def _collect_source_ids(
    candidates: list[ContextItem], source: ContextSourceType
) -> list[uuid.UUID]:
    """按候选顺序收集某来源条目的 id（metadata 键见 `_PRESELECT_ID_KEYS`）；缺失/非法值跳过.

    Args:
        candidates: 三类候选条目（混合列表）.
        source: 目标来源类型.

    Returns:
        该来源的 id 列表（保持候选顺序，可直接作为「全选」载荷）.
    """
    meta_key = _PRESELECT_ID_KEYS[source]
    ids: list[uuid.UUID] = []
    for item in candidates:
        if item.source != source:
            continue
        try:
            ids.append(uuid.UUID(str(item.metadata.get(meta_key, ""))))
        except ValueError:
            continue
    return ids


def _preselect_result(
    ids: dict[ContextSourceType, list[uuid.UUID]],
    *,
    mode: str,
) -> ContextPreselectResult:
    """三类 id 映射 → 预选结果 DTO（缺类补空）.

    Args:
        ids: 来源 → id 列表.
        mode: 产生方式（"agent" / "fallback"）.

    Returns:
        预选结果.
    """
    return ContextPreselectResult(
        character_ids=ids.get(ContextSourceType.CHARACTER_SETTING, []),
        world_ids=ids.get(ContextSourceType.WORLD_SETTING, []),
        foreshadowing_ids=ids.get(ContextSourceType.FORESHADOWING, []),
        mode=mode,
    )


def _apply_override(
    items: list[ContextItem],
    source_type: ContextSourceType,
    override: ContextOverride | None,
) -> list[ContextItem]:
    """override 通道过滤 — 只过滤 character_setting / foreshadowing / world_setting 三类来源.

    - override.character_ids → 仅保留 metadata.character_id 命中的角色 item（空列表 = 全不保留）
    - override.foreshadowing_ids → 仅保留 metadata.foreshadowing_id 命中的伏笔 item（空 = 全不保留）
    - override.world_ids → 仅保留 metadata.world_setting_id 命中的世界观 item（空 = 全不保留）
    - override 为 None / 其他来源 → 原样返回（不过滤）

    #1235 语义升级：显式空列表 = 删空（该类不注入），不再回退全注入；
    「全注入」仅由 override=None（缺省）表达，保证 GUI 勾选可删到零。

    Args:
        items: 数据源产出的上下文条目.
        source_type: 数据源类型.
        override: 显式勾选通道（v1.1 #593 / #704 追加世界观 / #1235 空列表=不注入）.

    Returns:
        过滤后的上下文条目列表.
    """
    if override is None:
        return items
    if source_type == ContextSourceType.CHARACTER_SETTING:
        allowed = {str(i) for i in override.character_ids}
        return [item for item in items if str(item.metadata.get("character_id", "")) in allowed]
    if source_type == ContextSourceType.FORESHADOWING:
        allowed = {str(i) for i in override.foreshadowing_ids}
        return [item for item in items if str(item.metadata.get("foreshadowing_id", "")) in allowed]
    if source_type == ContextSourceType.WORLD_SETTING:
        allowed = {str(i) for i in override.world_ids}
        return [item for item in items if str(item.metadata.get("world_setting_id", "")) in allowed]
    return items


async def _char_count(text: str, _model: str = "") -> int:
    """基于字符数的 Token 估算（兜底，字符数/4）."""
    return max(1, len(text) // 4)
