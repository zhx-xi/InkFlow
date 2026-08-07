"""SQLite 设置仓储 — app_settings 表实现。"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from inkflow.domain.ports.settings_repository import SettingsRepositoryProtocol


class SQLiteSettingsRepository(SettingsRepositoryProtocol):
    """app_settings 表读写（INSERT OR REPLACE 幂等 upsert）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_all(self) -> dict[str, str]:
        rows = await self._session.execute(text("SELECT key, value FROM app_settings"))
        return {key: value for key, value in rows.all()}

    async def set_many(self, values: dict[str, str]) -> None:
        for key, value in values.items():
            await self._session.execute(
                text(
                    "INSERT INTO app_settings (key, value) VALUES (:key, :value) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
                ),
                {"key": key, "value": value},
            )
        await self._session.commit()
