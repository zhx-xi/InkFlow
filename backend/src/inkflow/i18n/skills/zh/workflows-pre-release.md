# 功能验证场景指南（workflows-pre-release.md）

新版 CLI 产物（正式版/rc）的端到端功能验证。单测/CI 全绿 ≠ 真实可用——验证必须按用户场景跑真实 CLI 命令链。

## 验证面分层

CLI 与 GUI 共享同一内核 HTTP API（GUI = 薄壳 + 渲染层，业务全在后端）：**GUI 有的功能 CLI 全有，CLI 有的 GUI 不一定有**。验证 CLI = 覆盖核心功能；GUI 门禁只做启动/健康/版本，交互操作归用户复验。

## 前置

- 新版本产物就绪（CLI zip 已解压）
- **独立数据目录**：`%APPDATA%`（打包版）或 `INKFLOW_DATA_DIR`（dev 版）指向临时目录 = 全新 DB；上次验证的项目/章节不存在，别误判为缺陷；不污染正式数据
- LLM key：`llm set-key --provider deepseek --key sk-...`、`llm set-key --provider zhipu --key ...`（embedding）；全程 mask

## 断言规范

场景脚本每步自动断言，不是人工走查：

1. **JSON 信封**：`--json` 输出含 `"ok":true`（失败 = exit 1 + `ok:false` → 立即标记 FAIL 并停止）
2. **关键字段**：create 返回非空 UUID；list 含刚建条目；update 后回读一致；delete 后 list 不含
3. **LLM 链路**：content 非空、`word_count > 0`、`format_valid: true`、`token_usage` 存在；agentic 返回 agent_run 记录（steps/tool_calls）
4. **SSE**：首帧 <2s、帧结构（data: JSON）、无中途 error 帧
5. **失败即停 + 快照**：FAIL 时保存该步完整输出到日志文件，报告根因方向
6. **幂等**：重跑前清理（新数据目录或删除已建项目）

## 场景矩阵（发布前必跑 A/B/C/D）

| 场景 | 类型 | 旅程 | 覆盖域 | 数据依赖 |
|------|------|------|--------|----------|
| **A 新作者开新书** | 用户思维 | 建项目→配AI→设定库（世界/角色/地图/时间线/伏笔）→大纲→卷/章节→生成/续写/修订→agentic→草稿确认→提取→审计→风格→导出/搜索 | F1-F3,F5,F6,F9-F16,F21-F23,F26,F27,F30,F32,RAG | 独立（种子场景） |
| **B 老作者续写维护** | 用户思维 | 章节状态流转→续写修订→审计矛盾修正→时间线/伏笔维护→会话删除→回收站 restore→审计日志→导出备份 | F1,F2,F12-F15,F21,F24,F27,F28 | **承接 A 的项目** |
| **C 全功能域巡检** | 工程兜底 | 所有命令组最短路径 CRUD + 系统命令 + 缺口域 HTTP 直调 | 全部域 + 系统面 | 独立项目（不污染 A/B/D 数据） |
| **D AI 深度工作流** | 产品思维 | agentic 工具链→草稿确认→偏好学习（N≥2）→semantic RAG→上下文注入→memory remove 立即生效 | F26-F28,RAG,F6 | **复用 A 的项目** |

执行顺序 **A → B → C → D**（串行，共享同一数据目录；A/B/D 数据流承接，C 独立）。

## 场景 A「新作者开新书」（完整旅程）

```powershell
# 1. 项目 + AI 配置
project create --name verify --json
llm set-key --provider deepseek --key sk-****
llm set-key --provider zhipu --key 8a31****ZG3M   # embedding
# 2. 设定库铺垫
world create --project-id <uuid> --name 世界观 --content <内容>
character create --project-id <uuid> --name 主角 --description <描述>
character create --project-id <uuid> --name 配角 --description <描述>
map create --project-id <uuid> --name 地图 --content <描述>
timeline create --project-id <uuid> --title 关键事件 --date <时间>
foreshadowing create --project-id <uuid> --title 伏笔A --content <埋设>
# 3. 大纲 → 卷/章节
outline create --project-id <uuid> --title 大纲 --content <内容>
volume create --project-id <uuid> --name 第一卷
chapter create --project-id <uuid> --title 第一章 --content <≥50字>
# 4. 写作链路（生成→SSE→修订）
write next --project-id <uuid> --chapter-id <cid> --outline <主题> --min-words 300
write continue --project-id <uuid> --chapter-id <cid> --stream   # SSE 帧，首 token ≤2s
write revise --project-id <uuid> --chapter-id <cid> --content <改后> --model deepseek/deepseek-v4-flash
# 5. agentic + 草稿确认
write next --mode agentic --project-id <uuid> --chapter-id <cid> --outline <主题> --min-words 300
#   草稿确认流 → 章节 final（契约见 writing.md）
# 6. 提取（真实 AI）
extract run --project-id <uuid> --types character,world
extract status --run-id <id>
# 7. 审计 + 风格
audit check --project <名或UUID>
style analyze --project-id <uuid>
# 8. 导出 + 搜索（keyword + semantic）
export export <名或UUID>
search <关键词> --project <名或UUID>
search --mode semantic <查询> --project <名或UUID>   # embedding 真实调用
# 9. 记忆统计
memory stats --project-id <uuid>
```

