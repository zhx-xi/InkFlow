#!/usr/bin/env python
"""pre-push 钩子：强制 Conventional Branches（借鉴 LiteLLM .githooks/pre-push，Python 实现兼容 Windows）。

分支格式: <type>/<description>
- <type>: feat|fix|docs|chore|refactor|release
- 保护分支（跳过）: main、dependabot/*、gh-readonly-queue/*、release/*

绕过: git push --no-verify（慎用）。
"""

import re
import sys

ALLOWED_TYPES = r"feat|fix|docs|chore|refactor|release"
BRANCH_PATTERN = re.compile(rf"^({ALLOWED_TYPES})/.+")

PROTECTED_NAMES = {"main"}
PROTECTED_PREFIXES = ("dependabot/", "gh-readonly-queue/", "release/")


def is_protected(branch: str) -> bool:
    if branch in PROTECTED_NAMES:
        return True
    return branch.startswith(PROTECTED_PREFIXES)


def main() -> int:
    invalid: list[str] = []
    for line in sys.stdin:
        parts = line.strip().split()
        if len(parts) != 4:
            continue
        local_ref, local_oid, remote_ref, _remote_oid = parts
        # 分支删除（local_oid 全零）跳过
        if set(local_oid) == {"0"}:
            continue
        # 只校验 refs/heads/*
        if not remote_ref.startswith("refs/heads/"):
            continue
        branch = remote_ref[len("refs/heads/") :]
        if is_protected(branch):
            continue
        if not BRANCH_PATTERN.match(branch):
            invalid.append(branch)

    if invalid:
        print(
            "✗ Branch name does not follow Conventional Branches.\n"
            f"\n  Invalid:{' '.join(invalid)}\n"
            f"\n  Expected: <type>/<description>\n"
            f"\n  Allowed types: {ALLOWED_TYPES.replace('|', ', ')}\n"
            "  Examples:\n"
            "    feat/f14-extraction-service\n"
            "    fix/ci-cli-coverage\n"
            "    docs/update-agents\n"
            "\n  Protected (always allowed): main, dependabot/*, "
            "gh-readonly-queue/*, release/*\n"
            "\nRename with: git branch -m <new-name>\n"
            "To bypass (use sparingly): git push --no-verify",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
