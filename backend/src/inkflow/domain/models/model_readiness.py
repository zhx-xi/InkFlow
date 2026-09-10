"""ModelReadiness 领域模型 — 首启模型就绪判据的只读视图（#934 §3.1）。

领域层保持纯净：仅依赖 Pydantic v2，不感知 ORM / 框架 / 网络。

依据: specs/f60-first-run-guide/spec.md §2.1 / §3.1。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ReadinessReason = Literal["ready", "no_provider", "no_chat_model", "no_key"]
"""未就绪原因（互斥，按优先级降级：no_provider > no_chat_model > no_key）。

- ``ready``: 已具备可解析 chat 模型 + 有效 key（``ready=True``）
- ``no_provider``: 注册表无任何 provider（真·全新安装）
- ``no_chat_model``: 有 provider 但无一含 chat 模型（#929 精确缺陷形态）
- ``no_key``: 有 chat 模型但对应 provider 无 key
"""


class ModelReadiness(BaseModel):
    """首启模型就绪判据（GET /api/v1/settings/model-readiness 响应体）。

    Attributes:
        ready: 是否可进入写作主流程（唯一门控判据，spec §2.1）。
        has_chat_model: 是否存在「有 key 且有 chat 模型」的 provider。
        has_embedding_model: 是否存在「有 key 且有 embedding 模型」的 provider
            （GUI 步骤 3 / 语义检索置灰判据，spec §5.4 N2）。
        reason: 未就绪原因（供 GUI 定位引导起始步骤 + 诊断）。
    """

    model_config = {"from_attributes": True}

    ready: bool
    has_chat_model: bool
    has_embedding_model: bool
    reason: ReadinessReason
