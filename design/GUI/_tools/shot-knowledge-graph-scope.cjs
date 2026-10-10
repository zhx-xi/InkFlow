/* knowledge 原型截图 + 断言
 *   - #1325 图谱/列表/空态/关系表单 + 全量实体开关（工具栏）
 *   - #1373 节点着色（A 色相分层【采用】 / B 邻接着色【备选】）
 *          + 类别/实体筛选（B 左侧面板【采用】+ 底部折叠栏 / A 顶部 chip 组【备选】）
 *          + 选择记忆（localStorage）+ 一键清除筛选 + 折叠不牺牲画布宽度
 * 用法: node design/GUI/_tools/shot-knowledge-graph-scope.cjs
 * playwright 复用 electron 包内依赖（路径自解析，见 _shared.cjs）。
 *
 * 🔴 ROOT / playwright 均自解析——不写死 worktree 绝对路径，
 *    否则在别的 worktree 跑会把图出到主仓（#1361 统一到 _shared.cjs）。
 */
const path = require('path');
const { assertGuiRoot, requirePlaywright, assertPageDir } = require('./_shared.cjs');

const ROOT = assertGuiRoot();
const chromium = requirePlaywright();
assertPageDir('knowledge', ROOT);
const PAGE_FILE = 'knowledge/knowledge.html';
const STATE_URL = 'file:///' + path.join(ROOT, PAGE_FILE).replace(/\\/g, '/');
const VIEWPORT = { width: 1280, height: 800 };
const FILTER_STORE_KEY = 'inkflow:kg:filters:demo-project';

/* 每个场景：状态 + 输出文件名 + 截图前的滚动锚点 */
const SCENES = [
  { id: 'graph', out: 'knowledge-graph.png', scroll: 'canvas', desc: '产品默认：着色 A + 筛选面板（展开）+ 类别全选（#1465）' },
  { id: 'color-a', out: 'knowledge-graph-color-a.png', scroll: 'rail', desc: '着色 A【采用】· 面板收起 → 左侧竖条 + 画布近全宽' },
  { id: 'color-b', out: 'knowledge-graph-color-b.png', scroll: 'rail', desc: '着色 B【备选】· 面板收起 → 左侧竖条 + 画布近全宽' },
  { id: 'filter-b', out: 'knowledge-graph-filter-b.png', scroll: 'canvas', desc: '#1529 实体多选：取消 4 类（留角色+世界观）+ 取消若干实体（4/20 已勾）' },
  { id: 'filter-focus', out: 'knowledge-graph-filter-focus.png', scroll: 'canvas', desc: '#1568 实体定向三态：只选中「角色丁」→ 彩色 + 邻居灰显保位 + 无关节点隐藏' },
  { id: 'entity-page', out: 'knowledge-graph-entity-page.png', scroll: 'canvas', desc: '#1529 实体列表分页：第 2 / 2 页（每页 10 条）' },
  { id: 'collapse-rail-a', out: 'knowledge-graph-filter-rail-a.png', scroll: 'rail', desc: '#1465 折叠态方案 A · 左侧竖条（图标 + 类别圆点 + 清除）' },
  { id: 'collapse-rail-b', out: 'knowledge-graph-filter-rail-b.png', scroll: 'rail', desc: '#1465 折叠态方案 B · 左侧极窄把手' },
  { id: 'filter-a', out: 'knowledge-graph-filter-a.png', scroll: 'canvas', desc: '筛选 A【备选】· 顶部 chip 组' },
  { id: 'list', out: 'knowledge-list.png', scroll: 'list', desc: '关系列表视图（不筛选）' },
  { id: 'empty', out: 'knowledge-empty.png', scroll: 'empty', desc: '图谱空态' },
  { id: 'relation-form', out: 'knowledge-relation-form.png', scroll: 'none', desc: '新建关系表单' },
  { id: 'drawio-import', out: 'knowledge-drawio-import.png', scroll: 'none', desc: '#1360 导入 drawio 弹层（replace 模式 + 结果回报）' },
];

const SCROLL_TO = {
  canvas: '[data-testid="library-kg-canvas"]',
  /* #1465：折叠态改为「左侧竖条」，与画布同一行 —— 滚到画布即可同框 */
  rail: '[data-testid="library-kg-canvas"]',
  list: '[data-testid="library-kg-relation-list"]',
  empty: '[data-testid="library-kg-empty"]',
};

