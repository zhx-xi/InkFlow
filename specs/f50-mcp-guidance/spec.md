# F50 MCP 分发引导 — 功能规格（Specify 阶段）

> **Spec 版本**: v1.0
> **日期**: 2026-08-23
> **依据**: PRD §6.4 / Constitution P1-P6 / 用户拍板文件 `design/inkflow-mcp-distribution-guidance-2026-08-21.md`（工作区 D:\develop\hermes-projects\InkFlow）
> **所属阶段**: 0.12.0（最后一个 feature 轨），Issue #563（Closes）＋收尾 #551
> **关联 Issues**: #563（MCP 分发引导落地）/ #49（F20 MCP server，0.9.0 已交付）/ #551（自动写作链路收尾）
> **依赖**: F20（mcp server 薄客户端已实现并随包分发）、ADR-022（skills 三通道分发，mcp-setup.md 演进预留）、ADR-023 v2（薄客户端经 HTTP）、ADR-030（本地内核服务化）
> **参考 ADR**: [ADR-022](../../adr/ADR-022.md) · [ADR-023](../../adr/ADR-023.md) · [ADR-030](../../adr/ADR-030.md)
> **状态**: 待实现 🔲

> **Spec 变更**: v1.0 初始版（承接 #563 拍板，落地 MCP 分发引导的可发现性缺口）

## 1. 概述

### 1.1 模块定位

F20（#49，0.9.0 已交付）让 InkFlow 通过 MCP 协议暴露 15 个工具（`inkflow-mcp` 薄客户端经 HTTP 直连常驻内核，ADR-030 D3=A / ADR-023 v2）。**但「可发现性为零」**——agent 与其他宿主不知道 InkFlow 有 MCP 能力、客户端在哪、怎么配置。本模块补齐分发引导，**不改 MCP 集成本身**，只补「可发现性/可配置性」面。

**不做的事**（见 §10）：不重写 CLI 为 MCP 函数、不写 GUI 一键写入宿主配置、不做云端 MCP、不发布 PyPI uvx 通道。

### 1.2 与样板差异图

本模块是「文档 + 只读端点 + GUI 面板 + 安装器 PATH」四件套，非实体 CRUD 型模块——**无新数据模型 / 无新领域实体**，无跨模块 MODIFY 风险面（仅 MODIFY `api/app.py` 注册路由 + `installer.nsh` PATH）。

### 1.3 边界声明

- 端点 `/api/v1/mcp/info` = **自发现通道**（agent 程序化查询），只读、无副作用、无鉴权豁免（天然带 TokenAuthMiddleware，见 §3）。
- MCP 集成本体（tools/list / tools/call / stdio）不在本模块范围。

## 2. 数据模型

**无新数据模型 / 无新 Pydantic 实体**。端点响应为一次性构造的 dict，字段契约见 §3。所需的「MCP 客户端路径」由纯函数 `locate_mcp_client()` 运行时计算（不持久化——不同形态（源码/便携/NSIS/CLI zip）路径不同，动态值最稳）。

## 3. API 契约

### 3.1 端点总览

| 方法 | 路径 | 说明 | 状态 |
|------|------|------|------|
| GET | `/api/v1/mcp/info` | MCP 自发现信息（客户端路径 + 版本 + 宿主配置模板） | 新增 |

### 3.2 请求 / 响应

**GET `/api/v1/mcp/info`** — 无请求体。

响应 200（`application/json`）：

```json
{
  "client_path": "C:\\Program Files\\InkFlow\\resources\\kernel\\mcp\\inkflow-mcp.exe",
  "version": "0.12.0",
  "config_template": {
    "claude": {
      "mcpServers": {
        "inkflow": { "command": "C:\\Program Files\\InkFlow\\resources\\kernel\\mcp\\inkflow-mcp.exe" }
      }
    },
    "cursor": {
      "mcpServers": {
        "inkflow": { "command": "C:\\Program Files\\InkFlow\\resources\\kernel\\mcp\\inkflow-mcp.exe" }
      }
    },
    "hermes": {
      "mcpServers": {
        "inkflow": { "command": "C:\\Program Files\\InkFlow\\resources\\kernel\\mcp\\inkflow-mcp.exe" }
      }
    }
  }
}
```

