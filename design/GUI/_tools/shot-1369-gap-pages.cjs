/* #1369 原型 PNG ↔ HTML 同源性盘点：为「无出图脚本」的 7 个页面补可复现出图源。
 *
 * 用法: node design/GUI/_tools/shot-1369-gap-pages.cjs
 *
 * 背景（#1369）：
 *   全目录对拍时发现 agent / library / memory / outline / projects / search /
 *   settings（除 reasoning 外四态）这 7 个页面的 PNG **在仓库里没有任何出图脚本**——
 *   历史资产由 #796「补 14 页官方简图」一次性产出，脚本未随仓库保留
 *   （shot-pagination.cjs 只做断言、不出图）。缺出图源 ⇒ 无法对拍、无法重出 ⇒
 *   HTML 演进后这些图必然静默漂移。本脚本即这条「出图源」缺口的最小补齐。
 *
 * ── 「页 × 状态 ↔ 脚本」映射（除 writing 外 14 页，86 张 PNG；#1369 实测）──
 *   page        PNG  出图脚本
 *   agent         4  ← 本脚本（缺口页）
 *   book         17  shot-book-task-board.cjs(9) · shot-book-reset-1288.cjs(6)
 *                    · shot-book-token-scope-1431.cjs(8，与上者重叠 6) · shot-w8-restore-previous-1440.cjs(1)
 *   characters    3  shot-characters-pagination.cjs
 *   foreshadow   11  shot-1376-foreshadow-filter.cjs
 *   knowledge    10  shot-knowledge-graph-scope.cjs
 *   library       3  ← 本脚本（缺口页；shot-pagination.cjs 只断言不出图）
 *   memory        3  ← 本脚本（缺口页）
 *   outline       3  ← 本脚本（缺口页）
 *   projects      4  ← 本脚本（缺口页）
 *   search        3  ← 本脚本（缺口页）
 *   sessions      5  shot-writing-global-chat-and-sessions.cjs
 *   settings      5  shot-writing-and-settings-reasoning.cjs 仅 reasoning；
 *                    general/models/account/saved ← 本脚本（缺口页）
 *   timeline      6  shot-1374.cjs
 *   world         9  shot-1375-world-page.cjs（shot-world-map.cjs 与 world-map.png 重叠）
 *
 *   ⚠️ 已知重叠：book-run-overwrite-notice.png 被 shot-book-token-scope-1431.cjs(900×792)
 *      与 shot-w8-restore-previous-1440.cjs(1280×800) **双重写出且视口不同** → 后跑者胜。
 *      与其余 book-run-*.png 保持一致时应跑 token-scope。
 *
 *   ⚠️ 「有 HTML 状态、无 PNG」的补图缺口（不在本脚本范围，待另开 issue）：
 *      memory:noproject · search:confirm,noproject · settings:saving,note
 *
 * 视口/截图口径与既有资产一致：1280×800、deviceScaleFactor=1、body[data-shot="1"]。
 * agent/library/outline/projects 四页 HTML 自身没有 body[data-shot="1"] 规则
 * （#1400/#1402 未覆盖），故由本脚本注入同款规则（不改原型 HTML）。
 *
 * 路径自解析（ROOT / playwright 均从脚本位置推导），见 _shared.cjs。
 */
const path = require('path');
const { assertGuiRoot, requirePlaywright } = require('./_shared.cjs');

const ROOT = assertGuiRoot();
const chromium = requirePlaywright();

/** 与 memory/search/settings 等页 HTML 内既有规则逐字同源 */
const SHOT_CSS =
  'body[data-shot="1"] .demo-bar{display:none!important}' +
  'body[data-shot="1"],body[data-shot="1"] *,body[data-shot="1"] *::before,' +
  'body[data-shot="1"] *::after{animation:none!important;transition:none!important}';