/** 页面侧探针：一次性取回该状态下全部可断言事实（字段对「本页可能没有」一律空安全） */
async function probe(page) {
  return page.evaluate(() => {
    const q = (sel) => document.querySelector(sel);
    const disp = (sel) => {
      const el = q(sel);
      return el ? getComputedStyle(el).display : 'MISSING';
    };
    const rect = (sel) => {
      const el = q(sel);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, w: r.width, h: r.height };
    };
    const visibleNodes = Array.from(document.querySelectorAll('.kg-node')).filter(
      (el) => el.offsetParent !== null,
    );
    const nodeInfo = visibleNodes.map((el) => ({
      id: el.getAttribute('data-id'),
      type: el.getAttribute('data-type'),
      name: el.getAttribute('data-name'),
      dim: el.getAttribute('data-dim') === '1',
      hidden: el.getAttribute('data-hidden') === '1',
      dot: getComputedStyle(el.querySelector('.dot')).backgroundColor,
      bg: getComputedStyle(el).backgroundColor,
    }));
    const edges = Array.from(document.querySelectorAll('.kg-edges path[data-edge]')).map((p) =>
      p.getAttribute('data-edge'),
    );
    const labels = Array.from(document.querySelectorAll('.kg-edges text')).map((t) =>
      t.textContent.trim(),
    );
    const noteShown = (plan) => {
      const el = q('.kg-note[data-plan="' + plan + '"]');
      return el ? getComputedStyle(el).display !== 'none' : false;
    };
    const panelCat = q('[data-testid="library-kg-filter-panel-cat-character"]');
    const panelEntity = q('[data-testid="library-kg-filter-panel-entity-character-2"]');
    return {
      state: document.body.dataset.state,
      dataColor: document.body.dataset.color,
      dataFilterForm: document.body.dataset.filterForm,
      dataPanel: document.body.dataset.panel,
      dataNote: document.body.dataset.note,
      filterActive: document.body.dataset.filterActive === '1',
      icons: document.querySelectorAll('[data-ic]').length,
      svgs: document.querySelectorAll('[data-ic] svg').length,
      scrollW: document.documentElement.scrollWidth,
      innerW: window.innerWidth,
      demoBar: disp('.demo-bar'),
      canvas: disp('[data-testid="library-kg-canvas"]'),
      canvasRect: rect('[data-testid="library-kg-canvas"]'),
      graphView: disp('.view-graph'),
      listView: disp('.view-list'),
      listCard: disp('[data-testid="library-kg-relation-list"]'),
      emptyCard: disp('[data-testid="library-kg-empty"]'),
      dialog: disp('[data-testid="library-kg-relation-form"]'),
      detail: disp('[data-testid="library-kg-node-detail"]'),
      hint: ((q('.kg-tag') || {}).textContent || 'MISSING').trim(),
      legend: disp('[data-testid="library-kg-legend"]'),
      legendItems: document.querySelectorAll('[data-testid="library-kg-legend"] .lg-item').length,
      chipsRow: disp('[data-testid="library-kg-filters"]'),
      panel: disp('[data-testid="library-kg-filter-panel"]'),
      bar: disp('[data-testid="library-kg-filterbar"]'),
      barSummary: ((q('[data-testid="library-kg-filterbar-summary"]') || {}).textContent || 'MISSING').trim(),
      panelSummary: ((q('[data-testid="library-kg-filter-summary"]') || {}).textContent || 'MISSING').trim(),
      collapseBtn: disp('[data-testid="library-kg-filter-collapse"]'),
      expandBtn: disp('[data-testid="library-kg-filterbar-expand"]'),
      expandLabel: ((q('[data-testid="library-kg-filterbar-expand"]') || {}).getAttribute
        ? q('[data-testid="library-kg-filterbar-expand"]').getAttribute('aria-label')
        : 'MISSING'),
      barClearBtn: disp('[data-testid="library-kg-filterbar-clear"]'),
      /* 视口可见性（防「断言全绿但截图拍不到」，#1373 实测命中） */
      panelRect: rect('[data-testid="library-kg-filter-panel"]'),
      barRect: rect('[data-testid="library-kg-filterbar"]'),
      railRect: rect('.kg-rail'),
      railDots: document.querySelectorAll('.kg-rail .rail-dot').length,
      railDotsOff: document.querySelectorAll('.kg-rail .rail-dot.off').length,
      railDotsVisible: Array.from(document.querySelectorAll('.kg-rail .rail-dot')).filter((el) => el.offsetParent !== null).length,
      panelCatsChecked: Array.from(document.querySelectorAll('#panelCats .kf-opt input')).filter((i) => i.checked).length,
      entityRows: (function () { const h = document.getElementById('panelEntities'); return h ? h.querySelectorAll('.kf-opt').length : -1; })(),
      /* #1529：实体列表排序 + 分页事实 */
      entityNames: (function () {
        const h = document.getElementById('panelEntities');
        return h ? Array.from(h.querySelectorAll('.kf-opt .nm')).map((el) => el.textContent) : [];
      })(),
      entityCheckedRows: (function () {
        const h = document.getElementById('panelEntities');
        return h ? Array.from(h.querySelectorAll('.kf-opt input')).filter((i) => i.checked).length : -1;
      })(),
      entityPageBox: disp('[data-testid="library-kg-entity-page"]'),
      entityPageInfo: ((q('[data-testid="library-kg-entity-page-info"]') || {}).textContent || 'MISSING').trim(),
      entityPagePrev: q('[data-testid="library-kg-entity-page-prev"]')
        ? q('[data-testid="library-kg-entity-page-prev"]').disabled : 'MISSING',
      entityPageNext: q('[data-testid="library-kg-entity-page-next"]')
        ? q('[data-testid="library-kg-entity-page-next"]').disabled : 'MISSING',
      entityPageSize: q('[data-testid="library-kg-entity-page-size-select"]')
        ? q('[data-testid="library-kg-entity-page-size-select"]').value : 'MISSING',
      /* #1529：分类块自带的分页条（6 条 → 常态不出现） + 面板是否真的拆成两块 */
      catPageBox: disp('[data-testid="library-kg-cat-page"]'),
      panelBlocks: document.querySelectorAll('[data-testid="library-kg-filter-panel"] > .kf-block').length,
      /* #1529：灰显计数（未勾选 = 保留但降灰；画布节点总数恒为全部）
         #1568：隐藏计数（实体定向三态：无关节点不渲染） */
      dimNodes: document.querySelectorAll('.kg-node[data-dim="1"]').length,
      hiddenNodes: document.querySelectorAll('.kg-node[data-hidden="1"]').length,
      hiddenNames: Array.from(document.querySelectorAll('.kg-node[data-hidden="1"]'))
        .map((el) => el.getAttribute('data-name')).sort(),
      dimEdges: document.querySelectorAll('.kg-edges .kg-dim').length,
      entityChipCount: document.querySelectorAll('[data-testid="library-kg-filter-entity"] .fm-chip').length,
      catActive: (q('[data-testid="library-kg-filter-cat-character"]') || {className:'MISSING'}).className,
      panelCatChecked: panelCat ? panelCat.querySelector('input').checked : 'MISSING',
      panelEntityChecked: panelEntity ? panelEntity.querySelector('input').checked : 'MISSING',
      panelRows: document.querySelectorAll('[data-testid="library-kg-filter-panel"] .kf-opt').length,
      scopeBtn: disp('[data-testid="library-kg-scope-all"]'),
      scopeText: ((q('[data-testid="library-kg-scope-all"]') || {}).textContent || 'MISSING').trim(),
      scopePressed: q('[data-testid="library-kg-scope-all"]')
        ? q('[data-testid="library-kg-scope-all"]').getAttribute('aria-pressed')
        : 'MISSING',
      /* #1360 drawio 导入 / 导出 */
      exportBtn: disp('[data-testid="library-kg-export-drawio"]'),
      importBtn: disp('[data-testid="library-kg-import-drawio"]'),
      exportText: ((q('[data-testid="library-kg-export-drawio"]') || {}).textContent || 'MISSING').trim(),
      importText: ((q('[data-testid="library-kg-import-drawio"]') || {}).textContent || 'MISSING').trim(),
      drawioStatus: disp('[data-testid="library-kg-drawio-status"]'),
      dialogDrawio: disp('[data-testid="library-kg-import-dialog"]'),
      drawioMode: document.body.dataset.drawioMode,
      drawioResult: document.body.dataset.drawioResult,
      replaceAck: q('[data-testid="library-kg-import-replace-ack"]')
        ? q('[data-testid="library-kg-import-replace-ack"]').checked
        : 'MISSING',
      dangerBox: disp('.dlg-danger'),
      resultBox: disp('[data-testid="library-kg-import-result"]'),
      resultText: ((q('[data-testid="library-kg-import-result"]') || {}).textContent || 'MISSING').trim(),
      dialogRect: rect('[data-testid="library-kg-import-dialog"]'),
      noteA: noteShown('color-a'),
      noteB: noteShown('color-b'),
      noteFA: noteShown('filter-a'),
      noteFB: noteShown('filter-b'),
      noteFC: noteShown('filter-collapse'),
      nodes: nodeInfo,
      edges,
      labels,
      stored: (function () {
        try {
          return localStorage.getItem('inkflow:kg:filters:demo-project');
        } catch (e) {
          return 'ERR';
        }
      })(),
      viewportH: window.innerHeight,
    };
  });
}

