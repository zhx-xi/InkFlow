"""F48 知识图谱关系提取 LLM 辅助 — 解析容错各错误分支契约测试（#479 GREEN 补测）。

覆盖 _kg_relation_extractor 的 JSON 数组容错解析边界（#479 覆盖率收尾）：
- _extract_array_fragment 转义引号（in_string/escaped 分支）+ 无 [ 片段
- parse_kg_relations：无数组片段 / JSON 语法错误 / 顶层非数组 / 元素非对象 /
  缺字段 / from_type/to_type 非法
依据: specs/f48-knowledge-graph/spec.md §5.5.4（AI 输出契约 [{from_name, ...}]）。
"""

from __future__ import annotations

from inkflow.domain.services._kg_relation_extractor import (
    _extract_array_fragment,
    build_fix_prompt,
    parse_kg_relations,
)


def _valid_item() -> dict:
    return {
        "from_name": "林尘",
        "from_type": "character",
        "to_name": "天玄大陆",
        "to_type": "world",
        "relation_type": "历练于",
    }


class TestExtractArrayFragment:
    """_extract_array_fragment — 平衡数组片段提取边界。"""

    def test_simple_array(self):
        assert _extract_array_fragment('[{"a": 1}]') == '[{"a": 1}]'

    def test_fenced_with_preamble(self):
        out = _extract_array_fragment('好的，以下是结果：\n[{"a": 1}]\n希望有帮助')
        assert out == '[{"a": 1}]'

    def test_string_with_escaped_quote(self):
        # 字符串内含转义引号 → 触发 in_string/escaped 分支（不提前误判 ] 闭合）
        frag = _extract_array_fragment('[{"relation_type": "a\\"b"}]')
        assert frag == '[{"relation_type": "a\\"b"}]'

    def test_no_bracket_returns_none(self):
        assert _extract_array_fragment("不是 JSON，没有括号") is None

    def test_unclosed_bracket_exhausts_loop(self):
        # 有 [ 但从未闭合 → 循环耗尽 depth 未归零 → return None（L72 分支）
        assert _extract_array_fragment('[{"a":1}') is None

    def test_nested_array_depth_tracks(self):
        # 嵌套数组 → depth 到 2 再回落，覆盖 depth != 0 继续遍历分支
        assert _extract_array_fragment('[{"xs":[1,2]}]') == '[{"xs":[1,2]}]'


class TestParseKgRelations:
    """parse_kg_relations — 各失败分支 + 成功路径。"""

    def test_success(self):
        raw = (
            '[{"from_name":"林尘","from_type":"character",'
            '"to_name":"天玄大陆","to_type":"world","relation_type":"历练于"}]'
        )
        parsed, err = parse_kg_relations(raw)
        assert err == ""
        assert len(parsed) == 1
        assert parsed[0]["from_name"] == "林尘"

    def test_no_array_fragment(self):
        parsed, err = parse_kg_relations("没有数组")
        assert parsed is None
        assert "数组片段" in err

    def test_json_syntax_error(self):
        parsed, err = parse_kg_relations("[{这不是合法 json}]")
        assert parsed is None
        assert "JSON 语法错误" in err

    def test_top_level_not_array(self):
        parsed, err = parse_kg_relations('{"a": 1}')
        assert parsed is None
        assert "数组" in err

    def test_item_not_dict(self):
        parsed, err = parse_kg_relations("[1, 2, 3]")
        assert parsed is None
        assert "不是对象" in err

    def test_missing_required_key(self):
        item = _valid_item()
        item.pop("to_type")
        import json

        parsed, err = parse_kg_relations(json.dumps([item], ensure_ascii=False))
        assert parsed is None
        assert "缺少字段" in err and "to_type" in err

    def test_invalid_entity_type(self):
        item = _valid_item()
        item["from_type"] = "map_pin"  # 五类之外
        import json

        parsed, err = parse_kg_relations(json.dumps([item], ensure_ascii=False))
        assert parsed is None
        assert "非法" in err


class TestBuildFixPrompt:
    """build_fix_prompt — 修复重试提示包含错误信息。"""

    def test_includes_error(self):
        out = build_fix_prompt("某某错误")
        assert "某某错误" in out
        assert "JSON" in out
