"""#902 RED 契约 F1：usage 提取 helper（usage_accounting 模块，纯 domain 函数）。

权威来源：.hermes/plans/contract-902.md §1.2/§1.6。
新文件 backend/src/inkflow/domain/services/usage_accounting.py（GREEN 创建，无框架依赖）:

    def result_usage(result: dict) -> tuple[int, int, int]:
        \"\"\"agent.invoke 结果 → (prompt, completion, total)。
        主源：逐 message usage_metadata（input_tokens/output_tokens/total_tokens，
        兼容 prompt_tokens/completion_tokens 别名键）全消息求和；
        回退：顶层 result["usage"]（legacy/fake）；双源皆缺 → (0, 0, 0)。
        total 以 total_tokens 为准（不用 p+c 推算）。\"\"\"

    def chat_response_usage(response: object) -> tuple[int, int, int]:
        \"\"\"llm.chat 返回值 → (prompt, completion, total)。
        主源：response.token_usage（ChatResponse：prompt_tokens/completion_tokens/
        total_tokens，None 安全）；回退：response.usage_metadata dict（AIMessage 鸭子）；
        皆缺 → (0, 0, 0)。全部 getattr/None 守卫，鸭子对象无 usage → 不抛。\"\"\"

用例标注：
- 【R】当前模块不存在 → 函数体 import ImportError → FAILED（修复锚）。
- 【G】book_service._extract_usage_tokens 迁移后经 re-export 必须继续可用——
  守护（当前存在，RED 期 PASS 刻意）。

【符号导入铁律】新符号（usage_accounting.result_usage / chat_response_usage）全部
函数体内 import：模块级 import 失败 → 整文件 collection error（#669 实测惯例）。
"""

from __future__ import annotations

from types import SimpleNamespace


def _msg(content: str = "正文", usage_metadata: dict | None = None) -> SimpleNamespace:
    """带 usage_metadata 的 message 鸭子对象（真实 AIMessage 形态）。"""
    return SimpleNamespace(content=content, usage_metadata=usage_metadata)


# ── result_usage：逐 message usage_metadata 求和（主源）─────────────


def test_result_usage_sums_message_usage_metadata_object_and_dict() -> None:
    """【R】object + dict 双形态 message 的 usage_metadata 全消息求和：
    m1 {input 10/output 20/total 30} + m2 dict {input 100/output 200/total 300}
    → (110, 220, 330)（prompt=input 系，completion=output 系）。

    RED 形态：usage_accounting 模块不存在 → 函数体 ImportError。
    """
    from inkflow.domain.services.usage_accounting import result_usage

    result = {
        "messages": [
            _msg(usage_metadata={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}),
            {
                "content": "b",
                "usage_metadata": {
                    "input_tokens": 100,
                    "output_tokens": 200,
                    "total_tokens": 300,
                },
            },
        ]
    }
    assert result_usage(result) == (110, 220, 330)


def test_result_usage_alias_keys_prompt_completion() -> None:
    """【R】langchain legacy/别名键族：usage_metadata 含 prompt_tokens/completion_tokens
    （.hermes/repro_902.py USAGE_PER_CALL 形态）→ (60, 40, 100)。"""
    from inkflow.domain.services.usage_accounting import result_usage

    result = {
        "messages": [
            _msg(usage_metadata={"prompt_tokens": 60, "completion_tokens": 40, "total_tokens": 100})
        ]
    }
    assert result_usage(result) == (60, 40, 100)


def test_result_usage_top_level_usage_fallback() -> None:
    """【R】messages 无 usage → 回退顶层 result["usage"]（legacy/fake 契约）：
    {prompt 5/completion 3/total 25} → (5, 3, 25)。"""
    from inkflow.domain.services.usage_accounting import result_usage

    result = {
        "messages": [_msg(content="x", usage_metadata=None)],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 25},
    }
    assert result_usage(result) == (5, 3, 25)


def test_result_usage_missing_both_sources_returns_zero() -> None:
    """【R】双源皆缺 → (0, 0, 0)：messages 无 usage_metadata 且无顶层 usage；
    无 messages 键同样 (0,0,0) 不抛。"""
    from inkflow.domain.services.usage_accounting import result_usage

    assert result_usage({"messages": [SimpleNamespace(content="x"), {"content": "y"}]}) == (0, 0, 0)
    assert result_usage({}) == (0, 0, 0)


