/* InkFlow design/GUI 官方简图截图 + 断言脚本（#770 补图批次：writing-global-chat + sessions title/rename）
 * 用法: node shot-770.cjs
 * - 对 writing/sessions 每个状态: file:// 打开 -> evaluate setState -> data-shot=1 隐藏 demo-bar -> waitForTimeout -> screenshot 1280x800@DPR1
 * - 每状态跑计算样式/几何断言（视觉模型不可用时的主验证），失败 exit 1
 */
const path = require('path');
const { chromium } = require('D:/develop/projects/InkFlow/frontend/packages/electron/node_modules/@playwright/test');

const ROOT = 'D:/develop/projects/InkFlow-ft/session-page-770/design/GUI';
const PAGES = {
  writing: {
    file: 'writing/writing.html',
    states: ['editor-idle', 'streaming', 'collapsed', 'empty', 'global-chat'],
  },
  sessions: {
    file: 'sessions/sessions.html',
    states: ['directory', 'rename', 'archived', 'delete', 'empty'],
    // 文件名沿用既有批次约定（HTML 状态名 delete → PNG 名 delete-dialog）
    fileAlias: { delete: 'delete-dialog' },
  },
};

function rect(r) {
  return r ? { top: Math.round(r.top), bottom: Math.round(r.bottom), height: Math.round(r.height) } : null;
}

