"""#1372 提取合并路径 parent_id 穿透契约（真实 SQLite + 真实仓储）.

背景（rc5 实测）:
``_world_extractor._merge_world_fields``（:326）构造「合并后」WorldSetting 时
漏传 ``parent_id`` → 数据类默认 None → ``_merge``（:296）``repo.update(merged)``
把该条 parent_id 写成 NULL → 该条成为同项目第二个根 → 撞 #849 部分唯一索引
``uq_world_settings_root_per_project ON world_settings (project_id) WHERE parent_id IS NULL``
→ IntegrityError → API 500（提取半途中断，extraction_runs 只留部分章节）。

触发条件: **同名条目 re-encounter + category/content 有变化**（同章重跑因增量
跳过 → 不触发）。与 #1297（:275 新建路径，已修）同族；本文件锁 :326 合并路径。

不用 mock repo（#1200 教训: mock 太宽松会掩盖真实缺陷）—— 既有 mock 用例
``test_existing_same_name_entry_still_updates`` 的 ``updated[0].parent_id ==
existing.parent_id`` 在 ``side_effect=lambda s: s`` + 默认 parent_id=None 下恒真
（None == None），正是本缺陷存活至今的原因。本文件走真实 SQLite +
真实 SQLiteWorldRepository + 真实部分唯一索引。

⚠️ ORM 主键用小的确定性 int（uuid4().int 溢 SQLite INT64）；
domain 侧 UUID 由 uuid.UUID(int=n) 映射（仓库惯例）。
"""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from inkflow.core.database import Base  # sys.path 注入后才可导入
from inkflow.domain.models.world import WorldExtractRequest  # sys.path 注入后才可导入
from inkflow.domain.ports.llm_client import (  # sys.path 注入后才可导入
    ChatResponse,
    LLMClientProtocol,
)
from inkflow.domain.ports.prompt_template import (  # sys.path 注入后才可导入
    PromptTemplate,
    PromptTemplateProtocol,
    RenderedPrompt,
)
from inkflow.domain.services._world_extractor import (  # sys.path 注入后才可导入
    WorldExtractor,
)
from inkflow.infrastructure.database.models.world import (  # sys.path 注入后才可导入
    WorldSettingORM,
)
from inkflow.infrastructure.database.repositories.world_repo import (  # sys.path 注入后才可导入
    SQLiteWorldRepository,
)

pytestmark = pytest.mark.asyncio

PID = 1372001
ROOT_ID = 1372011
LEAF_ID = 1372012
DEFAULT_MODEL = "openai/gpt-4o"


def _u(n: int) -> uuid.UUID:
    """小 int → 领域 UUID（仓库惯例：ORM int PK ↔ uuid.UUID(int=n)）."""
    return uuid.UUID(int=n)


def _payload(*, name: str, category: str = "", content: str = "") -> str:
    """构造提取管线合法 JSON 输出（world_settings 键）."""
    return json.dumps(
        {"world_settings": [{"name": name, "category": category, "content": content}]},
        ensure_ascii=False,
    )


def _extractor(session: AsyncSession, payload: str) -> WorldExtractor:
    """真实 repo + 替身 LLM/模板 的提取器（只替外部 LLM 依赖，仓储/DB 全真实）."""
    llm = MagicMock(spec=LLMClientProtocol)
    llm.chat = AsyncMock(return_value=ChatResponse(content=payload, model=DEFAULT_MODEL))

    template = PromptTemplate(
        name="world_extract",
        description="World extraction template",
        system_prompt="你是小说世界观信息提取器。输出严格 JSON。",
        human_prompt="章节文本：\n{text}",
        variables=["text"],
    )
    pm = MagicMock(spec=PromptTemplateProtocol)
    pm.load = MagicMock(return_value=template)
    pm.render = MagicMock(
        return_value=RenderedPrompt(
            messages=[
                {"role": "system", "content": "你是小说世界观信息提取器。输出严格 JSON。"},
                {"role": "user", "content": "章节文本：\n测试文本"},
            ],
            token_estimate=50,
        )
    )
    return WorldExtractor(
        llm_client=llm, prompt_manager=pm, repository=SQLiteWorldRepository(session)
    )


