"""契约测试（#1326 PR 1）：ci_cd/check_gui_spec_sync.py 纯函数面 + main 退出码。

护栏职责：校验 `design/GUI/<page>/` 原型目录集 ↔ `specs/f19-gui/<page>.md` 页规格集
**双向一一对应**，防止再出现孤儿（有原型无规格）/ 幽灵（有规格无原型）。

脚本位于仓库根 ci_cd/、不属于 backend 包，故经 importlib.util 按路径动态加载
（与 ci_cd/tests/test_check_doc_pointers.py 同法；文件缺失 → exec_module 抛
FileNotFoundError，无收集期 ImportError）。

契约（函数签名 + 语义，以本文件断言为准）：
1. check_gui_spec_sync(repo_root: str) -> list[tuple[str, str]]
   - 页面目录集 = design/GUI/ 下全部子目录，排除 `_tools`。
   - 页规格集 = specs/f19-gui/*.md 的 stem，排除 `spec.md`。
   - 返回不匹配项 [(kind, page)]，kind ∈ {"orphan", "ghost"}，按 page 排序；空列表 = 一一对应。
   - orphan = 有原型目录无页规格；ghost = 有页规格无原型目录。
   - 目录/规格根不存在 → 视为空集（不抛异常）。
2. main() 退出码语义（任意 stdout 编码下同约束）：
   - 全部对应 → 打印 `[check_gui_spec_sync] OK: N page(s) matched prototype <-> spec` 后 return 0。
   - 存在不匹配 → 打印 `[check_gui_spec_sync] M mismatch(es):` + 每行含 `orphan:`/`ghost:`
     与 page 名后 return 1；非 UTF-8 stdout 下不得抛 UnicodeEncodeError
     （sys.stdout.reconfigure(errors="replace") 兜底）。
   - 缺参数（argv 只有脚本名）→ 打印模块 `__doc__` 后 return 2。

测试全部用 tmp 构造假仓库，零真实仓库依赖（正例基线口径由验收命令在主仓根实测 = 15 页）。
"""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "ci_cd" / "check_gui_spec_sync.py"


