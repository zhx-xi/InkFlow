# 项目记忆（memory.md）

agent 使用：项目记忆学习记录的读取与删除。GUI 对应：F28 项目记忆（写作页 Agent 链的记忆学习；GUI 无独立管理页，CLI 是管理入口）。

## 命令速查

| 命令 | 必选参数 | 可选/易错 | 说明 |
|---|---|---|---|
| `memory list` | `--project-id` | `--category`(addressing\|style_word\|structure\|other) | 已学偏好列表 |
| `memory remove` | 位置参数 `preference-id` | — | 删偏好 |
| `memory stats` | `--project-id` | — | 记忆学习统计 |

## 易错点

- `memory remove` 的 id 是位置参数
- memory 无手工添加/修改（#251 P3 候选）——CLI 只能读/删，写入靠写作链路的记忆学习
- `memory stats` 存在已知缺陷（#249：API 500 traceback「list 无 event_type」）——遇 5xx 先看内核 stderr（`serve --port 0` 前台 + `-RedirectStandardError`）