字段契约（**锁定**）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `client_path` | `str` | inkflow-mcp 可执行文件绝对路径（运行时动态解析，见 §3.4）；恒非空 |
| `version` | `str` | `inkflow.__version__`（动态读，不硬编码；与内核 /health 同源） |
| `config_template` | `dict[str, dict]` | 各宿主 mcpServers 配置模板，键 = `claude` / `cursor` / `hermes`，值 = 宿主配置文件 JSON（command 内已填 `client_path`） |

### 3.3 异常映射

| 情形 | 状态码 | body |
|------|--------|------|
| 未带 token / token 无效 | 401 | `{"detail": "..."}`（TokenAuthMiddleware 统一处理，非本路由） |
| 任何其他 | - | 不预期——本端点无 DB/LLM 依赖，500 不应发生 |

### 3.4 client_path 解析（`locate_mcp_client` 纯函数）

运行时按序取第一个存在的候选（均返回 `Path`）：

| # | 候选 | 形态 |
|---|------|------|
| 1 | `Path(sys.executable).parent / "mcp" / "inkflow-mcp.exe"` | NSIS 安装版 / 便携 zip：`resources\kernel\mcp\inkflow-mcp.exe` |
| 2 | `Path(sys.executable).parent / "inkflow-mcp.exe"` | dev venv `Scripts\` console script / onedir 兄弟 |
| 3 | `Path(sys.executable).parent.parent / "inkflow-mcp" / "inkflow-mcp.exe"` | CLI zip：`inkflow-mcp/` 与 `inkflow/` 兄弟目录 |

未命中 → 回退候选 1 的期望路径（`Path(sys.executable).parent / "mcp" / "inkflow-mcp.exe"`），保证恒非空。

## 4. CLI 命令签名

本模块**无新 CLI 命令**（MCP 自发现是 HTTP 面，不增 CLI；CLI 已由 F38/ADR-030 恒经 HTTP 覆盖）。

## 5. 关键差异节：分发引导四件套

### 5.1 P0 文档补全（mcp-setup.md + SKILL.md MCP 段）

`skills/inkflow/references/mcp-setup.md` 从占位 → 实操指引：

- **三形态 exe 路径**：CLI zip（`inkflow-mcp/inkflow-mcp.exe`）/ 便携 + NSIS（`resources\kernel\mcp\inkflow-mcp.exe`）/ dev venv（`<venv>\Scripts\inkflow-mcp.exe`）。
- **各宿主 mcpServers JSON 模板**：Claude Desktop / Cursor / Hermes，command 指向实际路径。
- **使用策略**：MCP 优先 / CLI 兜底；工具面以 `tool_search` 为准（**不写 15 工具函数清单**——tools/list 自描述，写 = 漂移源，F20 §4.2/§11）；信封语义（`{"ok":...,...}`）；冷启动说明（首次调用 ensure_kernel 拉起内核，秒级等待）。
- `skills/inkflow/SKILL.md` MCP 段从「发布后补充」改为摘要 + 指向 mcp-setup.md。

### 5.2 P1-A GUI 设置页「MCP 接入」面板

设置页 GeneralPanel 内新增 `McpSettingsCard` Card（零侵入，方案 A）：

- `data-testid="mcp-settings-panel"`（根）。
- 显示当前客户端 exe 路径（动态，来自 `/api/v1/mcp/info`）：`data-testid="mcp-client-path"`。
- 一键复制按钮：客户端路径 + Claude Desktop / Cursor / Hermes 配置 JSON（来自 `config_template`），用 `navigator.clipboard.writeText`；成功 → toast「已复制」。
- 明确**不写**外部宿主配置文件（方案 B 下版评估）。失败（内核未就绪 / 端点 4xx）→ 面板降级显示「暂不可用」+ 保留空路径，不阻断设置页。

### 5.3 P2 内核端点

见 §3（`GET /api/v1/mcp/info`），装配于 `api/routers/mcp.py` + `api/app.py` 注册。**打包版可用**（PyInstaller 冻结后 `inkflow.__version__` 经 copy_metadata 的 dist-info 读取，f19-packaging 已建立）。

### 5.4 附加 installer.nsh PATH 补 `resources\kernel\mcp`

现有 `AddKernelDirToPath` / `un.RemoveKernelDirFromPath` 只写/删 `resources\kernel`。**追加第二个条目 `resources\kernel\mcp`**（同幂等去重逻辑：按 `;` 分隔段大小写不敏感 + 尾部反斜杠归一化；1000 字符保护不变）。安装勾选 PATH 后 `inkflow-mcp` 命令可达，卸载按精确条目清理两目录。

## 6. 组织规则

无全局约定变更。新增路由 `backend/src/inkflow/api/routers/mcp.py` 遵循既有 router 模式（`APIRouter(prefix="/api/v1/mcp", tags=["MCP"])`），经 `api/app.py` `include_router(mcp.router)` 注册。辅助逻辑放 `inkflow/mcp/info.py`（纯函数，无 I/O），与既有 `mcp/server.py` / `mcp/tools/` 同包。

## 7. 边界情况与错误处理

| 情形 | 处理 |
|------|------|
| 内核未运行就调 `/api/v1/mcp/info` | 端点本身独立于运行态？——否：端点由内核进程服务，内核运行即可达；不触发 ensure_kernel（GUI 已拉起内核） |
| 打包版 mcp 客户端二进制缺失 | `locate_mcp_client` 回退期望路径（恒非空），GUI 显示该路径，文档解释三形态 |
| GUI 端点 4xx/网络失败 | 面板降级「暂不可用」，不抛错阻断 |
| 复制失败（clipboard 权限） | toast 失败提示 |
| PATH 超过 1000 字符 | 现有保护逻辑跳过写入并 DetailPrint 警告（不变） |

## 8. 文件结构

| 操作 | 文件 | 说明 |
|------|------|------|
| CREATE | `specs/f50-mcp-guidance/spec.md` | 本文件 |
| CREATE | `backend/src/inkflow/mcp/info.py` | `locate_mcp_client()` + `build_mcp_info()`（含 config_template 构造） |
| CREATE | `backend/src/inkflow/api/routers/mcp.py` | `GET /api/v1/mcp/info` router |
| MODIFY | `backend/src/inkflow/api/app.py` | import + `include_router(mcp.router)` |
| CREATE | `backend/tests/unit/test_mcp_info_api.py` | RED 契约：端点形状 + version 动态 + config_template 一致性 + locate 函数 |
| CREATE | `frontend/packages/renderer/src/components/McpSettingsCard.tsx` | GUI「MCP 接入」面板（方案 A） |
| MODIFY | `frontend/packages/renderer/src/pages/settings.tsx` | GeneralPanel 内挂载 `<McpSettingsCard />` |
| MODIFY | `frontend/packages/renderer/src/api/client.ts` | 新增 `fetchMcpInfo()` 类型化调用 |
| MODIFY | `frontend/packages/renderer/src/i18n/zh.ts` + `en.ts` | 新增 `set.mcp.*` 文案 |
| CREATE | `frontend/packages/renderer/src/components/McpSettingsCard.test.tsx` | RED 契约：面板展示 + 复制 JSON |
| MODIFY | `frontend/packages/electron/build/installer.nsh` | PATH 补 `resources\kernel\mcp`（幂等去重 + 卸载清理） |
| MODIFY | `skills/inkflow/references/mcp-setup.md` | 占位 → 实操指引 |
| MODIFY | `skills/inkflow/SKILL.md` | MCP 段非占位 |

> 说明：installer.nsh 无契约测试框架（NSIS），以打包脚本验证 + 人工核对幂等逻辑（§5.4）；不新增编译期测试。

## 9. 测试策略

| 层次 | 覆盖 | 命令 |
|------|------|------|
| backend/unit | `/api/v1/mcp/info` 端点形状 + version 动态 + config_template 三宿主键 + locate_mcp_client 三形态 | `cd backend; uv run pytest tests/unit/test_mcp_info_api.py` |
| frontend/vitest | McpSettingsCard 展示路径 + 一键复制（clipboard mock） | `pnpm vitest run McpSettingsCard` |

覆盖率：本模块为只读端点 + 展示面板，无新分支逻辑；端点形状与 resolve 逻辑为断言主体。全局 ≥60% 达标（新增逻辑面窄，不拉低）。

## 10. 不在范围内

| 项 | 归属/原因 |
|----|-----------|
| skills 里 CLI 调用改写为 MCP 函数 | ADR-022：工具由协议自描述，不重复实现逻辑 |
| GUI 一键写入宿主配置文件（方案 B） | 下版评估（#563 拍板方案 A） |
| 云端 Streamable HTTP / remote MCP | ADR-023 后移 2.0.0 云端里程碑 |
| PyPI `uvx inkflow-mcp` 通道 | 候选，随 2.0.0 云端版评估 |
| MCP 工具函数清单写入文档 | tools/list 自描述，F20 §4.2/§11（写 = 漂移源） |

## 11. 依赖关系

| 依赖 | 说明 |
|------|------|
| ✅ F20（mcp server） | 0.9.0 已交付，tools/list 自描述 |
| ✅ ADR-022 / ADR-023 v2 / ADR-030 | 架构定论沿用，不改 |
| ✅ f19-packaging（PyInstaller dist-info + `resources/kernel` 布局） | client_path 解析基础 |
| ⏳ f42 / f47（写作链路） | #551 收尾（本 PR 只关 #551，不依赖实现） |

## 12. 关键架构决策记录

| 决策 | 方案 | 理由 | 备选否决 |
|------|------|------|----------|
| GUI 面板范围 | **方案 A**（显示路径 + 一键复制 JSON） | 零侵入，不写外部宿主配置 | B（一键写入宿主配置文件）：下版评估 |
| 自发现端点 | **做** `GET /api/v1/mcp/info` | agent 程序化查询，与 mcp-setup.md 联动 | 只写文档：agent 无法程序化获取 |
| client_path 解析 | 运行时动态 `locate_mcp_client()` 纯函数 | 多发行形态路径不同，动态最稳 | 硬编码：形态间漂移 |
| 归属版本 | **全部归 0.12.0** | 拍板 | - |

## 13. 验收标准

| # | 里程碑 | 验证 |
|---|--------|------|
| M1 | RED 契约 FAIL 确认 | 后端 `uv run pytest tests/unit/test_mcp_info_api.py` 全 FAIL（ModuleNotFoundError / 断言失败）；前端 `pnpm vitest run McpSettingsCard` FAIL（组件不存在 collection error） |
| M2 | GREEN | 后端 `cd backend; uv run pytest tests/unit/ ../tests/` + ruff + mypy 全绿；前端 `pnpm vitest run && pnpm tsc --noEmit` 全绿 |
| M3 | PR merged + CLOSED | `gh pr merge --squash --delete-branch`；#563 CLOSED；#551 CLOSED（收尾）；`git worktree remove` |

**手工验收（发布验证）**：打包版 `curl http://127.0.0.1:<port>/api/v1/mcp/info`（带 token）返回 `{client_path, version, config_template}`，`client_path` 指向 `resources\kernel\mcp\inkflow-mcp.exe`；mcp-setup.md 照做能配通；安装勾选 PATH 后 `inkflow-mcp` 可达。

## 待澄清问题（≤3）

1. ~~config_template 是否按宿主分键~~ ✅ 已确认（用户拍板：方案 A，三宿主 Claude/Cursor/Hermes 分键 `claude`/`cursor`/`hermes`，值 = 宿主 mcpServers JSON，command 填 client_path）——正文 §3.2 已按此定稿。
