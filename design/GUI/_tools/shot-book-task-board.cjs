/*
 * design/GUI/_tools/shot-book-task-board.cjs — 成书页「自动写作任务列表」多方案原型截图 + 断言（#1333 段 2）
 *
 * 用途：book.html 的三方案（A 侧栏 / B 看板 / C 单栏时间线）+ 现状对照（legacy）+ 状态语义图例出图，
 * 并对「方案切换」「#1267 新增状态语义」「现状三处呈现缺陷」做计算样式/文本断言
 * （视觉模型不可用时的主验证手段）。
 *
 * 覆盖：legacy×{running,blocked} / a×{running,blocked} / b×{running,blocked} / c×{running,blocked} / legend
 * 用法：node design/GUI/_tools/shot-book-task-board.cjs
 * 路径自解析（ROOT / playwright 均从脚本位置推导），见 _shared.cjs。
 */
const path = require('path');
const { assertGuiRoot, requirePlaywright, assertPageDir } = require('./_shared.cjs');

const ROOT = assertGuiRoot();
const chromium = requirePlaywright();
const PAGE_DIR = assertPageDir('book', ROOT);
const PAGE_FILE = 'book/book.html';

/** [scheme, state, 输出名] —— 视口与 #903/#1288 的 book-run-*.png 不同：新图集用项目标准 1280×800 @DPR1 */
const SCENES = [
  { scheme: 'legacy',  state: 'running', out: 'book-legacy-running.png', desc: '现状对照 · 写作中' },
  { scheme: 'legacy',  state: 'blocked', out: 'book-legacy-blocked.png', desc: '现状对照 · 审计阻断（三处呈现缺陷）' },
  { scheme: 'a',       state: 'running', out: 'book-a-running.png',      desc: '方案 A 侧栏任务列表 · 写作中' },
  { scheme: 'a',       state: 'blocked', out: 'book-a-blocked.png',      desc: '方案 A · 审计阻断' },
  { scheme: 'b',       state: 'running', out: 'book-b-running.png',      desc: '方案 B 主区看板 · 写作中' },
  { scheme: 'b',       state: 'blocked', out: 'book-b-blocked.png',      desc: '方案 B · 审计阻断' },
  { scheme: 'c',       state: 'running', out: 'book-c-running.png',      desc: '方案 C 单栏任务时间线 · 写作中' },
  { scheme: 'c',       state: 'blocked', out: 'book-c-blocked.png',      desc: '方案 C · 审计阻断' },
  { scheme: 'legend',  state: 'running', out: 'book-legend.png',         desc: '状态语义图例（含 #1267 新增）' },
];

/** 公共断言用的全字段 PROBE（每个字段对「本页可能没有」空安全，见 ui-prototype-workflow 坑 #34） */
const PROBE = () => {
  const el = (s) => document.querySelector(s);
  const disp = (s) => (el(s) ? getComputedStyle(el(s)).display : 'MISSING');
  const ic = document.querySelectorAll('[data-ic]').length;
  const svg = document.querySelectorAll('[data-ic] svg').length;
  const visibleNotes = Array.from(document.querySelectorAll('.design-note'))
    .filter((n) => getComputedStyle(n).display !== 'none')
    .map((n) => n.dataset.plan);
  const bodyText = document.body.innerText || '';
  return {
    scheme: document.body.dataset.scheme,
    state: document.body.dataset.state,
    runStatusText: ((el('[data-testid="run-status"]') || {}).textContent || '').trim(),
    reasonDisplay: disp('[data-testid="run-progress-reason"]'),
    appVisible: ['legacy', 'a', 'b', 'c', 'legend']
      .filter((s) => disp(`[data-testid="app-${s}"]`) !== 'none' && disp(`[data-testid="app-${s}"]`) !== 'MISSING'),
    reviewCount: (bodyText.match(/待人工介入/g) || []).length,
    legacyPendingCount: (bodyText.match(/待处理/g) || []).length,
    noteTotal: document.querySelectorAll('.design-note').length,
    legendRows: document.querySelectorAll('#legend-body tr').length,
    bookNavDisplay: disp('.ni-book'),
    bookNavText: ((el('.ni-book') || {}).textContent || '').trim(),
    visibleNotes,
    ic, svg,
    demoBarDisplay: disp('.demo-bar'),
    scrollW: document.documentElement.scrollWidth,
    innerW: window.innerWidth,
    errs: window.__errs || [],
  };
};

