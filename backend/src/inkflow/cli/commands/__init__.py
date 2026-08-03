"""CLI 子命令模块."""

from inkflow.cli.commands import (  # noqa: F401  # 作为包门面 re-export 子模块（供外部 from inkflow.cli.commands import X）
    audit,
    extract,
    foreshadowing,
    timeline,
    vector,
)
