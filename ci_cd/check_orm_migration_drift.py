"""ORM↔迁移接线静态漂移门禁（#1006 backend-contract-drift）.

背景
────
前端有 ``gen:api``（openapi.d.ts 漂移即红），后端此前无等价物：给 ORM 加一个
NOT NULL / 无 SQL DEFAULT 的新列却忘写 ``ensure_*`` 补列迁移 → 新库 create_all
正常，**旧库升级后缺列**，运行时才崩（#869 类 3 的根因面之一）。

门禁语义（baseline 差分，只锁「新增列」）
────────────────────────────────────────
1. 运行时反射当前 ORM 列集（import models → Base.metadata，真值源，禁 substring）。
2. 与冻结 baseline（ci_cd/orm_migration_baseline.json）差分：
   - **新列**（当前有 / baseline 无）：必须满足其一，否则 FAIL——
     a) 该列有对应 ``ensure_*`` 的 ``ALTER TABLE <t> ADD COLUMN <c>`` 迁移
        （AST 提取 core/ 迁移文件全部字符串常量，含 f-string 动态元组形态）；
     b) 列是「软列」：nullable=True 或带 server_default（SQL DEFAULT）——
        raw INSERT / 旧行读取不炸（#858/#869 教训：Python-side default 不算，
        必须 SQL DEFAULT）。
   - **删除列**（baseline 有 / 当前无）：warning 不 FAIL（drop 列有独立迁移
     形态 ensure_*_drop_*，且删列不破坏旧库升级）。
   - **新表**：no-op（create_all 建新表，无需 ensure）。
3. baseline 更新 = 显式跑 regen 脚本（人工 review diff），CI 只读。

不能检测什么（文档义务，#1184a 教训——只写能力面的门禁制造虚假安全感）
──────────────────────────────────────────────────────────────────────
- baseline 冻结前的存量列（历史列的 ensure 覆盖由链级升级回归测试锁定，
  见 tests/unit/infrastructure/database/test_database_migration_chain.py
  与 tests/migration/ 发布版 DB 升级回归）。
- ensure 写了但 lifespan 未接线（由 D3 AST wiring 门禁锁：registered==called）。
- 数据回填 / 索引-旧数据顺序类缺陷（#869 类 1/2，靠链级回归测试）。
- 列类型漂移（改 String 长度 / 改 nullable 收紧）——只锁「新列缺迁移」。
- 表删除后的数据迁移完整性（靠升级回归 job #1005）。

用法
────
    cd backend
    uv run python ../ci_cd/check_orm_migration_drift.py          # CI 门禁（exit 0/1）
    uv run python ../ci_cd/check_orm_migration_drift.py --regen  # 重新冻结 baseline

依据: issue #1006 · ADR-027（测试分层/门禁）· sqlite-schema-migration skill
（D3 substring 假绿教训 → 本脚本全程 AST/反射，零 substring 判定）。
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

# backend/src 加入 sys.path（脚本从 backend/ 或仓库根跑均可）
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "backend" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

BASELINE_PATH = Path(__file__).resolve().parent / "orm_migration_baseline.json"

# 迁移 helper 分布面（#1006 勘察事实：ensure_* 不止 database.py，
# migrations_project.py / migrations_chapter.py 亦有；glob 覆盖后续拆分）
_MIGRATION_FILES_GLOB = "migrations*.py"
_DATABASE_FILE = "database.py"

# ALTER TABLE <t> ADD COLUMN <c>（字面量形态；表名/列名允许引号包裹）
_ADD_COL_RE = re.compile(
    r"ALTER\s+TABLE\s+[\"']?(\w+)[\"']?\s+ADD\s+COLUMN\s+[\"']?(\w+)[\"']?",
    re.IGNORECASE,
)
# f-string 动态形态碎片："ALTER TABLE projects ADD COLUMN "（列名来自 FormattedValue）
_DYN_ADD_COL_RE = re.compile(r"ALTER\s+TABLE\s+[\"']?(\w+)[\"']?\s+ADD\s+COLUMN\s*$", re.IGNORECASE)


def _orm_columns() -> dict[str, dict[str, dict[str, bool]]]:
    """运行时反射 ORM 列集：{table: {column: {"nullable": b, "has_server_default": b}}}.

    import 触发 Base.metadata 注册（models/__init__.py 全量 import）。
    """
    import inkflow.infrastructure.database.models  # noqa: F401  # Base.metadata 注册
    from inkflow.core.database import Base

    result: dict[str, dict[str, dict[str, bool]]] = {}
    for table_name, table in Base.metadata.tables.items():
        cols: dict[str, dict[str, bool]] = {}
        for col in table.columns:
            cols[col.name] = {
                "nullable": bool(col.nullable),
                # server_default 含 SQL DEFAULT（#858/#869：Python-side default 不算）
                "has_server_default": col.server_default is not None,
            }
        result[table_name] = cols
    return result


def _string_constants(tree: ast.AST) -> list[str]:
    """提取 AST 内全部字符串常量（含 f-string 的字面碎片，FormattedValue 处截断）.

    JoinedStr 的碎片拼接：``f"ALTER TABLE {t} ADD COLUMN {c}"`` 产出碎片
    "ALTER TABLE " / " ADD COLUMN "——动态形态由调用方按函数体二次处理。
    """
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            # f-string：把字面碎片按序拼成一条（FormattedValue 以 \x00 占位标记）
            parts: list[str] = []
            for v in node.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    parts.append(v.value)
                else:
                    parts.append("\x00")
            out.append("".join(parts))
    return out


def _tuple_column_names(tree: ast.AST) -> set[str]:
    """提取函数体内「(列名, 定义) 元组常量」的列名（ensure_project_columns 动态形态）.

    形态：additions = (("tags", "JSON NOT NULL DEFAULT '[]'"), ...)——
    元组首元素为 Str 常量、次元素为含 DEFAULT/NOT NULL 等 SQL 片段的 Str 常量。
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Tuple, ast.List)):
            continue
        elts = node.elts
        if len(elts) != 2:
            continue
        first, second = elts
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            continue
        if not (isinstance(second, ast.Constant) and isinstance(second.value, str)):
            continue
        # 次元素须像 SQL 列定义（防误收普通二元组）
        if re.search(
            r"\b(DEFAULT|NOT NULL|NULL|TEXT|INTEGER|JSON|BOOLEAN|VARCHAR|FLOAT)\b",
            second.value,
            re.IGNORECASE,
        ):
            names.add(first.value)
    return names


