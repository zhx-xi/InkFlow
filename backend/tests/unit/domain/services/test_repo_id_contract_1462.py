"""#1462 同族扫描契约：`.int` 漏网调用点（传给 repo 的裸 int）回归锁。

════════════════════════════════════════════════════════════════════
背景（#1462 根因的同族面）
  #1271（PR #1290）/ #1291（PR #1296）把仓储入口收窄为 `uuid.UUID`
  （`_id_guard.require_uuid_pk` 对裸 int 显式 `raise TypeError`，ADR-060 D9）。
  收窄时**漏改**了若干调用点——`planner_service._generate_questions`
  （#1462 本体）之外，本文件锁定另外三处同族漏网：

  1. `memory_service.list_user_preferences`      → `project_repo.get(pid.int)`
  2. `memory_service.get_user_preferences_for_injection` → `project_repo.get(project_id.int)`
  3. `agent_service_context._assemble_setting_context`   → `project_repo.get(project_uuid.int)`

  第 3 处最隐蔽：#1319 已把三源 `repo.list()` 的裸 int 修掉（见
  test_agent_service_setting_real_repo_1319.py），但同一 try 块内的
  `project_repo.get(project_int)` 被漏掉；其 `except Exception`（整体失败隔离）
  把 TypeError 吞成「设定注入失败」→ 生产 agent 轨 `variables["setting"]`
  **永不写入**（该文件里的 `_ProjRepo.get(_pid)` 吸收任意入参，故既有测试看不见）。

════════════════════════════════════════════════════════════════════
用例分组与预期（RED 阶段；实现者不得改本文件）

【新增契约】当前必须 FAIL：
  S-1 test_memory_list_user_preferences_passes_uuid
  S-2 test_memory_injection_passes_uuid
  S-3 test_agent_setting_context_passes_uuid
  S-4 test_no_project_repo_get_with_bare_dot_int_in_src（静态回归锁）

【反例守护】当前即 PASS，修复后必须保持 PASS：
  S-5 test_require_uuid_pk_still_rejects_bare_int
      （ADR-060 D9 契约不得被反向放宽——修调用点，不是放宽 guard）

若某条实际状态与预期不符，**如实报告，不要改断言凑数**。
════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import pathlib
import re
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.project import ProjectConfig
from inkflow.domain.services.agent_service import AgentService
from inkflow.domain.services.memory_service import MemoryService
from inkflow.infrastructure.database.repositories._id_guard import require_uuid_pk

PID = uuid.UUID(int=1001)
"""项目主键：uuid.UUID(int=n) 形态（仓库惯例）。"""

_SRC_ROOT = pathlib.Path(__file__).resolve().parents[4] / "src" / "inkflow"
"""`src/inkflow` 根（backend/src/inkflow）——静态回归锁的扫描面。"""


class _UuidOnlyProjectRepo:
    """镜像 SQLiteProjectRepository.get 的入参契约（复用真 require_uuid_pk）。"""

    def __init__(self, project: object | None) -> None:
        self._project = project
        self.received: list[object] = []

    async def get(self, project_id: object) -> object | None:
        require_uuid_pk(project_id)  # 裸 int → TypeError（ADR-060 D9）
        self.received.append(project_id)
        return self._project


class _StubListRepo:
    """三源 repo 鸭子桩：list 同样只认领域 UUID（镜像 #1319 已修形态）。"""

    def __init__(self, items: list[object]) -> None:
        self._items = items
        self.received: list[object] = []

    async def list(self, project_id: object, **kwargs: object) -> tuple[list[object], int]:
        require_uuid_pk(project_id)
        self.received.append(project_id)
        return list(self._items), len(self._items)


class _StubStore:
    """ExecutionStore 替身（本契约不跑管线）。"""

    async def create_execution(self, *args: object, **kwargs: object) -> None:
        return None

    async def get_execution(self, *args: object, **kwargs: object) -> None:
        return None

    async def update_status(self, *args: object, **kwargs: object) -> None:
        return None

    async def update_stages(self, *args: object, **kwargs: object) -> None:
        return None


