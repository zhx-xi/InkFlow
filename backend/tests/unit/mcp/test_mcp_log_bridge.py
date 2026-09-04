"""#924 MCP 进程日志桥接 — log_bridge 单元契约（RED 测试）。

缺陷背景（issue #924）
---------------------
MCP 工具实现运行于 inkflow-mcp 薄客户端**进程**，@instrument(caller_type="mcp")
埋点走 loguru 默认 sink=stderr，不进内核 StructuredLogStore → GUI 日志页
「内核」分类 MCP 操作恒空（审计盲区）。本文件锁定修复契约（issue 方向 A：
薄客户端 ingest 转发，复用 #888 POST /api/v1/logs 桥接端点）。

GREEN 实现契约（模块 inkflow.mcp.log_bridge，CREATE）
------------------------------------------------------
1. ``get_forwarder() -> McpLogForwarder``：进程级单例，公开属性：
   - ``pending: collections.deque[dict]``（有界 maxlen=200，满则丢最旧，静默）；
   - ``client: httpx.Client | None``（attach 产物）。
   方法：
   - ``attach(port: int, token: str) -> None``：端点未变 → 复用既有 client；
     变化 → 关闭旧 client（best-effort suppress）→ ``_make_client(port, token)``
     重建。token 仅存于 client 请求头，绝不进 pending/body（F20 §6.3/§271）。
   - ``sink(message) -> None``：loguru sink 回调。record["extra"] 无
     caller_type → 忽略；有 → 构建 LogRecordInput 形状 body dict 入 pending。
     level 归一：loguru "WARNING" → "WARN"（对齐 core/log._norm_sink_level）。
     全程 try/except 静默（日志故障绝不上抛业务，contract-496 §1 同语义）。
   - ``flush() -> None``：逐条 ``client.post("/logs", json=body, timeout=5.0)``；
     client 为 None → no-op；单条异常 → 丢弃该条继续（审计尽力而为）。成功/失败
     都从 pending 消费掉。

2. ``_make_client(port: int, token: str) -> httpx.Client``：模块级工厂缝
   （测试 monkeypatch 点）。生产实现 =
   ``httpx.Client(base_url=f"http://127.0.0.1:{port}/api/v1",
                  headers={"X-InkFlow-Token": token}, timeout=5.0)``。

3. ``mcp_log_sink()``：contextmanager（main() 与测试使用），进入时：
   a. ``logger.add(forwarder.sink, level="INFO",
      filter=lambda record: "caller_type" in record["extra"])``
      ——只转 INFO+（DEBUG start/done 不桥接；口径与内核 api 面一致）；
   b. 包装 ``inkflow.infrastructure.kernel.ensure_kernel`` 模块属性：
      await 原函数成功 → ``forwarder.attach(handle.port, handle.token)`` →
      原样返回 handle；异常透传（不 attach）。
      ——F20 §6.3 硬约束：token 只出自 ensure_kernel 返回的 KernelHandle，
      MCP 层禁直读 kernel.json。零额外探测（复用工具调用自身的 ensure）。
   退出时：最终 flush → 还原 ensure_kernel 属性 → logger.remove(sink token)
   → 关闭 client（best-effort）。可重入保护：嵌套/重复进入不叠加（幂等）。

GREEN 实现契约（inkflow.mcp.server.call_tool_result 扩展，MODIFY）
------------------------------------------------------------------
4. 每次**已知工具**调用在 func 返回后 emit 一条审计 checkpoint（经
   log_structured → 桥接 sink → POST /logs）：
   - level="INFO"（信封 ok=True）/ "WARN"（ok=False，含 UNKNOWN_TOOL 路径）；
   - caller_type="mcp"、caller_name="inkflow-mcp"（进程身份，区别于内核 api）；
   - event=工具名（如 "manage_project"）；
   - message_key="log.event.mcp_tool_call"（须登记 i18n zh/en 目录，含 {tool} 占位符）；
   - params 白名单 = {"tool": 工具名, "action": str(arguments.get("action")) 或 None,
     "project_id": str(arguments.get("project_id")) 或 None}
     ——🔴 原始 arguments 一律不落（正文/敏感载荷防泄漏）；
   - error_code=信封 error.code（仅失败时）；duration_ms=func 调用耗时；
   - project_id 顶层字段：arguments["project_id"] 为纯数字串 → int；
     UUID 串 → 顶层 None（值保留在 params）。
   未知工具路径同样 emit（WARN + UNKNOWN_TOOL，尽力记录尝试痕迹）。
5. call_tool_result 的 finally 中 ``await anyio.to_thread.run_sync(
   get_forwarder().flush)``——桥接失败对信封零影响。
6. main() 以 ``with mcp_log_sink():`` 包裹 stdio 会话主体。stdout 纪律不变：
   桥接走 stderr 之外的 HTTP 通道，loguru 新增 sink 为函数 sink，不写 stdout。

RED 预期（main@242cf37）
------------------------
inkflow.mcp.log_bridge 不存在 → 本文件顶部 import 收集期 ModuleNotFoundError
（exit 2，规则 1c，与 test_mcp_server.py RED 形态一致）。全 FAIL 后才允许 GREEN。

测试约定
--------
- async 用例显式 @pytest.mark.asyncio；fake_env 镜像 test_mcp_server（patch
  kernel_mod.ensure_kernel / http_mod.InkFlowHTTPClient 模块属性，工具 func
  延迟 import 动态生效——🔴 mcp_log_sink 须在 patch 之后进入，wrapper 才能
  捕获 fake）。
- 每用例独立 FakeLogClient（monkeypatch log_bridge._make_client），fixture
  复位单例 pending/client，防跨用例泄漏。
- 禁无断言 smoke：每个用例都有具体 body/level/字段断言。
"""