def test_result_usage_total_uses_total_tokens_not_pc_derived() -> None:
    """【R】total 以 total_tokens 为准，禁止用 p+c 推算：
    usage_metadata {input 100/output 200/total 250}（p+c=300 ≠ 250）→ total 必须 250。"""
    from inkflow.domain.services.usage_accounting import result_usage

    result = {
        "messages": [
            _msg(usage_metadata={"input_tokens": 100, "output_tokens": 200, "total_tokens": 250})
        ]
    }
    assert result_usage(result) == (100, 200, 250)


# ── chat_response_usage：llm.chat 返回值 → 三元组 ──────────────────


def test_chat_response_usage_token_usage_object() -> None:
    """【R】主源 response.token_usage（ChatResponse 形态：prompt/completion/total）：
    {prompt 7/completion 9/total 16} → (7, 9, 16)。"""
    from inkflow.domain.services.usage_accounting import chat_response_usage

    response = SimpleNamespace(
        content="ok",
        token_usage=SimpleNamespace(prompt_tokens=7, completion_tokens=9, total_tokens=16),
    )
    assert chat_response_usage(response) == (7, 9, 16)


def test_chat_response_usage_usage_metadata_dict_fallback() -> None:
    """【R】回退 response.usage_metadata dict（AIMessage 鸭子）：
    {prompt 3/completion 4/total 7} → (3, 4, 7)。"""
    from inkflow.domain.services.usage_accounting import chat_response_usage

    response = SimpleNamespace(
        content="ok", usage_metadata={"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}
    )
    assert chat_response_usage(response) == (3, 4, 7)


def test_chat_response_usage_duck_without_usage_zero_no_raise() -> None:
    """【R】鸭子对象无任何 usage 载体 → (0, 0, 0) 不抛（SimpleNamespace 仅 content）。"""
    from inkflow.domain.services.usage_accounting import chat_response_usage

    assert chat_response_usage(SimpleNamespace(content="ok")) == (0, 0, 0)
    assert chat_response_usage(
        SimpleNamespace(content="ok", token_usage=None, usage_metadata=None)
    ) == (0, 0, 0)


def test_chat_response_usage_none_fields_defensive() -> None:
    """【R】None 字段防御：token_usage 各字段 None → 0；usage_metadata dict 值
    None → 0（int(None) 不抛）；混合（prompt 有值其余 None）→ (3, 0, 0)。"""
    from inkflow.domain.services.usage_accounting import chat_response_usage

    tu_none = SimpleNamespace(prompt_tokens=None, completion_tokens=None, total_tokens=None)
    assert chat_response_usage(SimpleNamespace(content="ok", token_usage=tu_none)) == (0, 0, 0)
    meta = {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}
    assert chat_response_usage(SimpleNamespace(content="ok", usage_metadata=meta)) == (0, 0, 0)
    meta2 = {"prompt_tokens": 3, "completion_tokens": None, "total_tokens": None}
    assert chat_response_usage(SimpleNamespace(content="ok", usage_metadata=meta2)) == (3, 0, 0)


# ── G 守护：book_service._extract_usage_tokens 迁移后 re-export ────


def test_extract_usage_tokens_reexport_still_available() -> None:
    """【G】§1.6 迁移守护：helper 迁入 usage_accounting 后 book_service 顶部 import
    result_usage 并在原位置 re-export _extract_usage_tokens——既有测试
    `from inkflow.domain.services.book_service import _extract_usage_tokens` 必须
    继续可用且语义不变（返回累计 total_tokens：逐 message 求和 + 顶层 usage 回退）。

    守护用例 RED 期 PASS 刻意：当前 _extract_usage_tokens 就定义于 book_service。
    """
    from inkflow.domain.services.book_service import _extract_usage_tokens

    result = {
        "messages": [
            _msg(
                usage_metadata={
                    "total_tokens": 100,
                    "prompt_tokens": 60,
                    "completion_tokens": 40,
                }
            ),
            {"content": "b", "usage_metadata": {"total_tokens": 200}},
        ]
    }
    assert _extract_usage_tokens(result) == 300
    # 顶层 result["usage"] 回退（legacy/fake）
    assert _extract_usage_tokens({"usage": {"total_tokens": 42}}) == 42
    # 双源皆缺 → 0
    assert _extract_usage_tokens({"messages": [SimpleNamespace(content="x")]}) == 0
