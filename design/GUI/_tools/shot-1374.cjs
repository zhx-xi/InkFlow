/*
 * 时间线原型：「叙事序 / 世界序 / 世界序·纪元轴」截图 + 结构断言。
 *
 * 沿革：
 *   #1323 形态断言（两序共用章分组容器）→ #1374 取代（双序轴向语义分流）
 *   → #1353 取代：#1374 的「方案 B 演示态 world-b」正式落地为 0.16.0 实现形态：
 *     状态 world-b → `world-eras`（默认：仅主力轴）/ `world-eras-multi`（多轴同时显示）。
 *   → #1467（本批）取代：#1353 的「行内逐行重复轴名」形态 → 纪元轴**组头只显示一次轴名**，
 *     组内按时间刻度分层（`tl-timenode-<axisKey>-<i>`，同刻度事件归属同一时间节点、缩进一级）；
 *     另加**对照态 `world-eras-b`**（组头 + 行内时间刻度、不合并同刻度），供评审二选一。
 *
 * 状态集（与 timeline.html 的 demo-bar 一致）：
 *   narrative          叙事序 · 章为轴（章刻度 + 章下事件；行内小字=世界内时间）
 *   narrative-filter   叙事序 + 按章筛选面板展开（已选第十二章 → 列表仅 c12）
 *   world              世界序 · 单轴（项目无纪元数据时的形态；此处演示「时间轴」本体）
 *   world-eras         世界序 · 纪元轴族（默认只勾选主力轴 → 1 条泳道 + 3 chips）
 *   world-eras-multi   世界序 · 纪元轴族（全部轴勾选 → 3 条泳道，含默认轴「未分纪元」）
 *   world-eras-b       世界序 · 纪元轴族（对照方案 B：组头 + 行内时间刻度，不合并同刻度）
 *   empty              空态
 *
 * 用法: node design/GUI/_tools/shot-1374.cjs
 * 路径自解析（ROOT / playwright 均从脚本位置推导），见 _shared.cjs（#1361）。
 */
const path = require('path');
const { assertGuiRoot, requirePlaywright, assertPageDir } = require('./_shared.cjs');

const ROOT = assertGuiRoot();
const chromium = requirePlaywright();
assertPageDir('timeline', ROOT);

const SHOTS = [
  { state: 'narrative', out: 'timeline-narrative.png' },
  { state: 'narrative-filter', out: 'timeline-narrative-filter.png' },
  { state: 'world', out: 'timeline-world.png' },
  { state: 'world-eras', out: 'timeline-world-eras.png' },
  { state: 'world-eras-multi', out: 'timeline-world-eras-multi.png' },
  { state: 'world-eras-b', out: 'timeline-world-eras-b.png' },
  { state: 'empty', out: 'timeline-empty.png' },
];

