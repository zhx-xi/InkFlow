"""F19 打包分发：数据目录 sys.frozen 检测契约测试（spec §2.1.1，方案 B）。

RED 阶段契约（Q7=B 已拍板，2026-08-06）：
- F1 打包模式（sys.frozen=True + APPDATA）→ 默认 data_dir = <APPDATA>/InkFlow，
  database_url / vector_store_dir 基于 data_dir 派生（三字段一致性）
- F2 dev 模式（sys.frozen 未设置/False）→ 默认 data_dir = Path("./data")，行为不变防回归
- F3 env 显式覆盖（INKFLOW_DATA_DIR）→ 优先于 sys.frozen 默认值

实现形态（spec §2.1.1）：core/config.py 新增 `_default_data_dir()` 工厂函数
（`getattr(sys, "frozen", False)` 检测），InkFlowConfig.data_dir 以 default_factory 引用。

⚠️ 注意：config.py 的 `config = InkFlowConfig()` 是导入期模块级单例，本文件一律
构造新实例（monkeypatch 后），不依赖模块级缓存值。
"""

from __future__ import annotations

import sys
from pathlib import Path

from inkflow.core.config import InkFlowConfig


# ---- F1 打包模式：sys.frozen=True → %APPDATA%/InkFlow ----
def test_default_data_dir_frozen_uses_appdata(monkeypatch, tmp_path) -> None:
    """F1-工厂：sys.frozen=True 且 APPDATA 存在 → <APPDATA>/InkFlow。"""
    # 函数内 import：RED 阶段契约对象尚不存在，避免整文件收集失败（GREEN 后自然通过）
    from inkflow.core.config import _default_data_dir

    # Arrange
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))

    # Act
    result = _default_data_dir()

    # Assert
    assert result == tmp_path / "InkFlow"


def test_default_data_dir_frozen_without_appdata_falls_back_to_home(monkeypatch, tmp_path) -> None:
    """F1-工厂补充：sys.frozen=True 但 APPDATA 缺失 → Path.home()/InkFlow 兜底。"""
    import importlib

    from inkflow.core.config import _default_data_dir

    # Arrange
    # #266 隔离升级：instance.env 锚点固定指到 tmp_path，防真实 home 下的
    # instance.env（若有）污染本用例（raising=False：RED 阶段属性可不存在）
    core_config_mod = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(
        core_config_mod,
        "get_instance_env_path",
        lambda: tmp_path / "InkFlow" / "instance.env",
        raising=False,
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("APPDATA", raising=False)

    # Act
    result = _default_data_dir()

    # Assert
    assert result == Path.home() / "InkFlow"


def test_settings_frozen_defaults_data_dir_to_appdata(monkeypatch, tmp_path) -> None:
    """F1-集成：打包模式新建 Settings → data_dir=<APPDATA>/InkFlow，三字段一致。"""
    # Arrange（raising=False：sys.frozen 在 dev 解释器不存在，需「新增」该属性模拟打包）
    appdata = tmp_path / "appdata"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.delenv("INKFLOW_DATA_DIR", raising=False)

    # Act
    settings = InkFlowConfig()

    # Assert
    expected_data_dir = appdata / "InkFlow"
    assert settings.data_dir == expected_data_dir
    assert settings.vector_store_dir == expected_data_dir / "chroma"
    # database_url 基于 data_dir 派生（正/反斜杠归一化后比较，Windows 兼容）
    url_normalized = settings.database_url.replace("\\", "/")
    assert str(expected_data_dir).replace("\\", "/") in url_normalized


# ---- F2 dev 模式：sys.frozen 未设置/False → ./data 不变 ----
def test_default_data_dir_dev_keeps_cwd_relative(monkeypatch, tmp_path) -> None:
    """F2-工厂：非 frozen（属性缺失/False）→ Path("./data")，dev 行为不变。"""
    from inkflow.core.config import _default_data_dir

    # Arrange
    # #266 隔离升级：APPDATA 固定到 tmp_path（instance.env 锚点随之隔离，
    # 防真实 APPDATA 下未来存在的 instance.env 污染 dev 默认语义）
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delattr(sys, "frozen", raising=False)

    # Act
    result = _default_data_dir()

    # Assert
    assert result == Path("./data")


def test_settings_dev_keeps_cwd_relative_data_dir(monkeypatch, tmp_path) -> None:
    """F2-集成：默认环境（非 frozen）→ data_dir=Path("./data")，防回归。"""
    # Arrange
    # #266 隔离升级：APPDATA 固定到 tmp_path（instance.env 锚点随之隔离）
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delenv("INKFLOW_DATA_DIR", raising=False)

    # Act
    settings = InkFlowConfig()

    # Assert
    assert settings.data_dir == Path("./data")


# ---- F3 env 显式覆盖：INKFLOW_DATA_DIR 优先于 sys.frozen 默认值 ----
def test_settings_env_override_wins_over_frozen_default(monkeypatch, tmp_path) -> None:
    """F3：INKFLOW_DATA_DIR 指向自定义路径 → 覆盖 sys.frozen 默认值。"""
    # Arrange（raising=False：模拟新增 sys.frozen 属性，见 F1 集成测试注释）
    custom_data = tmp_path / "custom-data"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("INKFLOW_DATA_DIR", str(custom_data))

    # Act
    settings = InkFlowConfig()

    # Assert
    assert settings.data_dir == custom_data
    assert settings.vector_store_dir == custom_data / "chroma"


# ---- F51 debug 字段：config.json debug=true 触发（env INKFLOW_DEBUG 未设时）----
def test_debug_config_json_triggers(monkeypatch, tmp_path) -> None:
    """F51-配置：config.json 含 "debug": true → settings.debug is True。

    RED 阶段 InkFlowConfig 无 debug 字段 → settings.debug 访问抛 AttributeError
    （GREEN 义务：新增 debug: bool = False 字段 + model_validator 并入 config.json）。
    """
    import importlib

    # 真实 APPDATA 下可能存在 instance.env（含 INKFLOW_DEBUG/DATA_DIR），
    # 把 get_instance_env_path 固定到不存在的临时锚点，保证本用例只测 config.json 触发
    core_config_mod = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(
        core_config_mod,
        "get_instance_env_path",
        lambda: tmp_path / "nonexistent" / "instance.env",
        raising=False,
    )
    monkeypatch.delenv("INKFLOW_DEBUG", raising=False)

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "config.json").write_text('{"debug": true}', encoding="utf-8")

    settings = InkFlowConfig(data_dir=data_dir)

    assert settings.debug is True
