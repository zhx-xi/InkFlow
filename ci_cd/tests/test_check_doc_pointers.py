"""RED 契约测试（#1190 批 C）：ci_cd/check_doc_pointers.py 纯函数面 + main 退出码。

护栏职责：校验 `AGENTS.md` 里的「仓库根相对路径指针」（反引号 token）真实存在，
防止指针腐化（批 A/B 实测三类失效：悬空 plan.md 尾注 / 手写行号漂移 / 测试路径失效）。

脚本位于仓库根 ci_cd/、不属于 backend 包，故经 importlib.util 按路径动态加载
（与 ci_cd/tests/test_check_noqa_reason.py 同法；文件缺失 → exec_module 抛
FileNotFoundError，无收集期 ImportError）。

GREEN 义务（函数签名 + 语义，以本文件断言为准）：
1. check_doc_pointers(repo_root: str, doc: str = "AGENTS.md") -> list[tuple[str, int, str]]
   - 提取文档全部反引号 token；仅接受「仓库根相对路径」：白名单顶层目录前缀
     （adr/ specs/ backend/ docs/ design/ ci_cd/ tests/ frontend/ .specify/ .githooks/
     .github/ skills/）或不含 `/` 且以 .md 结尾的根级文件。
   - 排除：含 `<` `>` `*` `|` / 含 `NNN` / 含 `://` / 以 `/` 开头 / 含空格 /
     以 `D:` `C:` `http` `git ` `python ` `uv ` `gh ` `grep` `#` 开头。
   - 同一 token 多次出现按首次出现行号去重（指针数口径 = 去重后数量，见 #1190 批 C 基线 31）。
   - 判定：`Path(repo_root) / token` 存在；token 以 `/` 结尾时按目录判存在。
   - 报告元组 (str(Path(repo_root) / doc), 行号(1 基), token)，按首次出现顺序；全有效 → []。
2. main() 退出码语义（任意 stdout 编码下同约束）：
   - 全部有效 → 打印 `[check_doc_pointers] OK: N pointer(s) resolved` 后 return 0。
   - 存在失效 → 打印 `[check_doc_pointers] M broken pointer(s):` + 每行 `  文件:行号: token`
     后 return 1；cp1252 等非 UTF-8 stdout 下不得抛 UnicodeEncodeError
     （sys.stdout.reconfigure(errors="replace") 兜底）。
   - 缺参数（argv 只有脚本名）→ 打印模块 `__doc__` 后 return 2。

测试全部用 tmp 构造假文档 + 假仓库，零真实仓库依赖（正例基线口径由验收命令在主仓根实测）。
"""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "ci_cd" / "check_doc_pointers.py"

# 脚本 main() 固定读 AGENTS.md，故临时仓库的假文档必须叫这个名字
DOC = "AGENTS.md"


