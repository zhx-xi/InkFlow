"""#1174/#1177 审计桥：book 编排 ↔ F34 章节审计服务之间的适配（无编排状态）.

- ``build_audit_messages``：构造审计提示词——user 消息携带本章**正文全文**，
  取代此前只喂 ``chapter["description"]``（大纲描述）的输入（#1174）。
- ``score_from_findings``：F34 findings → 0-100 质量分（error 扣 20 / warning
  扣 8 / info 扣 2，下限 0；无 findings → 100）。
- ``report_to_audit_dict``：``ChapterAuditReport`` → 契约扁平 dict（#1177：把 F34
  四项检查暴露为 ``character_drift`` / ``setting_drift`` / ``issues`` 字段，
  供编排与 revise 节点消费）。
- ``audit_event``：审计 usage 事件（#902 语义，F34 分支零值）。
- ``read_draft_body`` / ``read_draft_content`` / ``persist_chapter_body``：正文
  取得与落章适配（#1174 输入面）——全部异常吞掉，绝不让 IO 失败炸掉编排。

独立于 ``book_agentic_pipeline``（900 行硬上限，见 AGENTS.md §10.5）。本模块属
infrastructure 层：允许依赖 domain 模型/端口，反向依赖不成立（AGENTS.md §4.2）。
审计输入截断归 F34 ``truncate_chapter``，此处**不截断**。
"""

from __future__ import annotations

from collections.abc import Sequence

from loguru import logger

from inkflow.domain.models.chapter import ChapterUpdate
from inkflow.domain.models.chapter_audit import AuditCheckType
from inkflow.domain.ports.llm_client import ChatMessage
from inkflow.domain.services.usage_accounting import chat_response_usage

_SEVERITY_PENALTY: dict[str, int] = {"error": 20, "warning": 8, "info": 2}
"""严重级别扣分表（spec §6 三级）；未识别级别不扣分（防御）。"""


def build_audit_messages(chapter: dict, content: str) -> list[ChatMessage]:
    """构造审计提示词：user 消息含本章正文全文（#1174）。

    章名/大纲描述仅作上下文，正文单独成段、与大纲描述不混同；正文截断由 F34
    内部 ``truncate_chapter``（8000 字预算）负责，本函数原样嵌入。

    Args:
        chapter: 章 dict（name/description 等编排字段）.
        content: 本章正文（可为空串——空正文时仍须在场，供上游观测）.

    Returns:
        [system, user] 两条 ChatMessage（role/content 具备，供鸭子审计调用方消费）.
    """
    outline = str(chapter.get("description", "") or "")
    return [
        ChatMessage(
            role="system",
            content=(
                "你是小说章节质量审校员：依据章节正文与角色/世界观设定档案，检查人设"
                "漂移、设定漂移、字数达标与静态一致性，并输出 JSON 质量评估。"
            ),
        ),
        ChatMessage(
            role="user",
            content=(
                f"请审校章节《{chapter.get('name', '')}》（大纲描述：{outline}）。\n\n"
                f"【正文】\n{content}\n\n"
                '输出 JSON：{"score": <0-100 整数>, "issues": ["<问题1>", ...]}。'
            ),
        ),
    ]


def score_from_findings(findings: Sequence[object]) -> int:
    """F34 findings → 0-100 质量分：error 扣 20 / warning 扣 8 / info 扣 2，下限 0.

    Args:
        findings: F34 审计发现序列（``ChapterAuditFinding`` 或同形鸭子对象）.

    Returns:
        100 - Σ扣分（下限 0）；无 findings → 100.
    """
    score = 100
    for finding in findings:
        severity = getattr(finding, "severity", None)
        score -= _SEVERITY_PENALTY.get(str(getattr(severity, "value", severity)), 0)
    return max(score, 0)


