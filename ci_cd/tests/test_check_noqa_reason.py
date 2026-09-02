"""RED 契约测试（contract-s3f-ci-guard / #869 遗留②）：
ci_cd/check_noqa_reason.py 纯函数面 + cp1252 stdout 健壮性。

脚本本体 = CI lint-backend 护栏（GREEN 义务，由 Codex 按本文件 docstring 契约实现；
argv 解析细节不锁）。脚本位于仓库根 ci_cd/、不属于 backend 包，故经 importlib.util 按路径
动态加载（与 backend/tests/unit/test_verify_release_artifacts.py 同法；文件缺失 →
exec_module 抛 FileNotFoundError，无收集期 ImportError）。

RED 预期形态：恰 1 红 = test_main_violations_report_returns_one_under_cp1252_stdout
——当前实现 main() 违规路径打印中文修复提示（L52-55），在 cp1252 stdout（CI windows runner
实测编码）下抛 UnicodeEncodeError，traceback 先于 return 1（#869 遗留②实锤缺陷）。
其余纯函数面用例当前实现已满足（绿）。

GREEN 义务（函数签名 + 语义，以本文件断言为准）：
1. check(paths: list[str]) -> list[tuple[str, int, str]]
   - 行内抑制匹配对象：noqa(: 代码)? 与 type: ignore[...] / mypy: ignore[...] 三种形式
     （抑制注释本身以「hash + 空白」开头，小写敏感；可带代码前缀/缩进）。
   - 理由 = 同一行内抑制段之后第二个 hash 注释，且其后至少 1 个非空白字符（含 CJK）；
     「空理由」（第二个 hash 后仅空白或直达行尾）仍判违规。
   - 报告元组 (str(文件路径), 行号(1 基), 原行 strip() 后内容)；路径为 utf-8 读取。
   - 目录参数 → sorted(rglob("*.py")) 递归；跳过含 `__pycache__` 段的文件；.py 之外不扫。
   - 不存在路径静默跳过；空输入/全合规 → []。
2. main() 退出码语义（任意 stdout 编码下同约束）：
   - 全合规 → return 0（输出仅 ASCII，cp1252 天然安全）。
   - 存在违规 → 打印违规清单与修复提示后 return 1；cp1252 等非 UTF-8 stdout 下不得抛
     UnicodeEncodeError（实现方式自由：提示 ASCII 化 / sys.stdout.reconfigure /
     errors='replace'，契约只锁「不崩 + 退出码 1」）。

测试全部用 tmp 构造假 .py 文件（utf-8 写入），零真实仓库依赖。夹具文本统一经 _sup() 运行时
拼装，杜绝测试文件自身物理行出现 hash 紧邻 noqa 的抑制字样（护栏未来若自扫本目录不误报的纪律）。
"""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "ci_cd" / "check_noqa_reason.py"


def _sup(suppression: str) -> str:
    """运行时拼装抑制注释前缀（拆散 hash 与 noqa 的物理相邻，防护栏自扫不把
    夹具文本误判为无理由抑制）。"""
    return "# " + suppression


# 测试夹具纯 ASCII 行内容基准（bad 行本身不含非 ASCII，保证 cp1252 崩溃只可能来自脚本的
# 中文修复提示行，而非扫描内容——精确复现 #869 遗留② 的 CI 崩溃形态）
BAD_LINE_ASCII = "x = 1  " + _sup("noqa: E501")


