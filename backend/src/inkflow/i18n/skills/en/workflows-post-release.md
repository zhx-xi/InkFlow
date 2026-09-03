# Version Verification and Smoke Checks (workflows-post-release.md)

After receiving a new InkFlow release artifact (stable/rc), the general process to confirm it
works: version verification → isolated-environment smoke → judgment. Full functional validation
(scenarios A-D) lives in workflows-pre-release.md.

## Version verification

1. CLI version: `inkflow --version` output = the expected tag (packaged artifacts show the tag
   version; dev builds show the pyproject version and are not a version criterion)
2. Kernel version: after startup `inkflow kernel status` (or `GET /health` with X-InkFlow-Token)
   → version matches
3. Release metadata (when reachable): verify the tag, prerelease flags, and asset manifest
   (name/size; trust the release assets' actual naming)

## Smoke command chain

In a dedicated data directory (`%APPDATA%` or `INKFLOW_DATA_DIR` pointing to a temp dir, fresh
DB), run in order:

```powershell
project list --json                        # basic commands work
project create --name smoke --json         # create returns a non-empty UUID
chapter create --project-id <uuid> --title 第一章 --content <≥50 chars> --json
chapter list --project-id <uuid> --status draft
memory stats --project-id <uuid>
extract status --project-id <uuid>
export export <project name or UUID> --output out.txt
search <keyword> --project <name or UUID>
```

The writing chain needs an LLM key: `llm set-key --provider deepseek --key sk-...` (always mask).

## Pass criteria

- Every command returns `"ok":true` with `--json`; create returns a non-empty UUID; list reads
  back the just-created entry; the export file is non-empty
- Any failed step → record the full output (command + exit code + actual output) as defect
  evidence and file it in the defect-report format (version, repro command, actual output)

## Version-sensitive points

- Artifact URL/tag criteria update with each version (trust the release assets' actual naming)
- Full functional validation beyond the smoke chain: see workflows-pre-release.md (scenarios A-D)
