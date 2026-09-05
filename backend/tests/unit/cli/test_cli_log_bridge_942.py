"""#942 CLI 进程日志桥接 — cli_log_bridge 单元契约（RED 测试）。

缺陷背景（issue #942，#924 同族 CLI 侧）
---------------------------------------
CLI 子命令（inkflow project/chapter/write/...）的 @instrument(caller_type="cli")
埋点运行在 **inkflow CLI 进程**内；该进程不做内核 setup_logging()，loguru 默认
sink=stderr，不进内核 StructuredLogStore → GET /api/v1/logs?caller_type=cli 恒
total=0，GUI 日志页「内核」分类 CLI 操作痕迹永远缺失（审计盲区）。

GREEN 实现契约 1（模块 inkflow.logging.bridge，CREATE —— 通用转发引擎）
-----------------------------------------------------------------------
#924 的转发器/sink/flush 形态与调用方进程无关，提升为通用模块：

1. ``class LogForwarder``：构造参数 ``client_factory: Callable[[int, str], Any] | None``
   （None → 用本模块 ``_make_client``）。公开属性/方法语义与 McpLogForwarder 逐字一致：
   - ``pending: deque[maxlen=200]`` 满丢最旧静默；``client``；
   - ``attach(port, token)``：端点未变且 client 非 None → 复用；否则关旧建新（factory）。
     token 只进 factory/client 请求头，绝不进 pending/body；
   - ``reset()`` / ``sink(message)``（仅带 caller_type 的 extra；WARNING→WARN 归一；
     LogRecordInput 形状 body；整体 suppress）/ ``flush()``（client None→no-op 不消费；
     逐条 POST "/logs" timeout=5.0；异常弃该条续后；成功/失败均消费 pending）。
2. ``_make_client(port, token) -> httpx.Client``：默认工厂
   （base_url=http://127.0.0.1:{port}/api/v1，头 X-InkFlow-Token，timeout 5.0）。
3. ``log_sink(forwarder)`` contextmanager：进入 logger.add(forwarder.sink, level="INFO",
   filter caller_type) + 包装 ``inkflow.infrastructure.kernel`` 模块属性的
   ensure_kernel（成功→forwarder.attach(port, token)，异常透传）；重入 depth 守卫；
   退出：final flush → 还原 ensure_kernel → logger.remove(handler_id) → 关 client。
4. ``is_sink_active() -> bool``：depth>0。

GREEN 实现契约 2（模块 inkflow.mcp.log_bridge，MODIFY → MCP 侧门面）
---------------------------------------------------------------------
公开面逐一保留（#924 两个测试文件必须原样绿）：``McpLogForwarder``（=引擎 subclass，
工厂**动态读 inkflow.mcp.log_bridge 模块属性** _make_client，使
monkeypatch.setattr(bridge, "_make_client") 生效）、``_make_client``（真实 httpx
工厂，契约不变）、``get_forwarder()``（mcp 单例）、``mcp_log_sink()``
（=log_sink(get_forwarder())）、``is_bridge_active()``（=is_sink_active()）。
引擎逻辑迁移，行为零变化。

GREEN 实现契约 3（模块 inkflow.cli.log_bridge，CREATE —— CLI 接线）
--------------------------------------------------------------------
1. ``_make_client(port, token)``：与契约 1.2 同 httpx 契约（本模块级工厂缝，
   测试 monkeypatch 点；CLI 单例工厂须**动态读该模块属性**）。
2. ``get_cli_forwarder()``：CLI 进程级单例（与 mcp 单例分离，互不污染）。
3. ``cli_log_sink()`` contextmanager：
   a. 进入时（此时 inkflow.cli.commands.* 已全部导入）：对每个已加载
      ``inkflow.cli.commands`` 前缀模块**且带 ensure_kernel 属性**者，包装其模块属性
      （await 原函数成功→forwarder.attach→返回；异常透传）——CLI 命令顶层
      ``from ... import ensure_kernel`` 是模块全局查找，包装模块属性即生效。
      🔴 绝不新增任何 ensure_kernel 调用（零额外探测/零冷启动副作用）；
   b. 包装 ``typer.core.TyperCommand.invoke``（类属性 patch，退出时还原）：每个叶子
      命令调用返回/抛出前 emit 审计 checkpoint（见 4）；
   c. 引擎复用 log_sink(get_cli_forwarder())；退出时最终 flush + 全部还原。
4. 审计 checkpoint（每次叶子命令恰好一条，经 log_structured → 引擎 sink → POST /logs）：
   - level："INFO"（正常返回 或 typer.Exit(code=0)）/ "WARN"（typer.Exit(code!=0)
     或任何异常，异常后原样 re-raise）。仅**非 typer.Exit 异常**时
     error_code="X_CLI_ERROR"（typer.Exit 失败路径靠 print_error 语义，不加码）；
   - caller_type="cli"、caller_name="inkflow-cli"（进程身份）；
   - event = 叶子命令路径：click info_name 链自根（"inkflow"）之下用 "." 连接
     （"project list" → "project.list"；拍平的 "serve"/"search" → 无点）；
   - message_key="log.event.cli_command"（登记 i18n zh/en，含 {command} 占位符）；
   - params 白名单 = {"group": 除叶子外的父链名（多段用 "-" 连接，叶子直挂根→""），
     "command": 叶子 info_name, "project_id": str(ctx.params.get("project_id")) 或 None}
     🔴 原始选项值（--content 正文等）一律不落；
   - 顶层 project_id：纯数字串→int；UUID/缺失→None（与 #924 口径一致）；
   - duration_ms=叶子 invoke 耗时；correlation_id 走缺省空串；
   - 叶子 invoke 的 **finally 尽力 flush**（forwarder.flush()，异常静默）——
     镜像 #924 call_tool_result finally 语义，保证命令返回前推送缓冲。
5. inkflow/cli/app.py ``_JsonHintGroup.main``：--json 错位提示检查之后，
   ``with cli_log_sink(): return super().main(...)``（SystemExit/异常路径同样
   触发退出 flush）。typer 全局 app()、python -m inkflow 与 CliRunner 均经
   Command.main → 本入口。
6. 隔离性：未进入 cli_log_sink（如子 app 直接 CliRunner、pytest 直调）→ 零 patch、
   零转发；``inkflow --help``/``--version``/无参 help → 叶子未执行 → 零 checkpoint。
7. token/命令正文不进转发 body（F20 §271 纪律延伸）；桥接故障静默，CLI 输出/退出码
   语义零变化。

RED 预期（main@9b89e06）
------------------------
inkflow.logging.bridge / inkflow.cli.log_bridge 不存在 → 本文件顶部 import 收集期
ModuleNotFoundError（exit 2，与 #924 RED 形态一致）。全 FAIL 后才允许 GREEN。

测试约定
--------
- 🔴 CLI 命令模块顶层 ``from inkflow.infrastructure.kernel import ensure_kernel``：
  假 ensure 必须 monkeypatch **命令模块属性**（project/chapter 各自），且在
  runner.invoke 之前（cli_log_sink 进入时读取并包装当时的模块属性）。
- 业务 HTTP 面 monkeypatch 命令模块的 InkFlowHTTPClient 属性（镜像
  backend/tests/unit/cli/test_cli_character_gaps.py 既有模式）。
- 每用例独立 FakeLogClient（monkeypatch cli log_bridge._make_client）+
  get_cli_forwarder().reset() 前后复位；禁全局 logger.remove() 复位（连坐）。
- 禁无断言 smoke：每个用例都有具体 body/level/字段断言。
"""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import AsyncMock

