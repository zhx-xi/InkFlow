"""deepagents HarnessProfile 注册表 — key 格式必须 litellm:<model_name>（ADR-051 实证）."""

from __future__ import annotations

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    register_harness_profile,
)

HARNESS_PROFILES: dict[str, HarnessProfile] = {}

# deepagents 0.7.5 默认文件系统工具全量清单（FsToolName：ls/read_file/write_file/
# edit_file/delete/glob/grep + execute 外壳命令）——F26 只读工具集下全部禁用
DEFAULT_EXCLUDED_TOOLS: frozenset[str] = frozenset(
    {"ls", "read_file", "write_file", "edit_file", "delete", "glob", "grep", "execute"}
)


def ensure_profile(model_name: str) -> str:
    """确保 HarnessProfile 已注册。key 格式必须 litellm:<model_name>（ADR-051 实证：
    deepagents 对预构建 ChatLiteLLM 实例按 ls_provider='litellm'（langchain_litellm
    硬编码）+ identifier=model 全名解析——调用方传入的必须是**已口径映射**的完整
    litellm 模型名，如 zai/glm-4.5）。

    已注册 → 直接返回 key；未注册 → 注册默认 profile 后返回 key。
    默认 profile 禁用全部默认文件系统工具，并关闭默认 general-purpose subagent
    （配合不传 subagents，task 工具随之移除）。
    """
    key = f"litellm:{model_name}"
    if key in HARNESS_PROFILES:
        return key
    profile = HarnessProfile(
        excluded_tools=DEFAULT_EXCLUDED_TOOLS,
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
    )
    HARNESS_PROFILES[key] = profile
    register_harness_profile(key, profile)
    return key
