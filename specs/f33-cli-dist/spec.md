# F33: CLI 独立发布产物（cli-dist）— 功能规格

> **Spec 版本**: 1.1（2026-08-08 拍板修订：Q1=A / Q2=C / Q3=A 已确认） | **日期**: 2026-08-08 | **依据**: ADR-030 ⑤（CLI 独立发布产物决策原文）、ADR-019 v5（版本对齐 SemVer）、ADR-021（内核进程化交付契约）、Constitution P1-P6
> **Spec 变更**: v1.0 → v1.1（2026-08-08）：Q1-Q3 用户拍板——Q1=A（zip 不含 README，说明放 Release Notes/项目 README，推翻原建议 B）、Q2=C（SHELL_CONTEXT 跟随安装模式，与建议一致）、Q3=A（仅 GUI 安装器勾选，与建议一致）；正文 §1.4/§7 N9/§10/§12 D11 同步标注 ✅ 已确认，待澄清问题区留痕（原建议行保留）
> **所属阶段**: 0.5.0 Agent 集成（本地内核服务化三件套第 3 个模块：F30 #166 ✅ / F31 #167 ✅ / F33 #168 本任务，估算 2-3 人天）
> **关联 Issues**: [#168](https://github.com/zhx-xi/InkFlow/issues/168)（本任务）· [#166](https://github.com/zhx-xi/InkFlow/issues/166)（F30 内核冷启动基建 ✅ PR #171）· [#167](https://github.com/zhx-xi/InkFlow/issues/167)（F31 GUI 托盘 ✅ PR #172）· [#169](https://github.com/zhx-xi/InkFlow/issues/169)（CLI 恒 HTTP，0.6.0，不在本任务范围）
> **依赖**: ✅ 0.4.0 打包基建（f19-packaging，PR #144 + 发布门禁 #145：inkflow.spec / release.yml / electron-builder.yml / tag 版本注入机制）· ✅ #166（PR #171：kernel.json + ensure_kernel + 互斥 + stale 清理——CLI 产物含 serve 能力的依据）· ✅ #167（PR #172：GUI 托盘——里程碑并行，无代码依赖）· ✅ #152（F32 设置持久化，PR #176——无代码依赖）
> **参考 ADR**: [ADR-030](../../adr/ADR-030.md)（⑤ CLI 独立发布产物）· [ADR-019](../../adr/ADR-019.md)（版本里程碑 v5：0.5.0 = Agent 集成，SemVer 对齐）· [ADR-021](../../adr/ADR-021.md)（本地内核进程化：INKFLOW_READY 交付契约）· [ADR-020](../../adr/ADR-020.md)（Electron 选型 + electron-builder 打包）
> **状态**: 待实现 🔲

---

## 1. 概述

### 1.1 本章定位

**打包/发布基建增量专项型（非业务模块变体）**：不新建业务实体、不新增业务 API 端点、不新增业务 CLI 命令，为 0.4.0 已建立的 Windows 打包分发链（f19-packaging，✅ 已实现）增加**第 4 个发布产物**与 NSIS 安装器增强：

| 产物 | 工具 | 形态 | 用户路径 | 来源 |
|------|------|------|----------|------|
| P1 内核 exe | PyInstaller onedir | `resources/kernel/inkflow.exe` + `_internal/` | 随安装包分发，壳主进程拉起 | f19-packaging（复用，零改动） |
| P2 NSIS 安装包 | electron-builder NSIS | `InkFlow-Setup-<ver>.exe` | 正式分发（可选安装目录 + **新增 PATH 勾选**） | f19-packaging（本任务增强） |
| P3 便携 ZIP | electron-builder zip target | `InkFlow-<ver>-portable.zip` | 解压即用文件夹 | f19-packaging（复用，零改动） |
| **P4 CLI ZIP** | **PowerShell Compress-Archive** | **`inkflow-cli-<ver>.zip`** | **解压即用的独立 CLI（inkflow.exe + _internal）** | **本任务新增** |

**ADR-030 ⑤ 验收口径**（2026-08-07 用户拍板 D4=拆分里程碑）：CLI 独立发布产物（需求 1）——PyInstaller 产出独立 `inkflow-cli.zip`，与 GUI 安装包并行发布；NSIS 安装器可选「添加 CLI 到 PATH」；版本与 GUI 对齐（ADR-019 SemVer）；CLI 产物 = 完整内核（含 serve 能力，纯 CLI 用户可自行拉起内核）。

本 spec 交付 = release.yml 增量（CLI zip 打包 + 资产上传）+ NSIS 定制（installer.nsh PATH 勾选/清理）+ 验证闭环，**不含**任何内核/CLI/前端功能代码改动（§10 不在范围内）。

### 1.2 与 f19-packaging 的关系（复用 vs 增量）

| 维度 | f19-packaging（0.4.0，✅ 已实现） | 本任务（0.5.0） | 动作 |
|------|----------------------------------|-----------------|------|
| PyInstaller 构建 | `backend/pyinstaller/inkflow.spec` → `backend/dist/inkflow/`（onedir） | **同一构建产物**，GUI 嵌入 + CLI 打 zip 两种消费 | 零改动（inkflow.spec 不动） |
| 版本注入 | tag → pyproject.toml → `copy_metadata('inkflow')` → INKFLOW_READY.version | **复用**；CLI zip 命名版本同样从 `github.ref_name` 派生 | 零新机制 |
| release.yml | 3 job（package-backend / build-renderer / package-electron） | **增量**：package-backend 加 CLI zip step；package-electron 资产列表加 CLI zip | MODIFY |
| electron-builder | `electron-builder.yml`（nsis oneClick:false + zip target + extraResources） | **增量**：`nsis.include` → `build/installer.nsh`（PATH 勾选/清理） | MODIFY + CREATE |
| 体积预算 | 内核 onedir 142MB / NSIS 145.6MB / 便携 ZIP 177.4MB（v0.4.0 实测） | CLI zip ≈ 内核 onedir 142MB deflate 压缩，预算 60-90MB（§2.3） | 新增 |
| 发布操作 | `git tag vX.Y.Z && git push origin vX.Y.Z` | **不变**（同一 tag 触发，资产集合扩展） | 零改动 |

### 1.3 关键事实（现状盘点，2026-08-08 实测）

- ✅ `release.yml`（205 行，tag `v*` 触发，3 job）：package-backend（setup-python 3.11 + setup-uv cache + **先注入 tag 版本再 `uv sync --frozen --extra packaging`**（rc.3 实测坑：sync 后改 pyproject 不更新 dist-info → 版本陈旧）+ `uv run pyinstaller pyinstaller/inkflow.spec` + upload-artifact `kernel-onedir` path=`backend/dist/inkflow`）；build-renderer（renderer dist + electron out 两个 artifact）；package-electron（needs 前两 job，permissions contents: write，下载组装 → 注入 package.json version ← tag → `pnpm --filter inkflow-electron dist:win` → `gh release create`，**env GH_TOKEN 显式声明**（rc.2 实测坑））
- ✅ `inkflow.spec`（105 行）：`collect_all('inkflow')` + `copy_metadata('inkflow')`（评审 🔴2 修复）+ uvicorn 动态导入 hiddenimports + T0 excludes 清单定稿；onedir 产物 = `backend/dist/inkflow/{inkflow.exe, _internal/}`
- ✅ `electron-builder.yml`（27 行）：extraResources `../kernel` → `kernel`；win target nsis + zip；`artifactName: InkFlow-${version}-${arch}.${ext}`；nsis oneClick:false + allowToChangeInstallationDirectory:true；**无 `nsis.include`**（PATH 定制需新增）
- ✅ 版本注入机制（f19-packaging §2.4 已建立）：tag → pyproject version（package-backend，先注入再 sync）+ package.json version（package-electron）；`inkflow.__version__` = `importlib.metadata.version("inkflow")`（依赖 copy_metadata 的 dist-info）
- ✅ CLI 能力现状：`inkflow serve`（F19 #77，INKFLOW_READY 交付契约）、`inkflow project list --json`（F1）、`inkflow kernel status`（#166 dev 调试命令）——**CLI 产物 = 完整内核含 serve**
- ✅ #166 已合入（PR #171）：`%APPDATA%\InkFlow\kernel.json` + `ensure_kernel()` 三态判定（复用/互斥拉起/stale 清理）+ CreateMutexW 防双 spawn——CLI 冷启动协议的基建（ADR-030 ②）；#169（CLI 恒 HTTP）0.6.0 未合入，本任务冒烟以**当前直连实现**为准（§5.4）
- ✅ `backend/pyinstaller/README.md` 存在（本地打包操作说明，含 ELECTRON_MIRROR / ELECTRON_BUILDER_BINARIES_MIRROR 国内镜像设置）
- ✅ `frontend/packages/electron/build/` 存在（`build/icon.ico`，electron-builder buildResources 目录）；**全仓无 `.nsh` 文件**（installer.nsh 为 CREATE）
- ✅ electron-builder 26.15.7（package.json devDependencies 实测）：`nsis.include` 默认解析 `build/installer.nsh`（buildResourcesDir）；NSIS 模板钩子宏清单见 §4.1（模板实测）
- ✅ upload-artifact 单目录 path 上传后 artifact 内**平铺**（rc.1 实测坑，无仓库相对前缀）——CLI zip 走单目录上传同样平铺

### 1.4 边界声明

- **不含** CLI 恒 HTTP 路由改造（#169，0.6.0，ADR-030 ② D1=A 的落地项）——本任务只交付产物形态，冒烟以当前直连实现为准（§5.4）
- **不含** CLI-only 独立安装器（**Q3 ✅ 已确认（用户拍板：选项 A，2026-08-08）**——仅 GUI 安装器加勾选；CLI 用户 = 技术型/agent 用户，zip 包 + 手动 PATH 已满足）
- **不含** 代码签名 / 自动更新 / macOS·Linux 打包（沿用 f19-packaging §10 不在范围声明，1.0.0 事项）
- **不含** 内核/CLI/前端任何功能代码改动（`serve.py` / `project.py` / `kernel.py` / `kernel.ts` 等一律不动）
- **不含** `inkflow.spec` 改动（CLI zip 直接复用现有 onedir 产物，同源同构）
- **不含** ci.yml 改动（本任务无新 Python/前端代码 → PR CI 零增量；release.yml 为独立 workflow 不进 PR CI）

---

## 2. 产物契约

### 2.1 CLI zip 定义（P4）

| 项 | 值 |
|----|----|
| 产物名 | `inkflow-cli-<version>.zip`（如 `inkflow-cli-0.5.0.zip`） |
| 内容 | PyInstaller onedir 目录**整体**：`inkflow/inkflow.exe` + `inkflow/_internal/**`（zip 根含 `inkflow/` 顶层目录，与 GUI `resources/kernel/` 内容同源同构） |
| 来源 | `backend/dist/inkflow/`（package-backend job 内 PyInstaller 构建产物，**零新增构建**） |
| 打包工具 | PowerShell `Compress-Archive`（决策 R1，§3.4） |
| 版本来源 | `github.ref_name`（tag `v0.5.0` → `0.5.0`），与 GUI 资产同源（§2.4） |
| 发布通道 | release.yml tag 触发，与 GUI 三件套**同一 Release 并行上传**（§3.3） |
| 解压后形态 | 解压得到 `inkflow/` 文件夹 → `inkflow\inkflow.exe --help` 可用；用户可将该目录加入 PATH 或直接调用 |

**zip 条目结构示意**：

```
inkflow-cli-0.5.0.zip
└── inkflow/
    ├── inkflow.exe          # 内核入口（CLI 全命令 + serve 强化版）
    └── _internal/           # onedir 依赖（Python 运行时 + 第三方库，与 GUI resources/kernel/_internal 一致）
```

> **同源性保证**：GUI 安装包内 `resources/kernel/` 与本 zip 内 `inkflow/` 来自**同一个** PyInstaller 构建产物（`backend/dist/inkflow/`）——GUI 包 = 整体复制进 extraResources；CLI 包 = 整体打 zip。两份产物内容一致、版本一致，无第二次构建、无漂移风险。

### 2.2 产物矩阵（并行发布）

| # | 产物 | 命名 | 发布方式 | 版本对齐 |
|---|------|------|----------|----------|
| P1 | 内核 exe | `resources/kernel/inkflow.exe`（包内） | 随 P2/P3 分发 | INKFLOW_READY.version = tag |
| P2 | NSIS 安装包 | `InkFlow-Setup-<ver>-x64.exe` | Release 资产 | 安装包属性 = tag（package.json 注入） |
| P3 | 便携 ZIP | `InkFlow-<ver>-x64.zip` | Release 资产 | 同上 |
| **P4** | **CLI ZIP** | **`inkflow-cli-<ver>.zip`** | **Release 资产（本任务新增）** | **文件名版本 = tag = 包内 exe 版本** |

### 2.3 体积预算

| 项 | 值 | 依据 |
|----|----|------|
| 内核 onedir（zip 源） | **142MB**（v0.4.0 实测，AGENTS.md 0.4.0 行） | 0.4.0 发布实测，f19-packaging M6 口径 |
| CLI zip（deflate 压缩后） | **预算 60-90MB**（`_internal/` 含 pyd/dll 二进制，压缩率中等；以实测记录为准） | 估算，验收按「实测记录 + 与预算偏差 >30% 说明」口径（f19-packaging §2.3 同款） |
| 新增发布成本 | CLI zip 与 GUI 资产并行上传，无额外构建成本 | — |

> **口径**：CLI zip 不做硬性 ≤ 阈值验收；M2 冒烟通过 + 实测记录即达标（f19-packaging 评审 🟡7 确立的「实测记录 + 偏差说明」口径沿用）。

### 2.4 版本对齐契约（复用 f19-packaging §2.4，零新机制）

| 消费方 | 来源 | 机制 |
|--------|------|------|
| CLI zip 文件名 | tag | package-backend 内 `$version = '${{ github.ref_name }}'.TrimStart('v')` → `inkflow-cli-$version.zip`（与 package.json 注入同款派生） |
| zip 内 `inkflow.exe --version` / INKFLOW_READY.version | pyproject version（tag 注入）+ `copy_metadata('inkflow')` dist-info | 已建立（f19 §2.4 + inkflow.spec `copy_metadata`），**先注入版本再 `uv sync`**（rc.3 实测坑，release.yml 已含顺序注释） |
| GUI 资产版本 | package.json version（tag 注入） | 已建立（f19 §2.4） |
| 对齐断言 | 文件名版本 = 包内 exe INKFLOW_READY.version = /health = GUI 资产版本 | M5（§13） |

> **⚠️ 版本注入顺序坑（沿用，不新增）**：package-backend 的「Inject version → Sync lockfile → uv sync → pyinstaller」顺序已固化在 release.yml 注释中；CLI zip 的命名版本在注入 step **之后**派生（同一 job 内 `$version` 变量作用域），不引入新的顺序依赖。

### 2.5 产物归属与流转

| 阶段 | 归属 | 说明 |
|------|------|------|
| 构建 | package-backend | `backend/dist/inkflow/` 既是 kernel-onedir artifact 源，也是 CLI zip 源 |
| 打 zip | package-backend | `Compress-Archive -Path dist/inkflow -DestinationPath dist/inkflow-cli-<ver>.zip`（zip 内含 `inkflow/` 顶层目录，与解压验收形态一致） |
| 上传 | package-backend | upload-artifact `cli-zip` path=`backend/dist/inkflow-cli-<ver>.zip`（单文件，artifact 平铺） |
| 发布 | package-electron | 下载 `cli-zip` artifact → 复制进 `packages/electron/dist/` → 并入 `gh release create` 资产列表 |
| 验收 | 全新机器 | 解压 → `inkflow --help` → `inkflow project list --json` → `inkflow serve`（§13 M2） |

---

## 3. release.yml 增量

### 3.1 现状（3 job 流水线，2026-08-08 实测）

```
tag v* ──► package-backend（PyInstaller onedir → kernel-onedir artifact）
        ├─► build-renderer（renderer dist + electron out artifacts）
        └─► package-electron（needs 前两 job：组装 → dist:win → gh release create 三件套资产）
```

- package-backend：`permissions: contents: read`（**无发布权限**）——CLI zip 不能在此 job 直接挂 Release
- package-electron：`permissions: contents: write` + `env GH_TOKEN: ${{ github.token }}`（rc.2 实测坑，显式声明）——**唯一发布点**
- 资产收集现状：`Get-ChildItem packages/electron/dist -File | Where-Object Extension -in '.exe','.zip'`（通配收集）

### 3.2 package-backend 增量（打 zip + 上传）

在 `Build kernel (PyInstaller onedir)` step 之后新增两个 step：

```yaml
      # F33 CLI 独立发布产物（spec f33-cli-dist §3.2）：同一份 onedir 产物打 zip
      # ⚠️ 必须先完成版本注入（上方 Inject version step）再打包——zip 内 exe 的
      #    dist-info 版本 = tag（copy_metadata 机制）；zip 文件名版本也从此派生
      - name: Package CLI zip
        shell: pwsh
        run: |
          $version = '${{ github.ref_name }}'.TrimStart('v')
          Compress-Archive -Path dist/inkflow -DestinationPath "dist/inkflow-cli-$version.zip" -CompressionLevel Optimal
          Write-Host "CLI zip created: dist/inkflow-cli-$version.zip"

      - name: Upload CLI zip artifact
        uses: actions/upload-artifact@v7
        with:
          name: cli-zip
          path: backend/dist/inkflow-cli-*.zip
```

**要点**：
- `Compress-Archive -Path dist/inkflow` 将 onedir 目录**整体**入包（zip 根含 `inkflow/` 顶层目录）——与解压验收形态（§2.1）一致；本地 PowerShell 5.1 同款命令可复现（决策 R1）
- `path: backend/dist/inkflow-cli-*.zip` 通配（单文件，上传后 artifact 平铺）；`defaults.run.working-directory: backend` 只影响 run step，upload-artifact path 相对仓库根（GITHUB_WORKSPACE）——沿用 release.yml 既有约定
- 若 Compress-Archive 出现偶发失败（大目录 IO），可加一次重试或改用 `-Force`；决策 R3 = **失败即阻断发布**（§3.4）

### 3.3 package-electron 增量（资产合并）

在 `Package Windows artifacts (NSIS + ZIP)` step 之后、`Create GitHub Release` step 之前新增下载 + 复制：

```yaml
      - name: Download CLI zip artifact
        uses: actions/download-artifact@v7
        with:
          name: cli-zip
          path: cli-zip

      # CLI zip 并入发布资产目录（gh release create 资产收集的既有位置）
      - name: Place CLI zip into release assets
        shell: pwsh
        run: |
          Copy-Item -Force "$env:GITHUB_WORKSPACE/cli-zip/inkflow-cli-*.zip" packages/electron/dist/
```

**`Create GitHub Release` step 资产收集零改动（评审 🔴-1 修订）**：现有收集逻辑
`Get-ChildItem packages/electron/dist -File | Where-Object { $_.Extension -in '.exe', '.zip' }`
**通配已覆盖 CLI zip**（扩展名 `.zip` 匹配）——若按初稿「显式追加 `$assets += $cliZip.FullName`」
会造成同一文件在资产列表出现两次 → `gh release create` 报 duplicate asset 或重复上传。
正确做法 = 依赖既有通配收集，**不追加**；CLI zip 只需被复制进 `packages/electron/dist/` 即自动进入 Release 资产。

### 3.4 决策 R1-R3

| # | 决策 | 方案 | 理由 | 备选（否决） |
|---|------|------|------|--------------|
| R1 | **CLI zip 打包工具 = PowerShell Compress-Archive** | `Compress-Archive -Path dist/inkflow -DestinationPath ...` | 与 CI（windows-latest 自带 pwsh）和本地（Windows PowerShell 5.1）**同一条命令**，本地可完整复现；零新增依赖；142MB 目录规模性能可接受 | Python zipfile（`uv run python -m zipfile`）：多一层 venv 依赖、CI 与本地解释器版本差异；tar.exe（bsdtar）：非 PowerShell 原生、zip 兼容性需验证 |
| R2 | **打 zip 的 job = package-backend** | 紧跟 PyInstaller 构建，产物同源零拷贝；上传独立 `cli-zip` artifact | 构建与打包在同一 job 内完成（文件已在本地）；失败在源头暴露；package-electron 只做资产合并（单一发布点职责不变） | package-electron 重打：需重新下载 142MB kernel-onedir 再压缩，且发布 job 承担打包职责（职责混杂） |
| R3 | **CLI zip 打包失败 = 阻断整个发布** | 不设 continue-on-error | Release 资产集合（GUI 三件套 + CLI zip）是发布契约（M1/M7），缺 CLI zip 的 Release 是残缺发布；失败在 package-backend 源头暴露，修复成本最低 | continue-on-error（静默发布残缺资产，与 Issue #168 验收 1 冲突） |

### 3.5 变更影响面

- **不新增 job**：CLI zip 完全并入既有 3 job 流水线（§3.2/§3.3 各 2 个 step）
- **不新增 workflow**：沿用 tag `v*` 触发（f19-packaging §7.2 R1 独立 workflow 决策不变）
- **本地等价复现**：`backend/pyinstaller/README.md` 补 CLI zip 打包 + 冒烟步骤（§8 MODIFY）
- **发布操作不变**：`git tag v0.5.0 && git push origin v0.5.0` → 同一 Release 含 4 资产

---

## 4. NSIS PATH 勾选（installer.nsh 定制）

### 4.1 electron-builder 定制机制（26.15.7 模板实测）

electron-builder 的 `nsis.include` 配置指向自定义 NSIS 脚本（默认解析 `build/installer.nsh`，buildResourcesDir 内），该脚本在生成安装器时被 `!include` 进**脚本头部**（sharedHeader，先于模板），通过**钩子宏**在模板固定位置展开。26.15.7 模板实测可用的钩子（本任务用到的加粗）：

| 钩子宏 | 展开位置（模板实测） | 用途 |
|--------|----------------------|------|
| `customInit` | `.onInit`（安装器初始化后、页面显示前） | 变量初始化 |
| `customWelcomePage` | 欢迎页位置（assistedInstaller.nsh L9-11） | 自定义欢迎页 |
| **`customPageAfterChangeDir`** | **目录选择页之后、INSTFILES 页之前（assistedInstaller.nsh L41-44，模板注释「you can show custom page here」）** | **PATH 勾选页（本任务）** |
| **`customInstall`** | **安装 Section 末尾（installSection.nsh，文件全部解压后、快捷方式创建后）** | **PATH 写入（本任务）** |
| **`customUnInstall`** | **卸载 Section 开头（uninstaller.nsh，文件删除前，$INSTDIR 仍有效）** | **PATH 清理（本任务）** |
| `customUnInit` / `customUnWelcomePage` / `customUninstallPage` / `customFinishPage` | 卸载初始化 / 卸载页 / 完成页 | 本任务不用 |

**关键机制事实（模板实测）**：
- 安装模式：本项目未设 `perMachine` → `INSTALL_MODE_PER_ALL_USERS` 未定义 → assisted 安装器显示**安装模式选择页**（multiUserUi.nsh `PAGE_INSTALL_MODE`），默认 per-user（`setInstallModePerUser` → `$installMode = "CurrentUser"`，`SetShellVarContext current`），可选 per-machine（`all`，需 UAC 提权）
- `SHELL_CONTEXT`：electron-builder 自带模板（`include/installer.nsh` 的 `registryAddInstallInfo`、`uninstaller.nsh` 的 `DeleteRegKey SHELL_CONTEXT`）使用的**注册表根符号**，随安装模式解析为 HKCU 或 HKLM——自定义脚本同款使用即可（Q2 的 C 方案零额外机制）
- `customUnInstall` 在卸载 Section 开头展开 → 此时 `$INSTDIR` 仍指向安装目录，PATH 条目目标可精确匹配
- 静默安装（`/S`）：页面全部跳过 → `customPageAfterChangeDir` 不执行 → 勾选变量保持默认值 0（不加 PATH）——与「默认不勾」语义一致（§4.5）

### 4.2 勾选页设计（customPageAfterChangeDir）

- nsDialogs 自定义页：一个 checkbox「添加 InkFlow CLI 到 PATH（默认不勾）」+ 说明文字（「将 `$INSTDIR\resources\kernel` 加入 PATH，可在任意终端使用 inkflow 命令」）
- 页面位置：目录选择之后、安装开始之前（模板提供的官方自定义页钩子）——用户选定安装目录后看到勾选项，语义连贯
- 结果存变量 `Var addCliToPath`（默认 `0`；勾选页 leave 回调置 `1`）
- 静默安装/升级跳过页面 → 变量保持默认 `0` → 不加 PATH
- 升级安装（覆盖旧版本）：页面仍显示，默认不勾；若旧版本已加过 PATH，customInstall 幂等去重（§4.3）不产生重复条目

### 4.3 PATH 写入算法（customInstall）

```
1. 若 $addCliToPath != "1" → 跳过（默认不勾 / 静默安装）
2. 目标条目 = "$INSTDIR\resources\kernel"（GUI 内嵌内核即 CLI，不复制第二份 exe——§5.1）
3. 读取 SHELL_CONTEXT\Environment\Path（REG_EXPAND_SZ）
4. 若 Path 不存在 → 直接写入目标条目（WriteRegExpandStr）
5. 若已存在 → 按 ';' 切分，大小写不敏感 + 尾部反斜杠归一化后比对：
   - 已含目标条目 → 跳过（幂等，升级场景）
   - 未含 → 追加 ";目标条目"
6. 长度保护：若读取长度 ≥ 1000 字符（NSIS 字符串上限 1024 的安全余量）→ 跳过写入并
   DetailPrint 警告（绝不截断写回，§7 N4）
7. WriteRegExpandStr SHELL_CONTEXT "Environment" "Path" <新值>
8. 广播 WM_SETTINGCHANGE：System::Call 'user32::SendMessageTimeout(i 0xFFFF, i 0x001A, i 0,
   w "Environment", i 0x0002, i 5000, *i r0)'——新开终端立即生效（已开终端需重启）
```

> **REG_EXPAND_SZ 必须保留**：PATH 含 `%SystemRoot%` 等展开变量，必须 `WriteRegExpandStr`（REG_EXPAND_SZ），不能用 `WriteRegStr`（REG_SZ 会破坏既有展开语义）。

### 4.4 PATH 清理算法（customUnInstall）

```
1. 目标条目 = "$INSTDIR\resources\kernel"（与安装写入完全同构）
2. 读取 SHELL_CONTEXT\Environment\Path
3. 按 ';' 切分，精确匹配删除目标条目（大小写不敏感 + 尾部反斜杠归一化）
   - 只删「完全等于目标条目」的段——用户手动加过其他 InkFlow 路径不误删（§7 N3）
4. 若剩余为空 → 删除 Environment\Path 整个值（若原本只有我们一条）
5. 否则 WriteRegExpandStr 写回剩余条目（同样 1000 字符保护）
6. 广播 WM_SETTINGCHANGE（同 §4.3）
```

> 卸载时**不依赖**安装时是否勾选：若用户安装时未勾选但之后手动加过 PATH，卸载时同样清理（删除动作幂等，PATH 里没有就不动）。安装时勾选与否的信息不落注册表（YAGNI——卸载只需按目标条目精确匹配）。

### 4.5 场景矩阵

| 场景 | 行为 |
|------|------|
| 全新安装 + 勾选 | 目录选择后出现勾选页 → 安装完成 PATH 含 `$INSTDIR\resources\kernel` → 新终端 `inkflow --help` 可用 |
| 全新安装 + 不勾（默认） | 勾选页不勾 → PATH 不变 |
| 静默安装 `/S` | 页面跳过 → 不加 PATH（静默安装无法交互，默认不勾语义） |
| 升级安装（旧版已勾选） | 勾选页默认不勾；若本次勾选 → 去重追加（不产生重复）；若不勾 → 不清理旧条目（升级不撤销用户既有 PATH，文档说明） |
| 卸载 | 无论安装时是否勾选，按目标条目精确清理 + WM_SETTINGCHANGE |
| 便携 ZIP / CLI zip 用户 | 无 NSIS 安装器 → 无 PATH 行为（CLI zip 用户手动加 PATH 或直接调用） |

### 4.6 installer.nsh 骨架示意（实现以 TDD/冒烟验证为准）

```nsh
; frontend/packages/electron/build/installer.nsh（F33 CLI 独立发布产物，spec §4）
; electron-builder nsis.include 默认解析位置（buildResourcesDir）

!ifndef BUILD_UNINSTALLER
  Var addCliToPath
  Var addCliToPathCheckbox

  ; 勾选页：目录选择之后、安装开始之前（assistedInstaller.nsh customPageAfterChangeDir 钩子）
  !macro customPageAfterChangeDir
    Page custom AddCliToPathPage AddCliToPathPageLeave
    Function AddCliToPathPage
      nsDialogs::Create 1018
      Pop $0
      ${If} $0 == error
        Abort
      ${EndIf}
      ${NSD_CreateLabel} 0 0 100% 24u "添加 InkFlow CLI 到 PATH（默认不勾）..."
      ${NSD_CreateCheckBox} 0 40u 100% 12u "将 $INSTDIR\resources\kernel 加入 PATH"
      Pop $addCliToPathCheckbox
      nsDialogs::Show
    FunctionEnd
    Function AddCliToPathPageLeave
      ${NSD_GetState} $addCliToPathCheckbox $addCliToPath
    FunctionEnd
  !macroend
!endif

; 安装末尾：写入 PATH（仅勾选时）
!macro customInstall
  ${If} $addCliToPath == "1"
    Call AddKernelDirToPath
  ${EndIf}
!macroend

; 卸载开头：清理 PATH
!macro customUnInstall
  Call un.RemoveKernelDirFromPath
!macroend
```

> 完整实现含 `AddKernelDirToPath` / `un.RemoveKernelDirFromPath` 函数体（读写 SHELL_CONTEXT\Environment\Path + 去重 + 1000 字符保护 + WM_SETTINGCHANGE 广播）；卸载侧函数需 `un.` 前缀（NSIS 卸载段约定）；`${NSD_*}` 来自 nsDialogs（electron-builder 模板已 `!include MUI2.nsh`，nsDialogs 随 MUI2 可用——实现时冒烟验证）。

---

## 5. 关键差异/决策节

### 5.1 同一份 PyInstaller 构建产物，两种消费方式

```
                ┌─► 整体复制进 frontend/packages/kernel/ ──► extraResources ──► resources/kernel/inkflow.exe（GUI 壳拉起）
backend/dist/inkflow/
（PyInstaller onedir， 142MB）│
                └─► Compress-Archive 整体打 zip ──► inkflow-cli-<ver>.zip（独立 CLI 发行）
```

- **零新增构建**：CLI zip 与 GUI 内核来自同一个 `uv run pyinstaller pyinstaller/inkflow.spec` 产物（Issue #168 需求明细 1「复用 0.4.0 打包配置，产物分离」）——GUI 包 = 内核嵌入 resources/kernel/；CLI 包 = 独立发行
- **同构保证**：两份产物内容逐字节同源（同一 dist/inkflow 目录），版本天然对齐，无「CLI 内核落后于 GUI 内核」的漂移面
- **INKFLOW_READY 交付契约不变**：CLI zip 内 `inkflow serve --port 0` 输出与 GUI 内嵌内核完全一致（同一 exe）

### 5.2 版本对齐链路（本任务唯一的版本面 = 文件名 + 既有 dist-info）

```
tag v0.5.0（单一事实来源，f19 §2.4）
 ├─► package-backend：pyproject version 注入（先注入再 sync）──► copy_metadata('inkflow') ──► exe 内 dist-info 0.5.0
 │        └─► $version 派生 ──► inkflow-cli-0.5.0.zip（文件名版本）
 └─► package-electron：package.json version 注入 ──► InkFlow-Setup-0.5.0-x64.exe / InkFlow-0.5.0-x64.zip
```

- 无新版本机制：CLI zip 文件名版本与 GUI 资产同为 tag 派生；zip 内 exe 版本经既有 `importlib.metadata` + copy_metadata 链路（INKFLOW_READY.version / `--version` / /health）
- M5 对齐断言见 §13

### 5.3 NSIS PATH 与 CLI zip 的关系（两个分发通道，一个内核）

| 通道 | 用户 | PATH 条目 | 说明 |
|------|------|-----------|------|
| GUI 安装器 + 勾选 | GUI 用户顺带用 CLI | `$INSTDIR\resources\kernel` | 不复制第二份内核；卸载随 GUI 清理 |
| CLI zip 独立解压 | 纯 CLI 用户（无 GUI） | 手动加 PATH（或直接调用） | 完整内核含 serve；独立生命周期，不受 GUI 卸载影响 |

- 两者指向**同一个 exe 形态**（onedir 内核），功能等价（含 serve → 纯 CLI 用户可自行拉起内核，ADR-030 ②）
- 互不干扰：GUI 卸载只清理自己的 PATH 条目（精确匹配 `$INSTDIR\resources\kernel`），不触碰 CLI zip 用户手动添加的路径（§7 N3）

### 5.4 与 #169（CLI 恒 HTTP）的关系

- #169（0.6.0）将 CLI 改为「先 `ensure_kernel()` 再经 HTTP 调用」（ADR-030 ② D1=A）——**本任务不实现**，但本任务是它的**产物载体**：CLI zip 是 #169 改造后 CLI 的发行通道
- 本任务验收冒烟（M2）以**当前直连实现**为准：`inkflow project list --json` 直连 domain 可用（现状即如此）；#169 合入后同一 zip 内的 exe 行为自动升级为恒 HTTP（产物形态、命名、版本机制均不变）
- `inkflow serve` 冒烟验证 serve 能力本身（拉起内核 + INKFLOW_READY），与 #169 无关

### 5.5 专项型 spec 13 节映射（对照 f19-packaging）

| 13 节 | f19-packaging（0.4.0 三产物） | 本任务（0.5.0 CLI 增量） |
|-------|------------------------------|--------------------------|
| §2 数据模型 → 产物契约 | 三产物矩阵 + 体积预算 + 版本注入 | 四产物矩阵（新增 P4）+ CLI zip 定义 + 体积预算 + 版本对齐复用 |
| §3 API → PyInstaller 契约 | inkflow.spec + hiddenimports + 冒烟 | **release.yml 增量**（§3）：CLI zip step + 资产合并 |
| §4（f19 内部） | 依赖瘦身 T0 / B+ 装配 | **NSIS PATH 定制**（§4）：installer.nsh + 钩子宏 |
| §5 关键差异 | 瘦身/决策节 | 同一产物两消费 + 版本链路 + PATH 与 zip 关系 |
| §8 文件结构 | CREATE/MODIFY 逐文件 | §6 组织规则 + §8 文件结构（本任务仅 1 CREATE + 4 MODIFY） |
| §12 决策表 | D1-D9 | D1-D11（R1-R3 并入 D1-D3） |
| §13 验收 | M1-M11 | M1-M8（4 项 Issue 验收 + 质量门禁） |

---

## 6. 组织规则/边界

### 6.1 文件组织规则

- **installer.nsh 归属 `frontend/packages/electron/build/`**：electron-builder `nsis.include` 未显式配置时默认从 buildResourcesDir 解析 `installer.nsh`（NsisTarget.js 实测 `getResource(this.options.include, "installer.nsh")`）——本任务在 electron-builder.yml **显式声明** `nsis.include: build/installer.nsh`（自文档化，防默认解析规则变更）；`build/` 目录已存在（icon.ico）
- **CLI zip 产物归属 `backend/dist/`**：与 PyInstaller 产物同目录（`backend/dist/inkflow-cli-<ver>.zip`），本地打包与 CI 同构；`.gitignore` 已覆盖 dist/（沿用，无需改动）
- **artifact 命名规范**：`cli-zip`（upload-artifact name 常量）；下载后经 `Copy-Item` 进 `packages/electron/dist/` 与 GUI 资产同目录发布（§3.3）
- **版本派生单一来源**：`github.ref_name`（package-backend 与 package-electron 各自 TrimStart('v')，与 f19 §2.4 同款）
- **release.yml 注释规范**：新增 step 均带 `F33` 前缀注释（与既有 `F19 打包分发` 注释风格一致），记录实测坑（artifact 平铺 / GH_TOKEN / 版本注入顺序）

### 6.2 产物归属表

| 产物/文件 | 构建 job | 上传/发布 | 消费方 |
|-----------|----------|-----------|--------|
| kernel-onedir artifact | package-backend | upload-artifact | package-electron（GUI 组装） |
| cli-zip artifact（新） | package-backend | upload-artifact | package-electron（Release 资产） |
| renderer-dist / electron-out | build-renderer | upload-artifact | package-electron |
| InkFlow-Setup/zip + inkflow-cli zip | package-electron | gh release create | 用户 |

### 6.3 边界声明（明确不改动）

- `backend/pyinstaller/inkflow.spec`：零改动（onedir 产物直接复用）
- `backend/src/inkflow/`：零改动（无任何内核/CLI 代码变更）
- `frontend/packages/electron/src/`：零改动（壳不感知 CLI zip；PATH 勾选纯安装器侧）
- `frontend/packages/renderer/`：零改动
- `ci.yml`：零改动（无新 Python/前端代码；release.yml 独立 workflow 不进 PR CI）
- `specs/f19-packaging/spec.md`：零改动（已合入 ✅；本任务增量以本 spec 为准，f19 §10 不在范围声明不覆盖 CLI zip——f19 是 0.4.0 快照，不回写）

---

## 7. 边界情况与错误处理

| # | 场景 | 行为 | 归属 |
|---|------|------|------|
| N1 | CLI zip 打包失败（Compress-Archive 异常） | **阻断整个发布**（决策 R3）——package-backend job 失败，package-electron 不执行，Release 不创建 | §3.4 R3 |
| N2 | PATH 已存在 InkFlow 条目（升级/重复安装） | 去重：大小写不敏感 + 尾部反斜杠归一化比对，已含则跳过 | §4.3 |
| N3 | 卸载时 PATH 条目被用户手动修改/其他程序引用同一路径 | 只按「完全等于 `$INSTDIR\resources\kernel`」的段精确删除；用户自加的其他 InkFlow 路径不动；删除幂等（无条目则无操作） | §4.4 |
| N4 | 既有 PATH 超长（≥1000 字符，NSIS 字符串上限 1024） | **跳过写入/清理并 DetailPrint 警告**——绝不截断写回（截断 = 破坏用户 PATH 的严重事故）；文档记录此限制 | §4.3/§4.4 |
| N5 | 安装目录含中文/空格 | PATH 条目为目录字符串（不含分号即可，无需引号）；安装器本身已支持自选目录（f19 已知坑：中文路径偶发问题——M3/M4 手工验证覆盖中文目录场景） | §4.3 |
| N6 | 静默安装 `/S` / 无人值守 | 勾选页跳过 → 不加 PATH（默认不勾语义，无法交互场景的正确退化） | §4.2/§4.5 |
| N7 | 升级安装（旧版本已加 PATH） | customInstall 幂等去重；升级不撤销既有 PATH | §4.5 |
| N8 | 便携 ZIP / CLI zip 用户 | 无安装器 → 无 PATH 行为；CLI zip 用户手动加 PATH（README 说明） | §5.3 |
| N9 | per-machine 安装（提权后） | PATH 写 HKLM（SHELL_CONTEXT 跟随安装模式，**Q2 ✅ 已确认（用户拍板：选项 C）**）；卸载器同样以提权运行，可清理 HKLM | §4.1/Q2 |
| N10 | artifact 平铺结构（upload-artifact 单目录上传无仓库前缀） | 沿用既有坑规避：下载到显式子目录后 Copy-Item（rc.1 实测坑已在 release.yml 注释）——CLI zip 是**单文件** artifact，平铺影响为零 | §3.2 |
| N11 | 版本注入顺序（先注入再 sync） | 既有 release.yml 顺序已固化；CLI zip 命名在注入 step 之后派生，无新顺序依赖 | §2.4 |
| N12 | 本地打包缺 ELECTRON_MIRROR / ELECTRON_BUILDER_BINARIES_MIRROR | 国内网络直连失败——`backend/pyinstaller/README.md` 已有说明（f19 评审 🟡9），本任务补 CLI zip 步骤时保留 | §8 |
| N13 | 卸载器编译（BUILD_UNINSTALLER）与安装器共用 installer.nsh | `!ifndef BUILD_UNINSTALLER` 守卫：安装侧 Var/勾选页宏仅安装器编译；卸载侧函数 `un.` 前缀（§4.6 骨架已含守卫） | §4.6 |

---

## 8. 文件结构

> 清单经 2026-08-08 实测核实（Test-Path）：`installer.nsh` 全仓不存在（CREATE）；其余文件均存在（MODIFY）。

### 8.1 CREATE（新建，1 项）

| 文件 | 内容 |
|------|------|
| `frontend/packages/electron/build/installer.nsh` | NSIS 定制脚本（§4.6 骨架）：`customPageAfterChangeDir` 勾选页（默认不勾）+ `customInstall` PATH 写入 + `customUnInstall` PATH 清理 + `BUILD_UNINSTALLER` 守卫；随 electron-builder `nsis.include` 打包进安装器 |

### 8.2 MODIFY（修改，4 项）

| 文件 | 变更 | 节 |
|------|------|-----|
| `.github/workflows/release.yml` | package-backend 加 2 step（Package CLI zip + Upload CLI zip artifact，§3.2）；package-electron 加 2 step（Download CLI zip artifact + Place CLI zip into release assets，§3.3）+ Create GitHub Release 资产收集显式追加 CLI zip | §3.2/§3.3 |
| `frontend/packages/electron/electron-builder.yml` | `nsis` 节新增 `include: build/installer.nsh`（显式声明，自文档化） | §4.1/§6.1 |
| `backend/pyinstaller/README.md` | 补「CLI zip 打包 + 冒烟」小节：本地 `Compress-Archive` 命令、`inkflow-cli-<ver>.zip` 产物说明、解压冒烟三步（--help / project list --json / serve） | §9.2 |
| `AGENTS.md` | 0.5.0 里程碑行回写（收尾，Phase 8：`#168 ✅` + PR 号） | — |

### 8.3 不修改（明确声明，防实现漂移）

- `backend/pyinstaller/inkflow.spec`（onedir 产物直接复用，零改动）
- `backend/src/inkflow/**`（无内核/CLI 代码变更；`serve.py`/`project.py`/`kernel.py` 均不动）
- `frontend/packages/electron/src/**`（壳不感知 CLI zip；无 preload/main 变更）
- `frontend/packages/renderer/**`（渲染层零改动）
- `.github/workflows/ci.yml`（无新 Python/前端代码；release.yml 独立 workflow 不进 PR CI）
- `frontend/pnpm-lock.yaml` / `backend/uv.lock`（零依赖变更）
- `specs/f19-packaging/spec.md`（已合入 ✅ 不回写；增量以本 spec 为准）

---

## 9. 测试策略

### 9.1 层次与载体

| 层 | 载体 | 覆盖 |
|----|------|------|
| 打包脚本（release.yml） | **预发布 tag（`v0.5.0-rc.N`）实跑**——本地不可执行（CI YAML 无法本地跑）；release.yml 仅 tag `v*` 触发（无 workflow_dispatch），走 #145 先例的 rc 迭代验证路径，全绿后正式 tag | §3.2/§3.3 全部 step |
| NSIS 定制 | **无法单元测试**（NSIS 宏在 electron-builder 生成脚本内展开）——手工验证清单（§9.4）+ 全新机器模拟 | §4 全部 |
| CLI zip 冒烟（本地近似） | PowerShell 脚本：`Compress-Archive` 打 zip → 解压到临时目录 → 三步冒烟 | M2 |
| 全新机器验证 | 隔离环境（VM/沙箱）：解压 CLI zip → 冒烟；安装器勾选/卸载 PATH 走查 | M2/M3/M4/M6 |
| 回归 | ci.yml 既有 job（本任务无新代码 → PR CI 零增量，全绿即可） | M8 |

### 9.2 关键场景

1. **CLI zip 本地复现**（backend 目录）：

```powershell
# ① 打包（复用 f19 流程）→ ② 打 zip（与 CI 同款命令）
Compress-Archive -Path dist/inkflow -DestinationPath dist/inkflow-cli-0.5.0.zip -CompressionLevel Optimal
# ③ 全新机器近似：解压到临时目录（模拟无 venv 环境）
Expand-Archive dist/inkflow-cli-0.5.0.zip "$env:TEMP\inkflow-cli-test" -Force
# ④ 冒烟三步（PYTHONUTF8=1 保证中文输出编码；inkflow.spec 已带运行时编码钩子）
$env:PYTHONUTF8 = "1"
& "$env:TEMP\inkflow-cli-test\inkflow\inkflow.exe" --help          # 退出码 0，usage 输出
& "$env:TEMP\inkflow-cli-test\inkflow\inkflow.exe" project list --json   # JSON 信封
& "$env:TEMP\inkflow-cli-test\inkflow\inkflow.exe" serve --port 0 --port-file smoke.json
# 期望输出 INKFLOW_READY {port, token, pid, version} 行 → Ctrl+C 结束
```

2. **NSIS PATH 手工验证**（§9.4 清单）：勾选安装 → 新终端 `inkflow --help`；不勾安装 → PATH 无条目；卸载 → 无残留
3. **版本对齐**：zip 文件名版本 = 解压后 `inkflow.exe --version` / INKFLOW_READY.version = GUI 资产版本（M5）
4. **升级路径**：旧版勾选安装 → 新版覆盖安装（勾选/不勾两分支）→ PATH 无重复条目

### 9.3 打包脚本单元测试？YAGNI 评估

| 候选 | 评估 | 结论 |
|------|------|------|
| zip 步骤抽 Python 脚本 + pytest | zip 步骤是 release.yml 内联 PowerShell（3 行），抽脚本反而增加构建链复杂度；Compress-Archive 行为由 PowerShell 保证 | **不引入**——冒烟（§9.2 场景 1）即验证 |
| installer.nsh 逻辑单测 | NSIS 宏无法在 pytest/vitest 中执行；electron-builder 生成脚本才可编译 | **不引入**——手工清单 + 全新机器验证 |
| 版本对齐断言脚本 | 有价值但一次性（tag 发布时验证） | 不新建仓库脚本；验证并入 §9.2 场景 3 手工/命令执行 |

> 结论：本任务零新 Python/前端代码 → 无 pytest/vitest 增量、ci.yml 零改动；质量门禁 = 冒烟脚本 + 手工清单 + release.yml 实跑（与 f19-packaging §9 同款口径：「PyInstaller/release.yml 为 CI/发布层，不进 pytest 覆盖率口径」）。

### 9.4 NSIS 手工验证清单（M3/M4/M6 载体）

| # | 步骤 | 通过标准 |
|---|------|----------|
| V1 | 全新安装 + **勾选**（默认目录，含中文路径变体） | 安装完成 → 新开终端 `inkflow --help` 可用；`$env:Path` 含 `resources\kernel`；注册表 HKCU/HKLM `Environment\Path` 含目标条目（REG_EXPAND_SZ） |
| V2 | 全新安装 + **不勾** | PATH 无 InkFlow 条目；`inkflow` 命令不存在 |
| V3 | 静默安装 `/S` | PATH 无条目（页面跳过） |
| V4 | 升级安装（旧版勾选过） | 无重复条目（去重）；PATH 仍可用 |
| V5 | 卸载（勾选安装过） | 卸载完成 → PATH 无残留；新终端 `inkflow` 不存在；PATH 其他条目完好（含 %SystemRoot% 展开） |
| V6 | 卸载（未勾选但手动加过同路径） | 手动条目同样被清理（幂等语义） |
| V7 | PATH 超长保护 | 构造长 PATH（≥1000 字符）→ 安装器跳过写入并警告，PATH 未被截断 |

> V1/V5 覆盖 Issue #168 验收 3；V2 覆盖验收 3 的「默认不勾」语义；全新机器模拟（M4）在 VM/沙箱执行 V1+V5。

---

## 10. 不在范围内

| 项 | 归属/原因 |
|----|-----------|
| CLI 恒 HTTP 路由改造（ensure_kernel + 统一客户端） | **#169**（0.6.0，ADR-030 ② D1=A 落地项）——本任务只交付产物形态；冒烟以当前直连实现为准（§5.4） |
| CLI-only 独立安装器 | **Q3 ✅ 已确认（用户拍板：选项 A，2026-08-08）**——仅 GUI 安装器加勾选；CLI 用户 = 技术型/agent 用户（GitHub 下载 zip + 手动 PATH），CLI-only 安装器留 1.0.0 需求驱动再评估 |
| CLI zip 内含 README / 示例配置 | **Q1 ✅ 已确认（用户拍板：选项 A，2026-08-08）**——zip 不含 README（用户从 GitHub 下载即见项目 README；CLI 有 `--help` 自带完整命令帮助）；说明放 Release Notes / 项目 README |
| PATH 写入位置（HKCU vs HKLM vs 跟随安装模式） | **Q2 ✅ 已确认（用户拍板：选项 C，2026-08-08）**——`SHELL_CONTEXT` 跟随安装模式（§4.1 机制已核实）；正文 §4 已按 C 方案撰写 |
| 代码签名 / 自动更新 / macOS·Linux 打包 | 沿用 f19-packaging §10（1.0.0 事项，本任务零新增） |
| 内核/CLI/前端功能代码 | 本任务零代码改动（§8.3） |
| kernel.json / ensure_kernel 行为变更 | #166 已交付（PR #171），本任务只消费其 serve 能力（CLI 产物 = 完整内核） |
| CLI zip 增量更新 / 差分发布 | 未立项（0.x 阶段全量发布，YAGNI） |

---

## 11. 依赖关系

### 11.1 依赖（本任务需要的既有交付）

| 依赖 | 交付 | 用途 |
|------|------|------|
| 0.4.0 打包基建（f19-packaging） | ✅ PR #144 + 发布门禁 #145（v0.4.0 2026-08-07 发布） | inkflow.spec（onedir 产物）、release.yml（3 job 流水线 + 版本注入 + GH_TOKEN/平铺坑注释）、electron-builder.yml（nsis/zip 配置）、本地打包 README（ELECTRON_MIRROR） |
| #166 F30 内核冷启动基建 | ✅ PR #171 | kernel.json + ensure_kernel + 互斥 + stale 清理——CLI 产物 = 完整内核含 serve 能力的依据（ADR-030 ②）；`inkflow kernel status` dev 命令 |
| #167 F31 GUI 托盘 | ✅ PR #172 | 里程碑并行，**无代码依赖**（本任务不触碰壳）；PATH 勾选指向的 `$INSTDIR\resources\kernel` 与托盘共用同一内嵌内核 |
| #77 F19 serve 强化版 | ✅ PR #85（0.3.0） | INKFLOW_READY 交付契约（CLI zip 冒烟验收） |
| #152 F32 设置持久化 | ✅ PR #176 | 里程碑并行，无代码依赖 |
| ADR-030 ⑤ / ADR-019 v5 / ADR-021 | ✅ | 产物形态 / 版本对齐 / 交付契约依据 |

### 11.2 被依赖（下游）

| 下游 | 依赖本任务的什么 |
|------|------------------|
| #169 CLI 恒 HTTP（0.6.0） | CLI zip 是改造后 CLI 的发行通道（§5.4）——产物形态/命名/版本机制不变 |
| F20 MCP（1.0.0，ADR-023 修订版薄客户端） | 外部 agent 冷调用场景的 CLI 分发（ADR-030 ⑤「CLI/MCP/skills 冷调用自动拉起内核」愿景的产物基础） |
| ADR-022 skills 包（1.0.0） | 同上（skills 封装 inkflow CLI 的场景依赖独立 CLI 可执行文件） |
| 1.0.0 跨平台打包 | release.yml 的 CLI zip 模式扩展到 mac/linux（f19 §11.2 同款扩展路径） |

### 11.3 编号口径声明

F33 为打包基建增量模块：F30（#166 内核冷启动 ✅ PR #171）、F31（#167 GUI 托盘 ✅ PR #172）、F32（#152 设置持久化 ✅ PR #176）均已占用，本任务顺延 **F33**（0.5.0 本地内核服务化三件套第 3 个模块；#169 恒 HTTP 属 0.6.0，不占 F 编号）。以 ADR-019 v5 为准（F25 移除不复用；F26-F29 为 Agent 化升级规划；F32 之后新基建承接 F33）。

---

## 12. 关键架构决策记录

| # | 决策 | 方案 | 理由 | 备选（否决） |
|---|------|------|------|--------------|
| D1 | **CLI zip 打包工具 = PowerShell Compress-Archive**（R1） | `Compress-Archive -Path dist/inkflow -DestinationPath dist/inkflow-cli-<ver>.zip` | CI（pwsh）与本地（PS 5.1）同一条命令，本地可完整复现；零新增依赖；142MB 规模性能可接受；zip 内含 `inkflow/` 顶层目录与解压验收形态一致 | Python zipfile（venv 依赖 + CI/本地解释器差异）；tar.exe/bsdtar（非原生、兼容性需验证） |
| D2 | **打 zip 的 job = package-backend**（R2） | 紧跟 PyInstaller 构建；上传独立 `cli-zip` artifact | 构建与打包同 job 零拷贝；失败在源头暴露；package-electron 保持单一发布点职责 | package-electron 重打（重复下载 142MB + 职责混杂） |
| D3 | **CLI zip 打包失败 = 阻断发布**（R3） | 不设 continue-on-error | Release 资产集合是发布契约（M1/M7），残缺发布与验收 1 冲突 | continue-on-error（静默残缺） |
| D4 | **CLI zip 经 upload-artifact 中转，由 package-electron 统一发布** | cli-zip artifact → 下载 → 复制进 packages/electron/dist → gh release create | package-backend 仅 contents:read（无发布权限）；发布点唯一（gh 需显式 GH_TOKEN，rc.2 坑） | package-backend 直接 gh release（权限不足）；新发布 job（过度设计） |
| D5 | **PATH 勾选默认不勾 + 静默安装跳过** | `Var addCliToPath` 默认 0；勾选页 leave 回调置 1；/S 跳过页面 | Issue #168 明确「默认不勾——GUI 用户不一定需要 CLI」；静默安装无法交互，默认值即正确退化 | 默认勾选（违背 issue 语义，污染 GUI 用户 PATH） |
| D6 | **PATH 条目目标 = `$INSTDIR\resources\kernel`**（不复制第二份内核） | NSIS 勾选写入 GUI 内嵌内核目录；CLI zip 独立解压 | 同一份 PyInstaller 产物两种消费（§5.1），零额外磁盘占用；卸载随 GUI 清理 | 安装器另解压 CLI zip 副本（双份 142MB 内核 + 版本同步面） |
| D7 | **PATH 写 REG_EXPAND_SZ + WM_SETTINGCHANGE 广播** | WriteRegExpandStr + SendMessageTimeout(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment") | PATH 含 %SystemRoot% 等展开变量，REG_SZ 破坏语义；广播让新终端立即生效 | WriteRegStr（破坏展开）；不广播（用户需注销才生效） |
| D8 | **卸载清理 = 精确条目匹配 + 去重 + 超长保护** | 按「完全等于目标条目」删除；1000 字符保护跳过 | 只删自管条目（N3）；绝不截断写回（N4） | 模糊删除（误伤用户手动条目）；无条件写回（长 PATH 截断事故） |
| D9 | **installer.nsh 放 `build/` + electron-builder.yml 显式声明 `nsis.include`** | `frontend/packages/electron/build/installer.nsh`；yml `nsis.include: build/installer.nsh` | buildResourcesDir 默认解析位置（模板实测 getResource 兜底名 installer.nsh）；显式声明自文档化、防解析规则变更 | 放其他目录（需绝对/相对路径解析，脆弱） |
| D10 | **CLI zip 命名版本 = tag 派生；包内版本 = 既有 dist-info 链路** | `github.ref_name`.TrimStart('v')；copy_metadata('inkflow') | 复用 f19 §2.4 版本注入，零新机制；文件名版本与包内版本同源同 tag | zip 内写版本文件（新机制 + 与 dist-info 双源） |
| D11 | **PATH 写入位置跟随安装模式（SHELL_CONTEXT）** | per-user → HKCU\Environment；per-machine → HKLM\...\Environment | 安装器安装模式选择页是一等公民 UI（§4.1 实测），PATH 作用域跟随安装作用域符合用户直觉；默认 per-user 无 UAC；SHELL_CONTEXT 是 electron-builder 自带根符号（**✅ 已确认：用户拍板选项 C，2026-08-08**） | 恒 HKCU（per-machine 安装下 CLI 仅安装者可用）；恒 HKLM（per-user 默认路径写失败） |

> D11 为待澄清 Q2 的建议方案——**✅ 已确认（用户拍板：选项 C，2026-08-08）**，正文 §4 即按此方案撰写（SHELL_CONTEXT 跟随安装模式），本节无需再修订。

---

## 13. 验收标准

| # | 验收项（M 行） | 验证方式 | 载体 |
|---|---------------|----------|------|
| M1 | Release 资产含 `inkflow-cli-<version>.zip`（独立 CLI 产物，与 GUI 三件套同 Release） | `gh release view <tag> --json assets` 或网页下载 | CI（release.yml 实跑） |
| M2 | 全新机器解压 CLI zip → `inkflow --help` 退出码 0 → `inkflow project list --json` 可用 → `inkflow serve` 拉起内核（INKFLOW_READY 行） | 本地近似（§9.2 场景 1）+ 全新机器（VM/沙箱） | 手动 + 脚本 |
| M3 | NSIS 勾选「添加 CLI 到 PATH」生效：勾选安装 → 新终端 `inkflow --help` 可用；`$env:Path` / 注册表含 `$INSTDIR\resources\kernel`（REG_EXPAND_SZ） | §9.4 V1（含中文路径变体） | 手工 |
| M4 | NSIS 卸载清理 PATH：卸载后注册表无残留、新终端 `inkflow` 不存在、PATH 其他条目完好 | §9.4 V5 | 手工 |
| M5 | CLI 产物版本号与 GUI 对齐：zip 文件名版本 = 包内 `inkflow.exe --version` 输出（`InkFlow v<version>` 格式，app.py L21 实测，解析 `v` 后版本号） = INKFLOW_READY.version = GUI 资产版本（= tag） | §9.2 场景 3 | 脚本 + 手动 |
| M6 | 默认不勾：不勾选安装 → PATH 无 InkFlow 条目（含静默安装 /S 分支） | §9.4 V2/V3 | 手工 |
| M7 | release.yml 全绿：tag `v0.5.x` → 3 job 成功 → Release 含 4 资产（GUI 三件套 + CLI zip），无新 job | GitHub Actions 实跑（预发布 tag `v0.5.0-rc.N` 迭代，#145 先例路径；release.yml 无 workflow_dispatch 触发） | CI |
| M8 | 既有测试全绿 + 零代码改动声明成立：backend/frontend CI 全绿；git diff 无 `backend/src`、`frontend/src`、ci.yml 变更 | ci.yml PR 全绿 + diff 审查 | CI + 审查 |

> 完成标准映射：M1 = Issue 验收 1；M2 = Issue 验收 2；M3/M4/M6 = Issue 验收 3；M5 = Issue 验收 4；M7/M8 = 发布流水线与质量门禁（f19-packaging M9/M10 同款）。

---

## 待澄清问题（已拍板，留痕）

1. **Q1 CLI zip 是否含 README 使用说明**（纯 CLI 用户首次接触的引导问题）
   - **背景**：CLI zip 面向纯 CLI 用户（可能从未见过 GUI），解压后面对 `inkflow/` 目录无任何说明；仓库文档（`docs/`）不随 zip 分发
   - **A 不含（最小产物）**：zip 只含内核（inkflow.exe + _internal），使用说明放 Release Notes 与 `backend/pyinstaller/README.md`
   - **B 含简短 README.md**：zip 根放 `README.md`（5-10 行：`inkflow --help` / serve / PATH 添加指引 + 版本 + 项目链接），打包 step 复制仓库文件
   - **对比**：A = 产物最简、零构建链改动、但解压即用体验差（用户需另找文档）；B = 单文件复制成本极低（CI 一个 Copy-Item step）、显著改善首次使用体验、README 内容需随版本维护
   - **建议：B**——成本（一个 Copy-Item step + 一个静态文件）与收益（纯 CLI 用户解压即得引导）比值最优；README 内容精简为命令速查，不重复仓库 docs
   - **✅ 已确认（用户拍板：选项 A，2026-08-08，推翻原建议）**——zip 从 GitHub 下载，用户自然查看项目 README；CLI `--help` 自带完整命令帮助；说明放 Release Notes 与项目 README（§10 已修订）

2. **Q2 NSIS PATH 写入位置（用户级 vs 系统级）**
   - **背景**：assisted 安装器（oneClick:false）默认 per-user 安装（无 UAC 提权），但显示安装模式选择页允许用户选 per-machine（提权安装）——PATH 写入的注册表根需要与安装模式匹配，否则权限失败或作用域不一致
   - **A 恒 HKCU 用户级**：`HKCU\Environment\Path`，无权限问题，卸载逻辑单一；per-machine 安装下 CLI 仅对安装者用户可用（作用域不一致）
   - **B 恒 HKLM 系统级**：`HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment\Path`；**per-user 默认路径下写入失败**（无提权）——需额外提权逻辑，与默认安装模式冲突
   - **C 跟随安装模式**（建议）：用 electron-builder 自带 `SHELL_CONTEXT` 根符号（其自带模板同款用法，§4.1 实测）——per-user → HKCU、per-machine → HKLM，卸载同源清理
   - **对比**：A = 实现最简单、单一测试路径、per-machine 场景语义不完整；B = 仅适合全机部署、默认模式不可行（否决）；C = 与安装模式选择 UI 天然一致、实现成本与 A 几乎相同（符号级差异）、测试面为两种模式各一次手工验证
   - **建议：C**——electron-builder 的 `SHELL_CONTEXT` 机制就是为此设计的（自带模板 `registryAddInstallInfo` 同款用法），per-user 默认路径零 UAC、per-machine 提权后写 HKLM 自然可行；恒 HKCU（A）在 per-machine 安装下产生「全机装了但 CLI 只对我可用」的不一致，属认知偏差偏好（实现简单 ≠ 语义正确）
   - **✅ 已确认（用户拍板：选项 C，2026-08-08，与建议一致）**——正文 §4 已按 C 撰写（SHELL_CONTEXT 跟随安装模式），无需再修订

3. **Q3 是否同时发布 CLI 独立安装器（NSIS CLI-only）**
   - **背景**：Issue #168 原文 = 仅 GUI 安装器加 PATH 勾选；但 CLI zip 用户若想「安装即 PATH 可用」，目前需手动加 PATH（或解压到已在 PATH 的目录）
   - **A 仅 GUI 安装器勾选（issue 原文）**：CLI zip 独立解压 + 手动加 PATH（README/Release Notes 给命令）；无第二套安装器维护面
   - **B 另发 NSIS CLI-only 安装器**：第二个 electron-builder nsis target（仅打包 kernel 目录 + PATH 写入），用户安装 CLI 即 PATH 可用
   - **对比**：A = 零额外构建/维护成本、CLI zip 已覆盖「解压即用」、手动加 PATH 是一次性操作（`setx PATH` 一行）；B = 安装体验最好（双击即用）但需要：新 electron-builder 配置/产物（体积 ≈ 内核压缩后 60-90MB 的第二个安装器）、PATH 逻辑双份维护（GUI installer.nsh + CLI 安装器）、发布资产再 +1、以及 CLI-only 安装器与 GUI 安装器 PATH 条目的共存/冲突管理（Q2 决策波及面翻倍）
   - **建议：A**——YAGNI：CLI zip + 文档已满足「解压即用」验收（M2）；CLI-only 安装器是 1.0.0「契约冻结」阶段需求驱动再评估的增强项，0.5.0 引入第二套 NSIS 配置的维护成本 > 收益
   - **✅ 已确认（用户拍板：选项 A，2026-08-08，与建议一致）**——CLI 用户 = 技术型/agent 用户（GitHub 下载 zip + 手动 PATH），CLI-only 安装器留 1.0.0「契约冻结」阶段需求驱动再评估（§10 已修订）

---

> **Spec 变更记录**：v1.0（2026-08-08）初稿——打包/发布基建增量专项型 spec，镜像 f19-packaging 13 节映射（§5.5）；Q1-Q3 待拍板，正文 §4/§12 已含建议方案（D11 = Q2 建议 C），拍板后同步修订并留痕。v1.1（2026-08-08）——Q1=A / Q2=C / Q3=A 已确认（头部 Spec 变更行 + §1.4/§7/§10/§12 + 待澄清区同步留痕）。
