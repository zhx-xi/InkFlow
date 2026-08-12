# 系统命令（system.md）

agent 使用：serve / kernel / search / config / llm——内核与系统级操作。

## serve（诊断模式核心）

| 命令 | 参数 | 说明 |
|---|---|---|
| `serve` | `--host`(127.0.0.1) `--port`(8000；**0 = 动态随机**) `--port-file` `--token`(缺省随机) `--open-browser` `--reload` | 前台直启内核；就绪 = stdout `INKFLOW_READY {"port","token","pid","version"}`；**不写 kernel.json**（诊断场景直接解析 INKFLOW_READY 行）；`--reload` 模式无交付契约 |

- **500 诊断唯一可靠 stderr 来源**：`serve --port 0 --port-file <f>` + `-RedirectStandardError <err.log>`（GUI 拉起的内核无 stderr 捕获）
- 场景：排查内核 500 / 确认 API 路径（openapi）/ 观察请求日志

## kernel

| 命令 | 说明 |
|---|---|
| `kernel status` | 读 kernel.json + PID 存活检查（无参；输出 running/pid/port/version；**绝不拉起内核**） |

## search（全文搜索）

| 命令 | 参数 | 说明 |
|---|---|---|
| `search <query>` | 位置参数 query(1-100 字符，--rebuild 模式可省)；`--project`(可重复、名称或 UUID) `--type` `--mode`(keyword\|semantic) `--limit`(20,≤100) `--offset` `--rebuild`(⚠️ 只取第一个项目，#251 P3) | 全文搜索 |

- ⚠️ `search` 是压平单命令（无 search search 嵌套）；`--rebuild` 仅支持单项目

## config（本地配置文件，非 settings 表！）

| 命令 | 说明 |
|---|---|
| `config show` | 展示 7 键配置（default_model/temperature/ratio/window/host/port/data_dir） |
| `config set <key> <value>` | 改配置；key 必须 ∈ CONFIG_WHITELIST，未知 key exit 2 |

⚠️ **`config` 组 ≠ GUI 设置页**：它读写 `data_dir/config.json`（服务端白名单配置），GUI 设置页（theme/bg/lang/字体/关闭行为/托盘提示）走 `/api/v1/settings` 表（CLI 无对应，#251 豁免——纯 UI 偏好）。

## llm（key 文件管理）

| 命令 | 说明 |
|---|---|
| `llm list` | 列 Provider + key_status（本地 key 文件，**非** provider-configs 表） |
| `llm set-key` | `--provider <name> --key <sk-...>`（--key 参数模式；stdin 挂起） |

详见 models.md（Provider 注册表缺口与 HTTP 直调）。

## 易错点

- `serve --port 0` 是**前台阻塞**命令（后台会话跑）；就绪判据 = INKFLOW_READY 行
- 开发版 `--version` 显示 pyproject 版本（如 v0.1.0），**不是产品版本**——版本判据只对打包产物有效（显示 tag 版本，PEP 440 规范化）
