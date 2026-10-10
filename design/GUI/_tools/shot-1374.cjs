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
 *   world              世界序 · 单轴（项目无纪元数据）：**#1527 前**平铺形态（改前对照）
 *   world-single       世界序 · 单轴（#1527 目标态）：按**时间刻度段**分组 + 组内缩进（两级树状）
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
  { state: 'world-single', out: 'timeline-world-single.png' },
  { state: 'world-band', out: 'timeline-world-band.png' },
  { state: 'world-band-p2', out: 'timeline-world-band-p2.png' },
  { state: 'world-band-metric', out: 'timeline-world-band-metric.png' },
  { state: 'world-band-dense', out: 'timeline-world-band-dense.png' },
  { state: 'world-band-dense-legacy', out: 'timeline-world-band-dense-legacy.png' },
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
    /* #1527：单轴（无 lane 容器）的时间节点 —— 库内 tl-tick-__none__-<i> 下的刻度 + 事件 id + 缩进 */
    const singleTn = (() => {
      const axis = q('.tl-axis--time');
      if (!axis || q('.tl-lane')) return [];
      return Array.from(axis.querySelectorAll('[data-testid^="tl-tick-"]')).map((lab) => {
        const node = lab.closest('.tl-timenode');
        const host = node ? node.querySelector('.tl-timenode-events') : null;
        return {
          label: lab.textContent.trim(),
          ids: host ? ids(host, '[data-testid^="tl-axis-node-"]') : [],
          indented: host ? getComputedStyle(host).paddingLeft : 'MISSING',
        };
      });
    })();
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
      laneNameTotal: qa('[data-testid^="tl-lanehead-"]').length,
      singleTn,
      band: !!q('[data-testid="tl-band"]'),
      bandSpines: qa('.mvs-spine').length,
      bandTicks: qa('.mvs-node').length,
      bandUnknown: qa('.mvs-rule').length,
      /* #1564：刻度带 v2（不定高 + 时间主轴 + 按刻度分页） */
      bandH: q('[data-testid="tl-band"]') ? Math.round(q('[data-testid="tl-band"]').getBoundingClientRect().height) : 0,
      bandMainNodes: qa('.mvs-mainnode').length,
      bandRowGuides: qa('.mvs-rowguide').length,
      bandRowTops: qa('.mvs-rowguide').map((n) => Math.round(n.getBoundingClientRect().top)),
      bandPager: txt(q('[data-testid="tl-band-pageinfo"]')),
      bandTickTexts: qa('.mvs-tick').map((n) => n.textContent.trim()),
      bandUnkHead: txt(q('.mvs-unkhead')),
      bandUnkListH: q('.mvs-unklist') ? Math.round(q('.mvs-unklist').getBoundingClientRect().height) : 0,
      bandBadge: txt(q('.mvs-badge')),
      bandEvents: qa('[data-testid^="tl-axis-node-"]').length,
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

