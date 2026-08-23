"""F50 MCP 分发引导 — MCP 自发现信息构造（Issue #563）。

纯函数，无 I/O 副作用；供 GET /api/v1/mcp/info 端点装配（spec f50 §3）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import inkflow


def locate_mcp_client() -> str:
    """定位 inkflow-mcp 可执行文件（spec f50 §3.4），恒返回非空 str。

    按序取第一个存在的候选（均以 sys.executable 为基准）：
    1. 同目录 mcp/inkflow-mcp.exe —— NSIS 安装版/便携 zip（resources\\kernel\\mcp\\）
    2. 同目录 inkflow-mcp.exe —— dev venv Scripts\\ console script / onedir 兄弟
    3. 父目录 inkflow-mcp/inkflow-mcp.exe —— CLI zip（与 inkflow/ 兄弟目录）
    未命中 → 回退候选 1 的期望路径，保证恒非空。
    """
    exe_dir = Path(sys.executable).parent
    candidates = [
        exe_dir / "mcp" / "inkflow-mcp.exe",
        exe_dir / "inkflow-mcp.exe",
        exe_dir.parent / "inkflow-mcp" / "inkflow-mcp.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return str(candidates[0])


def build_mcp_info() -> dict:
    """构造 GET /api/v1/mcp/info 响应（spec f50 §3.2）。

    client_path 由 locate_mcp_client() 动态解析；version 运行时读
    inkflow.__version__（不硬编码、模块级不绑定，测试经 patch 注入验证）。
    """
    client_path = locate_mcp_client()
    version = inkflow.__version__
    config_template = {
        host: {"mcpServers": {"inkflow": {"command": client_path}}}
        for host in ("claude", "cursor", "hermes")
    }
    return {
        "client_path": client_path,
        "version": version,
        "config_template": config_template,
    }
