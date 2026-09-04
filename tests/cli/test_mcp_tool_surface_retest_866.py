"""#866 MCP 15 工具系统性复测——间歇性 INTERNAL_ERROR 采样（0.13.0 rc 轨）。

背景：rc3 曾观测 `manage_project action=list` 返回 INTERNAL_ERROR（空 error detail），
08-24 / 08-30 复测恢复，判定为 MCP↔内核 token/数据目录不一致的间歇性隐患。本文件把
「系统性复测」固化为可重跑的采样用例（issue #866 验收）：

1. tools/list → 恰好 15 工具（面完整性）；
2. 15 工具各跑一遍**只读/无外部依赖动作**，每次调用三连发（协议层采样）；
3. `manage_project list` 压力连发 10 次（rc3 缺陷动作的直接复现锚点）；
4. 🔴 核心判据 = **rc3 指纹断言**：任何采样的失败信封不得是
   `code == "INTERNAL_ERROR" 且 message 为空`——复现即 FAIL（按 issue 要求升级为
   bug 修复批），业务性错误（NOT_FOUND / VALIDATION_ERROR / 非空 message 的
   LLM/内核错误）判为链路正常、仅记录不失败。

证据采集：设置环境变量 `INKFLOW_MCP_EVIDENCE_OUT=<path>` 时，session 结束把全部采样
（tool/params/attempt/ok/code/message 摘要）写 JSON 到该路径，供 rc 记录归档；未设置
则仅打印计数摘要。

── 测试约定（镜像 test_cli_mcp.py，spec 自包含原则 #140：基建复制不 import 兄弟文件）──
- 真实内核轨：module-scope fixture 一次拉起 + INKFLOW_DATA_DIR/state_file 隔离 tmp_path。
- 每次 tools/call 新建 stdio 子进程连接（间歇性缺陷可能与进程态相关，新连接=更强采样面）。
- ⚠️ CI 环境跳过（同 test_cli_mcp.py：GitHub Actions 沙箱拉内核秒退；本文件是 rc 复测轨，
  裁判在本地/预发布环境，CI 只保证收集不报错）。
- LLM 依赖动作（write generate / extract reindex 等）在无 key 的 tmp 数据目录会得业务性
  失败信封——判据只咬「空 detail INTERNAL_ERROR」，故无 key 环境可跑且不假红。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from inkflow.infrastructure.kernel import ensure_kernel

if TYPE_CHECKING:
    from mcp.client.stdio import StdioServerParameters

_KERNEL_TIMEOUT = 60.0

#: 全部采样记录（teardown 写证据文件）
_EVIDENCE: list[dict] = []

#: 压力锚点动作连发次数（rc3 直接复现面）
_STRESS_CALLS = 10

#: 每工具协议层连发次数
_ATTEMPTS_PER_TOOL = 3


def _kill_kernel_tree(pid: int) -> None:
    """可靠终止内核进程树（Windows taskkill /T /F；best-effort，已死进程容忍）。"""
    if pid <= 0:
        return
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=15,
        )


def _skip_ci() -> bool:
    """GitHub Actions 沙箱无法拉起真实内核（秒退）→ CI 跳过（同 test_cli_mcp.py）。"""
    return os.environ.get("CI") == "true"


@pytest.fixture(scope="module")
def retest_env(tmp_path_factory):
    """module-scope：隔离环境拉起真实内核 + 种子数据（项目/章节/角色）供各工具引用。

    种子数据经内核 REST（httpx）直建——MCP 工具调用本身是被测面，前置数据不走被测面，
    避免「准备数据失败」与「被测链路失败」混淆根因。
    """
    import httpx

    state_file = tmp_path_factory.mktemp("kernel") / "kernel.json"
    child_data_dir = tmp_path_factory.mktemp("kernel-data")
    prev_data_dir = os.environ.get("INKFLOW_DATA_DIR")
    os.environ["INKFLOW_DATA_DIR"] = str(child_data_dir)
    handle = None
    try:
        handle = asyncio.run(
            ensure_kernel(state_file=state_file, timeout=_KERNEL_TIMEOUT)
        )
        base = f"http://127.0.0.1:{handle.port}"
        headers = {"X-InkFlow-Token": handle.token}
        with httpx.Client(base_url=base, headers=headers, timeout=30.0) as client:
            r = client.post(
                "/api/v1/projects",
                json={"name": "866复测种子", "tags": ["其他"], "language": "zh-CN"},
            )
            r.raise_for_status()
            project_id = r.json()["id"]
            r = client.post(
                f"/api/v1/projects/{project_id}/chapters",
                json={"title": "第一章", "content": "夜色渐深，山门灯火未熄。" * 30},
            )
            r.raise_for_status()
            chapter_id = r.json()["id"]
            r = client.post(
                f"/api/v1/projects/{project_id}/characters",
                json={"name": "复测角色", "extra": {"role_rank": "major"}},
            )
            r.raise_for_status()
            character_id = r.json()["id"]
        yield SimpleNamespace(
            handle=handle,
            state_file=state_file,
            data_dir=child_data_dir,
            project_id=project_id,
            chapter_id=chapter_id,
            character_id=character_id,
        )
    finally:
        if handle is not None:
            _kill_kernel_tree(handle.pid)
        if prev_data_dir is None:
            os.environ.pop("INKFLOW_DATA_DIR", None)
        else:
            os.environ["INKFLOW_DATA_DIR"] = prev_data_dir
        _write_evidence()


def _write_evidence() -> None:
    """teardown：有 INKFLOW_MCP_EVIDENCE_OUT 时落证据 JSON，否则打印摘要。"""
    if not _EVIDENCE:
        return
    summary: dict[str, int] = {}
    for rec in _EVIDENCE:
        key = f"{rec['tool']}:{'ok' if rec['ok'] else rec['code'] or 'ERR'}"
        summary[key] = summary.get(key, 0) + 1
    out = os.environ.get("INKFLOW_MCP_EVIDENCE_OUT")
    if out:
        payload = {
            "issue": "#866",
            "collected_at": datetime.now(UTC).isoformat(),
            "samples": len(_EVIDENCE),
            "summary": summary,
            "evidence": _EVIDENCE,
        }
        with open(out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"\n[#866 mcp-retest] samples={len(_EVIDENCE)} summary={summary} evidence_out={out}")


def _server_params(env: SimpleNamespace) -> StdioServerParameters:
    """mcp server 子进程启动参数（StdioServerParameters 对象位参，mcp 2.0 契约）。"""
    from mcp.client.stdio import StdioServerParameters

    child_env = os.environ.copy()
    child_env["INKFLOW_DATA_DIR"] = str(env.data_dir)
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "inkflow.mcp"],
        env=child_env,
    )


async def _call_tool(env: SimpleNamespace, tool: str, params: dict) -> dict:
    """新开 stdio 连接调用一次工具，返回信封 dict。

    ℹ️ 业务失败信封在 MCP 协议层带 is_error=True（如 extract retrieve 无 embedding
    key 时返回 INTERNAL_ERROR「向量检索服务不可用」）——**非** rc3 缺陷（其指纹是
    INTERNAL_ERROR 且 message 为空）。复测判据在信封层（_assert_rc3_signature_free），
    故本函数不 assert is_error，仅把它记进证据供归档分析。协议层崩溃（无 text/非法
    JSON）仍会经 json.loads 抛错=用例失败。
    """
    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client

    async with (
        stdio_client(_server_params(env)) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        result = await session.call_tool(tool, params)
    assert result.content and isinstance(result.content[0].text, str), (
        f"{tool} 协议层无文本内容: {result!r}"
    )
    envelope = json.loads(result.content[0].text)
    _EVIDENCE.append(
        {
            "at": datetime.now(UTC).isoformat(),
            "tool": tool,
            "params": params,
            "ok": envelope.get("ok"),
            "is_error": result.is_error,
            "code": (envelope.get("error") or {}).get("code"),
            "message": ((envelope.get("error") or {}).get("message") or "")[:200],
        }
    )
    return envelope


def _assert_rc3_signature_free(envelope: dict, tool: str, params: dict) -> None:
    """🔴 #866 判据：失败信封不得命中 rc3 指纹（INTERNAL_ERROR 且 message 为空）。"""
    if envelope.get("ok") is True:
        return
    err = envelope.get("error") or {}
    code = err.get("code")
    message = (err.get("message") or "").strip()
    assert not (code == "INTERNAL_ERROR" and not message), (
        f"{tool} params={params} 复现 rc3 缺陷指纹：INTERNAL_ERROR 空 detail——"
        "按 issue 要求升级为 bug 修复批（附 mcp-retest evidence JSON）"
    )