import pytest
import typer
from typer.testing import CliRunner

from inkflow.cli.log_bridge import get_cli_forwarder  # RED: 模块不存在
from inkflow.logging.bridge import LogForwarder  # RED: 模块不存在

bridge_mod = importlib.import_module("inkflow.logging.bridge")
cli_bridge_mod = importlib.import_module("inkflow.cli.log_bridge")
project_mod = importlib.import_module("inkflow.cli.commands.project")
chapter_mod = importlib.import_module("inkflow.cli.commands.chapter")
http_mod = importlib.import_module("inkflow.infrastructure.http")

from inkflow.cli.app import app as root_app  # noqa: E402  # 常量须在模块导入后（依赖 RED 模块就位）

_FAKE_TOKEN = "sekret-942"  # 🔴 永不泄漏断言锚（F20 §271）
_UUID_P = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
_MESSAGES_DIR = Path(__file__).resolve().parents[3] / "src" / "inkflow" / "i18n" / "messages"
_PLACEHOLDER = re.compile(r"\{(\w+)[^}]*\}")


class FakeLogClient:
    """记录 POST /logs 转发的假客户端（cli log_bridge._make_client 缝）。"""

    def __init__(self) -> None:
        self.posts: list[dict] = []
        self.closed = False

    def post(self, path: str, *, json: dict | None = None, timeout: float | None = None) -> object:
        self.posts.append({"path": path, "json": json, "timeout": timeout})
        return SimpleNamespace(status_code=200)

    def close(self) -> None:
        self.closed = True


