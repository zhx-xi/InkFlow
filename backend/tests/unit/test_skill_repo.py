"""文件系统 Skill 存储单元测试（#522 P1）— 替代原 SQLiteSkillRepository DB 仓储测试。

背景: 本文件原为 F39 SQLiteSkillRepository coverage 补测（in-memory SQLite +
SkillORM 表）；#522 skill 存储架构重构（DB → 文件系统真源）后
SQLiteSkillRepository / SkillORM / SkillRepositoryProtocol 已从 src 真删，
旧测试因 import 失败而不可用（父侧事故曾恢复为 HEAD 旧版 231 行）。本文件按
统一契约（与 test_skill_service.py 同批，父侧定稿 2026-08-20）重建为文件系统
存储层测试：create/get/list/update/delete/duplicate 全部面向真实 tmp_path
目录断言（文件存在性、内容逐字、目录增删、级联清引用），并保留 DB 符号删除
守卫用例。

══════════════════ 设计假设（GREEN 实现契约，2026-08-20）══════════════════

1. 文件系统真源: skill 实体 = ``skills_root/<name>/SKILL.md``（不再落 DB 表）；
   ``SkillService(*, skills_root: Path, agent_repository: AgentRepositoryProtocol)``
   构造签名（不再注入 skill_repository），文件系统操作内联实现。
2. CRUD 语义: list 扫描 skills_root/*/SKILL.md 解析元数据按 name 升序；
   get/update/delete/duplicate 目标缺失 → SkillNotFoundError（404）；create/
   duplicate 同名目录已存在 → SkillNameConflictError（422）。
3. source 判定: 目录名 ∈ BUILTIN_SKILL_NAMES（6 英文 slug: architecture-
   methodology / writing-methodology / audit-methodology / revision-methodology /
   worldview-methodology / polishing-methodology）→ "builtin"（update/delete 只读
   409），否则 "user_upload"。
4. frontmatter 解析: create/update(content) 复用 inkflow.cli.skills_parser.
   parse_skill_metadata（N2: name 须=目录名）；缺失 name/description 或 name 格式
   非法 → SkillFrontmatterError（422）。
5. DB 形态符号真删: SkillRepositoryProtocol / SQLiteSkillRepository / SkillORM
   已从 src 删除，本文件不得正常 import；TestDbSymbolsRemoved 以
   pytest.raises(ImportError) 守卫其消失（回归恢复旧符号 → 守卫 FAIL）。

说明: 本批已是 GREEN 阶段（src 已实现文件系统真源），重建后本文件应全部
通过（pytest 全绿），不再呈现 RED FAIL 形态。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.agent import Agent
from inkflow.domain.models.skill import Skill, SkillCreate, SkillUpdate
from inkflow.domain.ports.skill_errors import (
    SkillBuiltinError,
    SkillFrontmatterError,
    SkillNameConflictError,
    SkillNotFoundError,
)
from inkflow.domain.services.skill_service import SkillService

VALID_CONTENT = (
    "---\nname: web-research\ndescription: 网络调研方法论\n---\n"
    "# 调研流程\n1. 明确问题\n2. 检索信源\n"
)
"""合法 SKILL.md 内容（frontmatter name=web-research + 描述 + 正文，N2 合规）。"""

NO_NAME_CONTENT = "---\ndescription: 网络调研方法论\n---\n# 无 name frontmatter"
NO_DESC_CONTENT = "---\nname: web-research\n---\n# 无 description frontmatter"
BAD_NAME_CONTENT = "---\nname: Web Research\ndescription: 网络调研方法论\n---\n# name 格式非法"


def _write_skill(
    root: Path,
    name: str,
    description: str = "测试技能",
    content: str | None = None,
) -> Path:
    """手工写一个 ``skills_root/<name>/SKILL.md``（模拟文件系统真源布局）.

    返回目录 Path；content 缺省时自动生成 frontmatter（name=目录名），
    保证可被 parse_skill_metadata 校验通过。
    """
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    body = (
        content
        if content is not None
        else (f"---\nname: {name}\ndescription: {description}\n---\n# {name}\n\n- 要点一\n")
    )
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")
    return skill_dir


def _make_service(skills_root: Path) -> SkillService:
    """按统一契约构造 SkillService（文件系统真源，不再注入 skill_repository）."""
    return SkillService(skills_root=skills_root, agent_repository=AsyncMock())


class TestModelContract:
    """契约点 1：Skill 领域模型删除 id 字段；DTO 形状不变。"""

    def test_skill_has_no_id_field(self) -> None:
        """Skill.model_fields 不含 "id"（DB 形态遗留 id → 本用例 FAIL）。"""
        assert "id" not in Skill.model_fields

    def test_skill_create_has_only_content(self) -> None:
        """SkillCreate 仍仅 content 必填（name/description 由服务层解析 frontmatter）。"""
        assert set(SkillCreate.model_fields) == {"content"}
        assert SkillCreate.model_fields["content"].is_required()

    def test_skill_update_all_optional(self) -> None:
        """SkillUpdate 仍全字段可选（exclude_unset 语义，None = 不修改）。"""
        for field in SkillUpdate.model_fields.values():
            assert not field.is_required()


class TestFileSystemList:
    """文件系统真源 list — 扫描 skills_root/*/SKILL.md 解析元数据，按 name 升序。"""

    async def test_list_empty_root_returns_empty(self, tmp_path: Path) -> None:
        """空根/根不存在 → []（无目录可扫，不抛错）。"""
        service = _make_service(tmp_path)
        assert await service.list() == []
        assert await _make_service(tmp_path / "missing").list() == []

    async def test_list_mixed_dirs_sorted_by_name_with_source(self, tmp_path: Path) -> None:
        """混合内置/用户/无 SKILL.md 目录 → 只收有 SKILL.md 的目录，按 name 升序；
        source 按目录名判定（∈ BUILTIN_SKILL_NAMES → builtin，否则 user_upload）。"""
        _write_skill(tmp_path, "z-skill", description="Z")
        _write_skill(tmp_path, "architecture-methodology", description="章节结构/大纲规划方法论")
        _write_skill(tmp_path, "a-skill", description="A")
        junk_dir = tmp_path / "no-skill-md"
        junk_dir.mkdir()
        (junk_dir / "README.md").write_text("x", encoding="utf-8")

        service = _make_service(tmp_path)
        items = await service.list()

        assert [s.name for s in items] == ["a-skill", "architecture-methodology", "z-skill"]
        by_name = {s.name: s for s in items}
        assert by_name["architecture-methodology"].source == "builtin"
        assert by_name["a-skill"].source == "user_upload"
        assert by_name["z-skill"].source == "user_upload"


class TestFileSystemGet:
    """文件系统真源 get — 按 name 读 SKILL.md（404 语义 / source 判定）。"""

    async def test_get_reads_skill_file_verbatim(self, tmp_path: Path) -> None:
        """get("web-research")：content 逐字读回、description 从 frontmatter 解析、
        source 判定为 user_upload；created_at/updated_at 为 mtime ISO 字符串或 None。"""
        _write_skill(tmp_path, "web-research", description="网络调研方法论", content=VALID_CONTENT)
        service = _make_service(tmp_path)

        skill = await service.get("web-research")

        assert skill.content == VALID_CONTENT
        assert skill.description == "网络调研方法论"
        assert skill.source == "user_upload"
        assert skill.created_at is None or isinstance(skill.created_at, str)
        assert skill.updated_at is None or isinstance(skill.updated_at, str)

    async def test_get_missing_raises_not_found(self, tmp_path: Path) -> None:
        """目录或 SKILL.md 缺失 → SkillNotFoundError（404 语义）。"""
        service = _make_service(tmp_path)
        with pytest.raises(SkillNotFoundError, match="不存在"):
            await service.get("ghost")


class TestCreate:
    """create — frontmatter 解析（复用 skills_parser）/ 同名 422 / 写文件表面。"""

    async def test_create_writes_skill_file_surface(self, tmp_path: Path) -> None:
        """create 成功：文件系统表面断言 —— skills_root/web-research/SKILL.md 真实
        存在且内容 == content（逐字）；返回 Skill 的 name/description 来自
        frontmatter、source="user_upload"。"""
        service = _make_service(tmp_path)

        saved = await service.create(SkillCreate(content=VALID_CONTENT))

        skill_file = tmp_path / "web-research" / "SKILL.md"
        assert skill_file.is_file()
        assert skill_file.read_text(encoding="utf-8") == VALID_CONTENT
        assert saved.name == "web-research"
        assert saved.description == "网络调研方法论"
        assert saved.content == VALID_CONTENT
        assert saved.source == "user_upload"

    async def test_create_same_name_conflict_raises_422(self, tmp_path: Path) -> None:
        """同名目录已存在 → SkillNameConflictError（422），原文件不被覆盖。"""
        _write_skill(tmp_path, "web-research", content="old content")
        service = _make_service(tmp_path)

        with pytest.raises(SkillNameConflictError, match="同名"):
            await service.create(SkillCreate(content=VALID_CONTENT))

        assert (tmp_path / "web-research" / "SKILL.md").read_text(encoding="utf-8") == "old content"

    async def test_create_frontmatter_invalid_rejected(self, tmp_path: Path) -> None:
        """frontmatter 缺失 name / 缺失 description / name 格式非法（大写+空格，N2
        违规）→ SkillFrontmatterError（422），根目录不落任何 skill 目录。"""
        service = _make_service(tmp_path)
        for bad in (NO_NAME_CONTENT, NO_DESC_CONTENT, BAD_NAME_CONTENT):
            with pytest.raises(SkillFrontmatterError, match="frontmatter"):
                await service.create(SkillCreate(content=bad))
        assert list(tmp_path.iterdir()) == []


class TestUpdate:
    """update — content PATCH 写回 + 新 frontmatter 重解析 / 内置只读 409 / 404。"""

    async def test_update_content_patches_file_and_reparses(self, tmp_path: Path) -> None:
        """update(content) → 磁盘 SKILL.md 整体替换（PATCH 写回），返回实体按新
        frontmatter 重解析（description 同步更新）。"""
        _write_skill(tmp_path, "web-research", content=VALID_CONTENT)
        new_content = "---\nname: web-research\ndescription: 网络调研方法论 v2\n---\n# v2\n"
        service = _make_service(tmp_path)

        updated = await service.update("web-research", SkillUpdate(content=new_content))

        assert (tmp_path / "web-research" / "SKILL.md").read_text(encoding="utf-8") == new_content
        assert updated.content == new_content
        assert updated.description == "网络调研方法论 v2"

    async def test_update_builtin_rejected_409_file_kept(self, tmp_path: Path) -> None:
        """内置 slug 目录 update → SkillBuiltinError（409），SKILL.md 不被改写。"""
        _write_skill(tmp_path, "architecture-methodology", description="章节结构/大纲规划方法论")
        service = _make_service(tmp_path)

        with pytest.raises(SkillBuiltinError, match="内置"):
            await service.update(
                "architecture-methodology",
                SkillUpdate(
                    content=("---\nname: architecture-methodology\n" "description: 篡改\n---\n"),
                ),
            )

        text = (tmp_path / "architecture-methodology" / "SKILL.md").read_text(encoding="utf-8")
        assert "篡改" not in text

    async def test_update_missing_raises_not_found(self, tmp_path: Path) -> None:
        """update 目标不存在 → SkillNotFoundError（404）。"""
        service = _make_service(tmp_path)
        with pytest.raises(SkillNotFoundError, match="不存在"):
            await service.update("ghost", SkillUpdate(description="d2"))


class TestDelete:
    """delete — 删整个目录 / 内置只读 409 / 级联清 Agent.skill_ids 引用。"""

    async def test_delete_removes_directory(self, tmp_path: Path) -> None:
        """delete 后 skills_root/<name>/ 整个目录消失；再次 delete → NotFound。"""
        _write_skill(tmp_path, "web-research", content=VALID_CONTENT)
        service = _make_service(tmp_path)

        await service.delete("web-research")

        assert not (tmp_path / "web-research").exists()
        with pytest.raises(SkillNotFoundError, match="不存在"):
            await service.delete("web-research")

    async def test_delete_builtin_rejected_409_directory_kept(self, tmp_path: Path) -> None:
        """内置 slug 目录 delete → SkillBuiltinError（409），目录与文件保留。"""
        _write_skill(tmp_path, "audit-methodology", description="一致性审计方法论")
        service = _make_service(tmp_path)

        with pytest.raises(SkillBuiltinError, match="内置"):
            await service.delete("audit-methodology")

        assert (tmp_path / "audit-methodology" / "SKILL.md").is_file()

    async def test_delete_cascades_clear_agent_skill_ids(self, tmp_path: Path) -> None:
        """被 N 个 Agent 引用: list_agents_by_skill(name) 反查 → 逐个从
        Agent.skill_ids 移除该目录名并 agent_repository.update（先清引用再删，
        §5.6）→ 最后删目录；其余字段保留。"""
        _write_skill(tmp_path, "web-research", content=VALID_CONTENT)
        writer = Agent(name="写手", skill_ids=["web-research", "other-skill"])
        architect = Agent(name="架构师", skill_ids=["web-research"])
        agent_repo = AsyncMock()
        agent_repo.list_agents_by_skill = AsyncMock(return_value=[writer, architect])
        agent_repo.update = AsyncMock(side_effect=lambda a: a)

        service = SkillService(skills_root=tmp_path, agent_repository=agent_repo)
        await service.delete("web-research")

        agent_repo.list_agents_by_skill.assert_awaited_once_with("web-research")
        assert agent_repo.update.await_count == 2
        assert writer.skill_ids == ["other-skill"]
        assert writer.name == "写手"
        assert architect.skill_ids == []
        assert not (tmp_path / "web-research").exists()


class TestDuplicate:
    """duplicate — 复制目录到 <name>-copy / 冲突 422 / 404。"""

    async def test_duplicate_creates_copy_directory(self, tmp_path: Path) -> None:
        """duplicate("web-research") → 新目录 web-research-copy/SKILL.md 内容逐字
        相同；返回 name="web-research-copy"、source="user_upload"；源目录保留。"""
        _write_skill(tmp_path, "web-research", description="网络调研方法论", content=VALID_CONTENT)
        service = _make_service(tmp_path)

        clone = await service.duplicate("web-research")

        copied = (tmp_path / "web-research-copy" / "SKILL.md").read_text(encoding="utf-8")
        assert copied == VALID_CONTENT
        assert clone.name == "web-research-copy"
        assert clone.content == VALID_CONTENT
        assert clone.source == "user_upload"
        assert (tmp_path / "web-research" / "SKILL.md").is_file()

    async def test_duplicate_conflict_raises_422(self, tmp_path: Path) -> None:
        """<name>-copy 目录已存在 → SkillNameConflictError（422），源目录不受影响。"""
        _write_skill(tmp_path, "web-research", content=VALID_CONTENT)
        _write_skill(tmp_path, "web-research-copy", content="existing")
        service = _make_service(tmp_path)

        with pytest.raises(SkillNameConflictError, match="同名"):
            await service.duplicate("web-research")

        assert (tmp_path / "web-research" / "SKILL.md").read_text(encoding="utf-8") == VALID_CONTENT

    async def test_duplicate_missing_raises_not_found(self, tmp_path: Path) -> None:
        """源缺失 → SkillNotFoundError（404），不产生副本目录。"""
        service = _make_service(tmp_path)
        with pytest.raises(SkillNotFoundError, match="不存在"):
            await service.duplicate("ghost")
        assert not (tmp_path / "ghost-copy").exists()


class TestDbSymbolsRemoved:
    """DB 符号守卫 — #522 语义变更真删：SkillORM / SQLiteSkillRepository /
    SkillRepositoryProtocol 必须从 src 消失，不得正常 import。"""

    def test_skill_orm_import_raises(self) -> None:
        """inkflow.infrastructure.database.models.skill 模块（含 SkillORM）已删除
        → import 抛 ImportError（ModuleNotFoundError 是其子类，同样捕获）。"""
        with pytest.raises(ImportError):
            from inkflow.infrastructure.database.models.skill import (
                SkillORM,  # noqa: F401 - 守卫用例：断言 DB 符号已删除（#522）
            )

    def test_sqlite_skill_repo_import_raises(self) -> None:
        """inkflow.infrastructure.database.repositories.skill_repo 模块
        （SQLiteSkillRepository）已删除 → import 抛 ImportError。"""
        with pytest.raises(ImportError):
            from inkflow.infrastructure.database.repositories.skill_repo import (
                SQLiteSkillRepository,  # noqa: F401 - 守卫用例：断言 DB 符号已删除（#522）
            )

    def test_skill_repository_protocol_import_raises(self) -> None:
        """inkflow.domain.ports.skill_repository 模块（SkillRepositoryProtocol）
        已删除 → import 抛 ImportError。"""
        with pytest.raises(ImportError):
            from inkflow.domain.ports.skill_repository import (
                SkillRepositoryProtocol,  # noqa: F401 - 守卫用例：断言 DB 符号已删除（#522）
            )
