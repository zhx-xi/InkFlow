# F19: 打包分发（packaging）— 功能规格

> **Spec 版本**: 1.1（评审修订 2026-08-06：🔴1 版本链 /health、🔴2 copy_metadata、🔴3 async 装配、🔴4 hiddenimports 纪律、🔴5 数据目录 Q7=B 已拍板；🟡6-11 同步修复） | **日期**: 2026-08-06 | **依据**: PRD v2.1 P1-10, Constitution P1-P6, ADR-013/019(v2)/020/021/025
> **所属阶段**: 0.4.0 里程碑（Issue #48，估算 4-6 人天；体积评审后追加 T0 瘦身与 B+ 装配，见 §3/§5）
> **关联 Issues**: [#48](https://github.com/zhx-xi/InkFlow/issues/48)（本任务）· [#70](https://github.com/zhx-xi/InkFlow/issues/70)（F19-skills，并行无关）· [#137](https://github.com/zhx-xi/InkFlow/issues/137)（Tauri 2 体积优化专项，2.0.0，本 spec §10 不在范围）
> **依赖**: #69 ✅（F19-GUI 已合入——内核进程化 #77 PR #85 / Electron 壳 #78 PR #95 / 渲染层 #79 PR #97 及其后子任务 #105/#106/#107）；#50 ✅（F23 SSE，PR #83）；#70 ⏳（skills 包，并行 worktree 无代码依赖）
> **参考 ADR**: [ADR-013](../../adr/ADR-013.md)（RAG 首次落地）· [ADR-019](../../adr/ADR-019.md)（版本里程碑 v2：0.4.0 = skills 包 + 打包）· [ADR-020](../../adr/ADR-020.md)（Electron 选型 + electron-builder 打包）· [ADR-021](../../adr/ADR-021.md)（内核进程化：resources/kernel/inkflow.exe 生命周期）· [ADR-025](../../adr/ADR-025.md)（依赖锁定 uv.lock/pnpm-lock）
> **状态**: 待实现 🔲

---

## 1. 概述

### 1.1 本章定位

**打包分发专项（非业务模块变体）**：不新建业务实体、不新增业务 API 端点，为 0.3.0 已交付的 GUI 产品（Electron 壳 + React 渲染层 + 本地内核进程化）建立 **Windows 三产物分发链**：

| 产物 | 工具 | 形态 | 用户路径 |
|------|------|------|----------|
| 内核 exe | PyInstaller onedir | `resources/kernel/inkflow.exe` + `_internal/` | 随安装包分发，壳主进程拉起 |
| 安装包 | electron-builder NSIS | `InkFlow-Setup-<ver>.exe` | 正式分发（可选安装目录） |
| 便携 ZIP | zip 目录打包 | `InkFlow-<ver>-portable.zip` | 解压即用文件夹 |

**ADR-019 v2 验收口径**：「Windows 三种打包可用」。本 spec 交付 = 打包脚本 + 分发配置 + 发布流水线（release.yml）+ 验证门禁，**不含** GUI 功能改动（除 §5 B+ 装配改造）。

### 1.2 关键事实（现状盘点，2026-08-06 实测）

- ✅ `frontend/packages/electron/src/kernel.ts` `resolveKernelCommand` 三分支**已含打包路径**：`isPackaged=true → resources/kernel/inkflow.exe serve --port 0`（#78 交付）——**壳侧零代码改动**，只需把 PyInstaller 产物放进 `resources/kernel/`
- ✅ 内核入口 `backend/src/inkflow/__main__.py` → `inkflow.cli.app:app`；`pyproject.toml [project.scripts] inkflow` 已配置
- ✅ `serve.py` 强化版（#77）已交付：`INKFLOW_READY {port, token, pid, version}` stdout 行 + `--port-file` + 随机 token；WAL 实现在 `core/database.py`（连接工厂，评审 ⚪13 归属修正）
- ✅ renderer 可构建 `dist/`（e2e-frontend job 已在 CI 构建）；图标资产已有（`frontend/packages/electron/favicon.ico` / `inkflow-icon-256.png`）
- ❌ `frontend/packages/electron/package.json` **无 electron-builder 依赖**（version 0.3.0）
- ❌ `electron-builder.yml` 为占位（`extraResources` 注释中；win.target 已含 nsis + zip 目标，评审 ⚪12 修正——非「只有 nsis 注释」）
- ❌ 无 PyInstaller 配置/脚本；pyproject **无 pyinstaller 依赖**
- ❌ 无 release.yml（CI 只有 ci.yml + conventional-commits.yml）
- ❌ 版本号不一致：backend `__init__.py`/`pyproject.toml` = 0.1.0，electron package.json = 0.3.0，renderer = 0.3.0 —— **本任务统一到 0.4.0（§2.4 版本注入）**
- ⚠️ 依赖体积（backend/.venv 实测 2026-08-06，site-packages 总计 **1,107 MB**）：torch 441 / scipy+libs 102 / litellm 64.7（**源码 0 引用，ADR-005v2 残留**）/ transformers 44.6 / onnxruntime 38.6 / kubernetes 37.8 / sklearn 25.8 / sympy 25.4 / tokenizers 7.3 / hf_xet 9 —— **T0 瘦身清单见 §3**

### 1.3 边界声明

- **不含** Tauri 2 换壳（#137，2.0.0 专项——ADR-020 预留平滑迁移路径）
- **不含** 代码签名（杀软误报缓解属 1.0.0 发布事项，§10）
- **不含** 自动更新（electron-updater 未引入，§10）
- **不含** macOS/Linux 打包（0.4.0 验收 = Windows 三种打包；跨平台属 1.0.0，ADR-020）
- **不含** skills 包分发（#70 独立 issue，ADR-022）
- **不含** 新增业务 API/实体/CLI 命令（`inkflow serve` 已满足分发需要；B+ 装配改造只改 embedding 装配方式，接口零变更）

---

## 2. 产物契约

### 2.1 打包目录结构（便携 ZIP 解压后 / NSIS 安装后）

```
InkFlow/                          ← 便携 ZIP 解压后（或 NSIS 安装目录）
├── InkFlow.exe                   # Electron 壳（主进程，管内核生命周期）
├── resources/
│   ├── app.asar                  # renderer + 主进程代码（electron-builder 默认）
│   └── kernel/
│       ├── inkflow.exe           # PyInstaller 内核（serve 强化版，onedir 入口）
│       └── _internal/            # onedir 依赖（Python 运行时 + 第三方库）
└── (用户数据首次运行时 %APPDATA%/InkFlow 创建：SQLite DB + chroma 向量库 + keys/)
```

- 壳主进程定位内核：`app.isPackaged ? path.join(process.resourcesPath, 'kernel', 'inkflow.exe') : <dev 路径>`（`kernel.ts` 已实现，`resources/kernel/inkflow.exe` 相对路径经 electron-builder `extraResources` 映射）
- **数据目录不进包**：SQLite（`data/inkflow.db`）、chroma 向量库（`data/chroma/`）、key 文件（`data/keys/`）均为运行时生成（ADR-021 §影响）

### 2.1.1 ⚠️ 数据目录落点（评审 🔴5，已拍板：方案 B）

**实测现状**：`core/config.py:22,30,101` 的 `database_url = ./inkflow.db`、`data_dir = ./data`、`vector_store_dir = ./data/chroma` **全部为 CWD 相对路径**；壳 spawn 内核时**不传 cwd/env**（main.ts:264-267，dev 模式 .db 直接落在 electron 包目录可证）。打包后数据将落在**安装/解压目录**——NSIS 自选目录装到 Program Files 会**写失败**（M4 全新机器验收受影响）。

**✅ 已拍板（用户 2026-08-06：方案 B）**：`config.py` 加 **`sys.frozen` 检测**（PyInstaller 打包标志）→ 打包模式下默认数据目录 = `%APPDATA%/InkFlow`（`platformdirs` 或 `os.environ['APPDATA']` 解析，实现以 TDD 为准）：

```python
# core/config.py 变更示意（实现以 TDD 为准）
def _default_data_dir() -> Path:
    if getattr(sys, "frozen", False):          # PyInstaller 打包模式
        base = Path(os.environ.get("APPDATA", Path.home()))
        return base / "InkFlow"
    return Path("./data")                       # dev 模式不变

class Settings(...):
    data_dir: Path = Field(default_factory=_default_data_dir)
    database_url: str = ...                     # 基于 data_dir 派生（或同源工厂）
    vector_store_dir: Path = ...                # data_dir / "chroma"
```

**决策要点**：
- **壳零改动声明成立**（§8.3 维持）：数据目录逻辑归内核配置层，壳保持薄（ADR-020「壳层无业务逻辑」精神）
- dev 模式（`sys.frozen=False`）行为完全不变——既有测试零破坏
- 用户可经 env（`INKFLOW_DATA_DIR` 等 pydantic-settings 既有 env 机制）覆盖，无需新增 CLI 参数
- 测试注入点：mock `sys.frozen`（`pytest` monkeypatch）断言打包/开发双路径（§9 补用例）
- 便携 ZIP 同样受益：解压到任意目录（含只读/无写权限位置）数据都进 %APPDATA%

### 2.2 三产物定义

| # | 产物 | 生成命令 | 验收形态 |
|---|------|----------|----------|
| P1 | 内核 exe | `uv run pyinstaller backend/pyinstaller/inkflow.spec` | `resources/kernel/inkflow.exe` 可独立执行 `inkflow --help`、`inkflow serve --port 0` 输出 INKFLOW_READY |
| P2 | NSIS 安装包 | `pnpm --filter inkflow-electron dist:win` | `dist/InkFlow-Setup-<ver>.exe`，可选安装目录 |
| P3 | 便携 ZIP | electron-builder zip target + 目录组装 | `dist/InkFlow-<ver>-portable.zip`，**解压即用文件夹**（非 portable 单 exe 自解压） |

> **P3 形态确认（用户拍板 2026-08-06：选项 A）**：electron-builder 的 `portable` target 产出自解压单 exe，**不是**「解压即用的 zip 文件夹」；本任务用 `zip` target + 手动组装目录（electron-packaging 技能 2026-08-02 已拍板产物形态，本次复确认）。

### 2.3 体积预算（T0 瘦身后，目标值；评审 🟡7 重算）

| 层 | 现状 | 目标 | 依据 |
|----|------|------|------|
| Python 内核 onedir | ~1.1 GB（site-packages 全量） | **~250-350 MB** | §3 T0 移除 ~796MB → site-packages 保留 ~311MB（含 Python 运行时与标准库；chromadb 族 ~110MB 为大头） |
| Electron 壳（解压） | ~250 MB（Chromium 硬成本） | 不变 | 结构性成本，Tauri #137 才可降 |
| **NSIS 安装包下载体积** | — | **~200-250 MB** | NSIS LZMA 压缩（Chromium 压缩率高）+ T1 `compression: maximum` |
| 便携 ZIP | — | ~250-350 MB | ZIP deflate 压缩，略大于 NSIS（无安装器压缩） |

> **⚠️ 体积是「实测记录 + 预算偏差说明」口径（评审 🟡7 修正）**：M6 不设硬性 ≤ 阈值，以首包实测记录为准、与预算偏差超 30% 时说明原因（hiddenimports 误收集/排除项失效是主要风险，§4.4 S5 断言兜底）。

### 2.4 版本注入契约（修存量债）

**现状问题（实测）**：三处版本不一致——backend `__init__.py:3` `__version__ = "0.1.0"`、`pyproject.toml:3` `version = "0.1.0"`、electron/renderer package.json `0.3.0`。**且 `api/app.py:129` /health 硬编码 `"version": "0.1.0"`**（renderer 关于页实际读 /health，`settings.tsx:474-481`）——打包后关于页永远显示 0.1.0，M5 必失败（评审 🔴1 修复）。

**决策**：0.4.0 发布以 **tag `v0.4.0` 为单一事实来源**，构建期注入：

| 消费方 | 来源 | 机制 |
|--------|------|------|
| PyInstaller 内核 | pyproject.toml `version` | release.yml 构建前 `version = "0.4.0"` 写入（tag 派生）；`__version__` 从 `importlib.metadata` 读（**不硬编码**） |
| electron-builder | package.json `version` | release.yml 构建前写入 tag 版本 |
| renderer 关于页 | **内核 /health（版本源）** | settings.tsx 已读 /health；`app.py` /health 改用 `inkflow.__version__`（**MODIFY，评审 🔴1**）——不存在 preload getVersion 通道（实测 `preload.ts:48-67` 只暴露 INKFLOW_API + windowControls） |
| INKFLOW_READY.version | 内核 `__version__` | 经 `importlib.metadata.version("inkflow")` |

**⚠️ 冻结环境元数据（评审 🔴2 修复）**：`importlib.metadata.version("inkflow")` 依赖 dist-info——PyInstaller **不自动收集** .dist-info，`inkflow.spec` 必须显式 `copy_metadata('inkflow')`（§4.2），否则冻结 exe 中 `from inkflow import __version__` 抛 PackageNotFoundError → INKFLOW_READY 交付失败 → P1 冒烟阻塞。

**提交态版本策略（评审 🟡6 修复）**：pyproject/package.json/electron+renderer 提交态统一 **0.4.0**（存量债一次清）；ci.yml build job（L775）的 dev 版本注入从硬编码 `-replace 'version = "0.1.0"'` 改为**读当前版本号追加 dev 后缀**（正则 `version = "([^"]+)"` → `$1.dev0+g<sha>`）——否则 pyproject 提交为 0.4.0 后该 replace 静默失效，PR wheel 失去 dev 版本号。

**验证**：安装包属性版本 = renderer 关于页（/health）= INKFLOW_READY.version = `0.4.0`。

---

## 3. 依赖瘦身（T0，用户拍板 2026-08-06：B+ 方案）

### 3.1 决策记录

**问题**：PyInstaller 打包会把 site-packages 全量收集（含 dev 组外的运行时依赖）。实测 1,107 MB 中 ~800MB 可移除，其中大头是本地 embedding（torch 族 634MB）与残留（litellm 65MB）。

**用户拍板（2026-08-06）**：**B+ = chromadb 进包 + API embedding**（torch/sentence-transformers 出包）。与 2026-08-02 技能里原 A/B/C 三案的关键差异：**embedding 从「本地推理」改「调用大模型 embedding API」**，彻底消除 torch 依赖，同时保留 RAG 检索功能（chromadb 进包，装完即用）。

| 方案 | 内容 | 体积 | RAG 可用性 | 结论 |
|------|------|------|------------|------|
| A 全量内置 | torch 全家桶 + 本地 BGE | 1.5-2 GB | ✅ 离线 | ❌ 体积大且 PyInstaller 收集 torch 风险高 |
| B 排除 RAG | chromadb 也不进包，报「未安装」 | ~400-500 MB | ❌ 不可用 | ❌ 「按需装」在 PyInstaller 冻结环境不可行（无 pip/ABI 匹配/依赖树，详见 §3.2） |
| **B+（选定）** | **chromadb 进包 + API embedding** | **~500-650 MB 解压（下载 ~200-250 MB）** | ✅ 装完即用 | ✅ 体积/功能帕累托最优 |

### 3.2 「打包后下载 chromadb」不可行性论证（用户提问 2026-08-06，实测结论）

| 约束 | 说明 |
|------|------|
| 冻结环境 | PyInstaller 产物内含 Python 运行时（python312.dll + `_internal/`），用户机器无 pip/site-packages 概念——「下载 chromadb」没有安装目标 |
| 二进制 ABI | chromadb 非纯 Python：`chromadb_rust_bindings.pyd`（60.5 MB，Rust HNSW 引擎）+ `onnxruntime`（38.6 MB，C 扩展）+ `tokenizers`（7.3 MB）必须与打包时 Python ABI（3.11/win-amd64）精确匹配；动态下载的 wheel 无法保证 |
| 依赖树 | chromadb 依赖 pydantic/kubernetes/opentelemetry 等数十包，按需安装 = 重新实现 pip 解析器 |
| 产品承诺 | DoD「全新机器（无 Python/Node）安装即用」被破坏 |

**推论**：RAG 可用性只有两个真实选项——chromadb 进包（B+）或 RAG 整体不可用（B）。B+ 的 chromadb 相关进包成本 ≈ 2.6 + 60.5 + 7.3 ≈ **~70-110 MB**（onnxruntime/kubernetes 排除见 §3.3），换来功能完整可用。

### 3.3 移除/保留清单（site-packages 实测，2026-08-06）

**🔴 移除（打包排除 + pyproject 依赖调整）**：

| 包 | 体积 | 理由 | pyproject 动作 |
|----|------|------|----------------|
| torch | 441 MB | API embedding 后无用 | 随 sentence-transformers 移除（间接） |
| scipy + scipy.libs | 102 MB | torch/sklearn 依赖 | 间接移除 |
| litellm | 64.7 MB | **ADR-005v2 后源码 0 引用，纯残留** | **显式删除依赖行** |
| transformers | 44.6 MB | sentence-transformers 依赖 | 间接移除 |
| onnxruntime | 38.6 MB | chromadb 默认 embedding 函数（API embedding 不用） | PyInstaller `--exclude-module`（spike 验证 chromadb import 链无硬依赖） |
| kubernetes | 37.8 MB | chromadb 云客户端（本地单机不用） | PyInstaller `--exclude-module`（spike 验证） |
| sklearn | 25.8 MB | sentence-transformers 依赖 | 间接移除 |
| sympy | 25.4 MB | torch 依赖 | 间接移除 |
| hf_xet | 9 MB | HF hub 下载（本地 embedding 用） | 间接移除 |
| tokenizers | 7.3 MB | transformers 依赖 | 间接移除（chromadb 声明依赖但 API embedding 路径不用——spike 验证） |

**✅ 保留（进包）**：

| 包 | 体积 | 理由 |
|----|------|------|
| chromadb + chromadb_rust_bindings | ~63 MB | RAG 检索核心（B+ 决策） |
| numpy + numpy.libs | ~40 MB | chromadb 依赖 |
| jieba | 36.5 MB | 中文分词（F9/F11/F12/F13/F16 写作功能） |
| FastAPI/uvicorn/SQLAlchemy/langchain 族/httpx/pydantic 等 | ~150 MB | 内核本体 |
| cryptography | 9.9 MB | APIKeyManager AES-GCM |

**预期结果**：内核 onedir ~250-350 MB（§2.3 目标，评审 🟡7 重算）。

### 3.4 pyproject 依赖调整细节

```toml
# [project.dependencies] 变更
- "litellm>=1.50",                    # 删除（ADR-005v2 残留，0 引用）
- "sentence-transformers>=3.0",       # 删除（本地 embedding 弃用）
# chromadb 保留为硬依赖（RAG 进包）
"chromadb>=1.0.0,<2.0.0",             # 保留

# [project.optional-dependencies] 新增
packaging = [
    "pyinstaller>=6.0",               # 打包工具（不进运行时）
]
```

- `uv sync --frozen` 后 `uv.lock` 同步（ADR-025 锁定口径）
- **⚠️ 删除 sentence-transformers 后必须全仓验证无 import**：`deps.py` 的 `HuggingFaceBgeEmbeddings` 是唯一引用点（§5 装配改造替换）；测试用 FakeEmbeddings 不依赖 ST

### 3.5 T1 压缩（用户确认 2026-08-06）

- electron-builder.yml `compression: maximum`
- PyInstaller UPX 可选（spike 评估杀软误报风险，见 §10 风险）
- 目标：NSIS 下载体积 ~200-250 MB（§2.3，评审 🟡7 重算）

---

## 4. PyInstaller 内核打包

### 4.1 交付物与位置

| 项 | 值 |
|----|----|
| spec 文件 | `backend/pyinstaller/inkflow.spec`（新建，PyInstaller 官方 spec 格式） |
| 入口 | `backend/src/inkflow/__main__.py`（`python -m inkflow` 语义，CLI app） |
| 模式 | **onedir**（非 onefile）：启动快（不现场解压）、hidden-import 报错好排查、体积差异可接受（electron-packaging 技能 2026-08-02 拍板） |
| 产物名 | `dist/inkflow/inkflow.exe` + `dist/inkflow/_internal/` |
| 放置 | electron-builder `extraResources` 把 `dist/inkflow/` 整体拷入 `resources/kernel/` |

### 4.2 spec 关键配置

```python
# backend/pyinstaller/inkflow.spec（示意，实现以 TDD 为准）
from PyInstaller.utils.hooks import collect_all, copy_metadata

# ⚠️ dist-info 元数据（评审 🔴2）：importlib.metadata.version 依赖；
#    PyInstaller 不自动收集 .dist-info，缺则冻结 exe PackageNotFoundError
datas, binaries, hiddenimports = collect_all('inkflow')
datas += copy_metadata('inkflow')

a = Analysis(
    ['src/inkflow/__main__.py'],
    pathex=['src'],
    # 动态导入显式清单（uvicorn 各层 + langchain 全家桶）
    hiddenimports=hiddenimports + [
        'uvicorn.logging', 'uvicorn.loops.auto',
        'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan.on',
        # ⚠️ 不收集 langchain_community.embeddings（评审 🔴4）：
        #    B+ 后源码 0 引用；且其懒加载/TYPE_CHECKING import 会拖回 torch 族，与 T0 冲突
        # chromadb 子模块（RAG 进包，首次打包冒烟后逐项补）
    ],
    # T0 排除（§3.3 spike 验证后确认清单；torch 族兜底，评审 🔴4）
    excludes=['onnxruntime', 'kubernetes', 'tokenizers', 'litellm',
              'torch', 'transformers', 'sentence_transformers'],
    datas=datas,      # collect_all + copy_metadata（LLM 模板 yaml 由 collect_all 携带）
    binaries=binaries,
    ...
)
```

**要点**：
- `collect_all('inkflow')`——带上包内数据文件（LLM 模板 yaml 等）与子模块，替代手写 datas 的多数条目；**必须配 `copy_metadata('inkflow')`**（评审 🔴2）
- **必须 hidden-imports**：uvicorn 动态导入（loop/protocol/http 各层）——**首次打包后跑冒烟逐项补**（`inkflow.exe --help` → `serve` → 写作调用）
- **hiddenimports 纪律（评审 🔴4）**：只列**运行时实际 import** 的模块；**不收集** `langchain_community.embeddings`（B+ 后 0 引用，且其 PEP 562 懒加载 + `TYPE_CHECKING` import 会被 PyInstaller 静态分析跟进 → 拖回 torch/transformers/sentence-transformers 全家，T0 全废）
- **excludes 兜底**：除 chromadb 云组件外，显式排除 `torch`/`transformers`/`sentence_transformers`——即使静态分析误跟，也强制不进包
- **RAG 收集**：chromadb 保留时注意 `chromadb_rust_bindings` 二进制（PyInstaller 默认收集 .pyd；spike 验证 `--collect-all chromadb` 是否完整）

### 4.3 冒烟验证（本地，打包后必跑）

```powershell
# P1 冒烟：help + serve 交付契约
dist\inkflow\inkflow.exe --help
dist\inkflow\inkflow.exe serve --port 0 --port-file smoke.json   # 期望输出 INKFLOW_READY 行
# 写作链路冒烟（Fake key 配置下 API 层可达性，§9）
```

**门禁**：三产物验收（§13 M 行）依赖 P1 冒烟通过——**exe 起不来则后续全部阻塞**，所以 P1 冒烟在 worktree 内先行。

### 4.4 排除项 spike 验证计划（M7，T0 前置）

**目标**：确认 `excludes=['onnxruntime', 'kubernetes', 'tokenizers']` 后 chromadb 仍可 import + 检索正常（API embedding 路径不使用这些组件）。

| 步骤 | 动作 | 通过标准 |
|------|------|----------|
| S1 | 在打包 venv 中 `pip uninstall onnxruntime kubernetes tokenizers`（临时隔离验证） | 卸载成功 |
| S2 | `python -c "import chromadb; c=chromadb.PersistentClient(path='tmp'); col=c.get_or_create_collection('t'); col.add(ids=['1'], embeddings=[[0.1]*8]); print(col.query(query_embeddings=[[0.1]*8], n_results=1))"` | 无 ImportError，检索返回 1 条 |
| S3 | `python -c "import chromadb; from chromadb.utils.embedding_functions import DefaultEmbeddingFunction; DefaultEmbeddingFunction()"` | **预期 ImportError（onnxruntime 缺失）——可接受**：DefaultEmbeddingFunction 只在未显式传入 embedding 时用，InkFlow 永远显式注入（§5） |
| S4 | 全仓 grep chromadb 调用路径确认无 DefaultEmbeddingFunction 隐式使用 | 0 命中 |
| S5 | PyInstaller 打包后重复 S2（在 `_internal/` 隔离环境） | 打包产物中 chromadb 检索正常 |

**结论记录**：spike 通过 → 排除清单定稿（§4.2）；S3 预期失败属**良性**（该函数路径在 InkFlow 中不可达，B+ 装配保证显式注入）——若 S3 意外成功或 S4 命中，回退排除项并更新 §3.3 体积预算。

**✅ spike 实测结论（2026-08-06，已闭环）**：
- S2 ✅ chromadb 写入+检索正常（显式 embeddings 数组路径）
- S3 ✅ DefaultEmbeddingFunction 可构造（当前 venv 有 onnxruntime），但 **InkFlow 源码 0 命中**（S4）——排除后该路径不可达
- **关键证据**：`import chromadb` 后顶层模块加载检查——**onnxruntime / kubernetes / tokenizers 均未加载**（excludes 安全）；**grpc 被加载**（opentelemetry exporter 依赖，~11.9MB）——**保留 grpc**（排除可能破坏 opentelemetry 初始化，风险 > 收益）
- **排除清单定稿**：`excludes=['onnxruntime', 'kubernetes', 'tokenizers', 'litellm', 'torch', 'transformers', 'sentence_transformers']`（litellm/torch 族为 T0 兜底）

---

## 5. B+ 装配改造：API embedding（用户拍板 2026-08-06：P1=A 并入本任务）

### 5.1 背景与现状

**问题**（#106 交付后实测）：`ProviderConfig` 领域模型已支持 embedding 类型模型注册（`type: chat / embedding` 二值，spec §8），但 RAG 装配 `api/deps.py:342-357` 仍硬编码本地 BGE：

```python
from langchain_community.embeddings import HuggingFaceBgeEmbeddings
_vector_store = LangChainVectorStore(
    persist_dir=config.vector_store_dir,
    embeddings=HuggingFaceBgeEmbeddings(   # ← 本地模型 → 拖进 torch/ST（T0 要移除）
        model_name=config.embedding_model,
        device=config.embedding_device,
    ),
)
```

**注册了 ≠ 用上了**——装配层未消费 ProviderConfig 的 embedding 模型。B+ 要求 embedding 走 API，此改造是**前置条件**（不改造则打包时已无本地 embedding，RAG 装配直接失败）。

### 5.2 决策

`deps.py` 装配从 ProviderConfig 读取 **embedding 类型模型**（base_url + api_key + model id），构造 `OpenAIEmbeddings`（langchain-openai 已是硬依赖，零新增依赖），替换 `HuggingFaceBgeEmbeddings`：

```python
# 装配示意（实现以 TDD 为准；评审 ⚪16：get_embedding_model 为示意命名，
# 真实契约见 §5.4——遍历 repo.list() 取首个 type="embedding" 模型）
embedding_cfg = await _resolve_embedding_config()   # §5.4 真实规则（async）
if embedding_cfg is None:
    raise RAGUnavailableError("未配置 embedding 模型（设置 → 模型管理 → embedding 类型）")
embeddings = OpenAIEmbeddings(
    model=embedding_cfg[1].id,                      # (provider, model)
    api_key=key_manager.load(embedding_cfg[0].name),  # APIKeyManager.load（评审 🟡8）
    base_url=embedding_cfg[0].base_url,             # OpenAI 兼容端点
)
_vector_store = LangChainVectorStore(persist_dir=config.vector_store_dir, embeddings=embeddings)
```

**接口零变更**：`VectorStoreProtocol` / `LangChainVectorStore` 构造签名不变（仍是 `embeddings: Embeddings` 注入）；`RAGUnavailableError` 语义复用（spec §3.4 500「RAG 向量库不可用」前缀）。

**⚠️ 装配链同步/异步边界（评审 🔴3 修复，必须）**：当前 `get_vector_store()` 是**同步**函数（deps.py:332），被同步的 `get_extraction_service(db)`（deps.py:283）调用；而 §5.4 的数据源 `SQLiteProviderConfigRepository` 是 **async**（AsyncSession），`repo.list()` 必须在 async 上下文调用。请求上下文中 event loop 已运行，`asyncio.run` 不可用——**同步签名 + async 数据源不可兼得**。

**决策**：装配链改为 **async**：

```python
# api/deps.py 变更示意（实现以 TDD 为准）
async def get_extraction_service(db: AsyncSession = Depends(get_db)) -> ExtractionService:
    ...
    vector_store = await get_vector_store()      # async（原同步函数改造）
    ...

async def get_vector_store() -> LangChainVectorStore:
    global _vector_store
    if _vector_store is None:
        provider, model = await _resolve_embedding_config()   # async repo.list()
        ...
    return _vector_store
```

- `get_vector_store` / `get_extraction_service` 均改 `async def`（FastAPI `Depends` 原生支持 async，routers 调用点**签名不变**，仅依赖注入自动适配——`await` 在 FastAPI 内部处理）
- 波及面：`api/deps.py` 两个函数 + `api/routers/extractions.py`（若有直接调用 `get_vector_store` 处同步适配）——**写进 §8.2 MODIFY 清单**
- **⚠️ 若 `get_vector_store` 还被非 FastAPI 同步上下文调用**（CLI 路径/测试直接调用），spike 阶段确认后二选一：a) CLI 侧改用独立 async 入口；b) 提供同步 fallback（embedding 配置已缓存时）。**默认 a**（CLI 提取走 service 层 async 方法，不直接调 deps）
- E1-E4 测试形态：`pytest.mark.anyio`（项目已有 asyncio 测试先例，tests/api/ 同款），直接 `await` 装配函数断言