def _tool_call_matrix(env: SimpleNamespace) -> list[tuple[str, dict]]:
    """15 工具 → 只读/无外部依赖动作矩阵（与 MCP_TOOL_REGISTRY 一一对应）。"""
    pid = env.project_id
    export_out = str(env.data_dir / "retest-export.txt")
    return [
        ("manage_project", {"action": "list"}),
        ("manage_chapter", {"action": "list", "project_id": pid}),
        ("manage_character", {"action": "list", "project_id": pid}),
        ("manage_relation", {"action": "list", "character_id": env.character_id}),
        ("manage_timeline", {"action": "list", "project_id": pid}),
        ("manage_world", {"action": "list", "project_id": pid}),
        ("manage_outline", {"action": "list", "project_id": pid}),
        ("manage_foreshadowing", {"action": "list", "project_id": pid}),
        ("manage_session", {"action": "list"}),
        ("audit", {"action": "project", "project_id": pid}),
        ("extract", {"action": "retrieve", "project_id": pid, "query": "山门"}),
        ("export", {"action": "export", "project_id": pid, "format": "txt",
                    "output_path": export_out}),
        ("search", {"action": "search", "project_id": pid, "query": "夜色"}),
        ("tool_search", {"action": "list"}),
        # write.generate 无 key 环境=业务性失败信封（只记录不失败，见模块 docstring）
        (
            "write",
            {"action": "generate", "project_id": pid, "chapter_id": env.chapter_id,
             "outline": "复测占位大纲"},
        ),
    ]