class FakeToolClient:
    """CLI 命令业务 HTTP 面 fake（镜像 #924 同名类；response 类属性可按例覆写）。"""

    response: ClassVar[dict] = {"items": [], "total": 0}

    def __init__(self, handle: object) -> None:
        self.handle = handle

    async def __aenter__(self) -> FakeToolClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, path: str, *, params: object = None) -> dict:
        return self.response

    async def post(self, path: str, *, json: object = None, params: object = None) -> dict:
        return self.response


@pytest.fixture
def fake_cli_env(monkeypatch):
    """转发缝 + 单例复位（跨用例隔离）。"""
    client = FakeLogClient()
    monkeypatch.setattr(cli_bridge_mod, "_make_client", lambda port, token: client)
    fwd = get_cli_forwarder()
    fwd.reset()
    yield SimpleNamespace(client=client, forwarder=fwd)
    fwd.reset()


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


def _patch_kernel(monkeypatch, *mods: object) -> AsyncMock:
    """monkeypatch 命令模块属性的 ensure_kernel（cli_log_sink 进入时读取包装）。"""
    fake = AsyncMock(
        return_value=SimpleNamespace(port=1, token=_FAKE_TOKEN, pid=2, version="0.1.0")
    )
    for mod in mods:
        assert hasattr(mod, "ensure_kernel")
        monkeypatch.setattr(mod, "ensure_kernel", fake)  # type: ignore[arg-type]  # AsyncMock 替函数，签名不同构
    return fake


def _last_body(client: FakeLogClient) -> dict:
    assert client.posts, "桥接未发生任何 POST /logs 转发"
    last = client.posts[-1]["json"]
    assert isinstance(last, dict)
    return last


# ---------------------------------------------------------------------------
# A. 通用引擎（inkflow.logging.bridge）
# ---------------------------------------------------------------------------