### 5.3 关键契约（RED 测试清单）

| # | 契约 | 测试载体 |
|---|------|----------|
| E1 | 未配置 embedding 模型 → `RAGUnavailableError`（500 RAG 前缀） | unit `tests/unit/test_deps_embedding.py` |
| E2 | 配置 embedding 模型 → 构造 `OpenAIEmbeddings`（mock ProviderConfig 装配，断言 model/base_url/api_key 透传） | 同上 |
| E3 | 已配置 → `get_vector_store()` 正常返回 store（懒加载单例不变） | 同上 |
| E4 | 非 embedding 类型模型（chat）不被消费 → 仍报 E1 | 同上 |
| E5 | `HuggingFaceBgeEmbeddings` 引用全仓移除（**代码 + 文档**：deps.py 装配、`domain/ports/vector_store.py:85` docstring 示例——评审 🟡11 核实，该 docstring 是第二处命中） | lint/guardrail |

**⚠️ 测试无网络约束**：OpenAIEmbeddings 不真正调用（装配层只构造对象）；RAG 检索测试继续用 `FakeEmbeddings`（inkflow-spec-authoring 技能「测试无网络约束」先例）；BGE 模型下载（~100MB）从测试路径彻底消失。

### 5.4 配置来源细节（源码核实 2026-08-06）

