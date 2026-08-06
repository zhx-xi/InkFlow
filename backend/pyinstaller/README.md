# InkFlow 本地打包操作说明（F19 打包分发 0.4.0）

> 对应 spec：`specs/f19-packaging/spec.md`（Issue #48）。正式发布走
> `.github/workflows/release.yml`（tag `v*` 触发），以下为**本地手动打包**的完整步骤。

## 1. 前置条件

- Windows 10/11 x64（0.4.0 仅 Windows 三产物）
- Python 3.11+（经 uv 管理，ADR-025 依赖锁定）
- Node.js ≥ 20 + pnpm（前端依赖，ADR-025）

## 2. 内核打包（PyInstaller onedir）

```powershell
cd backend
uv sync --frozen --extra packaging   # 仅安装打包 extra（pyinstaller），不装 dev
uv run pyinstaller pyinstaller/inkflow.spec
```

产物：

```
backend/dist/inkflow/
├── inkflow.exe          # 内核入口（CLI + serve 强化版）
└── _internal/           # onedir 依赖（Python 运行时 + 第三方库）
```

> 版本：发布时由 release.yml 从 tag 注入 `pyproject.toml` 的 `version`
> （spec §2.4 版本单一来源）；本地手动打包前需自行把 `version` 置为目标版本。

## 3. 内核冒烟（P1 门禁，打包后必跑）

```powershell
# ① --help：退出码 0
dist\inkflow\inkflow.exe --help

# ② serve 交付契约：期望输出 INKFLOW_READY {port, token, pid, version} 行
dist\inkflow\inkflow.exe serve --port 0 --port-file smoke.json
# 看到 INKFLOW_READY 后 Ctrl+C 结束，并确认 smoke.json 已生成

# ③ 写作链路冒烟（可选）：配置 LLM key 后走 API/CLI 写作
```

若报 `ModuleNotFoundError`：确认缺失模块是运行时实际 import 后，加入
`inkflow.spec` 的 `hiddenimports`（hiddenimports 纪律见 spec §4.2），
重新打包后重跑冒烟。

## 4. Electron 壳打包（NSIS + 便携 ZIP）

### 4.1 国内镜像（必设）

> 评审 🟡9：electron 二进制与 electron-builder 下载的 NSIS/winCodeSign 等托管在国外，
> 国内本地打包直连缓慢/失败，**必须**设置以下环境变量（CI runner 无此问题，release.yml 不设）。

```powershell
$env:ELECTRON_MIRROR = "https://npmmirror.com/mirrors/electron/"
$env:ELECTRON_BUILDER_BINARIES_MIRROR = "https://npmmirror.com/mirrors/electron-builder-binaries/"
```

> 需在 `pnpm install` 与 `pnpm dist:win` 前设置：electron 二进制在 install 阶段下载，
> NSIS/winCodeSign 在 dist:win 阶段下载。

### 4.2 组装内核目录 + 构建

```powershell
cd frontend\packages\electron
# 组装 extraResources 源目录：backend/dist/inkflow/ 整体 → packages/kernel/
# （对应 electron-builder.yml 的 extraResources.from: ../kernel）
New-Item -ItemType Directory -Force ..\kernel | Out-Null
Copy-Item -Recurse -Force ..\..\..\backend\dist\inkflow\* ..\kernel\

cd ..\..
pnpm install --frozen-lockfile
pnpm --filter renderer build            # renderer → packages/renderer/dist/
pnpm --filter inkflow-electron build    # electron → packages/electron/out/
pnpm --filter inkflow-electron dist:win # electron-builder --win → NSIS + ZIP
```

### 4.3 产物

```
frontend/packages/electron/dist/
├── InkFlow-<version>-<arch>.exe    # NSIS 安装包（可自选安装目录）
└── InkFlow-<version>-<arch>.zip    # 便携 ZIP（解压即用文件夹）
```

## 5. 验证

- 安装包 / 便携 ZIP 内含 `resources/kernel/inkflow.exe`（内核随包分发）
- 全新机器（无 Python/Node）安装或解压后：启动 GUI → 内核拉起 → 写作流可用
- 版本一致性：安装包属性 = 关于页（/health）= INKFLOW_READY.version（tag 单一来源，spec §2.4）
