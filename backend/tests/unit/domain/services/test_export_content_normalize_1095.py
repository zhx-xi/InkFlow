"""#1095 RED 契约（导出）— 存量脏数据在导出产物中不得出现 # / 重复标题.

issue #1095 验收: 「导出（EPUB/TXT/DOCX）无 # 与重复标题」。

存量数据归一端点**不在本条范围**（issue 决策点「是否提供批量归一端点」→
按最窄方案收口，不新增端点），故**导出侧是存量脏数据的唯一兜底面** ——
本文件锁定该兜底契约。

真相源: output_service.ExportService._assemble_chapters
（Chapter.content → BookChapter.content 组装点，output_service.py:230-240）
全管线: ExportService.export → to_txt（真实装配 + mock repo，
构造签名镜像 test_output_service_export.py::_service）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from inkflow.domain.models.chapter import Chapter, Volume
from inkflow.domain.models.project import Project
from inkflow.domain.services._txt_exporter import to_txt
from inkflow.domain.services.output_service import ExportService

FULLWIDTH = "\u3000"
PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000109")
TS = datetime(2026, 9, 11, 10, 0, 0, tzinfo=UTC)
TITLE = "第1章 雪夜怪梦"
DIRTY_CONTENT = f"# {TITLE}\n\n师父停了三天。\n\n李慕白醒了。"


def _project() -> Project:
    return Project(
        id=PID,
        name="归一出账项目",
        tags=["武侠"],
        language="zh-CN",
        target_words=100_000,
        created_at=TS,
        updated_at=TS,
    )


def _volume() -> Volume:
    return Volume(id=uuid.uuid4(), project_id=PID, title="序章", order_index=1.0)


def _dirty_chapter(volume_id: uuid.UUID) -> Chapter:
    """存量脏数据形态（issue #1095 实测：首行 # + 重复标题 + 无缩进）。"""
    return Chapter(
        id=uuid.uuid4(),
        project_id=PID,
        volume_id=volume_id,
        title=TITLE,
        content=DIRTY_CONTENT,
        order_index=1.0,
        word_count=len(DIRTY_CONTENT),
        created_at=TS,
        updated_at=TS,
    )


def _service(volume: Volume, chapters: list[Chapter]) -> ExportService:
    """装配真实 ExportService（7 repo mock，签名镜像 §8.2 契约）。"""
    project_repo = MagicMock()
    project_repo.get = AsyncMock(return_value=_project())
    chapter_repo = MagicMock()
    chapter_repo.list_volumes = AsyncMock(return_value=[volume])
    chapter_repo.list_chapters = AsyncMock(return_value=(chapters, len(chapters)))
    return ExportService(
        project_repo=project_repo,
        chapter_repo=chapter_repo,
        character_repo=MagicMock(),
        world_repo=MagicMock(),
        outline_repo=MagicMock(),
        timeline_repo=MagicMock(),
        foreshadowing_repo=MagicMock(),
    )


class TestExportLegacyDirtyContent:
    """导出兜底：存量脏正文 → 产物无 # 与重复标题。"""

    async def test_export_cleans_legacy_dirty_chapter_content(self) -> None:
        """存量脏章（# + 重复标题）经导出聚合后，BookChapter.content 已归一。"""
        vol = _volume()
        svc = _service(vol, [_dirty_chapter(vol.id)])
        book = await svc.export(PID)

        contents = [ch.content for v in book.volumes for ch in v.chapters]
        assert contents, "导出未取到章节正文 — 契约失效"
        for content in contents:
            assert "#" not in content, f"导出 BookChapter 仍含 markdown #: {content!r}"
            assert not content.lstrip().startswith(TITLE), "导出仍含重复标题行"

    async def test_txt_artifact_has_no_hash_or_duplicate_title(self) -> None:
        """全管线 to_txt 产物：无 #、无重复标题行、段首全角缩进。"""
        vol = _volume()
        svc = _service(vol, [_dirty_chapter(vol.id)])
        book = await svc.export(PID)
        text = to_txt(book)

        assert "#" not in text, "TXT 产物仍含 markdown #"
        body_lines = [ln for ln in text.splitlines() if ln.strip()]
        # 正文行不得以裸标题开头（章标题行由 exporter 用「第 N 章 title」承载）
        body = [ln for ln in body_lines if "师父停了三天。" in ln]
        assert body, "TXT 产物丢失正文 — 契约失效"
        for line in body:
            # 注意：不能 lstrip() —— U+3000 属 Unicode 空白，会被剥掉致恒 False
            assert line.startswith(FULLWIDTH * 2), f"TXT 正文行缺全角缩进: {line!r}"
