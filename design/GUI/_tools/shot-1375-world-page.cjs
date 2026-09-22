/*
 * #1375 world 页四处设计 · 原型截图 + 断言脚本
 * 用法: node shot-1375-world-page.cjs
 * - file:// 打开 world.html → 驱动 setState/setBtns/setCatplan/setActiveCat → data-shot=1 隐藏 demo-bar
 * - 截 1280x800@DPR1 → design/GUI/world/world-*.png（9 张）
 * - 跑计算样式/几何/DOM 契约断言（视觉模型不可用时的主验证），失败 exit 1
 *
 * 覆盖的四点（#1375）：
 *   ① 创建按钮：A 明确文案 / B ＋新建 下拉 / legacy 对照
 *   ② 分类栏：A 并集＋待注册 / B 提取自动注册 / C 提取时拒绝 / legacy 对照
 *   ③ 建条目分类前提 check（联动 ②，形态同 ②）
 *   ④ 分类 chip 的 × 移入框内（hover 显示）
 *
 * 路径自解析（ROOT / playwright 均从脚本位置推导），见 _shared.cjs（#1361 纪律）。
 */
const path = require('path');
const { assertGuiRoot, requirePlaywright, assertPageDir } = require('./_shared.cjs');

const ROOT = assertGuiRoot();
const chromium = requirePlaywright();
assertPageDir('world', ROOT);
const FILE = 'world/world.html';
const URL = 'file:///' + path.join(ROOT, FILE).replace(/\\/g, '/');

