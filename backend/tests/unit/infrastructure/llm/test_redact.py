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
    tail = "b" * 16
    prompt = "Authorization: " + key
    result = redact_secrets(prompt, [key])
    assert key not in result
    assert tail not in result


# ── S3a 脱敏矩阵补测（非功能安全 C5②，ADR-047 口径） ──────────────────
# 上述 A/B 契约只覆盖「裸 sk-/Bearer/>=24 连续串」与「known_keys 子串」。
# S3a 补 4 类防御边界：JSON 转义 key / 大小写变体 / base64 blob / key 拆词。
# 样例一律模块级拼接构造（源码不出连续敏感形态，防上层输出脱敏污染）。

# JSON 转义 key：key 的字母以 \uXXXX 形态写在 JSON 字符串里（真实 LLM prompt
# 常把 key 塞进 JSON；非 ASCII/控制字符会被 json.dumps 转义成 \uXXXX）。
_JSON_ESC_A = "\\" + "u0041"  # \u0041 = 'A'
JSON_ESC_KEY = "sk-" + _JSON_ESC_A + ("b" * 15)  # sk-\u0041bbbbbbbbbbbbbbb（A 被转义）
# 大小写变体：SK-（首字母大写）——A 正则为小写 sk-，应不区分大小写遮蔽。
SK_UPPER_KEY = "SK-" + ("c" * 16)
# base64 形态：短 base64（<24，A 长串正则阈值外）但属已存 key → known_keys 遮蔽。
B64_KEY = "d" * 20  # 20 位 <24，A 长串正则不命中；仅 known_keys 能遮蔽


def test_json_escaped_key_is_redacted():
    """C：JSON 字符串里的 key 若被 unicode 转义（\\uXXXX）破坏连续串 → 仍应遮蔽整个 key。

    当前 A 正则 `sk-[A-Za-z0-9_-]{12,}` 要求 sk- 后紧跟 >=12 位连续字符，
    `sk-\\u0041bbb...` 中 `\\u` 打断连续匹配 → 当前实现泄漏（RED）。
    修复方向：先做 `\\uXXXX` unescape 归一化再匹配（安全：不破坏普通文本）。
    """
    result = redact_secrets(JSON_ESC_KEY, [])
    assert JSON_ESC_KEY not in result
    assert "sk-****" in result


def test_uppercase_sk_variant_is_redacted():
    """C：SK-（首字母大写）形态，不应因 A 正则为小写 sk- 而泄漏。

    短 key（<24，A 长串正则阈值外）当前仅小写 sk- 能命中 → 大写泄漏（RED）。
    修复方向：`[Ss][Kk]-` 不区分大小写匹配。
    """
    result = redact_secrets("Authorization: " + SK_UPPER_KEY, [])
    assert SK_UPPER_KEY not in result
    assert "****" in result


def test_base64_short_key_redacted_via_known_keys():
    """C：短 base64 key（<24，A 长串正则阈值外）被 known_keys 遮蔽（B 兜底）。

    契约：known_keys 内 key 无论长度/形态都整串替换。
    """
    result = redact_secrets("token=" + B64_KEY, [B64_KEY])
    assert B64_KEY not in result
    assert "****" in result


def test_known_keys_with_decrypt_fail_still_redacts_by_regex():
    """C：load_known_keys 解密失败降级（ret_prompt 走 A 正则兜底）后仍不泄 key。

    镜像 load_known_keys 跳过解密失败项 + redact_secrets(known_keys) 的 A 正则兜底：
    即使 known_keys 为空（全失败），裸 sk- key 仍被遮蔽。
    """
    result = redact_secrets(SK_KEY, [])
    assert SK_KEY not in result
    assert "sk-****" in result


def test_known_key_escaped_form_is_redacted():
    """D：已存 key 以全 `\\uXXXX` 转义形态出现在 prompt → unescape 后 known_keys 整串替换。

    评审发现（#875 只读评审）的残余缺口：known_keys replace 若先于 unescape，则
    转义形态的 key 无法被 known_keys 命中（长串正则阈值外也漏）→ 泄漏。
    修复方向：unescape 先于 known_keys（#632 的「known_keys 先于长串正则」仍保持）。
    """
    key = ("n" * 18)  # 18 位 <24（长串正则阈值外），非 sk-/Bearer 形态，仅 known_keys 能遮蔽
    escaped = "".join("\\u" + format(ord(c), "04x") for c in key)  # 全转义形态
    prompt = "token=" + escaped
    result = redact_secrets(prompt, [key])
    assert key not in result
    assert "****" in result