@pytest.fixture
async def merge_env():
    """真实 SQLite（文件库）+ 真实仓储：根条目「世界观根甲」+ 其下子条目「世界观子乙」."""
    tmp = Path(tempfile.mkdtemp()) / "merge1372.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)

    async with sf() as s:
        s.add(
            WorldSettingORM(
                id=ROOT_ID,
                project_id=PID,
                name="世界观根甲",
                category="分类甲",
                content="根条目内容",
            )
        )
        s.add(
            WorldSettingORM(
                id=LEAF_ID,
                project_id=PID,
                parent_id=ROOT_ID,
                name="世界观子乙",
                category="分类甲",
                content="旧内容",
            )
        )
        await s.commit()

    yield sf
    await engine.dispose()


class TestMergeParentPassthrough:
    """#1372 合并路径（同名 re-encounter 更新）不得把 parent_id 写成 NULL."""

    async def test_category_change_update_keeps_parent(self, merge_env) -> None:
        """同名 re-encounter + **category 变化** → 更新成功且 parent_id 保持原父.

        RED（当前实现）: ``repo.update`` 写 parent_id=NULL → 撞根单例索引
        → IntegrityError（= API 500 的内核等价物）。
        """
        sf = merge_env
        payload = _payload(name="世界观子乙", category="分类乙", content="")
        async with sf() as s:
            result = await _extractor(s, payload).extract(
                WorldExtractRequest(project_id=_u(PID), text="t"), default_model=DEFAULT_MODEL
            )

        assert result.created == []
        assert len(result.updated) == 1
        updated = result.updated[0]
        assert updated.id == _u(LEAF_ID)
        assert updated.category == "分类乙"  # 覆盖生效
        assert updated.parent_id == _u(ROOT_ID), "合并更新必须保留原 parent_id（否则成为第二个根）"

    async def test_content_change_update_keeps_parent(self, merge_env) -> None:
        """同名 re-encounter + **content 变化** → 更新成功且 parent_id 保持原父（同上）."""
        sf = merge_env
        payload = _payload(name="世界观子乙", category="", content="新内容")
        async with sf() as s:
            result = await _extractor(s, payload).extract(
                WorldExtractRequest(project_id=_u(PID), text="t"), default_model=DEFAULT_MODEL
            )

        assert result.created == []
        assert len(result.updated) == 1
        updated = result.updated[0]
        assert updated.content == "新内容"  # 覆盖生效
        assert updated.parent_id == _u(ROOT_ID), "合并更新必须保留原 parent_id（否则成为第二个根）"

    async def test_updated_row_still_under_parent_in_db(self, merge_env) -> None:
        """反向断言：落库后该行仍挂在原父下，项目根条目数仍为 1（不是第二个根）."""
        sf = merge_env
        payload = _payload(name="世界观子乙", category="分类乙", content="")
        async with sf() as s:
            await _extractor(s, payload).extract(
                WorldExtractRequest(project_id=_u(PID), text="t"), default_model=DEFAULT_MODEL
            )

        async with sf() as s:
            row = (
                await s.execute(select(WorldSettingORM).where(WorldSettingORM.id == LEAF_ID))
            ).scalar_one()
            assert row.parent_id == ROOT_ID, "落库后该行必须仍挂在原父下（非第二个根）"
            assert row.category == "分类乙"
            roots = (
                await s.execute(
                    select(func.count())
                    .select_from(WorldSettingORM)
                    .where(
                        WorldSettingORM.project_id == PID,
                        WorldSettingORM.parent_id.is_(None),
                    )
                )
            ).scalar_one()
        assert roots == 1, f"项目根条目必须仍唯一，实得 {roots}"

    async def test_unchanged_entry_still_returns_none(self, merge_env) -> None:
        """无变化（category/content 与库中一致）→ 幂等跳过，updated 为空（既有 :324 判据不破）."""
        sf = merge_env
        payload = _payload(name="世界观子乙", category="分类甲", content="旧内容")
        async with sf() as s:
            result = await _extractor(s, payload).extract(
                WorldExtractRequest(project_id=_u(PID), text="t"), default_model=DEFAULT_MODEL
            )

        assert result.created == []
        assert result.updated == [], "字段无变化时应幂等跳过（不更新、不计入 updated）"

    async def test_root_unique_index_really_present(self, merge_env) -> None:
        """守护：真实库确实存在根单例部分唯一索引（证 RED 非环境假象）.

        首轮即 PASS —— 锁住「不许为绕过失败而丢弃/绕过索引」这条退路
        （#1297 同款机制的 DB 兜底，见 tests/unit/core/test_world_root_unique_index.py）。
        """
        sf = merge_env
        async with sf() as s:
            s.add(
                WorldSettingORM(
                    id=1372099, project_id=PID, name="世界观根丙", category="", content=""
                )
            )
            with pytest.raises(IntegrityError):
                await s.commit()
