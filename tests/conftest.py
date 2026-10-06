"""InkFlow 集成测试共享 fixture — 异步数据库 + 项目样本 + 会话级资源后置处理。

供 tests/integration/, tests/api/, tests/cli/ 使用。

#1488 / #1496（0.17.0）：本文件同时是**测试基础设施后置处理**的落点——

- 会话级回收测试拉起的 `inkflow serve` 内核进程（#1488，见文件末尾的
  `reclaim_test_kernel_processes` + `_reclaim_kernel_processes` fixture）；
- 注入 F51 v1.1 逃生门 `INKFLOW_DEBUG_NO_BROWSER=1`（#1496，见下方 env 块）。

两套 pytest 根（本文件 vs `backend/conftest.py`）各自加载各自的 conftest，
互不 import——同一对约定在两处镜像（与该文件既有的 `test_engine` 镜像同规）。
"""

import asyncio
import logging
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import AsyncGenerator
from pathlib import Path

# #735 D1: config.llm_default_model 全局默认已改空。顶层 integration/api/cli 测试的
# 历史用例依赖「未指定 model 时回退到 deepseek 默认」契约，此处统一经环境变量
# INKFLOW_LLM_DEFAULT_MODEL（env_prefix INKFLOW_ + 字段名 llm_default_model）
# 注入该值（「mock config 回退」）；D1 空默认契约由 test_model_resolution.py 用
# InkFlowConfig.model_fields（class 默认，免疫 env）单独断言。
os.environ.setdefault("INKFLOW_LLM_DEFAULT_MODEL", "deepseek/deepseek-v4-flash")

# ── #1496：pytest 侧统一注入 F51 v1.1（#949）逃生门 ──────────────────────────
# debug 态 `serve` 默认自动用系统浏览器打开 /docs（F51 拍板 D2，面向手动调试）。
# 本地跑 pytest 时，每个「以 debug 态拉起内核」的用例各弹一次 → 累积十几个/几十个
# 窗口（#1496 现象；`tests/cli/test_cli_serve.py::TestServeDebugMode` 中未 patch
# Timer 的用例即为其一）。e2e 侧已同规（`tests/e2e/e2e-debug-triad.spec.ts` 的
# `baseEnv`）。显式赋值（非 setdefault）：入口确定，宿主 shell 残留值（如 `=0`）
# 不得让弹窗复发。只关「debug 自动弹」这一条路径，产品默认语义不变（未设该 env
# 时仍弹），由 `test_cli_serve.py::TestServeDebugNoBrowser` 的 delenv 用例守护。
os.environ["INKFLOW_DEBUG_NO_BROWSER"] = "1"

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from inkflow.core.database import Base
from inkflow.domain.models.project import ProjectCreate
from inkflow.infrastructure.database.models.project import ProjectORM

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """session-scoped event loop for async fixtures."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def test_engine():
    """function-scoped in-memory SQLite engine with tables created per test."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession]:
    """function-scoped async session bound to test_engine."""
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
def sample_project_data() -> ProjectCreate:
    """返回 ProjectCreate 实例，用于创建项目测试。"""
    return ProjectCreate(
        name="测试小说",
        tags=["玄幻"],
        language="zh-CN",
        target_words=100000,
    )


