"""SkillService 契约单元测试（#522 P1 RED 批）— 文件系统真源形态，替代原 DB-mock 契约。

原文件（439 行）以双 Mock 仓储（skill_repository + agent_repository）注入测 DB
形态 SkillService；#522 后 SkillService 构造签名改为
``SkillService(*, skills_root: Path, agent_repository: AgentRepositoryProtocol)``
（不再注入 skill_repository，文件系统操作内联实现），本文件按新签名重写契约：
create/get/list/update/delete/duplicate 全部面向真实 tmp_path 目录断言，并保留
错误类守卫用例。

══════════════════ 设计假设（GREEN 实现契约，父侧统一契约 2026-08-20）══════════════════

1. ``Skill`` 领域模型删除 id 字段；保留 name/description/content/source/
   created_at/updated_at（created_at/updated_at 为文件 mtime ISO 字符串或
   None，不锁精确值）。SkillCreate 仍仅 content；SkillUpdate 仍全可选。
2. ``SkillService(*, skills_root: Path, agent_repository: AgentRepositoryProtocol)``
   ——不再注入 skill_repository；文件系统操作内联实现：
   - list: 扫描 skills_root/<name>/SKILL.md 解析元数据，按 name 升序
   - get(name): 读 SKILL.md；缺失 → SkillNotFoundError
   - create: frontmatter 解析（可复用 skills_parser.parse_skill_metadata，
     name 须=目录名）→ 写 skills_root/<name>/SKILL.md；同名目录已存在 →
     SkillNameConflictError（422）
   - update(name, SkillUpdate): PATCH 写回 SKILL.md；source="builtin" →
     SkillBuiltinError（409）；缺失 → SkillNotFoundError
   - delete(name): 删整个目录；source="builtin" → SkillBuiltinError（409）；
     缺失 → SkillNotFoundError；被 N 个 Agent 引用（agent_repository.
     list_agents_by_skill(name)——语义为精确含目录名）→ 先逐个移除
     Agent.skill_ids 中的该 name 并 agent_repository.update 再删（§5.6 级联）
   - duplicate(name): 复制目录到 skills_root/<name>-copy/（命名 f"{name}-copy"），
     冲突 → SkillNameConflictError（422）；缺失 → SkillNotFoundError
3. 内置 6 skill 改名英文 slug 常量：BUILTIN_SKILL_NAMES / BUILTIN_SKILL_SPECS
   的 name = architecture-methodology / writing-methodology /
   audit-methodology / revision-methodology / worldview-methodology /
   polishing-methodology（N2 合规：小写字母数字+单连字符；content 内 frontmatter
   name 与目录名同步）；description/content 保持中文；中文名仅作 history 注释。
4. source 判定不变：目录名 ∈ BUILTIN_SKILL_NAMES → "builtin"（只读 409），否则
   "user_upload"。
5. ``ensure_builtin_skills(skills_root: Path) -> int``（模块级，替代
   seed_builtin_skills(session)）：目录不存在或内置缺失 → 写出 6 个内置
   SKILL.md（幂等：已存在跳过、删了回补），返回本次写入数。RED 期该符号不存在
   → 顶部 try/except ImportError stub 为 None，用例以断言 FAIL（规则 5 惰性导入）。
6. 级联语义变更：agent_repository.list_agents_by_skill 入参从 skill_id:int 变为
   skill 目录名（精确含）；Agent.skill_ids 存 skill 目录名列表。
7. frontmatter 解析失败（缺失 name/description / name 格式非法 / name≠目录名）
   → SkillFrontmatterError（422，既有错误面与错误类不变，仅实现从手写解析器
   切换为 skills_parser 可复用函数）。

⚠️ RED 预期: 当前 src 仍是 DB 形态（构造签名 ``SkillService(*,
skill_repository=, agent_repository=)``；Skill 带 id 字段；BUILTIN_SKILL_NAMES
为中文；无 ensure_builtin_skills 符号）→
- 服务契约用例：每个用例体内 ``SkillService(skills_root=...)`` 抛
  TypeError: unexpected keyword argument 'skills_root' → FAILED
- 守卫用例：Skill.model_fields 含 id → AssertionError；BUILTIN_SKILL_NAMES
  为中文 ≠ 英文 slug → AssertionError；ensure_builtin_skills 为 None →
  AssertionError
GREEN 后本文件应全绿。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from inkflow.cli.skills_parser import parse_skill_metadata
from inkflow.domain.models.agent import Agent
from inkflow.domain.models.skill import Skill, SkillCreate, SkillUpdate
from inkflow.domain.ports.skill_errors import (
    SkillBuiltinError,
    SkillFrontmatterError,
    SkillNameConflictError,
    SkillNotFoundError,
    SkillServiceError,
)
from inkflow.domain.services.skill_service import (
    BUILTIN_SKILL_NAMES,
    BUILTIN_SKILL_SPECS,
    SkillService,
    _frontmatter_name,
)

try:
    from inkflow.domain.services.skill_service import ensure_builtin_skills
except ImportError:  # RED 期：旧实现无此符号（seed_builtin_skills(session) 形态）
    ensure_builtin_skills = None  # type: ignore[assignment]  # RED 期 stub：真实函数 GREEN 后覆盖

BUILTIN_SLUGS = [
    "architecture-methodology",
    "writing-methodology",
    "audit-methodology",
    "revision-methodology",
    "worldview-methodology",
    "polishing-methodology",
]

VALID_CONTENT = (
    "---\nname: web-research\ndescription: 网络调研方法论\n---\n"
    "# 调研流程\n1. 明确问题\n2. 检索信源\n"
)
NO_NAME_CONTENT = "---\ndescription: 网络调研方法论\n---\n# 无 name frontmatter"
NO_DESC_CONTENT = "---\nname: web-research\n---\n# 无 description frontmatter"
BAD_NAME_CONTENT = "---\nname: Web Research\ndescription: 网络调研方法论\n---\n# name 格式非法"


def _write_skill(
    root: Path,
    name: str,
    description: str = "测试技能",
    content: str | None = None,
) -> Path:
    """手工写一个 ``skills_root/<name>/SKILL.md``（模拟文件系统真源布局）."""
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
    """按统一契约构造 SkillService（文件系统真源，无 skill_repository 注入）.

    RED 期（旧实现 DB 形态）此调用抛
    TypeError: __init__() got an unexpected keyword argument 'skills_root'
    —— 本文件预期 FAIL 主形态（每个用例体内构造，保证 pytest 记 FAILED 而非
    收集期/夹具 ERROR）。
    """
    return SkillService(skills_root=skills_root, agent_repository=AsyncMock())


class TestModelContract:
    """契约点 1：Skill 领域模型删除 id；DTO 形状不变。"""

    def test_skill_has_no_id_field(self) -> None:
        """Skill.model_fields 不含 "id"（RED 期 DB 形态含 id → AssertionError FAIL）。"""
        assert "id" not in Skill.model_fields

    def test_skill_create_has_only_content(self) -> None:
        """SkillCreate 仍仅 content 必填（name/description 由服务层解析 frontmatter）。"""
        assert set(SkillCreate.model_fields) == {"content"}
        assert SkillCreate.model_fields["content"].is_required()

    def test_skill_update_all_optional(self) -> None:
        """SkillUpdate 仍全字段可选（exclude_unset 语义，None = 不修改）。"""
        for field in SkillUpdate.model_fields.values():
            assert not field.is_required()


class TestBuiltinConstants:
    """契约点 3：内置 6 skill 英文 slug 常量（N2 合规）。"""

    def test_builtin_names_are_english_slugs(self) -> None:
        """BUILTIN_SKILL_NAMES 逐字 == 6 个英文 slug（RED 期为中文名 → 本用例 FAIL）。"""
        assert BUILTIN_SKILL_NAMES == BUILTIN_SLUGS

    def test_builtin_specs_frontmatter_synced_with_slug(self) -> None:
        """每个 spec：name == 英文 slug；description/content 保持中文；content 内
        frontmatter name 与目录名（slug）同步且可被 parse_skill_metadata 校验通过。"""
        assert [s["name"] for s in BUILTIN_SKILL_SPECS] == BUILTIN_SLUGS
        for spec in BUILTIN_SKILL_SPECS:
            assert spec["description"]  # 中文描述非空
            meta = parse_skill_metadata(spec["content"], spec["name"])
            assert meta.name == spec["name"]
            assert meta.description == spec["description"]


class TestEnsureBuiltinSkills:
    """契约点 5：ensure_builtin_skills(skills_root) 幂等写出 6 个内置 SKILL.md。"""

    def test_ensure_writes_six_builtin_skills(self, tmp_path: Path) -> None:
        """空根目录 → 写出 6 个内置 SKILL.md，返回 6；每个目录的 SKILL.md
        frontmatter name == 目录名（英文 slug）。"""
        assert (
            ensure_builtin_skills is not None
        ), "RED: old impl lacks ensure_builtin_skills (GREEN contract 5)"
        n = ensure_builtin_skills(tmp_path)
        assert n == 6
        dirs = sorted(p.name for p in tmp_path.iterdir() if p.is_dir())
        assert dirs == sorted(BUILTIN_SLUGS)
        for slug in BUILTIN_SLUGS:
            md = tmp_path / slug / "SKILL.md"
            assert md.is_file()
            text = md.read_text(encoding="utf-8")
            assert f"name: {slug}" in text  # frontmatter name 与目录名同步
            meta = parse_skill_metadata(text, slug)
            assert meta.name == slug

    def test_ensure_idempotent_and_backfills(self, tmp_path: Path) -> None:
        """幂等：二次调用返回 0（已存在跳过）；删除一个内置目录后再次调用 →
        回补该目录并返回 1。"""
        assert (
            ensure_builtin_skills is not None
        ), "RED 期旧实现无 ensure_builtin_skills——GREEN 契约点 5"
        assert ensure_builtin_skills(tmp_path) == 6
        assert ensure_builtin_skills(tmp_path) == 0  # 已存在 → 跳过
        shutil.rmtree(tmp_path / "writing-methodology")
        assert ensure_builtin_skills(tmp_path) == 1  # 删了回补
        assert (tmp_path / "writing-methodology" / "SKILL.md").is_file()


class TestCreate:
    """create — frontmatter 解析（复用 skills_parser）/ 同名 422 / 写文件。"""

    async def test_create_parses_frontmatter_and_writes_file(self, tmp_path: Path) -> None:
        """create 成功：返回 Skill（name/description 来自 frontmatter、content 原样、
        source="user_upload"、created_at/updated_at 为 mtime ISO 字符串或 None），
        且 skills_root/web-research/SKILL.md 真实落盘。"""
        service = _make_service(tmp_path)
        saved = await service.create(SkillCreate(content=VALID_CONTENT))

        assert saved.name == "web-research"
        assert saved.description == "网络调研方法论"
        assert saved.content == VALID_CONTENT
        assert saved.source == "user_upload"
        assert "id" not in saved.model_fields
        assert saved.created_at is None or isinstance(saved.created_at, str)
        assert saved.updated_at is None or isinstance(saved.updated_at, str)
        assert (tmp_path / "web-research" / "SKILL.md").read_text(encoding="utf-8") == VALID_CONTENT

    async def test_create_missing_name_rejected(self, tmp_path: Path) -> None:
        """frontmatter 缺失 name → SkillFrontmatterError（422），不落盘。"""
        service = _make_service(tmp_path)
        with pytest.raises(SkillFrontmatterError, match="frontmatter"):
            await service.create(SkillCreate(content=NO_NAME_CONTENT))
        assert not (tmp_path / "web-research").exists()

    async def test_create_missing_description_rejected(self, tmp_path: Path) -> None:
        """frontmatter 缺失 description → SkillFrontmatterError（422），不落盘。"""
        service = _make_service(tmp_path)
        with pytest.raises(SkillFrontmatterError, match="frontmatter"):
            await service.create(SkillCreate(content=NO_DESC_CONTENT))
        assert not (tmp_path / "web-research").exists()

    async def test_create_illegal_name_rejected(self, tmp_path: Path) -> None:
        """frontmatter name 格式非法（大写/空格，须 1-64 小写字母数字+单连字符）
        → SkillFrontmatterError（422），根目录不留任何 skill 目录。"""
        service = _make_service(tmp_path)
        with pytest.raises(SkillFrontmatterError, match="frontmatter"):
            await service.create(SkillCreate(content=BAD_NAME_CONTENT))
        assert list(tmp_path.iterdir()) == []

    async def test_create_name_conflict_raises_422(self, tmp_path: Path) -> None:
        """同名目录已存在 → SkillNameConflictError（422），原文件不被覆盖。"""
        _write_skill(tmp_path, "web-research", content="old content")
        service = _make_service(tmp_path)
        with pytest.raises(SkillNameConflictError, match="同名"):
            await service.create(SkillCreate(content=VALID_CONTENT))
        assert (tmp_path / "web-research" / "SKILL.md").read_text(encoding="utf-8") == "old content"


class TestGet:
    """get — 按 name 读 SKILL.md（404 语义 / builtin source 判定）。"""

    async def test_get_reads_skill_file(self, tmp_path: Path) -> None:
        """get("web-research") 读回文件：content 逐字、description 解析、source 判定。"""
        _write_skill(tmp_path, "web-research", description="网络调研方法论", content=VALID_CONTENT)
        service = _make_service(tmp_path)
        skill = await service.get("web-research")
        assert skill.content == VALID_CONTENT
        assert skill.description == "网络调研方法论"
        assert skill.source == "user_upload"

    async def test_get_missing_raises_not_found(self, tmp_path: Path) -> None:
        """目标不存在 → SkillNotFoundError（消息「Skill 不存在」）。"""
        service = _make_service(tmp_path)
        with pytest.raises(SkillNotFoundError, match="不存在"):
            await service.get("ghost")

    async def test_get_builtin_source_detected(self, tmp_path: Path) -> None:
        """内置 slug 目录 → source="builtin"（契约点 4：目录名 ∈ BUILTIN_SKILL_NAMES）。"""
        _write_skill(tmp_path, "revision-methodology", description="修订打磨方法论")
        service = _make_service(tmp_path)
        skill = await service.get("revision-methodology")
        assert skill.source == "builtin"


class TestList:
    """list — 扫描目录解析元数据，按 name 升序。"""

    async def test_list_empty_returns_empty(self, tmp_path: Path) -> None:
        """空根 → []。"""
        service = _make_service(tmp_path)
        assert await service.list() == []

    async def test_list_sorted_by_name_with_sources(self, tmp_path: Path) -> None:
        """混合内置/用户目录 → 按 name 升序；source 按目录名判定（契约点 4）。"""
        _write_skill(tmp_path, "z-skill", description="Z")
        _write_skill(tmp_path, "architecture-methodology", description="章节结构/大纲规划方法论")
        _write_skill(tmp_path, "a-skill", description="A")
        service = _make_service(tmp_path)
        items = await service.list()
        assert [s.name for s in items] == ["a-skill", "architecture-methodology", "z-skill"]
        by_name = {s.name: s for s in items}
        assert by_name["architecture-methodology"].source == "builtin"
        assert by_name["a-skill"].source == "user_upload"
        assert by_name["z-skill"].source == "user_upload"


class TestUpdate:
    """update — PATCH 写回 / 内置只读 409 / 404。"""

    async def test_update_content_patches_file(self, tmp_path: Path) -> None:
        """update content → 磁盘 SKILL.md 整体替换（PATCH 写回），返回实体按新
        frontmatter 重解析。"""
        _write_skill(tmp_path, "web-research", content=VALID_CONTENT)
        new_content = "---\nname: web-research\ndescription: 网络调研方法论 v2\n---\n# v2\n"
        service = _make_service(tmp_path)
        updated = await service.update("web-research", SkillUpdate(content=new_content))
        assert (tmp_path / "web-research" / "SKILL.md").read_text(encoding="utf-8") == new_content
        assert updated.content == new_content
        assert updated.description == "网络调研方法论 v2"

    async def test_update_builtin_rejected_409(self, tmp_path: Path) -> None:
        """内置 slug 目录 update → SkillBuiltinError（409），文件不被改写。"""
        _write_skill(tmp_path, "architecture-methodology", description="章节结构/大纲规划方法论")
        service = _make_service(tmp_path)
        with pytest.raises(SkillBuiltinError, match="内置"):
            await service.update(
                "architecture-methodology",
                SkillUpdate(
                    content="---\nname: architecture-methodology\ndescription: 篡改\n---\n",
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
    """delete — 删目录 / 内置只读 409 / 级联清 Agent.skill_ids 引用。"""

    async def test_delete_removes_directory(self, tmp_path: Path) -> None:
        """delete 后目录消失；再次 delete → SkillNotFoundError。"""
        _write_skill(tmp_path, "web-research", content=VALID_CONTENT)
        service = _make_service(tmp_path)
        await service.delete("web-research")
        assert not (tmp_path / "web-research").exists()
        with pytest.raises(SkillNotFoundError, match="不存在"):
            await service.delete("web-research")

    async def test_delete_builtin_rejected_409(self, tmp_path: Path) -> None:
        """内置 slug 目录 delete → SkillBuiltinError（409），目录保留。"""
        _write_skill(tmp_path, "audit-methodology", description="一致性审计方法论")
        service = _make_service(tmp_path)
        with pytest.raises(SkillBuiltinError, match="内置"):
            await service.delete("audit-methodology")
        assert (tmp_path / "audit-methodology" / "SKILL.md").is_file()

    async def test_delete_missing_raises_not_found(self, tmp_path: Path) -> None:
        """目标不存在 → SkillNotFoundError（404），无副作用。"""
        service = _make_service(tmp_path)
        with pytest.raises(SkillNotFoundError, match="不存在"):
            await service.delete("ghost")

    async def test_delete_cascades_clear_skill_ids(self, tmp_path: Path) -> None:
        """被 N 个 Agent 引用：list_agents_by_skill(name)（语义：精确含目录名）反查
        → 逐个从 Agent.skill_ids 移除该 name 并 update（先清引用再删，§5.6）
        → 最后删目录。delete 返回后：目录消失、全部 update 已调用、其余字段保留。"""
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
        assert writer.skill_ids == ["other-skill"]  # 该 name 已移除，其他字段保留
        assert writer.name == "写手"
        assert architect.skill_ids == []
        assert not (tmp_path / "web-research").exists()  # 级联完成后目录已删


class TestDuplicate:
    """duplicate — f"{name}-copy" 命名 / 冲突 422 / 404（契约点 8）。"""

    async def test_duplicate_creates_copy_with_suffix(self, tmp_path: Path) -> None:
        """duplicate("web-research") → 新目录 web-research-copy/SKILL.md 内容逐字
        相同；返回 name="web-research-copy"、source="user_upload"；源目录保留。"""
        _write_skill(tmp_path, "web-research", description="网络调研方法论", content=VALID_CONTENT)
        service = _make_service(tmp_path)
        clone = await service.duplicate("web-research")
        assert clone.name == "web-research-copy"
        assert clone.content == VALID_CONTENT
        assert clone.description == "网络调研方法论"
        assert clone.source == "user_upload"
        copied = (tmp_path / "web-research-copy" / "SKILL.md").read_text(encoding="utf-8")
        assert copied == VALID_CONTENT
        assert (tmp_path / "web-research" / "SKILL.md").is_file()

    async def test_duplicate_builtin_copy_is_user(self, tmp_path: Path) -> None:
        """复制内置 slug → 副本 <slug>-copy 非内置名 → user_upload（#485 语义延续）。"""
        _write_skill(tmp_path, "worldview-methodology", description="世界观一致性方法论")
        service = _make_service(tmp_path)
        clone = await service.duplicate("worldview-methodology")
        assert clone.name == "worldview-methodology-copy"
        assert clone.source == "user_upload"

    async def test_duplicate_conflict_raises_422(self, tmp_path: Path) -> None:
        """<name>-copy 已存在 → SkillNameConflictError（422），源目录不受影响。"""
        _write_skill(tmp_path, "web-research", content=VALID_CONTENT)
        _write_skill(tmp_path, "web-research-copy", content="existing")
        service = _make_service(tmp_path)
        with pytest.raises(SkillNameConflictError, match="同名"):
            await service.duplicate("web-research")
        assert (tmp_path / "web-research" / "SKILL.md").read_text(encoding="utf-8") == VALID_CONTENT

    async def test_duplicate_missing_raises_not_found(self, tmp_path: Path) -> None:
        """目标不存在 → SkillNotFoundError（404），不产生副本目录。"""
        service = _make_service(tmp_path)
        with pytest.raises(SkillNotFoundError, match="不存在"):
            await service.duplicate("ghost")
        assert not (tmp_path / "ghost-copy").exists()


