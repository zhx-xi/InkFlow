"""InkFlow 全局配置 — 基于 Pydantic Settings，支持环境变量覆盖。"""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class InkFlowConfig(BaseSettings):
    """应用全局配置，可通过环境变量 `INKFLOW_*` 覆盖。"""

    model_config = SettingsConfigDict(
        env_prefix="INKFLOW_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ---- 数据库 ----
    database_url: str = "sqlite+aiosqlite:///./inkflow.db"
    """数据库连接字符串。本地开发使用 SQLite，云端切换至 PostgreSQL。"""

    # ---- 部署模式 ----
    mode: Literal["local", "cloud"] = "local"
    """部署模式：local（本地免认证） / cloud（需认证，Phase 4+）。"""

    # ---- 运行时 ----
    data_dir: Path = Path("./data")
    """用户数据目录（项目文件、配置备份等）。"""

    log_level: str = "INFO"
    """日志级别：DEBUG / INFO / WARNING / ERROR。"""

    # ---- LLM ----
    llm_default_provider: str = "openai"
    """默认 LLM Provider 名称。"""

    # ---- 密钥（通过环境变量注入，不落盘） ----
    secret_key: str = ""
    """API Key 加密密钥（AES-256-GCM）。"""


config = InkFlowConfig()
