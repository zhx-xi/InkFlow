"""SettingsORM — 应用级设置 key-value 承载表（infrastructure/database/models/settings.py）。"""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from inkflow.core.database import Base


class SettingsORM(Base):
    """应用级设置表 — key 主键 + JSON 编码 value。

    设计：key-value 行承载（对照 provider_configs 列式表）——设置项集合小且
    演进频繁（0.5.0 起 6 项，后续按需加键），行式免 ALTER；value 统一 JSON
    编码（'"night"' / 'true' / '800000'），解析收敛在 repo 层。
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    """设置键（SettingsKey 枚举值，代码级白名单校验）。"""

    value: Mapped[str] = mapped_column(Text, nullable=False)
    """JSON 编码的值（json.dumps 写入 / json.loads 读取）。"""