def _load_script():
    """动态加载 ci_cd/check_doc_pointers.py（RED：文件缺失 → FileNotFoundError）。"""
    spec = importlib.util.spec_from_file_location("check_doc_pointers", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_lines(root: Path, lines: list[str], doc: str = DOC) -> Path:
    """utf-8 写入假文档（父目录自动创建，行号 = 列表序号）。"""
    root.mkdir(parents=True, exist_ok=True)
    path = root / doc
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_tokens(root: Path, tokens: list[str], doc: str = DOC) -> Path:
    """每行一个反引号 token 的假文档（行号 = token 在列表中的序号）。"""
    return _write_lines(root, [f"`{token}`" for token in tokens], doc)


def _cp1252_stdout(monkeypatch) -> io.TextIOWrapper:
    """把 sys.stdout 换成 cp1252 编码包装器（CI windows runner 控制台编码形态）。

    write_through=True 保证写入即编码 → UnicodeEncodeError 同步抛出，与真实控制台行为一致。
    """
    buf = io.BytesIO()
    wrapper = io.TextIOWrapper(buf, encoding="cp1252", write_through=True)
    monkeypatch.setattr(sys, "stdout", wrapper)
    return wrapper


def test_script_exists_and_exposes_contract_functions() -> None:
    """脚本文件存在 + 契约函数可调用（RED：脚本不存在 → 本用例 ERROR）。"""
    module = _load_script()
    assert callable(module.check_doc_pointers), "脚本应导出函数 check_doc_pointers"
    assert callable(module.main), "脚本应导出函数 main"


def test_all_pointers_resolve_returns_empty_and_main_exits_zero(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """正例：指针（含目录形态）全部存在 → [] + main 退出码 0 + 指针数进 OK 行。"""
    module = _load_script()
    (tmp_path / "design").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "contract-guard.md").write_text("x\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "conftest.py").write_text("x\n", encoding="utf-8")
    _write_tokens(
        tmp_path,
        ["AGENTS.md", "design/", "docs/contract-guard.md", "tests/conftest.py"],
    )
    assert module.check_doc_pointers(str(tmp_path)) == []
    monkeypatch.setattr(sys, "argv", ["check_doc_pointers.py", str(tmp_path)])
    assert module.main() == 0
    assert "[check_doc_pointers] OK: 4 pointer(s) resolved" in capsys.readouterr().out


def test_broken_pointer_reports_token_and_lineno_and_main_exits_one(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """反例（核心）：1 个失效指针 → 1 条报告（文件/行号/token 正确）+ main 退出码 1。"""
    module = _load_script()
    doc_path = _write_tokens(tmp_path, ["AGENTS.md", "tests/missing-spec.md"])
    assert module.check_doc_pointers(str(tmp_path)) == [
        (str(doc_path), 2, "tests/missing-spec.md")
    ]
    monkeypatch.setattr(sys, "argv", ["check_doc_pointers.py", str(tmp_path)])
    assert module.main() == 1
    out = capsys.readouterr().out
    assert "[check_doc_pointers] 1 broken pointer(s):" in out
    assert f"  {doc_path}:2: tests/missing-spec.md" in out


def test_non_pointer_forms_are_ignored(tmp_path: Path) -> None:
    """排除规则：HTTP 端点 / DSN / 占位符 / 绝对路径 / 命令行片段一律不算指针。"""
    module = _load_script()
    _write_tokens(
        tmp_path,
        [
            "/health",
            "sqlite+aiosqlite:///:memory:",
            "adr/ADR-NNN.md",
            r"D:\path\x.md",
            "uv sync --frozen",
        ],
    )
    assert module.check_doc_pointers(str(tmp_path)) == []


def test_layer_relative_path_outside_whitelist_is_ignored(tmp_path: Path) -> None:
    """白名单外不放行：`domain/ports/`（层内相对）、`nodir/`（无白名单顶层目录）都不算指针。"""
    module = _load_script()
    _write_tokens(tmp_path, ["domain/ports/", "nodir/"])
    assert module.check_doc_pointers(str(tmp_path)) == []


def test_directory_token_is_judged_as_directory(tmp_path: Path) -> None:
    """目录形态：`design/` 目录存在判有效；`tests/nodir/` 不存在判失效；同名文件不算目录。

    注：目录形态失效用例用白名单前缀（`tests/nodir/`）——裸 `nodir/` 不在白名单顶层目录内，
    按提取规则根本不算指针（见上一条用例），故不能用来验证「目录不存在 → 失效」。
    """
    module = _load_script()

    ok_root = tmp_path / "ok"
    (ok_root / "design").mkdir(parents=True)
    _write_tokens(ok_root, ["design/"])
    assert module.check_doc_pointers(str(ok_root)) == []

    bad_root = tmp_path / "bad"
    _write_tokens(bad_root, ["tests/nodir/"])
    assert module.check_doc_pointers(str(bad_root)) == [
        (str(bad_root / DOC), 1, "tests/nodir/")
    ]

    file_root = tmp_path / "file-root"
    file_root.mkdir()
    (file_root / "tests").mkdir()
    (file_root / "tests" / "nodir").write_text("同名文件不是目录\n", encoding="utf-8")
    _write_tokens(file_root, ["tests/nodir/"])
    assert module.check_doc_pointers(str(file_root)) == [
        (str(file_root / DOC), 1, "tests/nodir/")
    ]


def test_repeated_token_counts_once_at_first_line(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """去重口径：同一 token 多次出现只算 1 个指针，行号取首次出现（基线 31 的口径）。"""
    module = _load_script()
    (tmp_path / "design").mkdir()
    _write_lines(tmp_path, ["`design/`", "`missing.md`", "`design/`", "`missing.md`"])
    assert module.check_doc_pointers(str(tmp_path)) == [
        (str(tmp_path / DOC), 2, "missing.md")
    ]
    monkeypatch.setattr(sys, "argv", ["check_doc_pointers.py", str(tmp_path)])
    assert module.main() == 1
    assert "[check_doc_pointers] 1 broken pointer(s):" in capsys.readouterr().out


def test_main_without_args_prints_usage_and_exits_two(monkeypatch, capsys) -> None:
    """缺参数：打印模块 __doc__（用法/退出码）→ return 2。"""
    module = _load_script()
    monkeypatch.setattr(sys, "argv", ["check_doc_pointers.py"])
    assert module.main() == 2
    assert "check_doc_pointers" in capsys.readouterr().out


def test_main_survives_cp1252_stdout_with_cjk_path(monkeypatch, tmp_path: Path) -> None:
    """cp1252 stdout + 报告路径含 CJK → 不得抛 UnicodeEncodeError，仍 return 1。"""
    module = _load_script()
    root = tmp_path / "中文目录"
    _write_tokens(root, ["missing-token.md"])
    _cp1252_stdout(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["check_doc_pointers.py", str(root)])
    assert module.main() == 1