function checkAll(d, state, sh) {
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

  if (state === 'world-single') {
    /* #1527：单轴（era 全空）→ 按时间刻度段分组 + 组内缩进（两级树状），无轴名组头 */
    chk('时间轴容器（tl-axis--time）', d.timeAxis);
    chk(`无章分组（实际 ${d.groupKeys.length}）`, d.groupKeys.length === 0);
    chk(`无纪元泳道（单轴不套 lane，实际 ${d.laneCount}）`, d.laneCount === 0);
    chk(`无轴名组头（实际 ${d.laneNameTotal}）`, d.laneNameTotal === 0);
    chk(`事件序=时间升序（未知末尾）[1..5]（实际 ${JSON.stringify(d.nodeIds)}）`,
      JSON.stringify(d.nodeIds) === JSON.stringify(['1', '2', '3', '4', '5']));
    chk(`时间刻度段节点=4（实际 ${d.singleTn.length}）`, d.singleTn.length === 4);
    chk(`组头刻度=['示例历 17 年','示例历 217 年','示例历 314 年','未知']（实际 ${JSON.stringify(d.singleTn.map((n) => n.label))}）`,
      JSON.stringify(d.singleTn.map((n) => n.label)) === JSON.stringify(['示例历 17 年', '示例历 217 年', '示例历 314 年', '未知']));
    chk(`同刻度合并：217 年节点下=['2','3']（实际 ${JSON.stringify(d.singleTn[1] ? d.singleTn[1].ids : null)}）`,
      JSON.stringify(d.singleTn[1] ? d.singleTn[1].ids : null) === JSON.stringify(['2', '3']));
    chk(`时间缺失事件归「未知」节点（末尾）（实际 ${JSON.stringify(d.singleTn[3] ? d.singleTn[3].ids : null)}）`,
      JSON.stringify(d.singleTn[3] ? d.singleTn[3].ids : null) === JSON.stringify(['5']));
    chk(`组内事件行缩进（padding-left=${d.singleTn[0] ? d.singleTn[0].indented : 'MISSING'}）`,
      d.singleTn[0] ? d.singleTn[0].indented !== '0px' && d.singleTn[0].indented !== 'MISSING' : false);
    chk(`组内事件行不重复时间刻度（tl-axis-main 数=${d.laneMainCount + (d.main1 ? 1 : 0)}）`,
      d.main1 === null);
    chk(`事件数=5 且无重复（实际 ${d.nodeCount} dup=${d.dup}）`, d.nodeCount === 5 && d.dup === 0);
    chk(`世界序专属：无轴选择器（实际 ${d.pickerDisplay}）`, d.pickerDisplay === 'none');
  }

  if (state === 'world-band' || state === 'world-band-p2') {
    /* #1564 刻度带 v2：不定高刻度 + 时间主轴 + 按刻度分页（#1541 形态重做） */
    const isP2 = state === 'world-band-p2';
    chk(`刻度带块存在（实际 ${!!d.band}）`, d.band === true);
    chk(`历竖轴=2（实际 ${d.bandSpines}）`, d.bandSpines === 2);
    chk(`刻度点=本页行数 ${isP2 ? 7 : 8}（实际 ${d.bandTicks}）`, d.bandTicks === (isP2 ? 7 : 8));
    chk(`未知区=1（实际 ${d.bandUnknown}）`, d.bandUnknown === 1);
    chk(`本页事件数=${isP2 ? 11 : 12}（实际 ${d.bandEvents}）`, d.bandEvents === (isP2 ? 11 : 12));
    chk(`无泳道卡片（实际 ${d.laneCount}）`, d.laneCount === 0);
    chk(`世界序专属：无轴选择器（实际 ${d.pickerDisplay}）`, d.pickerDisplay === 'none');
    /* 拍板 ③：时间主轴 = 定位 / 分页依据（刻度点 + 每行参考线） */
    chk(`时间主轴刻度点=${isP2 ? 7 : 8}（实际 ${d.bandMainNodes}）`, d.bandMainNodes === (isP2 ? 7 : 8));
    chk(`主轴参考线行数=${isP2 ? 7 : 8}（实际 ${d.bandRowGuides}）`, d.bandRowGuides === (isP2 ? 7 : 8));
    /* 拍板 ②：分页单位 = 时间刻度 */
    const expPager = `第 ${isP2 ? 2 : 1} / 2 页 · 每页 8 刻度 · 共 15 刻度`;
    chk(`分页信息=「${expPager}」（实际 ${d.bandPager}）`, d.bandPager === expPager);
    const has17 = d.bandTickTexts.includes('示例历 17 年');
    const has517 = d.bandTickTexts.includes('示例历 517 年');
    chk(`翻页后刻度集合变化（17年=${has17} 517年=${has517}）`, isP2 ? (!has17 && has517) : (has17 && !has517));
    /* 拍板 ①：不定高（同轴内不同刻度行高不同 —— 217 年双事件行更高） */
    const diffs = d.bandRowTops.slice(1).map((t, i) => t - d.bandRowTops[i]).filter((v) => v > 0);
    chk(`不定高：行距种类>1（实际 ${JSON.stringify(diffs)}）`, new Set(diffs).size > 1);
    chk(`画布高度受限（实际 ${d.bandH}px）`, d.bandH > 200 && d.bandH < 900);
  }

  if (state === 'world-band-metric') {
    /* #1564 拍板 ④ 选项 B：等比定位 + p10–p90 截断（单页全量对照） */
    chk(`刻度带块存在（实际 ${!!d.band}）`, d.band === true);
    chk(`历竖轴=1（实际 ${d.bandSpines}）`, d.bandSpines === 1);
    chk(`事件数=252（实际 ${d.bandEvents}）`, d.bandEvents === 252);
    chk(`单页全量（实际 ${d.bandPager}）`, /第 1 \/ 1 页/.test(String(d.bandPager)));
    chk(`badge 标注 p10–p90（实际 ${d.bandBadge}）`, String(d.bandBadge).includes('p10–p90'));
    const dm = d.bandRowTops.slice(1).map((t, i) => t - d.bandRowTops[i]).filter((v) => v > 0);
    chk(`等比间距（最大行距>=2×最小，实际 ${JSON.stringify(dm)}）`,
      dm.length > 0 && Math.max.apply(null, dm) >= 2 * Math.min.apply(null, dm));
    chk(`离群夹端点后画布受限（实际 ${d.bandH}px）`, d.bandH > 200 && d.bandH < 1200);
  }

  if (state === 'world-band-dense') {
    /* #1564 M6：真实数据量级（252 事件 = 12 有值 + 240 未知）→ 新形态紧凑 */
    chk(`刻度带块存在（实际 ${!!d.band}）`, d.band === true);
    chk(`历竖轴=1（实际 ${d.bandSpines}）`, d.bandSpines === 1);
    chk(`本页事件数=249（实际 ${d.bandEvents}）`, d.bandEvents === 249);
    chk(`刻度点=本页行数 8（实际 ${d.bandTicks}）`, d.bandTicks === 8);
    chk(`未知区表头含 240（实际 ${d.bandUnkHead}）`, String(d.bandUnkHead).includes('240'));
    chk(`未知区限高（列表高 ${d.bandUnkListH} <= 240）`, d.bandUnkListH > 0 && d.bandUnkListH <= 240);
    chk(`画布高度紧凑 <900px（实际 ${d.bandH}px）`, d.bandH < 900);
    chk(`分页覆盖全部刻度（实际 ${d.bandPager}）`, /共 11 刻度/.test(String(d.bandPager)));
  }

  if (state === 'world-band-dense-legacy') {
    /* #1564 M6 改前对照：#1541 旧公式复现 → 画布 13924px */
    chk(`刻度带块存在（实际 ${!!d.band}）`, d.band === true);
    chk(`事件数=252（实际 ${d.bandEvents}）`, d.bandEvents === 252);
    chk(`画布高度=13924px（实际 ${d.bandH}px）`, d.bandH === 13924);
    chk(`badge 标注旧公式高度（实际 ${d.bandBadge}）`, String(d.bandBadge).includes('13924'));
    chk(`旧形态无时间主轴（实际 ${d.bandMainNodes}）`, d.bandMainNodes === 0);
    chk(`旧形态无分页（实际 ${d.bandPager}）`, d.bandPager === null);
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
    const fails = checkAll(d, s.state, s);
    if (fails.length) { totalFails += fails.length; console.log(`[${s.state}] FAIL: ${fails.join(' | ')}`); }
    else console.log(`[${s.state}] OK -> ${s.out}`);
  }
  await browser.close();
  console.log(totalFails ? `TOTAL FAILS: ${totalFails}` : 'ALL PASS');
  process.exit(totalFails ? 1 : 0);
})().catch((e) => { console.error('SCRIPT ERROR:', e); process.exit(2); });