from __future__ import annotations

import asyncio
import importlib
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Protocol

import pytest
from inkflow.mcp.log_bridge import get_forwarder, mcp_log_sink  # RED: 模块不存在
from inkflow.mcp.server import call_tool_result
from inkflow.mcp.tools import build_mcp_tools

kernel_mod = importlib.import_module("inkflow.infrastructure.kernel")
http_mod = importlib.import_module("inkflow.infrastructure.http")

bridge_mod = importlib.import_module("inkflow.mcp.log_bridge")

_FAKE_TOKEN = "sekret-924"  # 🔴 永不泄漏断言锚（F20 §271）
_MESSAGES_DIR = Path(__file__).resolve().parents[3] / "src" / "inkflow" / "i18n" / "messages"
_PLACEHOLDER = re.compile(r"\{(\w+)[^}]*\}")


class _Poster(Protocol):
    def post(self, path: str, *, json: dict | None = None, timeout: float | None = None) -> object: ...


class FakeLogClient:
    """记录 POST /logs 调用的假转发客户端（log_bridge._make_client 缝）。"""

    def __init__(self) -> None:
        self.posts: list[dict] = []
        self.closed = False

    def post(self, path: str, *, json: dict | None = None, timeout: float | None = None) -> object:
        self.posts.append({"path": path, "json": json, "timeout": timeout})
        return SimpleNamespace(status_code=200)

    def close(self) -> None:
        self.closed = True


class FakeToolClient:
    """工具业务面 fake（镜像 test_mcp_server.FakeClient：async CM + 记录调用）。"""

    def __init__(self, handle: object) -> None:
        self.handle = handle
        self.calls: list[tuple[str, str]] = []
        self.response: object = {"id": "x", "name": "resp"}

    async def __aenter__(self) -> FakeToolClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, path: str, *, params: object = None, json: object = None) -> dict:
        self.calls.append(("GET", path))
        return self.response  # type: ignore[return-value]

    async def post(self, path: str, *, params: object = None, json: object = None, timeout: object = None) -> dict:
        self.calls.append(("POST", path))
        return self.response  # type: ignore[return-value]

    async def patch(self, path: str, *, params: object = None, json: object = None) -> dict:
        self.calls.append(("PATCH", path))
        return self.response  # type: ignore[return-value]

    async def delete(self, path: str, *, params: object = None, json: object = None) -> dict:
        self.calls.append(("DELETE", path))
        return self.response  # type: ignore[return-value]

    async def get_raw(self, path: str, *, params: object = None) -> str:
        self.calls.append(("GET_RAW", path))
        return "raw"


