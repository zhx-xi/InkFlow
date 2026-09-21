/* InkFlow design/GUI 官方简图截图 + 断言脚本（#1349 writing 上下文注入回执面）
 * 用法: node design/GUI/_tools/shot-writing-context-injection.cjs
 * - 对 writing 的两个新状态（context-injected / context-no-record）: file:// 打开
 *   -> evaluate setState -> data-shot=1 隐藏 demo-bar -> waitForTimeout -> screenshot
 * - 每状态跑计算样式/几何断言（视觉模型不可用时的主验证），失败 exit 1
 *
 * 路径自解析（ROOT / playwright 均从脚本位置推导），见 _shared.cjs。
 */
const path = require('path');
const { assertGuiRoot, requirePlaywright, assertPageDir } = require('./_shared.cjs');

const ROOT = assertGuiRoot();
const chromium = requirePlaywright();
assertPageDir('writing', ROOT);
const PAGES = {
  writing: {
    file: 'writing/writing.html',
    states: ['context-injected', 'context-no-record'],
  },
};

async function runChecks(page, pageName, state) {
  const fails = [];
  const push = (label, ok) => { if (!ok) fails.push(label); };
  const d = await page.evaluate(() => {
    const cs = (sel) => { const el = document.querySelector(sel); return el ? getComputedStyle(el).display : 'MISSING'; };
    const txt = (sel) => { const el = document.querySelector(sel); return el ? el.textContent.trim() : null; };
    const rectOf = (sel) => { const el = document.querySelector(sel); return el ? el.getBoundingClientRect() : null; };
    return {
      // 回执区（有记录态）
      echo: cs('[data-testid="context-injected-echo"]'),
      count: txt('[data-testid="context-injected-count"]'),
      execution: txt('[data-testid="context-injected-execution"]'),
      groupCharacters: cs('[data-testid="context-injected-character_ids"]'),
      groupWorld: cs('[data-testid="context-injected-world_ids"]'),
      items: Array.from(document.querySelectorAll('[data-testid^="context-injected-item-"]')).map((el) => el.textContent.trim()),
      // 回退区（无记录态）
      echoEmpty: cs('[data-testid="context-injected-echo-empty"]'),
      emptyHint: txt('[data-testid="context-injected-empty"]'),
      emptyRect: rectOf('[data-testid="context-injected-empty"]'),
      // 预览面仍在（主路径未被回执面挤掉）
      previewBlock: cs('[data-testid="context-block-character_setting"]'),
      // 两区几何关系：回执区在预览区块之下、在已裁剪之上
      echoRect: rectOf('[data-testid="context-injected-echo"]'),
      droppedRect: rectOf('[data-testid="context-dropped"]'),
      // 回执面只读：不含勾选框
      echoCheckboxes: (document.querySelector('[data-testid="context-injected-echo"]') || { querySelectorAll: () => [] }).querySelectorAll('input[type=checkbox]').length,
      // 预览面勾选框（控制面）仍在
      previewCheckboxCount: document.querySelectorAll('[data-testid="context-block-character_setting"] input[type=checkbox]').length,
      scrollW: document.documentElement.scrollWidth,
      innerW: window.innerWidth,
    };
  });

  if (state === 'context-injected') {
    push('回执区可见（有记录态）', d.echo !== 'none' && d.echo !== 'MISSING');
    push('无记录回退区隐藏', d.echoEmpty === 'none');
    push('计数徽章存在且非空', !!d.count && d.count.length > 0);
    push('来源执行记录行可见', !!d.execution && d.execution.includes('来自执行'));
    push('角色分组可见', d.groupCharacters !== 'none' && d.groupCharacters !== 'MISSING');
    push('世界观分组可见', d.groupWorld !== 'none' && d.groupWorld !== 'MISSING');
    push('明细 chip 为 id 粒度（≥3 条）', Array.isArray(d.items) && d.items.length >= 3);
    push('回执区不含勾选框（只读）', d.echoCheckboxes === 0);
    push('预览面勾选框仍在（控制面未丢）', d.previewCheckboxCount > 0);
    push('预览区块可见', d.previewBlock !== 'none' && d.previewBlock !== 'MISSING');
    push('回执区位于已裁剪区块之上', d.echoRect !== null && d.droppedRect !== null && d.echoRect.bottom <= d.droppedRect.top + 1);
    // 🔴 可见性硬门禁：可滚动容器内元素「存在且样式对」≠「截图拍得到」
    push('回执区落在视口内（截图可见）', d.echoRect !== null && d.echoRect.top >= 0 && d.echoRect.bottom <= 800);
  } else if (state === 'context-no-record') {
    push('回退区可见（无记录态）', d.echoEmpty !== 'none' && d.echoEmpty !== 'MISSING');
    push('有记录回执区隐藏', d.echo === 'none');
    push('回退文案正确', d.emptyHint === '本章尚无生成记录');
    push('预览区块仍可见（主路径不受影响）', d.previewBlock !== 'none' && d.previewBlock !== 'MISSING');
    push('回退区落在视口内（截图可见）', d.emptyRect !== null && d.emptyRect.top >= 0 && d.emptyRect.bottom <= 800);
  }
  if (d.scrollW > d.innerW) fails.push(`无横向滚动 (${d.scrollW}>${d.innerW})`);
  return fails;
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
  let totalFails = 0;
  for (const [pageName, cfg] of Object.entries(PAGES)) {
    const page = await ctx.newPage();
    const url = 'file:///' + path.join(ROOT, cfg.file).replace(/\\/g, '/');
    await page.goto(url);
    const icon = await page.evaluate(() => ({
      ic: document.querySelectorAll('[data-ic]').length,
      svg: document.querySelectorAll('[data-ic] svg').length,
    }));
    if (icon.svg !== icon.ic) { totalFails++; console.log(`[${pageName}] FAIL icons ${icon.svg}/${icon.ic}`); }
    else console.log(`[${pageName}] icons ${icon.svg}/${icon.ic} OK`);

    for (const state of cfg.states) {
      await page.evaluate((s) => { setState(s); document.body.dataset.shot = '1'; }, state);
      // 把目标区块滚入视口（右栏是可滚动容器，否则默认截图拍不到底部区块）
      await page.evaluate((s) => {
        const sel = s === 'context-no-record'
          ? '[data-testid="context-injected-empty"]'
          : '[data-testid="context-injected-echo"]';
        const el = document.querySelector(sel);
        if (el) el.scrollIntoView({ block: 'center' });
      }, state);
      await page.waitForTimeout(500);
      const shotPath = path.join(ROOT, pageName, `${pageName}-${state}.png`);
      await page.screenshot({ path: shotPath });
      const fails = await runChecks(page, pageName, state);
      if (fails.length) {
        totalFails += fails.length;
        console.log(`[${pageName}-${state}] FAIL: ${fails.join(' | ')}`);
      } else {
        console.log(`[${pageName}-${state}] OK -> ${shotPath}`);
      }
    }
    await page.close();
  }
  await browser.close();
  console.log(totalFails ? `TOTAL FAILS: ${totalFails}` : 'ALL PASS');
  process.exit(totalFails ? 1 : 0);
})().catch((e) => { console.error('SCRIPT ERROR:', e); process.exit(2); });