const SCENES = [
  {
    id: 'main',
    out: 'world-main.png',
    desc: '①A + ②A + ④ 基准（未选中分类；× 未 hover 隐藏；待注册 chip 可见）',
    cfg: { state: 'main', btns: 'A', catplan: 'A' },
    check: async (page) => {
      const d = await page.evaluate(() => {
        const cs = (el) => (el ? getComputedStyle(el) : null);
        const q = (s) => document.querySelector(s);
        const vis = (s) => {
          const el = q(s);
          return !!(el && el.offsetParent !== null);
        };
        const chipGeo = q('[data-testid="world-cat-filter-地理"]');
        const chipCulture = q('[data-testid="world-cat-filter-文化"]');
        const xGeo = q('[data-testid="world-cat-delete-地理"]');
        const xCulture = q('[data-testid="world-cat-delete-文化"]');
        const entry = q('[data-testid="world-cat-new-entry"]');
        return {
          newCatText: ((q('[data-testid="world-cat-new-cat"]') || {}).textContent || '').trim(),
          entryText: (entry ? entry.textContent : '').trim(),
          entryDisabled: entry ? entry.disabled : 'MISSING',
          entryVisible: vis('[data-testid="world-cat-new-entry"]'),
          chipsNewDisplay: cs(q('.chips-new')) ? cs(q('.chips-new')).display : 'MISSING',
          chipsLegacyDisplay: cs(q('.chips-legacy')) ? cs(q('.chips-legacy')).display : 'MISSING',
          cultureVisible: vis('[data-testid="world-cat-filter-文化"]'),
          techVisible: vis('[data-testid="world-cat-filter-科技"]'),
          cultureBorderStyle: chipCulture ? cs(chipCulture).borderTopStyle : 'MISSING',
          geoBorderStyle: chipGeo ? cs(chipGeo).borderTopStyle : 'MISSING',
          // ④：× 是否在 chip 容器内（框内 = DOM 内嵌），以及未 hover 时隐藏
          xInsideChip: !!(chipGeo && xGeo && chipGeo.contains(xGeo)),
          xOpacity: xGeo ? cs(xGeo).opacity : 'MISSING',
          xDisplayInPending: xCulture ? cs(xCulture).display : 'MISSING',
          pendingPlusVisible: vis('[data-testid="world-cat-register-文化"]'),
          pendingNoteDisplay: (() => {
            const n = q('[data-testid="world-cat-filter-文化"] .chip-note');
            return n ? getComputedStyle(n).display : 'MISSING';
          })(),
          pendingNoteText: (() => {
            const n = q('[data-testid="world-cat-filter-文化"] .chip-note');
            return n ? n.textContent.trim() : 'MISSING';
          })(),
          treeHasCulture: !!q('[data-testid="world-node-culture"]'),
          treeHasTech: !!q('[data-testid="world-node-tech"]'),
          badgeCulture: (() => {
            const n = q('[data-testid="world-node-culture"]');
            const b = n ? n.querySelector('.badge') : null;
            return b ? b.textContent.trim() : 'MISSING';
          })(),
          noteB: cs(q('.plan-note[data-plan="B"]')) ? cs(q('.plan-note[data-plan="B"]')).display : 'MISSING',
          noteC: cs(q('.plan-note[data-plan="C"]')) ? cs(q('.plan-note[data-plan="C"]')).display : 'MISSING',
        };
      });
      const fails = [];
      const p = (label, ok) => {
        if (!ok) fails.push(label);
      };
      p('①A 新建分类按钮文案', d.newCatText.includes('新建分类'));
      p('①A 新建条目按钮文案', d.entryText.includes('新建条目'));
      p('①A 未选中分类 → 新建条目 disabled', d.entryDisabled === true);
      p('①A 新建条目可见', d.entryVisible === true);
      p('新 chips 可见', d.chipsNewDisplay !== 'none' && d.chipsNewDisplay !== 'MISSING');
      p('legacy chips 隐藏', d.chipsLegacyDisplay === 'none');
      p('②A 待注册 chip 文化 可见', d.cultureVisible === true);
      p('②A 待注册 chip 科技 可见', d.techVisible === true);
      p('②A 待注册 chip 虚线边框', d.cultureBorderStyle === 'dashed');
      p('已注册 chip 实线边框', d.geoBorderStyle === 'solid');
      p('④ × 在 chip 框内（DOM 内嵌）', d.xInsideChip === true);
      p('④ × 未 hover 时隐藏（opacity 0）', d.xOpacity === '0');
      p('待注册 chip 不显示 ×', d.xDisplayInPending === 'none');
      p('②A 一键注册 ＋ 可见', d.pendingPlusVisible === true);
      p('②A「待注册」注记可见', d.pendingNoteDisplay !== 'none' && d.pendingNoteDisplay !== 'MISSING');
      p('②A「待注册」注记文案', d.pendingNoteText === '待注册');
      p('树含未注册类别条目（文化/科技）', d.treeHasCulture && d.treeHasTech);
      p('条目类别徽标 = 文化', d.badgeCulture === '文化');
      p('②B/C 说明条不在 ②A 形态显示', d.noteB === 'none' && d.noteC === 'none');
      return { fails, d };
    },
  },
  {
    id: 'cat-selected',
    out: 'world-cat-selected.png',
    desc: '①A 选中分类「势力」→ 新建条目启用；hover chip → × 在框内显示',
    cfg: { state: 'main', btns: 'A', catplan: 'A', active: '势力', hover: '[data-testid="world-cat-filter-势力"]' },
    check: async (page) => {
      const d = await page.evaluate(() => {
        const chip = document.querySelector('[data-testid="world-cat-filter-势力"]');
        const x = chip ? chip.querySelector('.chip-x') : null;
        const entry = document.querySelector('[data-testid="world-cat-new-entry"]');
        return {
          active: chip ? chip.classList.contains('active') : 'MISSING',
          ariaPressed: chip ? chip.querySelector('.chip-name').getAttribute('aria-pressed') : 'MISSING',
          entryDisabled: entry ? entry.disabled : 'MISSING',
          entryTitle: entry ? entry.title : 'MISSING',
          xInside: !!(chip && x && chip.contains(x)),
          xOpacity: x ? getComputedStyle(x).opacity : 'MISSING',
          chipBorderColor: chip ? getComputedStyle(chip).borderTopColor : 'MISSING',
        };
      });
      const fails = [];
      const p = (label, ok) => {
        if (!ok) fails.push(label);
      };
      p('选中 chip 高亮（active）', d.active === true);
      p('选中 chip aria-pressed=true', d.ariaPressed === 'true');
      p('①A 选中分类 → 新建条目启用', d.entryDisabled === false);
      p('①A 新建条目 title 提示选中分类', typeof d.entryTitle === 'string' && d.entryTitle.includes('势力'));
      p('④ × 在 chip 框内', d.xInside === true);
      p('④ hover 后 × 显示（opacity 1）', d.xOpacity === '1');
      return { fails, d };
    },
  },
  {
    id: 'reg-after',
    out: 'world-cat-registered.png',
    desc: '②A 一键注册：点击「文化 ＋」→ chip 转正式分类 + ok toast',
    cfg: { state: 'main', btns: 'A', catplan: 'A', click: '[data-testid="world-cat-register-文化"]' },
    check: async (page) => {
      const d = await page.evaluate(() => {
        const chip = document.querySelector('[data-testid="world-cat-filter-文化"]');
        const toast = document.getElementById('toast');
        return {
          stillPending: chip ? chip.classList.contains('pending') : 'MISSING',
          borderStyle: chip ? getComputedStyle(chip).borderTopStyle : 'MISSING',
          toastShown: toast ? toast.classList.contains('show') : 'MISSING',
          toastText: toast ? toast.textContent : 'MISSING',
          xDisplay: chip ? getComputedStyle(chip.querySelector('.chip-x')).display : 'MISSING',
          plusDisplay: chip ? getComputedStyle(chip.querySelector('.chip-plus')).display : 'MISSING',
        };
      });
      const fails = [];
      const p = (label, ok) => {
        if (!ok) fails.push(label);
      };
      p('注册后 pending 标记移除', d.stillPending === false);
      p('注册后 chip 实线（转为正式分类样式）', d.borderStyle === 'solid');
      p('注册后 toast 显示', d.toastShown === true);
      p('toast 文案含「已注册分类」', typeof d.toastText === 'string' && d.toastText.includes('已注册分类'));
      p('注册后 chip 出现 × 位（hover 可删）', d.xDisplay === 'flex' || d.xDisplay === 'inline-flex');
      p('注册后 ＋ 隐藏', d.plusDisplay === 'none');
      return { fails, d };
    },
  },
  {
    id: 'btn-b',
    out: 'world-btn-b.png',
    desc: '①B ＋新建 下拉菜单（展开态；②A 分类栏）',
    cfg: { state: 'main', btns: 'B', catplan: 'A' },
    check: async (page) => {
      const d = await page.evaluate(() => {
        const menu = document.querySelector('[data-testid="world-create-menu"]');
        const btn = document.querySelector('[data-testid="world-create-menu-btn"]');
        const entryItem = document.getElementById('menuEntryBtn');
        const groupA = document.querySelector('.create-group[data-variant="A"]');
        return {
          menuDisplay: menu ? getComputedStyle(menu).display : 'MISSING',
          menuItems: Array.from(document.querySelectorAll('.menu-item')).map((b) => b.textContent.trim()),
          btnText: btn ? btn.textContent.trim() : 'MISSING',
          entryDisabled: entryItem ? entryItem.disabled : 'MISSING',
          groupADisplay: groupA ? getComputedStyle(groupA).display : 'MISSING',
        };
      });
      const fails = [];
      const p = (label, ok) => {
        if (!ok) fails.push(label);
      };
      p('①B 菜单展开（display flex）', d.menuDisplay === 'flex');
      p('①B 菜单含「新建分类」项', d.menuItems.some((t) => t.includes('新建分类')));
      p('①B 菜单含「新建条目」项', d.menuItems.some((t) => t.includes('新建条目')));
      p('①B 未选中分类 → 菜单项新建条目 disabled', d.entryDisabled === true);
      p('①A 按钮组隐藏（变体互斥）', d.groupADisplay === 'none');
      return { fails, d };
    },
  },
  {
    id: 'plan-b',
    out: 'world-plan-b.png',
    desc: '②B 提取自动注册：pending chip 走正常样式 + 说明条',
    cfg: { state: 'main', btns: 'A', catplan: 'B' },
    check: async (page) => {
      const d = await page.evaluate(() => {
        const chip = document.querySelector('[data-testid="world-cat-filter-文化"]');
        const noteB = document.querySelector('.plan-note[data-plan="B"]');
        const noteC = document.querySelector('.plan-note[data-plan="C"]');
        return {
          cultureVisible: !!chip && chip.offsetParent !== null,
          borderStyle: chip ? getComputedStyle(chip).borderTopStyle : 'MISSING',
          chipNoteDisplay: chip ? getComputedStyle(chip.querySelector('.chip-note')).display : 'MISSING',
          xDisplay: chip ? getComputedStyle(chip.querySelector('.chip-x')).display : 'MISSING',
          noteB: noteB ? getComputedStyle(noteB).display : 'MISSING',
          noteC: noteC ? getComputedStyle(noteC).display : 'MISSING',
          noteBText: noteB ? noteB.textContent.replace(/\s+/g, ' ').trim() : '',
        };
      });
      const fails = [];
      const p = (label, ok) => {
        if (!ok) fails.push(label);
      };
      p('②B 文化 chip 可见', d.cultureVisible === true);
      p('②B 文化 chip 走正常实线样式', d.borderStyle === 'solid');
      p('②B 无「待注册」注记', d.chipNoteDisplay === 'none');
      p('②B chip 可删（× 位恢复）', d.xDisplay === 'flex' || d.xDisplay === 'inline-flex');
      p('②B 说明条 B 显示', d.noteB === 'flex');
      p('②C 说明条不显示', d.noteC === 'none');
      p('②B 说明条含自动注册要点', d.noteBText.includes('自动注册'));
      return { fails, d };
    },
  },
  {
    id: 'plan-c',
    out: 'world-plan-c.png',
    desc: '②C 提取时拒绝：分类栏只含已注册 + 说明条（影响面提示）',
    cfg: { state: 'main', btns: 'A', catplan: 'C' },
    check: async (page) => {
      const d = await page.evaluate(() => {
        const chip = document.querySelector('[data-testid="world-cat-filter-文化"]');
        const noteC = document.querySelector('.plan-note[data-plan="C"]');
        const noteB = document.querySelector('.plan-note[data-plan="B"]');
        return {
          cultureDisplay: chip ? getComputedStyle(chip).display : 'MISSING',
          noteC: noteC ? getComputedStyle(noteC).display : 'MISSING',
          noteB: noteB ? getComputedStyle(noteB).display : 'MISSING',
          noteCText: noteC ? noteC.textContent.replace(/\s+/g, ' ').trim() : '',
        };
      });
      const fails = [];
      const p = (label, ok) => {
        if (!ok) fails.push(label);
      };
      p('②C 待注册 chip 不显示（分类栏只含已注册）', d.cultureDisplay === 'none');
      p('②C 说明条 C 显示', d.noteC === 'flex');
      p('②B 说明条不显示', d.noteB === 'none');
      p('②C 说明条含链路中断风险提示', d.noteCText.includes('中断'));
      return { fails, d };
    },
  },
  {
    id: 'legacy',
    out: 'world-legacy.png',
    desc: '现状对照（①两同款按钮 / ②只已注册 / ④× 在框外恒显）',
    cfg: { state: 'main', btns: 'legacy', catplan: 'legacy' },
    check: async (page) => {
      const d = await page.evaluate(() => {
        const legacyChips = document.querySelector('.chips-legacy');
        const newChips = document.querySelector('.chips-new');
        const legacyX = document.querySelector('.chip-legacy-x');
        const legacyName = document.querySelector('.chip-legacy-name');
        const groupLegacy = document.querySelector('.create-group[data-variant="legacy"]');
        const addBtn = document.querySelector('[data-testid="world-cat-add-legacy"]');
        const addAlways = document.querySelector('[data-testid="world-cat-add-always-legacy"]');
        return {
          legacyChipsDisplay: legacyChips ? getComputedStyle(legacyChips).display : 'MISSING',
          newChipsDisplay: newChips ? getComputedStyle(newChips).display : 'MISSING',
          legacyXOpacity: legacyX ? getComputedStyle(legacyX).opacity : 'MISSING',
          legacyNameRadius: legacyName ? getComputedStyle(legacyName).borderTopLeftRadius : 'MISSING',
          xOutsideName: !!(legacyName && legacyX && !legacyName.contains(legacyX)),
          groupLegacyDisplay: groupLegacy ? getComputedStyle(groupLegacy).display : 'MISSING',
          addText: addBtn ? addBtn.textContent.trim() : 'MISSING',
          addAlwaysText: addAlways ? addAlways.textContent.trim() : 'MISSING',
          pendingVisible: (() => {
            const c = document.querySelector('[data-testid="world-cat-filter-文化"]');
            return !!(c && c.offsetParent !== null);
          })(),
        };
      });
      const fails = [];
      const p = (label, ok) => {
        if (!ok) fails.push(label);
      };
      p('legacy chips 可见', d.legacyChipsDisplay === 'flex' || d.legacyChipsDisplay === 'inline-flex');
      p('新 chips 隐藏', d.newChipsDisplay === 'none');
      p('④-legacy × 恒显（opacity 1）', d.legacyXOpacity === '1');
      p('④-legacy × 在筛选按钮框外（对照）', d.xOutsideName === true);
      p('legacy 按钮组可见', d.groupLegacyDisplay === 'inline-flex' || d.groupLegacyDisplay === 'flex');
      p('legacy 两个「新建分类」按钮在场', d.addText.includes('新建分类') && d.addAlwaysText.includes('不随选中项'));
      p('legacy 无待注册 chip', d.pendingVisible === false);
      return { fails, d };
    },
  },
  {
    id: 'map',
    out: 'world-map.png',
    desc: '地图工作台（①A 文案简化；#1322 契约回归）',
    cfg: { state: 'map', btns: 'A', catplan: 'A' },
    check: async (page) => {
      const d = await page.evaluate(() => {
        const btn = document.querySelector('[data-testid="world-cat-add-always"]');
        const newLabel = document.querySelector('.map-add-new');
        const legacyLabel = document.querySelector('.map-add-legacy');
        const leftRect = document.querySelector('.map-left').getBoundingClientRect();
        const handle = document.querySelector('[data-testid="map-tree-resize-handle"]');
        return {
          // innerText 只取可见文本（隐藏的 legacy 文案 span 不参与）
          btnText: btn ? btn.innerText.replace(/\s+/g, '') : 'MISSING',
          newLabelDisplay: newLabel ? getComputedStyle(newLabel).display : 'MISSING',
          legacyLabelDisplay: legacyLabel ? getComputedStyle(legacyLabel).display : 'MISSING',
          leftWidth: Math.round(leftRect.width),
          handleCursor: handle ? getComputedStyle(handle).cursor : 'MISSING',
          mainTreeText: ((document.querySelector('[data-testid="map-tree-main"]') || {}).textContent || ''),
          unmappedText: ((document.querySelector('[data-testid="map-tree-unmapped"]') || {}).textContent || ''),
        };
      });
      const fails = [];
      const p = (label, ok) => {
        if (!ok) fails.push(label);
      };
      p('① 地图左栏入口文案简化（无「不随选中项」）', d.btnText.includes('新建分类') && !d.btnText.includes('不随选中项'));
      p('① 地图入口新文案可见', d.newLabelDisplay !== 'none');
      p('#1322 左栏宽 260px', d.leftWidth === 260);
      p('#1322 resize 手柄 cursor', d.handleCursor === 'col-resize');
      p('#1322 主树含挂图条目', d.mainTreeText.includes('青云山'));
      p('#1322 未挂图折叠区在场', d.unmappedText.includes('未挂图条目'));
      return { fails, d };
    },
  },
  {
    id: 'copy-dialog',
    out: 'world-copy-dialog.png',
    desc: '复制对话框（回归：范围 chips + 目标项目）',
    cfg: { state: 'copy-dialog', btns: 'A', catplan: 'A' },
    check: async (page) => {
      const d = await page.evaluate(() => {
        const overlay = document.querySelector('.dialog-overlay');
        const target = document.querySelector('[data-testid="world-copy-target"]');
        const scope = document.querySelector('[data-testid="world-copy-scope-subtree"]');
        return {
          overlayDisplay: overlay ? getComputedStyle(overlay).display : 'MISSING',
          targetText: target ? target.textContent.trim() : 'MISSING',
          scopeText: scope ? scope.textContent.trim() : 'MISSING',
        };
      });
      const fails = [];
      const p = (label, ok) => {
        if (!ok) fails.push(label);
      };
      p('复制对话框 overlay 显示', d.overlayDisplay === 'flex');
      p('复制目标项目在场', d.targetText.includes('归墟记'));
      p('复制范围 chips 在场', d.scopeText.includes('本体'));
      return { fails, d };
    },
  },
];