/* 共享探针：所有字段对「本页可能没有」空安全（缺元素 -> null / 0，不炸 evaluate） */
async function probe(page) {
  return page.evaluate(() => {
    const q = (s) => document.querySelector(s);
    const qa = (s) => Array.from(document.querySelectorAll(s));
    const txt = (el) => (el ? el.textContent.trim() : null);
    const ids = (root, sel) =>
      Array.from(root.querySelectorAll(sel)).map((n) =>
        n.dataset.testid.replace('tl-axis-node-', ''),
      );
    /* #1467：轴主体内某个轴名的**可见**出现次数（innerText 受 CSS 影响，隐藏文案不计） */
    const bodyText = q('#tlBody') ? q('#tlBody').innerText : '';
    const nameCount = (name) => (name ? bodyText.split(name).length - 1 : 0);
    /* #1467：某轴泳道内的时间节点（标签 + 该节点下事件 id），按 DOM 顺序 */
    const timeNodesOf = (key) => {
      const lane = q(`[data-testid="tl-lane-${key}"]`);
      if (!lane) return [];
      return Array.from(lane.querySelectorAll('[data-testid^="tl-tick-"]')).map((lab) => {
        const node = lab.closest('.tl-timenode');
        const host = node ? node.querySelector('.tl-timenode-events') : null;
        return {
          label: lab.textContent.trim(),
          ids: host ? ids(host, '[data-testid^="tl-axis-node-"]') : [],
          indented: host ? getComputedStyle(host).paddingLeft : 'MISSING',
        };
      });
    };
    const laneOf = (key) => q(`[data-testid="tl-lane-${key}"]`);
    const laneIds = (key) => {
      const lane = laneOf(key);
      return lane ? ids(lane, '[data-testid^="tl-axis-node-"]') : [];
    };
    const chipOf = (key) => q(`[data-testid="tl-axis-chip-${key}"]`);
    /* #1467 几何：主轴轴线 / 时间刻度点 / 缩进事件点 是否落在同一条竖线上（视觉对齐的数值判据） */
    const geom = (() => {
      const lane = q('[data-testid="tl-lane-qingyuan"]');
      if (!lane) return null;
      const axis = lane.querySelector('.tl-axis--time');
      const tn = lane.querySelector('.tl-timenode');
      const head = tn ? tn.querySelector('.tl-timenode-head') : null;
      const evts = tn ? tn.querySelector('.tl-timenode-events') : null;
      const node = evts ? evts.querySelector('.tl-node') : null;
      const round1 = (v) => Math.round(v * 10) / 10;
      return {
        axisLine: axis ? round1(axis.getBoundingClientRect().left + 6 + 1) : null,
        tickDot: head ? round1(head.getBoundingClientRect().left - 23 + 4) : null,
        guideLine: evts ? round1(evts.getBoundingClientRect().left + 8 + 1) : null,
        eventDot: node ? round1(node.getBoundingClientRect().left - 17 + 4) : null,
      };
    })();
    const axis = q('[data-testid="tl-axis"]');
    const nodes = qa('[data-testid^="tl-axis-node-"]');
    const groups = qa('[data-testid^="tl-chgroup-"]');
    const ticks = qa('[data-testid^="tl-chtick-"]');
    const nodeIds = nodes.map((n) => n.dataset.testid.replace('tl-axis-node-', ''));
    return {
      state: document.body.dataset.state,
      icons: qa('[data-ic]').length,
      svgs: qa('[data-ic] svg').length,
      scrollW: document.documentElement.scrollWidth,
      innerW: window.innerWidth,
      axisExists: !!axis,
      chapterAxis: !!axis && axis.classList.contains('tl-axis--chapter'),
      timeAxis: !!axis && axis.classList.contains('tl-axis--time'),
      lanesWrap: !!q('.tl-lanes'),
      tickTexts: ticks.map((t) => txt(t.querySelector('.tl-chlabel'))),
      groupKeys: groups.map((g) => g.dataset.testid.replace('tl-chgroup-', '')),
      nodeIds,
      nodeCount: nodeIds.length,
      dup: nodeIds.length - new Set(nodeIds).size,
      main1: txt(q('[data-testid="tl-axis-main-1"]')),
      main1Cls: (q('[data-testid="tl-axis-main-1"]') || { className: '' }).className,
      main2: txt(q('[data-testid="tl-axis-main-2"]')),
      main2Cls: (q('[data-testid="tl-axis-main-2"]') || { className: '' }).className,
      src1: txt(q('[data-testid="tl-src-1"]')),
      src5: txt(q('[data-testid="tl-src-5"]')),
      laneCount: qa('.tl-lane').length,
      laneAxisCount: qa('.tl-lane .tl-axis--time').length,
      laneQyIds: laneIds('qingyuan'),
      laneNoneIds: laneIds('none'),
      laneXianjieIds: laneIds('xianjie'),
      laneNoneName: txt(q('[data-testid="tl-lane-none"] .tl-lane-name')),
      /* #1467：轴名分组头 + 时间刻度节点 */
      laneNameCount: qa('[data-testid^="tl-lanehead-"]').length,
      laneMainCount: qa('.tl-lane [data-testid^="tl-axis-main-"]').length,
      timeNodes: qa('.tl-timenode').length,
      tnQy: timeNodesOf('qingyuan'),
      tnNone: timeNodesOf('none'),
      tnXianjie: timeNodesOf('xianjie'),
      qyNameCount: nameCount('示例界 · 示例历'),
      xjNameCount: nameCount('示例仙界 · 示例仙历'),
      noneNameCount: nameCount('未分纪元'),
      chipCount: qa('[data-testid^="tl-axis-chip-"]').length,
      chipOn: qa('[data-testid^="tl-axis-chip-"].on').length,
      chipPressed: {
        qingyuan: chipOf('qingyuan') ? chipOf('qingyuan').getAttribute('aria-pressed') : null,
        none: chipOf('none') ? chipOf('none').getAttribute('aria-pressed') : null,
        xianjie: chipOf('xianjie') ? chipOf('xianjie').getAttribute('aria-pressed') : null,
      },
      pickerDisplay: q('[data-testid="tl-axis-picker"]')
        ? getComputedStyle(q('[data-testid="tl-axis-picker"]')).display
        : 'MISSING',
      c12Ids: (() => {
        const g = q('[data-testid="tl-chgroup-c12"]');
        return g ? ids(g, '[data-testid^="tl-axis-node-"]') : [];
      })(),
      filterBtnOn: !!q('#filterChapterBtn') && q('#filterChapterBtn').classList.contains('on'),
      filterLabel: txt(q('#filterChapterLabel')),
      panelDisplay: q('#filterChapterPanel') ? getComputedStyle(q('#filterChapterPanel')).display : 'MISSING',
      fpItems: qa('[data-testid^="tl-fp-item-"]').length,
      emptyDisplay: q('[data-testid="library-tab-empty"]')
        ? getComputedStyle(q('[data-testid="library-tab-empty"]')).display
        : 'MISSING',
      toolbarDisplay: q('[data-testid="timeline-toolbar"]')
        ? getComputedStyle(q('[data-testid="timeline-toolbar"]')).display
        : 'MISSING',
      legend: txt(q('[data-testid="tl-legend"]')),
      geom,
    };
  });
}

