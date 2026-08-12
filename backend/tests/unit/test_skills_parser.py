"""skills frontmatter 解析/校验纯函数测试（F19-skills spec §2.2/§7，RED 阶段）。

GREEN 契约（实现 inkflow.cli.skills_parser）：
- SkillMetadata dataclass：name: str / description: str / license: str | None /
  compatibility: str | None / metadata: dict[str, Any] | None / allowed_tools: list[str] | None
|- SkillValidationError(Exception)：code: str（SKILLS_INVALID_FRONTMATTER |
|  SKILLS_INVALID_NAME）+ message: str
- parse_skill_metadata(text: str, directory_name: str) -> SkillMetadata：
  - N1：缺 name（key 缺失或空串）/ 缺 description（key 缺失或空串）/ 无 frontmatter（无 --- 定界）/
    YAML 解析失败 → SkillValidationError(SKILLS_INVALID_FRONTMATTER)
  - N2：name 存在且非空但非法——非 1-64 字符 / 非小写字母数字单连字符（含 _、大写、--、首尾 -）/
    != directory_name → SkillValidationError(SKILLS_INVALID_NAME)
  - N3：description 超 1024 字符 → 截断到 1024 +
    warnings.warn("SKILLS_DESCRIPTION_TRUNCATED...", UserWarning)，不抛错
  - 可选字段宽容（deepagents 策略）：license/compatibility 非标量、metadata 非 dict、
    allowed-tools 非 list → 忽略该字段 + warnings.warn(..., UserWarning)，不抛错
- YAML 解析用 yaml.safe_load；frontmatter 定界为文件首行 --- 与后续 --- 之间的块

RED 预期形态：收集成功（20 用例 collected）；执行时 fixture 惰性 import 失败 →
全部用例因 ImportError 失败（ERROR/FAILED，exit 1）——不使用顶部 import 以守护
tests/unit 套件 sys.modules 干净性契约（test_http_client.py TestImportSurface）。
"""

from __future__ import annotations

import importlib
import warnings

import pytest


@pytest.fixture(scope="module")
def sp():
    """执行期惰性 import inkflow.cli.skills_parser。

    RED 阶段触发 ImportError（用例失败=正确 RED）；不用顶部 import 是避免 pytest
    收集阶段把 inkflow.cli 载入 sys.modules，破坏 tests/unit 套件守护契约
    test_http_client.py::TestImportSurface::test_no_cli_import_on_http_import。
    """
    return importlib.import_module("inkflow.cli.skills_parser")


# RED 阶段模块不存在 → 收集期 ModuleNotFoundError（预期）
VALID_FRONTMATTER = """---
name: web-research
description: 网络调研技能
license: MIT
compatibility: Python 3.11
metadata:
  version: 1.0.0
allowed-tools:
  - read_file
---
# Skill 正文
"""


def _frontmatter(name: str = "web-research", description: str = "网络调研技能") -> str:
    """构造合法 frontmatter 文本（可覆盖 name/description）。"""
    return f"""---
name: {name}
description: {description}
---
# 正文
"""


class TestParseValid:
    def test_valid_full(self, sp):
        """合法完整 frontmatter → 全字段解析。"""
        meta = sp.parse_skill_metadata(VALID_FRONTMATTER, "web-research")
        assert meta.name == "web-research"
        assert meta.description == "网络调研技能"
        assert meta.license == "MIT"
        assert meta.compatibility == "Python 3.11"
        assert meta.metadata == {"version": "1.0.0"}
        assert meta.allowed_tools == ["read_file"]

    def test_valid_minimal(self, sp):
        """仅 name+description 的最小 frontmatter → 可选字段默认 None。"""
        meta = sp.parse_skill_metadata(_frontmatter(), "web-research")
        assert meta.name == "web-research"
        assert meta.description == "网络调研技能"
        assert meta.license is None
        assert meta.compatibility is None
        assert meta.metadata is None
        assert meta.allowed_tools is None


