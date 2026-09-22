/* InkFlow design/GUI 官方简图截图 + 断言脚本（#1379 writing 上下文注入「Agent 按大纲预选」+ 一键清除/全选）
 * 用法: node design/GUI/_tools/shot-writing-context-preselect.cjs
 * - 对 writing 的两个新状态（context-preselect-loading / context-preselect）: file:// 打开
 *   -> evaluate setState -> data-shot=1 隐藏 demo-bar -> scrollIntoView -> waitForTimeout -> screenshot
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
    states: ['context-preselect-loading', 'context-preselect'],
  },
};

async function runChecks(page, pageName, state) {
  const fails = [];
  const push = (label, ok) => { if (!ok) fails.push(label); };
  const d = await page.evaluate(() => {
    const cs = (sel) => { const el = document.querySelector(sel); return el ? getComputedStyle(el).display : 'MISSING'; };
    const txt = (sel) => { const el = document.querySelector(sel); return el ? el.textContent.trim() : null; };
    const rectOf = (sel) => { const el = document.querySelector(sel); return el ? el.getBoundingClientRect() : null; };
    const charItems = Array.from(document.querySelectorAll('[data-testid="context-block-character_setting"] .ctx-item'));
    return {
      // 预选状态条两态
      pending: cs('[data-testid="context-preselect-pending"]'),
      pendingText: txt('[data-testid="context-preselect-pending"]'),
      applied: cs('[data-testid="context-preselect-applied"]'),
      appliedText: txt('[data-testid="context-preselect-applied"]'),
      // 一键清除 / 全选（标题行常驻）
      clearBtn: cs('[data-testid="context-clear-all"]'),
      clearText: txt('[data-testid="context-clear-all"]'),
      selectAllBtn: cs('[data-testid="context-select-all"]'),
      selectAllText: txt('[data-testid="context-select-all"]'),
      clearRect: rectOf('[data-testid="context-clear-all"]'),
      selectAllRect: rectOf('[data-testid="context-select-all"]'),
      // 角色卡勾选态（预选子集：第 1 项保留 / 第 2 项排除）
      charChecked: charItems.map((it) => it.querySelector('input[type=checkbox]').checked),
      charStrike: charItems.map((it) => it.querySelector('.t').style.textDecoration),
      // 世界观 / 伏笔全保留
      worldChecked: Array.from(document.querySelectorAll('[data-testid="context-block-world_setting"] .ctx-item input[type=checkbox]')).map((cb) => cb.checked),
      foreChecked: Array.from(document.querySelectorAll('[data-testid="context-block-foreshadowing"] .ctx-item input[type=checkbox]')).map((cb) => cb.checked),
      // 预览面仍在（预选不挤掉主路径）
      previewBlock: cs('[data-testid="context-block-outline"]'),
      // 容器内可见性（滚动后各状态的核心元素必须落在 ContextPanel 可视区内 → 截图拍得到）
      pendingRect: rectOf('[data-testid="context-preselect-pending"]'),
      appliedRect: rectOf('[data-testid="context-preselect-applied"]'),
      charCardRect: rectOf('[data-testid="context-block-character_setting"]'),
      containerRect: rectOf('[data-testid="context-panel-content"]'),
      scrollW: document.documentElement.scrollWidth,
      innerW: window.innerWidth,
    };
  });
  // 元素落在 ContextPanel 可视区内的判据（含 1px 容差）
  const inView = (rect) =>
    rect !== null &&
    d.containerRect !== null &&
    rect.bottom > d.containerRect.top + 1 &&
    rect.top < d.containerRect.bottom - 1;

  push('一键清除按钮可见', d.clearBtn !== 'none' && d.clearBtn !== 'MISSING');
  push('全选按钮可见', d.selectAllBtn !== 'none' && d.selectAllBtn !== 'MISSING');
  push('清除按钮文案为「清除」', d.clearText === '清除');
  push('全选按钮文案为「全选」', d.selectAllText === '全选');
  push('预览面大纲卡片可见（主路径不受影响）', d.previewBlock !== 'none' && d.previewBlock !== 'MISSING');

  if (state === 'context-preselect-loading') {
    push('加载态状态条可见', d.pending !== 'none' && d.pending !== 'MISSING');
    push('加载态文案含「预选中」', !!d.pendingText && d.pendingText.includes('预选中'));
    push('已预选状态条隐藏', d.applied === 'none');
    push('加载态面板暂为全选（不阻塞，未收窄）', d.charChecked.every(Boolean) === true);
    push('加载态状态条落在可视区内（截图可见）', inView(d.pendingRect));
  } else if (state === 'context-preselect') {
    push('已预选状态条可见', d.applied !== 'none' && d.applied !== 'MISSING');
    push('已预选文案含「已按大纲预选」', !!d.appliedText && d.appliedText.includes('已按大纲预选'));
    push('加载态状态条隐藏', d.pending === 'none');
    push('预选子集：角色第 1 项勾选', d.charChecked[0] === true);
    push('预选子集：角色第 2 项未勾选（与本章无关）', d.charChecked[1] === false);
    push('未勾选项带划线（与回执面表达一致）', d.charStrike[1] === 'line-through');
    push('世界观 / 伏笔保持全选', d.worldChecked.every(Boolean) && d.foreChecked.every(Boolean));
    push('角色卡子集勾选落在可视区内（截图可见）', inView(d.charCardRect));
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
      // 右栏是可滚动容器，且 ContextPanel 可视高度有限 —— 两个状态各自聚焦其核心信息：
      //  loading  → 状态条贴顶（演示加载态文案）
      //  applied  → 滚到角色卡（演示「按大纲收窄的子集勾选」；标题行工具带固定不滚，同框可见）
      await page.evaluate((s) => {
        const sel = s === 'context-preselect'
          ? '[data-testid="context-block-character_setting"]'
          : '[data-testid="context-preselect-pending"]';
        const el = document.querySelector(sel);
        if (el) el.scrollIntoView({ block: 'start' });
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