/** 每场景的专属断言 */
function sceneCheck(scene, d, push) {
  push('公共：仅 1 个方案容器可见', d.appVisible.length === 1);
  push(`公共：可见方案 = ${scene.scheme}`, d.appVisible[0] === scene.scheme);
  push('公共：恰好 1 条设计注释条可见且对应当前方案', JSON.stringify(d.visibleNotes) === JSON.stringify([scene.scheme]));
  push('公共：注释条总数 = 5', d.noteTotal === 5);

  if (scene.scheme === 'legend') {
    push('图例：7 行状态语义（含 #1267 新增 needs_review / blocked）', d.legendRows === 7);
    push('图例：已含「成书」导航入口（§3.5-4 拍板）', d.bookNavDisplay !== 'none' && d.bookNavText === '成书');
    return;
  }

  if (scene.scheme === 'legacy') {
    // 现状：五态映射，无 needs_review → 兜底「待处理」；run 徽标直接渲染英文枚举原文；无导航入口
    push('现状④：无「成书」导航入口', d.bookNavDisplay === 'none');
    push('现状①：needs_review 章兜底显示「待处理」', d.legacyPendingCount >= 1);
    push('现状①：全文无「待人工介入」', d.reviewCount === 0);
    push('现状②：run 徽标为英文枚举原文', ['running', 'blocked', 'completed'].includes(d.runStatusText));
    if (scene.state === 'blocked') {
      push('现状③：审计阻断原因块不渲染（仅 failed/degraded 渲染）', d.reasonDisplay === 'none');
    }
    return;
  }

  push(`${scene.scheme}：needs_review 章显示「待人工介入」`, d.reviewCount >= 1);
  push(`${scene.scheme}：已含「成书」导航入口（§3.5-4 拍板）`, d.bookNavDisplay !== 'none' && d.bookNavText === '成书');
  if (scene.state === 'blocked') {
    push(`${scene.scheme}：run 徽标中文语义（非英文原文）`, d.runStatusText === '审计阻断 · 已停止');
    push(`${scene.scheme}：审计阻断原因块渲染`, d.reasonDisplay !== 'none');
  } else {
    push(`${scene.scheme}：写作中无原因块`, d.reasonDisplay === 'none');
  }
}

(async () => {
  const browser = await chromium.launch();
  // 项目标准视口（ui-prototype-workflow 坑 #27）：1280×800 @DPR1
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  // 初始化链抛错捕获器（坑 #13/#15：静默死亡兜底网）
  await ctx.addInitScript(() => {
    window.__errs = [];
    window.addEventListener('error', (e) => window.__errs.push(`${e.message} @ ${e.filename}:${e.lineno}`));
    window.addEventListener('unhandledrejection', (e) => window.__errs.push(`PROMISE: ${(e.reason && e.reason.message) || e.reason}`));
  });
  const url = 'file:///' + path.join(ROOT, PAGE_FILE).replace(/\\/g, '/');
  await page.goto(url);
  // 截图纯净：body[data-shot=1] 隐藏 demo-bar（页面自带该规则，见坑 #36）
  await page.evaluate(() => { document.body.dataset.shot = '1'; });

  let totalFails = 0;
  for (const scene of SCENES) {
    await page.evaluate(({ scheme, state }) => { setScheme(scheme); setState(state); },
      { scheme: scene.scheme, state: scene.state });
    await page.waitForTimeout(250);
    const shotPath = path.join(PAGE_DIR, scene.out);
    await page.screenshot({ path: shotPath });

    const d = await page.evaluate(PROBE);
    const fails = [];
    const push = (label, ok) => { if (!ok) fails.push(label); };
    push('零 JS 错误', d.errs.length === 0);
    push('图标全渲染（svg === data-ic 挂载点）', d.svg === d.ic && d.ic > 0);
    push('无水平滚动', d.scrollW <= d.innerW);
    push('截图态 demo-bar 已隐藏', d.demoBarDisplay === 'none');
    sceneCheck(scene, d, push);
    if (d.errs.length) fails.push(`ERRS: ${d.errs.join(' | ')}`);

    if (fails.length) {
      totalFails += fails.length;
      console.log(`[${scene.out}] FAIL: ${fails.join(' | ')}`);
    } else {
      console.log(`[${scene.out}] OK (${scene.desc}) -> ${shotPath}`);
    }
  }
  await browser.close();
  console.log(totalFails ? `TOTAL FAILS: ${totalFails}` : 'ALL PASS');
  process.exit(totalFails ? 1 : 0);
})().catch((e) => {
  console.error('SCRIPT ERROR:', e);
  process.exit(2);
});