class TestGenericForwarder:
    """契约 1：LogForwarder 语义与 #924 McpLogForwarder 同构。"""

    def test_injected_factory_used_on_attach(self):
        made: list[tuple[int, str]] = []

        def factory(port: int, token: str) -> FakeLogClient:
            made.append((port, token))
            return FakeLogClient()  # type: ignore[return-value]  # 假客户端鸭子类型替 httpx.Client

        fwd = LogForwarder(client_factory=factory)
        fwd.attach(7, "tok-a")
        assert made == [(7, "tok-a")]
        client_a = fwd.client
        fwd.attach(7, "tok-a")  # 端点未变 → 复用
        assert fwd.client is client_a
        assert made == [(7, "tok-a")]

    def test_flush_noop_without_client(self):
        fwd = LogForwarder(client_factory=lambda port, token: FakeLogClient())
        fwd.pending.append({"level": "INFO", "caller_type": "cli"})
        fwd.flush()  # 不抛
        assert len(fwd.pending) == 1  # no-op 不消费

    def test_real_make_client_contract(self):
        import httpx

        client = bridge_mod._make_client(8123, _FAKE_TOKEN)
        try:
            assert isinstance(client, httpx.Client)
            assert str(client.base_url) == "http://127.0.0.1:8123/api/v1/"
            assert client.headers["X-InkFlow-Token"] == _FAKE_TOKEN
            assert client.timeout.read == 5.0
        finally:
            client.close()

    def test_default_factory_reads_module_attr(self, monkeypatch):
        """契约 1.1：client_factory=None → attach 时运行时读本模块 _make_client。"""
        made: list[tuple[int, str]] = []
        monkeypatch.setattr(
            bridge_mod, "_make_client", lambda port, token: made.append((port, token))
        )
        fwd = LogForwarder()  # 不注入工厂
        fwd.attach(9, "tok-b")
        assert made == [(9, "tok-b")]

    def test_sink_ignores_unstructured_records(self):
        """契约 1.3：无 caller_type 的记录不进缓冲（sink 级过滤，双保险）。"""
        fwd = LogForwarder(client_factory=lambda port, token: FakeLogClient())
        fwd.sink(SimpleNamespace(record={"extra": {}}))
        assert list(fwd.pending) == []


# ---------------------------------------------------------------------------
# B. CLI 审计 checkpoint 端到端（根 app + CliRunner）
# ---------------------------------------------------------------------------


