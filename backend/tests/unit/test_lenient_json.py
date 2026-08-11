"""LenientJSON 容错契约（#261 rc5 实测）：空串/None/损坏 JSON 读取 → fallback，正常 JSON → dict。"""

from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.engine import create_engine
from sqlalchemy.pool import StaticPool

from inkflow.core.database import LenientJSON


def _process(raw, fallback=None):
    """模拟 SQLAlchemy 读路径：result_processor(dialect, coltype) 返回的处理器。"""
    col = LenientJSON(fallback=fallback)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    proc = col.result_processor(engine.dialect, JSON())
    return proc(raw)


class TestLenientJSON:
    def test_normal_dict_roundtrip(self):
        """正常 JSON 字符串 → dict（原行为不变）。"""
        assert _process('{"a": 1}') == {"a": 1}

    def test_empty_string_returns_fallback(self):
        """#261 实测：DB 空串（extra 未填）→ fallback 而非 json.loads 崩溃。"""
        assert _process("", fallback={}) == {}
        assert _process("", fallback=[]) == []

    def test_none_returns_fallback(self):
        """NULL 列 → fallback（容错）。"""
        assert _process(None, fallback={}) == {}

    def test_corrupt_json_returns_fallback(self):
        """损坏 JSON → fallback（容错，不抛 ValueError）。"""
        assert _process("{not-json", fallback={}) == {}

    def test_whitespace_string_returns_fallback(self):
        """纯空白串 → fallback（json.loads 对空白串的兼容）。"""
        assert _process("   ", fallback={}) == {}

    def test_list_json_passthrough(self):
        """JSON 数组（如 agent_templates.roles）→ list（原行为不变）。"""
        assert _process('["a", "b"]', fallback={}) == ["a", "b"]