def ensure_addition_columns(core_dir: Path) -> dict[str, set[str]]:
    """AST 提取全部 ensure 迁移的补列集：{table: {column}}.

    扫描面：core/database.py + core/migrations*.py（迁移 helper 实际分布，
    #1006 勘察事实）。逐函数处理两种形态：
    1. 字面量：字符串常量直接匹配 _ADD_COL_RE；
    2. f-string 动态：碎片匹配 _DYN_ADD_COL_RE（表名在碎片内、列名是占位）→
       列名取同函数体的 (列名, SQL定义) 元组常量首元素。
    """
    files = [core_dir / _DATABASE_FILE, *sorted(core_dir.glob(_MIGRATION_FILES_GLOB))]
    additions: dict[str, set[str]] = {}
    for path in files:
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        # 逐函数扫描（动态形态的元组常量与 f-string 在同一函数体内）
        funcs = [
            n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        # 模块级字符串也扫（防 helper 写在模块级）
        scopes: list[ast.AST] = [*funcs, tree]
        for scope in scopes:
            consts = _string_constants(scope)
            dyn_tables: set[str] = set()
            for s in consts:
                for m in _ADD_COL_RE.finditer(s):
                    additions.setdefault(m.group(1), set()).add(m.group(2))
                # 动态碎片：\x00 是 FormattedValue 占位——"ALTER TABLE t ADD COLUMN \x00"
                normalized = s.replace("\x00", "").rstrip()
                dm = _DYN_ADD_COL_RE.search(normalized + " ")
                if dm and "\x00" in s:
                    dyn_tables.add(dm.group(1))
            if dyn_tables:
                tuple_cols = _tuple_column_names(scope)
                for t in dyn_tables:
                    additions.setdefault(t, set()).update(tuple_cols)
    return additions


def _load_baseline() -> dict[str, dict[str, dict[str, bool]]] | None:
    if not BASELINE_PATH.exists():
        return None
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return data.get("columns")  # type: ignore[no-any-return]


def _regen(columns: dict[str, dict[str, dict[str, bool]]]) -> None:
    payload = {
        "_comment": (
            "ORM 列集冻结 baseline（#1006 漂移门禁）。更新 = 显式跑 "
            "check_orm_migration_drift.py --regen 并 review diff；CI 只读。"
        ),
        "columns": columns,
    }
    BASELINE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    n_tables = len(columns)
    n_cols = sum(len(c) for c in columns.values())
    print(f"[drift] baseline 已冻结: {n_tables} 表 / {n_cols} 列 → {BASELINE_PATH.name}")


def check() -> int:
    """门禁主逻辑：新列必须有 ensure 迁移或为软列；返回 exit code."""
    columns = _orm_columns()
    baseline = _load_baseline()
    if baseline is None:
        print(
            "[drift] FAIL: baseline 不存在（ci_cd/orm_migration_baseline.json）。"
            "首次接入跑 --regen 冻结。",
            file=sys.stderr,
        )
        return 1

    core_dir = _SRC / "inkflow" / "core"
    additions = ensure_addition_columns(core_dir)

    failures: list[str] = []
    warnings: list[str] = []

    for table, cols in sorted(columns.items()):
        base_cols = baseline.get(table)
        if base_cols is None:
            continue  # 新表：create_all 负责，无需 ensure
        for col, attrs in sorted(cols.items()):
            if col in base_cols:
                continue  # 存量列：baseline 冻结前的历史，链级回归测试负责
            # ── 新列判定 ──
            if col in additions.get(table, set()):
                continue  # 有 ensure ADD COLUMN 迁移 ✓
            if attrs["nullable"] or attrs["has_server_default"]:
                continue  # 软列：旧行读取/raw INSERT 不炸 ✓
            failures.append(
                f"{table}.{col}: ORM 新增 NOT NULL 无 SQL DEFAULT 列，"
                f"且无 ensure_* ADD COLUMN 迁移 → 旧库升级将缺列"
                f"（修法：core/ 迁移文件加 ALTER TABLE {table} ADD COLUMN {col} ... "
                f"带 NOT NULL DEFAULT，并接线 lifespan；随后 --regen baseline）"
            )

    for table, base_cols in sorted(baseline.items()):
        cur_cols = columns.get(table)
        if cur_cols is None:
            warnings.append(f"{table}: 表已从 ORM 移除（确认有数据迁移/DROP 迁移承接）")
            continue
        for col in sorted(base_cols):
            if col not in cur_cols:
                warnings.append(f"{table}.{col}: 列已从 ORM 移除（确认 drop 迁移承接）")

    for w in warnings:
        print(f"[drift] WARNING {w}")
    if failures:
        for f in failures:
            print(f"[drift] FAIL {f}", file=sys.stderr)
        print(f"[drift] {len(failures)} 个 ORM 新列缺迁移接线", file=sys.stderr)
        return 1

    n_tables = len(columns)
    n_cols = sum(len(c) for c in columns.values())
    n_add = sum(len(v) for v in additions.values())
    print(f"[drift] OK: {n_tables} 表 / {n_cols} 列对账通过（ensure 补列集 {n_add} 项，0 漂移）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="ORM↔迁移漂移门禁（#1006）")
    parser.add_argument(
        "--regen",
        action="store_true",
        help="重新冻结 baseline（人工 review diff 后提交；CI 禁用）",
    )
    args = parser.parse_args()
    if args.regen:
        _regen(_orm_columns())
        return 0
    return check()


if __name__ == "__main__":
    sys.exit(main())
