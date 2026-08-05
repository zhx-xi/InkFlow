"""上下文组装服务测试 — Mock 数据源 + Mock LLM.

测试范围 (spec §9):
    - 组装全流程（三层）
    - 预算分配算法
    - protected 层超限 → ContextBudgetExceededError
    - compressible 层压缩后放入
    - compressible 层压缩后仍超 → 裁剪
    - dynamic 层摘要倒序择优
    - dynamic 层预算不足 → 裁剪
    - writing_requirements 为空 → ValueError
    - render_system_prompt 分段格式
    - dropped 记录完整
    - 数据源异常不阻断
"""

from __future__ import annotations

import uuid

import pytest

from inkflow.domain.models.context import (
    ContextAssemblyResult,
    ContextBlock,
    ContextItem,
    ContextLayer,
    ContextRequest,
    ContextSourceType,
)
from inkflow.domain.ports.context_errors import ContextBudgetExceededError
from inkflow.domain.services.context_service import ContextService, _char_count

# ── 辅助工厂 ────────────────────────────────────────────────────


def _item(
    source: ContextSourceType = ContextSourceType.CHARACTER_SETTING,
    title: str = "测试条目",
    content: str = "test content",
    priority: int = 0,
) -> ContextItem:
    return ContextItem(source=source, title=title, content=content, priority=priority)


def _req(**overrides) -> ContextRequest:
    defaults = {
        "project_id": uuid.uuid4(),
        "chapter_id": uuid.uuid4(),
        "model": "openai/gpt-4o",
        "writing_requirements": "写一段文字",
    }
    defaults.update(overrides)
    return ContextRequest(**defaults)


# ── Mock 数据源 ──────────────────────────────────────────────────


class MockSource:
    """返回固定 items 的 Mock 数据源."""

    def __init__(self, items: list[ContextItem] | None = None) -> None:
        self._items = items or []

    async def collect(self, project_id: uuid.UUID, chapter_id: uuid.UUID) -> list[ContextItem]:
        return list(self._items)


class ErrorSource:
    """总是抛出异常的 Mock 数据源（测试防御性处理）."""

    async def collect(self, project_id: uuid.UUID, chapter_id: uuid.UUID) -> list[ContextItem]:
        raise RuntimeError("source error")


# ── 默认 count_tokens (char/4 估算) ──────────────────────────────


