# #1358 取证结论：map_pin 节点数「6/10」的根因判定

**结论：非缺陷。** `scope="related"`（前端缺省）下未参与关系的 `map_pin` 不上图，是
`specs/f48-knowledge-graph/spec.md` §5.2（v1.4 / #1325 拍板）明文规定的**设计语义**；
`scope="all"` 下采集链路返回**真实全量 10/10**，无丢失。

本目录两个探针脚本在**真实 SQLite + 真实仓储**上复现并证伪 issue 全部 5 个怀疑方向。

复现命令（worktree 根）：

```
cd backend
.\.venv\Scripts\python.exe ..\docs\evidence\1358-map-pin-scope\probe-exclusions.py
.\.venv\Scripts\python.exe ..\docs\evidence\1358-map-pin-scope\probe-usability.py
```

---

## 1. 采集链路本身正确（真实 DB 取证）

`probe-exclusions.py` —— 3 张地图（全局图 `root_location_id=NULL` / 根地点图 / 子图
`parent_map_id` 指向全局图）× 10 个 pin，真实 `SQLiteMapRepository`：

```
── 方向 1：list_maps_by_project 是否排除某些 map ──
  返回 3 张（期望 3）: ['全局图', '子图', '根地点图']

── 方向 1b：地图形态是否影响 pin 遍历 ──
  全局图: 4 pins
  根地点图: 3 pins
  子图: 3 pins

── 方向 5：id 语义 —— pin.id 与节点 id 是否一致 ──
  scope=all map_pin=10  期望=10
  缺失: []
  节点 id 样例: map_pin:00000000-0000-0000-0000-0000000dbc69  entity_id=00000000-...dbc69

── 方向 2：端点在节点集的边 —— 参与关系的 pin 边是否保留 ──
  scope=all edges=2（期望 2）
    character:...dbbab -> map_pin:...dbc69
    character:...dbbab -> map_pin:...dbc6a

── 方向 3/4：去重 / 软删 ──
  map_pins 无 is_deleted 列（真删语义，见 models/map.py:77）
  maps 无 is_deleted 列（真删语义，见 models/map.py:22）

── 关键对照 ──
  scope=all     → map_pin=10/10  (edges=2)
  scope=related → map_pin=2/10   (edges=2)
```

## 2. issue §5 五个怀疑方向逐项证伪

| # | issue 怀疑 | 实证结论 |
|---|---|---|
| ① | `list_maps_by_project` 过滤了某些 map | ❌ **证伪** —— 全局/根地点/子图三种形态**全部返回**，各带 pin 4/3/3 |
| ② | pin 的 source 实体被过滤 → 边被当孤立边误杀 | ❌ **证伪** —— 参与关系的 2 条 `character→map_pin` 边**全保留** |
| ③ | dedupe / 去重逻辑误杀 | ❌ **证伪** —— `#495` 后单表读取，**无去重逻辑**（spec §5.2「去重: —」） |
| ④ | map 权限 / 软删过滤 | ❌ **证伪** —— `maps` / `map_pins` **均无 `is_deleted` 列**（真删语义） |
| ⑤ | id 语义不一致（pin 引用的 entity id vs 节点 id） | ❌ **证伪** —— `GraphNode.id` = `map_pin:<pin.id>`，`entity_id` = `pin.id`，与关系表 `target_id` **完全一致** |

## 3. 唯一成因：`scope="related"` 收窄（前端缺省值）

```
service 层 graph()（knowledge_graph_service.py:470-481）：
  scope="related" → related_ids = {n.id for n in nodes if n.id in edge_pairs}
                    nodes = [n for n in nodes if n.id in related_ids]  # 无关系时回退角色全集
```

`map_pin` 的节点 id 形如 `map_pin:<pin_uuid>`。pin 若不参与任何 `knowledge_relations`，
其 id 不在 `edge_pairs` 中 → 被整类排除。

前端缺省即 `related`（`frontend/.../api/knowledge-graph.ts:86` `scope: GraphScope = 'related'`）。

## 4. related 语义**可用性自洽**（两条路径都通）

`probe-usability.py`：

```
── 初始态（无任何关系）──
  [初始] scope=related  总节点=  1 map_pin= 0 edges=0     ← 回退角色全集（spec §5.2 明文）
  [初始] scope=all      总节点= 11 map_pin=10 edges=0

── 路径 (a)：经 create_relation 建 character -> map_pin ──
  create_relation 成功: 00000000-0000-0000-0000-000000000001
  [建 1 条关系后] scope=related  总节点=  2 map_pin= 1 edges=1   ← pin 立即可见
  [建 1 条关系后] scope=all      总节点= 11 map_pin=10 edges=1

── 路径 (b)：scope=all 开关 ──
  scope=all map_pin=10/10
```

- **路径 (a)**：图谱页拉线建 `character → map_pin` 关系 → pin 立即上图（related 生效）。
- **路径 (b)**：工具栏「显示全部实体」开关（`library-kg-scope-all`）切 `scope=all` → 10/10。

两条路径均由 spec 明文承接：
`specs/f19-gui/knowledge.md:37`（节点集范围 + 开关）、`:80` 验收 N7。

## 5. 与 #1325 实测「map_pin 6/10」的关系

*#1325 的 6/10 实测发生在 rc4（`a46ed4c9`），当时 **`scope` 语义尚未引入***，
图谱是「六类全量」语义。该版本源码：

- `git show a46ed4c9:.../map_repo.py` → `list_maps_by_project` / `list_pins` **均为全量不分页**
- `git show c28e60aa~1:.../knowledge_graph_service.py` → `_collect_map_pin_nodes`
  与 #1325 修复后**逐字相同**（本 PR 未改动该方法）

⇒ 全量语义下该链路应输出 **10/10**，#1325 的「6/10」**无法由任何源码路径复现**——
最可能源于该会话只读模拟脚本的统计口径（`count(表)` vs `count(图谱节点)` 对比口径），
但那脚本**未随 PR 落库**（`gh pr view 1357 --json files` 无取证脚本），**不可复现**，
故不作为可归因缺陷。

本 issue 观察到的现象（related 下 2/10、4/10、0/10 等）与「6/10」**同族**：
皆为「未参与关系的 pin 被 related 排除」，数字随参与关系的 pin 数变化。

## 6. 判定

| 项 | 判定 |
|---|---|
| 采集链路（`_collect_map_pin_nodes` / `list_maps_by_project` / `list_pins`） | ✅ **无缺陷**（`scope=all` = 10/10 真实全量） |
| `scope=related` 排除未参与关系的 map_pin | ✅ **设计使然**（spec §5.2 明文 + §f19-gui N7 已验收） |
| issue #1358 定性「map_pin 节点数不足」 | ❌ **定性不成立**（`all` 视图无缺失） |

按任务书 §9「发现是设计使然（非缺陷）→ 停并报告（可能需要改 issue 定性）」。
