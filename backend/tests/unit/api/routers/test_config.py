"""core/config.py 配置 JSON 持久化函数测试（Phase 3 覆盖率补齐）。

覆盖 load_config_json / save_config_json 的全部分支：
- 文件缺失 → {}
- 非法 JSON → {}（警告日志）
- config.json 为目录 → OSError 分支 → {}
- 合法 JSON → 解析结果
- save 合并 + 目录自动创建
"""

from __future__ import annotations

import json

from inkflow.core.config import InkFlowConfig, load_config_json, save_config_json


def test_load_config_json_missing_file_returns_empty(tmp_path) -> None:
    """config.json 不存在 → 空 dict（不抛错）。"""
    assert load_config_json(tmp_path) == {}


def test_load_config_json_valid_json_returns_dict(tmp_path) -> None:
    """config.json 内容合法 → 解析为 dict。"""
    (tmp_path / "config.json").write_text(
        json.dumps({"default.model": "deepseek/deepseek-chat"}), encoding="utf-8"
    )
    assert load_config_json(tmp_path) == {"default.model": "deepseek/deepseek-chat"}


def test_load_config_json_invalid_json_returns_empty(tmp_path) -> None:
    """config.json 内容非法 JSON → 空 dict（警告日志 + 默认值兜底）。"""
    (tmp_path / "config.json").write_text("{not-valid-json!!!", encoding="utf-8")
    assert load_config_json(tmp_path) == {}


def test_load_config_json_oserror_returns_empty(tmp_path) -> None:
    """config.json 是目录 → read_text 抛 IsADirectoryError（OSError 子类）→ 空 dict。"""
    (tmp_path / "config.json").mkdir()
    assert load_config_json(tmp_path) == {}


def test_save_config_json_creates_dir_and_writes(tmp_path) -> None:
    """目标目录不存在 → 自动创建并写入合并后的 JSON。"""
    data_dir = tmp_path / "nested" / "data"
    save_config_json(data_dir, {"server.port": 9000})
    saved = json.loads((data_dir / "config.json").read_text(encoding="utf-8"))
    assert saved == {"server.port": 9000}


def test_save_config_json_merges_existing(tmp_path) -> None:
    """重复保存 → 增量合并，旧 key 保留。"""
    save_config_json(tmp_path, {"a": 1})
    save_config_json(tmp_path, {"b": 2})
    assert load_config_json(tmp_path) == {"a": 1, "b": 2}


# ── G1 默认模型契约（#415，2026-08-16 / #735 D1，2026-08-28）─────────────────
# 用户拍板：生成管线默认模型切 deepseek/deepseek-v4-flash（便宜），仅 embedding 保留
# zhipu。config.py 是唯一默认源（代码不写第二份默认值）；INKFLOW_* env 优先覆盖。
# #735 D1：全局默认改空（移除内置 deepseek/deepseek-v4-flash 硬编码），未配 provider
# 时由项目/全局解析 + ensureModelReady 守卫兜底。契约值 = 用户拍板的产品决策。


def test_llm_default_model_defaults_empty(tmp_path, monkeypatch) -> None:
    """默认生成模型为空（#735 D1；移除内置 deepseek/deepseek-v4-flash 硬编码）。

    #977 隔离补强：instance.env 全键生效后，本机 %APPDATA%/InkFlow/instance.env
    可能含 INKFLOW_LLM_DEFAULT_MODEL → 锚点须 patch 到不存在路径（镜像
    test_log.py:158 手法），否则真默认断言被本地实例文件污染。断言语义不变。
    """
    import importlib

    monkeypatch.delenv("INKFLOW_LLM_DEFAULT_MODEL", raising=False)
    cfg_mod = importlib.import_module("inkflow.core.config")
    monkeypatch.setattr(
        cfg_mod,
        "get_instance_env_path",
        lambda: tmp_path / "no-instance-env" / "instance.env",
        raising=False,
    )
    cfg = InkFlowConfig(_env_file=None, data_dir=tmp_path)
    assert cfg.llm_default_model == ""


def test_model_routing_provider_keys_deepseek_defaults_v4_flash(tmp_path, monkeypatch) -> None:
    """#929 迁移：model_routing 改 provider 键 → ProviderDefault{model 裸名, type}。

    原 task 键（writing/revision=deepseek/deepseek-v4-flash）随 R2 键错位缺陷修复
    废止；#415 拍板值保留在 provider 键下（裸名，消费侧拼 provider/model）。
    """
    monkeypatch.delenv("INKFLOW_MODEL_ROUTING", raising=False)
    cfg = InkFlowConfig(_env_file=None, data_dir=tmp_path)
    assert {"openai", "deepseek", "zhipu"} <= set(cfg.model_routing)
    deepseek = cfg.model_routing["deepseek"]
    assert deepseek.model == "deepseek-v4-flash"
    assert deepseek.type == "chat"


def test_llm_default_model_env_override_wins(tmp_path, monkeypatch) -> None:
    """INKFLOW_LLM_DEFAULT_MODEL env 优先于配置默认（#415 守护；env 机制既有 → RED 阶段 PASS）。"""
    monkeypatch.setenv("INKFLOW_LLM_DEFAULT_MODEL", "env/override-model")
    cfg = InkFlowConfig(_env_file=None, data_dir=tmp_path)
    assert cfg.llm_default_model == "env/override-model"
