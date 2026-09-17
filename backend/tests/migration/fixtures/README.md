# 发布版 DB snapshot fixtures（#1005 迁移升级回归）

每个目录 = 一个**已合入正式版**的真实落盘 DB 归档，供 `migration-upgrade-backend`
CI job（`tests/migration/test_released_db_upgrade.py`）做「旧库 → 最新代码 lifespan
全链 → 语义可用」回归。

## 目录约定

```
fixtures/
  v0.14.0/
    inkflow.db      # 该版本代码真实启动 + 写入代表性数据后的单文件 DB（journal_mode=delete）
    MANIFEST.json   # {version, git_tag, generated_at, sha256, size_bytes,
                    #  tables: {表: 行数}, journal_mode}
```

- 测试对全部版本目录**参数化**——旧版本 fixture **永久保留**（跨多版本升级路径回归），
  不随版本演进删除。
- MANIFEST 的 sha256 是完整性锚（测试 M1 对账）；`tables` 行数是数据保全锚（M3 对账）。
- 关系表断言随当前 ORM 形态自动切换（`character_relations` 在 ORM → 原样保留断言；
  不在（#495 合并后）→ 断言行迁入 `knowledge_relations` character↔character 子空间）。

## 新版本归档流程（每个正式版发布后执行）

1. `git worktree add --detach <路径> v<X.Y.Z>` + `cd backend; uv sync --frozen --extra dev`
2. 设 `INKFLOW_DATA_DIR=<临时目录>`，用**该 tag 的代码**跑完整 `app.lifespan`
   （建 schema + ensure 链 + seed builtin providers/agents/skills）
3. 经该版本 repo/ORM 层写代表性业务数据（规划基线见 v0.14.0 生成脚本；至少覆盖：
   2 项目（跨项目隔离）/ 角色+分组+关系 / 卷+章节（带正文）/ 大纲 / 世界观 /
   时间线 / 伏笔）
4. 收尾单文件化：`PRAGMA wal_checkpoint(TRUNCATE)` → `journal_mode=DELETE` → `VACUUM`；
   确认无 `-wal`/`-shm` 残留
5. 拷入 `fixtures/v<X.Y.Z>/`，生成 MANIFEST.json（sha256/size/全表行数）
6. `git add -f`（.gitignore 已有 fixtures 例外，正常 add 即可）+ 本地跑
   `uv run pytest tests/migration/ -v` 确认新 fixture 升级回归全绿再提交

## 红线

- fixture 必须由**对应 tag 的真实代码**生成（不许手工 SQL 拼旧库——那是
  `test_database_migration_chain.py` 合成旧库的职责；本 fixture 的价值恰在
  「真实发布版落盘形态」，含 seed 数据与真实列集）。
- 禁止把含真实用户数据的 DB 检入仓库（生成时用隔离 INKFLOW_DATA_DIR + 虚构业务数据）。
- 修改已归档 fixture = 破坏 sha256 对账（M1 红）；确需重生成时同步更新 MANIFEST
  并在 PR 说明原因。

## 版本清单

| 版本 | 归档日期 | 说明 |
|------|----------|------|
| v0.14.0 | 2026-09-17 | 首个归档（#1005 落地批）；含 character_relations 双轨数据（#495 前形态） |
