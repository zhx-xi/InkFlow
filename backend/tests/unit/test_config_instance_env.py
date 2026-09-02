"""Issue #266：instance.env 数据目录持久化 — config 层 RED 契约测试（方案 A，0.7.0）。

新增三个模块级函数（inkflow.core.config，GREEN 义务）：
1. get_instance_env_path() -> Path
   固定锚点 = Path(os.environ.get("APPDATA", Path.home())) / "InkFlow" / "instance.env"。
   不随 data_dir 变；frozen 与 dev 同锚点；不依赖 sys.frozen。
2. load_instance_env() -> dict[str, str]
   读锚点文件 → 解析 KEY=VALUE 行 → dict。文件不存在 → {}；
   跳过空行与 # 开头注释行；无 '=' 的行忽略；KEY/VALUE 均 strip；
   VALUE 为空串的键跳过（不入 dict）；CRLF 兼容（splitlines）。
3. save_instance_env(data_dir: Path) -> Path
   expanduser().resolve() 得绝对路径 → 创建锚点父目录 + data_dir 本身
   （均 parents=True, exist_ok=True）→ 写 UTF-8 无 BOM 文件，内容恰好
   一行 INKFLOW_DATA_DIR=<绝对路径>（换行 \\n 结尾）→ 返回绝对路径 Path。

_default_data_dir() 优先级扩展（GREEN 义务，本文件锁定）：
- load_instance_env() 含 INKFLOW_DATA_DIR 键 → 返回 Path(该值)
  （frozen/dev 一致生效）
- 无 → 保持现状（frozen → %APPDATA%/InkFlow；dev → ./data）

RED 预期形态：
- 当前实现三函数均不存在 → 顶部 import 失败 → 收集期 ImportError
  （cannot import name 'get_instance_env_path'...），1 collection error，
  pytest 退出码 2，本文件用例不执行
- 实现补齐三函数但 _default_data_dir 未扩展时：h) 用例断言 FAIL，
  i)/j) 守护用例 PASS（刻意）
- 本文件不改动 test_config_frozen.py；该文件 F1/F2 未隔离 instance.env
  锚点，由父侧另行处理（不影响本文件）

patch 纪律：锚点一律 monkeypatch.setattr(config 模块, "get_instance_env_path",
lambda: <tmp_path 锚点>, raising=False)——RED 阶段属性不存在不报错，
GREEN 阶段覆盖真实函数；不用 unittest.mock.patch 字符串路径（RED 阶段
AttributeError → ERROR）。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from inkflow.core.config import (
    InkFlowConfig,
    get_instance_env_path,
    load_instance_env,
    save_instance_env,
)


def _patch_anchor(monkeypatch, anchor: Path) -> None:
    """把 config 模块的 get_instance_env_path 替换为固定锚点（测试隔离用）。

    RED 阶段属性不存在 → raising=False 容忍（不设置也不报错）；
    GREEN 阶段覆盖真实函数，load_instance_env/_default_data_dir 均命中。
    """
    module = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(module, "get_instance_env_path", lambda: anchor, raising=False)


# ---- 锚点路径（get_instance_env_path）----
def test_get_instance_env_path_uses_appdata(monkeypatch, tmp_path) -> None:
    """A-锚点：APPDATA 已设 → Path(APPDATA)/InkFlow/instance.env。"""
    monkeypatch.setenv("APPDATA", str(tmp_path))

    result = get_instance_env_path()

    assert result == tmp_path / "InkFlow" / "instance.env"


def test_get_instance_env_path_falls_back_to_home(monkeypatch) -> None:
    """B-锚点：APPDATA 缺失 → Path.home()/InkFlow/instance.env 兜底。"""
    monkeypatch.delenv("APPDATA", raising=False)

    result = get_instance_env_path()

    assert result == Path.home() / "InkFlow" / "instance.env"


# ---- 读取（load_instance_env）----
def test_load_instance_env_missing_file_returns_empty(monkeypatch, tmp_path) -> None:
    """C-读取：锚点文件不存在 → {}。"""
    _patch_anchor(monkeypatch, tmp_path / "InkFlow" / "instance.env")

    assert load_instance_env() == {}


def test_load_instance_env_parses_key_value_lines(monkeypatch, tmp_path) -> None:
    """D-读取：CRLF/空行/# 注释/无=行/带空格 KEY 均正确处理。"""
    anchor = tmp_path / "InkFlow" / "instance.env"
    _patch_anchor(monkeypatch, anchor)
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_text(
        "# 注释行：应被跳过\r\n"
        "\r\n"
        "KEY1=VALUE1\r\n"
        " KEY2 = VALUE2 \r\n"
        "no-equals-line\r\n"
        "PADDED =  padded value  \n"
        "\n",
        encoding="utf-8",
    )

    result = load_instance_env()

    assert result == {
        "KEY1": "VALUE1",
        "KEY2": "VALUE2",
        "PADDED": "padded value",
    }


