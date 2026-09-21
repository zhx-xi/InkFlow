/* #1320 characters 原型截图 + 断言：主态分页条 / 分览态 total 随筛选重算。
 * 用法: node shot-1320.cjs
 * playwright 复用 electron 包内依赖（与 _tools/shot-770.cjs 同款）。
 */
const path = require('path');
const { chromium } = require('D:/develop/projects/InkFlow-ft/w22-1320/frontend/packages/electron/node_modules/@playwright/test');

const ROOT = 'D:/develop/projects/InkFlow-ft/w22-1320/design/GUI';
const PAGE = { file: 'characters/characters.html', states: ['main', 'rank-protagonist'] };

async function checks(page, state) {
  const fails = [];
  const push = (label, ok) => { if (!ok) fails.push(label); };
  const d = await page.evaluate(() => {
    const q = (sel) => document.querySelector(sel);
    const cs = (sel) => (q(sel) ? getComputedStyle(q(sel)).display : 'MISSING');
    // ⚠️ 原型里 .page-lib 主容器与 pager 组件**共用** data-testid="library-page"（既有约定，
    //    #1320 不改动）；且主态/分览态各有一个 .app-main（分览块与主态同构）
    //    → 必须按「哪个 .app 容器」精确归类，不能只按 testid 或 .app-main 计数。
    const pagerIn = (appSel) =>
      Array.from(document.querySelectorAll(appSel)).map((app) => {
        const host = app.querySelector('.page-lib');
        const el = host && host.querySelector('.pager[data-testid="library-page"]');
        if (!el) return null;
        const info = el.querySelector('[data-testid="library-page-info"]').textContent.trim();
        const prev = el.querySelector('[data-testid="library-page-prev"]');
        const next = el.querySelector('[data-testid="library-page-next"]');
        return {
          visible: getComputedStyle(el).display !== 'none' && getComputedStyle(app).display !== 'none',
          info,
          prevDisabled: prev.disabled,
          nextDisabled: next.disabled,
        };
      }).filter(Boolean);
    const mainApp = document.querySelector('.app:not([data-testid="app-rank"])');
    const rankApp = document.querySelector('[data-testid="app-rank"]');
    return {
      icons: document.querySelectorAll('[data-ic]').length,
      svgs: document.querySelectorAll('[data-ic] svg').length,
      scrollW: document.documentElement.scrollWidth,
      innerW: window.innerWidth,
      appMain: mainApp ? getComputedStyle(mainApp).display : 'MISSING',
      rankBlock: rankApp ? getComputedStyle(rankApp).display : 'MISSING',
      mainPagers: pagerIn('.app:not([data-testid="app-rank"])'),
      rankPagers: pagerIn('[data-testid="app-rank"]'),
    };
  });

  if (d.svgs !== d.icons) { push(`icons ${d.svgs}/${d.icons}`, false); }
  if (d.scrollW > d.innerW) { push(`horizontal scroll ${d.scrollW}>${d.innerW}`, false); }

  if (state === 'main') {
    push('主视图可见', d.appMain !== 'none');
    push('分览块隐藏', d.rankBlock === 'none');
    push(`主态分页条=1（实际 ${d.mainPagers.length}）`, d.mainPagers.length === 1);
    const mp = d.mainPagers[0];
    push(`主态 info=「第 1 / 2 页 · 共 52 条」（实际 ${mp && mp.info}）`,
      !!mp && mp.info === '第 1 / 2 页 · 共 52 条');
    push('主态 next 可用（52 条 → 2 页）', !!mp && mp.nextDisabled === false);
    push('主态 prev 禁用（首页）', !!mp && mp.prevDisabled === true);
    push('主态只渲染 1 条分页条（分览块隐藏，其 pager 不可见）',
      d.rankPagers.filter((p) => p.visible).length === 0);
  } else if (state === 'rank-protagonist') {
    push('分览块可见', d.rankBlock !== 'none');
    push('主视图隐藏', d.appMain === 'none');
    push(`分览分页条=1（实际 ${d.rankPagers.length}）`, d.rankPagers.length === 1);
    const rp = d.rankPagers[0];
    // 核心契约：筛选后 total/页数随筛选重算（3 人 → 1 页），不是 52 条 / 2 页
    push(`分览 info=「第 1 / 1 页 · 共 3 条」（实际 ${rp && rp.info}）`,
      !!rp && rp.info === '第 1 / 1 页 · 共 3 条');
    push('分览 next 禁用（仅 1 页）', !!rp && rp.nextDisabled === true);
    push('分览 prev 禁用（首页）', !!rp && rp.prevDisabled === true);
    push('分览态主视图分页条不可见（整块隐藏）',
      d.mainPagers.filter((p) => p.visible).length === 0);
  }
  return fails;
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  await page.goto('file:///' + path.join(ROOT, PAGE.file).replace(/\\/g, '/'));
  let totalFails = 0;
  for (const state of PAGE.states) {
    await page.evaluate((s) => { setState(s); document.body.dataset.shot = '1'; }, state);
    await page.waitForTimeout(400);
    const out = path.join(ROOT, 'characters', `characters-${state === 'main' ? 'main' : 'rank-protagonist'}.png`);
    await page.screenshot({ path: out });
    const fails = await checks(page, state);
    if (fails.length) { totalFails += fails.length; console.log(`[${state}] FAIL: ${fails.join(' | ')}`); }
    else console.log(`[${state}] OK -> ${out}`);
  }
  await browser.close();
  console.log(totalFails ? `TOTAL FAILS: ${totalFails}` : 'ALL PASS');
  process.exit(totalFails ? 1 : 0);
})().catch((e) => { console.error('SCRIPT ERROR:', e); process.exit(2); });
