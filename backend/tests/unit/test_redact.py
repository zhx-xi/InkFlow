"""#614 对话输入机密脱敏 — `redact_secrets` RED 契约（specs/f53-secret-redact/spec.md §4.1）。

目标：redact_secrets(prompt, known_keys) -> str（llm/redact.py，尚未实现）。
契约用例（spec §3.1/§3.3/§4.1）：
- A 正则兜底（known_keys=[]）：sk-+/Bearer+/长 token 串 → '****'；普通中文/URL 不误伤
- B 已存 key 精确子串替换：known_keys 内 key 明文 → '****'
- known_keys=[] → 仅 A 生效；无匹配 → 原样返回

注：所有密钥/关键词样例用「模块级变量拼接构造」（源码不出现连续 sk-/Bearer 形态），
避免被上层输出脱敏机制污染测试夹具。RED 状态：redact.py 未创建 → import 即失败（门禁 M1）。
"""

from unittest.mock import MagicMock, patch

from inkflow.infrastructure.llm.redact import load_known_keys, redact_secrets

# ── 拼接构造（运行时值正确，源码不含连续敏感形态）──
SK_KEY = "sk-" + ("a" * 16)  # sk-aaa...aaa（16 位体）
SK_MASKED = "sk-" + "****"  # 期望输出 sk-****
BEARER = "Bea" + "rer"  # Bearer
BEARER_MASKED = "Bea" + "rer " + "****"  # Bearer ****
LONG_RUN = "c" * 30  # 30 位连续字母（疑似 token）


def test_a_regex_sk_key_replaced_keep_prefix():
    """A：sk- 形态 → 结果含 'sk-****'（key 体替换，前缀保留）。"""
    result = redact_secrets(SK_KEY, [])
    assert SK_MASKED in result
    assert SK_KEY not in result


def test_a_regex_bearer_token_replaced():
    """A：Authorization: <Bearer> token → 结果含 'Bearer ****'（token 替换）。"""
    prompt = "Authorization: " + BEARER + " " + ("b" * 20)
    result = redact_secrets(prompt, [])
    assert BEARER_MASKED in result
    assert ("b" * 20) not in result


def test_a_regex_long_token_run_replaced():
    """A：连续 >=24 位 [A-Za-z0-9_-] 串（疑似 token）→ 整体替换为 '****'。"""
    assert redact_secrets(LONG_RUN, []) == "****"


def test_a_regex_plain_chinese_and_url_untouched():
    """A：普通中文文本 / URL 原样返回（不误伤）。"""
    text = "今天我写了一个故事 https://ex.com/a"
    assert redact_secrets(text, []) == text


def test_b_known_key_substring_replaced():
    """B：known_keys 内 key 明文在 prompt 中被 '****' 替换。"""
    key = "sk-" + ("x" * 10)  # sk-xxxxxxxxxx（10 位体）
    prompt = "用密钥 " + key + " 测试"
    result = redact_secrets(prompt, [key])
    assert "****" in result
    assert key not in result


def test_known_keys_empty_only_regex_effective():
    """known_keys=[] → 仅 A 生效：sk- 后体 <12 位（A 阈值外）的 key 原样保留。"""
    key = "sk-" + ("x" * 10)  # 体 10 位 < 12（A 正则不匹配）
    prompt = "用密钥 " + key + " 测试"
    assert redact_secrets(prompt, []) == prompt


def test_no_match_returns_original():
    """无匹配 → 原样返回。"""
    text = "你好，今天天气不错，我们继续写作。"
    assert redact_secrets(text, []) == text


def test_known_keys_defaults_to_empty():
    """known_keys 缺省（None）→ 等同空列表，仅 A 生效。"""
    result = redact_secrets(SK_KEY)
    assert SK_MASKED in result


def test_load_known_keys_returns_provider_keys_and_skips_failure():
    """load_known_keys：正常返回各 provider 明文；单个解密失败跳过该项，不抛错。"""
    mgr = MagicMock()
    mgr.list_providers.return_value = ["p1", "p2", "p3"]
    mgr.load.side_effect = ["key1", Exception("decrypt fail"), "key3"]
    with patch("inkflow.infrastructure.llm.redact.APIKeyManager", return_value=mgr):
        assert load_known_keys() == ["key1", "key3"]


def test_load_known_keys_empty_when_no_provider():
    """load_known_keys：无任何已存 provider → 空列表。"""
    mgr = MagicMock()
    mgr.list_providers.return_value = []
    with patch("inkflow.infrastructure.llm.redact.APIKeyManager", return_value=mgr):
        assert load_known_keys() == []


def test_b_known_key_dot_separated_no_tail_leak():
    """B：已存密钥为 `<32hex>.<16char>`（含 `.` 分隔）→ 整串 key（含 `.`）+ 16char 尾部均不泄漏。

    #632 回归测试：旧实现先长串正则（_LONG_RUN_PATTERN 把 32hex 打成 ****）→
    known-keys 的 key.replace(整串) 匹配失败 → 16char 尾部残留。契约：known-keys
    整串替换必须先于长串正则兜底，保证已存密钥无论是否被部分命中都完整遮蔽。
    """
    key = ("a" * 32) + "." + ("b" * 16)  # <32hex>.<16char> 已存密钥形态
    tail = ("b" * 16)
    prompt = "Authorization: " + key
    result = redact_secrets(prompt, [key])
    assert key not in result
    assert tail not in result
