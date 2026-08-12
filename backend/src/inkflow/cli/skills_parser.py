"""SKILL.md frontmatter 解析/校验纯函数（deepagents 规则镜像，spec §2.2/§7）。"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from typing import Any

import yaml

NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_NAME_LEN = 64
MAX_DESC_LEN = 1024


@dataclass
class SkillMetadata:
    name: str
    description: str
    license: str | None = None
    compatibility: str | None = None
    metadata: dict[str, Any] | None = None
    allowed_tools: list[str] | None = None


@dataclass
class SkillValidationError(Exception):
    """frontmatter 校验失败（code: SKILLS_INVALID_FRONTMATTER | SKILLS_INVALID_NAME）。"""

    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def parse_skill_metadata(text: str, directory_name: str) -> SkillMetadata:
    """解析并校验 SKILL.md frontmatter，返回 SkillMetadata。

    - 首行必须为 ---，找到下一个 --- 作为终止符；无边界 → N1
    - name/description 必填（key 缺失或空串）→ N1；YAML 解析失败 → N1
    - name 须 1-64 字符、匹配小写字母数字单连字符、且等于目录名 → 否则 N2
    - description 超 1024 字符 → 截断 + UserWarning（N3）
    - license/compatibility 非 str、metadata 非 dict、allowed-tools 非 list → 忽略 + UserWarning
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillValidationError(
            "SKILLS_INVALID_FRONTMATTER",
            "frontmatter 缺失：首行必须为 ---",
        )
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise SkillValidationError(
            "SKILLS_INVALID_FRONTMATTER",
            "frontmatter 缺失：未找到结束 ---",
        )

    try:
        data = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as e:
        raise SkillValidationError(
            "SKILLS_INVALID_FRONTMATTER",
            f"frontmatter YAML 解析失败: {e}",
        ) from e

    if not isinstance(data, dict):
        raise SkillValidationError(
            "SKILLS_INVALID_FRONTMATTER",
            "frontmatter 必须为 YAML 映射",
        )

    name = data.get("name")
    description = data.get("description")
    if not isinstance(name, str) or not name:
        raise SkillValidationError(
            "SKILLS_INVALID_FRONTMATTER",
            "frontmatter 缺少必填字段 name",
        )
    if not isinstance(description, str) or not description:
        raise SkillValidationError(
            "SKILLS_INVALID_FRONTMATTER",
            "frontmatter 缺少必填字段 description",
        )

    if len(name) > MAX_NAME_LEN or not NAME_PATTERN.match(name) or name != directory_name:
        raise SkillValidationError(
            "SKILLS_INVALID_NAME",
            "name 不合规：须 1-64 字符、仅小写字母数字单连字符，且与目录名一致",
        )

    if len(description) > MAX_DESC_LEN:
        warnings.warn(
            "SKILLS_DESCRIPTION_TRUNCATED: description 超 1024 字符，已截断",
            UserWarning,
            stacklevel=2,
        )
        description = description[:MAX_DESC_LEN]

    license_value = data.get("license")
    if license_value is not None and not isinstance(license_value, str):
        warnings.warn("可选字段 license 格式错误，已忽略", UserWarning, stacklevel=2)
        license_value = None

    compatibility_value = data.get("compatibility")
    if compatibility_value is not None and not isinstance(compatibility_value, str):
        warnings.warn("可选字段 compatibility 格式错误，已忽略", UserWarning, stacklevel=2)
        compatibility_value = None

    metadata_value = data.get("metadata")
    if metadata_value is not None and not isinstance(metadata_value, dict):
        warnings.warn("可选字段 metadata 格式错误，已忽略", UserWarning, stacklevel=2)
        metadata_value = None

    allowed_tools_value = data.get("allowed-tools")
    if allowed_tools_value is not None and not isinstance(allowed_tools_value, list):
        warnings.warn("可选字段 allowed-tools 格式错误，已忽略", UserWarning, stacklevel=2)
        allowed_tools_value = None

    return SkillMetadata(
        name=name,
        description=description,
        license=license_value,
        compatibility=compatibility_value,
        metadata=metadata_value,
        allowed_tools=allowed_tools_value,
    )