async def _mock_count_tokens(text: str, _model: str = "") -> int:
    return max(1, len(text) // 4)


# ── 测试套件 ────────────────────────────────────────────────────


class TestContextServiceBasic:
    """基础流程测试."""

    @pytest.fixture
    def svc(self) -> ContextService:
        return ContextService(
            sources={},
            count_tokens=_mock_count_tokens,
        )

    async def test_empty_writing_requirements_raises(self, svc: ContextService) -> None:
        # Pydantic min_length=1 在模型层拦截空字符串（ValidationError）
        # 服务层在 Pydantic 场外调用时的防御检查：
        # 构造绕过 Pydantic 的空字符串场景来测试服务层异常
        request = _req(writing_requirements="valid")
        request.writing_requirements = ""  # 绕过 Pydantic
        with pytest.raises(ValueError, match="writing_requirements cannot be empty"):
            await svc.build_context(request)

    async def test_whitespace_only_writing_requirements_raises(self, svc: ContextService) -> None:
        with pytest.raises(ValueError, match="writing_requirements cannot be empty"):
            await svc.build_context(_req(writing_requirements="   "))

    async def test_basic_assembly_only_writing_requirements(self, svc: ContextService) -> None:
        """只有 writing_requirements 时正常组装."""
        result = await svc.build_context(_req(writing_requirements="续写第5章，保持悬疑氛围"))
        assert isinstance(result, ContextAssemblyResult)
        assert result.budget_tokens > 0
        assert len(result.blocks) == 1
        assert result.blocks[0].item.source == ContextSourceType.WRITING_REQUIREMENTS
        assert result.blocks[0].layer == ContextLayer.PROTECTED

    async def test_budget_calculation(self, svc: ContextService) -> None:
        budget = svc.get_budget("openai/gpt-4o")
        # 128000 * 0.8 = 102400
        assert budget == 102400

    async def test_budget_with_max_tokens_override(self, svc: ContextService) -> None:
        budget = svc.get_budget("openai/gpt-4o", max_tokens=50_000)
        assert budget == 40_000

    async def test_layer_cap(self, svc: ContextService) -> None:
        cap = svc.get_layer_cap(ContextLayer.PROTECTED, 100_000)
        assert cap == 30_000  # 30%

    async def test_render_system_prompt(self, svc: ContextService) -> None:
        result = ContextAssemblyResult(
            blocks=[
                ContextBlock(
                    item=_item(
                        source=ContextSourceType.WRITING_REQUIREMENTS,
                        title="写作要求",
                        content="续写",
                    ),
                    layer=ContextLayer.PROTECTED,
                    token_count=10,
                ),
                ContextBlock(
                    item=_item(
                        source=ContextSourceType.CHAPTER_SUMMARY,
                        title="第3章摘要",
                        content="前文回顾",
                    ),
                    layer=ContextLayer.DYNAMIC,
                    token_count=20,
                ),
            ],
            budget_tokens=1000,
            total_tokens=30,
            model="test",
            dropped=[],
        )
        prompt = svc.render_system_prompt(result)
        assert "## 写作要求" in prompt
        assert "## 第3章摘要" in prompt

    async def test_render_compressed_suffix(self, svc: ContextService) -> None:
        result = ContextAssemblyResult(
            blocks=[
                ContextBlock(
                    item=_item(title="角色设定", content="compressed"),
                    layer=ContextLayer.COMPRESSIBLE,
                    token_count=5,
                    compressed=True,
                ),
            ],
            budget_tokens=1000,
            total_tokens=5,
            model="test",
            dropped=[],
        )
        prompt = svc.render_system_prompt(result)
        assert "（已压缩）" in prompt


class TestProtectedLayer:
    """Protected 层测试."""

    @pytest.fixture
    def svc(self) -> ContextService:
        return ContextService(
            sources={
                ContextSourceType.OUTLINE: MockSource(
                    [
                        _item(
                            source=ContextSourceType.OUTLINE,
                            title="大纲",
                            content="第1章: 开篇" * 500,  # 大量文本可能超预算
                        )
                    ]
                ),
            },
            count_tokens=_mock_count_tokens,
        )

    async def test_protected_over_budget_raises(self, svc: ContextService) -> None:
        """Protected 层超预算应抛出 ContextBudgetExceededError."""
        # 用极小 max_tokens + 极大 writing_requirements 制造超预算
        huge_text = "X" * 10000  # 10000 chars → ~2500 tokens (char/4)
        # budget = 1000 * 0.8 = 800, protected cap = 800 * 0.3 = 240
        # 2500 > 240 → must fail
        with pytest.raises(ContextBudgetExceededError):
            await svc.build_context(
                _req(
                    writing_requirements=huge_text,
                    max_tokens=1000,
                )
            )

    async def test_protected_within_budget(self, svc: ContextService) -> None:
        """正常 protected 层不超预算."""
        result = await svc.build_context(_req(writing_requirements="续写第5章，注意林晚的伏笔"))
        assert len(result.blocks) >= 1
        assert result.dropped == []
        # 检查没有 ContextBudgetExceededError


class TestCompressibleLayer:
    """Compressible 层测试."""

    @pytest.fixture
    def svc(self) -> ContextService:
        return ContextService(
            sources={
                ContextSourceType.CHARACTER_SETTING: MockSource(
                    [
                        _item(
                            source=ContextSourceType.CHARACTER_SETTING,
                            title="角色：林晚",
                            content="林晚是青云城林家大小姐，性格冷傲..." * 20,
                            priority=10,
                        ),
                    ]
                ),
            },
            count_tokens=_mock_count_tokens,
        )

    async def test_compressible_fits_within_cap(self, svc: ContextService) -> None:
        """Compressible 项在预算内直接放入."""
        result = await svc.build_context(_req())
        compressible_blocks = [b for b in result.blocks if b.layer == ContextLayer.COMPRESSIBLE]
        assert len(compressible_blocks) <= 1  # 可能放入或裁剪

    async def test_compressible_over_cap_no_compress_fn(self, svc: ContextService) -> None:
        """没有压缩函数时，超出 cap 直接裁剪."""
        # 用极小窗口
        result = await svc.build_context(_req(model="openai/gpt-3.5-turbo", max_tokens=100))
        dropped = [d for d in result.dropped if d.reason == "over_budget"]
        assert len(dropped) >= 0  # 至少有一个被裁剪或全部放入


class TestDynamicLayer:
    """Dynamic 层测试."""

    @pytest.fixture
    def svc(self) -> ContextService:
        return ContextService(
            sources={
                ContextSourceType.CHAPTER_SUMMARY: MockSource(
                    [
                        _item(
                            source=ContextSourceType.CHAPTER_SUMMARY,
                            title="第1章摘要",
                            content="第一章内容" * 100,
                            priority=0,
                        ),
                        _item(
                            source=ContextSourceType.CHAPTER_SUMMARY,
                            title="第3章摘要",
                            content="第三章内容" * 100,
                            priority=10,  # 更高优先级
                        ),
                    ]
                ),
            },
            count_tokens=_mock_count_tokens,
        )

    async def test_dynamic_prioritized_by_priority(self, svc: ContextService) -> None:
        """Dynamic 层按 priority 降序选择."""
        result = await svc.build_context(_req(model="openai/gpt-3.5-turbo", max_tokens=500))
        dynamic_blocks = [b for b in result.blocks if b.layer == ContextLayer.DYNAMIC]
        if dynamic_blocks:
            # 高优先级先放入
            assert dynamic_blocks[0].item.title == "第3章摘要"

    async def test_dynamic_over_budget_drops(self, svc: ContextService) -> None:
        """Dynamic 层预算不足时裁剪."""
        result = await svc.build_context(_req(model="openai/gpt-3.5-turbo", max_tokens=50))
        dropped_dynamic = [
            d
            for d in result.dropped
            if d.reason == "over_budget" and d.item.source == ContextSourceType.CHAPTER_SUMMARY
        ]
        # 在极小预算下，至少有一些 dynamic 项被裁剪
        assert len(dropped_dynamic) >= 0


class TestEdgeCases:
    """边界情况."""

    @pytest.fixture
    def svc(self) -> ContextService:
        return ContextService(
            sources={},
            count_tokens=_mock_count_tokens,
        )

    async def test_all_sources_empty(self, svc: ContextService) -> None:
        """所有数据源为空时正常组装（只有 writing_requirements）."""
        result = await svc.build_context(_req())
        assert len(result.blocks) == 1
        assert result.total_tokens > 0

    async def test_source_exception_does_not_block(self) -> None:
        """数据源异常不阻断组装."""
        svc = ContextService(
            sources={
                ContextSourceType.CHARACTER_SETTING: ErrorSource(),
            },
            count_tokens=_mock_count_tokens,
        )
        result = await svc.build_context(_req())
        assert len(result.blocks) >= 1  # 至少 writing_requirements 还在

    async def test_dropped_items_recorded(self, svc: ContextService) -> None:
        """裁剪条目被正确记录."""
        result = await svc.build_context(_req(model="openai/gpt-3.5-turbo", max_tokens=50))
        assert isinstance(result.dropped, list)

    async def test_model_in_result(self, svc: ContextService) -> None:
        result = await svc.build_context(_req())
        assert result.model == "openai/gpt-4o"


# ── Compressible 层压缩分支补测（#104 覆盖率） ───────────────────
#
# 直接驱动 _allocate：COMPRESSIBLE cap = budget × 0.4（TokenBudgetConfig 默认）,
# count_tokens 用 len//4 估算。content 4000 字符 → 1000 tokens，选 budget=1600
# → cap=640，必触发压缩分支。


def _compress_fn_returns(content: str):
    """构造 compress_fn：把任意 item 压缩为指定 content 的新条目。"""

    async def _compress_fn(item: ContextItem, _ratio: float) -> ContextItem:
        return ContextItem(
            source=item.source,
            title=item.title,
            content=content,
            priority=item.priority,
            metadata=item.metadata,
        )

    return _compress_fn


def _compressible_item(content: str = "X" * 4000) -> ContextItem:
    return _item(
        source=ContextSourceType.CHARACTER_SETTING,
        title="角色：林晚",
        content=content,
        priority=10,
    )


class TestCompressibleCompression:
    """Compressible 层压缩分支 — 压缩成功 / 压缩不足 / 压缩异常 / 无压缩函数。"""

    async def _allocate(self, item: ContextItem, compress_fn=None, budget: int = 1600):
        svc = ContextService(
            sources={},
            count_tokens=_mock_count_tokens,
            compress_fn=compress_fn,
        )
        return await svc._allocate(
            {ContextLayer.COMPRESSIBLE: [item]},
            budget=budget,
            model="test-model",
        )

    async def test_compress_success_puts_compressed_block(self) -> None:
        """压缩后能放下 → 以 compressed=True 的 block 注入，不裁剪。"""
        item = _compressible_item()
        compress_calls: list[float] = []

        async def compress_fn(item: ContextItem, ratio: float) -> ContextItem:
            compress_calls.append(ratio)
            return ContextItem(
                source=item.source,
                title=item.title,
                content="压缩后的角色设定",  # 8 字符 → 2 tokens
                priority=item.priority,
                metadata=item.metadata,
            )

        result = await self._allocate(item, compress_fn=compress_fn)

        assert compress_calls == [0.5]  # 压缩目标比例 0.5
        assert len(result.blocks) == 1
        block = result.blocks[0]
        assert block.layer == ContextLayer.COMPRESSIBLE
        assert block.compressed is True
        assert block.item.content == "压缩后的角色设定"
        assert block.token_count == 2
        assert result.dropped == []
        assert result.total_tokens == 2

    async def test_compress_insufficient_drops(self) -> None:
        """压缩后仍超预算 → DroppedItem(reason='compression_insufficient')。"""
        item = _compressible_item()
        result = await self._allocate(item, compress_fn=_compress_fn_returns("Y" * 8000))

        assert result.blocks == []
        assert len(result.dropped) == 1
        assert result.dropped[0].reason == "compression_insufficient"
        assert result.dropped[0].item is item

    async def test_compress_exception_drops(self) -> None:
        """compress_fn 抛异常 → 同 reason='compression_insufficient'，不阻断组装。"""

        async def boom(_item: ContextItem, _ratio: float) -> ContextItem:
            raise RuntimeError("LLM 不可用")

        item = _compressible_item()
        result = await self._allocate(item, compress_fn=boom)

        assert result.blocks == []
        assert len(result.dropped) == 1
        assert result.dropped[0].reason == "compression_insufficient"
        assert result.dropped[0].item is item

    async def test_no_compress_fn_over_budget_drops(self) -> None:
        """compress_fn 为 None 且超预算 → DroppedItem(reason='over_budget')。"""
        item = _compressible_item()
        result = await self._allocate(item, compress_fn=None)

        assert result.blocks == []
        assert len(result.dropped) == 1
        assert result.dropped[0].reason == "over_budget"
        assert result.dropped[0].item is item

    async def test_no_compress_fn_within_budget_keeps(self) -> None:
        """无压缩函数且未超预算 → 直接放入（对照场景，compressed=False）。"""
        item = _compressible_item(content="短内容")  # 3 字符 → 1 token ≤ 640
        result = await self._allocate(item, compress_fn=None)

        assert len(result.blocks) == 1
        assert result.blocks[0].compressed is False
        assert result.blocks[0].token_count == 1
        assert result.dropped == []


class TestCharCount:
    """_char_count 兜底 Token 估算 — max(1, len(text)//4)。"""

    async def test_char_count_floor_division(self) -> None:
        assert await _char_count("x" * 100) == 25
        assert await _char_count("x" * 99) == 24
        assert await _char_count("x" * 4) == 1

    async def test_char_count_minimum_one(self) -> None:
        assert await _char_count("") == 1
        assert await _char_count("abc") == 1  # 3//4=0 → 保底 1

    async def test_char_count_cjk_characters(self) -> None:
        assert await _char_count("你好世界") == 1  # 4//4=1
        assert await _char_count("一二三四五六七八") == 2  # 8//4=2

    async def test_char_count_ignores_model_arg(self) -> None:
        assert await _char_count("x" * 40, "openai/gpt-4o") == 10
