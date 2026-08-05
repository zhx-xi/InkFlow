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

from inkflow.core.config import load_config_json, save_config_json


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