## 场景 B「老作者续写维护」

```powershell
# 1. 项目/章节状态流转
project list
chapter list --project-id <uuid> --status draft   # 显式 --status
chapter update --id <cid> --status writing
# 2. 续写 + 修订（显式 model）
write continue --project-id <uuid> --chapter-id <cid>
write revise --project-id <uuid> --chapter-id <cid> --model deepseek/deepseek-v4-flash
# 3. 审计矛盾 → 修正（时间线/伏笔维护）
audit check --project <名或UUID>
timeline update --id <tid> --title 修正后
foreshadowing resolve --id <fsid>     # 回收
foreshadowing reopen --id <fsid>      # 重开
# 4. 会话删除
session list --project-id <uuid>
session archive --id <sid> / session delete --id <sid>
# 5. 回收站 restore 回归
character delete --id <cid>
character restore --id <cid>
# 6. 导出备份
export export <名或UUID>
```

## 场景 C「全功能域巡检」

所有命令组 **create → list/get → update → delete → restore** 最短路径一次成功（world/character/outline/timeline/foreshadowing/map/chapter/volume/project），加系统命令：`serve --port 0 --port-file`、`config`、`llm list`、`agent validate` + `agent run/status`、`audit chapter`、`vector reindex|retrieve`（embedding）、`memory add`（HTTP 直调）、`POST /api/v1/context/assemble`（HTTP 直调）。**默认参数路径必须跑**（不加 flag 的最常见调用最易坏）。

## 场景 D「AI 深度工作流」

```powershell
# 1. agentic 写作（工具链：search_characters/check_foreshadowing/get_prior_summary/audit_chapter/count_words）
write next --mode agentic --project-id <uuid> --chapter-id <cid> --outline <主题> --min-words 300 --json
#   判据：agent_run 记录（steps/tool_calls/token）；显式 model
# 2. 草稿确认流 → final
# 3. 偏好学习：多次修改同类（N≥2）→ memory list 出现偏好 → learned_preferences>0
memory list --project-id <uuid>
memory stats --project-id <uuid>
# 4. semantic RAG：搜索资料库 → 上下文注入（write 请求自动装配偏好 + 上下文）
search --mode semantic <查询> --project <名或UUID>
# 5. memory remove 立即生效（删除偏好 → 注入停止）
memory remove --id <pid> --project-id <uuid>
memory list --project-id <uuid>   # 该偏好消失
```

## 回归裁剪

迭代修复后**不全量重跑**：修复影响域 → 重跑相关场景（如记忆模块修复 → 只重跑场景 D 记忆段 + 场景 B/C 的 memory 命令组）；**全量 A-D 只在发布前最后验证跑一次**；裁剪重跑 PASS 后才允许打下一个发布 tag。

## 数据升级兼容（新版本打开旧版本数据）

用上一版本生成的数据目录启动新版内核（自动迁移），断言：`project list` 旧项目在（id 一致）、`chapter list` 内容完整、`search` 索引可读、`memory stats` 表兼容、update 一个条目回读一致（旧数据可写）、内核 stderr 无迁移错误。任何数据丢失/迁移错误 → 阻断缺陷。

## 5 类缺陷模式复检（每轮验证）

1. `GET /openapi.json` 核对目标端点存在（不信测试绿）
2. 每条新命令真实跑一遍（**含默认参数路径**）
3. 500 一律 serve 前台 + stderr 重定向拿 traceback
4. LLM 链路先确认模型解析路径（DTO 字段/config 默认/env）+ key 注入
5. 验证全程用独立数据目录；正式数据前后对比

## 易错点

- `--project-id` 只收 UUID；`chapter create` 非法 UUID → DB_ERROR 信封（不是 NOT_FOUND）
- `chapter list` 必须显式 `--status`；`--json` 根级放子命令前
- seed UUID 每表独立不能猜——`list --json` 拿真实 UUID
- 敏感凭据全程 mask（`sk-****0a68`）

## 版本敏感点

- 产物 URL/tag 判据：`https://github.com/zhx-xi/InkFlow/releases/download/<tag>/InkFlow-CLI-<tag>-x64.zip`（以 release 资产实际命名为准）
- 新版本对照 FEATURES.md 增量更新场景矩阵（新功能域并入最贴近的场景或新增场景）