async function commonChecks(page) {
  const d = await page.evaluate(() => ({
    errs: window.__errs || [],
    icons: { ic: document.querySelectorAll('[data-ic]').length, svg: document.querySelectorAll('[data-ic] svg').length },
    scrollW: document.documentElement.scrollWidth,
    innerW: window.innerWidth,
    demoBar: (() => {
      const el = document.querySelector('.demo-bar');
      return el ? getComputedStyle(el).display : 'MISSING';
    })(),
  }));
  const fails = [];
  const p = (label, ok) => {
    if (!ok) fails.push(label);
  };
  p('无页面 JS 错误', Array.isArray(d.errs) && d.errs.length === 0);
  p('图标全部渲染（svg === ic）', d.icons.svg === d.icons.ic && d.icons.ic > 0);
  p('无水平滚动', d.scrollW <= d.innerW);
  p('截图态 demo-bar 已隐藏', d.demoBar === 'none');
  return { fails, d };
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

  let totalFails = 0;
  for (const scene of SCENES) {
    await page.goto(URL);
    await page.evaluate((cfg) => {
      document.body.dataset.shot = '1';
      setState(cfg.state);
      setBtns(cfg.btns);
      setCatplan(cfg.catplan);
      if (cfg.active) setActiveCat(cfg.active);
    }, scene.cfg);
    if (scene.cfg.click) {
      await page.click(scene.cfg.click, { force: true });
      await page.waitForTimeout(250);
    }
    if (scene.cfg.hover) {
      await page.hover(scene.cfg.hover);
      await page.waitForTimeout(400);
    } else {
      await page.waitForTimeout(200);
    }

    const { fails: sceneFails, d } = await scene.check(page);
    const { fails: commonFails, d: cd } = await commonChecks(page);
    const fails = [...sceneFails, ...commonFails];
    totalFails += fails.length;

    const shotPath = path.join(ROOT, 'world', scene.out);
    await page.screenshot({ path: shotPath });
    console.log(
      JSON.stringify(
        { scene: scene.id, desc: scene.desc, shot: shotPath, fails, check: d, common: cd },
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
  console.log(`ALL PASS -> ${SCENES.length} 张截图已输出至 ${path.join(ROOT, 'world')}`);
})().catch((e) => {
  console.error('SCRIPT ERROR:', e);
  process.exit(2);
});
