"""#1331 内置 skill 版本化 + 项目级覆盖 — RED 契约测试（独立主题文件）。

契约来源
--------
``specs/f39-multi-agent/spec.md``（#1331 修订节：内置 skill 版本化 + 项目级覆盖）
``adr/memory-skills/ADR-040.md``（本单决策记录）

背景（issue #1331）
-------------------
内置 6 个方法论 skill 现行实现硬编码于 Python 字符串（``BUILTIN_SKILL_SPECS``），
``ensure_builtin_skills`` 语义为「存在即跳过」——既保证不覆盖用户改动（取证确认），
也导致**未修改的副本永远拿不到升级**。本单补齐：

1. 抽离为 ``i18n/skills/builtin/{zh,en}/<slug>.md``（frontmatter 带 ``version``）
2. 三态播种：缺失 → 写出；未改（内容指纹 == 基线）→ 升级；改过 → 保留
3. 项目级同名 skill 优先于全局（查找顺序 + 冲突可判）
4. 升级可见面（服务层 ``builtin_skill_status`` 供 API/CLI 消费）

═══════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试类）
═══════════════════════════════════════════════════════════════════

A. 抽离完整性 + 逐字守护
   - ``i18n/skills/builtin/zh/<slug>.md`` 6 份均存在；``builtin/en/`` 目录存在
     （槽位；本期 en 无正文，加载回退 zh——en 翻译另开 issue）。
   - 每份 md 的**正文**（frontmatter 之后的全部内容）与原 ``BUILTIN_SKILL_SPECS``
     content 正文逐字一致 → 以黄金 sha256 锚定（独立于实现的数值基线）。
   - ``BUILTIN_SKILL_SPECS`` 模块级符号保留（形态不变：list of
     {name, description, content}），内容改为从 md 加载 → 既有消费方零改。

B. 版本化
   - 每份 md frontmatter 含非空 ``version`` 字段（语义化版本字符串）。
   - ``builtin_skill_status(skills_root)`` 返回 6 条状态，含最新版 ``version``。

C. 播种三态（``ensure_builtin_skills(skills_root: Path) -> int``）
   - 返回「本次写入/更新的文件数」（保持既有契约语义：首次 6 / 重复 0 / 删 1 回补 1）。
   - 缺失 → 写最新出厂内容；
   - 存在且指纹 == 基线 ``origin_sha256``（未改）且出厂内容已变 → **升级**（覆盖）；
   - 存在且指纹 != 基线（用户改过）→ **保留用户版，不写**；
   - 首次引入（无基线条目）：不修改已有文件 —— 指纹与当期出厂一致则记「跟随升级」，
     不一致则记 ``user_modified=True``（保守：推定用户改过，永不自动覆盖）。

D. 基线载体
   - ``<skills_root>/.builtin_state.json``（JSON 映射 name → 状态）。与 ADR-039
     「文件系统唯一真源」一致，**不引 DB 表/列**。字段：
     ``{"version": str, "origin_sha256": str, "user_modified": bool}``。
   - 指纹口径 = ``read_text(encoding="utf-8")`` 全文的 sha256（文本行尾归一化，
     避免 Windows CRLF 造成跨机漂移）。

E. 项目级覆盖（本期落解析面，不接装配链）
   - 载体 ``data_dir/projects/<project_id>/skills/<name>/SKILL.md``（项目 overlay）。
   - ``resolve_skill_md_path(name, *, project_skills_root, global_skills_root)``：
     项目级命中 → 项目级路径；否则全局；都无 → None。
   - ``is_project_override(...)``：项目级与全局同名并存 → True。

RED 阶段预期：抽离文件与新符号均不存在 → ImportError stub（A/B/C/D/E 全 FAILED）；
既有 test_skill_service.py / test_builtin_seed.py 保持绿（本文件不改其契约）。
═══════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from inkflow.domain.services import skill_service
from inkflow.domain.services.skill_service import (
    BUILTIN_SKILL_NAMES,
    BUILTIN_SKILL_SPECS,
    ensure_builtin_skills,
)

# ── #1331 新符号惰性导入（RED 阶段 stub，GREEN 后真实实现命中）──

try:
    from inkflow.domain.services.skill_service import (
        builtin_skill_status,
        is_project_override,
        load_builtin_specs,
        resolve_skill_md_path,
    )
except ImportError:  # pragma: no cover - RED 阶段 stub
    builtin_skill_status = None  # type: ignore[assignment]  # RED stub：真实实现 GREEN 后覆盖
    is_project_override = None  # type: ignore[assignment]  # RED stub
    load_builtin_specs = None  # type: ignore[assignment]  # RED stub
    resolve_skill_md_path = None  # type: ignore[assignment]  # RED stub


# ── 黄金基线：改动前 6 份内置 skill 的【正文】sha256（独立于实现的数值锚）──
# 正文 = frontmatter 结束 --- 之后的全部内容（新增 version 行不改变正文）。
# 采自实施前 ``BUILTIN_SKILL_SPECS`` 实测值（W6-A 父侧探针）。
_GOLDEN_BODY_SHA256: dict[str, str] = {
    "architecture-methodology": "b38ac6549276f172a2eeb0ab01fa1488be8046b8a10d85d058ea510cf298c0e6",
    "writing-methodology": "0f774b7d0338aee40270def936d7d5f4e15dd32959571bae7e78a61973a2cfa3",
    "audit-methodology": "657491c541695f2209233fe82bf9cf60bd4f2c9c0e04f892c2213d30efedf325",
    "revision-methodology": "0d17a2b69469d5d890c99aa68656d36cfc46f99360200fb185c58bd3c54fa43c",
    "worldview-methodology": "2ac983fdb1a06f701e8efe6408544ec778333b55c4ffbc4500d2de1514352bb2",
    "polishing-methodology": "6c2654daab654359cb8d689b3dcd883385c436aad9f64578219031b5524abb52",
}

_STATE_FILENAME = ".builtin_state.json"


def _frontmatter_body(text: str) -> str:
    """返回 frontmatter 之后的正文（原样，含前导换行）。"""
    lines = text.splitlines(keepends=True)
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return "".join(lines[i + 1 :])
    return text


def _body_sha(text: str) -> str:
    return hashlib.sha256(_frontmatter_body(text).encode("utf-8")).hexdigest()


def _text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _builtin_md_root() -> Path:
    """包内内置 md 根：<inkflow>/i18n/skills/builtin。"""
    return Path(skill_service.__file__).resolve().parents[2] / "i18n" / "skills" / "builtin"


def _read_md(slug: str, locale: str = "zh") -> str:
    return (_builtin_md_root() / locale / f"{slug}.md").read_text(encoding="utf-8")


# ════════════════ A. 抽离完整性 + 逐字守护 ════════════════


class TestBuiltinSkillExtraction:
    """内置 skill 抽离为 md 文件，且正文与原字符串实现逐字一致。"""

    def test_zh_md_files_present(self) -> None:
        """6 份 zh md 文件均存在（抽离落点）。"""
        for slug in BUILTIN_SKILL_NAMES:
            path = _builtin_md_root() / "zh" / f"{slug}.md"
            assert path.is_file(), f"缺失抽离文件: {path}"

    def test_en_slot_present(self) -> None:
        """en 槽位目录存在（本期空；en 翻译另开 issue）。"""
        assert (_builtin_md_root() / "en").is_dir(), "缺失 en 槽位目录"

    @pytest.mark.parametrize("slug", BUILTIN_SKILL_NAMES)
    def test_md_body_verbatim_matches_golden(self, slug: str) -> None:
        """每份 md 正文 sha256 == 黄金基线（抽离不得改动/截断正文）。"""
        assert _body_sha(_read_md(slug)) == _GOLDEN_BODY_SHA256[slug], (
            f"{slug} 正文与改动前不一致（抽离引入内容漂移）"
        )

    @pytest.mark.parametrize("slug", BUILTIN_SKILL_NAMES)
    def test_specs_loaded_from_md_verbatim(self, slug: str) -> None:
        """模块级 BUILTIN_SKILL_SPECS 的 content 正文 == 黄金基线（loader 正确）。"""
        spec = next(s for s in BUILTIN_SKILL_SPECS if s["name"] == slug)
        assert _body_sha(spec["content"]) == _GOLDEN_BODY_SHA256[slug]

    def test_load_builtin_specs_en_falls_back_to_zh(self) -> None:
        """en 无正文时 load_builtin_specs('en') 回退 zh（内容与 zh 一致）。"""
        assert load_builtin_specs is not None, "RED: 缺 load_builtin_specs 符号"
        zh = {s["name"]: s["content"] for s in load_builtin_specs("zh")}
        en = {s["name"]: s["content"] for s in load_builtin_specs("en")}
        assert set(zh) == set(BUILTIN_SKILL_NAMES)
        for slug in BUILTIN_SKILL_NAMES:
            assert _body_sha(en[slug]) == _body_sha(zh[slug]), f"{slug} en 未回退 zh"


# ════════════════ B. 版本化 ════════════════


class TestBuiltinVersioning:
    """内置 md 带版本号 frontmatter；状态查询暴露最新版本。"""

    @pytest.mark.parametrize("slug", BUILTIN_SKILL_NAMES)
    def test_md_frontmatter_has_version(self, slug: str) -> None:
        """每份 md frontmatter 含非空 version。"""
        head = _read_md(slug).split("---")[1]
        versioned = [ln for ln in head.splitlines() if ln.strip().startswith("version:")]
        assert versioned, f"{slug} frontmatter 缺 version 字段"
        assert versioned[0].split(":", 1)[1].strip(), f"{slug} version 为空"

    def test_status_reports_six_with_version(self, tmp_path: Path) -> None:
        """builtin_skill_status 返回 6 条，latest_version 非空。"""
        assert builtin_skill_status is not None, "RED: 缺 builtin_skill_status 符号"
        rows = builtin_skill_status(tmp_path)
        assert {r.name for r in rows} == set(BUILTIN_SKILL_NAMES)
        for row in rows:
            assert row.latest_version, f"{row.name} latest_version 为空"


# ════════════════ C. 播种三态 ════════════════


class TestSeedSemantics:
    """ensure_builtin_skills 三态：缺失写 / 未改升级 / 改过保留。"""

    def test_first_call_writes_six(self, tmp_path: Path) -> None:
        assert ensure_builtin_skills(tmp_path) == 6

    def test_user_modified_copy_is_preserved(self, tmp_path: Path) -> None:
        """核心（有牙）：用户改过的副本，再次 ensure 内容保持用户版。"""
        assert ensure_builtin_skills(tmp_path) == 6
        slug = BUILTIN_SKILL_NAMES[0]
        target = tmp_path / slug / "SKILL.md"
        edited = target.read_text(encoding="utf-8").replace("# ", "# [USER] ")
        target.write_text(edited, encoding="utf-8")

        assert ensure_builtin_skills(tmp_path) == 0, "用户改过的副本不得被写入"
        assert target.read_text(encoding="utf-8") == edited, "用户版内容被覆盖（数据丢失）"

    def test_unmodified_older_release_is_upgraded(self, tmp_path: Path) -> None:
        """未改的旧版（指纹 == 基线）应升级为当期出厂内容。"""
        assert ensure_builtin_skills(tmp_path) == 6
        slug = BUILTIN_SKILL_NAMES[1]
        target = tmp_path / slug / "SKILL.md"
        latest = target.read_text(encoding="utf-8")

        # 造「旧版出厂」：内容为上一版，基线登记该旧指纹（用户未改 → 指纹一致）
        older = latest.replace("version: 1.0.0", "version: 0.9.0", 1)
        assert older != latest
        target.write_text(older, encoding="utf-8")
        state_path = tmp_path / _STATE_FILENAME
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state[slug] = {
            "version": "0.9.0",
            "origin_sha256": _text_sha(older),
            "user_modified": False,
        }
        state_path.write_text(json.dumps(state), encoding="utf-8")

        assert ensure_builtin_skills(tmp_path) == 1, "未改的旧版必须升级（写 1）"
        assert target.read_text(encoding="utf-8") == latest, "未升级为当期出厂内容"

    def test_new_builtin_spec_is_seeded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """新增内置 skill（出厂集合扩容）→ 正常播种。"""
        extra = {
            "name": "extra-methodology",
            "description": "扩展方法论",
            "content": "---\nname: extra-methodology\ndescription: 扩展方法论\n---\n\n# 扩展\n",
        }
        monkeypatch.setattr(
            skill_service, "BUILTIN_SKILL_SPECS", [*BUILTIN_SKILL_SPECS, extra], raising=False
        )
        assert ensure_builtin_skills(tmp_path) == 7
        assert (tmp_path / "extra-methodology" / "SKILL.md").is_file()

    def test_deleted_builtin_is_replenished(self, tmp_path: Path) -> None:
        """删 1 个内置目录 → 回补 1（既有幂等语义保持）。"""
        assert ensure_builtin_skills(tmp_path) == 6
        shutil.rmtree(tmp_path / "audit-methodology")
        assert ensure_builtin_skills(tmp_path) == 1


# ════════════════ D. 项目级覆盖（解析面） ════════════════


class TestProjectOverride:
    """项目级同名 skill 优先于全局；冲突可判。"""

    @staticmethod
    def _write(root: Path, name: str, marker: str) -> Path:
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        f = d / "SKILL.md"
        f.write_text(
            f"---\nname: {name}\ndescription: {marker}\n---\n\n# {marker}\n", encoding="utf-8"
        )
        return f

    def test_project_takes_precedence(self, tmp_path: Path) -> None:
        assert resolve_skill_md_path is not None, "RED: 缺 resolve_skill_md_path 符号"
        proj, glob = tmp_path / "proj", tmp_path / "global"
        self._write(proj, "writing-methodology", "项目版")
        self._write(glob, "writing-methodology", "全局版")
        got = resolve_skill_md_path(
            "writing-methodology", project_skills_root=proj, global_skills_root=glob
        )
        assert got is not None and got == proj / "writing-methodology" / "SKILL.md"

    def test_global_fallback_when_project_absent(self, tmp_path: Path) -> None:
        proj, glob = tmp_path / "proj", tmp_path / "global"
        self._write(glob, "writing-methodology", "全局版")
        got = resolve_skill_md_path(
            "writing-methodology", project_skills_root=proj, global_skills_root=glob
        )
        assert got is not None and got == glob / "writing-methodology" / "SKILL.md"

    def test_missing_returns_none(self, tmp_path: Path) -> None:
        proj, glob = tmp_path / "proj", tmp_path / "global"
        assert (
            resolve_skill_md_path("nope", project_skills_root=proj, global_skills_root=glob) is None
        )

    def test_none_project_root_falls_back_global(self, tmp_path: Path) -> None:
        glob = tmp_path / "global"
        self._write(glob, "audit-methodology", "全局版")
        got = resolve_skill_md_path(
            "audit-methodology", project_skills_root=None, global_skills_root=glob
        )
        assert got is not None and got == glob / "audit-methodology" / "SKILL.md"

    def test_is_project_override_flag(self, tmp_path: Path) -> None:
        assert is_project_override is not None, "RED: 缺 is_project_override 符号"
        proj, glob = tmp_path / "proj", tmp_path / "global"
        self._write(proj, "writing-methodology", "项目版")
        self._write(glob, "writing-methodology", "全局版")
        assert is_project_override(
            "writing-methodology", project_skills_root=proj, global_skills_root=glob
        )
        assert not is_project_override(
            "writing-methodology", project_skills_root=tmp_path / "empty", global_skills_root=glob
        )


# ════════════════ E. 反例守护：播种结果逐字一致 ════════════════


class TestSeedParity:
    """抽离后 ensure 写出的内置内容与原实现逐字一致（防内容漂移）。"""

    @pytest.mark.parametrize("slug", BUILTIN_SKILL_NAMES)
    def test_seeded_file_body_verbatim(self, tmp_path: Path, slug: str) -> None:
        assert ensure_builtin_skills(tmp_path) == 6
        written = (tmp_path / slug / "SKILL.md").read_text(encoding="utf-8")
        assert _body_sha(written) == _GOLDEN_BODY_SHA256[slug], f"{slug} 播种内容与改动前不一致"
