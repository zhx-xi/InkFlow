"""F34 章节审计 LLM 提示词组装与输出解析纯函数单元测试（spec §5.2/§5.3）.

被测模块: domain/services/_audit_prompts.py（CREATE；RED 阶段不存在 →
顶部 import 抛 ModuleNotFoundError = 预期收集期失败，pytest 退出码 2）。

覆盖:
- build_character_drift_messages: 人设漂移提示词（system + user 两条消息，
  含角色档案名与章节文本片段；truncated=True 时 user 消息含「已截断」字样）
- build_setting_drift_messages: 设定漂移提示词（同构，含世界观条目 name/
  content 与章节文本片段）
- parse_drift_output: LLM 输出 JSON 解析 → list[ChapterAuditFinding]；
  非法 severity / check_type / 缺 message / JSON 语法错 / 非对象顶层 →
  None（不抛异常）；容忍 ```json 代码块围栏与前后缀文字（提取首个 {...}
  平衡片段，F16 _world_extractor._extract_json_fragment 同款逻辑——
  花括号扫描跳过字符串字面量）

设计假设（GREEN 实现契约，依据 specs/f34-chapter-audit/spec.md §5.2/§5.3）:
1. 模块路径: inkflow.domain.services._audit_prompts
2. build_character_drift_messages(chapter_text: str,
   characters: list[Character], truncated: bool) -> list[ChatMessage]:
   返回恰好 2 条消息（[0] role="system" 指令、[1] role="user" 携带章节文本
   + 角色档案）；user 消息须包含角色名（name 子串）与章节文本片段
   （chapter_text 前缀）；truncated=True 时 user 消息含「已截断」字样
3. build_setting_drift_messages(chapter_text: str,
   settings: list[WorldSetting], truncated: bool) -> list[ChatMessage]:
   同构（user 消息含条目 name 与 content 片段）
4. parse_drift_output(raw: str) -> list[ChapterAuditFinding] | None:
   - 合法输入: 顶层 JSON 对象含 "findings" 列表，元素为对象，键
     check_type（AuditCheckType 值）/ severity（AuditSeverity 值）/
     message（必填）/ suggestion? / ref_entity_id?（UUID 字符串）/
     ref_entity_name? / context?（缺省即模型默认值）
   - 任一元素校验失败（非法枚举值 / 缺 message / 非对象）→ 整体 None
   - "findings" 缺失或非列表 / 顶层非对象 / JSON 语法错误 / 空串 → None
   - 围栏与前后缀: ```json 代码块、前缀说明文字、后缀文字均容忍——
     提取首个平衡 {...} 片段后解析（字符串字面量内的花括号不破坏平衡）
   - 重试语义由 service 层做（spec §5.2 重试 1 次），本文件不测重试
5. 输出映射: check_type/severity 映射为 chapter_audit 模块枚举
   （AuditCheckType/AuditSeverity）；ref_entity_id 字符串解析为 uuid.UUID
6. RED 预期: 收集期 1 error（ModuleNotFoundError: No module named
   'inkflow.domain.models.chapter_audit'——import 字母序使其先于
   _audit_prompts 失败；GREEN 后两模块落地即自动收集），无其他失败

补测覆盖（覆盖率 miss 归因，2026-08）:
- parse_drift_output 非字符串字段（数字）→ 整批 None: check_type（L189）/
  severity（L199）/ suggestion（L211）/ ref_entity_name（L258）/
  context（L261）/ ref_entity_id（L266）；ref_entity_id 非法 UUID 字符串
  → None（L270）；平衡花括号但 JSON 语法错 → 兜底 except（L282/284）
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from inkflow.domain.models.chapter_audit import (
    AuditCheckType,
    AuditSeverity,
    ChapterAuditFinding,
)
from inkflow.domain.models.character import Character
from inkflow.domain.models.world import WorldSetting
from inkflow.domain.ports.llm_client import ChatMessage
from inkflow.domain.services._audit_prompts import (
    build_character_drift_messages,
    build_setting_drift_messages,
    parse_drift_output,
)

PID = uuid.UUID("3f2e1d4a-0000-4000-8000-000000000001")
EID = uuid.UUID("9b1c2d3e-0000-4000-8000-000000000001")
TS = datetime(2026, 8, 1, 10, 0, 0)


def _char(name: str, personality: str = "温厚沉稳") -> Character:
    """构造测试角色实体（F9 领域模型，已存在）。"""
    return Character(
        id=uuid.UUID(int=1),
        project_id=PID,
        name=name,
        personality=personality,
        background="青焰门弟子",
        goals="守护宗门",
        created_at=TS,
        updated_at=TS,
    )


def _setting(name: str, content: str) -> WorldSetting:
    """构造测试世界观条目实体（F10 领域模型，已存在）。"""
    return WorldSetting(
        id=uuid.UUID(int=2),
        project_id=PID,
        name=name,
        content=content,
        created_at=TS,
        updated_at=TS,
    )


def _findings_payload(**overrides: Any) -> dict:
    """构造合法 parse_drift_output 输入负载（§5.2 输出 JSON 形态）。"""
    base = {
        "findings": [
            {
                "check_type": "character_drift",
                "severity": "error",
                "message": "本章「李青焰」怒斥同伴，但角色档案性格为「温厚沉稳」",
                "suggestion": "可改为隐忍不发，或先铺垫情绪积累",
                "ref_entity_id": str(EID),
                "ref_entity_name": "李青焰",
                "context": "“够了！”李青焰猛地拍案而起，怒视众人……",
            },
            {
                "check_type": "word_count",
                "severity": "info",
                "message": "本章 2,845 字，低于目标 3,000 字",
            },
        ]
    }
    base.update(overrides)
    return base


class TestBuildCharacterDriftMessages:
    """build_character_drift_messages（§5.2 人设漂移提示词组装）。"""

    def test_returns_system_and_user_messages(self):
        chapter = "李青焰缓缓抬头。" * 3
        msgs = build_character_drift_messages(chapter, [_char("李青焰")], False)
        assert len(msgs) == 2
        assert isinstance(msgs[0], ChatMessage)
        assert msgs[0].role == "system"
        assert msgs[1].role == "user"

    def test_contains_character_name_and_chapter_snippet(self):
        chapter = "李青焰缓缓抬头，望向远方。" * 3
        msgs = build_character_drift_messages(chapter, [_char("李青焰")], False)
        user_content = msgs[1].content
        assert "李青焰" in user_content
        assert chapter[:20] in user_content

    def test_truncated_flag_marks_user_message(self):
        chapter = "李青焰缓缓抬头。" * 3
        msgs = build_character_drift_messages(chapter, [_char("李青焰")], True)
        assert "已截断" in msgs[1].content

    def test_not_truncated_has_no_marker(self):
        chapter = "李青焰缓缓抬头。" * 3
        msgs = build_character_drift_messages(chapter, [_char("李青焰")], False)
        assert "已截断" not in msgs[1].content

    def test_empty_characters_still_builds_messages(self):
        """档案为空时纯函数仍返回 system+user（跳过语义由 service 层做，§5.3）。"""
        chapter = "李青焰缓缓抬头。" * 3
        msgs = build_character_drift_messages(chapter, [], False)
        assert len(msgs) == 2
        assert chapter[:20] in msgs[1].content


class TestBuildSettingDriftMessages:
    """build_setting_drift_messages（§5.2 设定漂移提示词组装，同构）。"""

    def test_returns_system_and_user_messages(self):
        chapter = "灵气充沛的洞天福地。" * 3
        msgs = build_setting_drift_messages(
            chapter, [_setting("灵气枯竭", "天地灵气已枯竭百年")], False
        )
        assert len(msgs) == 2
        assert msgs[0].role == "system"
        assert msgs[1].role == "user"

    def test_contains_entry_name_content_and_chapter_snippet(self):
        chapter = "灵气充沛的洞天福地。" * 3
        msgs = build_setting_drift_messages(
            chapter, [_setting("灵气枯竭", "天地灵气已枯竭百年")], False
        )
        user_content = msgs[1].content
        assert "灵气枯竭" in user_content
        assert "天地灵气已枯竭百年" in user_content
        assert chapter[:20] in user_content

    def test_truncated_flag_marks_user_message(self):
        chapter = "灵气充沛的洞天福地。" * 3
        msgs = build_setting_drift_messages(
            chapter, [_setting("灵气枯竭", "天地灵气已枯竭百年")], True
        )
        assert "已截断" in msgs[1].content


class TestParseDriftOutput:
    """parse_drift_output（§5.2/§5.3: JSON 解析与降级语义）。"""

    def test_valid_output_maps_to_findings(self):
        payload = _findings_payload()
        findings = parse_drift_output(json.dumps(payload))
        assert findings is not None
        assert len(findings) == 2
        f0 = findings[0]
        assert isinstance(f0, ChapterAuditFinding)
        assert isinstance(f0.check_type, AuditCheckType)
        assert isinstance(f0.severity, AuditSeverity)
        assert f0.check_type == "character_drift"
        assert f0.severity == "error"
        assert f0.message == payload["findings"][0]["message"]
        assert f0.suggestion == "可改为隐忍不发，或先铺垫情绪积累"
        assert f0.ref_entity_id == EID
        assert f0.ref_entity_name == "李青焰"
        assert f0.context == "“够了！”李青焰猛地拍案而起，怒视众人……"
        f1 = findings[1]
        assert f1.check_type == "word_count"
        assert f1.severity == "info"
        assert f1.suggestion == ""
        assert f1.ref_entity_id is None
        assert f1.ref_entity_name == ""
        assert f1.context == ""

    def test_minimal_finding_uses_defaults(self):
        payload = {
            "findings": [
                {
                    "check_type": "setting_drift",
                    "severity": "warning",
                    "message": "疑似与设定矛盾",
                }
            ]
        }
        findings = parse_drift_output(json.dumps(payload))
        assert findings is not None
        assert len(findings) == 1
        f = findings[0]
        assert f.check_type == "setting_drift"
        assert f.severity == "warning"
        assert f.suggestion == ""
        assert f.ref_entity_id is None
        assert f.ref_entity_name == ""
        assert f.context == ""

    def test_empty_findings_returns_empty_list(self):
        findings = parse_drift_output(json.dumps({"findings": []}))
        assert findings == []

    def test_invalid_severity_returns_none(self):
        payload = {
            "findings": [{"check_type": "character_drift", "severity": "critical", "message": "x"}]
        }
        assert parse_drift_output(json.dumps(payload)) is None

    def test_invalid_check_type_returns_none(self):
        payload = {
            "findings": [{"check_type": "typo_check", "severity": "warning", "message": "x"}]
        }
        assert parse_drift_output(json.dumps(payload)) is None

    def test_missing_message_returns_none(self):
        payload = {"findings": [{"check_type": "character_drift", "severity": "warning"}]}
        assert parse_drift_output(json.dumps(payload)) is None

    def test_missing_findings_key_returns_none(self):
        assert parse_drift_output(json.dumps({"other": 1})) is None

    def test_findings_not_a_list_returns_none(self):
        assert parse_drift_output(json.dumps({"findings": "x"})) is None

    def test_finding_not_an_object_returns_none(self):
        assert parse_drift_output(json.dumps({"findings": [42]})) is None

    def test_top_level_list_returns_none(self):
        assert parse_drift_output(json.dumps([1, 2])) is None

    def test_top_level_string_returns_none(self):
        assert parse_drift_output(json.dumps("hello")) is None

    def test_malformed_json_returns_none(self):
        assert parse_drift_output('{"findings": [{"check_type": "character_drift"') is None

    def test_empty_raw_returns_none(self):
        assert parse_drift_output("") is None

    def test_json_fence_and_surrounding_text_tolerated(self):
        raw = (
            "好的，以下是分析结果：\n"
            "```json\n" + json.dumps(_findings_payload()) + "\n```\n"
            "希望对你有帮助"
        )
        findings = parse_drift_output(raw)
        assert findings is not None
        assert len(findings) == 2

    def test_prefix_text_without_fence_tolerated(self):
        raw = "分析结果如下：" + json.dumps(_findings_payload()) + " 完"
        findings = parse_drift_output(raw)
        assert findings is not None
        assert len(findings) == 2

    def test_braces_inside_string_literal_do_not_break_extraction(self):
        """平衡片段提取须跳过字符串字面量（F16 _extract_json_fragment 同款）。"""
        message = "角色说：结果 { 未知 } 且与 [设定] 无关"
        payload = {
            "findings": [
                {"check_type": "character_drift", "severity": "warning", "message": message}
            ]
        }
        raw = "```json\n" + json.dumps(payload) + "\n```"
        findings = parse_drift_output(raw)
        assert findings is not None
        assert findings[0].message == message

    # ── 补测: 覆盖率 miss 分支（非字符串字段 / 非法 UUID / 兜底 except）──

    def test_non_string_check_type_returns_none(self):
        """check_type 非字符串（数字）→ 整批 None（L189）。"""
        payload = {"findings": [{"check_type": 42, "severity": "warning", "message": "x"}]}
        assert parse_drift_output(json.dumps(payload)) is None

    def test_non_string_severity_returns_none(self):
        """severity 非字符串（数字）→ 整批 None（L199）。"""
        payload = {"findings": [{"check_type": "character_drift", "severity": 3, "message": "x"}]}
        assert parse_drift_output(json.dumps(payload)) is None

    def test_non_string_suggestion_returns_none(self):
        """suggestion 非字符串（数字）→ 整批 None（L211）。"""
        payload = {
            "findings": [
                {
                    "check_type": "character_drift",
                    "severity": "warning",
                    "message": "x",
                    "suggestion": 123,
                }
            ]
        }
        assert parse_drift_output(json.dumps(payload)) is None

    def test_non_string_ref_entity_name_returns_none(self):
        """ref_entity_name 非字符串（数字）→ 整批 None（L258）。"""
        payload = {
            "findings": [
                {
                    "check_type": "character_drift",
                    "severity": "warning",
                    "message": "x",
                    "ref_entity_name": 42,
                }
            ]
        }
        assert parse_drift_output(json.dumps(payload)) is None

    def test_non_string_context_returns_none(self):
        """context 非字符串（数字）→ 整批 None（L261）。"""
        payload = {
            "findings": [
                {
                    "check_type": "character_drift",
                    "severity": "warning",
                    "message": "x",
                    "context": 42,
                }
            ]
        }
        assert parse_drift_output(json.dumps(payload)) is None

    def test_non_string_ref_entity_id_returns_none(self):
        """ref_entity_id 非字符串（数字）→ 整批 None（L266）。"""
        payload = {
            "findings": [
                {
                    "check_type": "character_drift",
                    "severity": "warning",
                    "message": "x",
                    "ref_entity_id": 42,
                }
            ]
        }
        assert parse_drift_output(json.dumps(payload)) is None

    def test_invalid_uuid_ref_entity_id_returns_none(self):
        """ref_entity_id 非法 UUID 字符串 → 整批 None（L270）。"""
        payload = {
            "findings": [
                {
                    "check_type": "character_drift",
                    "severity": "warning",
                    "message": "x",
                    "ref_entity_id": "not-a-uuid",
                }
            ]
        }
        assert parse_drift_output(json.dumps(payload)) is None

    def test_balanced_braces_but_malformed_json_returns_none(self):
        """有平衡花括号但 JSON 语法错（'{"a": }'）→ 兜底 except 返回 None（L282/284）。"""
        assert parse_drift_output('{"a": }') is None