class TestCliCheckpoint:
    """契约 3/4：叶子命令 checkpoint（经 cli_log_sink → POST /logs）。"""

    def test_success_info_checkpoint(self, fake_cli_env, monkeypatch, cli_runner):
        _patch_kernel(monkeypatch, project_mod)
        monkeypatch.setattr(project_mod, "InkFlowHTTPClient", FakeToolClient)
        result = cli_runner.invoke(root_app, ["project", "list"])
        assert result.exit_code == 0, result.output
        body = _last_body(fake_cli_env.client)
        assert body["caller_type"] == "cli"
        assert body["caller_name"] == "inkflow-cli"
        assert body["level"] == "INFO"
        assert body["event"] == "project.list"
        assert body["message_key"] == "log.event.cli_command"
        assert body["params"]["group"] == "project"
        assert body["params"]["command"] == "list"
        assert body["params"]["project_id"] is None
        assert isinstance(body.get("duration_ms"), (int, float))
        assert body.get("error_code") is None
        assert "correlation_id" in body
        assert fake_cli_env.client.posts[-1]["path"] == "/logs"

    def test_failure_warn_checkpoint(self, fake_cli_env, monkeypatch, cli_runner):
        class Failing(FakeToolClient):
            async def get(self, path: str, *, params: object = None) -> dict:
                raise http_mod.HttpApiError(status_code=404, detail="不存在")

        _patch_kernel(monkeypatch, project_mod)
        monkeypatch.setattr(project_mod, "InkFlowHTTPClient", Failing)
        result = cli_runner.invoke(root_app, ["project", "list"])
        assert result.exit_code == 1
        body = _last_body(fake_cli_env.client)
        assert body["level"] == "WARN"
        assert body["event"] == "project.list"
        assert body["caller_type"] == "cli"
        assert body.get("error_code") is None  # typer.Exit 路径不加码（契约 4）
        # instrument 的 WARN/ERROR（_impl/exit 异常）也应被转发（INFO+ 口径）→ ≥2 条
        levels = [p["json"]["level"] for p in fake_cli_env.client.posts]
        assert "ERROR" in levels or "WARN" in levels
        assert len(fake_cli_env.client.posts) >= 2

    def test_uncaught_exception_warn_with_code(self, fake_cli_env, monkeypatch, cli_runner):
        class Boom(FakeToolClient):
            async def get(self, path: str, *, params: object = None) -> dict:
                raise ValueError("boom-942")

        _patch_kernel(monkeypatch, chapter_mod)
        monkeypatch.setattr(chapter_mod, "InkFlowHTTPClient", Boom)
        result = cli_runner.invoke(
            root_app, ["chapter", "list", "-p", _UUID_P]  # ValueError → 崩溃路径
        )
        assert result.exit_code != 0
        body = _last_body(fake_cli_env.client)
        assert body["level"] == "WARN"
        assert body["event"] == "chapter.list"
        assert body["error_code"] == "X_CLI_ERROR"
        # UUID → 顶层不猜 int（与 #924 口径一致），值保留 params
        assert body.get("project_id") is None
        assert body["params"]["project_id"] == _UUID_P

    def test_numeric_project_id_promoted(self, fake_cli_env, monkeypatch, cli_runner):
        """ensure 成功后纯数字 project_id → body 顶层 int；params 保留字符串。"""

        class PostEnsureBadId(FakeToolClient):
            async def get(self, path: str, *, params: object = None) -> dict:
                raise ValueError("bad uuid")

        _patch_kernel(monkeypatch, chapter_mod)
        monkeypatch.setattr(chapter_mod, "InkFlowHTTPClient", PostEnsureBadId)
        # chapter list 的 _impl 先 ensure 再 uuid 解析 → -p 42 崩溃但已 attach
        result = cli_runner.invoke(root_app, ["chapter", "list", "-p", "42"])
        assert result.exit_code != 0
        body = _last_body(fake_cli_env.client)
        assert body["error_code"] == "X_CLI_ERROR"
        assert body["project_id"] == 42
        assert body["params"]["project_id"] == "42"

    def test_option_values_never_leak(self, fake_cli_env, monkeypatch, cli_runner):
        secret = "夜色沉沉，山门之内灯火通明，这段正文绝不该出现在审计日志里。"
        monkeypatch.setattr(
            FakeToolClient, "response", {"id": "x", "title": "第一章", "word_count": 1}
        )
        _patch_kernel(monkeypatch, chapter_mod)
        monkeypatch.setattr(chapter_mod, "InkFlowHTTPClient", FakeToolClient)
        result = cli_runner.invoke(
            root_app,
            ["chapter", "create", "-p", _UUID_P, "-t", "第一章", "-c", secret],
        )
        assert result.exit_code == 0, result.output
        for post in fake_cli_env.client.posts:
            assert secret not in json.dumps(post["json"], ensure_ascii=False)
            assert "第一章" not in json.dumps(post["json"], ensure_ascii=False)
        body = _last_body(fake_cli_env.client)
        assert body["event"] == "chapter.create"
        assert body["level"] == "INFO"

    def test_token_never_in_forwarded_body(self, fake_cli_env, monkeypatch, cli_runner):
        _patch_kernel(monkeypatch, project_mod)
        monkeypatch.setattr(project_mod, "InkFlowHTTPClient", FakeToolClient)
        cli_runner.invoke(root_app, ["project", "list"])
        assert fake_cli_env.client.posts, "前置：确实发生了转发"
        for post in fake_cli_env.client.posts:
            assert _FAKE_TOKEN not in json.dumps(post["json"], ensure_ascii=False)

    def test_no_leaf_command_forwards_nothing(self, fake_cli_env, cli_runner):
        """无参 help / --version → 叶子未执行 → 零 checkpoint 零转发（契约 6）。"""
        r1 = cli_runner.invoke(root_app, [])
        assert r1.exit_code == 2  # no_args_is_help 既有契约（test_cli_output.py:155）
        r2 = cli_runner.invoke(root_app, ["--version"])
        assert r2.exit_code == 0
        assert fake_cli_env.client.posts == []

    def test_detach_when_kernel_ensure_never_called(self, fake_cli_env, cli_runner):
        """不调 ensure_kernel 的命令（config show）→ 未 attach → 零转发。"""
        result = cli_runner.invoke(root_app, ["--json", "config", "show"])
        assert result.exit_code == 0, result.output
        assert fake_cli_env.client.posts == []

    def test_checkpoint_emitted_exactly_once_per_leaf(self, fake_cli_env, monkeypatch, cli_runner):
        """一次叶子命令恰好一条 checkpoint（event 唯一 + caller_name 进程身份）。"""
        _patch_kernel(monkeypatch, project_mod)
        monkeypatch.setattr(project_mod, "InkFlowHTTPClient", FakeToolClient)
        cli_runner.invoke(root_app, ["project", "list"])
        ckpts = [
            p["json"]
            for p in fake_cli_env.client.posts
            if p["json"]["message_key"] == "log.event.cli_command"
        ]
        assert len(ckpts) == 1
        assert ckpts[0]["event"] == "project.list"