def test_load_instance_env_skips_empty_value_keys(monkeypatch, tmp_path) -> None:
    """E-读取：VALUE 为空串的键跳过（INKFLOW_DATA_DIR 空值不入 dict）。"""
    anchor = tmp_path / "InkFlow" / "instance.env"
    _patch_anchor(monkeypatch, anchor)
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_text("INKFLOW_DATA_DIR=\nOTHER=1\n", encoding="utf-8")

    result = load_instance_env()

    assert "INKFLOW_DATA_DIR" not in result
    assert result == {"OTHER": "1"}


# ---- 保存（save_instance_env）----
def test_save_instance_env_writes_file_and_creates_dirs(monkeypatch, tmp_path) -> None:
    """F-保存：写锚点文件 + 创建锚点父目录与 data_dir，返回绝对路径。"""
    anchor = tmp_path / "InkFlow" / "instance.env"
    _patch_anchor(monkeypatch, anchor)
    data_dir = tmp_path / "nested" / "user-data"

    result = save_instance_env(data_dir)

    assert result == data_dir
    assert result.is_absolute()
    assert anchor.parent.is_dir()
    assert data_dir.is_dir()
    assert anchor.read_text(encoding="utf-8") == f"INKFLOW_DATA_DIR={data_dir}\n"


def test_save_instance_env_resolves_relative_and_tilde(monkeypatch, tmp_path) -> None:
    """G-保存：相对路径/带 ~ 输入 → expanduser+resolve 后的绝对路径。"""
    anchor = tmp_path / "InkFlow" / "instance.env"
    _patch_anchor(monkeypatch, anchor)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))

    relative_result = save_instance_env(Path("relative-data"))
    tilde_result = save_instance_env(Path("~/tilde-data"))

    assert relative_result == Path("relative-data").expanduser().resolve()
    assert relative_result.is_absolute()
    assert tilde_result == Path("~/tilde-data").expanduser().resolve()
    assert tilde_result.is_absolute()


# ---- _default_data_dir 优先级扩展（INKFLOW_DATA_DIR 锚点优先）----
def test_default_data_dir_prefers_instance_env(monkeypatch, tmp_path) -> None:
    """H-优先级：instance.env 含 INKFLOW_DATA_DIR → 优先于 frozen/dev 默认。

    RED 阶段 _default_data_dir 不读 instance.env → 本用例断言 FAIL
    （实现补齐三函数后成为唯一红用例，即 GREEN 义务）。
    """
    from inkflow.core.config import _default_data_dir

    anchor = tmp_path / "appdata" / "InkFlow" / "instance.env"
    _patch_anchor(monkeypatch, anchor)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))

    target = tmp_path / "persisted-data"
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_text(f"INKFLOW_DATA_DIR={target}\n", encoding="utf-8")

    result = _default_data_dir()

    assert result == target


def test_default_data_dir_dev_without_instance_env(monkeypatch, tmp_path) -> None:
    """I-守护：无 instance.env 且非 frozen → Path("./data") 保持现状。

    RED 阶段即 PASS（刻意守护，防优先级扩展破坏 dev 默认）。
    """
    from inkflow.core.config import _default_data_dir

    _patch_anchor(monkeypatch, tmp_path / "appdata" / "InkFlow" / "instance.env")
    monkeypatch.delattr(sys, "frozen", raising=False)

    result = _default_data_dir()

    assert result == Path("./data")


def test_default_data_dir_frozen_without_instance_env(monkeypatch, tmp_path) -> None:
    """J-守护：无 instance.env 且 frozen=True + APPDATA → <APPDATA>/InkFlow。

    RED 阶段即 PASS（刻意守护，防优先级扩展破坏 frozen 默认）。
    """
    from inkflow.core.config import _default_data_dir

    _patch_anchor(monkeypatch, tmp_path / "appdata" / "InkFlow" / "instance.env")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))

    result = _default_data_dir()

    assert result == tmp_path / "appdata" / "InkFlow"


