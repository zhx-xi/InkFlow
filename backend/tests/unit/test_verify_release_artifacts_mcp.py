"""#1072 方案 C 的 MCP 门禁契约测试 —— #1078 修正后语义。

历史：#1075 曾断言 `inkflow-mcp.exe --version == tag`；#1078 证实该接口**不存在**
（MCP 入口是纯 stdio JSON-RPC 服务器），断言恒 FAIL → 已改用 stdio 握手探针。
本文件保留 #1072 的**有效**契约（路径常量 + 结构标签同源），
MCP 健康检查的新契约见 `test_verify_release_artifacts_mcp_stdio.py`。

#1072 背景：`inkflow.spec` 强制排除 `litellm`（#1024 迁移未同步），打包版内核
import 期 `ModuleNotFoundError` → `inkflow.exe --version` exit 1。修复=移除 excludes
+ collect_all(litellm/langchain_litellm/tokenizers)（洋葱第二层）。

保留契约：
  W1. `mcp_exe_rel_path() -> str` == "inkflow-mcp/inkflow-mcp.exe"
      （与 check_cli_zip_structure 的缺失标签同源，防两处字面量漂移）
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "ci_cd" / "verify_release_artifacts.py"

VALID_CLI_NAMELIST = [
    "inkflow/",
    "inkflow/inkflow.exe",
    "inkflow/_internal/",
    "inkflow/_internal/python312.dll",
    "inkflow/_internal/inkflow-0.14.0.dist-info/METADATA",
    "inkflow/_internal/inkflow-0.14.0.dist-info/RECORD",
    "inkflow-mcp/",
    "inkflow-mcp/inkflow-mcp.exe",
    "skills/",
    "skills/writing/",
    "skills/writing/SKILL.md",
]


def _load_script():
    spec = importlib.util.spec_from_file_location("verify_release_artifacts", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_cli_zip_structure_complete_includes_mcp() -> None:
    """完整 namelist（含 MCP exe）→ 无缺失。"""
    check = _load_script().check_cli_zip_structure
    assert check(VALID_CLI_NAMELIST) == []


def test_deprecated_mcp_version_row_still_importable_for_compat() -> None:
    """[#1078] 旧的 _mcp_zip_version_row 保留为弃用兼容壳，返回 FAIL 说明。"""
    module = _load_script()
    fn = getattr(module, "_mcp_zip_version_row", None)
    assert callable(fn)
    ok, detail = fn(Path("nonexistent.zip"), "v0.14.0-rc2")
    assert ok is False
    assert "deprecated" in detail
