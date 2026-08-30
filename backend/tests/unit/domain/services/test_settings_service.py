"""F32 SettingsService 契约测试 — Mock Repository（RED 批）。

覆盖 spec §2.5（服务层代码块逐字为准）+ §9.4 契约断言表:
- get_settings 空表 → 全默认（缺失键默认值补齐，不落库）
- 部分持久化键 → 与默认值合并
- update_settings 部分更新 → repo.set_many 收到 JSON 编码 payload
- 空 payload（全 None）→ repo.set_many 不被调用
- 脏 JSON / 类型错误 / 未知键防御性忽略（_merge 防御，§7 边界 #6）
- 白名单：DTO 已校验（extra='forbid' + Literal），service 只筛非 None 直接透传

依据: specs/f32-settings/spec.md §2.5 + §9.1/§9.4。

══════════════════════ 设计假设（GREEN 实现者唯一契约）══════════════════════

模块（本批新建，当前不存在 → 收集期 ModuleNotFoundError 即预期 RED 形态）:
``inkflow.domain.services.settings_service``，逐字实现 spec §2.5 代码块:

1. ``class SettingsService``:
   - ``def __init__(self, repository: SettingsRepositoryProtocol) -> None``
   - ``async def get_settings(self) -> AppSettings``:
     ``stored = await self._repository.get_all()`` → ``_merge(stored)``
   - ``async def update_settings(self, updates: AppSettingsUpdate) -> AppSettings``:
     ``updates.model_dump(exclude_none=True)`` → 逐字段 ``SettingsKey(field)``
     白名单（字段名 = 枚举值）→ ``json.dumps(value)`` 编码 →
     ``payload[key.value]`` → payload 非空才
     ``await self._repository.set_many(payload)`` → 返回 ``await self.get_settings()``
   - ``@staticmethod _merge(stored: dict[str, str]) -> AppSettings``:
     逐键 ``json.loads``；解析失败 **或** 单字段构造校验失败
     （``AppSettings(**{key: parsed})`` 抛异常）→ 忽略该键；
     未知键被 ``if k in current`` 白名单过滤；返回默认 + 已持久化合并

2. 依赖: ``inkflow.domain.models.settings``（AppSettings/AppSettingsUpdate/
   SettingsKey）与 ``inkflow.domain.ports.settings_repository``
   （SettingsRepositoryProtocol，签名 = spec §2.4）。

3. mock_repo: 用 ``AsyncMock()`` 裸 mock（Protocol 模块当前不存在，无法
   spec= 约束；get_all/set_many 为 AsyncMock 子属性，按用例覆盖返回值）。

4. JSON 编码形态契约: theme="night" → ``'"night"'``（带引号 JSON 串）；
   tray_hint_dismissed=True → ``"true"``（json.dumps 原生布尔）。

⚠️ 本批为 RED：不写任何 src/ 实现；GREEN 按上述签名实现后本文件应全绿。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from inkflow.domain.models.settings import AppSettings, AppSettingsUpdate
from inkflow.domain.services.settings_service import SettingsService


def _defaults() -> dict:
    """17 字段默认字典（与 AppSettings 默认值一致，独立字面量防实现偏差）。

    F27 扩展（#160 Q2 拍板）：agent_max_steps/agent_token_budget/
    agent_max_total_tool_calls 预算护栏设置键（ADR-C 默认值 12/32K/20；
    #430 语义改造: 单工具连续 → 会话总调用上限）。
    #277 M3 扩展（spec §5.6.1/§5.6.3）：rag_chunk_* 切片配置 4 键。
    #479 扩展（spec f48 §5.5.2）：kg_extract_* 定时提取三键。
    """
    return {
        "theme": "paper",
        "bg": "default",
        "lang": "zh",
        "font": "sans",
        "close_behavior": "tray",
        "tray_hint_dismissed": False,
        "default_words": 800000,
        "agent_max_steps": 12,
        "agent_token_budget": 32000,
        "agent_max_total_tool_calls": 20,
        "rag_chunk_mode": "fixed",
        "rag_chunk_size": 500,
        "rag_chunk_overlap": False,
        "rag_chunk_overlap_ratio": 0.15,
        "kg_extract_enabled": False,
        "kg_extract_interval_hours": 24,
        "kg_extract_method": "rule",
    }


@pytest.fixture
def mock_repo() -> AsyncMock:
    """Mock SettingsRepositoryProtocol — get_all 默认空表；set_many 自动 AsyncMock。"""
    repo = AsyncMock()
    repo.get_all.return_value = {}
    return repo


def _service(mock_repo: AsyncMock) -> SettingsService:
    """按 spec §2.5 构造 SettingsService（位置参数 repository）。"""
    return SettingsService(mock_repo)


class TestGetSettings:
    """get_settings: 默认补齐 + 合并（不落库）。"""

    async def test_empty_table_returns_all_defaults(self, mock_repo: AsyncMock):
        """空表 → 全默认（§9.4「空表默认补齐」）。"""
        result = await _service(mock_repo).get_settings()
        # 返回形态契约：AppSettings 领域对象（spec §2.5 签名 -> AppSettings），非裸 dict
        assert isinstance(result, AppSettings)
        assert result.model_dump() == _defaults()
        mock_repo.get_all.assert_awaited_once()

    async def test_partial_persisted_keys_merge_defaults(self, mock_repo: AsyncMock):
        """表含 theme → 其余 5 键默认值补齐（§9.4「部分持久化合并」）。"""
        mock_repo.get_all.return_value = {"theme": '"night"'}
        result = await _service(mock_repo).get_settings()
        assert result.model_dump() == {**_defaults(), "theme": "night"}


class TestUpdateSettings:
    """update_settings: 白名单 + JSON 编码 + 空 payload 不写库。"""

    async def test_partial_update_encodes_json_payload(self, mock_repo: AsyncMock):
        """theme='night' → set_many 收到 {'theme': '"night"'}（JSON 编码形态断言）。"""
        mock_repo.get_all.return_value = {"theme": '"night"'}
        service = _service(mock_repo)
        result = await service.update_settings(AppSettingsUpdate(theme="night"))

        mock_repo.set_many.assert_awaited_once_with({"theme": '"night"'})
        assert result.model_dump() == {**_defaults(), "theme": "night"}

    async def test_multi_field_update_whitelist_passthrough(self, mock_repo: AsyncMock):
        """多字段部分更新：仅非 None 字段进 payload（service 不校验枚举，直接透传）。"""
        mock_repo.get_all.return_value = {
            "theme": '"night"',
            "font": '"serif"',
            "close_behavior": '"quit"',
        }
        service = _service(mock_repo)
        result = await service.update_settings(
            AppSettingsUpdate(theme="night", font="serif", close_behavior="quit")
        )

        mock_repo.set_many.assert_awaited_once_with(
            {
                "theme": '"night"',
                "font": '"serif"',
                "close_behavior": '"quit"',
            }
        )
        assert result.model_dump() == {
            **_defaults(),
            "theme": "night",
            "font": "serif",
            "close_behavior": "quit",
        }

    async def test_bool_field_json_encoding(self, mock_repo: AsyncMock):
        """布尔字段编码：True → 'true'（json.dumps 原生形态，§2.5 编码契约）。"""
        mock_repo.get_all.return_value = {"tray_hint_dismissed": "true"}
        service = _service(mock_repo)
        result = await service.update_settings(AppSettingsUpdate(tray_hint_dismissed=True))

        mock_repo.set_many.assert_awaited_once_with({"tray_hint_dismissed": "true"})
        assert result.tray_hint_dismissed is True

    async def test_empty_payload_skips_set_many(self, mock_repo: AsyncMock):
        """全 None 更新 → set_many 不被调用（§9.4「空 payload 不写库」）；返回全默认。"""
        service = _service(mock_repo)
        result = await service.update_settings(AppSettingsUpdate())

        mock_repo.set_many.assert_not_awaited()
        assert result.model_dump() == _defaults()
        mock_repo.get_all.assert_awaited_once()


class TestMergeDefense:
    """_merge 脏数据防御（§2.5 + §7 边界 #6）：忽略脏键，其余正常。"""

    async def test_dirty_json_key_ignored(self, mock_repo: AsyncMock):
        """表含非法 JSON 键 → 忽略该键，其余键正常合并（§9.4「脏 JSON 防御」）。"""
        mock_repo.get_all.return_value = {
            "theme": "not-json{{{",
            "font": '"serif"',
        }
        result = await _service(mock_repo).get_settings()
        assert result.model_dump() == {**_defaults(), "font": "serif"}

    async def test_valid_json_wrong_type_ignored(self, mock_repo: AsyncMock):
        """合法 JSON 但类型不符（theme='"true"'）→ 同样忽略不抛（§2.5 单字段校验防御）。"""
        mock_repo.get_all.return_value = {
            "theme": '"true"',
            "tray_hint_dismissed": '"yes"',
        }
        result = await _service(mock_repo).get_settings()
        assert result.model_dump() == _defaults()

    async def test_unknown_key_ignored(self, mock_repo: AsyncMock):
        """未知键（非 SettingsKey 成员）→ 白名单过滤忽略，不影响其余键。"""
        mock_repo.get_all.return_value = {
            "ghost_key": '"x"',
            "lang": '"en"',
        }
        result = await _service(mock_repo).get_settings()
        assert result.model_dump() == {**_defaults(), "lang": "en"}


