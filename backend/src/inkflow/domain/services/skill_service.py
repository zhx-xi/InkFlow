"""Skill 业务服务 — 文件系统真源 CRUD + frontmatter 解析 + 删除级联清引用.

职责（spec §2.2/§3.3/§5.6/§7 + ADR-039 #522）:
- 文件系统真源：skill 实体 = data_dir/skills/<name>/SKILL.md（不再落 DB
  表）；list 扫描 skills_root/*/SKILL.md，get/create/update/delete/
  duplicate 全部内联文件系统操作（不再注入 skill_repository）
- frontmatter 后端解析（422）：create/update(content) 复用
  inkflow.cli.skills_parser.parse_skill_metadata（N2 严格规则
  ^[a-z0-9]+(-[a-z0-9]+)*$，name 须=目录名）；失败 → SkillFrontmatterError
- 同名唯一性校验（422）：create/duplicate 前检查同名目录已存在 →
  SkillNameConflictError
- 资源不存在（404 语义）：get/update/delete/duplicate 目标缺失 →
  SkillNotFoundError
- source 判定：目录名 ∈ BUILTIN_SKILL_NAMES（6 英文 slug）→ "builtin"
  （只读 409），否则 "user_upload"
- delete：source="builtin" → SkillBuiltinError（409）；被 N 个 Agent
  引用 → 先级联清引用（逐个移除 Agent.skill_ids 中的该目录名并
  agent_repository.update）再删目录（spec §5.6）
- 时间戳契约：created_at/updated_at 为 SKILL.md 文件 mtime ISO 字符串
  （create/update 写盘后读取；不锁精确值）

依赖通过构造函数注入（ADR-015，测试注入 Mock）；文件系统操作内联实现。
"""

from __future__ import annotations

import builtins
import difflib
import hashlib
import json
import logging
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.cli.skills_parser import SkillMetadata, SkillValidationError, parse_skill_metadata
from inkflow.domain.models.skill import Skill, SkillCreate, SkillUpdate
from inkflow.domain.ports.agent_repository import AgentRepositoryProtocol
from inkflow.domain.ports.skill_errors import (
    SkillBuiltinError,
    SkillFrontmatterError,
    SkillNameConflictError,
    SkillNotFoundError,
)
from inkflow.domain.services._data_change import publish_change

logger = logging.getLogger(__name__)


BUILTIN_SKILL_NAMES: list[str] = [
    "architecture-methodology",
    "writing-methodology",
    "audit-methodology",
    "revision-methodology",
    "worldview-methodology",
    "polishing-methodology",
]
"""内置 6 Skill 出厂目录名（英文 slug，N2 合规；顺序 = ensure_builtin_skills 写出序）."""


class _BuiltinSkillSpec(TypedDict):
    """内置 Skill 出厂配置项（spec §5.3，content = 完整 SKILL.md）."""

    name: str
    description: str
    content: str


_BUILTIN_MD_SUBDIR: tuple[str, str, str] = ("i18n", "skills", "builtin")
"""包内内置 md 根相对包根的子目录（#1331 抽离落点）."""

_DEFAULT_BUILTIN_LOCALE = "zh"
"""内置 md 默认语言（en 槽位无正文时回退源，#1331）."""

BUILTIN_SKILL_LOCALES: tuple[str, ...] = ("zh", "en")
"""内置 md 语言槽位（本期 en 无正文，加载回退 zh；en 翻译另开 issue）."""


def builtin_skills_md_root() -> Path:
    """包内内置 md 根：<inkflow pkg>/i18n/skills/builtin（#1331）."""
    return Path(__file__).resolve().parents[2].joinpath(*_BUILTIN_MD_SUBDIR)


def _frontmatter_version(text: str) -> str | None:
    """取 frontmatter 的 version 原值（缺失/空 → None，#1331）."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        key, sep, value = stripped.partition(":")
        if sep and key.strip() == "version":
            parsed = value.strip().strip('"').strip("'")
            return parsed or None
    return None


def _builtin_md_path(slug: str, locale: str) -> Path:
    """内置 md 路径；locale 侧缺失 → 回退默认语言（en → zh，#1331）."""
    root = builtin_skills_md_root()
    candidate = root / locale / f"{slug}.md"
    if candidate.is_file():
        return candidate
    return root / _DEFAULT_BUILTIN_LOCALE / f"{slug}.md"