const QY = '示例界 · 示例历';
const XJ = '示例仙界 · 示例仙历';

function checkAll(d, state) {
  const fails = [];
  const chk = (label, cond) => { if (!cond) fails.push(label); };

  chk(`icons ${d.svgs}/${d.icons}`, d.icons === d.svgs && d.icons > 0);
  chk(`horizontal scroll ${d.scrollW}>${d.innerW}`, d.scrollW <= d.innerW);
  chk(`body[data-state]=${state}（实际 ${d.state}）`, d.state === state);

  if (state === 'narrative' || state === 'narrative-filter') {
    const isFilter = state === 'narrative-filter';
    chk('章轴容器（tl-axis--chapter）', d.chapterAxis);
    chk('世界序专属：无轴选择器', d.pickerDisplay === 'none');
    chk(`无泳道（实际 ${d.laneCount}）`, d.laneCount === 0);
    const expTicks = isFilter
      ? ['第十二章 夜访地点乙']
      : ['第十一章 事件乙', '第十二章 夜访地点乙', '第十三章 事件甲', '未分章'];
    chk(`章刻度=${JSON.stringify(expTicks)}（实际 ${JSON.stringify(d.tickTexts)}）`,
      JSON.stringify(d.tickTexts) === JSON.stringify(expTicks));
    const expNodes = isFilter ? 2 : 6;
    chk(`事件数=${expNodes} 且无重复（实际 ${d.nodeCount} dup=${d.dup}）`,
      d.nodeCount === expNodes && d.dup === 0);
    if (!isFilter) {
      chk(`行内时间小字=示例历 17 年（实际 ${d.main1}）`, d.main1 === '示例历 17 年');
      chk('时间小字为降级态（tl-main--dim）', String(d.main1Cls).includes('tl-main--dim'));
      chk(`c12 组内章内序=['2','3']（实际 ${JSON.stringify(d.c12Ids)}）`,
        JSON.stringify(d.c12Ids) === JSON.stringify(['2', '3']));
      chk(`筛选标签=章：全部（实际 ${d.filterLabel}）`, d.filterLabel === '章：全部');
    } else {
      chk(`行内时间小字=示例历 217 年（实际 ${d.main2}）`, d.main2 === '示例历 217 年');
      chk('时间小字为降级态（tl-main--dim）', String(d.main2Cls).includes('tl-main--dim'));
      chk('筛选钮 on 态', d.filterBtnOn === true);
      chk(`筛选面板展开（实际 ${d.panelDisplay}）`, d.panelDisplay !== 'none' && d.panelDisplay !== 'MISSING');
      chk(`面板选项=5（实际 ${d.fpItems}）`, d.fpItems === 5);
      chk(`筛选标签=章：第十二章（实际 ${d.filterLabel}）`, d.filterLabel === '章：第十二章');
    }
  }

  if (state === 'world') {
    chk('时间轴容器（tl-axis--time）', d.timeAxis);
    chk(`无章分组（实际 ${d.groupKeys.length}）`, d.groupKeys.length === 0);
    chk(`无纪元泳道（实际 ${d.laneCount}）`, d.laneCount === 0);
    chk(`无纪元时间节点（实际 ${d.timeNodes}）`, d.timeNodes === 0);
    chk(`事件序=时间升序（未知末尾）[1..4,6,5]（实际 ${JSON.stringify(d.nodeIds)}）`,
      JSON.stringify(d.nodeIds) === JSON.stringify(['1', '2', '3', '4', '6', '5']));
    chk(`时间刻度 tl-axis-main-1=示例历 17 年（实际 ${d.main1}）`, d.main1 === '示例历 17 年');
    chk(`来源章小字 tl-src-1=第十一章…（实际 ${d.src1}）`, d.src1 === '第十一章 事件乙');
    chk(`来源章小字 tl-src-5=未分章（实际 ${d.src5}）`, d.src5 === '未分章');
    chk(`事件数=6 且无重复（实际 ${d.nodeCount}）`, d.nodeCount === 6 && d.dup === 0);
  }

  if (state === 'world-eras' || state === 'world-eras-multi') {
    const isMulti = state === 'world-eras-multi';
    chk(`轴选择器可见（实际 ${d.pickerDisplay}）`, d.pickerDisplay !== 'none' && d.pickerDisplay !== 'MISSING');
    chk(`轴 chips=3（实际 ${d.chipCount}）`, d.chipCount === 3);
    chk(`勾选数=${isMulti ? 3 : 1}（实际 ${d.chipOn}）`, d.chipOn === (isMulti ? 3 : 1));
    chk(`默认轴 chip 勾选态=${isMulti}（实际 ${d.chipPressed.none}）`,
      d.chipPressed.none === String(isMulti));
    chk(`主力轴 chip 勾选态=true（实际 ${d.chipPressed.qingyuan}）`, d.chipPressed.qingyuan === 'true');
    chk(`泳道=${isMulti ? 3 : 1}（实际 ${d.laneCount}）`, d.laneCount === (isMulti ? 3 : 1));
    chk(`泳道内时间轴=${isMulti ? 3 : 1}（实际 ${d.laneAxisCount}）`, d.laneAxisCount === (isMulti ? 3 : 1));
    chk(`组头数=泳道数（实际 ${d.laneNameCount}）`, d.laneNameCount === (isMulti ? 3 : 1));
    chk(`主力轴泳道序=['1','2','3','4']（实际 ${JSON.stringify(d.laneQyIds)}）`,
      JSON.stringify(d.laneQyIds) === JSON.stringify(['1', '2', '3', '4']));
    chk(`无章分组（实际 ${d.groupKeys.length}）`, d.groupKeys.length === 0);
    chk(`图例含「纪元」（实际 ${d.legend}）`, String(d.legend).includes('纪元'));
    /* #1467 回归锁定：轴名做组头只出现一次（不再逐行重复） */
    chk(`轴名「${QY}」在轴主体内只出现 1 次（实际 ${d.qyNameCount}）`, d.qyNameCount === 1);
    chk(`组内事件行不再重复时间刻度（lane 内 tl-axis-main 数=${d.laneMainCount}）`, d.laneMainCount === 0);
    /* #1467 树状层级：时间节点 + 同刻度合并 + 缩进 */
    chk(`主力轴时间节点=3（实际 ${d.tnQy.length}）`, d.tnQy.length === 3);
    chk(`时间刻度=[示例历 17 年, 示例历 217 年, 示例历 314 年]（实际 ${JSON.stringify(d.tnQy.map((n) => n.label))}）`,
      JSON.stringify(d.tnQy.map((n) => n.label)) === JSON.stringify(['示例历 17 年', '示例历 217 年', '示例历 314 年']));
    chk(`同刻度合并：217 年节点下=['2','3']（实际 ${JSON.stringify(d.tnQy[1] ? d.tnQy[1].ids : null)}）`,
      JSON.stringify(d.tnQy[1] ? d.tnQy[1].ids : null) === JSON.stringify(['2', '3']));
    chk(`单刻度节点下仅 1 个事件（实际 ${JSON.stringify(d.tnQy[0] ? d.tnQy[0].ids : null)}）`,
      JSON.stringify(d.tnQy[0] ? d.tnQy[0].ids : null) === JSON.stringify(['1']));
    chk(`事件行缩进（tl-timenode-events padding-left=${d.tnQy[0] ? d.tnQy[0].indented : 'MISSING'}）`,
      d.tnQy[0] ? d.tnQy[0].indented !== '0px' && d.tnQy[0].indented !== 'MISSING' : false);
    const g = d.geom || {};
    chk(`时间刻度点与主轴轴线同线（${g.tickDot} vs ${g.axisLine}）`,
      g.tickDot !== null && g.tickDot === g.axisLine);
    chk(`缩进事件点与组内引导线同线（${g.eventDot} vs ${g.guideLine}）`,
      g.eventDot !== null && g.guideLine !== null && g.eventDot === g.guideLine);
    chk(`树状层级：事件点右移于刻度点（${g.eventDot} > ${g.tickDot}）`,
      g.eventDot !== null && g.tickDot !== null && g.eventDot > g.tickDot);
    if (isMulti) {
      chk(`示例仙历泳道=['6']（实际 ${JSON.stringify(d.laneXianjieIds)}）`,
        JSON.stringify(d.laneXianjieIds) === JSON.stringify(['6']));
      chk(`默认轴泳道=['5']（实际 ${JSON.stringify(d.laneNoneIds)}）`,
        JSON.stringify(d.laneNoneIds) === JSON.stringify(['5']));
      chk(`默认轴泳道名=未分纪元（实际 ${d.laneNoneName}）`, String(d.laneNoneName).includes('未分纪元'));
      chk(`事件数=6 且无重复（实际 ${d.nodeCount} dup=${d.dup}）`, d.nodeCount === 6 && d.dup === 0);
      chk(`时间刻度回退：示例仙历节点=1024年（实际 ${JSON.stringify(d.tnXianjie.map((n) => n.label))}）`,
        JSON.stringify(d.tnXianjie.map((n) => n.label)) === JSON.stringify(['1024年']));
      chk(`默认轴节点=未知（实际 ${JSON.stringify(d.tnNone.map((n) => n.label))}）`,
        JSON.stringify(d.tnNone.map((n) => n.label)) === JSON.stringify(['未知']));
      chk(`轴名「${XJ}」在轴主体内只出现 1 次（实际 ${d.xjNameCount}）`, d.xjNameCount === 1);
      chk(`默认轴名在轴主体内的出现次数 = 1（泳道头，实际 ${d.noneNameCount}）`, d.noneNameCount === 1);
    }
  }

  if (state === 'world-eras-b') {
    chk(`轴选择器可见（实际 ${d.pickerDisplay}）`, d.pickerDisplay !== 'none' && d.pickerDisplay !== 'MISSING');
    chk(`泳道=1（实际 ${d.laneCount}）`, d.laneCount === 1);
    chk(`无时间节点（对照 B 不合并同刻度，实际 ${d.timeNodes}）`, d.timeNodes === 0);
    chk(`轴名「${QY}」在轴主体内只出现 1 次（实际 ${d.qyNameCount}）`, d.qyNameCount === 1);
    chk(`组内事件行**行内**显示时间刻度（tl-axis-main 数=${d.laneMainCount}）`, d.laneMainCount === 4);
    chk(`行内时间刻度 tl-axis-main-1=示例历 17 年（实际 ${d.main1}）`, d.main1 === '示例历 17 年');
    chk(`主力轴泳道序=['1','2','3','4']（实际 ${JSON.stringify(d.laneQyIds)}）`,
      JSON.stringify(d.laneQyIds) === JSON.stringify(['1', '2', '3', '4']));
  }

  if (state === 'empty') {
    chk(`空态可见（实际 ${d.emptyDisplay}）`, d.emptyDisplay === 'flex');
    chk(`工具栏隐藏（实际 ${d.toolbarDisplay}）`, d.toolbarDisplay === 'none');
    chk('无轴容器', d.axisExists === false);
  }

  return fails;
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  let totalFails = 0;
  for (const s of SHOTS) {
    const url = 'file:///' + path.join(ROOT, 'timeline', 'timeline.html').replace(/\\/g, '/');
    await page.goto(url); // 每状态一次干净加载（绕开 file:// hash 导航不重载的坑）
    await page.evaluate((st) => {
      // 首态（narrative）不显式 setState —— 顺带验证「双击打开」的初始渲染链（坑：初始化链抛错→页面空白）
      if (st !== 'narrative') window.setState(st);
      document.body.dataset.shot = '1'; // 隐藏 demo-bar + review-note
    }, s.state);
    await page.waitForTimeout(400);
    const out = path.join(ROOT, 'timeline', s.out);
    await page.screenshot({ path: out });
    const d = await probe(page);
    const fails = checkAll(d, s.state);
    if (fails.length) { totalFails += fails.length; console.log(`[${s.state}] FAIL: ${fails.join(' | ')}`); }
    else console.log(`[${s.state}] OK -> ${s.out}`);
  }
  await browser.close();
  console.log(totalFails ? `TOTAL FAILS: ${totalFails}` : 'ALL PASS');
  process.exit(totalFails ? 1 : 0);
})().catch((e) => { console.error('SCRIPT ERROR:', e); process.exit(2); });
