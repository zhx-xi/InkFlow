# -*- coding utf-8 -*-
"""S3c 契约一致性门禁（C1）：OpenAPI 快照版本化测试（ADR-027 契约小节）。

契约方向：后端 OpenAPI schema 是唯一真相。前端 DTO/调用面（api/*.ts）必须与之对拍
（对拍逻辑在 renderer vitest src/api/__contract__/contract.test.ts）。
本文件守 M1：仓库快照 `ci_cd/openapi_snapshot.json` 存在且与当前 app.openapi() 一致——
后端契约变更但快照未重导 → 红（schema diff 进 PR，契约漂移在 CI 可见）。

TDD RED（2026-09-02）：快照文件尚不存在 → 两用例 FAIL；GREEN 由
ci_cd/export_openapi.py 导出快照后转绿。
"""

from __future__ import annotations

import json
from pathlib import Path

from inkflow.api.app import app

REPO_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT_PATH = REPO_ROOT / "ci_cd" / "openapi_snapshot.json"


def _serialize(schema: dict) -> str:
    """快照唯一序列化形态：indent=2 + sort_keys + 尾换行（确定性，diff 友好）。"""
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def test_openapi_snapshot_file_exists():
    """M1：仓库内必须有版本化 OpenAPI 快照（契约对拍的基准文件）。"""
    assert SNAPSHOT_PATH.is_file(), (
        "ci_cd/openapi_snapshot.json 不存在：先运行 "
        "`python ci_cd/export_openapi.py` 从后端 app.openapi() 导出快照"
    )


def test_openapi_snapshot_matches_current_schema():
    """M1：快照内容必须与当前 app.openapi() 逐字节一致（漂移 = 契约变更未重导快照）。"""
    if not SNAPSHOT_PATH.is_file():
        raise AssertionError("快照缺失（见 test_openapi_snapshot_file_exists）")
    current = _serialize(app.openapi())
    committed = SNAPSHOT_PATH.read_text(encoding="utf-8")
    assert committed == current, (
        "OpenAPI 快照漂移：后端 schema 已变更但 ci_cd/openapi_snapshot.json 未更新。"
        "请运行 `python ci_cd/export_openapi.py` 重新导出并提交 diff。"
    )
