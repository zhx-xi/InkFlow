"""上下文组装服务 — 分层 Token 预算分配 + Prompt 渲染.

ContextService 是 F6 的核心服务，负责:
1. 从多个数据源收集 ContextItem
2. 按分层预算分配 Token 空间
3. 将组装结果渲染为系统提示词

依据: specs/f6-context-service/spec.md §4, ADR-010.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from inkflow.core.model_registry import calculate_budget, get_layer_cap
from inkflow.domain.models.context import (
    SOURCE_LAYER,
    ContextAssemblyResult,
    ContextBlock,
    ContextItem,
    ContextLayer,
    ContextRequest,
    ContextSourceType,
    DroppedItem,
    TokenBudgetConfig,
)
from inkflow.domain.ports.context_errors import ContextBudgetExceededError
from inkflow.domain.ports.context_sources import ContextSourceProtocol
from inkflow.domain.ports.summary_repository import SummaryRepositoryProtocol


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
    ) -> None:
        self._sources = sources
        self._summary_repo = summary_repo
        self._count_tokens = count_tokens or (lambda text, model: _char_count(text))
        self._compress_fn = compress_fn

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
                layer = SOURCE_LAYER[source_type]
                all_items[layer].extend(items)
            except Exception:
                # 数据源失败不阻断组装（防御性）
                continue

        # 3. 预算分配
        result = await self._allocate(all_items, budget, request.model)
        result.model = request.model
        return result

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


async def _char_count(text: str, _model: str = "") -> int:
    """基于字符数的 Token 估算（兜底，字符数/4）."""
    return max(1, len(text) // 4)