@pytest_asyncio.fixture
async def sample_project(db_session) -> ProjectORM:
    """创建并持久化一个 ProjectORM 实例（用于需要真实数据库记录的测试）。"""
    from inkflow.infrastructure.database.models.project import ProjectORM

    project = ProjectORM(
        name="测试小说",
        tags=["玄幻"],
        language="zh-CN",
        target_words=100000,
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest_asyncio.fixture
async def api_project(client, db_session, override_get_db) -> dict:
    """经真实 API 落库的存活项目（含可解析 UUID 字符串）。

    #1151: 反例守护必须用「真活着」的项目 — 本 fixture 走 POST /projects
    真实装配，故 project_service 依赖的 project_repo / 事件发布链路与生产一致。
    """
    resp = await client.post(
        "/api/v1/projects",
        json={
            "name": "filter-outline-probe",
            "genre": "xuanhuan",
            "tags": ["xuanhuan"],
        },
    )
    assert resp.status_code == 201, resp.text[:200]
    return resp.json()


@pytest.fixture
def sample_project_data2() -> ProjectCreate:
    """第二个项目数据，用于列表测试。"""
    return ProjectCreate(
        name="科幻新作",
        tags=["科幻"],
        language="zh-CN",
        target_words=80000,
    )


@pytest.fixture
def temp_keys_dir():
    """临时密钥存储目录，测试后自动清理。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# ── #1488：测试拉起的 `inkflow serve` 内核进程——会话级统一回收 ────────────────
#
# 缺陷：`_spawn_kernel` 是 detach 语义（`CREATE_NEW_PROCESS_GROUP` + 无窗口），内核
# 的存活期互斥由**客户端**（pytest 进程）持有 → 客户端退出即被 OS 回收，互斥不约束
# 内核存活。任何「测试没走到清理行 / 被中断 / 清理失败」的路径都会留下永久存活的
# `inkflow serve`（#1488 实测：本机累积 76 个；每个都持有 `%TEMP%\inkflow-kernel.log`
# 句柄 → 连带 #1477 的日志轮转失效）。
#
# 处置（用户 2026-10-06 拍板「统一后置处理」）：会话结束时按**归属**回收。归属判据
# 两条，宁漏不误杀：
#   ① CommandLine 含本会话 pytest 临时根（basetemp）——覆盖「spawn 方已退出、进程
#      被孤儿化」的情形（uv shim / 中间子进程退出后亲缘链已断，无法靠 pid 关系找）；
#   ② 亲缘链上溯到本 pytest 进程 pid——覆盖 state_file 落在 basetemp 之外的 spawn
#      （如 `tests/cli/test_cli_project.py::test_serve_smoke` 的固定端口 serve）。
# **不匹配**的：手工常驻内核（数据目录在 `%APPDATA%\InkFlow`，亲缘链指向用户 shell）
# 与并行会话/其他 worktree 的内核（basetemp 与 pytest pid 都不同）——见
# `tests/cli/test_kernel_cleanup_1488.py` 的负例守护。
# 1 个逻辑内核 = 2 个 python.exe（uv shim + 真解释器，CommandLine 相同）——两条都
# 命中，故不依赖 `/T` 的父子级联即可清干净（实测见同文件）。

ENUM_TIMEOUT_S = 30.0
KILL_TIMEOUT_S = 15.0
KILL_PASSES = 2
KILL_SETTLE_S = 0.3
ANCESTRY_DEPTH = 16

logger = logging.getLogger(__name__)


def enumerate_processes() -> list[tuple[int, int, str]]:
    """枚举本机全部进程 → ``[(pid, ppid, cmdline)]``（非 Windows → ``[]``）。

    装配缝（测试 patch 点）：进程**枚举**与**归属判定/终止**分离，判据得以在不真实
    拉起内核的前提下验证。CommandLine 走 CIM（`Get-CimInstance Win32_Process`），
    与 `inkflow-dev` 的「内核归属判据只能是 CommandLine」纪律同源（别用进程名/启动
    时间推断）。
    """
    if sys.platform != "win32":
        return []
    script = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
        "Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" | ForEach-Object { "
        '"$($_.ProcessId)`t$($_.ParentProcessId)`t$($_.CommandLine)" }'
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        timeout=ENUM_TIMEOUT_S,
        check=False,
    )
    rows: list[tuple[int, int, str]] = []
    for line in proc.stdout.decode("utf-8", errors="replace").splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        try:
            rows.append((int(parts[0]), int(parts[1]), parts[2]))
        except ValueError:
            continue
    return rows


def terminate_process_tree(pid: int) -> None:
    """终止单个进程树（`taskkill /PID <pid> /T /F`）；调用方负责吞掉"已退出"类失败。"""
    if pid <= 0:
        return
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        timeout=KILL_TIMEOUT_S,
        check=False,
    )


def is_test_kernel(
    cmdline: str, pid: int, parents: dict[int, int], *, pytest_pid: int, basetemp: str
) -> bool:
    """归属判定（纯函数）：该进程是否为本 pytest 会话拉起的测试内核。"""
    if "inkflow" not in cmdline or "serve" not in cmdline:
        return False
    if basetemp and basetemp in cmdline.lower():
        return True
    seen: set[int] = set()
    current = pid
    for _ in range(ANCESTRY_DEPTH):
        parent = parents.get(current)
        if not parent or parent <= 0 or parent in seen:
            return False
        seen.add(parent)
        if parent == pytest_pid:
            return True
        current = parent
    return False


def reclaim_test_kernel_processes(pytest_pid: int, basetemp: str) -> list[int]:
    """回收本会话拉起的 `inkflow serve` 内核进程 → 已下发终止的 pid 列表。

    最多两趟（`/T` 的进程树终止有传播延迟，杀掉 shim 后复查一次真解释器）。
    **绝不抛错**：枚举失败（无 powershell / 超时）与终止失败（进程已退出 / 权限不足）
    全部吞掉并记 WARNING——清理失败不得把测试 ERROR（#1488 验收）。
    """
    terminated: list[int] = []
    for attempt in range(KILL_PASSES):
        try:
            rows = enumerate_processes()
        except Exception as exc:  # 清理失败不得升级为测试 ERROR（#1488 验收）
            logger.warning("#1488 内核进程枚举失败（第 %d 趟）：%s", attempt + 1, exc)
            return terminated
        parents = {pid: ppid for pid, ppid, _ in rows}
        base = basetemp.lower()
        targets = [
            pid
            for pid, _ppid, cmdline in rows
            if is_test_kernel(cmdline or "", pid, parents, pytest_pid=pytest_pid, basetemp=base)
        ]
        if not targets:
            break
        for pid in targets:
            try:
                terminate_process_tree(pid)
                terminated.append(pid)
            except Exception as exc:  # 进程已退出 / 权限不足 → 记日志不抛（#1488 验收）
                logger.warning("#1488 终止测试内核 pid=%s 失败：%s", pid, exc)
        time.sleep(KILL_SETTLE_S)
    return terminated


@pytest.fixture(scope="session", autouse=True)
def _reclaim_kernel_processes(tmp_path_factory):
    """#1488：会话结束回收本会话拉起的 `inkflow serve` 内核进程。

    会话级而非逐用例：归属判据依赖会话临时根与会话 pid，而逐用例枚举全机进程在本仓
    规模（~6500 单元 + 1200 集成用例）下不可接受。契约是「**跑完套件**后无残留」。
    """
    yield
    terminated = reclaim_test_kernel_processes(os.getpid(), str(tmp_path_factory.getbasetemp()))
    if terminated:
        logger.warning("#1488 会话结束回收测试内核进程 pid=%s", terminated)
