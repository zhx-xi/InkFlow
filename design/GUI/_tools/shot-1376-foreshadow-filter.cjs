/*
 * #1376 伏笔页筛选（是否回收 · 章节出现）+ 优先级排序 · 原型截图 + 断言脚本
 * 用法: node shot-1376-foreshadow-filter.cjs
 * - file:// 打开 design/GUI/foreshadow/foreshadow.html → setState(状态) → data-shot=1 隐藏 demo-bar
 * - 滚到卡片顶部（#1342 教训：新增区块在视口下方 → 断言全绿但截图看不见）
 * - 截 1280x800@DPR1 → design/GUI/foreshadow/foreshadow-*.png（10 张）
 * - 计算样式 / 几何 / DOM 契约断言（视觉复核的前置网），任一条 FAIL → exit 1
 *
 * 覆盖：
 *   ① 方案 A（chip 组 + 位置文本 + 排序切换）· 推荐
 *   ② 方案 B（下拉 + 优先级区间）
 *   ③ 「出现章节」口径 1（location 文本匹配）vs 口径 2（结构化章节关联）
 *   ④ 排序控件升/降两向 + 筛选无结果边界 + 现状对照（legacy）
 *
 * 路径自解析（ROOT / playwright 均从脚本位置推导），见 _shared.cjs（#1361 纪律）。
 */
const path = require('path');
const { assertGuiRoot, requirePlaywright, assertPageDir } = require('./_shared.cjs');

const ROOT = assertGuiRoot();
const chromium = requirePlaywright();
assertPageDir('foreshadow', ROOT);
const FILE = 'foreshadow/foreshadow.html';
const URL = 'file:///' + path.join(ROOT, FILE).replace(/\\/g, '/');

/** 与截图同源的公共探针（全字段 null 安全：#34 教训） */
const PROBE = () => {
  const q = (s) => document.querySelector(s);
  const vis = (el) => !!(el && el.offsetParent !== null);
  const disp = (el) => (el ? getComputedStyle(el).display : 'MISSING');
  const tx = (el) => (el ? String(el.textContent || '').trim() : 'MISSING');
  const attr = (el, a) => (el ? el.getAttribute(a) : 'MISSING');
  const rows = Array.from(document.querySelectorAll('[data-testid^="fs-row-"]'));
  const notes = Array.from(document.querySelectorAll('.design-note'));
  const visibleNotes = notes.filter((n) => vis(n));
  const chip = (tid) => q('[data-testid="' + tid + '"]');
  const has = (tid) => !!q('[data-testid="' + tid + '"]');
  return {
    state: document.body.dataset.state,
    bar: document.body.dataset.bar,
    chapter: document.body.dataset.chapter,
    cardDisplay: disp(q('#fsCard')),
    filtersDisplay: disp(q('[data-testid="foreshadow-filters"]')),
    barADisplay: disp(q('[data-testid="fs-bar-a"]')),
    barBDisplay: disp(q('[data-testid="fs-bar-b"]')),
    chapterTextDisplay: disp(q('[data-testid="fs-chapter-text"]')),
    chapterStructDisplay: disp(q('[data-testid="fs-chapter-struct"]')),
    rowIds: rows.map((r) => r.getAttribute('data-testid')),
    rowPris: rows.map((r) => Number(r.getAttribute('data-priority'))),
    rowCount: rows.length,
    rowStatuses: rows.map((r) => r.getAttribute('data-status')),
    countA: tx(q('#fs-count')),
    countB: tx(q('#fs-count-b')),
    chipAll: chip('fs-status-chip-all') ? chip('fs-status-chip-all').classList.contains('active') : 'MISSING',
    chipOpen: chip('fs-status-chip-open') ? chip('fs-status-chip-open').classList.contains('active') : 'MISSING',
    chipResolved: chip('fs-status-chip-resolved')
      ? chip('fs-status-chip-resolved').classList.contains('active')
      : 'MISSING',
    searchValue: (q('#fsSearchInput') || { value: 'MISSING' }).value,
    searchVisible: vis(q('#fsSearchInput')),
    searchPlaceholder: attr(q('#fsSearchInput'), 'placeholder'),
    selectedChapter: tx(q('[data-testid="fs-chapter-chip-selected"]')),
    chapterPickerVisible: vis(q('[data-testid="fs-chapter-picker"]')),
    sortLabel: tx(q('#fsSortLabel')),
    sortIcon: attr(q('#fsSortIc'), 'data-ic'),
    noresultDisplay: disp(q('[data-testid="fs-noresult"]')),
    clearBtnVisible: vis(q('[data-testid="fs-clear-filters"]')),
    emptyDisplay: disp(q('[data-testid="library-tab-empty"]')),
    dialogDisplay: disp(q('.dialog-overlay')),
    noteTotal: notes.length,
    notePlansVisible: visibleNotes.map((n) => n.getAttribute('data-plan')),
    noteTextVisible: visibleNotes.map((n) => String(n.textContent || '').replace(/\s+/g, ' ').trim()),
    allNotesAnnotated: notes.every((n) => n.getAttribute('data-design-annotation') === '1'),
    row8HasBadge: has('fs-location-8'),
    row3Badge: tx((q('[data-testid="fs-row-3"]') || {}).querySelector
      ? q('[data-testid="fs-row-3"]').querySelector('.badge')
      : null),
    icons: {
      ic: document.querySelectorAll('[data-ic]').length,
      svg: document.querySelectorAll('[data-ic] svg').length,
    },
    scrollW: document.documentElement.scrollWidth,
    innerW: window.innerWidth,
    demoBar: disp(q('.demo-bar')),
    cardTop: q('#fsCard') ? Math.round(q('#fsCard').getBoundingClientRect().top) : 'MISSING',
    cardBottom: q('#fsCard') ? Math.round(q('#fsCard').getBoundingClientRect().bottom) : 'MISSING',
    errs: window.__errs || [],
  };
};