def load_builtin_specs(locale: str = "zh") -> list[_BuiltinSkillSpec]:
    """从包内 md 加载内置 specs（顺序 == BUILTIN_SKILL_NAMES，#1331）.

    content = 完整 md 文本（frontmatter + 正文，原样）；description 复用
    parse_skill_metadata 解析（与 frontmatter 一致）；单 slug 文件缺失 →
    回退默认语言（zh）。
    """
    specs: list[_BuiltinSkillSpec] = []
    for slug in BUILTIN_SKILL_NAMES:
        content = _builtin_md_path(slug, locale).read_text(encoding="utf-8")
        try:
            description = parse_skill_metadata(content, slug).description
        except SkillValidationError:
            description = ""
        specs.append({"name": slug, "description": description, "content": content})
    return specs


BUILTIN_SKILL_SPECS: list[_BuiltinSkillSpec] = load_builtin_specs()
"""内置 6 Skill 出厂配置（#1331 起由 loader 从包内 md 读取，顺序 = BUILTIN_SKILL_NAMES）."""


def _source_of(name: str) -> str:
    """source 判定：目录名 ∈ BUILTIN_SKILL_NAMES → "builtin"，否则 "user_upload"."""
    return "builtin" if name in BUILTIN_SKILL_NAMES else "user_upload"


def _mtime_iso(path: Path) -> str:
    """文件 mtime → ISO 8601 字符串（UTC，datetime.fromisoformat 可解析）."""
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()


def _frontmatter_name(content: str) -> str:
    """提取 content frontmatter 的 name 原值（未校验；缺失 → ""）."""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        key, sep, value = stripped.partition(":")
        if not sep:
            continue
        if key.strip() == "name":
            return value.strip().strip('"').strip("'")
    return ""


def _parse_upload(content: str, directory_name: str) -> SkillMetadata:
    """解析并校验 content frontmatter；失败 → SkillFrontmatterError（422）."""
    try:
        return parse_skill_metadata(content, directory_name)
    except SkillValidationError as err:
        raise SkillFrontmatterError() from err


