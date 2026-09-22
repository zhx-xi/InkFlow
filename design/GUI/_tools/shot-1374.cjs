/*
 * #1374 时间线「叙事序/世界序」轴向语义重构原型：截图 + 结构断言。
 *
 * ⚠️ 本脚本取代 shot-1323.cjs（#1323 形态断言：两序共用章分组容器 + 组内换序；
 *    #1374 轴向语义分流后该形态作废，原脚本已删除）。
 *
 * 状态集（与 timeline.html 的 demo-bar 一致）：
 *   narrative        叙事序 · 章为轴（章刻度 + 章下事件；行内小字=世界内时间）
 *   narrative-filter 叙事序 + 按章筛选面板展开（已选第十二章 → 列表仅 c12）
 *   world            世界序 · 方案 A 拆半（世界内时间单轴，无章分组，行尾=来源章）
 *   world-b          世界序 · 方案 B 全做（纪元多泳道 + 轴选择器）
 *   empty            空态
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
  { state: 'world-b', out: 'timeline-world-multiaxis.png' },
  { state: 'empty', out: 'timeline-empty.png' },
];

/* 共享探针：所有字段对「本页可能没有」空安全（缺元素 -> null / 0，不炸 evaluate） */
async function probe(page) {
  return page.evaluate(() => {
    const q = (s) => document.querySelector(s);
    const qa = (s) => Array.from(document.querySelectorAll(s));
    const txt = (el) => (el ? el.textContent.trim() : null);
    const axis = q('[data-testid="tl-axis"]');
    const nodes = qa('[data-testid^="tl-axis-node-"]');
    const groups = qa('[data-testid^="tl-chgroup-"]');
    const ticks = qa('[data-testid^="tl-chtick-"]');
    const nodeIds = nodes.map((n) => n.dataset.testid.replace('tl-axis-node-', ''));
    const laneQy = q('[data-testid="tl-lane-qingyuan"]');
    return {
      state: document.body.dataset.state,
      icons: qa('[data-ic]').length,
      svgs: qa('[data-ic] svg').length,
      scrollW: document.documentElement.scrollWidth,
      innerW: window.innerWidth,
      axisExists: !!axis,
      chapterAxis: !!axis && axis.classList.contains('tl-axis--chapter'),
      timeAxis: !!axis && axis.classList.contains('tl-axis--time'),
      tickTexts: ticks.map((t) => txt(t.querySelector('.tl-chlabel'))),
      groupKeys: groups.map((g) => g.dataset.testid.replace('tl-chgroup-', '')),
      nodeIds,
      nodeCount: nodeIds.length,
      dup: nodeIds.length - new Set(nodeIds).size,
      main1: txt(q('[data-testid="tl-axis-main-1"]')),
      main1Cls: (q('[data-testid="tl-axis-main-1"]') || { className: '' }).className,
      main2: txt(q('[data-testid="tl-axis-main-2"]')),
      main2Cls: (q('[data-testid="tl-axis-main-2"]') || { className: '' }).className,
      laneAxisCount: qa('.tl-lanes .tl-axis--time').length,
      src1: txt(q('[data-testid="tl-src-1"]')),
      src5: txt(q('[data-testid="tl-src-5"]')),
      laneCount: qa('[data-testid^="tl-lane-"]').length,
      laneQyIds: laneQy
        ? Array.from(laneQy.querySelectorAll('[data-testid^="tl-axis-node-"]')).map((n) =>
            n.dataset.testid.replace('tl-axis-node-', ''),
          )
        : [],
      chipCount: qa('[data-testid^="tl-axis-chip-"]').length,
      chipOn: qa('[data-testid^="tl-axis-chip-"].on').length,
      demoBadges: qa('#tlBody .tl-demo').length,
      c12Ids: (() => {
        const g = q('[data-testid="tl-chgroup-c12"]');
        return g
          ? Array.from(g.querySelectorAll('[data-testid^="tl-axis-node-"]')).map((n) =>
              n.dataset.testid.replace('tl-axis-node-', ''),
            )
          : [];
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
    };
  });
}

function checkAll(d, state) {
  const fails = [];
  const chk = (label, cond) => { if (!cond) fails.push(label); };

  chk(`icons ${d.svgs}/${d.icons}`, d.icons === d.svgs && d.icons > 0);
  chk(`horizontal scroll ${d.scrollW}>${d.innerW}`, d.scrollW <= d.innerW);
  chk(`body[data-state]=${state}（实际 ${d.state}）`, d.state === state);

  if (state === 'narrative' || state === 'narrative-filter') {
    const isFilter = state === 'narrative-filter';
    chk('章轴容器（tl-axis--chapter）', d.chapterAxis);
    const expTicks = isFilter
      ? ['第十二章 夜访剑冢']
      : ['第十一章 剑心为何物', '第十二章 夜访剑冢', '第十三章 剑心蒙尘', '未分章'];
    chk(`章刻度=${JSON.stringify(expTicks)}（实际 ${JSON.stringify(d.tickTexts)}）`,
      JSON.stringify(d.tickTexts) === JSON.stringify(expTicks));
    const expNodes = isFilter ? 2 : 5;
    chk(`事件数=${expNodes} 且无重复（实际 ${d.nodeCount} dup=${d.dup}）`,
      d.nodeCount === expNodes && d.dup === 0);
    if (!isFilter) {
      chk(`行内时间小字=青元历 17 年（实际 ${d.main1}）`, d.main1 === '青元历 17 年');
      chk('时间小字为降级态（tl-main--dim）', String(d.main1Cls).includes('tl-main--dim'));
      chk(`c12 组内章内序=['2','3']（实际 ${JSON.stringify(d.c12Ids)}）`,
        JSON.stringify(d.c12Ids) === JSON.stringify(['2', '3']));
      chk(`筛选标签=章：全部（实际 ${d.filterLabel}）`, d.filterLabel === '章：全部');
    } else {
      chk(`行内时间小字=青元历 217 年（实际 ${d.main2}）`, d.main2 === '青元历 217 年');
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
    chk(`事件序=时间升序 ['1','2','3','4','5']（实际 ${JSON.stringify(d.nodeIds)}）`,
      JSON.stringify(d.nodeIds) === JSON.stringify(['1', '2', '3', '4', '5']));
    chk(`时间刻度 tl-axis-main-1=青元历 17 年（实际 ${d.main1}）`, d.main1 === '青元历 17 年');
    chk(`来源章小字 tl-src-1=第十一章…（实际 ${d.src1}）`, d.src1 === '第十一章 剑心为何物');
    chk(`来源章小字 tl-src-5=未分章（实际 ${d.src5}）`, d.src5 === '未分章');
    chk(`事件数=5 且无重复（实际 ${d.nodeCount}）`, d.nodeCount === 5 && d.dup === 0);
  }

  if (state === 'world-b') {
    chk(`泳道=2（实际 ${d.laneCount}）`, d.laneCount === 2);
    chk(`泳道内时间轴=2（实际 ${d.laneAxisCount}）`, d.laneAxisCount === 2);
    chk(`轴 chips=3 勾选=2（实际 ${d.chipCount}/${d.chipOn}）`, d.chipCount === 3 && d.chipOn === 2);
    chk(`事件数=6 且无重复（实际 ${d.nodeCount} dup=${d.dup}）`, d.nodeCount === 6 && d.dup === 0);
    chk(`演示徽标=1（实际 ${d.demoBadges}）`, d.demoBadges === 1);
    chk(`主世界泳道序=['1','2','3','4','5']（实际 ${JSON.stringify(d.laneQyIds)}）`,
      JSON.stringify(d.laneQyIds) === JSON.stringify(['1', '2', '3', '4', '5']));
    chk(`无章分组（实际 ${d.groupKeys.length}）`, d.groupKeys.length === 0);
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