@pytest.fixture
def fake_env(monkeypatch):
    """装配缝（镜像 test_mcp_server.fake_env，token 换防泄漏锚串）。"""
    from unittest.mock import AsyncMock

    fake_ensure = AsyncMock(
        return_value=SimpleNamespace(port=1, token=_FAKE_TOKEN, pid=2, version="0.1.0")
    )
    monkeypatch.setattr(kernel_mod, "ensure_kernel", fake_ensure)
    monkeypatch.setattr(http_mod, "InkFlowHTTPClient", FakeToolClient)
    return SimpleNamespace(fake_ensure=fake_ensure)


@pytest.fixture
def fake_log(monkeypatch):
    """转发缝：_make_client → FakeLogClient + 单例复位（跨用例隔离）。"""
    client = FakeLogClient()
    monkeypatch.setattr(bridge_mod, "_make_client", lambda port, token: client)
    fwd = get_forwarder()
    fwd.pending.clear()
    old = fwd.client
    fwd.client = None
    if old is not None:
        try:
            old.close()
        except Exception:
            pass
    return SimpleNamespace(client=client, forwarder=fwd)


def _last_body(client: FakeLogClient) -> dict:
    assert client.posts, "桥接未发生任何 POST /logs 转发"
    last = client.posts[-1]["json"]
    assert isinstance(last, dict)
    return last


class TestSinkBuffering:
    """契约 §3a：sink 只收 INFO+ 且带 caller_type 的结构化记录。"""

    def test_info_record_buffered(self, fake_log):
        from loguru import logger

        from inkflow.logging import log_structured

        with mcp_log_sink():
            log_structured(
                level="INFO",
                caller_type="mcp",
                caller_name="inkflow-mcp",
                event="manage_project",
                message_key="log.event.mcp_tool_call",
                message="x",
                params={"tool": "manage_project"},
            )
            assert len(fake_log.forwarder.pending) == 1
            body = dict(fake_log.forwarder.pending[0])
        assert body["caller_type"] == "mcp"
        assert body["level"] == "INFO"
        assert body["event"] == "manage_project"
        assert body["message_key"] == "log.event.mcp_tool_call"
        assert body["params"] == {"tool": "manage_project"}
        assert "correlation_id" in body
        logger.remove()
        logger.add(__import__("sys").stderr, level="DEBUG")

    def test_debug_not_buffered(self, fake_log):
        """DEBUG start/done 不桥接（口径与内核 api 面 INFO+ 一致）。"""
        from loguru import logger

        from inkflow.logging import log_structured

        with mcp_log_sink():
            log_structured(
                level="DEBUG",
                caller_type="mcp",
                caller_name="inkflow-mcp",
                event="manage_project",
                message_key="log.call._impl",
                message="started",
            )
            assert list(fake_log.forwarder.pending) == []
        logger.remove()
        logger.add(__import__("sys").stderr, level="DEBUG")

    def test_warning_normalized(self, fake_log):
        from loguru import logger

        from inkflow.logging import log_structured

        with mcp_log_sink():
            log_structured(
                level="WARN",
                caller_type="mcp",
                caller_name="inkflow-mcp",
                event="e",
                message_key="k",
                message="w",
            )
            body = dict(fake_log.forwarder.pending[0])
        assert body["level"] == "WARN"
        logger.remove()
        logger.add(__import__("sys").stderr, level="DEBUG")

    def test_plain_logger_not_buffered(self, fake_log):
        """无 caller_type 的普通日志不进桥接面。"""
        from loguru import logger

        with mcp_log_sink():
            logger.info("not structured")
            assert list(fake_log.forwarder.pending) == []
        logger.remove()
        logger.add(__import__("sys").stderr, level="DEBUG")


