#!/usr/bin/env python
"""commit-msg 钩子：强制 Conventional Commits（借鉴 LiteLLM .githooks/commit-msg，Python 实现兼容 Windows）。

Subject 格式: <type>(<scope>)!: <description>
- <type>: feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert
- <scope> 可选；! 可选（breaking change）
- <description> 必填，小写字母开头（与 CI PR 标题检查保持一致，本地钩子更严）

跳过: merge/revert/fixup!/squash!/amend! 消息。
绕过: git commit --no-verify（慎用）。
"""

import re
import sys
from pathlib import Path

ALLOWED_TYPES = r"feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert"
PATTERN = re.compile(rf"^({ALLOWED_TYPES})(\([^)]+\))?!?: [^A-Z].*")

PASSTHROUGH = ("Merge ", 'Revert "', "fixup! ", "squash! ", "amend! ")


def main() -> int:
    if len(sys.argv) < 2:
        print("commit-msg: missing commit message file", file=sys.stderr)
        return 1
    msg_file = Path(sys.argv[1])
    if not msg_file.is_file():
        print(f"commit-msg: commit message file not found: {msg_file}", file=sys.stderr)
        return 1

    subject = ""
    for line in msg_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        subject = stripped
        break

    if not subject:
        print("commit-msg: empty commit message", file=sys.stderr)
        return 1

    if subject.startswith(PASSTHROUGH):
        return 0

    if PATTERN.match(subject):
        return 0

    print(
        "✗ Commit message does not follow Conventional Commits.\n"
        f"\n  Got:      {subject}\n"
        "\n  Expected: <type>(<scope>)!: <description>\n"
        "            (description must start with a lowercase letter)\n"
        f"\n  Allowed types: {ALLOWED_TYPES.replace('|', ', ')}\n"
        "  Examples:\n"
        "    feat(project): add bulk export\n"
        "    fix(timeline): reject orphan events\n"
        "    docs: update AGENTS.md\n"
        "    refactor!: drop legacy endpoints\n"
        "\nSee https://www.conventionalcommits.org/en/v1.0.0/\n"
        "To bypass (use sparingly): git commit --no-verify",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
