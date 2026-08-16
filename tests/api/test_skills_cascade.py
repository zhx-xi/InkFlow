"""F39 Skills 域 coverage 缺口补测（2026-08-16）— router 盲区行 + service 边界。

背景：coverage 测量盲区（coverage-measurement-blindspots 根因 1）——真实 DB
（aiosqlite 线程池）模式下端点 await 后行不记录，router 异常映射/return 行
假 miss（功能已由 tests/api/test_skills_api.py 既有真实 DB 用例覆盖）。本文件
按 coverage 缺口清单补三类：

1. TestSkillRouterMockCoverage — mock _get_service + mock SQLiteAgentRepository
   （无线程池切换）→ 补记 skills.py L69/71/79/96-98/100-101/113/126/140
2. TestSkillFrontmatterEdges — 真实 DB API 链（_parse_frontmatter 同步解析在
   await 前，真实 DB 可记录）→ 补记 skill_service.py frontmatter 边界
   L182（无 --- 起始块）/L191（空行与 # 注释行）/L194（无冒号行）/L197
   （未闭合块）
3. TestSkillServiceUpdateEdges — service 层 mock → 补记 skill_service.py
   update L272 查重未命中分支（真实 DB 下 await 后盲区）与 L278-280
   （repo.update 返回 None → NotFound，真实 DB 不可达）

⚠️ CI 登记需求：.github/workflows/ci.yml integration-agent-backend job 的
pytest 显式文件列表（含 test_skills_api.py）需追加本文件
../tests/api/test_skills_cascade.py（父侧补登）。

测试方式镜像 tests/api/test_skills_api.py（契约 docstring 风格 + 无 token
模式 + ASGITransport + override_get_db 真实 DB 模式）；mock 段镜像
tests/unit/test_skill_service.py（ADR-015 Mock 注入）。
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from inkflow.api.app import app
from inkflow.api.routers import (
    skills,  # noqa: F401  # 模块存在性契约（镜像 test_skills_api.py）
)
from inkflow.domain.models.skill import Skill, SkillUpdate
from inkflow.domain.ports.agent_repository import AgentRepositoryProtocol
from inkflow.domain.ports.skill_errors import (
    SkillBuiltinError,
    SkillNameConflictError,
    SkillNotFoundError,
)
from inkflow.domain.ports.skill_repository import SkillRepositoryProtocol
from inkflow.domain.services.skill_service import SkillService

# ── 契约常量 ──

ENDPOINT = "/api/v1/skills"
"""Skill 端点前缀（spec §3.1）。"""

ENV_TOKEN = "INKFLOW_SERVER_TOKEN"
"""token 来源环境变量：本文件全部用例依赖未设置 → 直通。"""

VALID_CONTENT = (
    "---\n"
    "name: ok-skill\n"
    "description: 合法方法论\n"
    "---\n"
    "# 正文\n"
    "1. 步骤一\n"
)
"""合法 SKILL.md 样例（frontmatter name 满足 ^[a-z0-9-]{1,64}$）。"""


# ── Fixtures ──


@pytest_asyncio.fixture
async def client(monkeypatch):
    """ASGI 测试客户端（函数级，镜像 test_skills_api.py + 无 token 模式）。"""
    monkeypatch.delenv(ENV_TOKEN, raising=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── 辅助 ──


def _mock_skill(skill_id: int = 1, **overrides: object) -> Skill:
    """构造 router/服务层断言用 Skill 实体（固定时间戳）。"""
    fields: dict[str, object] = {
        "name": "ok-skill",
        "description": "合法方法论",
        "content": VALID_CONTENT,
        "source": "user_upload",
        "created_at": datetime(2026, 8, 1, 10, 0, 0),
        "updated_at": datetime(2026, 8, 1, 10, 0, 0),
    }
    fields.update(overrides)
    return Skill(id=skill_id, **fields)


# ── skills.py router 盲区行补覆盖（mock 服务层）──


@pytest.mark.asyncio
@pytest.mark.api
class TestSkillRouterMockCoverage:
    """router 盲区行补覆盖：mock _get_service + mock SQLiteAgentRepository。

    补记 L69（404 raise）/L71（409 raise）/L79（_agent_ids return）/
    L96-98（list 循环）/L100-101（list append+return）/L113（create
    return）/L126（get return）/L140（update return）。每用例内 with patch
    注入 mock（无 pytest fixture 解析问题）。
    """

    async def test_list_success_envelope(self, client) -> None:
        """list 成功：{items, total} 信封（覆盖 L94-101 循环体）。"""
        svc = MagicMock()
        svc.list = AsyncMock(return_value=[_mock_skill(1), _mock_skill(2)])
        with patch("inkflow.api.routers.skills._get_service", return_value=svc), patch(
            "inkflow.api.routers.skills.SQLiteAgentRepository"
        ) as mock_repo_cls:
            mock_repo_cls.return_value.list_agents_by_skill = AsyncMock(return_value=[])
            resp = await client.get(ENDPOINT)
        assert resp.status_code == 200
        assert resp.json()["total"] == 2
        assert all(it["agent_ids"] == [] for it in resp.json()["items"])

    async def test_create_success_201(self, client) -> None:
        """create 成功：201 + 实体（覆盖 L111-113）。"""
        svc = MagicMock()
        svc.create = AsyncMock(return_value=_mock_skill(1))
        with patch("inkflow.api.routers.skills._get_service", return_value=svc):
            resp = await client.post(ENDPOINT, json={"content": VALID_CONTENT})
        assert resp.status_code == 201
        assert resp.json()["name"] == "ok-skill"

    async def test_get_success_200(self, client) -> None:
        """get 成功：200 + 实体含 agent_ids 反查（覆盖 L122-126 + L79）。"""
        svc = MagicMock()
        svc.get = AsyncMock(return_value=_mock_skill(1))
        with patch("inkflow.api.routers.skills._get_service", return_value=svc), patch(
            "inkflow.api.routers.skills.SQLiteAgentRepository"
        ) as mock_repo_cls:
            mock_repo_cls.return_value.list_agents_by_skill = AsyncMock(return_value=[])
            resp = await client.get(f"{ENDPOINT}/1")
        assert resp.status_code == 200
        assert str(resp.json()["id"]) == "1"
        assert resp.json()["agent_ids"] == []

    async def test_update_success_200(self, client) -> None:
        """update 成功：200 + 实体（覆盖 L136-140）。"""
        svc = MagicMock()
        svc.update = AsyncMock(return_value=_mock_skill(1, description="新描述"))
        with patch("inkflow.api.routers.skills._get_service", return_value=svc), patch(
            "inkflow.api.routers.skills.SQLiteAgentRepository"
        ) as mock_repo_cls:
            mock_repo_cls.return_value.list_agents_by_skill = AsyncMock(return_value=[])
            resp = await client.patch(f"{ENDPOINT}/1", json={"description": "新描述"})
        assert resp.status_code == 200
        assert resp.json()["description"] == "新描述"

    async def test_not_found_404_mapping(self, client) -> None:
        """服务层 SkillNotFoundError → 404（覆盖 L68-69 异常映射）。"""
        svc = MagicMock()
        svc.get = AsyncMock(side_effect=SkillNotFoundError())
        with patch("inkflow.api.routers.skills._get_service", return_value=svc):
            resp = await client.get(f"{ENDPOINT}/1")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Skill 不存在"

    async def test_builtin_409_mapping(self, client) -> None:
        """服务层 SkillBuiltinError → 409（覆盖 L70-71 异常映射）。"""
        svc = MagicMock()
        svc.delete = AsyncMock(side_effect=SkillBuiltinError())
        with patch("inkflow.api.routers.skills._get_service", return_value=svc):
            resp = await client.delete(f"{ENDPOINT}/1")
        assert resp.status_code == 409
        assert resp.json()["detail"]

    async def test_service_error_422_mapping(self, client) -> None:
        """服务层 SkillNameConflictError（SkillServiceError 子类）→ 422（覆盖 L72-73）。"""
        svc = MagicMock()
        svc.create = AsyncMock(side_effect=SkillNameConflictError())
        with patch("inkflow.api.routers.skills._get_service", return_value=svc):
            resp = await client.post(ENDPOINT, json={"content": VALID_CONTENT})
        assert resp.status_code == 422
        assert resp.json()["detail"]


# ── skill_service.py frontmatter 解析边界（真实 DB API 链）──


@pytest.mark.asyncio
@pytest.mark.api
class TestSkillFrontmatterEdges:
    """frontmatter 解析边界补覆盖：无起始块 / 未闭合 / 噪音行。

    _parse_frontmatter 为同步函数（create 首个语句，await 前）→ 真实 DB 模式
    可记录；补记 skill_service.py L182/L191/L194/L197（既有 test_skills_api.py
    只覆盖缺 name/description/name 非法）。
    """

    @pytest.mark.parametrize(
        "content",
        [
            "# 纯正文\n没有 frontmatter 块",  # 无 --- 起始块（L181-182）
            "---\nname: ok-skill\ndescription: 缺结束\n# 缺结束块",  # 未闭合（L196-197）
        ],
        ids=["missing_opening_block", "unclosed_block"],
    )
    async def test_frontmatter_block_errors_422(
        self, client, db_session, override_get_db, content
    ):
        """无 --- 起始块 / 未闭合 → 422 SkillFrontmatterError。"""
        resp = await client.post(ENDPOINT, json={"content": content})
        assert resp.status_code == 422
        assert resp.json()["detail"]

    @pytest.mark.parametrize(
        "content",
        [
            "---\n\n# 注释行\nname: ok-skill\ndescription: 噪音容忍\n---\n正文",
            # 空行 + # 注释行（L190-191 continue）
            "---\nname: ok-skill\n纯文本无冒号\ndescription: 无冒号容忍\n---\n正文",
            # 无冒号行（L193-194 continue）
        ],
        ids=["blank_and_comment_lines", "line_without_colon"],
    )
    async def test_frontmatter_noise_lines_201(
        self, client, db_session, override_get_db, content
    ):
        """frontmatter 含空行/# 注释/无冒号行 → 容忍跳过 → 201。"""
        resp = await client.post(ENDPOINT, json={"content": content})
        assert resp.status_code == 201
        assert resp.json()["name"] == "ok-skill"