def _load_script():
    """动态加载 ci_cd/check_gui_spec_sync.py（RED：文件缺失 → FileNotFoundError）。"""
    spec = importlib.util.spec_from_file_location("check_gui_spec_sync", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_repo(root: Path, pages: list[str], specs: list[str]) -> Path:
    """构造假仓库：pages 建 design/GUI/<p>/ 目录，specs 建 specs/f19-gui/<s>.md 文件。"""
    proto = root / "design" / "GUI"
    proto.mkdir(parents=True, exist_ok=True)
    for page in pages:
        (proto / page).mkdir(parents=True, exist_ok=True)
    spec_dir = root / "specs" / "f19-gui"
    spec_dir.mkdir(parents=True, exist_ok=True)
    for name in specs:
        (spec_dir / f"{name}.md").write_text(f"# {name}\n", encoding="utf-8")
    return root


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
    assert callable(module.check_gui_spec_sync), "脚本应导出函数 check_gui_spec_sync"
    assert callable(module.main), "脚本应导出函数 main"


def test_matched_sets_returns_empty_and_main_exits_zero(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """正例：目录集与规格集一致 → [] + main 退出码 0 + 页数进 OK 行。"""
    module = _load_script()
    _make_repo(tmp_path, ["book", "writing"], ["book", "writing"])
    assert module.check_gui_spec_sync(str(tmp_path)) == []
    monkeypatch.setattr(sys, "argv", ["check_gui_spec_sync.py", str(tmp_path)])
    assert module.main() == 0
    assert (
        "[check_gui_spec_sync] OK: 2 page(s) matched prototype <-> spec" in capsys.readouterr().out
    )


def test_orphan_page_reports_and_main_exits_one(monkeypatch, tmp_path: Path, capsys) -> None:
    """反例（核心，对应 #1326 实测形态）：有原型目录无页规格 → orphan + main 退出码 1。"""
    module = _load_script()
    _make_repo(tmp_path, ["book", "writing"], ["writing"])
    assert module.check_gui_spec_sync(str(tmp_path)) == [("orphan", "book")]
    monkeypatch.setattr(sys, "argv", ["check_gui_spec_sync.py", str(tmp_path)])
    assert module.main() == 1
    out = capsys.readouterr().out
    assert "[check_gui_spec_sync] 1 mismatch(es):" in out
    assert "orphan:" in out
    assert "book" in out


def test_ghost_spec_reports_and_main_exits_one(monkeypatch, tmp_path: Path, capsys) -> None:
    """反例（反向）：有页规格无原型目录 → ghost + main 退出码 1（双向都有效）。"""
    module = _load_script()
    _make_repo(tmp_path, ["writing"], ["book", "writing"])
    assert module.check_gui_spec_sync(str(tmp_path)) == [("ghost", "book")]
    monkeypatch.setattr(sys, "argv", ["check_gui_spec_sync.py", str(tmp_path)])
    assert module.main() == 1
    out = capsys.readouterr().out
    assert "[check_gui_spec_sync] 1 mismatch(es):" in out
    assert "ghost:" in out


def test_tools_dir_and_spec_md_are_excluded(tmp_path: Path) -> None:
    """排除规则：design/GUI/_tools 与 specs/f19-gui/spec.md 都不参与对应，不误报。"""
    module = _load_script()
    _make_repo(tmp_path, ["book", "_tools"], ["book", "spec"])
    assert module.check_gui_spec_sync(str(tmp_path)) == []


def test_missing_roots_are_treated_as_empty(tmp_path: Path) -> None:
    """根目录不存在 → 两侧都视为空集（不抛异常，返回 []）。"""
    module = _load_script()
    assert module.check_gui_spec_sync(str(tmp_path)) == []


def test_results_sorted_by_page(tmp_path: Path) -> None:
    """多项不匹配时按 page 名排序（orphan 在前、ghost 在后，各自内部有序）。"""
    module = _load_script()
    _make_repo(tmp_path, ["zeta", "alpha"], ["beta"])
    assert module.check_gui_spec_sync(str(tmp_path)) == [
        ("orphan", "alpha"),
        ("orphan", "zeta"),
        ("ghost", "beta"),
    ]


def test_both_directions_reported_together(monkeypatch, tmp_path: Path, capsys) -> None:
    """同时存在孤儿与幽灵 → 两条报告 + 计数为 2 + 退出码 1。"""
    module = _load_script()
    _make_repo(tmp_path, ["book"], ["writing"])
    assert module.check_gui_spec_sync(str(tmp_path)) == [("orphan", "book"), ("ghost", "writing")]
    monkeypatch.setattr(sys, "argv", ["check_gui_spec_sync.py", str(tmp_path)])
    assert module.main() == 1
    assert "[check_gui_spec_sync] 2 mismatch(es):" in capsys.readouterr().out


def test_main_without_args_prints_usage_and_exits_two(monkeypatch, capsys) -> None:
    """缺参数：打印模块 __doc__（用法/退出码）→ return 2。"""
    module = _load_script()
    monkeypatch.setattr(sys, "argv", ["check_gui_spec_sync.py"])
    assert module.main() == 2
    assert "check_gui_spec_sync" in capsys.readouterr().out


def test_main_survives_cp1252_stdout_with_cjk_path(monkeypatch, tmp_path: Path) -> None:
    """cp1252 stdout + 报告路径含 CJK → 不得抛 UnicodeEncodeError，仍 return 1。"""
    module = _load_script()
    root = tmp_path / "中文目录"
    _make_repo(root, ["手册"], [])
    _cp1252_stdout(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["check_gui_spec_sync.py", str(root)])
    assert module.main() == 1