class SkillService:
    """Skill 业务服务 — 文件系统真源 CRUD + frontmatter 解析 + 删除级联清引用.

    Args:
        skills_root: skill 文件系统真源根（data_dir/skills）.
        agent_repository: Agent 仓储端口（删除级联清引用用）.
    """

    def __init__(
        self,
        *,
        skills_root: Path,
        agent_repository: AgentRepositoryProtocol,
    ) -> None:
        self._skills_root = skills_root
        self._agent_repo = agent_repository

    async def create(self, data: SkillCreate) -> Skill:
        """创建用户上传 Skill（frontmatter 解析 → 同名查重 → 写文件）.

        目录名 = frontmatter name（parse_skill_metadata 强制 name == 目录名
        且匹配 N2）；同名目录已存在 → SkillNameConflictError（422）；成功
        → 写出 skills_root/<name>/SKILL.md（content 原样）并返回实体。
        """
        meta = _parse_upload(data.content, _frontmatter_name(data.content))
        name = meta.name
        target_dir = self._skills_root / name
        if target_dir.exists():
            raise SkillNameConflictError()
        self._skills_root.mkdir(parents=True, exist_ok=True)
        target_dir.mkdir(parents=True, exist_ok=True)
        skill_file = target_dir / "SKILL.md"
        skill_file.write_text(data.content, encoding="utf-8")
        logger.info("创建 Skill: name=%s", name)
        created: Skill = Skill(
            name=name,
            description=meta.description,
            content=data.content,
            source="user_upload",
            created_at=_mtime_iso(skill_file),
            updated_at=_mtime_iso(skill_file),
        )
        await publish_change("skill", "create", name, None)
        return created

    async def get(self, name: str) -> Skill:
        """按目录名读 skills_root/<name>/SKILL.md → Skill；缺失 → SkillNotFoundError（404）."""
        skill_file = self._skills_root / name / "SKILL.md"
        if not skill_file.is_file():
            raise SkillNotFoundError()
        content = skill_file.read_text(encoding="utf-8")
        description = ""
        try:
            description = parse_skill_metadata(content, name).description
        except SkillValidationError:
            description = ""
        return Skill(
            name=name,
            description=description,
            content=content,
            source=_source_of(name),
            created_at=_mtime_iso(skill_file),
            updated_at=_mtime_iso(skill_file),
        )

    async def list(self) -> builtins.list[Skill]:
        """列出全部 Skill（扫描 skills_root/*/SKILL.md 解析元数据，按 name 升序）."""
        if not self._skills_root.is_dir():
            return []
        items: builtins.list[Skill] = []
        for child in sorted(self._skills_root.iterdir(), key=lambda p: p.name):
            if not child.is_dir():
                continue
            skill_file = child / "SKILL.md"
            if not skill_file.is_file():
                continue
            content = skill_file.read_text(encoding="utf-8")
            description = ""
            try:
                description = parse_skill_metadata(content, child.name).description
            except SkillValidationError:
                description = ""
            items.append(
                Skill(
                    name=child.name,
                    description=description,
                    content=content,
                    source=_source_of(child.name),
                    created_at=_mtime_iso(skill_file),
                    updated_at=_mtime_iso(skill_file),
                )
            )
        return sorted(items, key=lambda s: s.name)

    async def update(self, name: str, data: SkillUpdate) -> Skill:
        """部分更新 Skill（文件系统真源）.

        None 值 = 不修改（exclude_unset 浅合并，同 F1/F13）；content 变更
        → 整文件写回 + 按新 frontmatter 重解析（非法 → SkillFrontmatterError）；
        内置目录 → SkillBuiltinError（409）；目标缺失 → SkillNotFoundError。
        """
        existing = await self.get(name)
        if existing.source == "builtin":
            raise SkillBuiltinError()
        updates = {
            k: getattr(data, k) for k in data.model_fields_set if getattr(data, k) is not None
        }
        if "content" in updates:
            content = updates["content"]
            _parse_upload(content, name)
            skill_file = self._skills_root / name / "SKILL.md"
            skill_file.write_text(content, encoding="utf-8")
            logger.info("更新 Skill: name=%s", name)
            await publish_change("skill", "update", name, None)
            return await self.get(name)
        if not updates:
            return existing
        merged = existing.model_copy(update=updates)
        logger.info("更新 Skill（元数据合并）: name=%s", name)
        return merged

    async def delete(self, name: str) -> None:
        """删除 Skill（内置只读 → 409；被引用 → 先级联清引用再删目录）.

        全部引用 Agent 的 update（清 skill_ids）先于目录删除（spec §5.6）；
        目标缺失 → SkillNotFoundError。
        """
        existing = await self.get(name)
        if existing.source == "builtin":
            raise SkillBuiltinError()
        refs = await self._agent_repo.list_agents_by_skill(name)
        for agent in refs:
            agent.skill_ids = [sid for sid in agent.skill_ids if sid != name]
            await self._agent_repo.update(agent)  # type: ignore[call-arg, arg-type]  # 测试 docstring 契约：update 以完整实体单参调用（G2 repo 签名双参形态兼容，见 agent_repo.update）
        target_dir = self._skills_root / name
        if target_dir.is_dir():
            shutil.rmtree(target_dir)
        logger.info("删除 Skill: name=%s", name)
        await publish_change("skill", "delete", name, None)

    async def duplicate(self, name: str, *, new_name: str | None = None) -> Skill:
        """复制 Skill（#485 语义延续 + #522 文件系统真源）.

        新名 = 指定名或 f"{name}-copy"；副本目录已存在 → SkillNameConflictError
        （422）；源缺失 → SkillNotFoundError；成功 → 复制整个目录并返回
        副本实体（source="user_upload"）。
        """
        existing = await self.get(name)
        target_name = new_name or f"{name}-copy"
        target_dir = self._skills_root / target_name
        if target_dir.exists():
            raise SkillNameConflictError()
        src_dir = self._skills_root / name
        shutil.copytree(src_dir, target_dir)
        logger.info("复制 Skill: name=%s → %s", name, target_name)
        duplicated: Skill = Skill(
            name=target_name,
            description=existing.description,
            content=existing.content,
            source="user_upload",
            created_at=_mtime_iso(target_dir / "SKILL.md"),
            updated_at=_mtime_iso(target_dir / "SKILL.md"),
        )
        await publish_change("skill", "create", target_name, None)
        return duplicated


_SKILL_FILENAME = "SKILL.md"
"""Skill 正文文件名（目录名 = slug）."""

_BUILTIN_STATE_FILENAME = ".builtin_state.json"
"""内置 skill 基线状态文件（<skills_root> 下；非 skill，不计入 SKILL.md 扫描/计数）."""


class _BuiltinStateEntry(TypedDict):
    """单个内置 slug 的基线状态（ADR-062）."""

    version: str
    origin_sha256: str
    user_modified: bool


def _state_entry(version: str, origin_sha256: str, *, user_modified: bool) -> _BuiltinStateEntry:
    """构造基线状态条目（字段全集，避免部分写入）."""
    return {
        "version": version,
        "origin_sha256": origin_sha256,
        "user_modified": user_modified,
    }


