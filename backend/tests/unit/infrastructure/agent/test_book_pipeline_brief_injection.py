"""F44 T3 卷级轨 · 章 brief 设定注入契约 — RED（#1185 + A3/A4/A5/A10）。

权威来源：`docs/evidence/audit-writing-chain-2026-09-15.md` P0-2 / P1-1 / P1-2 / P1-5 / P1-6。

被测对象：`inkflow/infrastructure/agent/book_pipeline.py::BookVolumePipeline`
（T3 轨，`books.py:513` mode=volume 入口；brief 为三份逐字复制品之一，
`book_pipeline.py:537-547`）。

为什么独立成文
--------------
`book_pipeline.py` 的 brief 复制品与 `book_service.py` / `book_agentic_pipeline.py`
逐字相同（F1），但**没有任何单测**覆盖它——三轨中唯一零测试的复制品。
T2 轨覆盖在 `test_book_service_brief_injection.py`、T4 轨在
`test_book_agentic_audit_contract.py`，本文件补齐 T3，三轨对称。

契约（GREEN 必须满足）
---------------------
`BookVolumePipeline._build_chapter_brief(plan, chapter, *, context="",
project_style="", default_words=None)`：

1. 注入的 F6 上下文文本进 brief（角色/世界观/伏笔），不落占位符
2. 项目级 `writing_style` 实值进 brief（而非常量祈使句）
3. 章级 `writing_requirements` 进 brief（P1-1：字段零消费——模型/迁移/repo 齐全）
4. `default_words` 目标字数进 brief（P1-6：book 三轨均无字数约束）

RED 预期：当前 `book_pipeline.py:537-547` 无上述任何参数 → 全部 FAIL。

可证伪性：把对应注入改成空串 → 该用例必 FAIL。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from inkflow.domain.models.writing_plan import WritingPlan
from inkflow.infrastructure.agent.book_pipeline import BookVolumePipeline

# ── fixture 锚点值（真实可辨识，与实现字面量不同源）──────────────────

REAL_CONTEXT = "【世界观】青鸾峰终年积雪，剑冢埋有前朝名剑\n【伏笔】青铜药臼应显裂纹"
REAL_STYLE = "慢热日常·白描·忌打脸立威"
REAL_REQUIREMENT = "本章须以医馆场景开篇，禁止出现打脸立威桥段"
PLACEHOLDER_MAIN = "主角自定"
PLACEHOLDER_REF = "见角色档案"


def _plan(**overrides) -> WritingPlan:
    base = dict(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        title="测试计划",
        status="ready",
        root_outline_id=uuid.uuid4(),
        character_ids=[uuid.uuid4()],
        limits={},
        progress={},
        execution_refs={},
        thread_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    base.update(overrides)
    return WritingPlan(**base)


def _chapter(**overrides) -> dict:
    base = {
        "outline_id": uuid.uuid4(),
        "chapter_id": uuid.uuid4(),
        "name": "第一章",
        "description": "主角在时间旅途中发现悖论",
        "sort_order": 0,
    }
    base.update(overrides)
    return base


def _brief(plan: WritingPlan, chapter: dict, **kw) -> str:
    return BookVolumePipeline._build_chapter_brief(plan, chapter, **kw)


# ── A1/A5：设定上下文（含伏笔）进 brief ────────────────────────────────


class TestVolumeBriefContext:
    def test_brief_carries_injected_setting_context(self):
        """装配层注入的 F6 上下文文本原样进 brief（角色/世界观/伏笔）。

        可证伪性：context 注入删掉（现状：参数不存在）→ FAIL。
        """
        brief = _brief(_plan(), _chapter(), context=REAL_CONTEXT)

        assert "青鸾峰" in brief
        assert "青铜药臼" in brief

    def test_brief_no_placeholder_with_character_ids(self):
        """character_ids 非空 → brief 不含占位符串（P0-2 占位符消除）。

        可证伪性：恢复现状实现 → FAIL（恒落「见角色档案（plan.character_ids）」）。
        """
        brief = _brief(_plan(), _chapter(), context=REAL_CONTEXT)

        assert PLACEHOLDER_MAIN not in brief
        assert PLACEHOLDER_REF not in brief


# ── A3：项目级 writing_style 实值 ──────────────────────────────────────


class TestVolumeBriefStyle:
    def test_brief_carries_project_writing_style_value(self):
        """brief 含项目级 writing_style 实值，而非常量祈使句。

        可证伪性：style 注入删掉（现状恒为字面量）→ FAIL。
        """
        brief = _brief(_plan(), _chapter(), project_style=REAL_STYLE)

        assert REAL_STYLE in brief, "风格段必须含项目 writing_style 实值"


# ── A4：章级 writing_requirements 优先于项目级 ─────────────────────────


class TestVolumeBriefWritingRequirements:
    def test_brief_carries_chapter_writing_requirements(self):
        """章级 writing_requirements 进 brief（P1-1：字段已存在但业务层零消费）。

        可证伪性：不消费该字段（现状）→ FAIL。
        """
        brief = _brief(_plan(), _chapter(extra={"writing_requirements": REAL_REQUIREMENT}))

        assert REAL_REQUIREMENT in brief

    def test_chapter_requirement_wins_over_project_style(self):
        """章级 requirements 与项目级 style 同时在场 → 两者都在，且章级具优先语义。

        优先级 > 项目级：章级要求必须出现（缺章级 → FAIL）。
        """
        brief = _brief(
            _plan(),
            _chapter(extra={"writing_requirements": REAL_REQUIREMENT}),
            project_style=REAL_STYLE,
        )

        assert REAL_REQUIREMENT in brief
        assert REAL_STYLE in brief


# ── A10：字数约束 ──────────────────────────────────────────────────────


class TestVolumeBriefWordTarget:
    def test_brief_carries_target_word_count(self):
        """brief 含目标字数（project.config.default_words，F15 字段已存在）。

        可证伪性：字数注入删掉（现状 book 三轨均无字数）→ FAIL。
        """
        brief = _brief(_plan(), _chapter(), default_words=800000)

        assert "800000" in brief or "800,000" in brief