class TestFlushDelivery:
    """契约 §1 flush / §2 _make_client / §3b ensure 包装 attach。"""

    @pytest.mark.asyncio
    async def test_ensure_kernel_attaches_and_flush_posts(self, fake_env, fake_log):
        """mcp_log_sink 内 ensure_kernel 成功 → attach → flush 走 POST /logs。"""
        with mcp_log_sink():
            handle = await kernel_mod.ensure_kernel()
            assert handle.token == _FAKE_TOKEN  # 包装透传原返回值
            fwd = fake_log.forwarder
            assert fwd.client is fake_log.client  # wrapper 已 attach
            fwd.pending.append(
                {
                    "level": "INFO",
                    "caller_type": "mcp",
                    "caller_name": "inkflow-mcp",
                    "event": "probe",
                    "message_key": "log.event.mcp_tool_call",
                    "params": {},
                    "correlation_id": "",
                }
            )
            fwd.flush()
        assert list(fwd.pending) == []
        assert len(fake_log.client.posts) == 1
        call = fake_log.client.posts[0]
        assert call["path"] == "/logs"
        assert call["json"]["caller_type"] == "mcp"
        assert call["json"]["event"] == "probe"

    def test_flush_without_client_noop(self, fake_log):
        fake_log.forwarder.pending.append({"level": "INFO", "caller_type": "mcp"})
        fake_log.forwarder.flush()
        assert fake_log.client.posts == []  # 未 attach → no-op 不抛

    def test_flush_posts_survive_client_error(self, fake_log, monkeypatch):
        class Boom(FakeLogClient):
            def post(self, path, *, json=None, timeout=None):  # noqa: ANN001, ANN201
                raise RuntimeError("kernel gone")

        boom = Boom()
        monkeypatch.setattr(bridge_mod, "_make_client", lambda port, token: boom)
        fwd = fake_log.forwarder
        fwd.client = None
        fwd.attach(1, _FAKE_TOKEN)
        fwd.pending.append({"level": "INFO", "caller_type": "mcp", "event": "e1"})
        fwd.pending.append({"level": "INFO", "caller_type": "mcp", "event": "e2"})
        fwd.flush()  # 不抛
        assert list(fwd.pending) == []  # 尽力而为：失败即弃


