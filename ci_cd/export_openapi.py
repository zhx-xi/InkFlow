"""导出 OpenAPI 快照（S3c 契约门禁 C1/M1，Issue #869）。

把 app.openapi() 落盘到 ci_cd/openapi_snapshot.json。

用法（cwd=backend，uv 环境内）:
    uv run python ../ci_cd/export_openapi.py

- 序列化形态与 backend/tests/unit/test_openapi_contract.py::_serialize 逐字节一致：
  json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
- 后端 OpenAPI schema 是唯一真相；后端契约变更后必须重跑本脚本并提交快照 diff，
  否则 unit-backend 的 M1 漂移测试与 lint-frontend 的类型漂移门禁（#869 S3c）会红。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_PATH = REPO_ROOT / "ci_cd" / "openapi_snapshot.json"


def _serialize(schema: dict[str, object]) -> str:
    """快照唯一序列化形态：indent=2 + sort_keys + 尾换行（与测试 _serialize 逐字节一致）。"""
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write_snapshot() -> None:
    # 函数级导入：兼容未 editable 安装的裸解释器（先注入 backend/src 再 import inkflow）
    sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))
    from inkflow.api.app import app

    schema = app.openapi()
    # newline="\n"：禁止 Windows 文本模式把 \n 转成 \r\n，保证与 _serialize 输出逐字节一致
    SNAPSHOT_PATH.write_text(_serialize(schema), encoding="utf-8", newline="\n")


def main() -> int:
    _write_snapshot()
    print(f"已导出 OpenAPI 快照：{SNAPSHOT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
