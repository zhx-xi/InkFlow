/* #1323 timeline 原型截图 + 断言：章分组容器（每事件一次）+ 真实章节标题 + 未分章。
 * 用法: node design/GUI/_tools/shot-1323.cjs
 * playwright 复用 electron 包内依赖（路径自解析，见 _shared.cjs）。
 */
const path = require('path');
const { assertGuiRoot, requirePlaywright, assertPageDir } = require('./_shared.cjs');

const ROOT = assertGuiRoot();
const chromium = requirePlaywright();
assertPageDir('timeline', ROOT);
const PAGE = { file: 'timeline/timeline.html', states: ['narrative', 'world'] };

async function checks(page, state) {
  const fails = [];
  const push = (label, ok) => { if (!ok) fails.push(label); };
  const d = await page.evaluate(() => {
    const axis = document.querySelector('[data-testid="tl-axis"]');
    const groups = axis ? Array.from(axis.querySelectorAll('[data-testid^="tl-group-"]'))
      .filter((el) => !el.dataset.testid.startsWith('tl-group-title-')) : [];
    const nodes = axis ? Array.from(axis.querySelectorAll('[data-testid^="tl-axis-node-"]')) : [];
    const titles = groups.map((g) => {
      const t = g.querySelector('[data-testid^="tl-group-title-"]');
      return t ? t.textContent.trim() : '';
    });
    // 每事件恰好出现一次（去重铁证）
    const nodeIds = nodes.map((n) => n.dataset.testid);
    // 章内顺序（每个分组的节点 id 序列）
    const orderPerGroup = groups.map((g) => ({
      gid: g.dataset.testid.replace('tl-group-', ''),
      ids: Array.from(g.querySelectorAll('[data-testid^="tl-axis-node-"]'))
        .map((n) => n.dataset.testid.replace('tl-axis-node-', '')),
    }));
    return {
      icons: document.querySelectorAll('[data-ic]').length,
      svgs: document.querySelectorAll('[data-ic] svg').length,
      scrollW: document.documentElement.scrollWidth,
      innerW: window.innerWidth,
      groupCount: groups.length,
      nodeCount: nodes.length,
      dupNodes: nodeIds.length - new Set(nodeIds).size,
      titles,
      orderPerGroup,
    };
  });

  if (d.svgs !== d.icons) { push(`icons ${d.svgs}/${d.icons}`, false); }
  if (d.scrollW > d.innerW) { push(`horizontal scroll ${d.scrollW}>${d.innerW}`, false); }
  push(`章分组=4（实际 ${d.groupCount}）`, d.groupCount === 4);
  push(`事件节点=5 且无重复（实际 ${d.nodeCount} dup=${d.dupNodes}）`,
    d.nodeCount === 5 && d.dupNodes === 0);
  push(`真实章节标题（实际 ${JSON.stringify(d.titles)}）`,
    d.titles[0] === '第十一章 剑心为何物' && d.titles[1] === '第十二章 夜访剑冢' &&
    d.titles[2] === '第十三章 剑心蒙尘' && d.titles[3] === '未分章');
  push('header 不含 narrative_position 拼的伪章号',
    !d.titles.some((t) => /第\s*[0-9]+\s*章/.test(t)));
  // 世界序：c12 组内按世界内时间倒序（3 → 2）
  const c12 = d.orderPerGroup.find((g) => g.gid === 'c12');
  if (state === 'world') {
    push(`世界序 c12 组内顺序 = ['3','2']（实际 ${JSON.stringify(c12 && c12.ids)}）`,
      !!c12 && JSON.stringify(c12.ids) === JSON.stringify(['3', '2']));
  } else {
    push(`叙事序 c12 组内顺序 = ['2','3']（实际 ${JSON.stringify(c12 && c12.ids)}）`,
      !!c12 && JSON.stringify(c12.ids) === JSON.stringify(['2', '3']));
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
    const out = path.join(ROOT, 'timeline', `timeline-${state}.png`);
    await page.screenshot({ path: out });
    const fails = await checks(page, state);
    if (fails.length) { totalFails += fails.length; console.log(`[${state}] FAIL: ${fails.join(' | ')}`); }
    else console.log(`[${state}] OK -> ${out}`);
  }
  await browser.close();
  console.log(totalFails ? `TOTAL FAILS: ${totalFails}` : 'ALL PASS');
  process.exit(totalFails ? 1 : 0);
})().catch((e) => { console.error('SCRIPT ERROR:', e); process.exit(2); });
