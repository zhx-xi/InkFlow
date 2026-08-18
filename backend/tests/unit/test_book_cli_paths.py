"""RED 契约（#458）：book CLI 命令组请求路径不得带 /api/v1 双前缀。

缺陷背景（0.10.0-rc1 实证 2026-08-18）：book_cmd.py 全部 11 处路径写
`/api/v1/agent/books/...`，而 InkFlowHTTPClient base_url 已含 /api/v1
（client.py L65）→ httpx 拼出 `/api/v1/api/v1/...` → 404 `? Not Found`。
HTTP 直调同端点 201 正常 = CLI 客户端路径问题，非后端路由缺失。

本契约：对 book_cmd 每个命令，mock InkFlowHTTPClient 断言请求路径
**以 /agent/books 开头**（不含 /api/v1 前缀）。修复后全部 PASS。

mock 策略（镜像 test_http_client.py §7）：patch 命令模块命名空间里的
InkFlowHTTPClient 类（`inkflow.cli.commands.book_cmd.InkFlowHTTPClient`），
返回 AsyncMock 实例；_run_ctx 包装 asyncio.run，直接 await client 调用。

⚠️ RED 期形态：当前实现路径带 /api/v1 → 本文件断言 FAIL（干净 RED）。
"""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _book_cmd():
    """执行期惰性 import（镜像 test_skills_parser.py sp fixture 模式）。

    不能顶部 import：tests/unit 套件守护契约
    test_http_client.py::TestImportSurface::test_no_cli_import_on_http_import
    断言 'inkflow.cli' not in sys.modules——顶部 import 在收集期载入 inkflow.cli
    会破坏该守护（CI unit-backend 4069 passed + 1 failed 实证）。
    """
    return importlib.import_module("inkflow.cli.commands.book_cmd")


def _patch_client():
    """patch book_cmd.InkFlowHTTPClient → AsyncMock 实例，返回 (patcher, mock_client)。

    mock_client 为 AsyncMock：async with client 需要 __aenter__/__aexit__；
    client.post/get 返回 dict（AsyncMock 自动）。kernel handle 由 ensure_kernel
    mock 返回 MagicMock（port/token 字段访问不炸）。
    """
    book_cmd = _book_cmd()
    patcher = patch.object(book_cmd, "InkFlowHTTPClient")
    mock_cls = patcher.start()
    mock_inst = AsyncMock()
    # async with InkFlowHTTPClient(handle) as client 需要 __aenter__/__aexit__
    mock_inst.__aenter__.return_value = mock_inst
    mock_inst.__aexit__ = AsyncMock(return_value=None)
    mock_inst.post = AsyncMock(return_value={"session_id": "s-1", "round": 1, "questions": []})
    mock_inst.get = AsyncMock(return_value={"run_id": "r-1", "status": "completed"})
    mock_inst.delete = AsyncMock(return_value={"deleted": True})
    mock_cls.return_value = mock_inst
    return patcher, mock_inst


def _patch_kernel():
    """patch ensure_kernel → 假 handle（KernelHandle 鸭子：port/token/pid/version）。"""
    book_cmd = _book_cmd()
    patcher = patch.object(book_cmd, "ensure_kernel")
    mock_handle = MagicMock()
    mock_handle.port = 38291
    mock_handle.token = "test-token-abc123"
    mock_handle.pid = 12345
    mock_handle.version = "0.10.0rc1"
    mock_handle.reused = False
    mock_handle.started_at = "2026-08-18T00:00:00Z"
    patcher.start().return_value = mock_handle
    return patcher


@pytest.fixture(autouse=True)
def _no_real_kernel():
    """每个用例隔离 patch；结束恢复。"""
    patchers = []
    yield
    for p in patchers:
        p.stop()


def _call(cmd_fn, *args, **kwargs):
    """直接调用命令函数（薄层：仅参数解析 + client 调用），CLI 对象不参与。"""
    ctx = MagicMock()
    ctx.obj = MagicMock()
    ctx.obj.json_output = False
    cmd_fn(ctx, *args, **kwargs)


def test_plan_start_path_no_api_v1_prefix():
    """plan start 请求路径 = /agent/books/planner（不含 /api/v1）。"""
    patcher, mock_inst = _patch_client()
    patcher2 = _patch_kernel()
    patchers = [patcher, patcher2]
    try:
        _call(_book_cmd().plan_start, "测试故事", project_id="00000000-0000-0000-0000-000000000001")
        path = mock_inst.post.await_args.args[0]
        msg = f"plan start path={path!r} 必须相对 base_url（不含 /api/v1）"
        assert path == "/agent/books/planner", msg
        assert "/api/v1" not in path, f"plan start path={path!r} 含 /api/v1 双前缀"
    finally:
        for p in patchers:
            p.stop()