const P = (fails) => (label, ok) => {
  if (!ok) fails.push(label);
};

const SCENES = [
  {
    id: 'legacy',
    out: 'foreshadow-legacy.png',
    desc: '① 现状对照：无筛选/排序控件（before）',
    check: (d, p) => {
      p('legacy 筛选条隐藏', d.filtersDisplay === 'none');
      p('legacy 仍渲染 8 行', d.rowCount === 8);
      p('legacy 行序 = 优先级降序', JSON.stringify(d.rowPris) === JSON.stringify([90, 75, 60, 55, 45, 40, 30, 20]));
      p('legacy 注释条 = 现状', JSON.stringify(d.notePlansVisible) === JSON.stringify(['legacy']));
    },
  },
  {
    id: 'main',
    out: 'foreshadow-main.png',
    desc: '② 方案 A（chip 组 + 位置文本 + 排序切换）· 推荐默认态',
    check: (d, p) => {
      p('A 形态：bar=a', d.bar === 'A');
      p('A 形态：筛选条可见（未隐藏）', d.filtersDisplay !== 'none' && d.filtersDisplay !== 'MISSING');
      p('A 形态：A 栏显示', d.barADisplay === 'flex');
      p('A 形态：B 栏隐藏', d.barBDisplay === 'none');
      p('A 形态：口径 1 检索输入可见', d.chapterTextDisplay !== 'none' && d.searchVisible === true);
      p('A 形态：口径 2 结构化控件隐藏', d.chapterStructDisplay === 'none');
      p('状态 chip「全部」激活', d.chipAll === true && d.chipOpen === false && d.chipResolved === false);
      p('默认 8 行 / 降序', d.rowCount === 8 && d.rowPris[0] === 90 && d.rowPris[7] === 20);
      p('计数文案（A 栏）', d.countA === '显示 8 / 共 8 条');
      p('计数文案（B 栏同步）', d.countB === '显示 8 / 共 8 条');
      p('排序标签默认 高→低', d.sortLabel === '优先级 高→低');
      p('排序图标 = arrowdown', d.sortIcon === 'arrowdown');
      p('注释条 = 方案 A', JSON.stringify(d.notePlansVisible) === JSON.stringify(['main']));
      p('注释条含「推荐」与零后端改动要点', d.noteTextVisible[0].includes('推荐') && d.noteTextVisible[0].includes('?status='));
    },
  },
  {
    id: 'filter-a',
    out: 'foreshadow-filter-a.png',
    desc: '③ 方案 A 激活：状态 = 未回收 → 8 收窄到 6',
    check: (d, p) => {
      p('「未回收」chip 激活', d.chipOpen === true && d.chipAll === false);
      p('筛选后 6 行', d.rowCount === 6);
      p('筛选后全为 open', d.rowStatuses.every((s) => s === 'open'));
      p('筛选后仍降序', JSON.stringify(d.rowPris) === JSON.stringify([90, 75, 60, 55, 45, 20]));
      p('计数跟随筛选（6/8）', d.countA === '显示 6 / 共 8 条');
      p('注释条 = A 激活态', JSON.stringify(d.notePlansVisible) === JSON.stringify(['filter-a']));
    },
  },
  {
    id: 'filter-b',
    out: 'foreshadow-filter-b.png',
    desc: '④ 方案 B（下拉 + 优先级区间）· 备选形态',
    check: (d, p) => {
      p('B 形态：bar=b', d.bar === 'B');
      p('B 形态：A 栏隐藏', d.barADisplay === 'none');
      p('B 形态：B 栏显示', d.barBDisplay === 'flex');
      p('B 形态：状态下拉在场', d.rowCount >= 0 && d.countB === '显示 8 / 共 8 条');
      p('B 形态：8 行全量', d.rowCount === 8);
      p('注释条 = 方案 B', JSON.stringify(d.notePlansVisible) === JSON.stringify(['filter-b']));
      p('注释条含区间/总口径风险', d.noteTextVisible[0].includes('区间'));
    },
  },
  {
    id: 'search-title',
    out: 'foreshadow-search-title.png',
    desc: '⑤ 检索（拍板项 1）：输入「剑」→ 标题面 4 条 + 位置面 1 条 = 5 条',
    check: (d, p) => {
      p('检索：输入框可见', d.searchVisible === true && d.chapterTextDisplay !== 'none');
      p('检索：查询值回显 = 剑', d.searchValue === '剑');
      p('检索：placeholder 标明两面', String(d.searchPlaceholder).includes('标题'));
      p('检索：命中 5 条', d.rowCount === 5);
      p(
        '检索：命中集 = 标题面 4 + 位置面 1',
        JSON.stringify(d.rowIds) ===
          JSON.stringify(['fs-row-2', 'fs-row-4', 'fs-row-5', 'fs-row-6', 'fs-row-7']),
      );
      p('检索：降序命中优先级', JSON.stringify(d.rowPris) === JSON.stringify([75, 55, 45, 40, 30]));
      p('检索：计数 5/8', d.countA === '显示 5 / 共 8 条');
      p('注释条 = 检索标题面', JSON.stringify(d.notePlansVisible) === JSON.stringify(['search-title']));
      p(
        '注释条同时标注标题面与位置面',
        d.noteTextVisible[0].includes('标题') && d.noteTextVisible[0].includes('位置'),
      );
    },
  },
  {
    id: 'chapter-match-text',
    out: 'foreshadow-chapter-match-text.png',
    desc: '⑥ 口径 1（位置文本）：检索「第 2 章」→ 命中 1 条，漏 2 条',
    check: (d, p) => {
      p('口径 1：输入框可见', d.searchVisible === true && d.chapterTextDisplay !== 'none');
      p('口径 1：结构化控件隐藏', d.chapterStructDisplay === 'none');
      p('口径 1：查询值回显', d.searchValue === '第 2 章');
      p('口径 1：命中 1 条', d.rowCount === 1);
      p('口径 1：命中项 = 林晚照的旧玉佩（id3）', JSON.stringify(d.rowIds) === JSON.stringify(['fs-row-3']));
      p('口径 1：计数 1/8', d.countA === '显示 1 / 共 8 条');
      p('注释条 = 口径 1', JSON.stringify(d.notePlansVisible) === JSON.stringify(['chapter-match-text']));
      p('注释条显式写明「必然漏掉」', d.noteTextVisible[0].includes('漏') && d.noteTextVisible[0].includes('为空'));
    },
  },
  {
    id: 'chapter-match-struct',
    out: 'foreshadow-chapter-match-struct.png',
    desc: '⑦ 口径 2（结构化章节关联）：选「第 2 章」→ 命中 3 条，无漏项',
    check: (d, p) => {
      p('口径 2：chapter=struct', d.chapter === 'struct');
      p('口径 2：文本框隐藏', d.chapterTextDisplay === 'none');
      p('口径 2：结构化控件可见', d.chapterStructDisplay !== 'none' && d.chapterStructDisplay !== 'MISSING');
      p('口径 2：已选章节 chip', d.selectedChapter === '第 2 章');
      p('口径 2：章节选择器在场（视觉过滤后可见）', d.chapterPickerVisible === true);
      p('口径 2：命中 3 条', d.rowCount === 3);
      p(
        '口径 2：含口径 1 漏掉的 id5/id8',
        JSON.stringify(d.rowIds) === JSON.stringify(['fs-row-3', 'fs-row-5', 'fs-row-8']),
      );
      p('口径 2：计数 3/8', d.countA === '显示 3 / 共 8 条');
      p('口径 2：location 为空者不渲染位置徽标（id8）', d.row8HasBadge === false);
      p('注释条 = 口径 2', JSON.stringify(d.notePlansVisible) === JSON.stringify(['chapter-match-struct']));
      p('注释条标明字段已落地但筛选 UI 未实现（#1350/#1429）', d.noteTextVisible[0].includes('#1350') && d.noteTextVisible[0].includes('仍未实现'));
    },
  },
  {
    id: 'sort-asc',
    out: 'foreshadow-sort-asc.png',
    desc: '⑦ 排序控件对侧：优先级升序（低→高）',
    check: (d, p) => {
      p('升序：8 行', d.rowCount === 8);
      p(
        '升序：行序 = 20→90',
        JSON.stringify(d.rowPris) === JSON.stringify([20, 30, 40, 45, 55, 60, 75, 90]),
      );
      p('升序：标签 低→高', d.sortLabel === '优先级 低→高');
      p('升序：图标 = arrowup', d.sortIcon === 'arrowup');
      p('注释条 = 排序升序', JSON.stringify(d.notePlansVisible) === JSON.stringify(['sort-asc']));
    },
  },
  {
    id: 'noresult',
    out: 'foreshadow-noresult.png',
    desc: '⑧ 边界：筛选无结果（已回收 × 「第 2 章」）',
    check: (d, p) => {
      p('无结果：0 行', d.rowCount === 0);
      p('无结果：空态块显示', d.noresultDisplay === 'flex');
      p('无结果：清除筛选入口可见', d.clearBtnVisible === true);
      p('无结果：计数 0/8', d.countA === '显示 0 / 共 8 条');
      p('无结果：不误用「还没有伏笔」空态', d.emptyDisplay === 'none');
      p('注释条 = 无结果', JSON.stringify(d.notePlansVisible) === JSON.stringify(['noresult']));
    },
  },
  {
    id: 'empty',
    out: 'foreshadow-empty.png',
    desc: '⑨ 回归：空态（筛选条随卡片一并隐藏）',
    check: (d, p) => {
      p('空态：卡片隐藏（筛选条随之隐藏）', d.cardDisplay === 'none');
      p('空态：空态块显示', d.emptyDisplay === 'flex');
      p('空态：无可见注释条（卡片内）', d.notePlansVisible.length === 0);
    },
  },
  {
    id: 'create-dialog',
    out: 'foreshadow-create-dialog.png',
    desc: '⑩ 回归：创建伏笔对话框（标题/优先级/位置/描述）',
    check: (d, p) => {
      p('对话框显示', d.dialogDisplay === 'flex');
      p('对话框后仍渲染 8 行', d.rowCount === 8);
      p('列表注释条不与对话框同态显示', d.notePlansVisible.length === 0);
    },
  },
];

