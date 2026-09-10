"""#1072 RED 契约：CLI zip 的 MCP exe 版本断言（方案 C 加强发布门禁）。

背景：`v0.14.0-rc1` 发布阻断 —— `inkflow.spec` 强制排除 `litellm`（#1024 迁移未同步），
打包版内核 import 期 `ModuleNotFoundError` → `inkflow.exe --version` exit 1。
现有门禁只断言内核 exe 版本；MCP exe（`inkflow-mcp/inkflow-mcp.exe`）**无版本/可启动断言**，
其 excludes 同样含 litellm（spec:196）→ 存在「内核修好、MCP 仍崩」漏网风险。

本文件锁定新增纯函数契约（RED：函数不存在 → AttributeError 失败）：

W1. `mcp_exe_rel_path() -> str`
    - 返回 CLI zip 内 MCP exe 的相对路径条目，规范形式锁定为
      `"inkflow-mcp/inkflow-mcp.exe"`（与 check_cli_zip_structure 的缺失标签同源，
      防两处字面量漂移）。

W2. `_mcp_zip_version_row(zip_path: Path, tag: str) -> tuple[bool, str]`
    - 解压 zip → 执行 `inkflow-mcp/inkflow-mcp.exe --version` → 与 tag 比对；
    - zip 内缺 MCP exe → (False, "<缺失说明>")，不抛异常；
    - 非法 zip → (False, "zip extraction failed: ...")；
    - 语义与 `_cli_zip_version_row` 对称（同一 `_exe_version_row` 复用）。

W3. `main` 面（--cli-zip 分支）新增行标签锁定：
    `"CLI zip MCP version == tag (inkflow-mcp.exe --version)"`
    （RED：脚本未产出该行 → 断言失败；GREEN 后应出现在 rows 中）

测试策略：纯函数用 tmp 构造最小 zip/exe 骨架，零真实产物依赖；
exe 启动路径用真实可执行假件（Windows 下 script 无法直接跑 → 用
`sys.executable --version` 式代理不可行，故 W2 的「成功」用例以 monkeypatch
替换 `_exe_version_row` 验证调用契约，真实打包由 rc 门禁/本地复现覆盖）。
"""

from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "ci_cd" / "verify_release_artifacts.py"


def _load_script():
    """动态加载 ci_cd/verify_release_artifacts.py（脚本在 backend 包外）。"""
    spec = importlib.util.spec_from_file_location("verify_release_artifacts", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── W1: MCP exe 相对路径常量 ────────────────────────────────────────────


def test_mcp_exe_rel_path_contract() -> None:
    """MCP exe 相对路径规范形式（与结构检查缺失标签同源）。"""
    module = _load_script()
    assert module.mcp_exe_rel_path() == "inkflow-mcp/inkflow-mcp.exe"


def test_mcp_exe_rel_path_matches_structure_label() -> None:
    """路径常量与 check_cli_zip_structure 的缺失标签一致（防两处漂移）。"""
    module = _load_script()
    rel = module.mcp_exe_rel_path()
    namelist = [
        "inkflow/inkflow.exe",
        "inkflow/_internal/x.dll",
        "skills/writing/SKILL.md",
    ]  # 缺 mcp exe
    missing = module.check_cli_zip_structure(namelist)
    assert rel in missing


# ── W2: MCP 版本行 helper ───────────────────────────────────────────────


def _make_zip_with_mcp(tmp_path: Path, *, with_mcp: bool = True) -> Path:
    """构造最小但**结构完整**的 CLI zip（镜像 PyInstaller onedir + mcp + skills）。

    结构完整是 main 面 rc==0 的前提：缺 inkflow/_internal/ 或 skills/ 会让结构行 FAIL，
    掩盖被测的 MCP 版本行。
    """
    zip_path = tmp_path / "cli.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("inkflow/inkflow.exe", b"MZ")
        zf.writestr("inkflow/_internal/", b"")
        zf.writestr("inkflow/_internal/inkflow-0.14.0.dist-info/METADATA", "x")
        zf.writestr("skills/writing/SKILL.md", "x")
        if with_mcp:
            zf.writestr("inkflow-mcp/inkflow-mcp.exe", b"MZ")
    return zip_path


def test_mcp_zip_version_row_missing_mcp_exe(tmp_path: Path) -> None:
    """zip 内缺 MCP exe → (False, 缺失说明)，不抛异常。"""
    module = _load_script()
    zip_path = _make_zip_with_mcp(tmp_path, with_mcp=False)
    ok, detail = module._mcp_zip_version_row(zip_path, "v0.14.0-rc1")
    assert ok is False
    assert "inkflow-mcp" in detail


def test_mcp_zip_version_row_bad_zip(tmp_path: Path) -> None:
    """非法 zip → (False, 'zip extraction failed: ...')，不抛异常。"""
    module = _load_script()
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip at all")
    ok, detail = module._mcp_zip_version_row(bad, "v0.14.0-rc1")
    assert ok is False
    assert "zip extraction failed" in detail


def test_mcp_zip_version_row_delegates_to_exe_version_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """复用 _exe_version_row（同一版本比对语义），路径为解压后 MCP exe。"""
    module = _load_script()
    zip_path = _make_zip_with_mcp(tmp_path)
    captured: dict[str, object] = {}

    def fake_row(exe: Path, tag: str) -> tuple[bool, str]:
        captured["exe"] = exe
        captured["tag"] = tag
        return True, "stub"

    monkeypatch.setattr(module, "_exe_version_row", fake_row)
    ok, detail = module._mcp_zip_version_row(zip_path, "v0.14.0-rc1")
    assert ok is True and detail == "stub"
    assert captured["tag"] == "v0.14.0-rc1"
    assert str(captured["exe"]).replace("\\", "/").endswith("inkflow-mcp/inkflow-mcp.exe")


# ── W3: main 增加 MCP 版本行 ────────────────────────────────────────────


def test_main_reports_mcp_version_row_for_cli_zip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """--cli-zip 分支必须产出一行 MCP 版本断言（标签锁定）。"""
    module = _load_script()
    zip_path = _make_zip_with_mcp(tmp_path)
    # 内核行与 MCP 行都走 _exe_version_row；stub 返回成功，隔离真实 exe 启动
    monkeypatch.setattr(module, "_exe_version_row", lambda exe, tag: (True, "stub"))
    rc = module.main(["--cli-zip", str(zip_path), "--version", "v0.14.0-rc1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "CLI zip MCP version == tag (inkflow-mcp.exe --version)" in out
