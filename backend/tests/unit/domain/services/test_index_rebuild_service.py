"""
#659 IndexRebuildService 编排单元测试 (后端 #657 P2 配套)

本文件 = 契约。GREEN 新建 src/domain/services/index_rebuild_service.py, 导出
IndexRebuildService 类, 构造 Keyword-only, 方法签名(镜像 books_service 后台任务模式):

- __init__(*, project_repo, fulltext, vector):
    project_repo: ProjectRepositoryProtocol
    fulltext: Callable[[list[int] | None], Awaitable[None]]   # 全文重建 (search_service.rebuild)
    vector:   Callable[[list[int] | None], Awaitable[None]] | None  # 向量重建 (None = 未配)
- async start_rebuild(project_ids, scope='both') -> dict:
    预校验 -> spawn 后台任务 -> 返回 {task_id, status: 'running'}.
    预校验 raise: scope 非法 -> ValueError; ProjectNotFoundError -> 404;
    ValueError("未配置 embedding 模型") (scope=vector/both 且 vector is None) -> 422;
    ValueError("索引重建进行中") (相同 project 范围已有 running 任务) -> 409.
- async get_status(task_id) -> dict | None: 查任务进度状态; 未注册 -> None (router 映射 404).
- async _run(task_id, project_ids, scope) -> None: 后台执行体, 顺序 fulltext -> vector.

进度状态 dto (每 task): {status, step, progress_done, progress_total, rebuilt_at, error}。
progress_total = 项目数; progress_done 逐项目递增; step 标识当前阶段 (fulltext/vector)。

测试策略: patch 调用点 spawn_background_task 为记录 coroutine 的 fake, 返回可手动 await
的伪任务对象。真 store (内存 _tasks dict)。RED 预期: 模块不存在 -> collection error。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from inkflow.domain.ports.character_errors import ProjectNotFoundError
from inkflow.domain.services.index_rebuild_service import IndexRebuildService

PID_A = 1
PID_B = 2


class _FakeTask:
    """记录 coroutine 的伪任务 (spawn_background_task 返回), 可手动 await 执行体。"""

    def __init__(self, coro):
        self._coro = coro
        self._done = False

    def add_done_callback(self, cb):
        return None

    async def __call__(self):
        if not self._done:
            self._done = True
            return await self._coro
        return None


@pytest.fixture
def spawned():
    """patch spawn_background_task: 记录 (coro, key), 返回可 await 的伪任务。"""
    recorded = []

    def _fake_spawn(coro, *, key=None):
        task = _FakeTask(coro)
        recorded.append((task, key))
        return task

    with patch(
        "inkflow.domain.services.index_rebuild_service.spawn_background_task",
        side_effect=_fake_spawn,
    ) as m:
        m.recorded = recorded
        yield m


@pytest.fixture
def project_repo():
    repo = AsyncMock()
    repo.get = AsyncMock(side_effect=lambda pid: AsyncMock() if pid in (PID_A, PID_B) else None)
    return repo


def _svc(project_repo, vector=None):
    return IndexRebuildService(
        project_repo=project_repo,
        fulltext=AsyncMock(),
        vector=vector,
    )


@pytest.mark.asyncio
async def test_start_rebuild_returns_running_and_spawns(project_repo, spawned):
    """start_rebuild -> 运行中 task + 进度注册 + spawn (fire-and-forget fire)。"""
    svc = _svc(project_repo)
    result = await svc.start_rebuild([PID_A], scope="fulltext")
    assert result["status"] == "running"
    assert result["task_id"]
    task_id = result["task_id"]
    assert len(spawned.recorded) == 1
    assert spawned.recorded[0][1] == task_id
    status = await svc.get_status(task_id)
    assert status["status"] == "running"


@pytest.mark.asyncio
async def test_start_rebuild_project_not_found(project_repo, spawned):
    """任一 project 不存在 -> ProjectNotFoundError (-> 404)。"""
    svc = _svc(project_repo)
    with pytest.raises(ProjectNotFoundError):
        await svc.start_rebuild([999], scope="fulltext")


@pytest.mark.asyncio
async def test_start_rebuild_vector_needs_embedding(project_repo, spawned):
    """scope=vector 且 vector is None -> ValueError (-> 422 前置校验)。"""
    svc = _svc(project_repo, vector=None)
    with pytest.raises(ValueError, match="未配置 embedding 模型"):
        await svc.start_rebuild([PID_A], scope="vector")
    with pytest.raises(ValueError, match="未配置 embedding 模型"):
        await svc.start_rebuild([PID_A], scope="both")


@pytest.mark.asyncio
async def test_start_rebuild_conflict_409(project_repo, spawned):
    """相同 project 范围已有 running 任务 -> ValueError (-> 409)。"""
    svc = _svc(project_repo)
    await svc.start_rebuild([PID_A], scope="fulltext")
    with pytest.raises(ValueError, match="索引重建进行中"):
        await svc.start_rebuild([PID_A], scope="fulltext")


@pytest.mark.asyncio
async def test_start_rebuild_fulltext_done(project_repo, spawned):
    """后台执行体: fulltext 顺序执行 -> done + rebuilt_at + progress_done=total。"""
    svc = _svc(project_repo)
    result = await svc.start_rebuild([PID_A, PID_B], scope="fulltext")
    task_id = result["task_id"]
    task, _ = spawned.recorded[0]
    await task()
    status = await svc.get_status(task_id)
    assert status["status"] == "done"
    assert status["step"] == "fulltext"
    assert status["progress_done"] == 2
    assert status["progress_total"] == 2
    assert status["rebuilt_at"]


@pytest.mark.asyncio
async def test_start_rebuild_both_fulltext_then_vector(project_repo, spawned):
    """both: fulltext 先于 vector 执行, step 分段上报。"""
    svc = _svc(project_repo, vector=AsyncMock())
    result = await svc.start_rebuild([PID_A], scope="both")
    task_id = result["task_id"]
    task, _ = spawned.recorded[0]
    await task()
    status = await svc.get_status(task_id)
    assert status["status"] == "done"
    assert status["step"] == "vector"
    assert svc._fulltext.await_count == 1
    assert svc._vector.await_count == 1


@pytest.mark.asyncio
async def test_start_rebuild_vector_failure(project_repo, spawned):
    """vector 阶段失败 -> failed + error (fulltext 已建, 向量失败)。"""

    async def _failing_vector(project_ids):
        raise RuntimeError("embedding 模型不可用")

    svc = IndexRebuildService(
        project_repo=project_repo,
        fulltext=AsyncMock(),
        vector=_failing_vector,
    )
    result = await svc.start_rebuild([PID_A], scope="both")
    task_id = result["task_id"]
    task, _ = spawned.recorded[0]
    await task()
    status = await svc.get_status(task_id)
    assert status["status"] == "failed"
    assert "embedding 模型不可用" in status["error"]


@pytest.mark.asyncio
async def test_get_status_unknown_returns_none(project_repo, spawned):
    """未注册 task_id -> None (router 映射 404)。"""
    svc = _svc(project_repo)
    assert await svc.get_status("nope") is None


@pytest.mark.asyncio
async def test_start_rebuild_invalid_scope_raises(project_repo, spawned):
    """覆盖 L61-62：scope 非法 -> ValueError(invalid scope)。"""
    svc = _svc(project_repo)
    with pytest.raises(ValueError, match="invalid scope"):
        await svc.start_rebuild([PID_A], scope="bogus")


@pytest.mark.asyncio
async def test_start_rebuild_all_projects_via_list_all(spawned):
    """覆盖 L66-False/75/149-157：project_ids=None -> 走 _list_all_project_ids 分页。"""
    repo = AsyncMock()
    proj = AsyncMock()
    repo.list_all = AsyncMock(side_effect=[([proj], 2), ([proj], 2)])
    svc = IndexRebuildService(project_repo=repo, fulltext=AsyncMock(), vector=None)
    result = await svc.start_rebuild(None, scope="fulltext")
    assert result["status"] == "running"
    status = await svc.get_status(result["task_id"])
    assert status["progress_total"] == 2
    assert repo.list_all.await_count == 2


@pytest.mark.asyncio
async def test_run_vector_scope_skips_fulltext(project_repo, spawned):
    """覆盖 L113-False 弧：scope=vector 且 vector 已配 -> 跳过 fulltext 直接 vector。"""
    svc = _svc(project_repo, vector=AsyncMock())
    await svc.start_rebuild([PID_A], scope="vector")
    task, _ = spawned.recorded[0]
    await task()
    assert svc._fulltext.await_count == 0
    assert svc._vector.await_count == 1


@pytest.mark.asyncio
async def test_run_vector_none_defensive_failed(project_repo):
    """覆盖 L122-123：_run 内 vector is None 防御 -> RuntimeError -> failed。"""
    svc = _svc(project_repo, vector=None)
    svc._tasks["t-id"] = {
        "status": "running",
        "step": "vector",
        "progress_done": 0,
        "progress_total": 1,
        "rebuilt_at": None,
        "error": None,
    }
    await svc._run("t-id", [PID_A], scope="vector")
    assert svc._tasks["t-id"]["status"] == "failed"
    assert "embedding 模型不可用" in svc._tasks["t-id"]["error"]


@pytest.mark.asyncio
async def test_run_project_ids_none(project_repo):
    """覆盖 L109-False/121-False：_run project_ids=None -> 不解析 pid，fulltext-only 落 done。"""
    svc = _svc(project_repo)
    svc._tasks["t-id"] = {
        "status": "running",
        "step": "fulltext",
        "progress_done": 0,
        "progress_total": None,
        "rebuilt_at": None,
        "error": None,
    }
    await svc._run("t-id", None, scope="fulltext")
    assert svc._tasks["t-id"]["status"] == "done"
