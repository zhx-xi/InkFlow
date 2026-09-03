# 日常操作流程（workflows-daily.md）

agent 通过 InkFlow CLI 操作数据的日常端到端流程：创建项目 → 写作 → 资料库维护 → 审计/记忆 → 导出。原则：能读不写；破坏性操作先列计划。

## 通用前置

1. 确认数据目录：打包版 `%APPDATA%\InkFlow`，dev 版 `INKFLOW_DATA_DIR`；演示/验证用独立数据目录，与正式数据分开
2. 写作链路需要 LLM key：`llm set-key --provider deepseek --key sk-...`（embedding 用 zhipu）；key 全程 mask
3. 写操作（create/update/delete）前想清楚影响面；delete 类先 `--json` 确认目标再执行

## 创建项目

```powershell
project create --name X --json          # 返回项目 id（UUID），后续命令复用
project list --json                     # 查看现有项目真实 id/名称
```

## 写作

```powershell
chapter create --project-id <uuid> --title 第一章 --content <≥50字> --json
chapter list --project-id <uuid> --status draft
write next --project-id <uuid> --chapter-id <cid> --outline <主题> --min-words 300
write continue --project-id <uuid> --chapter-id <cid> --stream
write revise --project-id <uuid> --chapter-id <cid> --content <改后>
# 完整写作链路（SSE/草稿确认/agentic）：见 writing.md
```

## 资料库维护

```powershell
world create --project-id <uuid> --name 世界观 --content <内容>
character create --project-id <uuid> --name 主角 --description <描述>
map create --project-id <uuid> --name 地图 --content <描述>
timeline create --project-id <uuid> --title 关键事件 --date <时间>
foreshadowing create --project-id <uuid> --title 伏笔A --content <埋设>
outline create --project-id <uuid> --title 大纲 --content <内容>
volume create --project-id <uuid> --name 第一卷
```

## 审计与记忆

```powershell
audit check --project <名或UUID>
memory stats --project-id <uuid>        # 记忆学习状态
extract status --project-id <uuid>      # 提取记录
```

## 导出与搜索

```powershell
export export <项目名或UUID> --output out.txt   # 导出全文
search <关键词> --project <名或UUID>
search --mode semantic <查询> --project <名或UUID>
```

## 破坏性操作纪律

- delete 类：先 list 确认 → `--force`（--json 模式必须）→ 事后 list 确认
- 涉及正式数据：先报告计划（清什么、保留什么）再执行；不擅自删项目
- 敏感凭据（key）全程 mask

## 常见问题排查

- 「项目不存在」类反馈：常见原因是 UUID 猜错（seed UUID 每表独立，用 `project list --json` 拿真实 id）、项目软删（回收站 `restore`）
- `chapter list` 必须显式 `--status`；`--json` 根级放子命令前