/** 页面 × [状态, 输出名]。状态名 = 各页 `const STATES` 内的 data-state 值。 */
const PAGES = [
  {
    page: 'agent',
    file: 'agent/agent.html',
    shots: [
      ['main', 'agent-main.png'],
      ['templates', 'agent-templates.png'],
      ['dialog', 'agent-template-dialog.png'],
      ['confirm', 'agent-risk-confirm.png'],
    ],
  },
  {
    page: 'library',
    file: 'library/library.html',
    shots: [
      ['main', 'library-main.png'],
      ['noproject', 'library-noproject.png'],
      ['tab-empty', 'library-tab-empty.png'],
    ],
  },
  {
    page: 'memory',
    file: 'memory/memory.html',
    shots: [
      ['stats', 'memory-stats.png'],
      ['extracting', 'memory-extracting.png'],
      ['add', 'memory-add-form.png'],
    ],
  },
  {
    page: 'outline',
    file: 'outline/outline.html',
    shots: [
      ['main', 'outline-main.png'],
      ['empty', 'outline-empty.png'],
      ['generate-dialog', 'outline-generate-dialog.png'],
    ],
  },
  {
    page: 'projects',
    file: 'projects/projects.html',
    shots: [
      ['grid', 'projects-grid.png'],
      ['new-dialog', 'projects-new-dialog.png'],
      ['menu-open', 'projects-menu-open.png'],
      ['empty', 'projects-empty.png'],
    ],
  },
  {
    page: 'search',
    file: 'search/search.html',
    shots: [
      ['results', 'search-results.png'],
      ['empty', 'search-empty.png'],
      ['rebuilding', 'search-rebuilding.png'],
    ],
  },
  {
    page: 'settings',
    file: 'settings/settings.html',
    shots: [
      ['general', 'settings-general.png'],
      ['models', 'settings-models.png'],
      ['account', 'settings-account.png'],
      ['saved', 'settings-saved.png'],
    ],
  },
];

/** 共同断言：图标渲染数、无横向溢出、demo-bar 已隐藏、初始化链无 JS 异常 */
async function commonChecks(page) {
  return page.evaluate(() => {
    const ic = document.querySelectorAll('[data-ic]').length;
    const svg = document.querySelectorAll('[data-ic] svg').length;
    const bar = document.querySelector('.demo-bar');
    return {
      ic,
      svg,
      scrollW: document.documentElement.scrollWidth,
      innerW: window.innerWidth,
      demoBar: bar ? getComputedStyle(bar).display : 'ABSENT',
      errs: window.__errs || [],
    };
  });
}

(async () => {
  const browser = await chromium.launch();
  let totalFails = 0;
  let shots = 0;

  for (const cfg of PAGES) {
    const url = 'file:///' + path.join(ROOT, cfg.file).replace(/\\/g, '/');
    const ctx = await browser.newContext({
      viewport: { width: 1280, height: 800 },
      deviceScaleFactor: 1,
    });
    const page = await ctx.newPage();
    // 抓初始化链抛错（静默死亡类缺陷的兜底网）
    await page.addInitScript(() => {
      window.__errs = [];
      window.addEventListener('error', (e) => window.__errs.push(`${e.message} @ ${e.filename}:${e.lineno}`));
      window.addEventListener('unhandledrejection', (e) =>
        window.__errs.push(`PROMISE: ${(e.reason && e.reason.message) || e.reason}`));
    });

    for (const [state, out] of cfg.shots) {
      await page.goto(url); // 每状态一次干净加载（绕开 file:// hash 导航不重载的坑）
      // ⚠️ 每次导航后重新注入：addStyleTag 的样式随导航丢失
      await page.addStyleTag({ content: SHOT_CSS });
      await page.evaluate((s) => {
        setState(s);
        document.body.dataset.shot = '1';
      }, state);
      await page.waitForTimeout(450);

      const d = await commonChecks(page);
      const fails = [];
      if (d.svg !== d.ic) fails.push(`icons ${d.svg}/${d.ic}`);
      if (d.scrollW > d.innerW) fails.push(`h-scroll ${d.scrollW}>${d.innerW}`);
      if (d.demoBar !== 'none') fails.push(`demo-bar=${d.demoBar}`);
      if (d.errs.length) fails.push(`js-errors ${JSON.stringify(d.errs)}`);

      const shotPath = path.join(ROOT, cfg.page, out);
      await page.screenshot({ path: shotPath });
      shots += 1;
      if (fails.length) {
        totalFails += fails.length;
        console.log(`[${cfg.page}-${state}] FAIL: ${fails.join(' | ')}`);
      } else {
        console.log(`[${cfg.page}-${state}] OK -> ${shotPath}`);
      }
    }
    await ctx.close();
  }

  await browser.close();
  console.log(`${shots} 张截图 · ${totalFails === 0 ? 'ALL PASS' : `${totalFails} FAILURE(S)`}`);
  process.exit(totalFails === 0 ? 0 : 1);
})();
