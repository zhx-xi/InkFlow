"""SettingsService — 设置读写服务（默认值补齐 + 白名单过滤）。

职责边界：
- get_settings(): 读全量已持久化键 → 与 AppSettings 默认值合并 → 返回全量对象
  （缺失键用默认值，不落库）
- update_settings(): 接收已通过 DTO 校验的部分更新 → 过滤出非 None 字段 →
  白名单（SettingsKey 枚举）→ JSON 编码批量落库 → 返回合并后的全量对象
"""

from __future__ import annotations

import json

from inkflow.core.config import config
from inkflow.domain.models.settings import (
    AppSettings,
    AppSettingsUpdate,
    SettingsKey,
)
from inkflow.domain.ports.settings_repository import SettingsRepositoryProtocol


class SettingsService:
    def __init__(self, repository: SettingsRepositoryProtocol) -> None:
        self._repository = repository

    async def get_settings(self) -> AppSettings:
        """全量设置（缺失键默认值补齐，不落库）。"""
        stored = await self._repository.get_all()
        return self._merge(stored)

    async def update_settings(self, updates: AppSettingsUpdate) -> AppSettings:
        """部分更新（白名单 + JSON 编码落库）→ 返回全量设置。

        注意：updates 已由 DTO（extra='forbid' + Literal 枚举）完成值域校验，
        本方法只负责「非 None 字段」筛选与编码，不重复校验。
        """
        non_none_updates = updates.model_dump(exclude_none=True)
        payload: dict[str, str] = {}
        for field, value in non_none_updates.items():
            key = SettingsKey(field)  # 白名单：字段名 = SettingsKey 值
            payload[key.value] = json.dumps(value)
        if payload:
            await self._repository.set_many(payload)
        # D-1 方案 A 同步桥（#987 镜像）：GUI PATCH 思考档位 → 回灌 config 单例，
        # 装配层读取点（config.llm_reasoning_effort）立即生效。
        if "default_reasoning_effort" in non_none_updates:
            config.llm_reasoning_effort = non_none_updates["default_reasoning_effort"]
        return await self.get_settings()

    @staticmethod
    def _merge(stored: dict[str, str]) -> AppSettings:
        """已持久化键值 + 默认值合并（非法 JSON/未知键防御性忽略，仅记录）。"""
        merged: dict[str, object] = {}
        for key, raw in stored.items():
            try:
                parsed = json.loads(raw)
                # 评审 🟢 修订：合法 JSON 但类型不匹配（手改库 theme:'true'）也会使
                # 最终 AppSettings 构造失败 → 单字段校验防御（与脏 JSON 同级忽略）
                # strict=True：lax 模式会把 "yes" 强转 bool（RED 契约 §9.4 要求忽略）
                AppSettings.model_validate({key: parsed}, strict=True)
                merged[key] = parsed
            except Exception:
                continue  # 防御：脏数据不阻塞读（§7 边界 #6）
        current = AppSettings().model_dump()
        current.update({k: v for k, v in merged.items() if k in current})
        # D-1 方案 A（F59 spec §3.4）：DB 无 default_reasoning_effort 键时回读
        # config 单例当前值（启动源 config.json/env 在 GUI 可见）；DB 有值则 DB 优先。
        if "default_reasoning_effort" not in merged:
            current["default_reasoning_effort"] = config.llm_reasoning_effort
        return AppSettings(**current)