class TestSkillErrorsGuard:
    """错误类守卫：默认文案 + 继承关系 + 不导出他域错误类（规则 1m，既有契约保留）。"""

    def test_error_default_messages_and_hierarchy(self) -> None:
        """4 错误类默认消息逐字 + 继承关系（镜像 agent_template_errors.py）。"""
        assert str(SkillNotFoundError()) == "Skill 不存在"
        assert str(SkillNameConflictError()) == "同名 Skill 已存在（Skill 名称必须唯一）"
        assert str(SkillBuiltinError()) == "内置 Skill 不可修改或删除"
        assert str(SkillFrontmatterError()) == "frontmatter 缺失 name/description 或 name 格式非法"
        # 422/409 类继承 SkillServiceError；404 类独立（镜像 agent_template_errors）
        assert issubclass(SkillNameConflictError, SkillServiceError)
        assert issubclass(SkillBuiltinError, SkillServiceError)
        assert issubclass(SkillFrontmatterError, SkillServiceError)
        assert not issubclass(SkillNotFoundError, SkillServiceError)
        assert issubclass(SkillServiceError, Exception)

    def test_no_foreign_error_classes_leaked(self) -> None:
        """skill_errors 不导出 Agent 系错误类（防复制粘贴残留）。"""
        import inkflow.domain.ports.skill_errors as skill_errors_module

        assert not hasattr(skill_errors_module, "AgentNotFoundError")
        assert not hasattr(skill_errors_module, "AgentNameConflictError")
        assert not hasattr(skill_errors_module, "AgentBuiltinError")


