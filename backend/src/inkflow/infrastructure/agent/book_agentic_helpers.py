"""book-agentic 编排辅助（#1186 从 book_agentic_pipeline 下沉的纯函数工具箱）.

与编排图（nodes/pipeline）解耦的纯函数 + state 工具：决策/审校 JSON 解析、
章查找、正文提取、plan 序列化往返、usage/落盘 dict 构造。

下沉动机：``book_agentic_pipeline.py`` 触达 900 行护栏（#1186 新增书任务上下文
后 942 行）。纯函数无编排耦合，独立成模块后主文件回到护栏内——与 #1185
「三轨副本收敛到 domain 单一实现」同族的**体积治理**，行为零变化。
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any, cast

from inkflow.domain.models.writing_plan import WritingPlan

if TYPE_CHECKING:  # 注解经 `from __future__ import annotations` 延迟求值，运行期无需真类型
    from inkflow.infrastructure.agent.book_agentic_pipeline import BookAgenticState


def _try_json(content: str) -> dict | None:
    """宽松 JSON 解析：仅接受 dict；其余（含列表/标量）返回 None."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _parse_decision(content: str) -> tuple[str, str, str] | None:
    """解析 LLM 决策 JSON → (action, op, outline_id)；空 content/解析失败返回 None.

    宽松解析（镜像 F29 _parse_decision）：LLM 可能返回 markdown 代码块围栏包裹的
    JSON，先试完整解析，失败则提取首个 { 到末个 } 子串。
    """
    if not content.strip():
        return None
    data = _try_json(content)
    if data is None:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and start < end:
            data = _try_json(content[start : end + 1])
    if data is None:
        return None
    action = data.get("action")
    if action == "goto":
        op = data.get("op")
        oid = data.get("outline_id")
        if isinstance(op, str) and op and isinstance(oid, str) and oid:
            return ("goto", op, oid)
        return None
    if action in ("finish", "fallback"):
        return (action, "", "")
    return None


def _parse_audit(content: str) -> dict:
    """解析审校 LLM 输出 → {score, issues}；解析失败返回零分空问题（不阻塞编排）."""
    data = _try_json(content)
    if data is None:
        return {"score": 0, "issues": []}
    issues = data.get("issues", [])
    return {
        "score": int(data.get("score", 0)),
        "issues": [str(i) for i in issues] if isinstance(issues, list) else [],
    }


def _find_chapter(chapters: list[dict], outline_id: str) -> dict | None:
    """按 outline_id（uuid 或 str）查章 dict；无 → None."""
    for ch in chapters:
        if str(ch.get("outline_id", "")) == str(outline_id):
            return ch
    return None


def _extract_final_content(result: dict[str, Any]) -> str:
    """从 agent.invoke 结果（dict，含 "messages"）提取最终 message content（镜像 F44）."""
    messages = result.get("messages", [])
    if not messages:
        return ""
    final = messages[-1]
    content = getattr(final, "content", None)
    if content is None and isinstance(final, dict):
        content = final.get("content")
    if content is None:
        return ""
    return str(content)


def _plan_to_dict(plan: object) -> dict:
    """WritingPlan → JSON dict；鸭子对象（SimpleNamespace）→ vars 快照（UUID 转 str）."""
    if hasattr(plan, "model_dump"):
        return cast(dict, plan.model_dump(mode="json"))  # 鸭子类型：WritingPlan 提供 model_dump
    data = dict(vars(plan))
    return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in data.items()}


def _restore_plan(data: dict) -> WritingPlan:
    """从 checkpoint 状态还原 WritingPlan（过滤未知键，兼容鸭子对象快照）."""
    fields = WritingPlan.model_fields
    return WritingPlan(**{k: v for k, v in data.items() if k in fields})


def _chapter_failed(state: BookAgenticState, op: str, oid: str) -> dict[str, object]:
    """章操作失败落盘（#1186 收敛 write/revise 重复的 failed 分支）."""
    return {
        **_counter_update(state, op),
        "results": {oid: "failed"},
        "progress": {oid: "failed"},
    }


def _chapter_written(
    state: BookAgenticState, op: str, oid: str, execution_id: str, event: dict | None
) -> dict[str, object]:
    """章写作成功落盘（#1186 收敛 write/revise 重复的成功分支）."""
    return {
        **_counter_update(state, op),
        "chapter_ops": _bump_chapter_ops(state, oid),
        "results": {oid: execution_id},
        "progress": {oid: "in_progress"},
        "usage": [event] if event is not None else [],
    }


def _usage_event(
    source: str, chapter: str, prompt_tokens: int, completion_tokens: int, total_tokens: int
) -> dict:
    """usage 事件 dict（#1186 收敛 write/revise 两处逐字重复的构造）."""
    return {
        "source": source,
        "chapter": chapter,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _counter_update(state: BookAgenticState, op: str) -> dict[str, object]:
    """操作节点计数（镜像 F29 _role_node）：steps/consecutive/last_op."""
    consecutive = state.get("consecutive", 0)
    if state.get("last_op", "") == op:
        consecutive += 1
    else:
        consecutive = 1
    return {
        "steps": state.get("steps", 0) + 1,
        "consecutive": consecutive,
        "last_op": op,
    }


def _bump_chapter_ops(state: BookAgenticState, outline_id: str) -> dict[str, int]:
    """各章 write/audit/revise 累计次数 +1（章节循环护栏数据源）."""
    ops = dict(state.get("chapter_ops", {}))
    ops[outline_id] = ops.get(outline_id, 0) + 1
    return ops


def _first_unaudited_written(state: BookAgenticState) -> str | None:
    """返回已写未审的章 outline_id（progress=in_progress 且无 audit_results）；无 → None."""
    progress = state.get("progress", {})
    audit_results = state.get("audit_results", {})
    for oid in progress:
        if progress[oid] == "in_progress" and oid not in audit_results:
            return oid
    return None
