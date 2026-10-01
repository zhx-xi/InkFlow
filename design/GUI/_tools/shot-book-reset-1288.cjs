/*
 * design/GUI/_tools/shot-book-reset-1288.cjs — book 页原型截图 + 断言（#1288）
 *
 * 用途：BookRunPanel 工具栏新增「重置运行」（run-reset）+ 共享 ConfirmDialog 确认框后，
 * 重出 book 页原型简图，并对「按钮渲染条件」「确认框可见性」「文案要点」做计算样式/文本断言
 * （视觉模型不可用时的主验证手段）。
 *
 * 覆盖状态：running / completed / failed / degraded / degraded-expanded（既有 5 张重出）
 *           + reset-confirm（#1288 新增：确认框可见）
 *
 * 用法：node design/GUI/_tools/shot-book-reset-1288.cjs
 * 路径自解析（ROOT / playwright 均从脚本位置推导），见 _shared.cjs。
 */
const path = require('path');
const { assertGuiRoot, requirePlaywright, assertPageDir } = require('./_shared.cjs');

const ROOT = assertGuiRoot();
const chromium = requirePlaywright();
const PAGE_DIR = assertPageDir('book', ROOT);
const PAGE_FILE = 'book/book-run.html';

/** 既有 5 态 + #1288 新增 reset-confirm 态 */
const STATES = ['running', 'completed', 'failed', 'degraded', 'degraded-expanded', 'reset-confirm'];

/** 计算样式/文本断言（返回失败标签数组） */
async function runChecks(page, state) {
  const fails = [];
  const push = (label, ok) => {
    if (!ok) fails.push(label);
  };
  const d = await page.evaluate(() => {
    const el = (sel) => document.querySelector(sel);
    const disp = (sel) => (el(sel) ? getComputedStyle(el(sel)).display : 'MISSING');
    const resetBtn = el('[data-testid="run-reset"]');
    return {
      resetDisplay: disp('[data-testid="run-reset"]'),
      resetVisible: !!resetBtn && resetBtn.offsetParent !== null,
      overlayDisplay: disp('.overlay'),
      dialogDisplay: disp('[data-testid="run-reset-dialog"]'),
      dialogText: (el('[data-testid="run-reset-dialog"] .c-msg') || {}).textContent || '',
      cancelText: (el('[data-testid="run-reset-cancel"]') || {}).textContent || '',
      okText: (el('[data-testid="run-reset-ok"]') || {}).textContent || '',
      titleText: (el('[data-testid="run-reset-dialog"] h2') || {}).textContent || '',
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

  if (state === 'running') {
    // running 态：后端 reset 会 422 → GUI 不渲染该按钮
    push('running: run-reset hidden', !d.resetVisible);
    push('running: overlay hidden', d.overlayDisplay === 'none');
  } else if (state === 'reset-confirm') {
    push('reset-confirm: run-reset visible', d.resetVisible);
    push('reset-confirm: overlay flex', d.overlayDisplay === 'flex');
    push('reset-confirm: dialog visible', d.dialogDisplay !== 'none' && d.dialogDisplay !== 'MISSING');
    push('reset-confirm: title 重置运行？', d.titleText === '重置运行？');
    push('reset-confirm: message contains 重置 ≠ 删除正文', d.dialogText.includes('重置 ≠ 删除正文'));
    push('reset-confirm: message mentions 正文与草稿不会被删除', d.dialogText.includes('正文与草稿不会被删除'));
    push('reset-confirm: message mentions 需你先自行处理旧正文', d.dialogText.includes('需你先自行处理旧正文'));
    push('reset-confirm: cancel 取消', d.cancelText === '取消');
    push('reset-confirm: ok 确认重置', d.okText === '确认重置');
  } else {
    push(`${state}: run-reset visible`, d.resetVisible);
    push(`${state}: overlay hidden`, d.overlayDisplay === 'none');
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