def _project(extra: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(config=ProjectConfig(extra=extra or {}))


def _user_pref() -> SimpleNamespace:
    """用户级偏好鸭子对象（source_projects 含 PID → 触发惰性重算的项目存在性查询）。"""
    return SimpleNamespace(
        id="up-1",
        category="style_word",
        pattern="说",
        value="低声道",
        confidence=0.5,
        count=2,
        project_count=2,
        source_projects=[str(PID)],
        source_events=["evt-1"],
    )


# ══════════════════════════════════════════════════════════════════════
# 同族漏网 1/2：memory_service
# ══════════════════════════════════════════════════════════════════════


async def test_memory_list_user_preferences_passes_uuid() -> None:
    """【新增契约 S-1】惰性重算的项目存在性查询必须传领域 UUID。

    当前 `project_repo.get(pid.int)` → TypeError（**未被捕获**，直接冒泡）→ FAIL。
    """
    project_repo = _UuidOnlyProjectRepo(_project())
    user_repo = AsyncMock()
    user_repo.list_all.return_value = ([_user_pref()], 1)
    svc = MemoryService(
        preference_repo=AsyncMock(),
        event_repo=AsyncMock(),
        project_repo=project_repo,
        user_preference_repo=user_repo,
    )

    items, total = await svc.list_user_preferences()

    assert project_repo.received and set(project_repo.received) == {PID}
    assert [p.id for p in items] == ["up-1"]
    assert total == 1


async def test_memory_injection_passes_uuid() -> None:
    """【新增契约 S-2】注入读口的项目查询必须传领域 UUID。

    当前 `project_repo.get(project_id.int)` → TypeError（未被捕获）→ FAIL。
    """
    project_repo = _UuidOnlyProjectRepo(_project({"memory_learning": True}))
    user_repo = AsyncMock()
    user_repo.list_all.return_value = ([], 0)
    svc = MemoryService(
        preference_repo=AsyncMock(),
        event_repo=AsyncMock(),
        project_repo=project_repo,
        user_preference_repo=user_repo,
    )

    result = await svc.get_user_preferences_for_injection(PID)

    assert result == []
    assert project_repo.received and set(project_repo.received) == {PID}


# ══════════════════════════════════════════════════════════════════════
# 同族漏网 3：agent_service_context（#1319 的漏网兄弟）
# ══════════════════════════════════════════════════════════════════════


async def test_agent_setting_context_passes_uuid() -> None:
    """【新增契约 S-3】`_assemble_setting_context` 的项目查询必须传领域 UUID。

    当前 `project_repo.get(project_uuid.int)` → TypeError → 被外层
    `except Exception`（整体失败隔离）吞掉 → `variables["setting"]` 永不写入 → FAIL。
    """
    char = SimpleNamespace(
        id=uuid.uuid4(),
        name="角色甲",
        personality="甲的性格",
        background="",
        goals="",
        brief="",
    )
    char_repo = _StubListRepo([char])
    project_repo = _UuidOnlyProjectRepo(_project())
    svc = AgentService(
        None,  # type: ignore[arg-type]  # 本契约不跑管线
        None,
        store=_StubStore(),
        project_repo=project_repo,
        chapter_repo=object(),
        template_repo=object(),
        character_repo=char_repo,
        world_repo=None,
        outline_repo=None,
        foreshadowing_repo=None,
    )

    variables = await svc._assemble_setting_context(str(PID), {})

    assert project_repo.received and set(project_repo.received) == {PID}
    assert char_repo.received and set(char_repo.received) == {PID}
    assert "setting" in variables, "设定注入必须真的产出（当前被 except Exception 吞成空）"
    assert "角色甲" in variables["setting"]


# ══════════════════════════════════════════════════════════════════════
# 同族漏网 4：静态回归锁（防新增 `.int` 漏网）
# ══════════════════════════════════════════════════════════════════════


def test_no_project_repo_get_with_bare_dot_int_in_src() -> None:
    """【新增契约 S-4】`src/inkflow` 内不得再有 `_project_repo.get(....int)` 形态。

    白空格归一后按 `[^)]*?\\.int` 匹配（跨行实参亦可命中）；
    `_project_repo.get(uuid.UUID(int=pid))` 这类**正确**回包不受影响
    （其形参是 `(int=`，非 `.int`）。
    """
    pattern = re.compile(r"_project_repo\.get\([^)]*?\.int\b")
    offenders: list[str] = []
    for path in _SRC_ROOT.rglob("*.py"):
        text = re.sub(r"\s+", " ", path.read_text(encoding="utf-8", errors="ignore"))
        for match in pattern.finditer(text):
            offenders.append(f"{path.relative_to(_SRC_ROOT)} :: {match.group(0)}")
    assert not offenders, (
        "以下调用点仍向 project_repo.get 传裸 int（ADR-060 D9 拒收）：\n" + "\n".join(offenders)
    )


# ══════════════════════════════════════════════════════════════════════
# 反例守护
# ══════════════════════════════════════════════════════════════════════


def test_require_uuid_pk_still_rejects_bare_int() -> None:
    """【反例守护 S-5】ADR-060 D9 契约不得被反向放宽（修调用点，不是放宽 guard）。"""
    assert require_uuid_pk(uuid.UUID(int=7)) == 7
    with pytest.raises(TypeError):
        require_uuid_pk(7)  # type: ignore[arg-type]  # 故意违例：验证裸 int 仍被拒