**数据源（已核实的真实结构）**：

| 项 | 实现 | 说明 |
|----|------|------|
| Provider 实体 | `domain/models/provider_config.py` `ProviderConfig` | `models: list[ProviderModel]`；`ProviderModel.type: Literal["chat", "embedding"]`（二值）；`base_url: str \| None`（None = SDK 默认） |
| 仓储 | `infrastructure/database/repositories/provider_config_repo.py` `SQLiteProviderConfigRepository` | `get(id)` 按主键；`list()` 返回全部（含内置 4 provider：openai/deepseek/zhipu/ollama，seed 幂等） |
| key 读取 | `infrastructure/llm/key_manager.py` `APIKeyManager` | AES-256-GCM，`data_dir/keys/{provider}.json`；**`load(provider)`**（key_manager.py:81，评审 🟡8 修正——非 get）不存在抛 FileNotFoundError |
| 协议 | `domain/ports/provider_config_repository.py` `ProviderConfigRepositoryProtocol` | 装配层依赖 Protocol（ADR-002 六边形），不直接依赖 SQLite 仓储 |

**选型规则（实现契约）**：遍历 `list()` 结果，取**首个** `models` 中含 `type="embedding"` 条目的 provider：

```python
# 装配示意（实现以 TDD 为准）
async def _resolve_embedding_config() -> tuple[ProviderConfig, ProviderModel]:
    for provider in await repo.list():          # Protocol 注入
        for model in provider.models:
            if model.type == "embedding":
                return provider, model
    raise RAGUnavailableError("未配置 embedding 模型")
```