function parseRgb(s) {
  const m = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(s || '');
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
}
/** 两色的最大单通道差（0-255）：比「字符串不等」更接近「肉眼能否分辨」 */
function maxChannelDelta(a, b) {
  const x = parseRgb(a);
  const y = parseRgb(b);
  if (!x || !y) return -1;
  return Math.max(Math.abs(x[0] - y[0]), Math.abs(x[1] - y[1]), Math.abs(x[2] - y[2]));
}
/** 同类型内个体色的「视觉可辨度」统计（kinds = 实际出现的圆点色种数，#1418 扩槽口径） */
function typeColorSpread(nodes) {
  const byType = {};
  nodes.forEach((n) => {
    (byType[n.type] = byType[n.type] || []).push(n);
  });
  return Object.keys(byType).map((t) => {
    const list = byType[t];
    let maxDot = 0;
    let maxBg = 0;
    for (let i = 0; i < list.length; i += 1) {
      for (let j = i + 1; j < list.length; j += 1) {
        maxDot = Math.max(maxDot, maxChannelDelta(list[i].dot, list[j].dot));
        maxBg = Math.max(maxBg, maxChannelDelta(list[i].bg, list[j].bg));
      }
    }
    const kinds = new Set(list.map((n) => n.dot)).size;
    return { t, n: list.length, maxDot, maxBg, kinds };
  });
}

/** #1529：原型 20 个节点的种子表（id → name，按 NODES 原序） */
const SEED = [
  ['character:8', '角色己'], ['character:2', '角色甲'], ['character:4', '角色庚'], ['character:7', '角色戊'],
  ['character:1', '角色丁'], ['character:3', '角色乙'], ['character:5', '角色丙'], ['character:6', '角色辛'],
  ['world:1', '门派甲'], ['world:4', '地点乙'], ['timeline:2', '下山历练'], ['world:3', '地点甲'],
  ['timeline:1', '夜访地点乙'], ['world:5', '地点乙禁地'], ['world:2', '地点丁'], ['world:6', '地点戊'],
  ['foreshadow:1', '断剑的秘密'], ['foreshadow:2', '师父闭关的真相'], ['outline:1', '事件甲'], ['map_pin:1', '地点己'],
];
const SEED_NAMES = SEED.map(([, n]) => n);
/** 期望排序（与实现同口径：Intl.Collator('zh')，中文出拼音序） */
function pinyinSorted(names) {
  return names.slice().sort((a, b) => new Intl.Collator('zh').compare(a, b));
}
/** 指定类别下的期望实体名序（`filter-b` 面板池 = 角色 + 世界观） */
function seedPoolSorted(types) {
  return pinyinSorted(SEED.filter(([id]) => types.includes(id.split(':')[0])).map(([, n]) => n));
}
/** `filter-b` 已勾选实体；本页（第 1 页）内可见的勾选行数（排序依赖 ICU，故由数据推导而非写死） */
const FB_SELECTED = ['character:1', 'character:2', 'world:1', 'world:3'];
function fbSelectedOnPage1() {
  const page1 = seedPoolSorted(['character', 'world']).slice(0, 10);
  return FB_SELECTED.filter((id) => page1.includes(SEED.find(([i]) => i === id)[1])).length;
}

const ADJ_SAME_TYPE = [
  ['character:2', 'character:1'],
  ['character:2', 'character:3'],
  ['character:2', 'character:5'],
  ['character:2', 'character:6'],
  ['world:1', 'world:3'],
  ['world:1', 'world:4'],
  ['world:3', 'world:2'],
  ['world:3', 'world:6'],
  ['world:4', 'world:5'],
];

