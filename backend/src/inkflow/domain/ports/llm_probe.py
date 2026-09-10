"""LLM 探测端口 — 保存前 type-aware 最小连通探测（#936 C 项）。

领域层定义 Protocol（依赖倒置，ADR-015）；infrastructure 层实现
（`InfrastructureLLMProbe`），api/deps 注入 service。`probe_chat` 失败抛异常；
`probe_embedding` 返回向量维度（>0 成功），失败抛异常。service 侧 `probe is None`
→ 零门禁（向后兼容既有调用方）。
"""

from __future__ import annotations

from typing import Protocol


class LLMProbeProtocol(Protocol):
    """Provider 模型探测端口（#936 C 项保存前门禁）。"""

    async def probe_chat(
        self,
        provider: str,
        model: str,
        api_key: str,
        base_url: str | None = None,
    ) -> None:
        """chat 型最小探测（1-token completion 语义）；失败抛异常。"""
        ...

    async def probe_embedding(
        self,
        provider: str,
        model: str,
        api_key: str,
        base_url: str | None = None,
    ) -> int:
        """embedding 型最小探测（`embed_query("0")`）；返回维度（>0 成功），失败抛异常。"""
        ...
