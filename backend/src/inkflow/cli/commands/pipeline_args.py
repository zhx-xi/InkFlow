"""#1475 `agent run --pipeline` 三形态参数解析（CLI 本地判定，spec f42 §4.1）。

判别顺序（即优先级，见 `resolve_pipeline_arg`）：

1. `builtin:*` 前缀 → 内置模板 id，不带任何自定义载荷（零回归）；
2. `<path>.yaml` / `.yml` / 存在的文件 → 本地读 YAML → `PipelineConfig`；
3. 其余 → 逗号分隔 role_key 序列 → `stages`。

失败面（本地拒绝，不发请求）：异常消息即用户可读原因，由调用方（agent_cmd）
映射为 stderr「❌ …」+ 退出码 1。本模块从 agent_cmd.py 迁出（monster-file 纪律）。
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from inkflow.domain.models.agent_pipeline import PipelineConfig


def load_pipeline_config(file: str) -> dict:
    """读 YAML 管线文件 → dict（强制 source=yaml）；错误抛 ValueError（消息即原因）。"""
    try:
        raw = Path(file).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ValueError(f"配置文件不存在: {file}") from None
    try:
        config = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML 解析失败: {exc}") from None
    if not isinstance(config, dict):
        raise TypeError("管线配置必须是 YAML 映射")
    config.setdefault("source", "yaml")
    return config


def resolve_pipeline_arg(value: str) -> tuple[list[str] | None, PipelineConfig | None]:
    """`--pipeline` 取值 → `(stages, pipeline_config)` 二元组（spec §4.1 三形态）。

    形态 1（`builtin:*`）/ 默认值 → `(None, None)`：请求体不带两字段（内置路径零回归）。
    形态 2（YAML 路径）→ `(None, <PipelineConfig>)`：本地读取 + DTO 校验，失败即本地报错。
    形态 3（兜底）→ `(<role_key 序列>, None)`：去空白，空列表 → `ValueError`。
    """
    if value.startswith("builtin:"):
        return None, None
    if Path(value).is_file() or value.endswith((".yaml", ".yml")):
        config_dict = load_pipeline_config(value)
        try:
            return None, PipelineConfig.model_validate(config_dict)
        except ValidationError as exc:
            raise ValueError(f"管线配置无效: {exc}") from None
    keys = [segment.strip() for segment in value.split(",") if segment.strip()]
    if not keys:
        raise ValueError("自定义 stage 列表为空")
    return keys, None