class TestFrontmatterErrors:
    def test_missing_name(self, sp):
        """缺 name → N1 SKILLS_INVALID_FRONTMATTER。"""
        text = _frontmatter().replace("name: web-research\n", "")
        with pytest.raises(sp.SkillValidationError) as exc:
            sp.parse_skill_metadata(text, "web-research")
        assert exc.value.code == "SKILLS_INVALID_FRONTMATTER"

    def test_empty_name(self, sp):
        """name 空串 → 视为缺必填字段 → N1。"""
        with pytest.raises(sp.SkillValidationError) as exc:
            sp.parse_skill_metadata(_frontmatter(name=""), "web-research")
        assert exc.value.code == "SKILLS_INVALID_FRONTMATTER"

    def test_missing_description(self, sp):
        """缺 description → N1。"""
        text = _frontmatter().replace("description: 网络调研技能\n", "")
        with pytest.raises(sp.SkillValidationError) as exc:
            sp.parse_skill_metadata(text, "web-research")
        assert exc.value.code == "SKILLS_INVALID_FRONTMATTER"

    def test_empty_description(self, sp):
        """description 空串 → N1。"""
        with pytest.raises(sp.SkillValidationError) as exc:
            sp.parse_skill_metadata(_frontmatter(description=""), "web-research")
        assert exc.value.code == "SKILLS_INVALID_FRONTMATTER"

    def test_no_frontmatter(self, sp):
        """纯正文无 frontmatter 定界 → N1。"""
        with pytest.raises(sp.SkillValidationError) as exc:
            sp.parse_skill_metadata("# 只有正文\n没有 frontmatter\n", "web-research")
        assert exc.value.code == "SKILLS_INVALID_FRONTMATTER"

    def test_yaml_syntax_error(self, sp):
        """frontmatter YAML 语法错误 → N1。"""
        text = "---\nname: [unclosed\n---\n"
        with pytest.raises(sp.SkillValidationError) as exc:
            sp.parse_skill_metadata(text, "web-research")
        assert exc.value.code == "SKILLS_INVALID_FRONTMATTER"

    def test_unterminated_frontmatter(self, sp):
        """有起始 --- 但无终止 --- → N1。"""
        text = "---\nname: web-research\ndescription: 网络调研技能\n"
        with pytest.raises(sp.SkillValidationError) as exc:
            sp.parse_skill_metadata(text, "web-research")
        assert exc.value.code == "SKILLS_INVALID_FRONTMATTER"

    def test_frontmatter_not_mapping(self, sp):
        """frontmatter YAML 非映射（标量）→ N1。"""
        text = "---\njust-a-string\n---\n"
        with pytest.raises(sp.SkillValidationError) as exc:
            sp.parse_skill_metadata(text, "web-research")
        assert exc.value.code == "SKILLS_INVALID_FRONTMATTER"


