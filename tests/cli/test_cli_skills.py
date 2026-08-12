"""skills 命令组 CLI 契约测试（F19-skills spec §4/§7，RED 阶段）。

GREEN 契约（实现 inkflow.cli.commands.skills + app.py 注册）：
- 命令面：install <SOURCE> [--target PATH] [--force] / list / verify [--name NAME] / remove <NAME>
- 执行模型：零后端代码——纯本地文件操作，不 ensure_kernel、不 HTTP
- 默认目标根 = config.data_dir / "skills"（config 单例动态读取，测试 monkeypatch 实例属性）
- 成功信封：{"ok": true, "data": ...}；错误信封：{"ok": false, "error": {"code", "message"}}
- 错误码（exit 1）：N1 SKILLS_INVALID_FRONTMATTER / N2 SKILLS_INVALID_NAME /
  N4 ALREADY_INSTALLED / N5 NOT_FOUND / N6 SKILLS_SOURCE_INVALID / N7 SKILLS_TARGET_UNWRITABLE
- 用法错误（exit 2）：缺 SOURCE/未知子命令（typer 默认）
- install 成功 data：{"name", "target", "files"}；list 成功 data：
  {"skills": [{name, description, path, status}]}；
- verify 成功 data：{"name", "checks": {frontmatter, name, description}, "status"}；
  remove 成功 data：{"removed"}
- list status：frontmatter 校验结果（ok | invalid，invalid 附错误信息）

RED 预期形态：顶部 import 缺失 → 收集期 ModuleNotFoundError（exit 2）。
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

# RED 阶段模块不存在 → 收集期 ModuleNotFoundError（预期）
from inkflow.cli.commands import skills  # 契约主模块
from inkflow.cli.context import CliContext

runner = CliRunner()


@pytest.fixture
def skills_dir(monkeypatch, tmp_path):
    """隔离 config.data_dir → skills 默认根 = tmp_path/skills（config 单例实例属性 patch）。"""
    core_config_mod = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(core_config_mod.config, "data_dir", tmp_path)
    return tmp_path / "skills"


def make_skill_package(root: Path, name: str = "web-research") -> Path:
    """构造含合法 SKILL.md 的 skill 包目录
    （SKILL.md + helper.py + references/guide.md = 3 文件）。"""
    pkg = root / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: 网络调研技能\n---\n# {name} 正文\n",
        encoding="utf-8",
    )
    (pkg / "helper.py").write_text(
        "def helper() -> int:\n    return 1\n", encoding="utf-8"
    )
    refs = pkg / "references"
    refs.mkdir(exist_ok=True)
    (refs / "guide.md").write_text("# Guide\n", encoding="utf-8")
    return pkg


def _invoke(args: list[str], json_output: bool = True):
    """invoke skills 子组（每个 invoke 必须带 obj=CliContext）。"""
    return runner.invoke(skills.app, args, obj=CliContext(json_output=json_output))


class TestInstall:
    def test_install_success(self, tmp_path, skills_dir):
        """install 本地 skill 包 → 落盘 data_dir/skills/<name>/
        （SKILL.md + helper + references 原样保留）。"""
        pkg = make_skill_package(tmp_path)
        result = _invoke(["install", str(pkg)])
        assert result.exit_code == 0
        target = skills_dir / "web-research"
        assert (target / "SKILL.md").is_file()
        expected_helper = "def helper() -> int:\n    return 1\n"
        assert (target / "helper.py").read_text(encoding="utf-8") == expected_helper
        assert (target / "references" / "guide.md").is_file()

    def test_install_json_envelope(self, tmp_path, skills_dir):
        """install --json 信封：ok true + data{name, target, files=3}。"""
        pkg = make_skill_package(tmp_path)
        result = _invoke(["install", str(pkg)])
        assert result.exit_code == 0
        envelope = json.loads(result.stdout)
        assert envelope["ok"] is True
        assert envelope["data"]["name"] == "web-research"
        assert envelope["data"]["target"] == str(skills_dir / "web-research")
        assert envelope["data"]["files"] == 3

    def test_install_target_override(self, tmp_path):
        """--target 覆盖默认目标根。"""
        pkg = make_skill_package(tmp_path)
        alt_root = tmp_path / "alt-skills"
        result = _invoke(["install", str(pkg), "--target", str(alt_root)])
        assert result.exit_code == 0
        assert (alt_root / "web-research" / "SKILL.md").is_file()

    def test_install_missing_name(self, tmp_path):
        """frontmatter 缺 name → exit 1 + SKILLS_INVALID_FRONTMATTER。"""
        pkg = tmp_path / "bad-skill"
        pkg.mkdir()
        (pkg / "SKILL.md").write_text(
            "---\ndescription: 没有名字\n---\n", encoding="utf-8"
        )
        result = _invoke(["install", str(pkg)])
        assert result.exit_code == 1
        envelope = json.loads(result.stdout)
        assert envelope["ok"] is False
        assert envelope["error"]["code"] == "SKILLS_INVALID_FRONTMATTER"

    def test_install_name_mismatch(self, tmp_path):
        """frontmatter name 与源目录名不一致 → exit 1 + SKILLS_INVALID_NAME。"""
        wrong_dir = tmp_path / "other-dir"
        wrong_dir.mkdir()
        (wrong_dir / "SKILL.md").write_text(
            "---\nname: web-research\ndescription: 网络调研技能\n---\n",
            encoding="utf-8",
        )
        result = _invoke(["install", str(wrong_dir)])
        assert result.exit_code == 1
        envelope = json.loads(result.stdout)
        assert envelope["error"]["code"] == "SKILLS_INVALID_NAME"

    def test_install_source_missing(self, tmp_path):
        """SOURCE 路径不存在 → exit 1 + SKILLS_SOURCE_INVALID。"""
        result = _invoke(["install", str(tmp_path / "no-such-dir")])
        assert result.exit_code == 1
        envelope = json.loads(result.stdout)
        assert envelope["error"]["code"] == "SKILLS_SOURCE_INVALID"

    def test_install_no_skill_md(self, tmp_path):
        """源目录无 SKILL.md → exit 1 + SKILLS_SOURCE_INVALID。"""
        pkg = tmp_path / "empty-skill"
        pkg.mkdir()
        result = _invoke(["install", str(pkg)])
        assert result.exit_code == 1
        envelope = json.loads(result.stdout)
        assert envelope["error"]["code"] == "SKILLS_SOURCE_INVALID"

    def test_install_read_oserror(self, tmp_path, monkeypatch):
        """SKILL.md 读取失败（OSError）→ exit 1 + SKILLS_SOURCE_INVALID。"""
        pkg = make_skill_package(tmp_path)
        import pathlib

        def _boom(self, *args, **kwargs):
            raise OSError("denied")

        monkeypatch.setattr(pathlib.Path, "read_text", _boom)
        result = _invoke(["install", str(pkg)])
        assert result.exit_code == 1
        envelope = json.loads(result.stdout)
        assert envelope["error"]["code"] == "SKILLS_SOURCE_INVALID"

    def test_install_already_exists(self, tmp_path, skills_dir):
        """同名已存在且无 --force → exit 1 + ALREADY_INSTALLED。"""
        pkg = make_skill_package(tmp_path)
        assert _invoke(["install", str(pkg)]).exit_code == 0
        result = _invoke(["install", str(pkg)])
        assert result.exit_code == 1
        envelope = json.loads(result.stdout)
        assert envelope["error"]["code"] == "ALREADY_INSTALLED"

    def test_install_force_overwrites(self, tmp_path, skills_dir):
        """--force 覆盖已存在同名 skill → 目标内容更新。"""
        pkg = make_skill_package(tmp_path)
        assert _invoke(["install", str(pkg)]).exit_code == 0
        (pkg / "SKILL.md").write_text(
            "---\nname: web-research\ndescription: 更新后的描述\n---\n",
            encoding="utf-8",
        )
        result = _invoke(["install", str(pkg), "--force"])
        assert result.exit_code == 0
        updated = (skills_dir / "web-research" / "SKILL.md").read_text(encoding="utf-8")
        assert "更新后的描述" in updated

    def test_install_target_is_file(self, tmp_path):
        """--target 指向已存在文件（根不可写）→ exit 1 + SKILLS_TARGET_UNWRITABLE。"""
        pkg = make_skill_package(tmp_path)
        blocker = tmp_path / "blocker.txt"
        blocker.write_text("x", encoding="utf-8")
        result = _invoke(["install", str(pkg), "--target", str(blocker)])
        assert result.exit_code == 1
        envelope = json.loads(result.stdout)
        assert envelope["error"]["code"] == "SKILLS_TARGET_UNWRITABLE"

    def test_install_missing_arg(self):
        """install 缺 SOURCE 参数 → 用法错误 exit 2。"""
        result = _invoke(["install"])
        assert result.exit_code == 2


class TestList:
    def test_list_empty(self, tmp_path, skills_dir):
        """无已导入 skills → skills: []。"""
        result = _invoke(["list"])
        assert result.exit_code == 0
        envelope = json.loads(result.stdout)
        assert envelope["ok"] is True
        assert envelope["data"]["skills"] == []

    def test_list_after_install(self, tmp_path, skills_dir):
        """install 后 list → status=ok + name/description/path。"""
        pkg = make_skill_package(tmp_path)
        assert _invoke(["install", str(pkg)]).exit_code == 0
        result = _invoke(["list"])
        envelope = json.loads(result.stdout)
        skills_list = envelope["data"]["skills"]
        assert len(skills_list) == 1
        entry = skills_list[0]
        assert entry["name"] == "web-research"
        assert entry["description"] == "网络调研技能"
        assert entry["path"] == str(skills_dir / "web-research")
        assert entry["status"] == "ok"

    def test_list_invalid_status(self, tmp_path, skills_dir):
        """预置坏 frontmatter 的 skill → list status=invalid 附错误信息。"""
        bad = skills_dir / "bad-skill"
        bad.mkdir(parents=True)
        (bad / "SKILL.md").write_text(
            "---\ndescription: 缺名字\n---\n", encoding="utf-8"
        )
        result = _invoke(["list"])
        assert result.exit_code == 0
        entry = json.loads(result.stdout)["data"]["skills"][0]
        assert entry["name"] == "bad-skill"
        assert entry["status"] == "invalid"
        assert "SKILLS_INVALID_FRONTMATTER" in str(entry.get("error", ""))

    def test_list_skips_dir_without_skill_md(self, tmp_path, skills_dir):
        """无 SKILL.md 的目录被跳过（不报错、不列出）。"""
        empty_dir = skills_dir / "not-a-skill"
        empty_dir.mkdir(parents=True)
        (empty_dir / "readme.txt").write_text("x", encoding="utf-8")
        result = _invoke(["list"])
        assert result.exit_code == 0
        names = [s["name"] for s in json.loads(result.stdout)["data"]["skills"]]
        assert "not-a-skill" not in names


class TestVerify:
    def test_verify_all_ok(self, tmp_path, skills_dir):
        """install 后 verify → checks 三字段 true + status ok。"""
        pkg = make_skill_package(tmp_path)
        assert _invoke(["install", str(pkg)]).exit_code == 0
        result = _invoke(["verify"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)["data"]
        assert data["name"] == "web-research"
        assert data["checks"] == {
            "frontmatter": True,
            "name": True,
            "description": True,
        }
        assert data["status"] == "ok"

    def test_verify_named(self, tmp_path, skills_dir):
        """verify --name 指定 → 只校验指定 skill。"""
        pkg = make_skill_package(tmp_path)
        assert _invoke(["install", str(pkg)]).exit_code == 0
        result = _invoke(["verify", "--name", "web-research"])
        assert result.exit_code == 0
        assert json.loads(result.stdout)["data"]["name"] == "web-research"

    def test_verify_fail(self, tmp_path, skills_dir):
        """坏 frontmatter 的已导入 skill → exit 1 + SKILLS_INVALID_FRONTMATTER。"""
        bad = skills_dir / "bad-skill"
        bad.mkdir(parents=True)
        (bad / "SKILL.md").write_text(
            "---\ndescription: 缺名字\n---\n", encoding="utf-8"
        )
        result = _invoke(["verify"])
        assert result.exit_code == 1
        envelope = json.loads(result.stdout)
        assert envelope["error"]["code"] == "SKILLS_INVALID_FRONTMATTER"

    def test_verify_not_found(self, tmp_path, skills_dir):
        """verify --name 指定未导入 skill → exit 1 + NOT_FOUND。"""
        result = _invoke(["verify", "--name", "no-such-skill"])
        assert result.exit_code == 1
        envelope = json.loads(result.stdout)
        assert envelope["error"]["code"] == "NOT_FOUND"

    def test_verify_empty_root_not_found(self, tmp_path, skills_dir):
        """无任何已导入 skills → verify → exit 1 + NOT_FOUND。"""
        result = _invoke(["verify"])
        assert result.exit_code == 1
        envelope = json.loads(result.stdout)
        assert envelope["error"]["code"] == "NOT_FOUND"


class TestRemove:
    def test_remove_success(self, tmp_path, skills_dir):
        """remove → exit 0 + removed + 目录删除。"""
        pkg = make_skill_package(tmp_path)
        assert _invoke(["install", str(pkg)]).exit_code == 0
        result = _invoke(["remove", "web-research"])
        assert result.exit_code == 0
        assert json.loads(result.stdout)["data"] == {"removed": "web-research"}
        assert not (skills_dir / "web-research").exists()

    def test_remove_not_found(self, tmp_path, skills_dir):
        """remove 不存在 skill → exit 1 + NOT_FOUND。"""
        result = _invoke(["remove", "no-such-skill"])
        assert result.exit_code == 1
        envelope = json.loads(result.stdout)
        assert envelope["error"]["code"] == "NOT_FOUND"

    def test_remove_oserror(self, tmp_path, skills_dir, monkeypatch):
        """remove 删除失败（OSError）→ exit 1 + SKILLS_TARGET_UNWRITABLE。"""
        pkg = make_skill_package(tmp_path)
        assert _invoke(["install", str(pkg)]).exit_code == 0
        import shutil as _shutil

        def _boom(*args, **kwargs):
            raise OSError("denied")

        monkeypatch.setattr(_shutil, "rmtree", _boom)
        result = _invoke(["remove", "web-research"])
        assert result.exit_code == 1
        envelope = json.loads(result.stdout)
        assert envelope["error"]["code"] == "SKILLS_TARGET_UNWRITABLE"


class TestFullCycle:
    def test_install_list_verify_remove_cycle(self, tmp_path, skills_dir):
        """用户自定义轨闭环：install → list(ok) → verify(ok) → remove → list 空。"""
        pkg = make_skill_package(tmp_path)
        assert _invoke(["install", str(pkg)]).exit_code == 0
        listed = json.loads(_invoke(["list"]).stdout)["data"]["skills"]
        assert len(listed) == 1 and listed[0]["status"] == "ok"
        verified = json.loads(_invoke(["verify"]).stdout)["data"]
        assert verified["status"] == "ok"
        assert _invoke(["remove", "web-research"]).exit_code == 0
        after = json.loads(_invoke(["list"]).stdout)["data"]["skills"]
        assert after == []
