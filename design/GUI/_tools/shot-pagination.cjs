/* #1314 分页条原型断言：library / search / sessions 三页的 .pager 结构与文案。
 *
 * 用法: node design/GUI/_tools/shot-pagination.cjs
 * 背景：#1300/#1314 给三页加了分页条，但原型的既有截图脚本
 *   （shot-characters-pagination.cjs 只覆盖 characters）不覆盖这三页；
 *   且 sessions 列表 10 条撑满视口时分页条落在折叠线以下，截图不可见
 *   → 用结构断言做主验证（同 shot-770 的「视觉模型不可用时主验证」思路）。
 *
 * 路径自解析（ROOT / playwright 均从脚本位置推导），见 _shared.cjs。
 */
const path = require('path');
const { assertGuiRoot, requirePlaywright } = require('./_shared.cjs');

const ROOT = assertGuiRoot();
const chromium = requirePlaywright();

const PAGES = [
  { name: 'library', file: 'library/library.html', prefix: 'library-page', expectInfo: '第 1 / 1 页 · 共 6 条' },
  { name: 'search', file: 'search/search.html', prefix: 'search-page', expectInfo: '第 1 / 1 页 · 共 5 条' },
  { name: 'sessions', file: 'sessions/sessions.html', prefix: 'sessions-page', expectInfo: '第 1 / 1 页 · 共 10 条' },
];

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  let fails = 0;

  for (const p of PAGES) {
    const url = 'file://' + path.join(ROOT, p.file).replace(/\\/g, '/');
    await page.goto(url);
    const d = await page.evaluate((prefix) => {
      const q = (s) => document.querySelector(s);
      const pager = q(`[data-testid="${prefix}"]`);
      if (!pager) return { found: false };
      const info = pager.querySelector(`[data-testid="${prefix}-info"]`);
      const prev = pager.querySelector(`[data-testid="${prefix}-prev"]`);
      const next = pager.querySelector(`[data-testid="${prefix}-next"]`);
      const sel = pager.querySelector(`[data-testid="${prefix}-size-select"]`);
      return {
        found: true,
        display: getComputedStyle(pager).display,
        info: info && info.textContent.trim(),
        prevDisabled: prev && prev.disabled,
        nextDisabled: next && next.disabled,
        hasSizeSelect: !!sel,
        scrollW: document.documentElement.scrollWidth,
        innerW: window.innerWidth,
      };
    }, p.prefix);

    const fail = [];
    const chk = (label, cond) => { if (!cond) fail.push(label); };
    chk('pager 存在', d.found);
    if (d.found) {
      chk('display≠none', d.display !== 'none');
      chk(`info="${p.expectInfo}"`, d.info === p.expectInfo);
      chk('prev 禁用（单页）', d.prevDisabled === true);
      chk('next 禁用（单页）', d.nextDisabled === true);
      chk('有每页条数 Select', d.hasSizeSelect);
      chk('无横向溢出', d.scrollW <= d.innerW);
    }

    console.log(`[${p.name}] ${fail.length === 0 ? 'OK' : 'FAIL'}`);
    if (fail.length) {
      console.log(`   INFO: ${JSON.stringify(d)}`);
      fail.forEach((f) => console.log(`   x ${f}`));
      fails += fail.length;
    }
  }

  await browser.close();
  console.log(fails === 0 ? 'ALL PASS' : `${fails} FAILURE(S)`);
  process.exit(fails === 0 ? 0 : 1);
})();