function commonChecks(d, p) {
  p('无页面 JS 错误', Array.isArray(d.errs) && d.errs.length === 0);
  p('图标全部渲染（svg === ic）', d.icons.svg === d.icons.ic && d.icons.ic > 0);
  p('无水平滚动', d.scrollW <= d.innerW);
  p('截图态 demo-bar 已隐藏', d.demoBar === 'none');
  p('注释条全部带设计标注属性', d.allNotesAnnotated === true);
  p('注释条总数 = 11（每方案一条；#1429 新增「位置徽标」一条）', d.noteTotal === 11);
  // 卡片隐藏态（空态）无几何值；可见态要求卡片在视口内（#1342）
  p(
    '卡片未被滚出视口（可见时）',
    d.cardDisplay === 'none' || (d.cardTop !== 'MISSING' && d.cardTop >= 40),
  );
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
  await ctx.addInitScript(() => {
    window.__errs = [];
    window.addEventListener('error', (e) => window.__errs.push(String((e && e.message) || e)));
    window.addEventListener('unhandledrejection', (e) =>
      window.__errs.push('PROMISE: ' + ((e.reason && e.reason.message) || e.reason)),
    );
  });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => console.log('PAGEERROR:', String(e)));

  let totalFails = 0;
  for (const scene of SCENES) {
    await page.goto(URL);
    await page.evaluate((s) => {
      document.body.dataset.shot = '1';
      setState(s);
      // #1342：把卡片滚到视口内，防「新增区块在可视区下方 → 断言绿但截图看不见」
      const card = document.getElementById('fsCard');
      if (card) card.scrollIntoView({ block: 'start' });
    }, scene.id);
    await page.waitForTimeout(320);

    const d = await page.evaluate(PROBE);
    const fails = [];
    const p = P(fails);
    scene.check(d, p);
    commonChecks(d, p);

    const shotPath = path.join(ROOT, 'foreshadow', scene.out);
    await page.screenshot({ path: shotPath });
    totalFails += fails.length;
    console.log(
      JSON.stringify(
        {
          scene: scene.id,
          desc: scene.desc,
          shot: shotPath,
          fails,
          rows: d.rowPris,
          note: d.notePlansVisible,
          cardTop: d.cardTop,
          cardBottom: d.cardBottom,
        },
        null,
        2,
      ),
    );
  }

  await browser.close();
  if (totalFails > 0) {
    console.log(`FAIL: 共 ${totalFails} 条断言未通过`);
    process.exit(1);
  }
  console.log(`ALL PASS -> ${SCENES.length} 张截图已输出至 ${path.join(ROOT, 'foreshadow')}`);
})().catch((e) => {
  console.error('SCRIPT ERROR:', e);
  process.exit(2);
});
