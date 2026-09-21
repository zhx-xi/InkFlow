/* InkFlow design/GUI 官方简图截图 + 断言脚本（F59-M6 收尾：writing 思考级别选择器/reasoning 思考区块 + settings 全局思考强度）
 * 用法: node shot-f59.cjs
 * - 对 writing/settings 每个状态: file:// 打开 -> evaluate setState -> data-shot=1 隐藏 demo-bar -> waitForTimeout -> screenshot 1280x800@DPR1
 * - 每状态跑计算样式/几何断言（视觉模型不可用时的主验证），失败 exit 1
 */
const path = require('path');
const { chromium } = require('D:/develop/projects/InkFlow/frontend/packages/electron/node_modules/@playwright/test');

const ROOT = 'D:/develop/projects/InkFlow-ft/f59-m6-governance/design/GUI';
const PAGES = {
  writing: {
    file: 'writing/writing.html',
    states: ['thinking-level', 'reasoning'],
  },
  settings: {
    file: 'settings/settings.html',
    states: ['reasoning'],
  },
};

function rect(r) {
  return r ? { top: Math.round(r.top), bottom: Math.round(r.bottom), height: Math.round(r.height) } : null;
}

async function runChecks(page, pageName, state) {
  const fails = [];
  const push = (label, ok) => { if (!ok) fails.push(label); };
  const d = await page.evaluate(() => {
    const cs = (sel) => { const el = document.querySelector(sel); return el ? getComputedStyle(el).display : 'MISSING'; };
    const rectOf = (sel) => { const el = document.querySelector(sel); return el ? el.getBoundingClientRect() : null; };
    const inline = '.editor > .chat-panel.inline-chat';
    const msgs = document.querySelector(`${inline} [data-testid="chat-messages"]`);
    return {
      selector: cs(`${inline} [data-testid="chat-reasoning-wrap"]`),
      selectorEffort: cs(`${inline} [data-testid="chat-reasoning-effort"]`),
      effortValue: (document.querySelector(`${inline} [data-testid="chat-reasoning-value"]`) || {}).textContent,
      effortExpanded: ((document.querySelector(`${inline} [data-testid="chat-reasoning-effort"]`) || { getAttribute: () => null }).getAttribute('aria-expanded')),
      menu: cs(`${inline} [data-testid="chat-reasoning-menu"]`),
      menuRect: rectOf(`${inline} [data-testid="chat-reasoning-menu"]`),
      options: Array.from(document.querySelectorAll(`${inline} [data-testid^="chat-reasoning-effort-option-"]`)).map((el) => el.textContent),
      reasoning: cs(`${inline} [data-testid="chat-reasoning-0"]`),
      reasoningText: (document.querySelector(`${inline} [data-testid="chat-reasoning-0"]`) || {}).textContent,
      reasoningRect: rectOf(`${inline} [data-testid="chat-reasoning-0"]`),
      aiMsg: cs(`${inline} .chat-msg.ai`),
      aiMsgRect: rectOf(`${inline} .chat-msg.ai`),
      msgsContainsReasoning: msgs ? !!msgs.querySelector('[data-testid="chat-reasoning-0"]') : false,
      globalCard: cs('[data-testid="global-reasoning-effort-card"]'),
      globalLabel: (document.querySelector('[data-testid="global-reasoning-effort-card"] .field-label') || {}).textContent,
      globalValue: (((document.querySelector('[data-testid="global-reasoning-effort-select"]') || {}).textContent) || '').trim(),
      reasoningHead: Array.from(document.querySelectorAll('[data-testid="model-table"] th')).map((th) => th.textContent.trim()),
      reasoningBadges: Array.from(document.querySelectorAll('[data-testid^="model-reasoning-badge-"]')).filter((el) => el.offsetParent !== null).map((el) => el.textContent),
      manualBadges: Array.from(document.querySelectorAll('[data-testid^="model-reasoning-manual-"]')).filter((el) => el.offsetParent !== null).map((el) => el.textContent),
      catModelsActive: !!(document.querySelector('[data-cat="models"]') || { classList: { contains: () => false } }).classList.contains('active'),
    };
  });

  if (pageName === 'writing' && state === 'thinking-level') {
    // flex item blockification：.thinking-control 的 inline-flex 在 flex 容器父级下 computed 为 flex
    push('selector visible in inline toolbar', d.selector === 'flex' || d.selector === 'inline-flex');
    push('trigger visible', d.selectorEffort !== 'none');
    push('trigger shows 高', d.effortValue === '高');
    push('dropdown expanded', d.menu !== 'none' && d.menu !== 'MISSING');
    push('dropdown shows 7 options', Array.isArray(d.options) && d.options.length === 7);
    push('options order none->default', d.options.join(',') === '关闭思考,最低,低,中,高,极高,跟随模型默认');
    push('aria-expanded=true', d.effortExpanded === 'true');
    push('dropdown fully inside viewport', d.menuRect !== null && d.menuRect.top >= 0 && d.menuRect.bottom <= 800);
  } else if (pageName === 'writing' && state === 'reasoning') {
    push('selector visible in inline toolbar', d.selector === 'flex' || d.selector === 'inline-flex');
    push('trigger shows 高 (previous round choice)', d.effortValue === '高');
    push('dropdown closed', d.menu === 'none');
    push('reasoning block visible', d.reasoning !== 'none' && d.reasoning !== 'MISSING');
    push('reasoning block in messages', d.msgsContainsReasoning);
    push('reasoning label 思考过程', !!d.reasoningText && d.reasoningText.includes('思考过程'));
    push('reasoning content non-empty', !!d.reasoningText && d.reasoningText.includes('先判断'));
    push('reasoning block above AI answer', d.reasoningRect !== null && d.aiMsgRect !== null && d.reasoningRect.bottom < d.aiMsgRect.top);
    push('AI message visible below', d.aiMsg !== 'none');
  } else if (pageName === 'settings' && state === 'reasoning') {
    push('models view visible', d.catModelsActive);
    push('global reasoning card present', d.globalCard !== 'none' && d.globalCard !== 'MISSING');
    push('card label 全局默认思考强度', d.globalLabel === '全局默认思考强度');
    push('card value 跟随模型默认', d.globalValue === '跟随模型默认');
    push('model table has 思考 column', Array.isArray(d.reasoningHead) && d.reasoningHead.includes('思考'));
    push('capability badge 支持思考 shown', Array.isArray(d.reasoningBadges) && d.reasoningBadges.includes('支持思考'));
    push('manual badge 手动 shown', Array.isArray(d.manualBadges) && d.manualBadges.includes('手动'));
  }
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
      scrollW: document.documentElement.scrollWidth,
      innerW: window.innerWidth,
    }));
    if (icon.svg !== icon.ic) { totalFails++; console.log(`[${pageName}] FAIL icons ${icon.svg}/${icon.ic}`); }
    else console.log(`[${pageName}] icons ${icon.svg}/${icon.ic} OK`);
    if (icon.scrollW > icon.innerW) { totalFails++; console.log(`[${pageName}] FAIL horizontal scroll ${icon.scrollW}>${icon.innerW}`); }

    for (const state of cfg.states) {
      await page.evaluate((s) => { setState(s); document.body.dataset.shot = '1'; }, state);
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