@pytest.mark.skipif(_skip_ci(), reason="GitHub Actions 沙箱拉内核秒退；#866 为本地 rc 复测轨")
class TestMcpToolSurfaceRetest866:
    """0.13.0 里程碑系统性复测（tools/list + 15 工具×3 + manage_project list×10）。"""

    @pytest.mark.asyncio
    async def test_tools_list_exactly_15(self, retest_env: SimpleNamespace) -> None:
        """tools/list 面完整性：恰好 15 个工具（F20 契约基线）。"""
        from mcp.client.session import ClientSession
        from mcp.client.stdio import stdio_client

        async with (
            stdio_client(_server_params(retest_env)) as (r, w),
            ClientSession(r, w) as session,
        ):
            init = await session.initialize()
            assert init.server_info.name == "inkflow"
            result = await session.list_tools()
        names = sorted(t.name for t in result.tools)
        assert len(names) == 15, names

    @pytest.mark.asyncio
    async def test_all_15_tools_sampled_rc3_free(self, retest_env: SimpleNamespace) -> None:
        """15 工具各三连发：任何一次失败都不得命中 rc3 指纹（空 detail INTERNAL_ERROR）。"""
        matrix = _tool_call_matrix(retest_env)
        assert len(matrix) == 15
        for tool, params in matrix:
            for attempt in range(_ATTEMPTS_PER_TOOL):
                envelope = await _call_tool(retest_env, tool, params)
                _assert_rc3_signature_free(envelope, tool, params | {"attempt": attempt})

    @pytest.mark.asyncio
    async def test_manage_project_list_stress_rc3_free(
        self, retest_env: SimpleNamespace
    ) -> None:
        """rc3 缺陷动作直接复现锚点：manage_project list 连发 10 次全不命中空 INTERNAL_ERROR。"""
        params = {"action": "list"}
        for _ in range(_STRESS_CALLS):
            envelope = await _call_tool(retest_env, "manage_project", params)
            _assert_rc3_signature_free(envelope, "manage_project(stress)", params)
        # 至少首尾两次必须成功（连发全业务失败=数据链路问题，另案）
        ok_count = sum(1 for rec in _EVIDENCE if rec["tool"] == "manage_project" and rec["ok"])
        assert ok_count >= 2, "manage_project list 连发无一成功——内核数据链路异常"
