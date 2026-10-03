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
  { id: 'graph', out: 'knowledge-graph.png', scroll: 'canvas', desc: '产品默认：着色 A + 折叠面板（展开）+ 类别=全部' },
  { id: 'color-a', out: 'knowledge-graph-color-a.png', scroll: 'bar', desc: '着色 A【采用】· 面板收起 → 画布全宽 + 底部折叠栏' },
  { id: 'color-b', out: 'knowledge-graph-color-b.png', scroll: 'bar', desc: '着色 B【备选】· 面板收起 → 画布全宽 + 底部折叠栏' },
  { id: 'filter-b', out: 'knowledge-graph-filter-b.png', scroll: 'canvas', desc: '筛选 B【采用】· 面板展开 + 角色/角色甲' },
  { id: 'filter-b-collapsed', out: 'knowledge-graph-filter-b-collapsed.png', scroll: 'bar', desc: '筛选 B 折叠态 · 底部折叠栏 + 画布全宽' },
  { id: 'filter-a', out: 'knowledge-graph-filter-a.png', scroll: 'canvas', desc: '筛选 A【备选】· 顶部 chip 组' },
  { id: 'list', out: 'knowledge-list.png', scroll: 'list', desc: '关系列表视图（不筛选）' },
  { id: 'empty', out: 'knowledge-empty.png', scroll: 'empty', desc: '图谱空态' },
  { id: 'relation-form', out: 'knowledge-relation-form.png', scroll: 'none', desc: '新建关系表单' },
  { id: 'drawio-import', out: 'knowledge-drawio-import.png', scroll: 'none', desc: '#1360 导入 drawio 弹层（replace 模式 + 结果回报）' },
];

