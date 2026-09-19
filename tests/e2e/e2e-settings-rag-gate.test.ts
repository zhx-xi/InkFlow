/**
 * `e2e-settings-rag.spec.ts` RAG 状态就绪门契约（#1295 RED）。
 *
 * 背景（#1295 CI 实证，run 35371922814 attempt1 job 105687727064）：
 *   tests/e2e/e2e-settings-rag.spec.ts:299
 *   rag_stale_persists_across_restart：stale（unknown）跨重启保留
 *     await openRagStatus(first.window);
 *   > await expect(first.window.getByTestId('rag-stale-banner')).toBeVisible();
 *                                     ^  Timeout: 5000ms / element(s) not found
 *   Retry #1 同样红。35 passed / 1 failed (8.4m)。
 *
 * 根因（三态竞态，非逻辑错）：
 *   RagStatusCard.tsx:17  `const [status, setStatus] = useState<VectorStatusDto | null>(null)`
 *   → 挂载后 status 恒为 null，组件渲染 `rag-empty`（「加载中」，:156-159）；
 *   → `useEffect`（:25-40）异步 fetchVectorStatus 解析后才 `setStatus(data)`
 *     → `status.stale` 为真时才渲染 `rag-stale-banner`（:172-180）。
 *   而 `openRagStatus` 的门（:189）等的是 `rag-status-card`——**#824 起该卡片恒渲染**
 *   （RagStatusCard.tsx:112-117），故该门对「status 已就绪」零判别力：
 *   卡片在 status===null 时就可见 → 门立即放行 → 裸 `toBeVisible()` 用
 *   **Playwright 默认 5s 预算**去追一个尚未解析的异步状态。
 *
 *   同文件同形兄弟用例（CI 同 run 内）对照：
 *     :199 rag_unknown_shows_stale_banner  13.4s  passed（先断 rag-model-name，给了额外时间）
 *     :253 rag_no_embedding_shows_hint     18.7s  passed
 *     :281 rag_stale_persists_across_restart 20.1s FAILED（唯一首个断言即裸断言横幅）
 *   → 竞争同一异步解析：谁先赢取决于调度，故为 flake（近 30 次 main run ≈3.5%）。
 *
 * 契约面（照抄 #1227/#1229/#1283 的既有整治模式，不新造）：
 *  A. 就绪门必须**下沉到 `openRagStatus`**（RAG 区块唯一入口）——
 *     与 e2e-settings.spec.ts:94-97 的 `gotoNav` 下沉 `awaitAppReady` 同形；
 *  B. `openRagStatus` 的门必须等**status 解析完成**（三态之一出现），
 *     而非等恒渲染的 `rag-status-card`；
 *  C. `rag-stale-banner` 断言必须带**显式预算**，禁裸 `toBeVisible()`
 *     （默认 5s 在 CI 长跑退化下不足——对齐 #1239/#1257/#1283 的「显式预算」手法）。
 *
 * RED 形态：本文件断言 spec 源码满足 A/B/C；未修时 A/B/C 逐条 FAIL。
 * ⚠️ 本文件为**父侧契约**（spec 源码静态契约 + 就绪门行为契约）。
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const SPEC_PATH = path.join(__dirname, 'e2e-settings-rag.spec.ts');
const SPEC_SRC = readFileSync(SPEC_PATH, 'utf8');

/** 抽取 `openRagStatus` 函数体（源码契约用）。 */
function extractOpenRagStatusBody(src: string): string {
  const start = src.indexOf('async function openRagStatus(');
  expect(start).toBeGreaterThanOrEqual(0);
  const end = src.indexOf('\n}', start);
  expect(end).toBeGreaterThan(start);
  return src.slice(start, end);
}

/**
 * 抽取所有 `rag-stale-banner` 的 **正向** toBeVisible 断言形态。
 * 返回每处断言是否带显式 timeout。
 *
 * ⚠️ 只收正向断言：`not.toBeVisible()`（负例，:271 `rag_no_embedding_shows_hint`）
 * 等「元素不该出现」的形态**不适用显式预算**——它等的是「不出现」，
 * 默认 5s 语义正确（负例不应被要求等待更久）。本正则用 `(?<!not\.)` 排除。
 */
function findStaleBannerAssertions(src: string): Array<{ hasTimeout: boolean; text: string }> {
  const out: Array<{ hasTimeout: boolean; text: string }> = [];
  const re = /getByTestId\(['"]rag-stale-banner['"]\)[\s\S]{0,120}?\.(?<!not\.)toBeVisible\(([^)]*)\)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(src)) !== null) {
    out.push({ hasTimeout: /timeout\s*:/.test(m[1] ?? ''), text: m[0].replace(/\s+/g, ' ') });
  }
  return out;
}

describe('#1295 rag-stale-banner 跨重启可见性 flake 整治（RAG 状态就绪门）', () => {
  describe('A · 就绪门下沉：openRagStatus 必须等渲染层出 boot gate', () => {
    it('spec 须 import awaitAppReady（与 #1227/#1283 同形）', () => {
      expect(SPEC_SRC).toMatch(/import\s*\{\s*awaitAppReady\s*\}\s*from\s*['"]\.\/e2e-app-ready['"]/);
    });

    it('openRagStatus 须经就绪门（自身调用或经 gotoNav 下沉，二者其一）', () => {
      const body = extractOpenRagStatusBody(SPEC_SRC);
      // 门可下沉在 gotoNav（#1227 形态，一处修多调用点）——此时 openRagStatus 经
      // gotoNav 间接受门保护。两处至少一处在（且 gotoNav 那处由下一条测试单独钉住）。
      const direct = body.includes('awaitAppReady');
      const viaGotoNav = body.includes('gotoNav(');
      expect(direct || viaGotoNav).toBe(true);
      expect(viaGotoNav, 'openRagStatus 须走 gotoNav（导航唯一入口）').toBe(true);
    });

    it('gotoNav 须下沉 awaitAppReady（覆盖第二程等多调用点）', () => {
      const start = SPEC_SRC.indexOf('async function gotoNav(');
      expect(start).toBeGreaterThanOrEqual(0);
      const body = SPEC_SRC.slice(start, SPEC_SRC.indexOf('\n}', start));
      expect(body).toContain('awaitAppReady');
    });
  });

  describe('B · 状态就绪门：必须等 status 解析，而非恒渲染的 rag-status-card', () => {
    it('openRagStatus 须等待状态三态之一（stale 横幅 / no-embedding / fresh 文案）', () => {
      const body = extractOpenRagStatusBody(SPEC_SRC);
      // #824 起 rag-status-card 恒渲染 → 它不构成「status 已就绪」判据
      const waitsForStatusResolution =
        /rag-stale-banner|rag-no-embedding|rag-empty/.test(body) ||
        /toPass\(/.test(body) ||
        /waitForFunction/.test(body);
      expect(waitsForStatusResolution).toBe(true);
    });
  });

  describe('C · 显式预算：rag-stale-banner 断言禁裸 toBeVisible（默认 5s）', () => {
    it('每处 rag-stale-banner 的 toBeVisible 均带显式 timeout', () => {
      const assertions = findStaleBannerAssertions(SPEC_SRC);
      expect(assertions.length).toBeGreaterThanOrEqual(2); // 首程 + 第二程各一处
      const bare = assertions.filter((a) => !a.hasTimeout);
      expect(
        bare.map((a) => a.text),
        '存在裸 toBeVisible（默认 5s）——CI 长跑退化下不足（#1295 根因面）',
      ).toEqual([]);
    });
  });
});