class TestCoverageGapDefensiveBranches:
    """coverage-gap #522：skill_service.py 防御/边缘分支补测（缺失行 L181/L188/L254-255/
    L272/L280-281/L315；L395 由 tests/integration/test_builtin_seed.py 的
    test_table_missing_returns_0 已覆盖，此处不重复）。补测直接通过，不改 src/。"""

    def test_frontmatter_name_empty_or_no_delimiter_returns_empty(self) -> None:
        """_frontmatter_name：content 为空 / 首行非 --- → 返回 ""（L180-181 防御分支）。

        coverage-gap #522 L181：现有用例只走正常路径（首行 ---），空 content 与
        无 frontmatter 文本的早退分支未覆盖。
        """
        assert _frontmatter_name("") == ""
        assert _frontmatter_name("没有 frontmatter 分隔符的正文") == ""

    def test_frontmatter_name_skips_lines_without_colon(self) -> None:
        """_frontmatter_name：frontmatter 行无冒号（如 "no-colon-line"）→ 跳过继续（L187-188）。

        coverage-gap #522 L188：frontmatter 内混入无冒号行时 `if not sep: continue`
        分支未覆盖；本用例在其后仍有 name 行，断言最终提取到 name。
        """
        content = (
            "---\n"
            "no-colon-line\n"
            "name: web-research\n"
            "description: 网络调研方法论\n"
            "---\n"
            "# 正文\n"
        )
        assert _frontmatter_name(content) == "web-research"

    async def test_get_invalid_frontmatter_description_empty(self, tmp_path: Path) -> None:
        """get：SKILL.md frontmatter 缺 name（SkillValidationError）→ 不抛错且
        description=""（L253-255 except 分支）。

        coverage-gap #522 L254-255：文件存在但 frontmatter 非法时 get 的
        except SkillValidationError 兜底未覆盖。
        """
        _write_skill(tmp_path, "web-research", content=NO_NAME_CONTENT)
        service = _make_service(tmp_path)

        skill = await service.get("web-research")

        assert skill.name == "web-research"
        assert skill.description == ""
        assert skill.content == NO_NAME_CONTENT

    async def test_list_skips_non_directory_entries(self, tmp_path: Path) -> None:
        """list：skills_root 下混入普通文件（非目录）→ 跳过（L271-272 continue）。

        coverage-gap #522 L272：现有 list 用例只混入「无 SKILL.md 的目录」，混入
        普通文件（is_dir() False）的 continue 分支未覆盖。
        """
        _write_skill(tmp_path, "web-research", description="网络调研方法论")
        (tmp_path / "loose-file.txt").write_text("非目录文件", encoding="utf-8")
        service = _make_service(tmp_path)

        items = await service.list()

        assert [s.name for s in items] == ["web-research"]

    async def test_list_invalid_frontmatter_description_empty(self, tmp_path: Path) -> None:
        """list：某目录 SKILL.md frontmatter 非法 → 该条目 description="" 仍出现在
        列表（L279-281 except 分支）。

        coverage-gap #522 L280-281：list 扫描时单目录 frontmatter 非法 → except
        SkillValidationError 兜底 description="" 未覆盖。
        """
        _write_skill(tmp_path, "good-skill", description="合法技能")
        _write_skill(tmp_path, "bad-skill", content=NO_NAME_CONTENT)
        service = _make_service(tmp_path)

        items = await service.list()
        by_name = {s.name: s for s in items}

        assert "bad-skill" in by_name
        assert by_name["bad-skill"].description == ""
        assert by_name["good-skill"].description == "合法技能"

    async def test_update_empty_dto_returns_existing(self, tmp_path: Path) -> None:
        """update：空 DTO（无字段变更，model_fields_set 为空）→ 直接返回现有实体
        且不写盘（L314-315）。

        coverage-gap #522 L315：`if not updates: return existing` 早退分支未覆盖。
        """
        _write_skill(tmp_path, "web-research", description="网络调研方法论")
        service = _make_service(tmp_path)
        before = (tmp_path / "web-research" / "SKILL.md").read_text(encoding="utf-8")

        updated = await service.update("web-research", SkillUpdate())

        assert updated.name == "web-research"
        assert updated.description == "网络调研方法论"
        assert (tmp_path / "web-research" / "SKILL.md").read_text(encoding="utf-8") == before