# ── skill_service.py update 边界（service 层 mock）──


@pytest.mark.asyncio
class TestSkillServiceUpdateEdges:
    """update 边界补覆盖：L272 查重未命中分支 + L278-280 repo.update None。

    真实 DB 下 update 的 await（get_by_name/repo.update）后行不记录，且
    repo.update 恒返回实体（None 分支不可达）——直接构造 SkillService +
    mock 仓储补记（镜像 tests/unit/test_skill_service.py 形态）。
    """

    async def test_update_rename_no_conflict_merges(self) -> None:
        """name 变更但查重未命中 → 走 merged（skill_service L272 False 分支）。"""
        skill_repo = MagicMock(spec=SkillRepositoryProtocol)
        agent_repo = MagicMock(spec=AgentRepositoryProtocol)
        skill_repo.get = AsyncMock(return_value=_mock_skill(3, name="a"))
        skill_repo.get_by_name = AsyncMock(return_value=None)
        skill_repo.update = AsyncMock(side_effect=lambda s: s)
        svc = SkillService(skill_repository=skill_repo, agent_repository=agent_repo)

        merged = await svc.update(3, SkillUpdate(name="b"))
        assert merged.name == "b"
        skill_repo.get_by_name.assert_awaited_once()

    async def test_update_repo_returns_none_raises_not_found(self) -> None:
        """repo.update 返回 None（竞态已删）→ SkillNotFoundError（L278-280）。"""
        skill_repo = MagicMock(spec=SkillRepositoryProtocol)
        agent_repo = MagicMock(spec=AgentRepositoryProtocol)
        skill_repo.get = AsyncMock(return_value=_mock_skill(3, name="a"))
        skill_repo.update = AsyncMock(return_value=None)
        svc = SkillService(skill_repository=skill_repo, agent_repository=agent_repo)

        with pytest.raises(SkillNotFoundError, match="不存在"):
            await svc.update(3, SkillUpdate(description="d2"))
