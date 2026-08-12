# 版本核对与冒烟检查（workflows-post-release.md）

拿到 InkFlow 新版本（正式版/rc）产物后，确认其可用性的通用流程：版本核对 → 独立环境冒烟 → 判定。完整功能验证（场景 A-D）见 workflows-pre-release.md。

## 版本核对

1. CLI 版本：`inkflow --version` 输出 = 期望 tag（打包产物显示 tag 版本；开发版显示 pyproject 版本，不做版本判据）
2. 内核版本：启动后 `inkflow kernel status`（或 `GET /health` 带 X-InkFlow-Token）→ version 一致
3. 发布元数据（可访问时）：核对 tag、prerelease 标记、资产清单（名称/体积，以 release 资产实际命名为准）

## 冒烟命令链

在独立数据目录（`%APPDATA%` 或 `INKFLOW_DATA_DIR` 指向临时目录，全新 DB）按序执行：

```powershell
project list --json                        # 基础命令可用
project create --name smoke --json         # 创建返回非空 UUID
chapter create --project-id <uuid> --title 第一章 --content <≥50字> --json
chapter list --project-id <uuid> --status draft
memory stats --project-id <uuid>
extract status --project-id <uuid>
export export <项目名或UUID> --output out.txt
search <关键词> --project <名或UUID>
```

写作链路需要 LLM key：`llm set-key --provider deepseek --key sk-...`（全程 mask）。

## 判定标准

- 每条命令 `--json` 返回 `"ok":true`；create 返回非空 UUID；list 能回读刚建条目；导出文件非空
- 任一步失败 → 记录完整输出（命令 + exit code + 实际输出）作为缺陷证据，按缺陷报告格式提交（版本、复现命令、实际输出）

## 版本敏感点

- 产物 URL/tag 判据随版本更新（以 release 资产实际命名为准）
- 冒烟链之外的完整功能验证：见 workflows-pre-release.md（场景 A-D）
