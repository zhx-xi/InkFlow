/* InkFlow design/GUI 官方简图截图 + 断言脚本（#1378 writing 删除授权两态补图 + 右栏铺满/2:1）
 * 用法: node design/GUI/_tools/shot-writing-delete-auth.cjs
 *
 * 为什么有这个脚本：writing 页的 delete-auth / delete-hitl 两个状态此前**无任何 shot 脚本**
 *   （png 为历史批次的孤儿产物）→ writing.html 改动后它们无法再生成、只能静默过期。
 *   #1378 改动右栏面板布局（影响这两个状态的画面），故补上脚本把两状态纳入可重生成集合。
 *
 * - 对 writing 的两个状态: file:// 打开 -> evaluate setState -> data-shot=1 隐藏 demo-bar
 *   -> waitForTimeout -> screenshot 1280x800@DPR1
 * - 每状态跑计算样式/几何断言（视觉模型不可用时的主验证），失败 exit 1
 *   含 #1378 右栏两面板「铺满 + 2:1」几何门禁（本页拉灰态同样适用）
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
    states: ['delete-auth', 'delete-hitl'],
  },
};

async function runChecks(page, pageName, state) {
  const fails = [];
  const push = (label, ok) => { if (!ok) fails.push(label); };
  const d = await page.evaluate(() => {
    const cs = (sel) => { const el = document.querySelector(sel); return el ? getComputedStyle(el).display : 'MISSING'; };
    const rectOf = (sel) => { const el = document.querySelector(sel); return el ? el.getBoundingClientRect() : null; };
    return {
      auth: cs('[data-testid="delete-auth-control"]'),
      authBtns: Array.from(document.querySelectorAll('[data-testid^="delete-mode-"]')).map((el) => ({
        text: el.textContent.trim(),
        selected: el.getAttribute('data-selected'),
        pressed: el.getAttribute('aria-pressed'),
        disabled: el.disabled,
      })),
      dialog: cs('[data-testid="delete-confirm-dialog"]'),
      dialogCard: rectOf('.delete-hitl-dialog .delete-hitl-card'),
      dialogTitle: (document.querySelector('.delete-hitl-dialog h3') || {}).textContent,
      dialogBody: (document.querySelector('.delete-hitl-dialog p') || {}).textContent,
      cancel: cs('[data-testid="delete-confirm-cancel"]'),
      approve: cs('[data-testid="delete-confirm-approve"]'),
      dialogCheckboxes: (document.querySelector('.delete-hitl-dialog') || { querySelectorAll: () => [] }).querySelectorAll('input[type=checkbox]').length,
      // #1378：右栏两面板几何（铺满 + 2:1）
      rail: (() => {
        const r = (sel) => {
          const node = document.querySelector(sel);
          if (!node) return null;
          const b = node.getBoundingClientRect();
          return { top: Math.round(b.top), bottom: Math.round(b.bottom), height: Math.round(b.height) };
        };
        return {
          box: r('[data-testid="right-rail"]'),
          ctx: r('[data-testid="rail-panel-context"]'),
          sum: r('[data-testid="rail-panel-summary"]'),
        };
      })(),
      scrollW: document.documentElement.scrollWidth,
      innerW: window.innerWidth,
    };
  });

  // 两态共有：右栏两面板铺满 + 2:1（#1378）
  if (d.rail && d.rail.box && d.rail.ctx && d.rail.sum) {
    push('面板铺满右栏（summary 底缘 = rail 底缘）', Math.abs(d.rail.sum.bottom - d.rail.box.bottom) <= 2);
    push('context:summary ≈ 2:1', d.rail.sum.height > 0 && Math.abs(d.rail.ctx.height / d.rail.sum.height - 2) <= 0.06);
  } else {
    push('右栏两面板存在', false);
  }

  if (state === 'delete-auth') {
    push('删除授权三态控件可见', d.auth === 'flex');
    push('三态按钮齐备（手动/一次确认/全自动）', Array.isArray(d.authBtns) && d.authBtns.map((b) => b.text).join(',') === '手动,一次确认,全自动');
    push('默认选中 manual（data-selected + aria-pressed）', d.authBtns[0] && d.authBtns[0].selected === 'true' && d.authBtns[0].pressed === 'true');
    push('控件可用（未禁用）', d.authBtns.every((b) => b.disabled === false));
    push('HITL 弹窗隐藏', d.dialog === 'none');
  } else if (state === 'delete-hitl') {
    push('HITL 弹窗可见', d.dialog === 'flex');
    push('弹窗标题/正文有文案', !!d.dialogTitle && !!d.dialogBody);
    push('取消钮可见', d.cancel !== 'none');
    push('确认钮可见', d.approve !== 'none');
    push('弹窗内无勾选框（纯确认）', d.dialogCheckboxes === 0);
    push('弹窗卡片落在视口内（截图可见）', d.dialogCard !== null && d.dialogCard.top >= 0 && d.dialogCard.bottom <= 800);
    push('弹窗打开期间三态按钮禁用', Array.isArray(d.authBtns) && d.authBtns.every((b) => b.disabled === true));
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
