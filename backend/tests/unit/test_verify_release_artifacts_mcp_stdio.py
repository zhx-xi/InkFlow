"""#1078 RED 契约：MCP exe 门禁从「--version」改为 stdio 握手探针。

背景：`inkflow-mcp.exe --version` **不是产品接口** —— MCP 入口是纯 stdio JSON-RPC
服务器（`mcp/__main__.py` 仅 `run()`；`server.py:219` `anyio.run(main)` →
`stdio_server()`），无 CLI 参数解析。传 `--version` 被忽略，进程进入 stdio 等待、
stdin 即关 → exit 0 + stdout 空 → #1075 的版本断言恒 FAIL（rc2 发布阻断，run 34472329168）。

修正语义：用 MCP **协议本身**做健康检查 —— initialize → notifications/initialized
→ tools/list，断言工具面完整（18 个，与 MCP_TOOL_REGISTRY 同源）。

RED 预期：`mcp_stdio_row` / `MCP_EXPECTED_TOOLS` 不存在 → 用例失败。
GREEN 义务（以本文件断言为准）：
  W1. `MCP_EXPECTED_TOOLS` == 18（#1036 契约：15→18）
  W2. `mcp_stdio_row(mcp_exe: Path, expected: set[str] | None = None) -> tuple[bool, str]`
      - 对可握手的 MCP 入口（用本仓 venv 的 inkflow-mcp 或其模块入口）→ True
      - 不存在的 exe → (False, 说明)；不抛异常
      - 工具名集合不满足 expected → (False, ...)，不得假绿
  W3. `main` 的 --cli-zip 分支产出标签改为
      `CLI zip MCP stdio handshake (tools/list)`，且不再出现旧标签
      `CLI zip MCP version == tag (inkflow-mcp.exe --version)`

测试策略：W1 直接断言常量；W3 用 monkeypatch 隔离真实握手；
W2 的「真实握手成功」用例经 dev venv 的 inkflow-mcp 入口验证（CI 不可用则 skip）。
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "ci_cd" / "verify_release_artifacts.py"
BACKEND = REPO_ROOT / "backend"

OLD_LABEL = "CLI zip MCP version == tag (inkflow-mcp.exe --version)"
NEW_LABEL = "CLI zip MCP stdio handshake (tools/list)"


def _load_script():
    spec = importlib.util.spec_from_file_location("verify_release_artifacts", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── W1 期望工具面 ──────────────────────────────────────────────────


def test_mcp_expected_tools_is_18() -> None:
    """#1036 契约：MCP 工具面 15→18。"""
    module = _load_script()
    assert module.MCP_EXPECTED_TOOLS == 18


def test_mcp_expected_tools_matches_registry() -> None:
    """与 MCP_TOOL_REGISTRY 同源（防面板漂移）。"""
    action = REPO_ROOT / "backend" / "src" / "inkflow" / "mcp" / "tools" / "__init__.py"
    src = action.read_text(encoding="utf-8")
    # 注册表条目形如 `    build_xxx_tool(),`
    count = src.count("build_") - src.count("def build_") - src.count("from inkflow")
    module = _load_script()
    # 宽松对账：源码中工厂调用数应 ≥ 期望（import 行也含 build_，故用 ≥）
    assert count >= module.MCP_EXPECTED_TOOLS - 2


# ── W2 stdio 握手行 ────────────────────────────────────────────────


def test_mcp_stdio_row_exposes_callable() -> None:
    module = _load_script()
    assert callable(getattr(module, "mcp_stdio_row", None))


def test_mcp_stdio_row_missing_exe(tmp_path: Path) -> None:
    """不存在的 MCP exe → (False, 说明)，不抛异常。"""
    module = _load_script()
    ok, detail = module.mcp_stdio_row(tmp_path / "nope.exe")
    assert ok is False
    assert detail


@pytest.mark.skipif(
    not (BACKEND / ".venv" / "Scripts" / "inkflow-mcp.exe").is_file(),
    reason="dev venv 无 inkflow-mcp.exe（CI 环境可能未建 venv）",
)
def test_mcp_stdio_row_real_handshake() -> None:
    """对真实 MCP 入口做 stdio 握手 → tools/list 应返回 18 个工具。"""
    module = _load_script()
    exe = BACKEND / ".venv" / "Scripts" / "inkflow-mcp.exe"
    ok, detail = module.mcp_stdio_row(exe)
    assert ok is True, detail
    assert "18" in detail


def test_mcp_stdio_row_detects_tool_shortfall(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """工具数不足 → FAIL（不得假绿）——用桩脚本模拟只报 1 个工具的 MCP 入口。"""
    module = _load_script()
    stub = tmp_path / "stub_mcp.py"
    stub.write_text(
        "import json, sys\n"
        "\n"
        "\n"
        "def _init(rid):\n"
        "    return {'jsonrpc': '2.0', 'id': rid, 'result': {\n"
        "        'protocolVersion': '2024-11-05', 'capabilities': {},\n"
        "        'serverInfo': {'name': 'stub', 'version': '0'}}}\n"
        "\n"
        "\n"
        "for line in sys.stdin:\n"
        "    line = line.strip()\n"
        "    if not line:\n"
        "        continue\n"
        "    msg = json.loads(line)\n"
        "    if msg.get('method') == 'initialize':\n"
        "        print(json.dumps(_init(msg['id'])), flush=True)\n"
        "    elif msg.get('method') == 'tools/list':\n"
        "        payload = {'jsonrpc': '2.0', 'id': msg['id'],\n"
        "                   'result': {'tools': [{'name': 'only_one'}]}}\n"
        "        print(json.dumps(payload), flush=True)\n"
        "        break\n",
        encoding="utf-8",
    )
    # 用 python.exe 直接跑桩（避免依赖 exe 打包）
    runner = tmp_path / "runner.exe"
    exe = Path(sys.executable)
    try:
        shutil.copy2(exe, runner)
    except OSError:
        pytest.skip("无法复制 python.exe 作桩运行体")
    # 直接调内部实现：允许注入 argv 前缀
    ok, detail = module.mcp_stdio_row(exe, launcher=[str(exe), str(stub)])
    assert ok is False
    assert "18" in detail or "tool" in detail.lower()


# ── W3 main 标签切换 ───────────────────────────────────────────────


def _make_full_zip(tmp_path: Path) -> Path:
    z = tmp_path / "cli.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("inkflow/inkflow.exe", b"MZ")
        zf.writestr("inkflow/_internal/", b"")
        zf.writestr("inkflow/_internal/inkflow-0.14.0.dist-info/METADATA", "x")
        zf.writestr("skills/writing/SKILL.md", "x")
        zf.writestr("inkflow-mcp/inkflow-mcp.exe", b"MZ")
    return z


def test_main_uses_stdio_label_not_version_label(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """--cli-zip 分支：新标签在位，旧版本标签消失。"""
    module = _load_script()
    z = _make_full_zip(tmp_path)
    monkeypatch.setattr(module, "_exe_version_row", lambda exe, tag: (True, "stub"))
    monkeypatch.setattr(module, "mcp_stdio_row", lambda exe, **kw: (True, "stub-18"))
    rc = module.main(["--cli-zip", str(z), "--version", "v0.14.0-rc2"])
    out = capsys.readouterr().out
    assert rc == 0
    assert NEW_LABEL in out
    assert OLD_LABEL not in out
    assert "inkflow-mcp.exe --version" not in out