function checks(d, scene) {
  const fails = [];
  const push = (label, ok) => {
    if (!ok) fails.push(label);
  };

  /* ── 全场景共有 ── */
  push(`icons ${d.svgs}/${d.icons}`, d.svgs === d.icons);
  push(`horizontal scroll ${d.scrollW}>${d.innerW}`, d.scrollW <= d.innerW);
  push('截图态 demo-bar 已隐藏', d.demoBar === 'none');
  push(`图例可见（实际 ${d.legend}）`, d.legend !== 'none' && d.legend !== 'MISSING');
  push(`图例含 6 类（实际 ${d.legendItems}）`, d.legendItems === 6);
  push(`画布提示=「滚轮缩放 · 拖拽节点」（实际 ${d.hint}）`, d.hint === '滚轮缩放 · 拖拽节点');
  push(`全量实体开关可见（实际 ${d.scopeBtn}）`, d.scopeBtn !== 'none' && d.scopeBtn !== 'MISSING');
  push(`开关文案=「显示全部实体」（实际 ${d.scopeText}）`, d.scopeText === '显示全部实体');
  push(`开关 aria-pressed=false（实际 ${d.scopePressed}）`, d.scopePressed === 'false');
  /* #1360：drawio 导入/导出按钮常驻工具栏（全状态） */
  push(`drawio 导出按钮可见（实际 ${d.exportBtn}）`, d.exportBtn !== 'none' && d.exportBtn !== 'MISSING');
  push(`drawio 导入按钮可见（实际 ${d.importBtn}）`, d.importBtn !== 'none' && d.importBtn !== 'MISSING');
  push(`导出按钮文案=「导出 drawio」（实际 ${d.exportText}）`, d.exportText === '导出 drawio');
  push(`导入按钮文案=「导入 drawio」（实际 ${d.importText}）`, d.importText === '导入 drawio');
  /* 导出状态行只在导出后出现（默认态不占位） */
  push(`导出状态行默认隐藏（实际 ${d.drawioStatus}）`, d.drawioStatus === 'none');

  const canvasTop = d.canvasRect ? d.canvasRect.top : -1;
  const canvasBottom = d.canvasRect ? d.canvasRect.bottom : -1;
  const canvasInView = canvasTop >= 0 && canvasBottom <= d.viewportH;
  const canvasW = d.canvasRect ? d.canvasRect.w : -1;

  const isGraphish = ['graph', 'color-a', 'color-b', 'filter-b', 'filter-focus', 'entity-page', 'filter-b-collapsed', 'filter-a'].includes(scene.id);
  if (isGraphish) {
    push('图谱视图可见 / 列表隐藏', d.graphView !== 'none' && d.listView === 'none');
    push('画布完整落在视口内（截图可见）', canvasInView);
  }
  if (['graph', 'color-a', 'color-b'].includes(scene.id)) {
    push(`边 label 集齐 6 类关系词（实际 ${d.labels.join(',')}）`,
      ['师承', '加入', '管辖', '埋设于', '包含', '参与'].filter((l) => d.labels.includes(l)).length === 6);
  }

  if (scene.id === 'graph') {
    push(`全量节点 20（实际 ${d.nodes.length}）`, d.nodes.length === 20);
    push(`全量边 22（实际 ${d.edges.length}）`, d.edges.length === 22);
    push('详情卡可见（未筛选态）', d.detail !== 'none');
    push('筛选形态 = B（左侧面板）', d.dataFilterForm === 'b');
    push('面板展开可见 / 折叠栏隐藏', d.panel !== 'none' && d.bar === 'none');
    push(`底部有「折叠」按钮（实际 ${d.collapseBtn}）`, d.collapseBtn !== 'none' && d.collapseBtn !== 'MISSING');
    push('默认未筛选（filterActive 关）', d.filterActive === false);
    push(`#1465 类别默认全选 6/6（实际 ${d.panelCatsChecked}/6）`, d.panelCatsChecked === 6);
    push(`#1529 画布全量 20 节点且无一灰显（实体列表第 1 页 10 行；实际 rows=${d.entityRows}/dim=${d.dimNodes}）`,
      d.entityRows === 10 && d.nodes.length === 20 && d.dimNodes === 0);
    push(`#1529 面板拆两块（分类块 / 实体块），各带一条分页条（实际 block=${d.panelBlocks}）`,
      d.panelBlocks === 2 && d.catPageBox !== 'MISSING');
    push(`#1465 分类 6 条 → 分类块分页条不出现（实际 ${d.catPageBox}）`, d.catPageBox === 'none');
    push(`#1529 每页条数可改（默认 10，实际 ${d.entityPageSize}）`, d.entityPageSize === '10');
    push(`#1529 实体列表按拼音排序（实得 ${d.entityNames.join(',')}）`,
      JSON.stringify(d.entityNames) === JSON.stringify(pinyinSorted(SEED_NAMES).slice(0, 10)));
    push(`#1529 分页条出现 + 「1 / 2」（实际 ${d.entityPageInfo}）`,
      d.entityPageBox !== 'none' && /^1 \/ 2$/.test(d.entityPageInfo));
    push(`#1529 首页 prev 禁用 / next 可用（实际 ${d.entityPagePrev}/${d.entityPageNext}）`,
      d.entityPagePrev === true && d.entityPageNext === false);
    push(`#1529 首页 10 行全部勾选（实际 ${d.entityCheckedRows}）`, d.entityCheckedRows === 10);
    push('#1465 面板与画布等高同顶（视觉对齐）',
      !!d.panelRect && !!d.canvasRect && Math.abs(d.panelRect.h - d.canvasRect.h) <= 2 &&
      Math.abs(d.panelRect.top - d.canvasRect.top) <= 2);
    push(`面板摘要含「显示 20 个实体」（实际 ${d.panelSummary}）`, /显示 20 个实体/.test(d.panelSummary));
    push('无方案说明条（默认态即产品形态）', !d.noteA && !d.noteB && !d.noteFA && !d.noteFB && !d.noteFC);
    push('面板整块在画面内可见（不能只断 display）',
      !!d.panelRect && d.panelRect.top >= 0 && d.panelRect.bottom <= d.viewportH);
    /* 「不牺牲画布宽度」的基线：收起后可换回全宽 → 展开态应确实更窄（差异存在，说明折叠有意义） */
    push(`展开态画布宽 < 900（实际 ${Math.round(canvasW)}）`, canvasW > 0 && canvasW < 900);
  }

  if (scene.id === 'color-a' || scene.id === 'color-b') {
    const want = scene.id === 'color-a' ? 'a' : 'b';
    push(`data-color=${want}`, d.dataColor === want);
    push('全量节点 20 / 全量边 22', d.nodes.length === 20 && d.edges.length === 22);
    push('只有本方案说明条可见',
      scene.id === 'color-a' ? d.noteA && !d.noteB : d.noteB && !d.noteA);
    push('筛选说明条不可见', !d.noteFA && !d.noteFB && !d.noteFC);
    /* 着色对照态：面板收起 → 画布恢复全宽（折叠的实际价值，也可看清着色差异） */
    push('面板收起 / 折叠栏接管', d.panel === 'none' && d.bar !== 'none');
    push(`折叠后画布显著变宽（展开态 < 900；实际 ${Math.round(canvasW)}）`, canvasW > 860);
    push('折叠栏本身在画面内可见（不能只断 display）',
      !!d.barRect && d.barRect.top >= 0 && d.barRect.bottom <= d.viewportH);
  }

  if (scene.id === 'color-b') {
    const dotOf = {};
    d.nodes.forEach((n) => {
      dotOf[n.id] = n.dot;
    });
    const same = ADJ_SAME_TYPE.filter((p) => dotOf[p[0]] === dotOf[p[1]]);
    push(`相邻同类型节点全部异色（同色对：${same.join(' / ') || '无'}）`, same.length === 0);
  }

  /* 着色 A 的设计承诺：同类型内个体**肉眼**可辨（判据=最大单通道差，非 rgb 字符串不等） */
  if (d.dataColor === 'a' && d.nodes.length === 20) {
    const spread = typeColorSpread(d.nodes);
    const strong = spread.filter((s) => s.maxDot >= 40 || s.maxBg >= 30);
    console.log(
      `    方案A 个体色差明细 ${spread
        .map((s) => s.t + ':dot' + s.maxDot + '/bg' + s.maxBg + '/kinds' + s.kinds)
        .join(' ')}`,
    );
    push(`同类型内 ≥4 类出现肉眼可辨的个体色差（实际 ${strong.length} 类）`, strong.length >= 4);
    /* #1418 扩槽：6 槽下 8 个角色实染只有 4 色（碰撞组 3+3）→ 12 槽后色种数必须 > 4 */
    const ch = spread.find((s) => s.t === 'character');
    push(
      `#1418 8 个角色圆点色种数 > 4（实际 ${ch ? ch.kinds : 'MISSING'} 色 / ${ch ? ch.n : 0} 节点）`,
      !!ch && ch.n === 8 && ch.kinds > 4,
    );
  }

  if (scene.id === 'filter-a') {
    push('筛选说明条 A 可见（备选态）', d.noteFA && !d.noteFB && !d.noteFC);
    push(`#1465 类别多选（角色+世界观）→ 6 灰显（实际 dim=${d.dimNodes}/${d.nodes.length}）`,
      d.dimNodes === 6 && d.nodes.length === 20);
    push('#1465 正常彩色节点只含已勾选类别',
      d.nodes.filter((n) => !n.dim).every((n) => n.type === 'character' || n.type === 'world'));
    push(`类别 chip「角色」激活（实际 ${d.catActive}）`, String(d.catActive).includes('active'));
    push('实体 chip 行可见 8 个', d.entityChipCount === 8);
    push('形态 A：面板与折叠栏都不出现', d.panel === 'none' && d.bar === 'none');
    push('筛选态隐藏节点详情卡', d.detail === 'none');
  }

  if (scene.id === 'filter-b') {
    push('筛选说明条 B 可见（采用态）', d.noteFB && !d.noteFA && !d.noteFC);
    push(`#1568 实体定向三态：4 彩色 + 13 灰显 + 3 隐藏（可见 ${d.nodes.length}；实际 dim=${d.dimNodes}/hidden=${d.hiddenNodes}）`,
      d.nodes.length === 17 && d.dimNodes === 13 && d.hiddenNodes === 3);
    push(`#1568 隐藏者 = 既未选中也不相连者（实际 ${d.hiddenNames.join(',')}）`,
      JSON.stringify(d.hiddenNames) === JSON.stringify(['角色戊', '角色己', '地点乙禁地'].sort()));
    push('#1529 正常彩色的节点只含已勾选类别（角色/世界观）',
      d.nodes.some((n) => !n.dim) &&
        d.nodes.filter((n) => !n.dim).every((n) => n.type === 'character' || n.type === 'world'));
    push(`#1529 边一律保留、非高亮者降灰（实际 dimEdges=${d.dimEdges}）`, d.dimEdges > 0);
    push('面板可见 / 竖条隐藏', d.panel !== 'none' && d.bar === 'none');
    push(`#1465 面板类别勾选 2/6（实际 ${d.panelCatsChecked}）`, d.panelCatsChecked === 2);
    push(`面板实体「角色甲」勾选（实际 ${d.panelEntityChecked}）`, d.panelEntityChecked === true);
    push(`#1465 实体列表随类别过滤 = 14（角色 8 + 世界观 6）→ 第 1 页 10 行（实际 ${d.entityRows}）`,
      d.entityRows === 10);
    push(`#1529 第 1 页勾选 ${fbSelectedOnPage1()} 行（其余取消）（实际 ${d.entityCheckedRows}）`,
      d.entityCheckedRows === fbSelectedOnPage1());
    push(`摘要含「角色/世界观 · 实体 4/20 · 显示 4 个实体」（实际 ${d.panelSummary}）`,
      /角色\/世界观 · 实体 4\/20 · 显示 4 个实体/.test(d.panelSummary));
    push('筛选生效标记已置位', d.filterActive === true);
    push('筛选态隐藏节点详情卡', d.detail === 'none');
  }

  /* #1568：实体定向三态（聚焦：只选中「角色丁」→ 彩色 + 邻居灰显保位 + 其余隐藏） */
  if (scene.id === 'filter-focus') {
    const colored = d.nodes.filter((n) => !n.dim);
    const dimmed = d.nodes.filter((n) => n.dim);
    push(`#1568 三态：可见仅 2 节点 = 1 彩色 + 1 灰显保位（实际 可见 ${d.nodes.length}/dim=${d.dimNodes}/hidden=${d.hiddenNodes}）`,
      d.nodes.length === 2 && d.dimNodes === 1 && d.hiddenNodes === 18);
    push(`#1568 彩色 = 选中实体「角色丁」（实际 ${colored.map((n) => n.name).join(',')}）`,
      colored.length === 1 && colored[0].name === '角色丁');
    push(`#1568 灰显保位 = 其邻居「角色甲」（实际 ${dimmed.map((n) => n.name).join(',')}）`,
      dimmed.length === 1 && dimmed[0].name === '角色甲');
    push('面板可见 / 竖条隐藏', d.panel !== 'none' && d.bar === 'none');
    push(`摘要含「实体 1/20 · 显示 1 个实体」（实际 ${d.panelSummary}）`,
      /实体 1\/20 · 显示 1 个实体/.test(d.panelSummary));
    push('筛选生效标记已置位', d.filterActive === true);
  }

  /* #1529：实体列表分页（第 2 / 2 页） */
  if (scene.id === 'entity-page') {
    push(`画布不受分页影响 → 仍 20 节点且无灰显（实际 ${d.nodes.length}/dim=${d.dimNodes}）`,
      d.nodes.length === 20 && d.dimNodes === 0);
    push(`分页条 + 「2 / 2」（实际 ${d.entityPageInfo}）`,
      d.entityPageBox !== 'none' && /^2 \/ 2$/.test(d.entityPageInfo));
    push(`末页 prev 可用 / next 禁用（实际 ${d.entityPagePrev}/${d.entityPageNext}）`,
      d.entityPagePrev === false && d.entityPageNext === true);
    push(`第 2 页 10 行（实际 ${d.entityRows}）`, d.entityRows === 10);
    push(`第 2 页 = 拼音序 11-20（实得 ${d.entityNames.join(',')}）`,
      JSON.stringify(d.entityNames) === JSON.stringify(pinyinSorted(SEED_NAMES).slice(10, 20)));
    push(`第 2 页 10 行全部勾选（实际 ${d.entityCheckedRows}）`, d.entityCheckedRows === 10);
    push('分页本身不算筛选生效（类别全选 + 实体全选）', d.filterActive === false);
    push('面板可见（分页控件属面板）', d.panel !== 'none');
  }

  if (scene.id === 'collapse-rail-a' || scene.id === 'collapse-rail-b') {
    push('折叠态说明条可见', d.noteFC && !d.noteFA && !d.noteFB);
    push('#1465 面板已收起 / 左侧竖条接管', d.panel === 'none' && d.bar !== 'none');
    push('#1465 竖条位于画布左侧',
      !!d.railRect && !!d.canvasRect && d.railRect.right <= d.canvasRect.left + 1);
    push(`#1465 竖条与画布等高（rail ${Math.round(d.railRect ? d.railRect.h : -1)} / canvas ${Math.round(d.canvasRect ? d.canvasRect.h : -1)}）`,
      !!d.railRect && !!d.canvasRect && Math.abs(d.railRect.h - d.canvasRect.h) <= 2);
    push('#1465 竖条与画布同顶',
      !!d.railRect && !!d.canvasRect && Math.abs(d.railRect.top - d.canvasRect.top) <= 2);
    push(`#1465 竖条为竖向形态（高 > 宽×3；实际 ${Math.round(d.railRect ? d.railRect.w : -1)}×${Math.round(d.railRect ? d.railRect.h : -1)}）`,
      !!d.railRect && d.railRect.h > d.railRect.w * 3);
    push(`折叠后筛选仍生效 → 14 正常 + 6 灰显（角色 8 + 世界观 6；实际 dim=${d.dimNodes}/${d.nodes.length}）`,
      d.dimNodes === 6 && d.nodes.length === 20);
    push(`竖条摘要含「角色/世界观 · 显示 14 个实体」（实际 ${d.barSummary}）`,
      /角色\/世界观 · 显示 14 个实体/.test(d.barSummary));
    push('收起后仍有「展开筛选」+「清除筛选」入口',
      d.expandBtn !== 'none' && d.barClearBtn !== 'none');
    push(`#1465 展开入口是明确的「展开筛选」按钮（aria-label=${d.expandLabel}）`,
      d.expandLabel === '展开筛选');
    push('筛选生效时竖条有 accent 强调（filterActive）', d.filterActive === true);
    push('竖条整条在画面内可见（不能只断 display）',
      !!d.barRect && d.barRect.top >= 0 && d.barRect.bottom <= d.viewportH);
  }

  if (scene.id === 'collapse-rail-a') {
    push(`#1465 方案 A：竖条列 6 个类别圆点（实际 ${d.railDots}/可见 ${d.railDotsVisible}）`, d.railDots === 6 && d.railDotsVisible === 6);
    push(`#1465 方案 A：取消的 4 类圆点置灰（实际 ${d.railDotsOff}）`, d.railDotsOff === 4);
    push(`#1465 方案 A：竖条宽 46（实际 ${Math.round(d.railRect ? d.railRect.w : -1)}）`,
      !!d.railRect && Math.abs(d.railRect.w - 46) <= 2);
  }
  if (scene.id === 'collapse-rail-b') {
    push(`#1465 方案 B：极窄把手宽 30（实际 ${Math.round(d.railRect ? d.railRect.w : -1)}）`,
      !!d.railRect && Math.abs(d.railRect.w - 30) <= 2);
    push(`#1465 方案 B：类别圆点列表隐藏（仅把手；可见圆点 ${d.railDotsVisible}）`, d.railDotsVisible === 0);
  }

  if (scene.id === 'list') {
    push('列表视图可见 / 图谱视图隐藏', d.listView !== 'none' && d.graphView === 'none');
    push('关系列表可见', d.listCard !== 'none' && d.listCard !== 'MISSING');
    push('决策④：列表不筛选 → 三套控件全隐藏',
      d.chipsRow === 'none' && d.panel === 'none' && d.bar === 'none');
  }

  if (scene.id === 'empty') {
    push('空态画布隐藏', d.canvas === 'none');
    push('空态卡片可见', d.emptyCard !== 'none' && d.emptyCard !== 'MISSING');
    push('空态隐藏筛选控件', d.chipsRow === 'none' && d.panel === 'none' && d.bar === 'none');
  }

  if (scene.id === 'relation-form') {
    push('关系表单弹层可见', d.dialog !== 'none' && d.dialog !== 'MISSING');
  }

  if (scene.id === 'drawio-import') {
    push('drawio 导入弹层可见', d.dialogDrawio !== 'none' && d.dialogDrawio !== 'MISSING');
    push(`模式 = replace（实际 ${d.drawioMode}）`, d.drawioMode === 'replace');
    push(`replace 危险提示露出（实际 ${d.dangerBox}）`, d.dangerBox !== 'none' && d.dangerBox !== 'MISSING');
    push(`确认勾选框已勾（实际 ${d.replaceAck}）`, d.replaceAck === true);
    push(`结果回报可见（实际 ${d.resultBox}）`, d.resultBox !== 'none' && d.resultBox !== 'MISSING');
    push(
      `结果回报含新增/跳过/失败三段（实际 ${d.resultText}）`,
      /新增/.test(d.resultText) && /跳过/.test(d.resultText) && /失败/.test(d.resultText),
    );
    /* 弹层在视口内完整可见（不能只断 display） */
    push('导入弹层完整落在视口内', !!d.dialogRect && d.dialogRect.top >= 0 && d.dialogRect.bottom <= d.viewportH);
  }

  return fails;
}