- **首个匹配**（非「默认标记」）——YAGNI：单 embedding 模型是 0.4.0 主场景；多 embedding 并存选型规则留到出现需求再补（§12 D8 记录）
- api_key 读取：`APIKeyManager.load(provider.name)`（评审 🟡8 修正——方法名 load 非 get）；未存 key 且 provider 无 env 回退 → 视为未配置（E1 语义扩展：`RAGUnavailableError` 文案区分「未配置模型」与「未配置 key」）

### 5.5 边界情况与错误处理（B+ 装配）

| # | 场景 | 行为 | 错误面 |
|---|------|------|--------|
| B1 | 无任何 provider / 无 embedding 类型模型 | `RAGUnavailableError` → 500「RAG 向量库不可用: 未配置 embedding 模型」 | E1 契约 |
| B2 | 有 embedding 模型但 key 未存 | `RAGUnavailableError` → 500「未配置 embedding 模型 API key」 | E1 扩展 |
| B3 | base_url 为 None（内置 provider SDK 默认） | `OpenAIEmbeddings` 不传 base_url（用 SDK 默认端点） | 正常路径 |
| B4 | 多个 embedding 模型 | 取 list() 首个（§5.4 选型规则） | 正常路径 |
| B5 | API 调用失败（网络/鉴权） | 透传 OpenAIEmbeddings 异常（现有 RAG 错误语义不变，spec f14 §3.4） | 500 RAG 前缀 |
| B6 | ProviderConfig 表未初始化（全新 DB） | seed_builtin_providers 幂等插入后 list() 有内置 4 provider——但**内置 provider 无 embedding 模型** → 仍报 E1（产品语义：用户需先配置 embedding 模型） | E1 契约 |