const SCROLL_TO = {
  canvas: '[data-testid="library-kg-canvas"]',
  /* 折叠态：底部折叠栏在画布之下，若只把画布滚到底，折叠栏会被顶出画面
     （DOM 断言全绿、截图里却没有——「断言 PASS ≠ 用户视角可见」实测再次命中） */
  bar: '[data-testid="library-kg-filterbar"]',
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
      return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, w: r.width };
    };
    const visibleNodes = Array.from(document.querySelectorAll('.kg-node')).filter(
      (el) => el.offsetParent !== null,
    );
    const nodeInfo = visibleNodes.map((el) => ({
      id: el.getAttribute('data-id'),
      type: el.getAttribute('data-type'),
      name: el.getAttribute('data-name'),
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
      barClearBtn: disp('[data-testid="library-kg-filterbar-clear"]'),
      /* 视口可见性（防「断言全绿但截图拍不到」，#1373 实测命中） */
      panelRect: rect('[data-testid="library-kg-filter-panel"]'),
      barRect: rect('[data-testid="library-kg-filterbar"]'),
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

  const isGraphish = ['graph', 'color-a', 'color-b', 'filter-b', 'filter-b-collapsed', 'filter-a'].includes(scene.id);
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
    push(`折叠后画布恢复全宽 > 900（实际 ${Math.round(canvasW)}）`, canvasW > 900);
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
    push(`类别=角色 → 8 个角色节点（实际 ${d.nodes.length}）`, d.nodes.length === 8);
    push('可见节点全为角色类', d.nodes.every((n) => n.type === 'character'));
    push(`类别 chip「角色」激活（实际 ${d.catActive}）`, String(d.catActive).includes('active'));
    push('实体 chip 行可见 8 个', d.entityChipCount === 8);
    push('形态 A：面板与折叠栏都不出现', d.panel === 'none' && d.bar === 'none');
    push('筛选态隐藏节点详情卡', d.detail === 'none');
  }

  if (scene.id === 'filter-b') {
    push('筛选说明条 B 可见（采用态）', d.noteFB && !d.noteFA && !d.noteFC);
    push(`类别=角色 + 实体=角色甲 → 5 个邻接角色（实际 ${d.nodes.length}）`, d.nodes.length === 5);
    push('可见节点全为角色类', d.nodes.every((n) => n.type === 'character'));
    push('面板可见 / 折叠栏隐藏', d.panel !== 'none' && d.bar === 'none');
    push(`面板类别「角色」勾选（实际 ${d.panelCatChecked}）`, d.panelCatChecked === true);
    push(`面板实体「角色甲」勾选（实际 ${d.panelEntityChecked}）`, d.panelEntityChecked === true);
    push(`面板行 = 6 类 + 20 实体（实际 ${d.panelRows}）`, d.panelRows === 26);
    push(`摘要含「角色 · 角色甲 · 显示 5 个实体」（实际 ${d.panelSummary}）`,
      /角色 · 角色甲 · 显示 5 个实体/.test(d.panelSummary));
    push('筛选生效标记已置位', d.filterActive === true);
    push('筛选态隐藏节点详情卡', d.detail === 'none');
  }

  if (scene.id === 'filter-b-collapsed') {
    push('折叠态说明条可见', d.noteFC && !d.noteFA && !d.noteFB);
    push('面板已收起 / 折叠栏接管', d.panel === 'none' && d.bar !== 'none');
    push(`折叠后画布恢复全宽 > 900（实际 ${Math.round(canvasW)}）`, canvasW > 900);
    push(`折叠后筛选仍生效 → 5 个节点（实际 ${d.nodes.length}）`, d.nodes.length === 5);
    push('可见节点全为角色类', d.nodes.every((n) => n.type === 'character'));
    push(`折叠栏摘要含「角色 · 角色甲 · 显示 5 个实体」（实际 ${d.barSummary}）`,
      /角色 · 角色甲 · 显示 5 个实体/.test(d.barSummary));
    push('收起后仍有「展开筛选」+「清除筛选」入口',
      d.expandBtn !== 'none' && d.barClearBtn !== 'none');
    push('筛选生效时折叠栏有 accent 强调（filterActive）', d.filterActive === true);
    push('折叠栏整条在画面内可见（不能只断 display）',
      !!d.barRect && d.barRect.top >= 0 && d.barRect.bottom <= d.viewportH);
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

  await page.evaluate(() => {
    try {
      localStorage.clear();
    } catch (e) {
      /* ignore */
    }
  });
  await page.goto(STATE_URL);
  await page.waitForTimeout(250);
  let d = await probe(page);
  push('① 无记忆时默认：类别=全部 + 面板展开 + 20 节点',
    d.panel !== 'none' && d.bar === 'none' && d.nodes.length === 20 && d.filterActive === false);

  /* 用户在面板里选择：类别=角色 → 实体=角色甲 */
  await page.click('[data-testid="library-kg-filter-panel-cat-character"]');
  await page.waitForTimeout(150);
  await page.click('[data-testid="library-kg-filter-panel-entity-character-2"]');
  await page.waitForTimeout(150);
  d = await probe(page);
  push(`② 选择后筛选生效（角色+角色甲 → 5 节点；实际 ${d.nodes.length}）`, d.nodes.length === 5);
  push(`② 选择即落记忆（实际 ${d.stored}）`,
    typeof d.stored === 'string' && /"category":"character"/.test(d.stored) && /"entity":"character:2"/.test(d.stored));

  /* 折叠：面板消失 + 折叠栏出现 + 筛选保持 */
  await page.click('[data-testid="library-kg-filter-collapse"]');
  await page.waitForTimeout(150);
  d = await probe(page);
  push('③ 点「折叠」→ 面板收起、折叠栏接管、画布全宽、筛选保持 5 节点',
    d.panel === 'none' && d.bar !== 'none' && d.nodes.length === 5 && d.canvasRect.w > 900);

  /* 重新加载：记忆恢复（筛选值 + 面板折叠态） */
  await page.goto(STATE_URL);
  await page.waitForTimeout(300);
  d = await probe(page);
  push('④ 重载后：面板仍折叠 + 筛选仍生效 5 节点 + 折叠栏摘要正确',
    d.panel === 'none' && d.nodes.length === 5 && /角色 · 角色甲/.test(d.barSummary));

  /* 展开 → 面板恢复，勾选态从记忆回填 */
  await page.click('[data-testid="library-kg-filterbar-expand"]');
  await page.waitForTimeout(150);
  d = await probe(page);
  push('⑤ 点「展开筛选」→ 面板恢复 + 勾选态回填',
    d.panel !== 'none' && d.panelCatChecked === true && d.panelEntityChecked === true);

  /* 一键清除 */
  await page.click('[data-testid="library-kg-filter-panel-clear"]');
  await page.waitForTimeout(150);
  d = await probe(page);
  push(`⑥ 一键清除 → 20 节点 + 全部 + filterActive 关（实际 ${d.nodes.length}）`,
    d.nodes.length === 20 && d.filterActive === false);
  push(`⑥ 清除也写入记忆（实际 ${d.stored}）`,
    typeof d.stored === 'string' && /"category":"all"/.test(d.stored));

  /* 清除后重载 → 仍是全部（记忆一致性） */
  await page.goto(STATE_URL);
  await page.waitForTimeout(250);
  d = await probe(page);
  push('⑦ 清除后重载仍为全部 + 20 节点', d.nodes.length === 20 && d.filterActive === false);

  /* 负向：损坏的记忆不应炸页面 */
  await page.evaluate(() => {
    try {
      localStorage.setItem('inkflow:kg:filters:demo-project', '{not json');
      localStorage.setItem('inkflow:kg:panel', '"weird"');
    } catch (e) {
      /* ignore */
    }
  });
  await page.goto(STATE_URL);
  await page.waitForTimeout(250);
  d = await probe(page);
  push('⑧ 记忆损坏 → 静默回退默认（20 节点、面板可用），不抛错',
    d.nodes.length === 20 && d.panel !== 'none');

  await page.evaluate(() => {
    try {
      localStorage.clear();
    } catch (e) {
      /* ignore */
    }
  });
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
