"""结构化日志 JSON 行存储 — 按天文件隔离，支持过滤 / 降序 / 分页查询。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from inkflow.logging.schema import StructuredLogRecord


def _normalize_ts(value: datetime) -> datetime:
    """naive datetime 按 UTC 处理，aware datetime 原样返回。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _parse_ts(value: object) -> datetime | None:
    """解析 JSON-safe ISO 时间串为 aware datetime；非法输入返回 None。"""
    if not isinstance(value, str):
        return None
    text = value.replace("Z", "+00:00")
    try:
        return _normalize_ts(datetime.fromisoformat(text))
    except ValueError:
        return None


def _record_matches_q(rec: dict, q: str) -> bool:
    """关键字过滤：整条记录 JSON（含 event / caller_name / params）大小写不敏感匹配。"""
    return q.lower() in json.dumps(rec, ensure_ascii=False).lower()


def _csv_match(actual: object, expected: str) -> bool:
    """actual（str）大写后 ∈ expected 按逗号拆分（strip 各段）的大写集合 → True。

    B2 #496 多值过滤：单值（无逗号）向后兼容等值比较；非 str actual 恒 False。
    """
    if not isinstance(actual, str):
        return False
    return actual.upper() in {part.strip().upper() for part in expected.split(",")}


class StructuredLogStore:
    """结构化日志 JSON 行存储：POST /logs 写、GET /logs 读（按 data_dir/logs/structured 隔离）。"""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def append(self, record: StructuredLogRecord) -> None:
        """写一行 JSON 到 {directory}/inkflow_structured_{date}.log（date=record 日期）。"""
        self.directory.mkdir(parents=True, exist_ok=True)
        date = record.timestamp.date().isoformat()
        path = self.directory / f"inkflow_structured_{date}.log"
        line = json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    def query(
        self,
        *,
        level: str | None = None,
        caller_type: str | None = None,
        project_id: int | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        q: str | None = None,
        correlation_id: str | None = None,
        trace_id: str | None = None,
        page: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict], int]:
        """读全部 inkflow_structured_*.log 行，过滤后按 timestamp 降序 + 分页。

        level / caller_type 支持逗号分隔多值（大小写不敏感，单值向后兼容）；解析失败的行跳过；
        correlation_id / trace_id 等值过滤（#932：trace_id 镜像 correlation_id 口径）；
        返回 (items, total)，items 为 JSON-safe record dict（含脱敏后 params）。
        """
        from_norm = _normalize_ts(from_ts) if from_ts is not None else None
        to_norm = _normalize_ts(to_ts) if to_ts is not None else None
        rows: list[tuple[datetime, dict]] = []
        for path in sorted(self.directory.glob("inkflow_structured_*.log")):
            for raw in path.read_text(encoding="utf-8").splitlines():
                if not raw.strip():
                    continue
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(parsed, dict):
                    continue
                ts = _parse_ts(parsed.get("timestamp"))
                if ts is None:
                    ts = datetime.min.replace(tzinfo=UTC)
                rows.append((ts, parsed))

        matched: list[tuple[datetime, dict]] = []
        for ts, rec in rows:
            if level is not None and not _csv_match(rec.get("level"), level):
                continue
            if caller_type is not None and not _csv_match(rec.get("caller_type"), caller_type):
                continue
            if project_id is not None and rec.get("project_id") != project_id:
                continue
            if correlation_id is not None and rec.get("correlation_id") != correlation_id:
                continue
            if trace_id is not None and rec.get("trace_id") != trace_id:
                continue
            if from_norm is not None and ts < from_norm:
                continue
            if to_norm is not None and ts > to_norm:
                continue
            if q is not None and not _record_matches_q(rec, q):
                continue
            matched.append((ts, rec))

        matched.sort(key=lambda item: item[0], reverse=True)
        total = len(matched)
        offset = page * limit
        items = [rec for _, rec in matched[offset : offset + limit]]
        return items, total
