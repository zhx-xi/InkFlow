# 章节与卷（chapters.md）

agent 使用：章节/卷的 CRUD。GUI 对应：`/writing` 卷章树 + 编辑器（章节 CRUD 走本域）。

## 命令速查

| 命令 | 必选参数 | 可选/易错 | 说明 |
|---|---|---|---|
| `chapter create` | `--project-id/-p`(UUID) `--title/-t` | `--volume-id/-v` `--content/-c` | ⚠️ 非法 UUID → ValueError → **DB_ERROR 信封**（不是 NOT_FOUND）；创建成功返回完整章节（含 id） |
| `chapter list` | `--project-id` | `--volume-id` `--status` | ⚠️ **无默认状态过滤**：不传 status = 全量；`--status draft` 才过滤；非法 status → DB_ERROR 信封 |
| `chapter get` | `--id` | — | 返回章节全文 + word_count + status_history |
| `chapter update` | `--id` | `--title` `--content` `--status` | 改正文/标题/状态 |
| `chapter move` | `--id` | `--to-volume` | 移卷 |
| `chapter delete` | `--id` | `--force` | 软删（无 restore 命令，恢复经 GUI 或 API） |
| `volume create` | `--project-id` `--title` | `--order` | 建卷 |
| `volume list` | `--project-id` | — | 列卷 |
| `volume delete` | `--id` | `--force` | 其下章节变未分类（volume 无 update/restore，#251 P3） |

## 易错点

- 第一个章节 seed UUID = `00000000-0000-0000-0000-000000000001`（每表独立，不是 002！）；正确取法 = `chapter list --project-id <uuid> --status draft --json`
- `--content` 直接传中文在 PowerShell 内联有 GBK 风险——长内容用 write_file 写 UTF-8 文件再 `Get-Content -Raw -Encoding UTF8` 读入传参
- word_count 按字符计（44 字章节 → word_count 44，2026-08-11 记录）
- **写作链路前置**：章节 content 需 ≥ 50 字符（`write continue` 的 existing_content 业务校验，不满足 → 422）——生成/续写前先 `chapter update` 加长