class TestDispatcherAudit:
    """契约 §4/§5：call_tool_result 审计 checkpoint 端到端（含信封语义）。"""

    @pytest.mark.asyncio
    async def test_success_emits_info_checkpoint(self, fake_env, fake_log):
        with mcp_log_sink():
            result = await call_tool_result(
                build_mcp_tools(), "manage_project", {"action": "list", "search": "x"}
            )
        assert result.is_error is False
        body = _last_body(fake_log.client)
        assert body["caller_type"] == "mcp"
        assert body["level"] == "INFO"
        assert body["event"] == "manage_project"
        assert body["caller_name"] == "inkflow-mcp"
        assert body["message_key"] == "log.event.mcp_tool_call"
        assert body["params"]["tool"] == "manage_project"
        assert body["params"]["action"] == "list"
        assert isinstance(body.get("duration_ms"), (int, float))
        assert body.get("error_code") is None

    @pytest.mark.asyncio
    async def test_http_error_emits_warn_with_code(self, fake_env, fake_log, monkeypatch):
        class FailingClient(FakeToolClient):
            async def get(self, path, *, params=None, json=None) -> dict:
                from inkflow.infrastructure.http import HttpApiError

                raise HttpApiError(status_code=404, detail="不存在")

        monkeypatch.setattr(http_mod, "InkFlowHTTPClient", FailingClient)
        with mcp_log_sink():
            result = await call_tool_result(
                build_mcp_tools(), "manage_project", {"action": "list"}
            )
        assert result.is_error is True
        body = _last_body(fake_log.client)
        assert body["level"] == "WARN"
        assert body["event"] == "manage_project"
        assert body["error_code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_unknown_tool_warn_recorded(self, fake_env, fake_log):
        with mcp_log_sink():
            result = await call_tool_result(build_mcp_tools(), "no_such_tool", {})
        assert result.is_error is True
        body = _last_body(fake_log.client)
        assert body["level"] == "WARN"
        assert body["event"] == "no_such_tool"
        assert body["error_code"] == "UNKNOWN_TOOL"

    @pytest.mark.asyncio
    async def test_arguments_never_leak_into_body(self, fake_env, fake_log):
        """🔴 原始 arguments 不落桥接 body（正文/载荷防泄漏）。"""
        secret_text = "夜色沉沉，山门之内灯火通明，这段正文绝不该出现在审计日志里。"
        with mcp_log_sink():
            await call_tool_result(
                build_mcp_tools(),
                "manage_chapter",
                {"action": "create", "project_id": "42", "title": "第一章", "content": secret_text},
            )
        for post in fake_log.client.posts:
            assert secret_text not in json.dumps(post["json"], ensure_ascii=False)

    @pytest.mark.asyncio
    async def test_numeric_project_id_promoted(self, fake_env, fake_log):
        """project_id 纯数字串 → body 顶层 int（GUI 项目过滤面）；params 保留字符串。"""
        with mcp_log_sink():
            await call_tool_result(
                build_mcp_tools(), "manage_chapter", {"action": "list", "project_id": "42"}
            )
        body = _last_body(fake_log.client)
        assert body.get("project_id") == 42
        assert body["params"]["project_id"] == "42"

    @pytest.mark.asyncio
    async def test_uuid_project_id_stays_in_params(self, fake_env, fake_log):
        with mcp_log_sink():
            await call_tool_result(
                build_mcp_tools(),
                "manage_chapter",
                {"action": "list", "project_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8"},
            )
        body = _last_body(fake_log.client)
        assert body.get("project_id") is None
        assert body["params"]["project_id"] == "6ba7b810-9dad-11d1-80b4-00c04fd430c8"

    @pytest.mark.asyncio
    async def test_token_never_in_forwarded_body(self, fake_env, fake_log):
        with mcp_log_sink():
            await call_tool_result(build_mcp_tools(), "manage_project", {"action": "list"})
            await call_tool_result(build_mcp_tools(), "tool_search", {"action": "list"})
        for post in fake_log.client.posts:
            assert _FAKE_TOKEN not in json.dumps(post["json"], ensure_ascii=False)

    @pytest.mark.asyncio
    async def test_no_sink_installed_forwards_nothing(self, fake_env, fake_log):
        """隔离性：未进入 mcp_log_sink()（非 stdio 会话面）→ 零 HTTP 转发。"""
        await call_tool_result(build_mcp_tools(), "manage_project", {"action": "list"})
        assert fake_log.client.posts == []

    @pytest.mark.asyncio
    async def test_stdout_stays_clean(self, fake_env, fake_log, capsys):
        """F20 stdout 纪律：tools/call 全程 stdout 零字节（协议帧独占）。"""
        with mcp_log_sink():
            await call_tool_result(build_mcp_tools(), "manage_project", {"action": "list"})
        assert capsys.readouterr().out == ""


class TestI18nCatalog:
    """契约 §4：message_key 登记 zh/en 打包目录（test_logging_message_keys 同族前哨）。"""

    def test_mcp_tool_call_key_registered(self):
        zh = json.loads((_MESSAGES_DIR / "zh.json").read_text(encoding="utf-8"))
        en = json.loads((_MESSAGES_DIR / "en.json").read_text(encoding="utf-8"))
        key = "log.event.mcp_tool_call"
        assert key in zh, "zh.json 缺少 log.event.mcp_tool_call"
        assert key in en, "en.json 缺少 log.event.mcp_tool_call"
        assert _PLACEHOLDER.findall(zh[key]) == _PLACEHOLDER.findall(en[key])