---

## 6. electron-builder 分发配置

### 6.1 依赖

`frontend/packages/electron/package.json` devDependencies 新增：

```json
"electron-builder": "^26.0.0"   // 版本以 pnpm 解析为准，uv.lock 无关（pnpm-lock 同步）
```

### 6.2 electron-builder.yml（占位转正，改动点）

```yaml
appId: com.inkflow.app
productName: InkFlow
directories:
  output: dist
files:
  - out/**
  - ../renderer/dist/**
extraResources:                    # ← 启用（占位注释移除）
  - from: ../kernel                # release.yml 组装时 dist/inkflow/ → ../kernel/
    to: kernel
win:
  target:
    - nsis
    - zip                          # ← 便携 ZIP（P3 形态，§2.2）
artifactName: InkFlow-${version}-${arch}.${ext}   # 评审 🟡10：明确产物命名（P3 验收名 InkFlow-<ver>-portable.zip 经 release.yml 改名或直接 artifactName 配置）
nsis:
  oneClick: false
  allowToChangeInstallationDirectory: true
compression: maximum               # ← T1（§3.5）
```

**要点**：
- `extraResources` 源目录 `../kernel` 由 release.yml/本地脚本在 electron-builder 前组装（`dist/inkflow/` → `kernel/`）
- zip target 产出解压文件夹结构（配合 asar + extraResources），非 portable 单 exe
- NSIS `oneClick: false`（可自选目录）+ 中文路径坑（§10 风险）

