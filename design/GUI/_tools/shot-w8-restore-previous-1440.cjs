/* InkFlow design/GUI 官方简图截图 + 断言脚本（#1440 被覆盖章的「已有上一稿」徽标 + 恢复入口）
 * 用法: node design/GUI/_tools/shot-w8-restore-previous-1440.cjs
 *
 * 覆盖：
 *   writing 页 —— 章节树「已有上一稿」徽标（常显）+ 行内「恢复上一稿」入口（hover 操作区）
 *                 + 恢复确认框（chapter-restore-dialog，共享 ConfirmDialog 形态）
 *   book 页    —— force 覆盖后的「N 章已备份，可恢复」提示（run-overwrite-notice）
 *
 * 产出 PNG：writing-chapter-previous.png / writing-chapter-restore.png / book-run-overwrite-notice.png
 * 路径自解析（ROOT / playwright 均从脚本位置推导），见 _shared.cjs。
 */
const path = require('path');
const { assertGuiRoot, requirePlaywright, assertPageDir } = require('./_shared.cjs');

const ROOT = assertGuiRoot();
const chromium = requirePlaywright();
assertPageDir('writing', ROOT);
assertPageDir('book', ROOT);

const WRITING = 'writing/writing.html';
const BOOK = 'book/book-run.html';

