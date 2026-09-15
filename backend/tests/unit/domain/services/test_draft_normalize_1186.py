"""#1186 P2-c RED 契约 — 草稿层正文归一（DraftService 写入路径调 normalize_chapter_content）.

被测行为（对照当前实现 FAIL）:
    ``normalize_chapter_content``（domain/models/chapter.py:295）全仓调用点仅 3 处：
    chapter_service.py:187-188（建章）/ :260-262（改章）/ output_service.py:89-90（导出）。
    **``draft_service.py`` 零调用** → 写作 agent 产出正文在草稿层（GUI 预览 / 草稿列表）
    保持未归一，归一延到 draft confirm→update_chapter 或导出。

    → 本契约要求 DraftService 的**写入路径**（create / update / replace_content）
      对正文调用既有 ``normalize_chapter_content``（**复用**，不重写实现）。

spec：specs/f27-writer-agent/spec.md（草稿服务 §5.2）；#1095 归一闸口。
闸口语义（chapter.py:228-295）：与 ``should_normalize`` 共用同一「单行豁免」闸口 ——
    仅脏数据（多行/含标题重复等）被改写，干净单行数据原样保留。

RED 形态：当前 create/update/replace_content 均原样落库 → 断言「脏数据已归一」必 FAIL。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.chapter import normalize_chapter_content
from inkflow.domain.models.draft import Draft, DraftStatus
from inkflow.domain.services.draft_service import DraftService

pytestmark = pytest.mark.asyncio

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
CHAPTER_ID = uuid.UUID("87654321-4321-8765-4321-876543218765")

#: 脏正文：段间无空行（多段挤压）——归一闸口应插入空行分隔。
DIRTY_CONTENT = "第一段正文内容。\n第二段正文内容。\n第三段正文内容。"
TITLE = "第一章 山道救人"


def _expected_normalized(content: str) -> str:
    """期望值 = 既有纯函数的产出（父侧不重写归一逻辑，只验证接线）。"""
    return normalize_chapter_content(content, TITLE)


def _make_draft(**overrides) -> Draft:
    kwargs = dict(
        id="draft-1",
        project_id=PROJECT_ID,
        chapter_id=CHAPTER_ID,
        content=DIRTY_CONTENT,
        status=DraftStatus.DRAFT,
        created_at=datetime.now(UTC),
        confirmed_at=None,
    )
    kwargs.update(overrides)
    return Draft(**kwargs)


@pytest.fixture
def repo() -> AsyncMock:
    """鸭子类型 draft_repo：create/get/update_content 记录入参。"""
    mock = AsyncMock()
    mock.create.side_effect = lambda **kw: _make_draft(
        id="draft-new", content=kw.get("content", ""), chapter_id=kw.get("chapter_id")
    )
    mock.get.return_value = _make_draft()
    mock.update_content.side_effect = lambda *a, **kw: _make_draft(
        content=a[1] if len(a) > 1 else kw.get("content", "")
    )
    return mock


class TestDraftLayerNormalization:
    async def test_create_normalizes_content(self, repo: AsyncMock) -> None:
        """P2-c：create 落库前正文已归一（草稿层 GUI 预览与落章一致）。"""
        # 前置：脏数据确实会被归一改写（防「恒真断言」——闸口对干净单行是豁免的）
        assert (
            _expected_normalized(DIRTY_CONTENT) != DIRTY_CONTENT
        ), "选定样本未被闸口改写，用例无意义"

        service = DraftService(draft_repo=repo)
        await service.create(
            project_id=PROJECT_ID, chapter_id=CHAPTER_ID, content=DIRTY_CONTENT, summary="s"
        )

        assert repo.create.await_count == 1
        passed = repo.create.await_args.kwargs["content"]
        assert passed == _expected_normalized(DIRTY_CONTENT), (
            f"create 未归一草稿正文：\n期望 {_expected_normalized(DIRTY_CONTENT)!r}\n"
            f"实际 {passed!r}"
        )

    async def test_update_normalizes_content(self, repo: AsyncMock) -> None:
        """P2-c：update（F28 编辑流）落库前正文已归一。"""
        service = DraftService(draft_repo=repo)
        await service.update("draft-1", DIRTY_CONTENT)

        assert repo.update_content.await_count == 1
        args = repo.update_content.await_args.args
        assert args[1] == _expected_normalized(DIRTY_CONTENT), f"update 未归一草稿正文：{args[1]!r}"

    async def test_replace_content_normalizes(self, repo: AsyncMock) -> None:
        """P2-c：replace_content（#997 agent 覆盖）落库前正文已归一。"""
        service = DraftService(draft_repo=repo)
        await service.replace_content("draft-1", DIRTY_CONTENT)

        assert repo.update_content.await_count == 1
        args = repo.update_content.await_args.args
        assert args[1] == _expected_normalized(
            DIRTY_CONTENT
        ), f"replace_content 未归一草稿正文：{args[1]!r}"

    async def test_clean_single_line_content_untouched(self, repo: AsyncMock) -> None:
        """P2-c 反例守护：干净单行正文不得被改写（闸口单行豁免——防过度归一）。"""
        clean = "单行正文，无需归一。"
        assert _expected_normalized(clean) == clean  # 前提校验

        service = DraftService(draft_repo=repo)
        await service.create(
            project_id=PROJECT_ID, chapter_id=CHAPTER_ID, content=clean, summary="s"
        )
        assert repo.create.await_args.kwargs["content"] == clean
