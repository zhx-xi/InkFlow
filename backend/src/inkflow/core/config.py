"""InkFlow 全局配置 — 基于 Pydantic Settings，支持环境变量覆盖。"""

import json as _json
from pathlib import Path
from typing import Literal

from loguru import logger
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
    """用户数据目录。包含：SQLite DB、chromadb 向量库、项目配置备份。"""

    log_level: str = "INFO"
    """日志级别：DEBUG / INFO / WARNING / ERROR。"""

    server_host: str = "127.0.0.1"
    """serve 默认监听地址."""

    server_port: int = 8000
    """serve 默认监听端口."""

    # ---- LLM Provider ----
    llm_default_model: str = "openai/gpt-4o"
    """默认 LLM 模型（LiteLLM 格式：provider/model_name）。"""

    llm_temperature: float = 0.7
    """LLM 默认温度参数。"""

    llm_max_retries: int = 3
    """LLM 调用失败自动重试次数。"""

    llm_request_timeout: int = 120
    """LLM API 请求超时（秒）。"""

    # ---- LLM Provider API Keys（通过环境变量注入，不落盘） ----
    openai_api_key: str = ""
    deepseek_api_key: str = ""
    anthropic_api_key: str = ""

    # ---- 模型路由（task → model，可在项目级配置覆盖） ----
    model_routing: dict[str, str] = {
        "writing": "openai/gpt-4o",
        "audit": "anthropic/claude-3-haiku-20240307",
        "outline": "deepseek/deepseek-chat",
        "revision": "openai/gpt-4o",
    }
    """不同 Agent 角色的默认模型映射。"""

    # ---- LangSmith 追踪（调试用） ----
    langsmith_api_key: str = ""
    """LangSmith API Key。为空时禁用追踪。"""

    langsmith_project: str = "inkflow"
    """LangSmith 项目名称。"""

    langsmith_enabled: bool = False
    """是否启用 LangSmith 追踪。"""

    # ---- Embedding 模型 ----
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    """本地 Embedding 模型名称（sentence-transformers 兼容）。首次运行自动下载。"""

    embedding_device: str = "cpu"
    """Embedding 推理设备：cpu / cuda。"""

    # ---- 向量数据库（RAG） ----
    vector_store_dir: Path = Path("./data/chroma")
    """chromadb 持久化目录。"""

    vector_store_collections: list[str] = [
        "character",
        "setting",
        "foreshadowing",
        "timeline_event",
        "chapter_chunk",
    ]
    """chromadb collection 列表，每种实体类型一个 collection。"""

    retrieval_top_k: int = 10
    """RAG 检索默认返回的 top-K 结果数。"""

    # ---- 上下文管理（F6） ----
    context_default_window: int = 128_000
    """默认上下文窗口大小（未知模型兜底用）."""

    context_max_ratio: float = 0.8
    """上下文预算比例上限 = 模型窗口 × ratio."""

    # ---- 密钥（AES-256-GCM，API Key 加密存储） ----
    secret_key: str = ""
    """API Key 本地加密密钥。通过环境变量注入。"""


config = InkFlowConfig()


# Config key 白名单: CLI key → Pydantic field name
CONFIG_WHITELIST: dict[str, str] = {
    "default.model": "llm_default_model",
    "default.temperature": "llm_temperature",
    "context.max_ratio": "context_max_ratio",
    "context.default_window": "context_default_window",
    "server.host": "server_host",
    "server.port": "server_port",
}


def load_config_json(data_dir: Path) -> dict:
    """从 {data_dir}/config.json 加载配置.

    Args:
        data_dir: 数据目录路径.

    Returns:
        配置 dict，文件不存在时返回空 dict.
    """
    config_file = data_dir / "config.json"
    if not config_file.exists():
        return {}
    try:
        return _json.loads(config_file.read_text(encoding="utf-8"))
    except (_json.JSONDecodeError, OSError):
        logger.warning("config.json 解析失败，使用默认值")
        return {}


def save_config_json(data_dir: Path, updates: dict) -> None:
    """合并更新到 config.json.

    Args:
        data_dir: 数据目录路径.
        updates: 要更新的 key-value 对.
    """
    config_file = data_dir / "config.json"
    current = load_config_json(data_dir)
    current.update(updates)
    data_dir.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        _json.dumps(current, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
