"""`domain/services/skill_assembly.py` 单元测试（#1472 下沉纯函数）。

覆盖：`append_skills`（base 前 skill 后 / 查不到跳过 / 多 skill 顺序）、
`read_skill_content`（存在/缺失/不可读）、`file_skill_lookup`（命中 → FileSkill）。
"""

from __future__ import annotations

from inkflow.domain.services.skill_assembly import (
    FileSkill,
    append_skills,
    file_skill_lookup,
    read_skill_content,
)


class _Skill:
    """含 name/content 的鸭子对象（镜像 Skill 实体字段）。"""

    def __init__(self, name: str, content: str) -> None:
        self.name = name
        self.content = content


def _lookup(mapping: dict[str, object]) -> object:
    return lambda name: mapping.get(name)


class TestAppendSkills:
    def test_empty_ids_returns_base_unchanged(self) -> None:
        """白名单为空 → base 逐字符不变（零回归）。"""
        assert append_skills("BASE", [], _lookup({})) == "BASE"

    def test_missing_skill_skipped(self) -> None:
        """白名单目录名查不到 → 跳过（防御语义，不抛错）。"""
        assert append_skills("BASE", ["nope"], _lookup({})) == "BASE"

    def test_single_skill_appended_after_base(self) -> None:
        """命中 → base 在前，skill 以固定格式追加在后。"""
        result = append_skills("BASE", ["a"], _lookup({"a": _Skill("a", "AAA")}))
        assert result == "BASE\n\n# 技能：a\n\nAAA\n\n---\n"

    def test_multiple_skills_keep_whitelist_order(self) -> None:
        """多 skill → 按白名单顺序拼接（顺序固定）。"""
        lookup = _lookup({"a": _Skill("a", "AAA"), "b": _Skill("b", "BBB")})
        result = append_skills("BASE", ["b", "a"], lookup)
        assert result.index("BBB") < result.index("AAA")

    def test_skill_without_name_content_attrs_uses_empty(self) -> None:
        """鸭子对象缺 name/content 属性 → 取空串（getattr 防御）。"""
        result = append_skills("BASE", ["x"], _lookup({"x": object()}))
        assert result == "BASE\n\n# 技能：\n\n\n\n---\n"


class TestReadSkillContent:
    def test_reads_skill_md(self, tmp_path) -> None:
        (tmp_path / "s1").mkdir()
        (tmp_path / "s1" / "SKILL.md").write_text("正文", encoding="utf-8")
        assert read_skill_content(tmp_path, "s1") == "正文"

    def test_missing_returns_none(self, tmp_path) -> None:
        assert read_skill_content(tmp_path, "ghost") is None

    def test_directory_without_file_returns_none(self, tmp_path) -> None:
        (tmp_path / "empty").mkdir()
        assert read_skill_content(tmp_path, "empty") is None


class TestFileSkillLookup:
    def test_hit_returns_file_skill(self, tmp_path) -> None:
        (tmp_path / "s1").mkdir()
        (tmp_path / "s1" / "SKILL.md").write_text("c", encoding="utf-8")
        skill = file_skill_lookup(tmp_path)("s1")
        assert isinstance(skill, FileSkill)
        assert skill.name == "s1"
        assert skill.content == "c"

    def test_miss_returns_none(self, tmp_path) -> None:
        assert file_skill_lookup(tmp_path)("ghost") is None
