"""F58 #957 §4.2 守护：messages zh.json / en.json 的 agent.scope.domain.* 域名词条。

json 直读（无 FastAPI、无 resolver），覆盖两条契约：
1. zh.json 与 en.json 均含 8 个 ``agent.scope.domain.*`` 键；
2. 两文件对该内容键集完全一致（对称，防 en 漏键静默回退中文）；
3. 值逐字对齐 contract-957 §4.1（zh/en，码点级）。

RED 预期：当前 messages 未登记 agent.scope.domain.*（GREEN 补 8 键后转绿）。
"""
import json
from pathlib import Path

MESSAGES_DIR = Path(__file__).resolve().parents[3] / "src" / "inkflow" / "i18n" / "messages"

DOMAIN_KEYS = [
    "agent.scope.domain.outline",
    "agent.scope.domain.character",
    "agent.scope.domain.world",
    "agent.scope.domain.timeline",
    "agent.scope.domain.foreshadowing",
    "agent.scope.domain.memory",
    "agent.scope.domain.writing",
    "agent.scope.domain.agent_chain",
]

EXPECTED_ZH = {
    "agent.scope.domain.outline": "大纲",
    "agent.scope.domain.character": "角色",
    "agent.scope.domain.world": "世界观",
    "agent.scope.domain.timeline": "时间线",
    "agent.scope.domain.foreshadowing": "伏笔",
    "agent.scope.domain.memory": "记忆",
    "agent.scope.domain.writing": "写作",
    "agent.scope.domain.agent_chain": "Agent 链",
}

EXPECTED_EN = {
    "agent.scope.domain.outline": "Outline",
    "agent.scope.domain.character": "Characters",
    "agent.scope.domain.world": "World Building",
    "agent.scope.domain.timeline": "Timeline",
    "agent.scope.domain.foreshadowing": "Foreshadowing",
    "agent.scope.domain.memory": "Memory",
    "agent.scope.domain.writing": "Writing",
    "agent.scope.domain.agent_chain": "Agent Chain",
}


def _load(lang: str) -> dict:
    path = MESSAGES_DIR / f"{lang}.json"
    assert path.exists(), f"缺少消息文件：{path}"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_zh_messages_have_all_scope_domain_keys():
    data = _load("zh")
    for k in DOMAIN_KEYS:
        assert k in data, f"zh.json 缺少 {k}"


def test_en_messages_have_all_scope_domain_keys():
    data = _load("en")
    for k in DOMAIN_KEYS:
        assert k in data, f"en.json 缺少 {k}"


def test_zh_en_scope_domain_key_sets_symmetric():
    zh = _load("zh")
    en = _load("en")
    zh_set = {k for k in DOMAIN_KEYS if k in zh}
    en_set = {k for k in DOMAIN_KEYS if k in en}
    assert zh_set == en_set, (
        f"zh/en 键集不对称：zh_only={zh_set - en_set} en_only={en_set - zh_set}"
    )
    assert zh_set == set(DOMAIN_KEYS), f"两侧应同时包含全部 {len(DOMAIN_KEYS)} 个域名词条"


def test_zh_scope_domain_values_match_contract():
    data = _load("zh")
    for k, v in EXPECTED_ZH.items():
        assert data.get(k) == v, f"zh.json {k} 值应为 {v!r}，实际 {data.get(k)!r}"


def test_en_scope_domain_values_match_contract():
    data = _load("en")
    for k, v in EXPECTED_EN.items():
        assert data.get(k) == v, f"en.json {k} 值应为 {v!r}，实际 {data.get(k)!r}"