let fails = 0;
const push = (label, ok) => {
  if (!ok) {
    fails += 1;
    console.log(`  FAIL ${label}`);
  }
};

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();

  // ─────────────────────────── writing 页 ───────────────────────────
  await page.goto('file:///' + path.join(ROOT, WRITING).replace(/\\/g, '/'));

  // 图标完整性（ICONS 表缺项会渲染空 svg —— 本次新增 rotate-ccw）
  const icon = await page.evaluate(() => ({
    ic: document.querySelectorAll('[data-ic]').length,
    svg: document.querySelectorAll('[data-ic] svg').length,
  }));
  push(`icons 全覆盖（${icon.svg}/${icon.ic}）`, icon.svg === icon.ic);

  // ① 徽标常显（editor-idle 态）
  await page.evaluate(() => {
    setState('editor-idle');
    document.body.dataset.shot = '1';
  });
  await page.waitForTimeout(400);
  const idle = await page.evaluate(() => {
    const vis = (sel) => {
      const el = document.querySelector(sel);
      return !!el && el.offsetParent !== null;
    };
    const badgeText = (sel) => {
      const el = document.querySelector(sel);
      return el ? el.textContent.trim() : null;
    };
    const badgeTitle = (sel) => {
      const el = document.querySelector(sel);
      return el ? el.getAttribute('title') : null;
    };
    const row = document.querySelector('[data-testid="chapter-restore-ch12"]');
    const actions = row ? row.parentElement : null;
    return {
      badge10: vis('[data-testid="chapter-prev-badge-ch10"]'),
      badge10Text: badgeText('[data-testid="chapter-prev-badge-ch10"]'),
      badge10Title: badgeTitle('[data-testid="chapter-prev-badge-ch10"]'),
      badge12: vis('[data-testid="chapter-prev-badge-ch12"]'),
      restore10: vis('[data-testid="chapter-restore-ch10"]'),
      restore12: vis('[data-testid="chapter-restore-ch12"]'),
      dialogDisplay: getComputedStyle(document.querySelector('[data-testid="chapter-restore-dialog"]')).display,
      order: actions
        ? Array.from(actions.children).map((el) => el.getAttribute('data-testid') || el.className)
        : [],
      scrollW: document.documentElement.scrollWidth,
      innerW: window.innerWidth,
    };
  });
  push('editor-idle：第 10 章徽标常显', idle.badge10);
  push('editor-idle：第 12 章（当前章）徽标常显', idle.badge12);
  push('editor-idle：徽标文案为「旧稿」（紧凑，避免挤掉章节标题）', idle.badge10Text === '旧稿');
  push('editor-idle：徽标 title 说明「已有上一稿」（tooltip 承载完整语义）', idle.badge10Title === '已有上一稿，可恢复');
  push('editor-idle：第 10 / 12 章均有恢复入口', idle.restore10 && idle.restore12);
  push(
    'editor-idle：恢复钮位于编辑钮之前（行内次要动作在左）',
    idle.order.length >= 3 && String(idle.order[0]).includes('chapter-restore-ch12'),
  );
  push('editor-idle：确认框不显示', idle.dialogDisplay === 'none');
  push('editor-idle：无横向滚动', idle.scrollW <= idle.innerW);
  await page.screenshot({ path: path.join(ROOT, 'writing', 'writing-chapter-previous.png') });
  console.log(`[writing-editor-idle] -> ${path.join(ROOT, 'writing', 'writing-chapter-previous.png')}`);

  // ② 恢复确认框（chapter-restore-confirm 态）
  await page.evaluate(() => {
    setState('chapter-restore-confirm');
    document.body.dataset.shot = '1';
  });
  await page.waitForTimeout(400);
  const dlg = await page.evaluate(() => {
    const el = (sel) => document.querySelector(sel);
    const txt = (sel) => (el(sel) ? el(sel).textContent.trim() : null);
    return {
      dialogDisplay: getComputedStyle(el('[data-testid="chapter-restore-dialog"]')).display,
      title: txt('[data-testid="chapter-restore-dialog"] h2'),
      msg: txt('[data-testid="chapter-restore-dialog"] .cr-msg'),
      cancel: txt('[data-testid="chapter-restore-cancel"]'),
      ok: txt('[data-testid="chapter-restore-ok"]'),
      // 恢复 = 破坏性（覆盖当前正文）→ 确认钮为 err 描边（danger），非 accent 实心
      okBorderW: getComputedStyle(el('[data-testid="chapter-restore-ok"]')).borderTopWidth,
      okColor: getComputedStyle(el('[data-testid="chapter-restore-ok"]')).color,
      scrollW: document.documentElement.scrollWidth,
      innerW: window.innerWidth,
    };
  });
  push('chapter-restore-confirm：确认框可见', dlg.dialogDisplay === 'flex');
  push('chapter-restore-confirm：标题「恢复上一稿？」', dlg.title === '恢复上一稿？');
  push('chapter-restore-confirm：文案含「双向切换」（可逆性说明）', !!dlg.msg && dlg.msg.includes('双向切换'));
  push('chapter-restore-confirm：文案说明可切回', !!dlg.msg && dlg.msg.includes('切回'));
  push('chapter-restore-confirm：取消钮「取消」', dlg.cancel === '取消');
  push('chapter-restore-confirm：确认钮「恢复」', dlg.ok === '恢复');
  push('chapter-restore-confirm：确认钮为描边（danger 形态，非实心 accent）', dlg.okBorderW !== '0px');
  push('chapter-restore-confirm：无横向滚动', dlg.scrollW <= dlg.innerW);
  await page.screenshot({ path: path.join(ROOT, 'writing', 'writing-chapter-restore.png') });
  console.log(`[writing-chapter-restore] -> ${path.join(ROOT, 'writing', 'writing-chapter-restore.png')}`);

  // ─────────────────────────── book 页 ───────────────────────────
  await page.goto('file:///' + path.join(ROOT, BOOK).replace(/\\/g, '/'));
  await page.evaluate(() => {
    const bar = document.querySelector('.demo-bar');
    if (bar) bar.style.display = 'none';
  });

  const notice = async (state) =>
    page.evaluate((s) => {
      window.setState(s);
      const el = document.querySelector('[data-testid="run-overwrite-notice"]');
      return {
        display: getComputedStyle(el).display,
        text: el.textContent.trim(),
        status: document.querySelector('[data-testid="run-status"]').textContent.trim(),
      };
    }, state);

  // ③ overwrite-notice 态：提示可见
  const on = await notice('overwrite-notice');
  await page.waitForTimeout(300);
  push('book overwrite-notice：提示可见', on.display !== 'none');
  push('book overwrite-notice：文案为「N 章已备份，可恢复」', on.text === '3 章已备份，可恢复');
  push('book overwrite-notice：状态徽标为 completed', on.status === 'completed');
  // 截图为 shot-book-token-scope-1431.cjs 的职责（900×792，与 book-run-*.png 家族同视口）
  // —— 见 #1455：同一 PNG 不允许两个脚本以不同视口写出，本脚本只做断言。
  console.log('[book-run-overwrite-notice] 截图归 shot-book-token-scope-1431.cjs，本脚本仅断言');

  // ④ 其余状态：提示不显示（无 overwrite 数据）
  for (const state of ['running', 'completed', 'failed', 'degraded', 'degraded-expanded', 'reset-confirm']) {
    const off = await notice(state);
    push(`book ${state}：提示不显示`, off.display === 'none');
  }

  await page.close();
  await browser.close();
  console.log(fails ? `TOTAL FAILS: ${fails}` : 'ALL PASS');
  process.exit(fails ? 1 : 0);
})().catch((e) => {
  console.error('SCRIPT ERROR:', e);
  process.exit(2);
});
