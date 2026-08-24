# InkFlow 测试断言质量基线（#524 登记）

> 日期：2026-08-20；来源：issue #524「测试断言有效性审计——P0 无效断言清零 + P1 错误面补 body 断言 + P2 前端补强 + 扫描器固化」。
> 本文登记修复后测试套件的断言质量基线，并说明前端弱断言候选扫描器（ci_cd/scan_front_v3.py）的定位与用法。

## 1. 审计结论摘要

2026-08-20 三层审计（后端单元 227 文件 ~8.9 万行 + 集成/API/CLI 97 文件 ~3.9 万行 + 前端 Vitest ~90 文件 + E2E），判定标准 = 「修改被测逻辑后测试仍绿 = 无效/弱断言」：

| 层 | 发现 | 处置 |
|---|---|---|
| 后端单元 | 18 处真弱断言（8 处集中在 test_agent_relations.py 同一「纯校验合法路径」模式；其余为防御分支 noop / 恒真 assert True / 自引用字数 / force 无返回锚定 / list_recent 无排序断言 / 字数自引用） | P0 清零（#524 合入后） |
| 集成/API/CLI | 17 处实质发现：test_agent_api.py 前 7 用例整文件 mock 回显（最严重）；test_book_repository.py 2 处 update noop；错误面 ~26 处仅锁状态码不锁 body；CLI 2 处仅 exit code | P0 + P1 清零 |
| 前端 | 102 个扫描器命中块人工复核：98 个实际有效（扫描器误报），4 处可加强 | P2 补强 4 处 + **扫描器修复** |
| E2E | 4 测试无问题（真实 LLM 连通性冒烟，宽松断言符合 ADR-026 设计意图） | 不动 |

## 2. 修复后基线（#524 合入后）

- **P0 完全无效断言：0**（每处修后「故意改坏被测逻辑 → 测试变红」实证 ≥2 处入 PR body）
- **P1 错误面 body 断言：全覆盖**（404/409/422/401 均锁 detail/body；DELETE 204 锁 assert_awaited；CLI 锁 stderr 文案）
- **P2 前端 4 处补强**：main.tray.test.ts 时序冒烟 + dismiss 副作用、main.window-controls.test.ts catch 分支失败计数、BookPlannerPanel.test.tsx Times(1)
- **覆盖率门禁不变**：backend line ≥98.5% / branch ≥95%、前端 vitest thresholds（门禁只证明行被执行，断言有效性由本审计 + 候选扫描器持续看护）

## 3. 前端弱断言候选扫描器（ci_cd/scan_front_v3.py）

### 3.1 定位

**CI 弱断言候选提示器（非门禁）**——输出「只有弱断言、无强断言、无守卫」的 test/it 块清单供人工复核；**不阻断 CI**（弱断言 ≠ 必然无效，如「否定路径守卫」「纯函数布尔返回值契约」需人读源码判定）。

### 3.2 v3 → v4 修复（#524 审计实证，102 命中里 98 个实际有效）

1. **STRONG 正则嵌套括号误报**：v3 `expect\([^)]*\)\.` 无法匹配参数含嵌套括号的断言（`expect(useAgentStore.getState().config.x).toBe(...)` 在 `getState()` 的 `)` 截断 → 强断言被漏判）。v4 用括号平衡正则 `expect\((?:(?:[^()]|\((?:[^()]|\([^()]*\))*\))*)\)` 容忍多层嵌套。
2. **`toBe` 分类修正**：v3 把一切 `toBe` 计入弱。v4 只有 `toBe(null|undefined|true|false)` 计弱（存在性/布尔标志），`toBe('具体值')` / `toBe(8)` / `toBe(SENTINEL)` / `toBe(表达式)` 计强。
3. **否定守卫归类**：`not.toHaveBeenCalled()` 否定路径（未配置→不发请求、Escape 取消等防副作用契约）从弱断言拆出为 **守卫块（类型 4，有效）**，单独输出不计弱。
4. **`toHaveBeenCalledTimes(N)` 归强**：带数字参数 = 次数锚定（强）；仅 `toHaveBeenCalled()` / `toHaveBeenCalledTimes()` 无参计弱。

### 3.3 运行方式

```powershell
# 仓库根（自动定位 frontend/packages/*/src 下 *.test.*）
python ci_cd/scan_front_v3.py
```

输出三段：弱候选块总数 + 按文件分布 + 明细（文件 / 测试名 / 弱 matcher）；守卫块独立清单。预期基线（#524 合入后，2026-08-20 实测）：**弱候选 ~60 块、守卫块 ~17 块**（v3 未修复时为 102 弱块无守卫区分）。

### 3.4 使用约定

- 弱候选命中 → 人工复核（读源码判定：否定守卫 / 纯函数布尔返回值 / toBe 表达式透传 属有效；仅状态码无 body、仅调用无效果 属真弱）→ 真弱修测试（参照 #524 P0/P1 手法）
- 新增测试提交前可选择性跑扫描器自查；命中数显著上升（> 基线 +50%）→ 建议评审
- **禁止**将该脚本改为 CI 门禁（弱断言判定需人工语境判断，机械门禁会产生虚假告警/虚假安全感）

## 4. 审计报告归档

- [单元层报告](assert-audit-report-unit-2026-08-20.md)（backend/tests/unit 227 文件）
- [集成/API/CLI 层报告](assert-audit-report-integration-2026-08-20.md)（tests/api + cli + integration 97 文件）
- [前端层报告](assert-audit-report-frontend-2026-08-20.md)（85+ 测试文件，102 命中逐块复核）

原始扫描产物：`.tmp/assert-scan/`（开发机本地，不入库）。
