/* #1322 world 地图视图截图 + 断言脚本
 * 用法: node shot-world-map.cjs
 * - file:// 打开 world.html → setState('map') → data-shot=1 隐藏 demo-bar → 截图 1280x800@DPR1
 * - 跑计算样式/几何断言（视觉模型不可用时的主验证），失败 exit 1
 */
const path = require('path');
const { chromium } = require('D:/develop/projects/InkFlow/frontend/packages/electron/node_modules/@playwright/test');
const ROOT = path.join(__dirname, '..');
const FILE = 'world/world.html';

async function runChecks(page) {
  const fails = [];
  const push = (label, ok) => { if (!ok) fails.push(label); };
  const d = await page.evaluate(() => {
    const cs = (sel) => { const el = document.querySelector(sel); return el ? getComputedStyle(el).display : 'MISSING'; };
    const rectOf = (sel) => { const el = document.querySelector(sel); return el ? el.getBoundingClientRect() : null; };
    const leftRect = rectOf('.map-left');
    return {
      main: cs('[data-testid="map-tree-main"]'),
      unmapped: cs('[data-testid="map-tree-unmapped"]'),
      toggle: cs('[data-testid="map-tree-unmapped-toggle"]'),
      handle: cs('[data-testid="map-tree-resize-handle"]'),
      handleCursor: (() => {
        const el = document.querySelector('[data-testid="map-tree-resize-handle"]');
        return el ? getComputedStyle(el).cursor : 'MISSING';
      })(),
      leftWidth: leftRect ? Math.round(leftRect.width) : -1,
      overflowX: (() => {
        const el = document.querySelector('[data-testid="library-list"]');
        return el ? getComputedStyle(el).overflowX : 'MISSING';
      })(),
      inMain: (document.querySelector('[data-testid="map-tree-main"]') || {}).textContent || '',
      inUnmapped: (document.querySelector('[data-testid="map-tree-unmapped"]') || {}).textContent || '',
      scrollW: document.documentElement.scrollWidth,
      innerW: window.innerWidth,
      icons: { ic: document.querySelectorAll('[data-ic]').length, svg: document.querySelectorAll('[data-ic] svg').length },
    };
  });

  push('map-tree-main rendered', d.main !== 'MISSING' && d.main !== 'none');
  push('unmapped section rendered', d.unmapped !== 'MISSING' && d.unmapped !== 'none');
  push('unmapped toggle rendered', d.toggle !== 'MISSING');
  push('resize handle rendered', d.handle !== 'MISSING');
  push('handle cursor col-resize', d.handleCursor === 'col-resize');
  push('left column 260px', d.leftWidth === 260);
  push('main tree has map rows', d.inMain.includes('青云山') && d.inMain.includes('剑冢区域'));
  push('unmapped section lists unmapped entries', d.inUnmapped.includes('未挂图条目'));
  push('no horizontal scroll', d.scrollW <= d.innerW);
  push('icons resolved', d.icons.svg === d.icons.ic);
  return { fails, d };
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  const url = 'file:///' + path.join(ROOT, FILE).replace(/\\/g, '/');
  await page.goto(url);
  await page.evaluate(() => { setState('map'); document.body.dataset.shot = '1'; });
  await page.waitForTimeout(500);
  const shotPath = path.join(ROOT, 'world', 'world-map.png');
  await page.screenshot({ path: shotPath });
  const { fails, d } = await runChecks(page);
  console.log(JSON.stringify(d, null, 2));
  if (fails.length) { console.log('FAIL: ' + fails.join(' | ')); process.exit(1); }
  console.log(`ALL PASS -> ${shotPath}`);
  await browser.close();
})().catch((e) => { console.error('SCRIPT ERROR:', e); process.exit(2); });
