# Kernel Lifecycle (kernel.md)

Agent usage: the InkFlow kernel is a local resident HTTP service (uvicorn/FastAPI); the GUI and
CLI both access it over HTTP (ADR-030). Before operating InkFlow, confirm the kernel is running
and get port/token from kernel.json.

## kernel.json discovery protocol

- Location: `%APPDATA%\InkFlow\kernel.json` (the Electron GUI writes the real %APPDATA%; CLI
  ensure_kernel writes to the path under its APPDATA environment)
- Fields: `{port, token, pid, version, started_at}` (X-InkFlow-Token is used for /health and the
  API auth header)
- Read: `Get-Content $env:APPDATA\InkFlow\kernel.json | ConvertFrom-Json`

## ensure_kernel (auto-triggered by the first CLI command)

1. Read kernel.json state
2. Healthy reuse: /health 200 + version match → use it directly
3. Dead/mutex-start: CreateMutexW prevents double spawn → start `inkflow.exe serve`
   (`--port 0` dynamic) → wait for the stdout `INKFLOW_READY` line → write kernel.json
4. **Version check**: a running kernel with a mismatched old version gets **killed and
   kernel.json rewritten** by the new version's ensure_kernel (stale pid) — before terminating an
   instance, confirm it is not a process the user is actively using

## serve diagnostic mode (the reliable way to get stderr)

- `serve --port 0`: random port; readiness goes to stdout as
  `INKFLOW_READY {"port":..,"token":..,"pid":..,"version":..}`; **does not write kernel.json**
  (kernel.json is written by the ensure_kernel client path)
- 500 troubleshooting: run `serve --port 0 --port-file <f>` in the foreground with
  `-RedirectStandardError` → the traceback lands in stderr; stdout only has INKFLOW_READY +
  request lines
- A kernel started by the GUI has no stderr capture — troubleshoot with a foreground serve, not
  the GUI kernel

## Data directory

`config.py _default_data_dir()` branches on packaging state:

| Run form | data_dir | Override variable |
|---|---|---|
| Packaged CLI/GUI (PyInstaller frozen) | `%APPDATA%\InkFlow` | `$env:APPDATA` (effective on the kernel side; Electron appData does not use env — by contract) |
| **dev venv (development build)** | **`./data` (relative to cwd) — does NOT read APPDATA!** | `$env:INKFLOW_DATA_DIR` (pydantic-settings env_prefix=INKFLOW_ override) |

- Running a dev build from another cwd drops data into `cwd\data` — set INKFLOW_DATA_DIR
  explicitly when a fixed data location is required
- kernel.json follows the data directory: first confirm the kernel run form, then decide whether
  to read `%APPDATA%\InkFlow\kernel.json` or `$env:INKFLOW_DATA_DIR\kernel.json`

## Health check

- `GET /health` (with `X-InkFlow-Token: <token>`) → 200 +
  `{"status":"ok","version":...,"mode":"local"}` = kernel alive + version consistency criterion
- After getting port/token from kernel.json:
  `Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -Headers @{'X-InkFlow-Token'=$token}`
- `inkflow kernel status`: reads kernel.json + PID liveness check (no params; prints
  `running/pid/port/version`; never starts the kernel)
