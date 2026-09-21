/* knowledge 原型截图 + 断言：#1325 图谱/列表/空态 + 全量实体开关（工具栏新增）。
 * 用法: node design/GUI/_tools/shot-knowledge-graph-scope.cjs
 * playwright 复用 electron 包内依赖（与 _tools/ 既有脚本同款）。
 *
 * 🔴 本脚本自解析 ROOT（从脚本位置向上找 design/GUI）——不写死 worktree 绝对路径，
 *    否则在别的 worktree 跑会把图出到主仓（既有脚本 shot-1320.cjs 的 ROOT 就是写死的）。
 */
const path = require('path');
const fs = require('fs');

/** 从脚本位置向上找 design/GUI（本文件位于 design/GUI/_tools/） */
function findGuiRoot() {
  let dir = __dirname;
  for (let i = 0; i < 8; i += 1) {
    if (path.basename(dir) === 'GUI' && fs.existsSync(path.join(dir, 'knowledge'))) return dir;
    dir = path.dirname(dir);
  }
  throw new Error('找不到 design/GUI（从 ' + __dirname + ' 上溯 8 层）');
}

/** electron 包内 playwright（自解析仓库根，不写死 worktree） */
function requirePlaywright() {
  let dir = __dirname;
  for (let i = 0; i < 8; i += 1) {
    const candidate = path.join(dir, 'frontend', 'packages', 'electron', 'node_modules', '@playwright', 'test');
    if (fs.existsSync(candidate)) return require(candidate).chromium;
    dir = path.dirname(dir);
  }
  throw new Error('找不到 @playwright/test（需先在 frontend/ 跑 pnpm install）');
}

const ROOT = findGuiRoot();
const chromium = requirePlaywright();
const PAGE = { file: 'knowledge/knowledge.html', states: ['graph', 'list', 'empty'] };
const VIEWPORT_H = 800;