# ---- F51 debug 字段：env INKFLOW_DEBUG > instance.env INKFLOW_DEBUG > config.json ----
def test_debug_instance_env_triggers(monkeypatch, tmp_path) -> None:
    """F51-优先级：env 未设 + instance.env INKFLOW_DEBUG=1 → settings.debug is True。

    RED 阶段 InkFlowConfig 无 debug 字段 → settings.debug 抛 AttributeError
    （GREEN 义务：新增 debug: bool = False 字段 + model_validator 并入 instance.env）。
    """
    anchor = tmp_path / "appdata" / "InkFlow" / "instance.env"
    _patch_anchor(monkeypatch, anchor)
    monkeypatch.delenv("INKFLOW_DEBUG", raising=False)
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_text("INKFLOW_DEBUG=1\n", encoding="utf-8")

    settings = InkFlowConfig()

    assert settings.debug is True


def test_debug_env_zero_not_overridden_by_instance_env(monkeypatch, tmp_path) -> None:
    """F51-D8：env 显式 INKFLOW_DEBUG=0 不被 instance.env=1 覆盖 → debug is False。

    核心契约：pydantic env 已显式设（model_fields_set 含 debug）→ 跳过 instance.env，
    env 显式 0 保持 False（GREEN 义务）。
    """
    anchor = tmp_path / "appdata" / "InkFlow" / "instance.env"
    _patch_anchor(monkeypatch, anchor)
    monkeypatch.setenv("INKFLOW_DEBUG", "0")
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_text("INKFLOW_DEBUG=1\n", encoding="utf-8")

    settings = InkFlowConfig()

    assert settings.debug is False


def test_debug_env_wins_over_instance_env(monkeypatch, tmp_path) -> None:
    """F51-优先级：env INKFLOW_DEBUG=1 胜 instance.env=0 → debug is True（env 最高）。"""
    anchor = tmp_path / "appdata" / "InkFlow" / "instance.env"
    _patch_anchor(monkeypatch, anchor)
    monkeypatch.setenv("INKFLOW_DEBUG", "1")
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_text("INKFLOW_DEBUG=0\n", encoding="utf-8")

    settings = InkFlowConfig()

    assert settings.debug is True


# ---- S3f-T1（#869，contract-s3f-t1.md §2.5）：config.json 优先级链补全 ----
def test_debug_config_json_true_when_no_env_no_instance_env(monkeypatch, tmp_path) -> None:
    """S3f-T1-优先级：env 未设 + instance.env 文件存在但无 INKFLOW_DEBUG 键 +
    config.json debug=true → debug is True。

    test_config_frozen.py:138 已测「锚点不存在」近似；本用例链语义不同：锚点文件
    存在（含无关键）但未命中 INKFLOW_DEBUG → 继续降级 config.json（config.py:253
    `if "INKFLOW_DEBUG" in ie` 键存在性判定——instance.env 文件存在≠含键）。
    """
    anchor = tmp_path / "appdata" / "InkFlow" / "instance.env"
    _patch_anchor(monkeypatch, anchor)
    monkeypatch.delenv("INKFLOW_DEBUG", raising=False)
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_text("SOME_UNRELATED_KEY=1\n", encoding="utf-8")

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "config.json").write_text('{"debug": true}', encoding="utf-8")

    settings = InkFlowConfig(data_dir=data_dir)

    assert settings.debug is True


def test_debug_env_zero_beats_config_json_true(monkeypatch, tmp_path) -> None:
    """S3f-T1-D8（扩到 config.json）：env INKFLOW_DEBUG=0 + config.json debug=true
    → debug is False。

    env 显式设置即入 model_fields_set → 跳过 instance.env/config.json 降级链
    （D8 判据：显式关 > 任何低优先级真值源）。
    """
    _patch_anchor(monkeypatch, tmp_path / "appdata" / "InkFlow" / "instance.env")
    monkeypatch.setenv("INKFLOW_DEBUG", "0")

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "config.json").write_text('{"debug": true}', encoding="utf-8")

    settings = InkFlowConfig(data_dir=data_dir)

    assert settings.debug is False


def test_debug_instance_env_zero_beats_config_json_true(monkeypatch, tmp_path) -> None:
    """S3f-T1-守护：instance.env INKFLOW_DEBUG=0 + config.json debug=true → False。

    instance.env 命中即终止，不进 config.json——config.py:253 `ie["INKFLOW_DEBUG"] == "1"`
    现实现已满足（契约标【G】守护）。
    """
    anchor = tmp_path / "appdata" / "InkFlow" / "instance.env"
    _patch_anchor(monkeypatch, anchor)
    monkeypatch.delenv("INKFLOW_DEBUG", raising=False)
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_text("INKFLOW_DEBUG=0\n", encoding="utf-8")

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "config.json").write_text('{"debug": true}', encoding="utf-8")

    settings = InkFlowConfig(data_dir=data_dir)

    assert settings.debug is False