def _write(path: Path, lines: list[str]) -> None:
    """utf-8 写入多行夹具文件（父目录自动创建）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_script():
    """动态加载 ci_cd/check_noqa_reason.py（RED：文件缺失 → FileNotFoundError）。"""
    spec = importlib.util.spec_from_file_location("check_noqa_reason", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cp1252_stdout(monkeypatch) -> io.TextIOWrapper:
    """把 sys.stdout 换成 cp1252 编码包装器（CI windows runner 控制台编码形态）。

    write_through=True 保证写入即编码 → UnicodeEncodeError 同步抛出，与真实控制台行为一致。
    """
    buf = io.BytesIO()
    wrapper = io.TextIOWrapper(buf, encoding="cp1252", write_through=True)
    monkeypatch.setattr(sys, "stdout", wrapper)
    return wrapper


def test_script_exists_and_exposes_contract_functions() -> None:
    """脚本文件存在 + check/main 两个契约函数可调用（RED：脚本不存在 → 本用例 ERROR）。"""
    module = _load_script()
    assert callable(module.check), "脚本应导出函数 check"
    assert callable(module.main), "脚本应导出函数 main"


def test_check_empty_and_missing_paths_are_skipped_silently(tmp_path: Path) -> None:
    """空输入 → []；不存在路径（非文件非目录）→ 静默跳过 → []。"""
    check = _load_script().check
    assert check([]) == []
    missing = tmp_path / "does_not_exist.py"
    assert check([str(missing)]) == []


def test_check_nonpy_files_ignored_in_directory(tmp_path: Path) -> None:
    """目录参数只扫 *.py：.txt 内含抑制字样不进结果。"""
    check = _load_script().check
    d = tmp_path / "src"
    d.mkdir()
    (d / "readme.txt").write_text("import os  " + _sup("noqa: E501") + "\n", encoding="utf-8")
    assert check([str(d)]) == []


def test_check_flags_noqa_without_reason(tmp_path: Path) -> None:
    """无理由 noqa（带 code / 裸 noqa）→ 报告；同行带理由的对照行不报告。"""
    check = _load_script().check
    f = tmp_path / "bad_noqa.py"
    noqa_coded = "import os  " + _sup("noqa: E501")
    noqa_bare = "x = 1  " + _sup("noqa")
    clean = "y = 2  " + _sup("noqa: E501") + "  # ascii reason"
    _write(f, [noqa_coded, noqa_bare, clean])
    assert check([str(f)]) == [
        (str(f), 1, noqa_coded),
        (str(f), 2, noqa_bare),
    ]


def test_check_accepts_noqa_with_reason_including_cjk(tmp_path: Path) -> None:
    """理由非空即合规：ASCII / 多 code / 裸 noqa / CJK 理由均不报告。"""
    check = _load_script().check
    f = tmp_path / "ok_noqa.py"
    _write(
        f,
        [
            "a = 1  " + _sup("noqa: E501") + "  # 单字符变量豁免（lint 风格）",
            "b = 2  " + _sup("noqa: E501, F401") + "  # multi-code ascii reason",
            "c = 3  " + _sup("noqa") + "  # bare form with reason",
            "d = 4  " + _sup("noqa: W605") + "  # 正则字符串转义需显式豁免",
        ],
    )
    assert check([str(f)]) == []


def test_check_rejects_empty_reason_tail(tmp_path: Path) -> None:
    """空理由仍判违规：`#` 后仅尾随空白、或 `#` 直达行尾。"""
    check = _load_script().check
    f = tmp_path / "empty_reason.py"
    ws_only = "x = 1  " + _sup("noqa: E501") + "  #   "
    bare_hash = "y = 2  " + _sup("noqa: E501") + "  #"
    _write(f, [ws_only, bare_hash])
    # strip() 后两条报告的原始行形态一致（尾随空白被剥）
    assert check([str(f)]) == [
        (str(f), 1, ws_only.strip()),
        (str(f), 2, bare_hash),
    ]


def test_check_flags_type_and_mypy_ignores_without_reason(tmp_path: Path) -> None:
    """type: ignore / mypy: ignore 无理由 → 报告；带理由 → 合规。"""
    check = _load_script().check
    f = tmp_path / "type_ignore.py"
    type_bare = "import foo  " + _sup("type: ignore[import-not-found]")
    mypy_bare = "x: int = 1  " + _sup("mypy: ignore")
    type_ok = "import bar  " + _sup("type: ignore[import-not-found]") + "  # stub 缺失"
    mypy_ok = "y = 1  " + _sup("mypy: ignore[assignment]") + "  # 反射赋值绕过"
    _write(f, [type_bare, mypy_bare, type_ok, mypy_ok])
    assert check([str(f)]) == [
        (str(f), 1, type_bare),
        (str(f), 2, mypy_bare),
    ]


def test_check_reports_lineno_and_utf8_cjk_payload(tmp_path: Path) -> None:
    """行号 1 基准确 + utf-8 读取：CJK 行内容（无理由）正常进报告。"""
    check = _load_script().check
    f = tmp_path / "cjk_payload.py"
    cjk_line = "数据 = 1  " + _sup("noqa: E501")
    _write(
        f,
        [
            "import os",
            "import sys  # ok",
            cjk_line,
        ],
    )
    assert check([str(f)]) == [(str(f), 3, cjk_line)]


def test_check_directory_recursion_skips_pycache(tmp_path: Path) -> None:
    """目录递归：子目录 .py 全扫；__pycache__ 段与 .txt 不报告。"""
    check = _load_script().check
    root = tmp_path / "src_tree"
    (root / "sub").mkdir(parents=True)
    (root / "__pycache__").mkdir()
    _write(root / "a.py", [BAD_LINE_ASCII])
    _write(root / "sub" / "b.py", [BAD_LINE_ASCII])
    (root / "readme.txt").write_text("import os  " + _sup("noqa: E501") + "\n", encoding="utf-8")
    _write(root / "__pycache__" / "c.py", [BAD_LINE_ASCII])
    expected = sorted(
        [
            (str(root / "a.py"), 1, BAD_LINE_ASCII),
            (str(root / "sub" / "b.py"), 1, BAD_LINE_ASCII),
        ]
    )
    assert sorted(check([str(root)])) == expected


def test_main_clean_scan_returns_zero_under_cp1252_stdout(monkeypatch, tmp_path: Path) -> None:
    """cp1252 stdout + 全合规 → return 0 不崩（输出全 ASCII，当前实现即满足）。"""
    module = _load_script()
    f = tmp_path / "clean.py"
    _write(f, ["import os", "x = 1  " + _sup("noqa: E501") + "  # 有理由"])
    _cp1252_stdout(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["check_noqa_reason.py", str(f)])
    assert module.main() == 0


def test_main_violations_report_returns_one_under_cp1252_stdout(
    monkeypatch, tmp_path: Path
) -> None:
    """【本文件唯一 RED】#869 遗留②：cp1252 stdout 下违规报告必须 return 1。

    当前实现 L55 print 中文修复提示 → TextIOWrapper(cp1252) 写入即抛 UnicodeEncodeError，
    main() 崩溃、rc 永不赋值 → 本用例 FAIL（traceback 先于 return 1 的 CI 实锤缺陷形态）。
    GREEN 修复（提示 ASCII 化或 stdout reconfigure/errors='replace' 等，方式自由）后应
    正常 return 1。夹具 bad 行纯 ASCII，确保崩溃仅可能来自脚本自身中文提示行。
    """
    module = _load_script()
    f = tmp_path / "bad.py"
    _write(f, [BAD_LINE_ASCII])
    _cp1252_stdout(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["check_noqa_reason.py", str(f)])
    assert module.main() == 1