class TestBridgeLifecycle:
    """契约 3/5：进入/退出与还原纪律。"""

    def test_teardown_restores_everything(self, fake_cli_env, monkeypatch, cli_runner):
        from typer.core import TyperCommand

        orig_invoke = TyperCommand.invoke
        fake = _patch_kernel(monkeypatch, project_mod)
        monkeypatch.setattr(project_mod, "InkFlowHTTPClient", FakeToolClient)
        cli_runner.invoke(root_app, ["project", "list"])
        assert TyperCommand.invoke is orig_invoke  # 类属性还原
        assert project_mod.ensure_kernel is fake  # 进入时捕获的（已 patch 的）值还原

    def test_debug_instrument_logs_not_forwarded(self, fake_cli_env, monkeypatch, cli_runner):
        """DEBUG start/done 不桥接（口径与 #924/内核 api 一致）。"""
        _patch_kernel(monkeypatch, project_mod)
        monkeypatch.setattr(project_mod, "InkFlowHTTPClient", FakeToolClient)
        cli_runner.invoke(root_app, ["project", "list"])
        for post in fake_cli_env.client.posts:
            assert post["json"]["level"] != "DEBUG"

    def test_flush_survives_transport_error(self, fake_cli_env, monkeypatch, cli_runner):
        class Boom(FakeLogClient):
            def post(self, path, *, json=None, timeout=None):  # type: ignore[no-untyped-def]  # 覆写父类签名只测抛异常
                raise RuntimeError("kernel gone")

        monkeypatch.setattr(cli_bridge_mod, "_make_client", lambda port, token: Boom())
        _patch_kernel(monkeypatch, project_mod)
        monkeypatch.setattr(project_mod, "InkFlowHTTPClient", FakeToolClient)
        result = cli_runner.invoke(root_app, ["project", "list"])
        assert result.exit_code == 0  # 转发失败对 CLI 语义零影响
        assert list(fake_cli_env.forwarder.pending) == []  # 尽力而为即弃

    def test_nested_cli_log_sink_single_install(self, fake_cli_env, monkeypatch, cli_runner):
        """契约 3c：嵌套进入不叠加 patch——内层退出后外层会话完好，外层次退出才还原。"""
        from typer.core import TyperCommand

        _patch_kernel(monkeypatch, project_mod)
        monkeypatch.setattr(project_mod, "InkFlowHTTPClient", FakeToolClient)
        with cli_bridge_mod.cli_log_sink():
            outer_patched = "invoke" in TyperCommand.__dict__
            assert outer_patched
            with cli_bridge_mod.cli_log_sink():
                pass
            assert "invoke" in TyperCommand.__dict__  # 内层退出未拆外层（depth 守卫）
            cli_runner.invoke(root_app, ["project", "list"])
            assert fake_cli_env.client.posts  # 会话仍正常转发
        assert "invoke" not in TyperCommand.__dict__  # 最外层退出才还原

    def test_restore_invoke_respects_preexisting_own_attribute(self, fake_cli_env, monkeypatch):
        """契约 3b 还原纪律：进入前已有自有 invoke（第三方 patch）→ 退出回填原函数。"""
        from typer.core import TyperCommand

        sentinel = TyperCommand.invoke

        def third_party(self, ctx):  # 模拟第三方类属性 patch
            return sentinel(self, ctx)

        TyperCommand.invoke = third_party
        try:
            with cli_bridge_mod.cli_log_sink():
                assert TyperCommand.invoke is not third_party
            assert TyperCommand.invoke is third_party  # 回填进入前的自有属性
        finally:
            del TyperCommand.invoke

    def test_emit_checkpoint_exit_zero_is_info(self, fake_cli_env):
        """契约 4：typer.Exit(code=0) 显式成功 → INFO 无 error_code。"""
        ctx = SimpleNamespace(
            info_name="list",
            parent=SimpleNamespace(info_name="inkflow", parent=None),
            params={},
        )
        with bridge_mod.log_sink(get_cli_forwarder()):
            get_cli_forwarder().attach(1, _FAKE_TOKEN)  # flush 需 client（工厂=fixture fake）
            cli_bridge_mod._emit_checkpoint(
                ctx, outcome=typer.Exit(0), duration_ms=1.5
            )
        get_cli_forwarder().flush()
        body = _last_body(fake_cli_env.client)
        assert body["level"] == "INFO"
        assert body["event"] == "list"
        assert body["params"]["group"] == ""
        assert body.get("error_code") is None

    def test_emit_checkpoint_bare_exception_is_warn_with_code(self, fake_cli_env):
        """契约 4：非 typer.Exit 异常直抛 → WARN + X_CLI_ERROR。"""
        ctx = SimpleNamespace(
            info_name="run",
            parent=SimpleNamespace(info_name="inkflow", parent=None),
            params={},
        )
        with bridge_mod.log_sink(get_cli_forwarder()):
            get_cli_forwarder().attach(1, _FAKE_TOKEN)  # flush 需 client（工厂=fixture fake）
            cli_bridge_mod._emit_checkpoint(
                ctx, outcome=RuntimeError("crash-942"), duration_ms=2.0
            )
        get_cli_forwarder().flush()
        body = _last_body(fake_cli_env.client)
        assert body["level"] == "WARN"
        assert body["error_code"] == "X_CLI_ERROR"
        assert body["caller_type"] == "cli"

    def test_ctx_below_root_defensive_shapes(self):
        """契约 4 边界：ctx None / 全链无名 → 空链（不抛，checkpoint event 退化为空）。"""
        assert cli_bridge_mod._ctx_below_root(None) == []
        no_name = SimpleNamespace(info_name=None, parent=None)
        assert cli_bridge_mod._ctx_below_root(no_name) == []
        one = SimpleNamespace(
            info_name="list", parent=SimpleNamespace(info_name="inkflow", parent=None)
        )
        assert cli_bridge_mod._ctx_below_root(one) == ["list"]

    def test_subapp_direct_runner_forwards_nothing(self, fake_cli_env, monkeypatch):
        """隔离性：绕过根 app（子 app 直接 CliRunner）→ 零 patch 零转发。"""
        from inkflow.cli.commands.project import app as project_app

        runner = CliRunner()
        _patch_kernel(monkeypatch, project_mod)  # 防真实冷启动
        monkeypatch.setattr(project_mod, "InkFlowHTTPClient", FakeToolClient)
        runner.invoke(project_app, ["list"], obj=SimpleNamespace(json_output=False))
        assert fake_cli_env.client.posts == []


class TestI18nCatalog:
    """契约 4：message_key 登记 zh/en（AST 前哨测试同族）。"""

    def test_cli_command_key_registered(self):
        zh = json.loads((_MESSAGES_DIR / "zh.json").read_text(encoding="utf-8"))
        en = json.loads((_MESSAGES_DIR / "en.json").read_text(encoding="utf-8"))
        key = "log.event.cli_command"
        assert key in zh, "zh.json 缺少 log.event.cli_command"
        assert key in en, "en.json 缺少 log.event.cli_command"
        assert _PLACEHOLDER.findall(zh[key]) == _PLACEHOLDER.findall(en[key])
        assert "command" in _PLACEHOLDER.findall(zh[key])