def _text_sha256(text: str) -> str:
    """全文 sha256（read_text 文本口径，CRLF/LF 归一，跨机稳定）."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_builtin_state(skills_root: Path) -> dict[str, _BuiltinStateEntry]:
    """读 <skills_root>/.builtin_state.json；缺失/损坏/非法 → {}（不抛错）."""
    state_path = skills_root / _BUILTIN_STATE_FILENAME
    try:
        raw: object = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    state: dict[str, _BuiltinStateEntry] = {}
    for slug, entry in raw.items():
        if not isinstance(slug, str) or not isinstance(entry, dict):
            continue
        version = entry.get("version")
        origin = entry.get("origin_sha256")
        modified = entry.get("user_modified")
        state[slug] = _state_entry(
            version if isinstance(version, str) else "",
            origin if isinstance(origin, str) else "",
            user_modified=bool(modified),
        )
    return state


def _save_builtin_state(skills_root: Path, state: dict[str, _BuiltinStateEntry]) -> None:
    """写 <skills_root>/.builtin_state.json（ensure 收敛后落盘）."""
    (skills_root / _BUILTIN_STATE_FILENAME).write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _latest_builtin_content(name: str) -> str | None:
    """当期出厂 content（按 name 查 BUILTIN_SKILL_SPECS；兜底读包内 md；非内置 → None）."""
    for spec in BUILTIN_SKILL_SPECS:
        if spec["name"] == name:
            return spec["content"]
    if name not in BUILTIN_SKILL_NAMES:
        return None
    path = _builtin_md_path(name, _DEFAULT_BUILTIN_LOCALE)
    return path.read_text(encoding="utf-8") if path.is_file() else None


def ensure_builtin_skills(skills_root: Path) -> int:
    """三态播种内置 SKILL.md（ADR-039 回补 + ADR-062 版本化）.

    每 slug 按基线（<skills_root>/.builtin_state.json）判定：

    - 文件缺失 → 写出当期出厂内容并记基线（计 +1）
    - 已标记 user_modified → 保守冻结，永不自动覆盖
    - 内容 == 当期出厂内容 → 只刷新基线，不重写文件
    - 指纹 == 基线 origin_sha256（用户未改）且出厂内容已变 → 升级覆盖（计 +1）
    - 其余（无基线且内容 ≠ 出厂 / 指纹 ≠ 基线）→ 保留用户副本，标 user_modified=True

    返回本次实际写入/升级的文件数（既有幂等契约：首次 6 / 重复 0 / 删 1 回补 1）。
    """
    skills_root.mkdir(parents=True, exist_ok=True)
    state = _load_builtin_state(skills_root)
    written = 0
    for spec in BUILTIN_SKILL_SPECS:
        name = spec["name"]
        content = spec["content"]
        version = _frontmatter_version(content) or ""
        target = skills_root / name / _SKILL_FILENAME
        entry = state.get(name)
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            state[name] = _state_entry(version, _text_sha256(content), user_modified=False)
            written += 1
            continue
        if entry is not None and entry["user_modified"]:
            # ADR-062：一旦判定为用户定制（含「改了又改回」），永不自动覆盖。
            continue
        installed = target.read_text(encoding="utf-8")
        installed_sha = _text_sha256(installed)
        if installed == content:
            state[name] = _state_entry(version, installed_sha, user_modified=False)
            continue
        origin = entry["origin_sha256"] if entry is not None else ""
        if origin and installed_sha == origin:
            target.write_text(content, encoding="utf-8")
            state[name] = _state_entry(version, _text_sha256(content), user_modified=False)
            written += 1
            continue
        state[name] = _state_entry(
            entry["version"] if entry is not None else "",
            origin or installed_sha,
            user_modified=True,
        )
    _save_builtin_state(skills_root, state)
    return written


@dataclass(frozen=True)
class BuiltinSkillStatus:
    """内置 skill 的安装/版本/定制状态行（ADR-062 升级可见面）."""

    name: str
    latest_version: str
    installed: bool
    installed_version: str | None
    user_modified: bool
    has_update: bool


def builtin_skill_status(skills_root: Path) -> list[BuiltinSkillStatus]:
    """返回出厂 slug 的状态行（顺序 == BUILTIN_SKILL_NAMES，ADR-062）.

    - installed_version：安装文件 frontmatter 的 version（不可解析 → 基线记录值）；
      未安装 → 基线记录值 → None
    - user_modified：基线标记，或安装内容既 != 基线 origin 又 != 当期出厂内容
    - has_update：未安装，或（未定制且安装内容 != 当期出厂内容）
    """
    state = _load_builtin_state(skills_root)
    rows: list[BuiltinSkillStatus] = []
    for name in BUILTIN_SKILL_NAMES:
        latest_content = _latest_builtin_content(name)
        if latest_content is None:
            continue
        latest_version = _frontmatter_version(latest_content) or ""
        entry = state.get(name)
        target = skills_root / name / _SKILL_FILENAME
        installed = target.is_file()
        installed_text = target.read_text(encoding="utf-8") if installed else ""
        installed_version = _frontmatter_version(installed_text) if installed else None
        if installed_version is None and entry is not None and entry["version"]:
            installed_version = entry["version"]
        origin = entry["origin_sha256"] if entry is not None else ""
        baseline_modified = entry["user_modified"] if entry is not None else False
        if installed:
            drifted = installed_text != latest_content and (
                not origin or _text_sha256(installed_text) != origin
            )
            user_modified = baseline_modified or drifted
        else:
            user_modified = False
        has_update = not installed or (not user_modified and installed_text != latest_content)
        rows.append(
            BuiltinSkillStatus(
                name=name,
                latest_version=latest_version,
                installed=installed,
                installed_version=installed_version,
                user_modified=user_modified,
                has_update=has_update,
            )
        )
    return rows


def builtin_skill_diff(name: str, skills_root: Path) -> dict[str, str | None] | None:
    """安装版 vs 当期出厂版的 unified diff；非内置 slug → None（ADR-062）.

    ``diff`` 为 ``difflib.unified_diff`` 文本（未安装或内容一致 → ""）。
    """
    latest_content = _latest_builtin_content(name)
    if latest_content is None:
        return None
    entry = _load_builtin_state(skills_root).get(name)
    target = skills_root / name / _SKILL_FILENAME
    installed_text = target.read_text(encoding="utf-8") if target.is_file() else ""
    installed_version = _frontmatter_version(installed_text) if installed_text else None
    if installed_version is None and entry is not None and entry["version"]:
        installed_version = entry["version"]
    if not installed_text or installed_text == latest_content:
        diff = ""
    else:
        diff = "".join(
            difflib.unified_diff(
                installed_text.splitlines(keepends=True),
                latest_content.splitlines(keepends=True),
                fromfile=f"{name}/SKILL.md (installed)",
                tofile=f"{name}/SKILL.md (latest)",
            )
        )
    return {
        "name": name,
        "installed_version": installed_version,
        "latest_version": _frontmatter_version(latest_content) or "",
        "diff": diff,
    }


def resolve_skill_md_path(
    name: str, *, project_skills_root: Path | None, global_skills_root: Path
) -> Path | None:
    """解析 skill 真源路径：项目级优先 → 全局；都不存在 → None（ADR-062）."""
    if project_skills_root is not None:
        project_candidate = project_skills_root / name / _SKILL_FILENAME
        if project_candidate.is_file():
            return project_candidate
    global_candidate = global_skills_root / name / _SKILL_FILENAME
    if global_candidate.is_file():
        return global_candidate
    return None


def is_project_override(
    name: str, *, project_skills_root: Path | None, global_skills_root: Path
) -> bool:
    """项目级与全局同名 skill 并存 → True（ADR-062 冲突可判）."""
    if project_skills_root is None:
        return False
    return (project_skills_root / name / _SKILL_FILENAME).is_file() and (
        global_skills_root / name / _SKILL_FILENAME
    ).is_file()


async def migrate_skills_from_db(session: AsyncSession, skills_root: Path) -> int:
    """一次性迁移旧 skills 表 user_upload 行 → 写出文件后清表（ADR-039 D3c=A）.

    raw SQL 实现（sqlalchemy.text），不得依赖 SkillORM；表不存在 → 0（不抛
    错、不重建旧表）；迁移后 DELETE 全部行（含 builtin 行）；返回迁移条数。
    """
    skills_root.mkdir(parents=True, exist_ok=True)
    try:
        result = await session.execute(
            text("SELECT name, content FROM skills WHERE source = 'user_upload'")
        )
    except Exception:
        # 旧库无 skills 表（全新安装/表已被清）→ 无存量可迁移
        await session.rollback()
        return 0
    rows = result.all()
    migrated = 0
    for row in rows:
        name = str(row[0])
        content = str(row[1])
        skill_dir = skills_root / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
        migrated += 1
    await session.execute(text("DELETE FROM skills"))
    await session.commit()
    logger.info("迁移旧 skills 表: %s 条 user_upload 行写出文件", migrated)
    return migrated
