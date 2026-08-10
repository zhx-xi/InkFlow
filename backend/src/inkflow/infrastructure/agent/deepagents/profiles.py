"""deepagents HarnessProfile 注册表 — key 格式必须 openai:<model_name>（Spike ③ 实测）."""

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
    """确保 HarnessProfile 已注册。key 格式必须 openai:<model_name>（Spike ③ 实测）.

    已注册 → 直接返回 key；未注册 → 注册默认 profile 后返回 key。
    默认 profile 禁用全部默认文件系统工具，并关闭默认 general-purpose subagent
    （配合不传 subagents，task 工具随之移除）。
    """
    key = f"openai:{model_name}"
    if key in HARNESS_PROFILES:
        return key
    profile = HarnessProfile(
        excluded_tools=DEFAULT_EXCLUDED_TOOLS,
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
    )
    HARNESS_PROFILES[key] = profile
    register_harness_profile(key, profile)
    return key