class TestChunkSettingsPersistence:
    """#277 切片配置 4 键白名单 + 合并（spec §5.6.3/§5.6.5）。"""

    async def test_update_chunk_settings_persists_4_keys(self, mock_repo: AsyncMock):
        """更新 4 键 → set_many 收到 JSON 编码键值（白名单放行，§5.6.3）。

        镜像既有 update 用例模式：预置 get_all 模拟落库读回（真实仓储
        set_many 后 get_all 返回新值）——update_settings 返回
        get_settings() 读回结果，而非本地合并。
        """
        mock_repo.get_all.return_value = {
            "rag_chunk_mode": '"paragraph"',
            "rag_chunk_size": "600",
            "rag_chunk_overlap": "true",
            "rag_chunk_overlap_ratio": "0.18",
        }
        service = _service(mock_repo)
        result = await service.update_settings(
            AppSettingsUpdate(
                rag_chunk_mode="paragraph",
                rag_chunk_size=600,
                rag_chunk_overlap=True,
                rag_chunk_overlap_ratio=0.18,
            )
        )
        mock_repo.set_many.assert_awaited_once_with(
            {
                "rag_chunk_mode": '"paragraph"',
                "rag_chunk_size": "600",
                "rag_chunk_overlap": "true",
                "rag_chunk_overlap_ratio": "0.18",
            }
        )
        assert result.rag_chunk_mode == "paragraph"
        assert result.rag_chunk_size == 600
        assert result.rag_chunk_overlap is True
        assert result.rag_chunk_overlap_ratio == 0.18

    async def test_merge_restores_chunk_settings_defaults(self, mock_repo: AsyncMock):
        """表内仅存部分切片键 → 缺省键用默认值补齐（§5.6.5 配置快照读取前提）。"""
        mock_repo.get_all.return_value = {
            "rag_chunk_mode": '"paragraph"',
            "rag_chunk_overlap": "true",
        }
        result = await _service(mock_repo).get_settings()
        assert result.rag_chunk_mode == "paragraph"
        assert result.rag_chunk_overlap is True
        assert result.rag_chunk_size == 500  # 缺省 → 默认
        assert result.rag_chunk_overlap_ratio == 0.15  # 缺省 → 默认

    async def test_dirty_chunk_settings_ignored(self, mock_repo: AsyncMock):
        """非法 chunk 配置 JSON → 防御忽略（§2.5 单字段校验防御）。"""
        mock_repo.get_all.return_value = {
            "rag_chunk_size": '"not-a-number"',
            "rag_chunk_mode": '"char"',
        }
        result = await _service(mock_repo).get_settings()
        assert result.model_dump() == _defaults()
