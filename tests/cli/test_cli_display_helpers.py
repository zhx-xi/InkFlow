"""CLI 展示辅助函数直测 — F38 #169 覆盖率补测（纯函数，无 CliRunner）。

Coverage-Gap 补测（2026-08-09）：命令模块人类可读输出辅助函数在
mock CLI 测试中未触达的 miss 分支。直接调用纯函数断言输出。

GREEN 实现契约（backend/src/inkflow/cli/commands/ 各模块辅助函数）：
- vector._retrieved_label(entity: dict, index: int) -> str
  （metadata.name 缺省回退 entity_id、空 content、多行取首行）
- extract._summarize(result: dict) -> str
  （SKIPPED 分支、无 skipped_reason 回退「内容未变更」）
- extract._status_line(run: dict) -> str（SKIPPED / error / success 三态）
- timeline._time_label(event: dict) -> str
  （time_value 与 time_display 均缺 →「时间未知」；display 优先）
- style._top_words_line(words: list[dict]) -> str
  （前 N 个 `词(次数)` 空格连接；超限加省略号）
- foreshadowing._status_label(status: str) -> str 与 _item_label(item: dict) -> str
  （SKIPPED/resolved 等状态文案）
- audit._dimension_label(finding: dict) -> str 与 _counts_line(report: dict) -> str
"""

from __future__ import annotations

from inkflow.cli.commands import audit as audit_mod
from inkflow.cli.commands import extract as extract_mod
from inkflow.cli.commands import foreshadowing as foreshadowing_mod
from inkflow.cli.commands import style as style_mod
from inkflow.cli.commands import timeline as timeline_mod
from inkflow.cli.commands import vector as vector_mod


class TestVectorDisplay:
    """vector._retrieved_label / _reindex_summary 展示分支。"""

    def test_retrieved_label_metadata_name(self):
        """metadata.name 存在 → 显示名称。"""
        label = vector_mod._retrieved_label(
            {
                "entity_id": "e1",
                "entity_type": "character",
                "relevance_score": 0.82,
                "metadata": {"name": "主角"},
                "content": "第一行\n第二行",
            },
            0,
        )
        assert "主角" in label
        assert "character" in label
        assert "0.82" in label

    def test_retrieved_label_fallback_entity_id(self):
        """metadata 缺失/无 name → 回退 entity_id。"""
        label = vector_mod._retrieved_label(
            {
                "entity_id": "e-42",
                "entity_type": "world",
                "relevance_score": 0.5,
                "content": "",
            },
            1,
        )
        assert "e-42" in label
        assert "1." in label  # 序号

    def test_retrieved_label_empty_content_first_line(self):
        """content 空 → 无首行摘录（不崩溃）；多行取首行。"""
        label = vector_mod._retrieved_label(
            {
                "entity_id": "e2",
                "entity_type": "character",
                "relevance_score": 0.9,
                "content": "",
            },
            2,
        )
        assert "e2" in label
        label2 = vector_mod._retrieved_label(
            {
                "entity_id": "e3",
                "entity_type": "character",
                "relevance_score": 0.1,
                "content": "首行\n次行",
            },
            3,
        )
        assert "首行" in label2

    def test_retrieved_label_long_first_line_truncated(self):
        """首行超 50 字符 → 截断加省略号。"""
        long_line = "字" * 60
        label = vector_mod._retrieved_label(
            {
                "entity_id": "e4",
                "entity_type": "character",
                "relevance_score": 0.3,
                "content": long_line,
            },
            4,
        )
        assert "……" in label

    def test_reindex_summary(self):
        """重建索引摘要：类型列表 + 数量。"""
        label = vector_mod._reindex_summary(
            {"entity_types": ["character", "world"], "indexed": 5}
        )
        assert "character/world" in label
        assert "5" in label