def report_to_audit_dict(report: object) -> dict:
    """ChapterAuditReport → 审计结论 dict（#1177：把 F34 四项检查暴露为契约字段）.

    findings 在场（真实 F34 报告）→ 逐项派生 issues/漂移/score；无 findings
    （鸭子报告：测试桩/降级路径）→ 按报告平铺字段兜底，缺 score → 100（满分）。

    Args:
        report: ``ChapterAuditReport`` 或同形鸭子对象.

    Returns:
        ``score`` / ``issues`` / ``character_drift`` / ``setting_drift`` /
        ``degraded`` / ``chapter_id`` / ``findings``（原始 findings JSON dict 列表）.
    """
    findings: list[object] = list(getattr(report, "findings", None) or [])
    if findings:
        issues = [str(getattr(f, "message", "")) for f in findings]
        character_drift = _drift_messages(findings, AuditCheckType.CHARACTER_DRIFT)
        setting_drift = _drift_messages(findings, AuditCheckType.SETTING_DRIFT)
        score = score_from_findings(findings)
    else:
        issues = _as_str_list(getattr(report, "issues", None))
        character_drift = _as_str_list(getattr(report, "character_drift", None))
        setting_drift = _as_str_list(getattr(report, "setting_drift", None))
        score = _as_int(getattr(report, "score", None), 100)
    return {
        "score": score,
        "issues": issues,
        "character_drift": character_drift,
        "setting_drift": setting_drift,
        "degraded": bool(getattr(report, "degraded", False)),
        "chapter_id": str(getattr(report, "chapter_id", "") or ""),
        "findings": [_dump_finding(f) for f in findings],
    }


def audit_event(chapter: dict, response: object | None) -> dict:
    """审计 usage 事件（#902）：source="audit"、chapter=str(outline_id).

    response=None（F34 分支无 chat 响应）→ chat_response_usage 零三元组（防伪计费）。
    """
    prompt_tokens, completion_tokens, total_tokens = chat_response_usage(response)
    return {
        "source": "audit",
        "chapter": str(chapter["outline_id"]),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


async def read_draft_body(draft_service: object | None, project_id: object, chapter: dict) -> str:
    """按 source_outline_id 回读该章最新草稿正文；未装配/未命中/异常 → ""（不抛）."""
    if draft_service is None:
        return ""
    try:
        draft = await draft_service.find_pending(  # type: ignore[attr-defined]  # 鸭子类型：draft_service 按 F27 契约提供 async find_pending
            project_id, source_outline_id=chapter.get("outline_id")
        )
    except Exception:
        return ""
    return str(getattr(draft, "content", "") or "") if draft is not None else ""


async def read_draft_content(draft_service: object | None, draft_id: str) -> str:
    """按草稿 id（= execution_id）取正文；未装配/未命中/异常 → ""（不抛）."""
    if draft_service is None or not draft_id:
        return ""
    try:
        draft = await draft_service.get(draft_id)  # type: ignore[attr-defined]  # 鸭子类型：draft_service 按 F27 契约提供 async get(draft_id)
    except Exception:
        return ""
    return str(getattr(draft, "content", "") or "") if draft is not None else ""


async def persist_chapter_body(
    chapter_service: object | None, chapter_id: object, text: str
) -> bool:
    """把正文写入 F2 章实体（F34 的审计输入面）；True = 可继续走 F34.

    未装配 chapter_service → 跳过落章（返回 True，F34 读章仓储现值）；章不存在 /
    uuid4 int 溢出 / 写入异常 → False（不抛）——不发 F34，回落注入点分支，
    避免 ChapterNotFoundError 炸掉编排（#1174）。
    """
    if chapter_service is None:
        return True
    try:
        updated = await chapter_service.update_chapter(  # type: ignore[attr-defined]  # 鸭子类型：chapter_service 按 F2 契约提供 async update_chapter
            chapter_id, ChapterUpdate(content=text)
        )
    except Exception:
        logger.warning("审计正文落章失败，回落注入点分支：chapter_id={}", chapter_id)
        return False
    return updated is not None


def _drift_messages(findings: Sequence[object], check_type: AuditCheckType) -> list[str]:
    """取指定检查项的 findings message（有档案条目名 → 前缀，展示可读）."""
    messages: list[str] = []
    for finding in findings:
        value = getattr(finding, "check_type", None)
        if str(getattr(value, "value", value)) != check_type.value:
            continue
        name = str(getattr(finding, "ref_entity_name", "") or "")
        message = str(getattr(finding, "message", ""))
        messages.append(f"{name}：{message}" if name else message)
    return messages


def _dump_finding(finding: object) -> object:
    """findings 单项 → JSON dict（Pydantic ``model_dump``；非模型对象退化为 message）."""
    dump = getattr(finding, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    return {"message": str(getattr(finding, "message", finding))}


def _as_str_list(value: object) -> list[str]:
    """任意值 → list[str]（list/tuple 逐项 str；其余 → []）."""
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return []


def _as_int(value: object, default: int) -> int:
    """数值 → int；None / bool / 非数值 → default."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return int(value)