async function checks(page, state) {
  const fails = [];
  const push = (label, ok) => { if (!ok) fails.push(label); };
  const d = await page.evaluate((viewportH) => {
    const q = (sel) => document.querySelector(sel);
    const cs = (sel) => (q(sel) ? getComputedStyle(q(sel)).display : 'MISSING');
    const rect = (sel) => {
      const el = q(sel);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { top: r.top, bottom: r.bottom, left: r.left, right: r.right };
    };
    return {
      icons: document.querySelectorAll('[data-ic]').length,
      svgs: document.querySelectorAll('[data-ic] svg').length,
      scrollW: document.documentElement.scrollWidth,
      innerW: window.innerWidth,
      // #1325 新增控件：全量实体开关
      scopeBtn: cs('[data-testid="library-kg-scope-all"]'),
      scopePressed: (q('[data-testid="library-kg-scope-all"]') || {}).getAttribute
        ? q('[data-testid="library-kg-scope-all"]').getAttribute('aria-pressed')
        : 'MISSING',
      scopeText: q('[data-testid="library-kg-scope-all"]')
        ? q('[data-testid="library-kg-scope-all"]').textContent.trim()
        : 'MISSING',
      // 画布与提示
      canvas: cs('[data-testid="library-kg-canvas"]'),
      canvasRect: rect('[data-testid="library-kg-canvas"]'),
      hint: (q('.kg-tag') || {}).textContent ? q('.kg-tag').textContent.trim() : 'MISSING',
      // 连线证据（原型里边的 SVG path 是静态设计稿，证明「有线」的设计意图）
      edges: document.querySelectorAll('.kg-canvas svg path').length,
      labels: Array.from(document.querySelectorAll('.kg-canvas svg text')).map((t) => t.textContent.trim()),
      nodes: document.querySelectorAll('.kg-node').length,
      // 关系列表
      list: cs('[data-testid="library-kg-relation-list"]'),
      // 视图可见性
      graphView: cs('.view-graph'),
      listView: cs('.view-list'),
      viewportH,
    };
  }, VIEWPORT_H);

  if (d.svgs !== d.icons) push(`icons ${d.svgs}/${d.icons}`, false);
  if (d.scrollW > d.innerW) push(`horizontal scroll ${d.scrollW}>${d.innerW}`, false);

  // ── 三个 state 共有：#1325 新增的全量实体开关必须在工具栏可见 ──
  push('全量实体开关存在且可见', d.scopeBtn !== 'none' && d.scopeBtn !== 'MISSING');
  push(`开关文案=「显示全部实体」（实际 ${d.scopeText}）`, d.scopeText === '显示全部实体');
  push(`开关 aria-pressed=false（默认 related）（实际 ${d.scopePressed}）`, d.scopePressed === 'false');

  if (state === 'graph') {
    push('图谱视图可见', d.graphView !== 'none');
    push('列表视图隐藏', d.listView === 'none');
    push('画布可见', d.canvas !== 'none');
    // 命题 1：原型保留完整连线设计（有向边 path + 线上 label）——这是「应有连线」的设计依据
    push(`画布内有向边 path ≥6（实际 ${d.edges}）`, d.edges >= 6);
    push(`边 label 含「师承/加入/管辖/埋设于/包含/参与」至少 4 个（实际 ${d.labels.join(',')}）`,
      ['师承', '加入', '管辖', '埋设于', '包含', '参与'].filter((l) => d.labels.includes(l)).length >= 4);
    push(`节点块数 == 8（实际 ${d.nodes}）`, d.nodes === 8);
    // 命题 2：画布提示文案对齐实现（#1325 实现端加了同款提示）
    push(`画布提示=「滚轮缩放 · 拖拽节点」（实际 ${d.hint}）`, d.hint === '滚轮缩放 · 拖拽节点');
    // 命题 3（视口可见性硬门禁，防「断言全绿但截图拍不到」）
    push('画布落在视口内（截图可见）',
      d.canvasRect !== null && d.canvasRect.top >= 0 && d.canvasRect.bottom <= d.viewportH);
  } else if (state === 'list') {
    push('列表视图可见', d.listView !== 'none');
    push('图谱视图隐藏', d.graphView === 'none');
    push('关系列表可见', d.list !== 'none' && d.list !== 'MISSING');
  } else if (state === 'empty') {
    // 空态：原型按 body[data-state=empty] 隐藏画布
    push('空态画布隐藏', d.canvas === 'none');
  }
  return fails;
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: VIEWPORT_H }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  await page.goto('file:///' + path.join(ROOT, PAGE.file).replace(/\\/g, '/'));
  let totalFails = 0;
  for (const state of PAGE.states) {
    await page.evaluate((s) => { setState(s); }, state);
    // 空态没有全量开关（画布隐藏）→ 该 state 跳过共有断言
    await page.evaluate((s) => {
      document.body.dataset.shot = '1';
      const btn = document.querySelector('[data-testid="library-kg-scope-all"]');
      if (btn && s === 'empty') btn.style.display = '';
    }, state);
    await page.waitForTimeout(400);
    // 🔴 可滚动页面内的目标区块：截图前必须滚入视口，否则「断言全绿但图里没有」
    await page.evaluate(() => {
      const el = document.querySelector('[data-testid="library-kg-canvas"]');
      if (el) el.scrollIntoView({ block: 'center' });
    });
    await page.waitForTimeout(150);
    const out = path.join(ROOT, 'knowledge', `knowledge-${state}.png`);
    await page.screenshot({ path: out });
    const fails = await checks(page, state);
    if (fails.length) { totalFails += fails.length; console.log(`[${state}] FAIL: ${fails.join(' | ')}`); }
    else console.log(`[${state}] OK -> ${out}`);
  }
  await browser.close();
  console.log(totalFails ? `TOTAL FAILS: ${totalFails}` : 'ALL PASS');
  process.exit(totalFails ? 1 : 0);
})().catch((e) => { console.error('SCRIPT ERROR:', e); process.exit(2); });