### 6.3 package.json scripts 扩展

```json
"dist:win": "electron-builder --win"
```

---

## 7. GitHub Release 自动发布（release.yml）

### 7.1 触发与结构

```yaml
# .github/workflows/release.yml（新建）
on:
  push:
    tags: ['v*']
jobs:
  package-backend:
    runs-on: windows-latest
    # setup-uv cache（enable-cache + prune-cache: false，ci.yml 同款）
    steps:
      - checkout
      - setup-python 3.11 + setup-uv（cache）
      - uv sync --frozen --extra packaging   # ⚠️ 只装 packaging extra（pyinstaller），不装 dev
      - 版本注入：tag 派生 0.4.0 → pyproject version
      - pyinstaller backend/pyinstaller/inkflow.spec
      - upload-artifact: dist/inkflow/（内核 onedir 整体）

  build-renderer:
    runs-on: windows-latest
    steps:
      - checkout
      - pnpm/action-setup + setup-node（cache: pnpm）
      - pnpm install --frozen-lockfile
      - pnpm --filter renderer build        # dist/
      - pnpm --filter inkflow-electron build # out/
      - upload-artifact: frontend/packages/renderer/dist + electron/out

  package-electron:
    needs: [package-backend, build-renderer]
    runs-on: windows-latest
    steps:
      - checkout
      - pnpm/action-setup + setup-node（cache: pnpm）
      - pnpm install --frozen-lockfile
      - download artifacts → 组装 kernel/ + dist/
      - 版本注入：package.json version ← tag
      - pnpm --filter inkflow-electron dist:win   # NSIS + ZIP
      - gh release create "$tag" dist/*.exe dist/*.zip --generate-notes
```

### 7.2 关键决策

| # | 决策 | 理由 |
|---|------|------|
| R1 | **独立 workflow，不并入 ci.yml** | 触发不同（tag vs push/PR）、产物不同（PyInstaller exe vs wheel）、发布动作不同；ci.yml build 的 wheel 是 pip 安装用，与分发 exe 是两条链 |
| R2 | **package-backend 用 `--extra packaging` 而非 dev** | dev 含 pytest 等大体积测试依赖，PyInstaller 收集会污染产物；pyinstaller 独立 extra（§3.4） |
| R3 | **各 job 自带 cache** | GitHub Actions cache 按 workflow 隔离，不能复用 ci.yml 的（用户问题 1 的回答，2026-08-06） |
| R4 | 版本单一来源 = tag | 三处注入（pyproject/package.json/renderer）从 `github.ref_name` 派生（§2.4） |
| R5 | `gh release create` 需要 `permissions: contents: write` | release.yml job 显式声明（ci.yml 各 job 只 read） |

### 7.3 发布操作（ADR-019 版本管理规则第 3 条；评审 ⚪14 引用修正）

```powershell
git tag v0.4.0 && git push origin v0.4.0    # 触发 release.yml
# 产物：InkFlow-Setup-0.4.0.exe + InkFlow-0.4.0-portable.zip + Release Notes
```

---

## 8. 文件结构

### 8.1 CREATE（新建）

| 文件 | 内容 |
|------|------|
| `backend/pyinstaller/inkflow.spec` | PyInstaller 配置（§4.2） |
| `backend/pyinstaller/README.md` | 本地打包操作说明（命令 + 冒烟步骤 + **ELECTRON_MIRROR / ELECTRON_BUILDER_BINARIES_MIRROR 设置**——评审 🟡9：国内本地打包必设，CI runner 无此问题） |
| `.github/workflows/release.yml` | tag 触发发布流水线（§7.1） |
| `backend/tests/unit/test_deps_embedding.py` | §5.3 E1-E4 契约测试（RED 先行） |
| `backend/tests/unit/test_config_frozen.py` | Q7=B 数据目录双路径测试（monkeypatch sys.frozen） |
| `ci_cd/check_version_consistency.py`（可选） | 版本一致性护栏（§2.4 验证：pyproject/package.json 对齐） |

### 8.2 MODIFY（修改）

| 文件 | 变更 | 节 |
|------|------|-----|
| `backend/pyproject.toml` | 删 litellm/sentence-transformers 依赖行；新增 `packaging` extra（pyinstaller）；version → 0.4.0 注入语义 | §3.4/§2.4 |
| `backend/uv.lock` | `uv lock` 同步（ADR-025） | §3.4 |
| `backend/src/inkflow/api/app.py` | `/health` version 字段改用 `inkflow.__version__`（评审 🔴1：现硬编码 "0.1.0"，M5 依赖） | §2.4 |
| `backend/src/inkflow/core/config.py` | **数据目录 sys.frozen 检测（Q7 拍板 B）**：打包模式默认 `%APPDATA%/InkFlow`，dev 不变 | §2.1.1 |
| `backend/src/inkflow/__init__.py` | `__version__` 改 `importlib.metadata.version("inkflow")`（不再硬编码 0.1.0） | §2.4 |
| `frontend/packages/electron/package.json` | electron-builder devDep + `dist:win` script + version → 0.4.0 | §6.1/§6.3 |
| `frontend/packages/electron/electron-builder.yml` | 启用 extraResources + zip target + compression maximum | §6.2 |
| `frontend/pnpm-lock.yaml` | pnpm install 同步 | §6.1 |
| `AGENTS.md` | 0.4.0 里程碑回写（收尾，Phase 8） | — |
| `adr/ADR-020.md` | 追加 Tauri #137 专项引用（收尾） | — |

