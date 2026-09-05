"""#931 RED 契约：F57 spec §2.2 与 OTel traceparent 实现对齐（spec=truth）。

拍板：correlation/trace 折入 F57 §2.2 —— 日志结构采用 OpenTelemetry/W3C
traceparent 语义（trace_id/span_id/parent_span_id），不再维持「correlation_id
与 trace_id 双轨分离、后端内部补充」的旧表述。

本文件锁定 spec.md 文本契约（GREEN 批同步改 specs/f57-logging-i18n/spec.md §2.2）：
1. §2.2 字段行含 parent_span_id（三件套）；
2. 出现 traceparent / W3C / OpenTelemetry 字样（协议锚点）；
3. 旧句「后端内部 trace_id/span_id 补充」被替换（不得残留）。

RED 形态：spec.md 未更新 → 断言 FAIL。
"""

from __future__ import annotations

from pathlib import Path

SPEC = Path(__file__).resolve().parents[4] / "specs" / "f57-logging-i18n" / "spec.md"


def _section_22() -> str:
    """截取 §2.2 至下一个 '---' 分隔（§2.3/§3 之前）的文本。"""
    text = SPEC.read_text(encoding="utf-8")
    start = text.index("### 2.2")
    end = text.index("---", start)
    return text[start:end]


class TestF57SpecOtelAlignment:
    def test_spec_file_exists(self):
        assert SPEC.is_file(), f"F57 spec 路径漂移: {SPEC}"

    def test_field_list_includes_parent_span_id(self):
        section = _section_22()
        assert "parent_span_id" in section, (
            "#931: §2.2 日志结构字段须含 parent_span_id（OTel span 父子语义）"
        )

    def test_traceparent_protocol_anchor_documented(self):
        section = _section_22()
        assert "traceparent" in section, "§2.2 须记录 W3C traceparent 头协议"
        assert "OpenTelemetry" in section or "OTel" in section, "§2.2 须标注 OTel 语义对齐"

    def test_legacy_dual_track_sentence_removed(self):
        section = _section_22()
        assert "后端内部 `trace_id`/`span_id` 补充" not in section, (
            "#931 拍板：旧「correlation 主链 + trace 后端内部补充」分离表述已废弃"
        )

    def test_header_format_documented(self):
        section = _section_22()
        assert "00-" in section and "32" in section, (
            "§2.2 须写明 traceparent 格式（version-trace(32hex)-span(16hex)-flags）"
        )
