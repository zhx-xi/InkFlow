"""F50 MCP 分发引导 — /api/v1/mcp/info 自发现端点契约（Issue #563，RED 阶段测试契约）。

覆盖（spec f50-mcp-guidance §3/§9）：
- GET /api/v1/mcp/info → 200，字段 {client_path, version, config_template}；
- version 动态读 inkflow.__version__（不得硬编码；patch 注入验证）；
- config_template 三宿主键 claude/cursor/hermes，各含 mcpServers.inkflow.command == client_path；
- locate_mcp_client 纯函数三形态（NSIS/便携 kernel+mcp 子目录；dev venv Scripts/onedir 兄弟；
  CLI zip 兄弟目录）按序取第一个存在项；未命中回退期望路径恒非空；
- build_mcp_info 端到端（patch locate 返回固定路径 → contract 一致性）。

── RED 形态说明 ─────────────────────────────────────────────────
inkflow.mcp.info 模块整个不存在 + inkflow.api.routers.mcp 不存在 →
顶部 import 收集期 ModuleNotFoundError（exit 2，整模块 RED 首选形态）。
GREEN 落地（CREATE info.py + routers/mcp.py + MODIFY api/app.py 注册）后整文件自动转绿。

── 测试约定 ─────────────────────────────────────────────────────
- TestClient(app)：app.py 注册 mcp router 后 /api/v1/mcp/info 可达（RED 阶段 404）。
- patch 均用 with 上下文管理器（避免 decorator 参数被 pytest 当 fixture——
  @patch.object(..., new="9.9.9") 因 new 为字面量不注入 mock 参数，实测 fixture not found）。
- locate_mcp_client 用 monkeypatch 注入 sys.executable + tmp_path 造发行结构
  （.touch() 前必须 mkdir 父目录，Path.touch 不建父目录）。
- pytest-asyncio 1.x STRICT：async 用例显式 @pytest.mark.asyncio（本文件纯 sync，无需）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import inkflow
from inkflow.api.app import app
from inkflow.mcp.info import build_mcp_info, locate_mcp_client

client = TestClient(app)

FAKE_CLIENT = r"C:\fake\resources\kernel\mcp\inkflow-mcp.exe"


class TestMcpInfoEndpoint:
    """GET /api/v1/mcp/info 契约（spec §3.2）。"""

    def test_returns_contract_shape(self) -> None:
        """200 + 三字段；version 动态；config_template 三宿主键 + command 与 client_path 一致。"""
        with (
            patch("inkflow.mcp.info.locate_mcp_client", return_value=FAKE_CLIENT),
            patch.object(inkflow, "__version__", "9.9.9"),
        ):
            resp = client.get("/api/v1/mcp/info")
        assert resp.status_code == 200
        data = resp.json()
        assert set(data) == {"client_path", "version", "config_template"}
        assert data["client_path"] == FAKE_CLIENT
        assert data["version"] == "9.9.9"  # 动态读 inkflow.__version__（patch 注入）
        assert set(data["config_template"]) == {"claude", "cursor", "hermes"}
        for host in ("claude", "cursor", "hermes"):
            servers = data["config_template"][host]["mcpServers"]["inkflow"]
            assert servers["command"] == FAKE_CLIENT

    def test_version_is_dynamic_not_hardcoded(self) -> None:
        """硬编码校验：patch __version__ 后响应 version 必须跟随变化（防写死版本号）。"""
        with (
            patch("inkflow.mcp.info.locate_mcp_client", return_value=FAKE_CLIENT),
            patch.object(inkflow, "__version__", "0.0.0"),
        ):
            resp = client.get("/api/v1/mcp/info")
        assert resp.json()["version"] == "0.0.0"


class TestLocateMcpClient:
    """locate_mcp_client 三形态解析（spec §3.4）。"""

    def _set_executable(self, monkeypatch, root: Path, name: str) -> None:
        """把 sys.executable 指向 root/name（造发行布局用）。"""
        exe = root / name
        exe.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(sys, "executable", str(exe))

    def test_nsis_install_layout_prefers_mcp_subdir(self, monkeypatch, tmp_path: Path) -> None:
        """NSIS/便携：resources/kernel/inkflow.exe → 首选 resources/kernel/mcp/inkflow-mcp.exe。"""
        kernel_dir = tmp_path / "resources" / "kernel"
        mcp_dir = kernel_dir / "mcp"
        kernel_dir.mkdir(parents=True, exist_ok=True)
        mcp_dir.mkdir(parents=True, exist_ok=True)
        (kernel_dir / "inkflow.exe").touch()
        (mcp_dir / "inkflow-mcp.exe").touch()
        self._set_executable(monkeypatch, kernel_dir, "inkflow.exe")
        assert locate_mcp_client() == str(mcp_dir / "inkflow-mcp.exe")

    def test_dev_venv_scripts_layout(self, monkeypatch, tmp_path: Path) -> None:
        """dev venv：python.exe 旁 Scripts/inkflow-mcp.exe（候选 2）。"""
        scripts_dir = tmp_path / "Scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        (scripts_dir / "python.exe").touch()
        (scripts_dir / "inkflow-mcp.exe").touch()
        self._set_executable(monkeypatch, scripts_dir, "python.exe")
        assert locate_mcp_client() == str(scripts_dir / "inkflow-mcp.exe")

    def test_cli_zip_sibling_dir_layout(self, monkeypatch, tmp_path: Path) -> None:
        """CLI zip：inkflow/inkflow.exe 与 inkflow-mcp/inkflow-mcp.exe 兄弟目录（候选 3）。"""
        kernel_dir = tmp_path / "inkflow"
        mcp_dir = tmp_path / "inkflow-mcp"
        kernel_dir.mkdir(parents=True, exist_ok=True)
        mcp_dir.mkdir(parents=True, exist_ok=True)
        (kernel_dir / "inkflow.exe").touch()
        (mcp_dir / "inkflow-mcp.exe").touch()
        self._set_executable(monkeypatch, kernel_dir, "inkflow.exe")
        assert locate_mcp_client() == str(mcp_dir / "inkflow-mcp.exe")

    def test_missing_binary_falls_back_to_expectation(self, monkeypatch, tmp_path: Path) -> None:
        """未命中任何候选 → 回退候选 1 期望路径（恒非空）。"""
        kernel_dir = tmp_path / "resources" / "kernel"
        kernel_dir.mkdir(parents=True, exist_ok=True)
        (kernel_dir / "inkflow.exe").touch()  # 有 kernel 但无 mcp 子目录
        self._set_executable(monkeypatch, kernel_dir, "inkflow.exe")
        result = locate_mcp_client()
        assert result  # 恒非空
        assert result.endswith("mcp\\inkflow-mcp.exe") or result.endswith("mcp/inkflow-mcp.exe")


class TestBuildMcpInfo:
    """build_mcp_info 端到端一致性（spec §3.2/§9）。"""

    def test_build_mcp_info_contract(self) -> None:
        with (
            patch("inkflow.mcp.info.locate_mcp_client", return_value=FAKE_CLIENT),
            patch.object(inkflow, "__version__", "1.2.3"),
        ):
            info = build_mcp_info()
        assert info["client_path"] == FAKE_CLIENT
        assert info["version"] == "1.2.3"
        assert set(info["config_template"]) == {"claude", "cursor", "hermes"}
        for cfg in info["config_template"].values():
            assert cfg["mcpServers"]["inkflow"]["command"] == FAKE_CLIENT
