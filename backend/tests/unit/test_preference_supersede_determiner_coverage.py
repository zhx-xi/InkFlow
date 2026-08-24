"""#627 coverage-gap closure: 补 preference_supersede_determiner._extract_json_fragment
漏覆盖分支（嵌套回边 L77->61 / 转义 L64->65·L66->67 / 未闭合 L61->79）。

同形于 _llm_chunk_analyzer（F16/F45 骨架公共逻辑）：_extract_json_fragment 的
字符串转义与花括号深度扫描是多个 F 系列模块的拷贝，各模块独立计覆盖。
"""

from __future__ import annotations

from inkflow.domain.services.preference_supersede_determiner import _extract_json_fragment


class TestFragmentCoverage:
    """preference_supersede_determiner._extract_json_fragment 防御分支。"""

    def test_nested_braces_back_edge(self):
        """嵌套花括号：深度未归零继续扫描（L77->61 回边）。"""
        assert _extract_json_fragment("{{a}}") == "{{a}}"

    def test_escaped_string(self):
        """字符串字面量内转义（\\ / \"）→ 跳过（L64->65 / L66->67）。"""
        import json

        raw = json.dumps({"a": "x\\ny"}, ensure_ascii=False)
        assert _extract_json_fragment(raw) == raw

    def test_unterminated_returns_none(self):
        """有 { 无配对 } → None（L61->79 / line 79）。"""
        assert _extract_json_fragment("{abc") is None