def test_plan_respond_path_no_api_v1_prefix():
    patcher, mock_inst = _patch_client()
    patcher2 = _patch_kernel()
    patchers = [patcher, patcher2]
    try:
        _call(_book_cmd().plan_respond, "sess-1", "主角是林晚")
        path = mock_inst.post.await_args.args[0]
        assert path == "/agent/books/planner/sess-1/respond", f"path={path!r}"
        assert "/api/v1" not in path
    finally:
        for p in patchers:
            p.stop()


def test_plan_auto_path_no_api_v1_prefix():
    patcher, mock_inst = _patch_client()
    patcher2 = _patch_kernel()
    patchers = [patcher, patcher2]
    try:
        _call(
            _book_cmd().plan_auto, "一句话故事", project_id="00000000-0000-0000-0000-000000000001"
        )
        # auto 内部两次 post：第一次 /planner，第二次 /planner/{sid}/respond
        calls = mock_inst.post.await_args_list
        assert len(calls) == 2
        for call in calls:
            path = call.args[0]
            assert "/api/v1" not in path, f"auto path={path!r} 含 /api/v1 双前缀"
        assert calls[0].args[0] == "/agent/books/planner"
        assert calls[1].args[0] == "/agent/books/planner/s-1/respond"
    finally:
        for p in patchers:
            p.stop()


def test_plan_show_path_no_api_v1_prefix():
    patcher, mock_inst = _patch_client()
    patcher2 = _patch_kernel()
    patchers = [patcher, patcher2]
    try:
        _call(_book_cmd().plan_show, "sess-1")
        path = mock_inst.get.await_args.args[0]
        assert path == "/agent/books/planner/sess-1", f"path={path!r}"
        assert "/api/v1" not in path
    finally:
        for p in patchers:
            p.stop()


def test_plan_run_path_no_api_v1_prefix():
    patcher, mock_inst = _patch_client()
    patcher2 = _patch_kernel()
    patchers = [patcher, patcher2]
    try:
        _call(_book_cmd().plan_run, "plan-1")
        path = mock_inst.post.await_args.args[0]
        assert path == "/agent/books/runs", f"path={path!r}"
        assert "/api/v1" not in path
    finally:
        for p in patchers:
            p.stop()


def test_book_run_path_no_api_v1_prefix():
    patcher, mock_inst = _patch_client()
    patcher2 = _patch_kernel()
    patchers = [patcher, patcher2]
    try:
        _call(_book_cmd().book_run, "plan-1", limits=None)
        path = mock_inst.post.await_args.args[0]
        assert path == "/agent/books/runs", f"path={path!r}"
        assert "/api/v1" not in path
    finally:
        for p in patchers:
            p.stop()


def test_book_status_path_no_api_v1_prefix():
    patcher, mock_inst = _patch_client()
    patcher2 = _patch_kernel()
    patchers = [patcher, patcher2]
    try:
        _call(_book_cmd().book_status, "run-1")
        path = mock_inst.get.await_args.args[0]
        assert path == "/agent/books/runs/run-1", f"path={path!r}"
        assert "/api/v1" not in path
    finally:
        for p in patchers:
            p.stop()


def test_book_confirm_path_no_api_v1_prefix():
    patcher, mock_inst = _patch_client()
    patcher2 = _patch_kernel()
    patchers = [patcher, patcher2]
    try:
        _call(_book_cmd().book_confirm, "run-1")
        path = mock_inst.post.await_args.args[0]
        assert path == "/agent/books/runs/run-1/confirm", f"path={path!r}"
        assert "/api/v1" not in path
    finally:
        for p in patchers:
            p.stop()


def test_book_intervene_path_no_api_v1_prefix():
    patcher, mock_inst = _patch_client()
    patcher2 = _patch_kernel()
    patchers = [patcher, patcher2]
    try:
        _call(_book_cmd().book_intervene, "run-1", action="pause")
        path = mock_inst.post.await_args.args[0]
        assert path == "/agent/books/runs/run-1/intervene", f"path={path!r}"
        assert "/api/v1" not in path
    finally:
        for p in patchers:
            p.stop()


def test_book_summary_path_no_api_v1_prefix():
    patcher, mock_inst = _patch_client()
    patcher2 = _patch_kernel()
    patchers = [patcher, patcher2]
    try:
        _call(_book_cmd().book_summary, "run-1", export=None)
        path = mock_inst.get.await_args.args[0]
        assert path == "/agent/books/runs/run-1/summary", f"path={path!r}"
        assert "/api/v1" not in path
    finally:
        for p in patchers:
            p.stop()