/* ═══════ 决策②③ 的功能验证：折叠 / 记忆 / 一键清除（真交互，不是看 DOM 存在性） ═══════ */
async function behavioural(page) {
  const fails = [];
  const push = (label, ok) => {
    if (!ok) fails.push(label);
  };

  const reset = () => page.evaluate(() => { try { localStorage.clear(); } catch (e) { /* ignore */ } });

  await reset();
  await page.goto(STATE_URL);
  await page.waitForTimeout(250);
  let d = await probe(page);
  push(`#1465 ① 无记忆默认：类别全选 6/6 + 面板展开 + 20 节点无灰显 + 竖条隐藏（实际 ${d.panelCatsChecked}/${d.nodes.length}/dim${d.dimNodes}）`,
    d.panelCatsChecked === 6 && d.panel !== 'none' && d.bar === 'none' && d.nodes.length === 20 && d.dimNodes === 0 && d.filterActive === false);

  /* 取消「角色」类别 → 画布与实体列表双双去掉 8 个角色 */
  await page.click('[data-testid="library-kg-filter-panel-cat-character"]');
  await page.waitForTimeout(150);
  d = await probe(page);
  push(`#1529 ② 取消角色类 → 8 个角色灰显（画布仍 20 节点；实际 dim=${d.dimNodes}）`,
    d.dimNodes === 8 && d.nodes.length === 20);
  push(`#1465 ② 实体列表同步过滤 → 12 个实体 → 第 1 页 10 行（实际 ${d.entityRows}）`, d.entityRows === 10);
  push(`#1465 ② 记忆写 categories 列表（实际 ${d.stored}）`,
    typeof d.stored === 'string' && /"categories"/.test(d.stored) && !/"character"/.test(d.stored));

  /* 勾回「角色」 → 全选 == 显示全部 */
  await page.click('[data-testid="library-kg-filter-panel-cat-character"]');
  await page.waitForTimeout(150);
  d = await probe(page);
  push(`#1465 ③ 勾回角色 → 恢复 20 节点且无灰显 / 全选 6/6 / filterActive 关（实际 ${d.nodes.length}/dim${d.dimNodes}）`,
    d.nodes.length === 20 && d.dimNodes === 0 && d.panelCatsChecked === 6 && d.filterActive === false);

  /* 取消两类（角色 + 世界观）→ 只剩其余四类 */
  await page.click('[data-testid="library-kg-filter-panel-cat-character"]');
  await page.waitForTimeout(120);
  await page.click('[data-testid="library-kg-filter-panel-cat-world"]');
  await page.waitForTimeout(150);
  d = await probe(page);
  push(`#1529 ④ 取消角色+世界观 → 14 个灰显（大纲1+时间线2+伏笔2+地图标记1 正常；实际 dim=${d.dimNodes}）`,
    d.dimNodes === 14 && d.panelCatsChecked === 4);

  /* 折叠 → 左侧竖条 + 画布变宽 + 筛选保持 */
  const wOpen = d.canvasRect ? d.canvasRect.w : -1;
  await page.click('[data-testid="library-kg-filter-collapse"]');
  await page.waitForTimeout(150);
  d = await probe(page);
  push(`#1465 ⑤ 折叠 → 面板收起 / 竖条接管 / 竖条在画布左侧 / 画布变宽（${Math.round(wOpen)} → ${Math.round(d.canvasRect ? d.canvasRect.w : -1)}）`,
    d.panel === 'none' && d.bar !== 'none' && !!d.railRect && !!d.canvasRect &&
    d.railRect.right <= d.canvasRect.left + 1 && d.canvasRect.w > wOpen + 100);
  push(`#1465 ⑤ 折叠不牺牲筛选 → 仍 14 灰显 + 竖条摘要正确（实际 dim=${d.dimNodes} / ${d.barSummary}）`,
    d.dimNodes === 14 && /显示 6 个实体/.test(d.barSummary));

  /* 重载 → 记忆恢复（4 类 + 面板折叠） */
  await page.goto(STATE_URL);
  await page.waitForTimeout(300);
  d = await probe(page);
  push(`#1465 ⑥ 重载按记忆恢复：仍折叠 + 4 类 + 14 灰显（实际 ${d.panelCatsChecked}/dim${d.dimNodes}）`,
    d.panel === 'none' && d.dimNodes === 14 && d.panelCatsChecked === 4);

  /* 展开 → 面板恢复 + 勾选态回填 */
  await page.click('[data-testid="library-kg-filterbar-expand"]');
  await page.waitForTimeout(150);
  d = await probe(page);
  push(`#1465 ⑦ 展开筛选 → 面板恢复 + 4/6 勾选回填（实际 ${d.panelCatsChecked}）`,
    d.panel !== 'none' && d.panelCatsChecked === 4);

  /* 一键清除 → 全选 + 20 节点 */
  await page.click('[data-testid="library-kg-filter-panel-clear"]');
  await page.waitForTimeout(150);
  d = await probe(page);
  push(`#1465 ⑧ 一键清除 → 20 节点无灰显 + 全选 6/6 + filterActive 关（实际 dim=${d.dimNodes}/${d.panelCatsChecked}）`,
    d.nodes.length === 20 && d.dimNodes === 0 && d.panelCatsChecked === 6 && d.filterActive === false);
  push(`#1465 ⑧ 清除即写记忆 categories 全 6（实际 ${d.stored}）`,
    typeof d.stored === 'string' && /"categories"/.test(d.stored));

  /* 损坏记忆 → 静默回退默认 */
  await page.evaluate(() => {
    try {
      localStorage.setItem('inkflow:kg:filters:demo-project', '{not json');
      localStorage.setItem('inkflow:kg:panel', '"weird"');
    } catch (e) { /* ignore */ }
  });
  await page.goto(STATE_URL);
  await page.waitForTimeout(250);
  d = await probe(page);
  push(`#1465 ⑨ 记忆损坏 → 静默回退默认（20 节点无灰显 / 全选 / 面板可用）`,
    d.nodes.length === 20 && d.dimNodes === 0 && d.panelCatsChecked === 6 && d.panel !== 'none');

  /* 旧格式记忆（单选 category）→ 兼容为「只勾该类」 */
  await page.evaluate(() => {
    try {
      localStorage.setItem('inkflow:kg:filters:demo-project', JSON.stringify({ category: 'character', entity: null }));
    } catch (e) { /* ignore */ }
  });
  await page.goto(STATE_URL);
  await page.waitForTimeout(250);
  d = await probe(page);
  push(`#1465 ⑩ 旧记忆（category=character）向后兼容 → 只勾 1 类 / 12 个灰显（实际 ${d.panelCatsChecked}/dim${d.dimNodes}）`,
    d.panelCatsChecked === 1 && d.dimNodes === 12);

  /* #1529 实体多选：取消一个实体 → 该实体隐藏（与类别语义一致）+ filterActive 开 */
  await reset();
  await page.goto(STATE_URL);
  await page.waitForTimeout(250);
  d = await probe(page);
  const firstEntityName = d.entityNames[0];
  push(`#1529 ⑪ 默认实体全选（第 1 页 10 行全勾；实际 ${d.entityCheckedRows}/10）`, d.entityCheckedRows === 10);
  await page.click('#panelEntities .kf-opt:first-child');
  await page.waitForTimeout(150);
  d = await probe(page);
  push(`#1529 ⑪ 取消「${firstEntityName}」→ 该节点灰显、画布仍 20 节点 + filterActive 开（实际 dim=${d.dimNodes}/${d.nodes.length}/${d.filterActive}）`,
    d.dimNodes === 1 && d.nodes.length === 20 && d.entityCheckedRows === 9 && d.filterActive === true);
  push(`#1529 ⑪ 取消实体即写记忆 entities 数组（实际 ${d.stored}）`,
    typeof d.stored === 'string' && /"entities"/.test(d.stored));

  /* #1529 实体列表排序 + 分页（真交互） */
  await reset();
  await page.goto(STATE_URL);
  await page.waitForTimeout(250);
  d = await probe(page);
  push(`#1529 ⑫ 首页 = 拼音序第 1-10（实得 ${d.entityNames.join(',')}）`,
    JSON.stringify(d.entityNames) === JSON.stringify(pinyinSorted(SEED_NAMES).slice(0, 10)));
  await page.click('[data-testid="library-kg-entity-page-next"]');
  await page.waitForTimeout(150);
  d = await probe(page);
  push(`#1529 ⑫ 点下一页 → 「2 / 2」+ 行 = 拼音序 11-20（实际 ${d.entityPageInfo}）`,
    /^2 \/ 2$/.test(d.entityPageInfo) &&
    JSON.stringify(d.entityNames) === JSON.stringify(pinyinSorted(SEED_NAMES).slice(10, 20)));
  push(`#1529 ⑫ 末页 next 禁用 / prev 可用（实际 ${d.entityPageNext}/${d.entityPagePrev}）`,
    d.entityPageNext === true && d.entityPagePrev === false);

  await reset();
  return fails;
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  await page.goto(STATE_URL);
  await page.waitForTimeout(300);

  let totalFails = 0;
  for (const scene of SCENES) {
    /* 🔴 file:// 同文档导航不重载 → 每个场景显式 setState，不依赖 hash */
    await page.evaluate((s) => { setState(s); }, scene.id);
    await page.evaluate(() => { document.body.dataset.shot = '1'; });
    await page.waitForTimeout(250);
    const sel = SCROLL_TO[scene.scroll];
    if (sel) {
      /* 🔴 可滚动页面：把目标区块滚入视口（block:'end' → 画布完整 + 上方工具栏/筛选行仍在画面内） */
      await page.evaluate((s) => {
        const el = document.querySelector(s);
        if (el) el.scrollIntoView({ block: 'end' });
      }, sel);
      await page.waitForTimeout(200);
    }
    await page.evaluate((s) => { setState(s); }, scene.id);
    await page.evaluate(() => { document.body.dataset.shot = '1'; });
    await page.waitForTimeout(150);

    const out = path.join(ROOT, 'knowledge', scene.out);
    await page.screenshot({ path: out });
    const d = await probe(page);
    const fails = checks(d, scene);

    /* 幂等性/稳定性：同状态重放一次，逐节点色值必须逐位相同
       （防「着色用了随机数 / hash 不稳定」这类会毁掉「同实体永远同色」承诺的实现） */
    const first = d.nodes.map((n) => n.id + '=' + n.dot).join(',');
    await page.evaluate((s) => { setState(s); }, scene.id);
    await page.waitForTimeout(120);
    const d2 = await probe(page);
    const second = d2.nodes.map((n) => n.id + '=' + n.dot).join(',');
    if (first !== second) fails.push('同状态重放后节点色值不稳定（着色非确定性）');

    if (fails.length) {
      totalFails += fails.length;
      console.log(`[${scene.id}] FAIL: ${fails.join(' | ')}`);
    } else {
      console.log(`[${scene.id}] OK -> ${scene.out}`);
    }
    console.log(
      `    visible=${d.nodes.length} edges=${d.edges.length} form=${d.dataFilterForm} color=${d.dataColor} panel=${d.dataPanel} bar=${d.bar === 'none' ? 'off' : 'on'} canvasW=${Math.round(canvasW(d))}`,
    );
  }

  const bFails = await behavioural(page);
  totalFails += bFails.length;
  console.log(bFails.length ? `[behaviour] FAIL: ${bFails.join(' | ')}` : '[behaviour] OK 折叠 / 记忆 / 一键清除 全通');

  await browser.close();
  console.log(totalFails ? `TOTAL FAILS: ${totalFails}` : 'ALL PASS');
  process.exit(totalFails ? 1 : 0);
})().catch((e) => { console.error('SCRIPT ERROR:', e); process.exit(2); });

function canvasW(d) {
  return d.canvasRect ? d.canvasRect.w : -1;
}