### 8.3 不修改（明确声明）

- `frontend/packages/electron/src/kernel.ts`（resolveKernelCommand 已含 isPackaged 分支，零改动）
- `backend/src/inkflow/cli/commands/serve.py`（serve 强化版已交付，零改动）
- `frontend/packages/renderer/`（渲染层不感知打包；版本显示通道已存在）
- `specs/f19-gui/spec.md`（GUI spec 不含打包，边界已在 §1 声明）

---

## 9. 测试策略

### 9.1 层次与载体

| 层 | 载体 | 覆盖 |
|----|------|------|
| unit | `tests/unit/test_deps_embedding.py`（新建） | §5.3 E1-E4 装配契约（RED 先行，Codex 按契约实现） |
| unit（新建） | `tests/unit/test_config_frozen.py`（Q7 拍板 B 配套） | config.py sys.frozen 双路径：monkeypatch sys.frozen=True → %APPDATA%/InkFlow；False → ./data（dev 不变） |
| unit（既有） | `tests/unit/test_langchain_vector_store.py` | RAG 存储不变（FakeEmbeddings 注入，无网络）；B+ 改造不触碰 |
| guardrail/lint | 全仓 grep `HuggingFaceBgeEmbeddings` = 0 | §5.3 E5 |
| 集成（既有） | `tests/api/` + `tests/cli/` | 全量回归（B+ 改造不破坏既有端点；覆盖率门槛 98.5/95.0 不变，ADR-027） |
| CI | ci.yml 既有 job | 本任务 PR 全绿（release.yml 单独验证，不进 PR CI——tag 触发） |
| 本地冒烟 | `dist/inkflow/inkflow.exe --help` + `serve --port 0` | §4.3 P1 门禁 |
| E2E 手工 | 全新机器模拟（§13 M4） | 三产物端到端 |

### 9.2 关键场景

1. **B+ 装配**：未配置 embedding → 500 RAG 前缀；配置后 → OpenAIEmbeddings 透传（E1-E4）
2. **PyInstaller 冒烟**：`--help` 退出码 0；`serve --port 0` 输出 INKFLOW_READY JSON；写作链路 API 可达
3. **排除项 spike**：exclude onnxruntime/kubernetes/tokenizers 后 chromadb import + 检索正常（FakeEmbeddings 路径）
4. **版本一致性**：安装包属性 = renderer 关于页 = INKFLOW_READY.version = 0.4.0

### 9.3 覆盖率

- 新增装配代码走单元测试（E1-E4 全分支）；整体覆盖率门槛不变（CI coverage-backend 98.5/95.0，ADR-027）
- PyInstaller/release.yml 为 CI/发布层，不进 pytest 覆盖率口径（打包脚本属构建资产，与 ci.yml 同类）

---

## 10. 不在范围内

| 项 | 归属/原因 |
|----|-----------|
| Tauri 2 换壳 | **#137**（2.0.0 专项，用户拍板 2026-08-06「挂 1.0.0 后，以后优化用」）；ADR-020 已声明壳层薄可平滑迁移 |
| 代码签名 | 1.0.0 发布事项（杀软误报缓解）；0.4.0 首次发布用户手动「仍要运行」 |
| 自动更新（electron-updater） | 未立项；0.4.0 手动下载新版本 |
| macOS/Linux 打包 | 1.0.0「跨平台打包」验收项（ADR-019 表）；本任务仅 Windows |
| skills 包分发 | **#70**（ADR-022，0.4.0 并行 issue，独立 worktree） |
| 业务功能/API/实体 | 内核进程化已交付（#77）；本任务不改业务面（§5 装配改造是唯一代码改动） |
| RAG 向量数据迁移 | chroma.sqlite3 用户数据运行时生成，不进包、无迁移（§2.1） |
| 云端远程模式打包 | 2.0.0（GUI 远程模式是云端里程碑项） |
| **NSIS 中文/空格路径** | 已知坑（electron-packaging 技能）：安装目录含中文/空格时偶发问题——**验证门禁覆盖**（M4 全新机器安装路径含中文场景），非本任务实现项 |
| **UPX 压缩** | T1 可选优化（§3.5）：spike 评估杀软误报风险后决定是否启用；**默认不启用**（PyInstaller onedir 已满足体积目标），启用需过 M7 spike |

---

## 11. 依赖关系

### 11.1 依赖（本任务需要的既有交付）

| 依赖 | 交付 | 用途 |
|------|------|------|
| #77 内核进程化 | ✅ PR #85 | INKFLOW_READY 契约（P1 冒烟验收） |
| #78 Electron 壳 | ✅ PR #95 | isPackaged 分支 + resources/kernel 定位 |
| #79 + 子任务渲染层 | ✅ PR #97/#120/#121/#135（#122 属 #106 模型管理，评审 ⚪15 分组修正——已并入本行引用） | renderer dist 构建 + 版本显示通道 |
| #106 ProviderConfig | ✅ PR #122 | embedding 模型注册（§5 装配数据源） |
| #50 F23 SSE | ✅ PR #83 | 写作流（E2E 冒烟链路） |
| ADR-013/021 | ✅ | RAG 存储 / 进程化契约依据 |
| #70 skills 包 | ⏳ 并行 | **无代码依赖**（独立 worktree，ADR-022 分发独立） |

### 11.2 被依赖（下游）

| 下游 | 依赖本任务的什么 |
|------|------------------|
| #70 skills 包 | 无（并行）；但 0.4.0 发布 tag 时两产物一起发布（ADR-019 0.4.0 口径） |
| #137 Tauri | 打包产物矩阵稳定（安装包/便携 ZIP/内核 exe 形态），Tauri 替换壳后保持同构 |
| 1.0.0 跨平台 | 本任务建立的 release.yml 模式扩展到 mac/linux |

### 11.3 编号口径声明

F19 为拆分条目：GUI 壳与内核进程化（0.3.0）已完成，打包分发（0.4.0）为本任务——以 ADR-019 v2 为准（PRD §6.4 旧归属已被形态决策重排）。

---

## 12. 关键架构决策记录