class TestNameValidation:
    def test_name_too_long(self, sp):
        """name 超 64 字符 → N2。"""
        long_name = "a" * 65
        with pytest.raises(sp.SkillValidationError) as exc:
            sp.parse_skill_metadata(_frontmatter(name=long_name), long_name)
        assert exc.value.code == "SKILLS_INVALID_NAME"

    def test_name_uppercase(self, sp):
        """name 含大写 → N2。"""
        with pytest.raises(sp.SkillValidationError) as exc:
            sp.parse_skill_metadata(_frontmatter(name="Web-Research"), "Web-Research")
        assert exc.value.code == "SKILLS_INVALID_NAME"

    def test_name_underscore(self, sp):
        """name 含下划线 → N2。"""
        with pytest.raises(sp.SkillValidationError) as exc:
            sp.parse_skill_metadata(_frontmatter(name="web_research"), "web_research")
        assert exc.value.code == "SKILLS_INVALID_NAME"

    def test_name_double_hyphen(self, sp):
        """name 含连续连字符 → N2。"""
        with pytest.raises(sp.SkillValidationError) as exc:
            sp.parse_skill_metadata(_frontmatter(name="web--research"), "web--research")
        assert exc.value.code == "SKILLS_INVALID_NAME"

    def test_name_leading_hyphen(self, sp):
        """name 首字符连字符 → N2。"""
        with pytest.raises(sp.SkillValidationError) as exc:
            sp.parse_skill_metadata(_frontmatter(name="-web"), "-web")
        assert exc.value.code == "SKILLS_INVALID_NAME"

    def test_name_trailing_hyphen(self, sp):
        """name 尾字符连字符 → N2。"""
        with pytest.raises(sp.SkillValidationError) as exc:
            sp.parse_skill_metadata(_frontmatter(name="web-"), "web-")
        assert exc.value.code == "SKILLS_INVALID_NAME"

    def test_name_dir_mismatch(self, sp):
        """name 与目录名不一致 → N2。"""
        with pytest.raises(sp.SkillValidationError) as exc:
            sp.parse_skill_metadata(_frontmatter(name="web-research"), "other-dir")
        assert exc.value.code == "SKILLS_INVALID_NAME"

    def test_name_with_digits_ok(self, sp):
        """name 含数字合法 → 通过。"""
        meta = sp.parse_skill_metadata(_frontmatter(name="web2-research"), "web2-research")
        assert meta.name == "web2-research"


class TestDescriptionRules:
    def test_description_truncated(self, sp):
        """description 超 1024 字符 → 截断 + SKILLS_DESCRIPTION_TRUNCATED 警告，不抛错。"""
        long_desc = "长" * 1100
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            meta = sp.parse_skill_metadata(_frontmatter(description=long_desc), "web-research")
        assert len(meta.description) == 1024
        assert any("SKILLS_DESCRIPTION_TRUNCATED" in str(w.message) for w in caught)


class TestOptionalFieldLenience:
    def test_license_wrong_type_ignored(self, sp):
        """license 非标量（列表）→ 忽略 + 警告，不抛错。"""
        text = "---\nname: web-research\ndescription: 网络调研技能\nlicense: [MIT, Apache]\n---\n"
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            meta = sp.parse_skill_metadata(text, "web-research")
        assert meta.license is None
        assert any("license" in str(w.message) for w in caught)

    def test_metadata_wrong_type_ignored(self, sp):
        """metadata 非 dict → 忽略 + 警告，不抛错。"""
        text = "---\nname: web-research\ndescription: 网络调研技能\nmetadata: just-a-string\n---\n"
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            meta = sp.parse_skill_metadata(text, "web-research")
        assert meta.metadata is None
        assert any("metadata" in str(w.message) for w in caught)

    def test_allowed_tools_wrong_type_ignored(self, sp):
        """allowed-tools 非 list → 忽略 + 警告，不抛错。"""
        text = "---\nname: web-research\ndescription: 网络调研技能\nallowed-tools: read_file\n---\n"
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            meta = sp.parse_skill_metadata(text, "web-research")
        assert meta.allowed_tools is None
        assert any("allowed-tools" in str(w.message) for w in caught)

    def test_compatibility_wrong_type_ignored(self, sp):
        """compatibility 非 str → 忽略 + 警告，不抛错。"""
        text = (
            "---\nname: web-research\ndescription: 网络调研技能\n"
            "compatibility: [Python 3.11, Python 3.12]\n---\n"
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            meta = sp.parse_skill_metadata(text, "web-research")
        assert meta.compatibility is None
        assert any("compatibility" in str(w.message) for w in caught)


class TestErrorStr:
    def test_error_str_returns_message(self, sp):
        """SkillValidationError.__str__ 返回 message。"""
        err = sp.SkillValidationError("SKILLS_INVALID_NAME", "name 不合规")
        assert str(err) == "name 不合规"
