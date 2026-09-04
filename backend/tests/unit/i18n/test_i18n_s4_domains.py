"""F57 全译迁入 + per-call 切换 — RED 契约测试（任务 #888-S4 / spec §2.1、§5）。

契约来源
--------
specs/f57-logging-i18n/spec.md §2.1（语义域分目录 + 双层 fallback 链）、
§5（提示词全译、per-call 准实时、迁移「旧路径不再 import」、用户 override 键校验）、
§12 M5（prompt_manager per-locale 加载生效）。

目标模块：``backend/src/inkflow/i18n/prompts/{zh,en}/``、``i18n/functions/{zh,en}.json``、
``i18n/skills/{zh,en}/``、``infrastructure/llm/prompt_manager.py``（per-locale 加载）、
``i18n/resolver.py``（用户覆盖层 + fallback 链）。

════════════════════════════════════════════════════════════════════
设计假设（GREEN 实现必须满足的契约，逐条对应下方测试）
════════════════════════════════════════════════════════════════════

A. prompts 迁移完整性
   - ``infrastructure/llm/templates/*.yaml`` 的 18 个模板**已迁入** i18n/prompts/{zh,en}/；
     旧目录 `infrastructure/llm/templates` 中不再存在任何 ``*.yaml``（被 mv 走）。
   - 迁移集 = {architect, auditor, chapter_audit_drift, character_extract, context_compress,
     context_summary, foreshadowing_extract, llm_chunk, memory_semantic_summary,
     memory_supersede, outline_generate, planner_interview, reviser, style_llm_analysis,
     timeline_extract, world_extract, writer, writer_agent}（共 18）。

B. 提示词 per-locale
   - ``LangChainPromptManager`` 默认（无 ``templates_dir``）从 ``i18n/prompts/<locale>/`` 读取，
     locale = ``resolve_locale()``（per-call 解析）。
   - ``load(name, locale=None)``：显式传 locale → 从 ``i18n/prompts/<locale>/<name>.yaml`` 读；
     未传 → ``resolve_locale()``。zh 模板保留原文；en 为全译。
   - 自定义 ``templates_dir``（传给构造器）仍为**扁平模式**（既有 test_prompt_manager.py
     契约，locale 无关），保持向后兼容。

C. 同名 prompt 键集合 + {占位符} 集合 zh/en 必须一致
   - ``{name, description, system_prompt, human_prompt, variables}`` 键集合 zh == en。
   - ``system_prompt``/``human_prompt`` 内 ``{param}`` 占位符集合 zh == en（防翻译丢 {var}）。

D. per-call 切换准实时
   - 改变生效 locale（显式传 locale 或改 config.lang）后，再次 ``load`` 读取即新语言
     （无需重启）。

E. functions/skills 迁入 + 对称
   - ``i18n/functions/{zh,en}.json`` 均存在，键集合对称。
   - ``i18n/skills/{zh,en}/`` 均存在，文件名集合对称（.md 文件）。

F. 用户覆盖层（override.json 键级 merge + fallback）
   - ``load_messages(domain, locale)`` 返回 打包默认 | 用户覆盖（键级 merge，覆盖层优先）。
   - 用户覆盖文件可经 ``user_i18n_root()`` 定位（默认
     ``%APPDATA%/InkFlow/i18n``），测试可 monkeypatch。
   - 覆盖层的孤儿键（不在打包默认中）→ ``logger.warning``（防静默）。
   - ``t()`` 缺键回退链：有效 locale 文件（含覆盖）→ zh 文件 → msgid 本身 + WARN。

RED 阶段预期：i18n/prompts|functions|skills 目录**不存在**/旧模板仍在 → 断言失败；
per-call 切换（load(..., locale='en') 返英文）→ 当前 prompt_manager 忽略 locale → 失败；
override merge → 当前 load_messages 只读打包默认 → 失败。
GREEN 阶段：Codex 迁移 + 翻译 + per-locale 加载 + 用户覆盖层后全绿。
════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from loguru import logger

from inkflow.domain.ports.prompt_template import PromptTemplate
from inkflow.i18n.resolver import load_messages, t

# test 文件 backend/tests/unit/test_i18n_s4_domains.py → parents[2] = backend 根
_BACKEND = Path(__file__).resolve().parents[3]
_I18N_SRC = _BACKEND / "src" / "inkflow" / "i18n"
_OLD_TEMPLATES = _BACKEND / "src" / "inkflow" / "infrastructure" / "llm" / "templates"

# 迁移集（18 个模板名，来自 infrastructure/llm/templates 现况）
_EXPECTED_TEMPLATE_NAMES: frozenset[str] = frozenset(
    {
        "architect",
        "auditor",
        "chapter_audit_drift",
        "character_extract",
        "context_compress",
        "context_summary",
        "foreshadowing_extract",
        "llm_chunk",
        "memory_semantic_summary",
        "memory_supersede",
        "outline_generate",
        "planner_interview",
        "reviser",
        "style_llm_analysis",
        "timeline_extract",
        "world_extract",
        "writer",
        "writer_agent",
    }
)

_PROMPT_KEYS = ("name", "description", "system_prompt", "human_prompt", "variables")


def _prompt_names(locale: str) -> frozenset[str]:
    """读取 i18n/prompts/<locale>/*.yaml → 模板名集合。目录不存在返回空集。"""
    d = _I18N_SRC / "prompts" / locale
    if not d.is_dir():
        return frozenset()
    return frozenset(p.stem for p in d.glob("*.yaml"))


def _as_yaml_map(path: Path) -> dict:
    return dict(yaml.safe_load(path.read_text(encoding="utf-8")))


def _placeholders(text: str) -> frozenset[str]:
    """提取 {param} / {{ param }} 占位符名（忽略 {% ... %} 标签）。

    outline_generate 等模板用 Jinja 风格双花括号条件块（``{{ num_chapters }}`` +
    ``{% if ... %}``），渲染后由服务层 ``_resolve_num_chapters_in_text`` 解析；故需同时
    匹配单花括号与双花括号变量，但跳过 ``{% ... %}`` 标签块。
    """
    double = re.findall(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}", text)
    single = re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", text)
    return frozenset(double) | frozenset(single)


# ── A. prompts 迁移完整性 ──


class TestPromptsMigrationCompleteness:
    def test_migrated_set_present_in_zh(self):
        """zh 目录必须包含全部 18 个已迁入模板名。"""
        assert _EXPECTED_TEMPLATE_NAMES - _prompt_names("zh") == frozenset()

    def test_migrated_set_present_in_en(self):
        """en 目录必须包含全部 18 个已迁入模板名。"""
        assert _EXPECTED_TEMPLATE_NAMES - _prompt_names("en") == frozenset()

    def test_old_templates_dir_is_empty(self):
        """旧 infrastructure/llm/templates 目录不再含 *.yaml（已 mv 走 → 迁移完整性）。"""
        assert list(_OLD_TEMPLATES.glob("*.yaml")) == []


# ── B. prompt 文件 zh/en 键集合 + 占位符集合一致 ──


class TestPromptFileSymmetry:
    @pytest.mark.parametrize("name", sorted(_EXPECTED_TEMPLATE_NAMES))
    def test_same_name_key_sets_equal(self, name: str):
        """同名模板 zh/en 的 YAML 键集合必须相等（name/desc/system/human/variables）。"""
        zh = _as_yaml_map(_I18N_SRC / "prompts" / "zh" / f"{name}.yaml")
        en = _as_yaml_map(_I18N_SRC / "prompts" / "en" / f"{name}.yaml")
        assert set(zh.keys()) == set(en.keys())
        assert set(zh.keys()) == set(_PROMPT_KEYS)

    @pytest.mark.parametrize("name", sorted(_EXPECTED_TEMPLATE_NAMES))
    def test_internal_placeholder_sets_equal(self, name: str):
        """zh/en 的 system_prompt+human_prompt 中 {占位符} 集合必须一致。"""
        zh = _as_yaml_map(_I18N_SRC / "prompts" / "zh" / f"{name}.yaml")
        en = _as_yaml_map(_I18N_SRC / "prompts" / "en" / f"{name}.yaml")
        zh_ph = _placeholders(str(zh.get("system_prompt", "")) + str(zh.get("human_prompt", "")))
        en_ph = _placeholders(str(en.get("system_prompt", "")) + str(en.get("human_prompt", "")))
        assert zh_ph == en_ph

    @pytest.mark.parametrize("name", sorted(_EXPECTED_TEMPLATE_NAMES))
    def test_variables_declared_match_placeholders(self, name: str):
        """variables 声明集合应与模板内实际 {占位符} 集合一致（防遗漏）。"""
        data = _as_yaml_map(_I18N_SRC / "prompts" / "zh" / f"{name}.yaml")
        declared = set(data.get("variables", []))
        used = _placeholders(str(data.get("system_prompt", "")) + str(data.get("human_prompt", "")))
        assert declared == used


# ── C. prompt_manager per-locale 加载 + per-call 切换 ──


class TestPromptManagerPerLocale:
    @pytest.fixture
    def default_manager(self):
        from inkflow.infrastructure.llm.prompt_manager import LangChainPromptManager

        return LangChainPromptManager()  # 默认（无 templates_dir）→ per-locale 模式

    def test_default_loads_architect_locale_en(self, default_manager):
        """默认管理器 load('architect', locale='en') 应返回英文 system_prompt。"""
        tmpl = default_manager.load("architect", locale="en")
        assert isinstance(tmpl, PromptTemplate)
        blob = (tmpl.system_prompt or "") + " " + (tmpl.description or "")
        assert "architect" in blob.lower() or "architecture" in blob.lower()

    def test_per_call_switch_re_reads_new_language(self, default_manager, monkeypatch):
        """改 config.lang 后再次 load（不传 locale）应读到新语言 → 准实时切换。"""
        import importlib

        cfg = importlib.import_module("inkflow.core.config")
        monkeypatch.setattr(cfg.config, "lang", "en", raising=False)
        tmpl_en = default_manager.load("architect")
        assert isinstance(tmpl_en, PromptTemplate)
        # describe/system 至少其一为英文（无东亚字符）
        blob = (tmpl_en.system_prompt or "") + (tmpl_en.description or "")
        assert not any("\u4e00" <= ch <= "\u9fff" for ch in blob)

    def test_explicit_templates_dir_flat_mode(self, tmp_path):
        """自定义 templates_dir 仍为扁平模式（向后兼容既有 test_prompt_manager.py）。"""
        from inkflow.infrastructure.llm.prompt_manager import LangChainPromptManager

        tmpl_dir = tmp_path / "templates"
        tmpl_dir.mkdir()
        (tmpl_dir / "flat.yaml").write_text(
            "name: flat\nsystem_prompt: \"Flat {x}\"\nhuman_prompt: \"\"\nvariables: [x]\n",
            encoding="utf-8",
        )
        pm = LangChainPromptManager(templates_dir=tmpl_dir)
        tmpl = pm.load("flat", locale="en")  # 扁平模式下 locale 被忽略
        assert tmpl.system_prompt == "Flat {x}"


# ── D. functions / skills 迁入 + 对称 ──


class TestFunctionsAndSkillsSymmetry:
    def test_functions_zh_en_key_symmetry(self):
        zh_path = _I18N_SRC / "functions" / "zh.json"
        en_path = _I18N_SRC / "functions" / "en.json"
        assert zh_path.is_file(), f"缺失 {zh_path}"
        assert en_path.is_file(), f"缺失 {en_path}"
        zh = json.loads(zh_path.read_text(encoding="utf-8"))
        en = json.loads(en_path.read_text(encoding="utf-8"))
        assert set(zh.keys()) == set(en.keys())

    def test_functions_nonempty(self):
        zh_path = _I18N_SRC / "functions" / "zh.json"
        assert zh_path.is_file()
        assert json.loads(zh_path.read_text(encoding="utf-8"))

    def test_skills_zh_en_file_set_symmetric(self):
        zh_dir = _I18N_SRC / "skills" / "zh"
        en_dir = _I18N_SRC / "skills" / "en"
        assert zh_dir.is_dir(), f"缺失 {zh_dir}"
        assert en_dir.is_dir(), f"缺失 {en_dir}"
        zh_names = {p.name for p in zh_dir.glob("*.md")}
        en_names = {p.name for p in en_dir.glob("*.md")}
        assert zh_names == en_names
        assert zh_names  # 非空


# ── E. 用户覆盖层（override.json 键级 merge + 孤儿键校验）──


class TestUserOverride:
    @pytest.fixture
    def override_root(self, monkeypatch, tmp_path):
        """把 resolver.user_i18n_root 指向临时目录，写一份 messages/en.override.json。"""
        import inkflow.i18n.resolver as resolver_mod

        root = tmp_path / "i18n"
        over = root / "messages"
        over.mkdir(parents=True)
        (over / "en.override.json").write_text(
            json.dumps({"api.error.project_not_found": "EN override: {project_id}"}),
            encoding="utf-8",
        )
        monkeypatch.setattr(resolver_mod, "user_i18n_root", lambda: root, raising=False)
        return root

    def test_override_merges_over_package_default(self, override_root):
        """用户覆盖键优先于打包默认；未覆盖键沿用打包默认。"""
        assert (
            t("messages", "api.error.project_not_found", {"project_id": "x"}, locale="en")
            == "EN override: x"
        )
        # 未被覆盖的键仍来自打包默认
        assert (
            t("messages", "log.event.create_chapter", {"title": "T"}, locale="en")
            == "Created chapter: T"
        )

    def test_orphan_override_key_warns(self, override_root, monkeypatch):
        """覆盖层孤儿键（不在打包默认中）→ logger.warning（防静默）。"""
        over = override_root / "messages"
        (over / "en.override.json").write_text(
            json.dumps({"some.orphan.key": "orphan"}), encoding="utf-8"
        )
        records = []
        sink = logger.add(lambda m: records.append(m), level="WARNING", format="{message}")
        try:
            load_messages("messages", "en")
        finally:
            logger.remove(sink)
        assert any("orphan" in str(m) or "some.orphan.key" in str(m) for m in records)

    def test_t_missing_key_falls_back_to_zh(self, monkeypatch):
        """缺键回退链：locale 文件缺键 → 尝试 zh → 仍缺 → msgid 本身。"""
        import inkflow.i18n.resolver as resolver_mod

        monkeypatch.setattr(resolver_mod, "user_i18n_root", lambda: None, raising=False)
        result = t("messages", "log.event.nonexistent_xyz", locale="en")
        assert result == "log.event.nonexistent_xyz"