class TestExtractDisplay:
    """extract._summarize / _status_line 展示分支。"""

    def test_summarize_skipped_with_reason(self):
        label = extract_mod._summarize(
            {"status": "skipped", "type": "character", "skipped_reason": "无新内容"}
        )
        assert "提取跳过" in label
        assert "无新内容" in label

    def test_summarize_skipped_without_reason(self):
        """无 skipped_reason → 回退「内容未变更」。"""
        label = extract_mod._summarize({"status": "skipped", "type": "world"})
        assert "内容未变更" in label

    def test_status_line_success(self):
        label = extract_mod._status_line(
            {
                "type": "character",
                "source_key": "s1",
                "status": "success",
                "created_count": 1,
                "updated_count": 0,
                "indexed": True,
                "run_at": "2026-08-02T10:00:00",
            }
        )
        assert "success" in label
        assert "新增 1 更新 0" in label
        assert "已索引" in label

    def test_status_line_success_not_indexed(self):
        """indexed=False → 无「已索引」后缀。"""
        label = extract_mod._status_line(
            {
                "type": "character",
                "source_key": "s1",
                "status": "success",
                "created_count": 0,
                "updated_count": 2,
                "indexed": False,
                "run_at": "2026-08-02T10:00:00",
            }
        )
        assert "已索引" not in label

    def test_status_line_skipped(self):
        label = extract_mod._status_line(
            {
                "type": "setting",
                "source_key": "m1",
                "status": "skipped",
                "run_at": "10:00",
            }
        )
        assert "skipped" in label

    def test_status_line_error(self):
        label = extract_mod._status_line(
            {
                "type": "foreshadowing",
                "source_key": "f1",
                "status": "error",
                "error": "解析失败",
                "run_at": "10:00",
            }
        )
        assert "error" in label
        assert "解析失败" in label

    def test_status_line_error_no_error_key(self):
        """error 字段缺失 → 回退「提取失败」。"""
        label = extract_mod._status_line(
            {
                "type": "character",
                "source_key": "s2",
                "status": "error",
                "run_at": "10:00",
            }
        )
        assert "提取失败" in label


class TestTimelineDisplay:
    """timeline._time_label 展示分支。"""

    def test_time_label_unknown(self):
        """time_value 与 time_display 均缺 → 时间未知。"""
        assert timeline_mod._time_label({}) == "时间未知"

    def test_time_label_display_priority(self):
        """time_display 优先。"""
        assert (
            timeline_mod._time_label(
                {"time_display": "青元历 317 年秋", "time_value": 317.5}
            )
            == "青元历 317 年秋"
        )

    def test_time_label_fallback_value(self):
        """无 display → str(time_value)。"""
        assert timeline_mod._time_label({"time_value": 42.0}) == "42.0"


class TestStyleDisplay:
    """style._top_words_line 展示分支。"""

    def test_top_words_line_normal(self):
        label = style_mod._top_words_line(
            [{"word": "剑", "count": 12}, {"word": "云", "count": 5}]
        )
        assert "剑(12)" in label
        assert "云(5)" in label

    def test_top_words_line_overflow(self):
        """超过 TOP_WORDS_LIMIT → 加省略号（不崩溃）。"""
        words = [{"word": f"w{i}", "count": i} for i in range(20)]
        label = style_mod._top_words_line(words)
        assert "w0" in label
        assert "…" in label or "..." in label


class TestForeshadowingDisplay:
    """foreshadowing._status_label / _item_label 展示分支。"""

    def test_status_label_open(self):
        """open → 未回收。"""
        assert foreshadowing_mod._status_label({"status": "open"}) == "未回收"

    def test_status_label_resolved(self):
        """resolved → 已回收。"""
        assert foreshadowing_mod._status_label({"status": "resolved"}) == "已回收"

    def test_item_label_open_with_location(self):
        item = {"status": "open", "title": "伏笔A", "priority": 3, "location": "第5章"}
        label = foreshadowing_mod._item_label(item)
        assert "伏笔A" in label
        assert "第5章" in label

    def test_item_label_open_no_location(self):
        """location 缺失 → 无位置后缀。"""
        item = {"status": "open", "title": "伏笔B", "priority": 1}
        label = foreshadowing_mod._item_label(item)
        assert "伏笔B" in label

    def test_item_label_resolved_with_date(self):
        item = {
            "status": "resolved",
            "title": "伏笔C",
            "resolved_at": "2026-08-01T10:00:00",
        }
        label = foreshadowing_mod._item_label(item)
        assert "回收于 2026-08-01" in label

    def test_item_label_resolved_no_date(self):
        item = {"status": "resolved", "title": "伏笔D"}
        label = foreshadowing_mod._item_label(item)
        assert "已回收" in label


class TestAuditDisplay:
    """audit._dimension_label / _counts_line 展示分支。"""

    def test_dimension_label_known(self):
        assert "角色" in audit_mod._dimension_label({"dimension": "character"})

    def test_dimension_label_unknown(self):
        """未知维度 → 原样返回。"""
        assert audit_mod._dimension_label({"dimension": "weird"}) == "weird"

    def test_counts_line(self):
        line = audit_mod._counts_line(
            {"summary": {"counts": {"character": 3, "world": 2}}}
        )
        assert "3" in line
        assert "2" in line
