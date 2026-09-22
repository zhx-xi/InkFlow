/* InkFlow design/GUI 官方简图截图 + 断言脚本（#1377 草稿审批弹层「驳回」入口）
 * 用法: node design/GUI/_tools/shot-writing-drafts-approval.cjs
 * - drafts-approval 状态: file:// 打开 → setState → data-shot=1 隐藏 demo-bar → screenshot
 * - 计算样式/几何/结构断言（视觉模型不可用时的主验证），失败 exit 1
 *
 * 路径自解析（ROOT / playwright 均从脚本位置推导），见 _shared.cjs。
 */
const path = require('path');
const { assertGuiRoot, requirePlaywright, assertPageDir } = require('./_shared.cjs');

const ROOT = assertGuiRoot();
const chromium = requirePlaywright();
assertPageDir('writing', ROOT);

const PAGE = { file: 'writing/writing.html', state: 'drafts-approval' };

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  const url = 'file:///' + path.join(ROOT, PAGE.file).replace(/\\/g, '/');
  await page.goto(url);

  let fails = 0;
  const push = (label, ok) => { if (!ok) { fails += 1; console.log(`  FAIL ${label}`); } };

  // ── 图标完整性（ICONS 表缺项会渲染空 svg） ──
  const icon = await page.evaluate(() => ({
    ic: document.querySelectorAll('[data-ic]').length,
    svg: document.querySelectorAll('[data-ic] svg').length,
  }));
  if (icon.svg !== icon.ic) { fails += 1; console.log(`[writing] FAIL icons ${icon.svg}/${icon.ic}`); }
  else console.log(`[writing] icons ${icon.svg}/${icon.ic} OK`);

  await page.evaluate((s) => { setState(s); document.body.dataset.shot = '1'; }, PAGE.state);
  await page.waitForTimeout(500);

  const d = await page.evaluate(() => {
    const cs = (sel, prop) => {
      const el = document.querySelector(sel);
      return el ? getComputedStyle(el)[prop] : 'MISSING';
    };
    const txt = (sel) => {
      const el = document.querySelector(sel);
      return el ? el.textContent.trim() : null;
    };
    const rect = (sel) => {
      const el = document.querySelector(sel);
      return el ? el.getBoundingClientRect() : null;
    };
    const reject = document.querySelector('[data-testid="drafts-drawer-reject-d1"]');
    const confirm = document.querySelector('[data-testid="drafts-drawer-confirm-d1"]');
    const actions = reject ? reject.parentElement : null;
    const cancel = document.querySelector('.drafts-dialog .draft-cancel');
    return {
      dialogDisplay: cs('[data-testid="drafts-drawer"]', 'display'),
      overlayDisplay: cs('[data-testid="drafts-overlay"]', 'display'),
      title: txt('[data-testid="drafts-drawer"] .drafts-head h2'),
      item1: cs('[data-testid="drafts-drawer-item-d1"]', 'display'),
      item2: cs('[data-testid="drafts-drawer-item-d2"]', 'display'),
      rejectText: reject ? reject.textContent.trim() : null,
      confirmText: confirm ? confirm.textContent.trim() : null,
      cancelText: cancel ? cancel.textContent.trim() : null,
      rejectSvg: reject ? reject.querySelectorAll('svg').length : -1,
      confirmSvg: confirm ? confirm.querySelectorAll('svg').length : -1,
      // 顺序：同一动作行内 取消 < 拒绝 < 确认（次要动作在左、主行动在右）
      domOrder: actions ? Array.from(actions.children).map((el) => el.getAttribute('data-testid') || el.className) : [],
      actionCount: actions ? actions.children.length : -1,
      // 几何：与确认同排（top 一致）且在其左侧
      rejectRect: reject ? { left: reject.getBoundingClientRect().left, top: reject.getBoundingClientRect().top } : null,
      confirmRect: confirm ? { left: confirm.getBoundingClientRect().left, top: confirm.getBoundingClientRect().top } : null,
      // 视觉层级：确认=accent 实心，拒绝=描边（背景不得为 accent）
      rejectBg: reject ? getComputedStyle(reject).backgroundColor : 'MISSING',
      confirmBg: confirm ? getComputedStyle(confirm).backgroundColor : 'MISSING',
      rejectBorderW: reject ? getComputedStyle(reject).borderTopWidth : 'MISSING',
      confirmBorderW: confirm ? getComputedStyle(confirm).borderTopWidth : 'MISSING',
      actionsJustify: actions ? getComputedStyle(actions).justifyContent : 'MISSING',
      // 工具栏入口（#1003）**不在本原型**（存量缺口，见 writing.md §11.1 与 #1330）→ 不作断言
      scrollW: document.documentElement.scrollWidth,
      innerW: window.innerWidth,
    };
  });

  push('弹层可见（drafts-approval 态）', d.dialogDisplay !== 'none' && d.dialogDisplay !== 'MISSING');
  push('遮罩可见', d.overlayDisplay !== 'none' && d.overlayDisplay !== 'MISSING');
  push('标题为「草稿审批」', d.title === '草稿审批');
  push('两行草稿均渲染', d.item1 !== 'none' && d.item2 !== 'none');
  push('驳回钮可见且文案为「拒绝」', d.rejectText !== null && d.rejectText.includes('拒绝'));
  push('驳回钮带图标', d.rejectSvg === 1);
  push('确认钮文案为「确认」且带图标', d.confirmText !== null && d.confirmText.includes('确认') && d.confirmSvg === 1);
  push('取消钮文案为「取消」', d.cancelText === '取消');
  push('动作行内 取消 → 拒绝 → 确认 顺序（三个控件）', d.actionCount === 3
    && d.domOrder[0].includes('draft-cancel')
    && String(d.domOrder[1]).includes('drafts-drawer-reject-d1')
    && String(d.domOrder[2]).includes('drafts-drawer-confirm-d1'));
  push('驳回与确认同排（top 一致）', d.rejectRect && d.confirmRect && Math.abs(d.rejectRect.top - d.confirmRect.top) <= 1);
  push('驳回位于确认左侧（次要动作在左）', d.rejectRect && d.confirmRect && d.rejectRect.left < d.confirmRect.left);
  push('确认=accent 实心（无描边）', d.confirmBg !== d.rejectBg && d.confirmBorderW === '0px');
  push('驳回=描边次要钮（非 accent 底）', d.rejectBorderW !== '0px');
  push('动作行右对齐', d.actionsJustify === 'flex-end');
  push('无横向滚动', d.scrollW <= d.innerW);

  if (d.rejectRect && (d.rejectRect.top < 0 || d.rejectRect.top > 800)) {
    fails += 1;
    console.log(`  FAIL 驳回钮落在视口内（top=${d.rejectRect.top}）`);
  }

  await page.evaluate((s) => { setState(s); document.body.dataset.shot = '1'; }, PAGE.state);
  await page.waitForTimeout(400);
  const shotPath = path.join(ROOT, 'writing', `writing-${PAGE.state}.png`);
  await page.screenshot({ path: shotPath });
  console.log(fails ? `[writing-${PAGE.state}] FAIL: ${fails} assertion(s)` : `[writing-${PAGE.state}] OK -> ${shotPath}`);

  await page.close();
  await browser.close();
  console.log(fails ? `TOTAL FAILS: ${fails}` : 'ALL PASS');
  process.exit(fails ? 1 : 0);
})().catch((e) => { console.error('SCRIPT ERROR:', e); process.exit(2); });