async function runChecks(page, pageName, state) {
  const fails = [];
  const push = (label, ok) => { if (!ok) fails.push(label); };
  const d = await page.evaluate(() => {
    const cs = (sel) => { const el = document.querySelector(sel); return el ? getComputedStyle(el).display : 'MISSING'; };
    const rectOf = (sel) => { const el = document.querySelector(sel); return el ? el.getBoundingClientRect() : null; };
    return {
      gc: cs('[data-testid="global-chat"]'),
      toolbar: cs('.editor > .editor-toolbar'),
      chapterHead: cs('.editor > .chapter-head'),
      editorScroll: cs('.editor > .editor-scroll'),
      inlinePanel: cs('.editor > .chat-panel.inline-chat'),
      resizeHandles: Array.from(document.querySelectorAll('[data-testid="chat-resize-handle"]')).filter((el) => el.offsetParent !== null).length,
      pipeline: cs('.editor > .chat-panel.inline-chat [data-testid="pipeline-output"]'),
      chatStop: cs('.editor > .chat-panel.inline-chat [data-testid="chat-stop"]'),
      chatSend: cs('.editor > .chat-panel.inline-chat [data-testid="chat-send"]'),
      input: rectOf('[data-testid="chat-input"]'),
      send: rectOf('[data-testid="chat-send"]'),
      messages: rectOf('.chat-panel.gc .chat-messages'),
      railWidth: rectOf('[data-testid="right-rail"]') ? Math.round(rectOf('[data-testid="right-rail"]').width) : -1,
      pageWriting: cs('.page-writing'),
      writingEmpty: cs('.writing-empty'),
      title1: (document.querySelector('[data-testid="session-title-conv-1"]') || {}).textContent,
      title2: (document.querySelector('[data-testid="session-title-conv-2"]') || {}).textContent,
      title3: (document.querySelector('[data-testid="session-title-conv-3"]') || {}).textContent,
      renameBtn1: cs('[data-testid="chat-conv-rename-1"]'),
      renameBtn2: cs('[data-testid="chat-conv-rename-2"]'),
      renameBtn3: cs('[data-testid="chat-conv-rename-3"]'),
      renameInput: cs('.chat-conv-rename-input'),
      renameInputVal: (document.querySelector('.chat-conv-rename-input') || {}).value,
      nonArchivedCards: Array.from(document.querySelectorAll('.dir-card[data-archived="false"]')).map((el) => getComputedStyle(el).display),
      dialog: cs('[data-testid="session-delete-dialog"]'),
      dirList: cs('.dir-list'),
      emptyBox: cs('.empty-box'),
    };
  });

  if (pageName === 'writing') {
    if (state === 'editor-idle') {
      push('toolbar visible', d.toolbar !== 'none');
      push('inline chat visible', d.inlinePanel !== 'none');
      push('gc hidden', d.gc === 'none');
      push('rail 240', d.railWidth === 240);
      push('resize handle present', d.resizeHandles === 1);
    } else if (state === 'streaming') {
      push('pipeline visible', d.pipeline !== 'none');
      push('stop visible', d.chatStop !== 'none');
      push('send hidden', d.chatSend === 'none');
    } else if (state === 'collapsed') {
      push('rail 26', d.railWidth === 26);
    } else if (state === 'empty') {
      push('page-writing hidden', d.pageWriting === 'none');
      push('writing-empty shown', d.writingEmpty === 'flex');
    } else if (state === 'global-chat') {
      push('gc shown', d.gc === 'flex');
      push('toolbar hidden', d.toolbar === 'none');
      push('chapter-head hidden', d.chapterHead === 'none');
      push('editor-scroll hidden', d.editorScroll === 'none');
      push('inline chat hidden', d.inlinePanel === 'none');
      push('no resize handle', d.resizeHandles === 0);
      push('input at bottom (>=700)', d.input !== null && d.input.bottom >= 700);
      push('send aligns with input', d.input !== null && d.send !== null && Math.abs(d.send.bottom - d.input.bottom) <= 4);
      push('messages fill middle (>=300px)', d.messages !== null && d.messages.height >= 300);
      push('rail 240', d.railWidth === 240);
    }
  } else if (pageName === 'sessions') {
    if (state === 'directory') {
      push('title1 = 第 1 章 初见', d.title1 === '第 1 章 初见');
      push('title2 = 第 3 章 剑引', d.title2 === '第 3 章 剑引');
      push('title3 = 第二卷开篇设定讨论', d.title3 === '第二卷开篇设定讨论');
      push('rename btn1 visible', d.renameBtn1 !== 'none');
      push('rename btn2 visible', d.renameBtn2 !== 'none');
      push('rename btn3 visible', d.renameBtn3 !== 'none');
      push('rename input hidden', d.renameInput === 'none');
    } else if (state === 'rename') {
      push('rename input shown', d.renameInput === 'block');
      push('rename input value', d.renameInputVal === '第 1 章 初见');
      push('rename btn1 hidden', d.renameBtn1 === 'none');
      push('rename btn2 stays', d.renameBtn2 !== 'none');
      push('rename btn3 stays', d.renameBtn3 !== 'none');
    } else if (state === 'archived') {
      push('non-archived cards hidden', d.nonArchivedCards.length > 0 && d.nonArchivedCards.every((x) => x === 'none'));
    } else if (state === 'delete') {
      push('dialog shown', d.dialog === 'flex');
    } else if (state === 'empty') {
      push('dir-list hidden', d.dirList === 'none');
      push('empty-box shown', d.emptyBox === 'block');
    }
  }
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
      scrollW: document.documentElement.scrollWidth,
      innerW: window.innerWidth,
    }));
    if (icon.svg !== icon.ic) { totalFails++; console.log(`[${pageName}] FAIL icons ${icon.svg}/${icon.ic}`); }
    else console.log(`[${pageName}] icons ${icon.svg}/${icon.ic} OK`);
    if (icon.scrollW > icon.innerW) { totalFails++; console.log(`[${pageName}] FAIL horizontal scroll ${icon.scrollW}>${icon.innerW}`); }

    for (const state of cfg.states) {
      await page.evaluate((s) => { setState(s); document.body.dataset.shot = '1'; }, state);
      await page.waitForTimeout(500);
      const fileName = (cfg.fileAlias && cfg.fileAlias[state]) || state;
      const shotPath = path.join(ROOT, pageName, `${pageName}-${fileName}.png`);
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