| # | 决策 | 方案 | 理由 | 备选（否决） |
|---|------|------|------|--------------|
| D1 | **B+：chromadb 进包 + API embedding** | torch/ST 出包；chromadb ~70-110MB 进包；embedding 走 ProviderConfig 注册的 API 模型 | 体积/功能帕累托最优；RAG 装完即用；与 #106 provider/key 体系天然契合 | A 全量（1.5-2GB，torch 打包风险）；B 排除（「按需装」在冻结环境不可行，§3.2） |
| D2 | **release.yml 独立 workflow** | tag `v*` 触发，3 job（package-backend/build-renderer/package-electron） | 触发/产物/权限与 ci.yml 不同；PyInstaller exe ≠ wheel | 并入 ci.yml（触发语义污染）；本地手动打包（不可重复） |
| D3 | **PyInstaller onedir** | `dist/inkflow/inkflow.exe` + `_internal/` | 启动快、hidden-import 可排查 | onefile（启动解压慢、报错黑盒） |
| D4 | **版本单一来源 = tag** | 构建期从 `github.ref_name` 注入三处 | 修 0.1.0/0.3.0 不一致存量债；避免多源漂移 | 三处手写（现状，已实测漂移） |
| D5 | **pyinstaller 独立 `packaging` extra** | release.yml `uv sync --extra packaging` | 不污染运行时依赖；dev 组 pytest 等大依赖不进打包环境 | 并入 dev（PyInstaller 收集污染）；并入 dependencies（运行时不需要） |
| D6 | **zip 目录打包（非 portable 单 exe）** | electron-builder zip target + 组装目录 | 「解压即用文件夹」是用户验收形态（§2.2 P3，拍板 A） | portable（自解压单 exe，非文件夹形态） |
| D7 | **装配改造并入 #48** | deps.py 一处装配 + RED 契约（P1=A 拍板） | 不改造则 B+ 无法落地（打包时已无本地 embedding）；拆两个 PR 互相依赖 | 单独 issue（依赖链更长） |
| D8 | **embedding 选型 = 首个匹配**（非默认标记） | 遍历 `repo.list()` 取首个 `type="embedding"` 模型 | YAGNI：单 embedding 是 0.4.0 主场景；「默认标记」是表结构/API 变更，无需求驱动 | 显式 default 标记字段（schema 变更，过度设计） |
| D9 | **数据目录 = config.py sys.frozen 检测（Q7=B 拍板）** | 打包模式默认 `%APPDATA%/InkFlow`，dev 不变；env 可覆盖 | 数据目录逻辑归内核配置层（壳保持薄，ADR-020）；测试注入点明确；dev/打包双路径可测 | A 壳注入 env（壳层职责膨胀）；C 接受 exe 目录（Program Files 写失败，违反 M4） |

---

## 13. 验收标准

| # | 验收项（M 行） | 验证方式 | 载体 |
|---|---------------|----------|------|
| M1 | 内核 exe 独立可用：`inkflow.exe --help` 退出码 0；`serve --port 0` 输出 INKFLOW_READY | 本地 P1 冒烟（§4.3） | 手动 + 脚本 |
| M2 | 安装包可生成：`InkFlow-Setup-<ver>.exe`（NSIS，可选目录） | electron-builder 本地/CI 运行 | 手动 + release.yml |
| M3 | 便携 ZIP 可生成：`InkFlow-<ver>-portable.zip` 解压即用文件夹 | 同上 | 手动 + release.yml |
| M4 | 全新机器模拟（无 Python/Node）：安装 → 启动 GUI → 内核拉起 → 写作流可用；**数据落 %APPDATA%/InkFlow（Q7=B），安装目录只读场景不写失败** | 隔离环境（VM/沙箱）手工走查 | 手工 |
| M5 | 三产物版本一致 = 0.4.0（安装包属性 / renderer 关于页 / INKFLOW_READY.version） | §2.4 验证脚本 | 脚本 + 手动 |
| M6 | T0 生效：内核 onedir ~250-350MB；安装包下载体积 ~200-250MB（实测记录 + 预算偏差说明口径，§2.3） | 产物实测 | 手动 |
| M7 | 排除项 spike 通过：exclude onnxruntime/kubernetes/tokenizers 后 chromadb import + 检索正常 | spike 脚本（FakeEmbeddings 路径） | 脚本 |
| M8 | RAG 功能可用（B+）：配置 embedding 模型后提取/检索正常；未配置 → 500 RAG 前缀 | E1-E4 + 手工 | 单元 + 手动 |
| M9 | release.yml 全绿：tag `v0.4.0` → 3 job 成功 → Release 资产可网页下载 | GitHub Actions 实跑 | CI |
| M10 | 既有测试全绿：backend unit/integration/coverage（98.5/95.0）+ frontend 三层 | ci.yml PR 全绿 | CI |
| M11 | `HuggingFaceBgeEmbeddings` 全仓 0 命中（源码/文档） | grep guardrail | lint |

> 完成标准映射：M1-M4 = ADR-019 v2「Windows 三种打包可用」；M5 = 版本一致性（存量债修复）；M6-M8 = T0/B+ 瘦身决策验收；M9 = 发布流水线；M10-M11 = 质量门禁。

---

## 待澄清问题（已拍板，留痕）

1. **Q1 RAG 打包策略**：A 全量内置（1.5-2GB）/ B 排除（报未安装）/ **B+ chromadb 进包 + API embedding（~500-700MB）**。**✅ 已确认（用户拍板：B+，2026-08-06）**——正文 §3.1 已按 B+ 修订。追问「打包后下载 chromadb 可否」：不可行（冻结环境/ABI/依赖树，§3.2 论证）。
2. **Q2 发布通道**：本地手动 / **release.yml 自动发布（tag v\*）**。**✅ 已确认（用户拍板：选项 A=release.yml，2026-08-06）**——正文 §7 已按自动发布修订。追问「build job cache / 新 release job」：cache 按 workflow 隔离需自带（§7.2 R3）；release 是独立 workflow 非 ci.yml job（§7.2 R1）。
3. **Q3 便携 ZIP 形态**：**zip 目录打包（解压即用文件夹）** / portable 单 exe 自解压。**✅ 已确认（用户拍板：选项 A，2026-08-06）**——正文 §2.2 P3 已按文件夹形态修订。
4. **Q4 装配改造归属**：**并入 #48（P1=A）** / 单独 issue。**✅ 已确认（用户拍板：选项 A，2026-08-06）**——正文 §5 已并入。
5. **Q5 Tauri 换壳**：**开独立 issue #137 挂 2.0.0**（用户拍板 2026-08-06「挂 1.0.0 后，以后优化用」）/ 仅 ADR 备注。**✅ 已确认**——正文 §10 不在范围内 + ADR-020 收尾备注。
6. **Q6 压缩档位（T1）**：NSIS `compression: maximum` + UPX 可选。**✅ 已确认（用户拍板：按建议，2026-08-06）**——正文 §3.5。
7. **Q7 数据目录落点（评审 🔴5 发现）**：A 壳注入 env（`INKFLOW_DATA_DIR`/`INKFLOW_DATABASE_URL`）/ **B config.py `sys.frozen` 检测默认 %APPDATA%/InkFlow** / C 接受 exe 目录。**✅ 已确认（用户拍板：选项 B，2026-08-06）**——正文 §2.1.1 已按 B 修订（config.py sys.frozen 检测 + 壳零改动成立 + §8.2 config.py MODIFY 行）。
