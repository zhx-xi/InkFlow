/**
 * `e2e-rag-fake.spec.ts` RAG 状态就绪门契约（#1307 RED）。
 *
 * 背景（#1307 = #1295 同族潜伏）：
 *   tests/e2e/e2e-rag-fake.spec.ts:250-256（修前）
 *     await gotoNav(window, '设置');
 *     await window.getByTestId('settings-cat-models').click();
 *     await expect(window.getByTestId('rag-status-card')).toBeVisible({ timeout: 15_000 }); // :253
 *     await expect(window.getByTestId('rag-model-name')).toContainText('e2e-embed-test');   // :254
 *     await expect(window.getByTestId('rag-stale-banner')).toBeVisible();                   // :255 裸
 *     await expect(window.getByTestId('rag-reindex-btn')).toBeVisible();                    // :256 裸
 *
 * 与 #1295 逐字同形（issue 正文对照表）：
 *   门   = 等 `rag-status-card`——**#824 起该卡恒渲染**，对「status 已就绪」零判别力；
 *   裸断言 = 默认 5s 预算追异步 `fetchVectorStatus`；
 *   侥幸 = 兄弟用例靠先断 `rag-model-name`（:254）多赚一轮重试窗口。
 *
 * 根因（同 #1295，三态竞态非逻辑错）：
 *   RagStatusCard.tsx:17  `const [status, setStatus] = useState<VectorStatusDto | null>(null)`
 *   → 挂载后 status 恒 null，组件渲染 `rag-empty`（「加载中」，:156-159）；
 *   → `useEffect`（:25-40）异步 fetchVectorStatus 解析后才 `setStatus(data)`
 *     → `status.stale` 为真时才渲染 `rag-stale-banner`（:172-180）+ `rag-reindex-btn`（:181-189）。
 *   门等恒渲染卡片 → 立即放行 → 裸断言用默认 5s 追尚未解析的异步状态。
 *
 * 契约面（照抄 #1295，拒绝同族分叉）：
 *  A. 就绪门下沉到 `gotoNav`（导航唯一入口，一处修覆盖多调用点）；
 *  B. 状态就绪门 = `rag-empty` 消失（≡ status 解析落态）；
 *  C. `rag-stale-banner` / `rag-reindex-btn` 正向断言均带**显式预算**，禁裸 `toBeVisible()`。
 *
 * RED 形态：本文件断言 spec 源码满足 A/B/C；未修时 A/B/C 逐条 FAIL。
 * ⚠️ 本文件为**父侧契约**（spec 源码静态契约）。
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const SPEC_PATH = path.join(__dirname, 'e2e-rag-fake.spec.ts');
const SPEC_SRC = readFileSync(SPEC_PATH, 'utf8');

/**
 * 抽取所有指定 testid 的 **正向** toBeVisible 断言形态。
 * 返回每处断言是否带显式 timeout。
 *
 * ⚠️ 只收正向断言：`not.toBeVisible()`（负例）等的是「元素不该出现」，
 * 默认 5s 语义正确（负例不应被要求等待更久）。本正则用 `(?<!not\.)` 排除。
 *
 * ⚠️ 窗口限 40 字符且**禁跨 `;`**：testid 与 `toBeVisible` 之间只允许同一个
 * 语句内的调用链（如 `const banner = window.getByTestId('x');` + 下一行 expect）。
 * 无此约束时正则会把「`.click(); await expect(...toBeVisible())`」这种**下一条语句**
 * 误判成本 testid 的裸断言（本契约首版即踩中，:`256` 报出 2 处）。
 */
function findPositiveVisibleAssertions(
  src: string,
  testid: string,
): Array<{ hasTimeout: boolean; text: string }> {
  const out: Array<{ hasTimeout: boolean; text: string }> = [];
  const re = new RegExp(
    `getByTestId\\(['"]${testid}['"]\\)([^;]{0,120}?)\\.(?<!not\\.)toBeVisible\\(([^)]*)\\)`,
    'g',
  );
  let m: RegExpExecArray | null;
  while ((m = re.exec(src)) !== null) {
    out.push({ hasTimeout: /timeout\s*:/.test(m[2] ?? ''), text: m[0].replace(/\s+/g, ' ') });
  }
  return out;
}

describe('#1307 e2e-rag-fake RAG 状态就绪门（对齐 #1295）', () => {
  describe('A · 就绪门下沉：gotoNav 必须等渲染层出 boot gate', () => {
    it('spec 须 import awaitAppReady（与 #1227/#1295 同形）', () => {
      expect(SPEC_SRC).toMatch(
        /import\s*\{\s*awaitAppReady\s*\}\s*from\s*['"]\.\/e2e-app-ready['"]/,
      );
    });

    it('gotoNav 须下沉 awaitAppReady（一处修覆盖多调用点）', () => {
      const start = SPEC_SRC.indexOf('async function gotoNav(');
      expect(start).toBeGreaterThanOrEqual(0);
      const body = SPEC_SRC.slice(start, SPEC_SRC.indexOf('\n}', start));
      expect(body).toContain('awaitAppReady');
    });
  });

  describe('B · 状态就绪门：必须等 status 解析，而非恒渲染的 rag-status-card', () => {
    it('设置页模型分类段须等 `rag-empty` 消失（≡ status 解析落态）', () => {
      // #824 起 rag-status-card 恒渲染 → 它不构成「status 已就绪」判据。
      // RagStatusCard 四态互斥（:152-193）：!currentProjectId → rag-empty；
      //   !status → rag-empty（加载中）；status 已解析 → 三态之一（均无 rag-empty）。
      // 用例已先建项目（currentProjectId 已设）⇒ rag-empty 消失 ≡ status 解析完成。
      const waitsForStatusResolution =
        /rag-empty'\)\)\s*\.toHaveCount\(\s*0/.test(SPEC_SRC) ||
        /toPass\(/.test(SPEC_SRC) ||
        /waitForFunction/.test(SPEC_SRC);
      expect(
        waitsForStatusResolution,
        '设置页模型分类段缺少「rag-empty 消失」判据——门仍在等恒渲染的 rag-status-card（#1295 根因面）',
      ).toBe(true);
    });
  });

  describe('C · 显式预算：rag-* 正向断言禁裸 toBeVisible（默认 5s）', () => {
    it('每处 rag-stale-banner 正向断言均带显式 timeout', () => {
      const assertions = findPositiveVisibleAssertions(SPEC_SRC, 'rag-stale-banner');
      expect(assertions.length).toBeGreaterThanOrEqual(1);
      const bare = assertions.filter((a) => !a.hasTimeout);
      expect(
        bare.map((a) => a.text),
        '存在裸 toBeVisible（默认 5s）——CI 长跑退化下不足（#1307 :255 根因面）',
      ).toEqual([]);
    });

    it('每处 rag-reindex-btn 正向断言均带显式 timeout', () => {
      const assertions = findPositiveVisibleAssertions(SPEC_SRC, 'rag-reindex-btn');
      expect(assertions.length).toBeGreaterThanOrEqual(1);
      const bare = assertions.filter((a) => !a.hasTimeout);
      expect(
        bare.map((a) => a.text),
        '存在裸 toBeVisible（默认 5s）——CI 长跑退化下不足（#1307 :256 根因面）',
      ).toEqual([]);
    });
  });
});
