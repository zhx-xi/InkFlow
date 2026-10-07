"""book-agentic supervisor 任务清单工具箱（#1439）.

纯函数工具箱（镜像 book_agentic_helpers 体积治理先例）：清单条目构造 / 目标章名
解析 / plan.tasklist 播种与回写 / 决策消息「上次清单」段渲染。

清单是 supervisor 的**计划 / 决策记录**（读回供下次决策参考），
**绝不写 progress**——实际执行态仍以 progress 为唯一权威源（单字段单一 writer，
构造上零双写漂移）。

依据: specs/f44-book-orchestrator/spec.md §5.9 + §2.1 + issue #1439。
"""

from __future__ import annotations

DEGRADED_OP: str = "__degraded__"


def make_task_entry(op: str, outline_id: str, title: str) -> dict:
    """构造一条清单条目 {op, outline_id, title}."""
    return {"op": op, "outline_id": outline_id, "title": title}


def degraded_entry(reason: str) -> dict:
    """构造一条降级条目 {op: DEGRADED_OP, reason}（决策重试耗尽的留痕）."""
    return {"op": DEGRADED_OP, "reason": reason}


def task_title(chapters: list[dict], outline_id: str) -> str:
    """按 outline_id（uuid 或 str）取目标章名；章缺失 / 章名缺失或为空 → outline_id."""
    for ch in chapters:
        if str(ch.get("outline_id", "")) == str(outline_id):
            name = str(ch.get("name", "") or "")
            return name or str(outline_id)
    return str(outline_id)


def seed_tasklist(plan: object) -> list[dict]:
    """从 plan.tasklist 播种清单（共享引用）；plan 无该属性 / 值为空 → []（鸭子守卫）."""
    return list(getattr(plan, "tasklist", None) or [])


def persist_tasklist(plan: object, tasklist: object) -> None:
    """把清单回写 plan.tasklist（共享引用）；非 list 或 plan 无该属性 → no-op（不抛错）."""
    if isinstance(tasklist, list) and hasattr(plan, "tasklist"):
        plan.tasklist = list(tasklist)


def decision_prompt_section(tasklist: list[dict]) -> str:
    """渲染决策消息的「上次清单」提示段（上下文，非约束）；空清单 → ""."""
    if not tasklist:
        return ""
    parts = [
        DEGRADED_OP
        if str(entry.get("op", "")) == DEGRADED_OP
        else f"{entry.get('op', '')}({entry.get('outline_id', '')})"
        for entry in tasklist
    ]
    return f"\n上次清单：{' -> '.join(parts)}\n"
