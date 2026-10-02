/*
 * design/GUI/_tools/shot-book-token-scope-1431.cjs — book 页原型截图 + 断言（#1431）
 *
 * 用途：BookRunPanel 把 token 用量拆成「本轮」（run-counter-tokens-run，累计 − reset 基线）
 * 与「累计」（run-counter-tokens，plan.limits 账单、reset 不清零）两行后，重出 book 页原型简图，
 * 并对「两值并存且可辨」「累计告警（run-token-warning）门控 + 文案点名累计」「无横向滚动」
 * 做计算样式/文本断言（视觉模型不可用时的主验证手段）。
 *
 * 覆盖状态：running / completed / failed / degraded / degraded-expanded / reset-confirm
 *           + overwrite-notice（#1440 既有）+ token-warn（#1431 新增：累计超限告警可见）
 *
 * 用法：node design/GUI/_tools/shot-book-token-scope-1431.cjs
 * 路径自解析（ROOT / playwright 均从脚本位置推导），见 _shared.cjs。
 */
const path = require('path');
const { assertGuiRoot, requirePlaywright, assertPageDir } = require('./_shared.cjs');

const ROOT = assertGuiRoot();
const chromium = requirePlaywright();
const PAGE_DIR = assertPageDir('book', ROOT);
const PAGE_FILE = 'book/book-run.html';

/** 既有状态 + #1431 新增 token-warn 态 */
const STATES = [
  'running',
  'completed',
  'failed',
  'degraded',
  'degraded-expanded',
  'reset-confirm',
  'overwrite-notice',
  'token-warn',
];

/** 计算样式/文本断言（返回失败标签数组） */
async function runChecks(page, state) {
  const fails = [];
  const push = (label, ok) => {
    if (!ok) fails.push(label);
  };
  const d = await page.evaluate(() => {
    const el = (sel) => document.querySelector(sel);
    const disp = (sel) => (el(sel) ? getComputedStyle(el(sel)).display : 'MISSING');
    const run = el('[data-testid="run-counter-tokens-run"]');
    const tot = el('[data-testid="run-counter-tokens"]');
    const warn = el('[data-testid="run-token-warning"]');
    return {
      runVisible: !!run && run.offsetParent !== null,
      totVisible: !!tot && tot.offsetParent !== null,
      runText: run ? run.textContent.trim() : '',
      totText: tot ? tot.textContent.trim() : '',
      warnDisplay: disp('[data-testid="run-token-warning"]'),
      warnText: warn ? warn.textContent.trim() : '',
      panelDisplay: disp('[data-testid="book-run-panel"]'),
      demoBarDisplay: disp('.demo-bar'),
      scrollW: document.documentElement.scrollWidth,
      innerW: window.innerWidth,
    };
  });

  // 面板与 demo-bar 恒不可见（截图纯净）
  push('book-run-panel visible', d.panelDisplay !== 'none' && d.panelDisplay !== 'MISSING');
  push('demo-bar hidden in shot', d.demoBarDisplay === 'none');
  push('no horizontal scroll', d.scrollW <= d.innerW);

  // #1431：本轮 / 累计 两值并存、均可见、文本非空且互不相同
  push(`${state}: run-counter-tokens-run visible`, d.runVisible);
  push(`${state}: run-counter-tokens visible`, d.totVisible);
  push(`${state}: 本轮 token 文本非空`, d.runText.length > 0);
  push(`${state}: 累计 token 文本非空`, d.totText.length > 0);
  push(`${state}: 两值文本可辨（本轮 ≠ 累计）`, d.runText !== d.totText);

  // #1431：累计告警仅 token-warn 态可见，且文案点名「累计」
  if (state === 'token-warn') {
    push('token-warn: run-token-warning visible', d.warnDisplay !== 'none' && d.warnDisplay !== 'MISSING');
    push('token-warn: warning text contains 累计', d.warnText.includes('累计'));
  } else {
    push(`${state}: run-token-warning display:none`, d.warnDisplay === 'none');
  }
  return fails;
}

(async () => {
  const browser = await chromium.launch();
  // 与既有 book-run-*.png（900x792）同视口，保证图集可比
  const ctx = await browser.newContext({ viewport: { width: 900, height: 792 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  const url = 'file:///' + path.join(ROOT, PAGE_FILE).replace(/\\/g, '/');
  await page.goto(url);
  // 截图纯净：隐藏 demo-bar（原型无 data-shot 规则，直接摘除）
  await page.evaluate(() => {
    const bar = document.querySelector('.demo-bar');
    if (bar) bar.style.display = 'none';
  });

  let totalFails = 0;
  for (const state of STATES) {
    await page.evaluate((s) => setState(s), state);
    await page.waitForTimeout(300);
    const shotPath = path.join(PAGE_DIR, `book-run-${state}.png`);
    await page.screenshot({ path: shotPath });
    const fails = await runChecks(page, state);
    if (fails.length) {
      totalFails += fails.length;
      console.log(`[book-run-${state}] FAIL: ${fails.join(' | ')}`);
    } else {
      console.log(`[book-run-${state}] OK -> ${shotPath}`);
    }
  }
  await browser.close();
  console.log(totalFails ? `TOTAL FAILS: ${totalFails}` : 'ALL PASS');
  process.exit(totalFails ? 1 : 0);
})().catch((e) => {
  console.error('SCRIPT ERROR:', e);
  process.exit(2);
});
