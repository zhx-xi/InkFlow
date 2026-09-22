/**
 * 写作页 — 右栏（right rail）契约（从 writing.test.tsx 拆出的兄弟文件，#1014）
 *
 * 拆出原因：writing.test.tsx 基线 896 行，逼近 CI 900 行 monster-file 护栏
 * （ci.yml「Guardrail: file length」扫 ../frontend/packages/）；#1014 新增右栏断言
 * 会触线，故把右栏相关 describe 独立成文件（用例/断言逐字保持，零行为变化）。
 *
 * 覆盖：
 * - #765 收起按钮文案 + 拖动分隔线 hover 形态
 * - #1014 收起钮铺满右栏全宽（非 self-start 收缩内容宽）：展开 / 折叠两态
 * - #747 往左拖 right-col-drag → 右栏变宽
 * - 点按钮整栏收起/展开（面板全隐藏 + data-collapsed）
 *
 * ⚠️ 本文件 = 契约。jsdom 无盒模型：右缘零间隙/整行可点以 className 铺满组合断言
 *    （w-full + 非 self-start/items-start），镜像本仓库既有退化先例
 *    （library-map-workbench-fixes.test.tsx:18）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { WritingPage } from './writing';
import { apiFetch } from '../api/client';
import { streamPipeline, executePipeline, confirmExecution } from '../api/pipeline';
import { createChatConversation, saveChatMessage } from '../api/chat';
import { railLayoutStorageKey } from '../lib/railLayout';
import { useChapterStore } from '../stores/chapter';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import { useModelsStore, type ProviderConfig } from '../stores/models';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});
vi.mock('../api/pipeline', () => ({
  streamPipeline: vi.fn(),
  executePipeline: vi.fn(),
  getExecutionStatus: vi.fn(),
  confirmExecution: vi.fn(),
}));
vi.mock('../api/chat', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/chat')>();
  return { ...actual, createChatConversation: vi.fn(), saveChatMessage: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);
const streamPipelineMock = vi.mocked(streamPipeline);
const executeMock = vi.mocked(executePipeline);
const confirmMock = vi.mocked(confirmExecution);
const createChatCovMock = vi.mocked(createChatConversation);
const saveChatMsgMock = vi.mocked(saveChatMessage);

/** #840：WritingPage 需要 Router 上下文（useSearchParams）；统一用 MemoryRouter 包裹渲染 */
function renderWritingPage() {
  return render(
    <MemoryRouter initialEntries={['/writing']}>
      <WritingPage />
    </MemoryRouter>
  );
}

/** 与后端对齐的种子数据（mock 与 store 播种共用，防 GREEN 自动加载覆盖种子） */
const seedVolumes = [
  { id: 'v1', title: '第一卷 风起', order_index: 0 },
];
const seedChapters = [
  { id: 'c1', title: '第1章 初见', volume_id: 'v1', order_index: 0, word_count: 2347 },
  { id: 'c2', title: '第2章 夜谈', volume_id: 'v1', order_index: 1, word_count: 0 },
];

/** #474：已配置模型种子 provider（key_saved=true + chat 模型），默认播种让既有用例行为不变 */
const READY_PROVIDER: ProviderConfig = {
  id: 1,
  name: 'openai',
  base_url: 'https://api.openai.com/v1',
  default_model: 'gpt-4o',
  models: [{ id: 'gpt-4o', type: 'chat', roles: ['main'] }],
  key_saved: true,
  max_retries: 3,
  timeout: 60,
  created_at: '2026-08-01T10:00:00Z',
  updated_at: '2026-08-05T10:00:00Z',
};

beforeEach(() => {
  vi.useRealTimers();
  apiFetchMock.mockReset();
  streamPipelineMock.mockReset();
  executeMock.mockReset();
  confirmMock.mockReset();
  createChatCovMock.mockReset();
  saveChatMsgMock.mockReset();
  useModelsStore.setState({ providers: [READY_PROVIDER], loading: false, error: null });
  useToastStore.setState({ toasts: [] });
  window.INKFLOW_API = { baseURL: 'http://test.local', token: 'tok-1' };
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useChapterStore.setState({
    volumes: seedVolumes, chapters: seedChapters, treeProjectId: 'p1', currentChapterId: 'c1', content: '已有正文第一段。', loading: false, error: null,
  });
  useProjectStore.setState({
    projects: [{ id: 'p1', name: '青云志', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, config: {}, created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z' }],
    currentProjectId: 'p1', loading: false, error: null,
  });
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === '/api/v1/provider-configs') {
      return { items: [READY_PROVIDER], total: 1, offset: 0, limit: 50 };
    }
    if (path === '/api/v1/projects/p1/volumes') return { items: seedVolumes };
    if (path === '/api/v1/projects/p1/chapters') return { items: seedChapters, total: 2, offset: 0, limit: 50 };
    if (path.startsWith('/api/v1/chapters/') && init?.method === 'PATCH') return { ok: true };
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

afterEach(() => {
  vi.useRealTimers();
  delete window.INKFLOW_API;
});

describe('写作页 — 右栏整栏收起/展开（#742 收起按钮整行 + #747 拖动方向）', () => {
  it('#765 收起按钮移到右栏左缘 + 显示「折叠」提示；拖动分隔线 hover 变鼠标（非方框）', () => {
    renderWritingPage();
    const rail = screen.getByTestId('right-rail');
    const toggle = within(rail).getByTestId('right-col-toggle');
    // #1014 修订：收起按钮内容居中 + 显式铺满右栏全宽（w-full）。
    //   #765 原断言 not.toMatch(/w-full/) 是为表达「非整行居中图标」而写，与 #1014
    //   验收（按钮铺满全宽、右缘零间隙、整行可点）直接冲突，故由父侧修订为正向断言。
    expect(toggle).toBeInTheDocument();
    expect(toggle).toHaveTextContent('折叠');
    expect(toggle.className).toMatch(/w-full/);
    expect(toggle.compareDocumentPosition(screen.getByTestId('rail-panel-context')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // 拖动分隔线：右栏内、hover 变鼠标（cursor-col-resize）、细边界（非 28px 方框）
    const drag = within(rail).getByTestId('right-col-drag');
    expect(drag).toBeInTheDocument();
    expect(drag.className).toMatch(/cursor-col-resize/);
    expect(drag.className).not.toMatch(/h-7/);
  });

  it('#1014 收起钮铺满右栏全宽（非 self-start 收缩内容宽）：按钮右缘贴 aside 右缘 + 整行可点', () => {
    renderWritingPage();
    const rail = screen.getByTestId('right-rail');
    const toggle = within(rail).getByTestId('right-col-toggle');
    // #765 保留：「折叠」可见文案
    expect(toggle).toHaveTextContent('折叠');
    // #1014：按钮不得在 aside（flex-col）交叉轴上收缩为内容宽——
    //   self-start / items-start 会让按钮宽度只包内容，右侧留下不属于按钮的空白带（点击无响应）。
    //   默认 flex 子项为 stretch，按钮应铺满整栏宽度。
    expect(toggle.className).not.toMatch(/\bself-start\b/);
    expect(toggle.className).not.toMatch(/\bitems-start\b/);
    // 整行可点：按钮宽度撑满其父容器（aside 内容盒），左右零间隙
    //   ⚠️ jsdom 无盒模型：getBoundingClientRect 恒返回全零 rect（左右同为 0），
    //   elementFromPoint 亦未实现——故「整行可点」以 className 铺满组合为契约
    //   （w-full + 非 self-start/items-start），镜像本仓库既有退化形态
    //   （library-map-workbench-fixes.test.tsx:18「jsdom 无盒模型 → 契约退化为 className 锚位组合断言」）。
    const railBox = rail.getBoundingClientRect();
    const btnBox = toggle.getBoundingClientRect();
    expect([railBox.left, railBox.right, btnBox.left, btnBox.right]).toEqual([0, 0, 0, 0]);
    expect(toggle.className).toMatch(/\bw-full\b/);
  });

  it('#1014 折叠态（width 26）按钮同样占满列宽、icon 居中、整行可点', async () => {
    const user = userEvent.setup();
    renderWritingPage();
    const rail = screen.getByTestId('right-rail');
    const toggle = within(rail).getByTestId('right-col-toggle');

    await user.click(toggle);

    expect(rail).toHaveAttribute('data-collapsed', 'true');
    expect(rail.style.width).toBe('26px');
    // 折叠态同样不得 self-start 收缩（26px 列内应铺满）
    expect(toggle.className).not.toMatch(/\bself-start\b/);
    // 折叠态内容居中（icon 居中，而非靠左悬空）
    expect(toggle.className).toMatch(/\bjustify-center\b/);
    expect(toggle.className).toMatch(/\bw-full\b/);
  });

  it('#747 往左拖「right-col-drag」→ 右栏变宽、左编辑器变窄', () => {
    renderWritingPage();
    const rail = screen.getByTestId('right-rail');
    const startW = parseInt(rail.style.width, 10) || 240;
    const drag = screen.getByTestId('right-col-drag');
    fireEvent.mouseDown(drag, { clientX: 300, clientY: 100 });
    fireEvent.mouseMove(window, { clientX: 200, clientY: 100 }); // 往左拖 100px
    const afterW = parseInt(rail.style.width, 10);
    expect(afterW).toBeGreaterThan(startW); // 右栏变宽
  });

  it('点「»」→ 整栏收起（context/summary 面板全隐藏 + data-collapsed=true）；再点「«」→ 展开', async () => {
    const user = userEvent.setup();
    renderWritingPage();
    // 展开态：两面板均在（#764 无 drafts）
    expect(screen.getByTestId('rail-panel-context')).toBeInTheDocument();
    expect(screen.getByTestId('rail-panel-summary')).toBeInTheDocument();

    // 收起整栏
    await user.click(screen.getByTestId('right-col-toggle'));
    expect(screen.getByTestId('right-rail')).toHaveAttribute('data-collapsed', 'true');
    expect(screen.queryByTestId('rail-panel-context')).not.toBeInTheDocument();
    expect(screen.queryByTestId('rail-panel-summary')).not.toBeInTheDocument();

    // 展开整栏
    await user.click(screen.getByTestId('right-col-toggle'));
    expect(screen.getByTestId('right-rail')).not.toHaveAttribute('data-collapsed', 'true');
    expect(screen.getByTestId('rail-panel-context')).toBeInTheDocument();
    expect(screen.getByTestId('rail-panel-summary')).toBeInTheDocument();
  });
});

/* ────────────────────────────────────────────────────────────────────────────
 * #1378：右栏两面板默认 2:1 铺满 + 拖拽改比例 + 调整结果跨挂载持久化
 *
 * 现象：两面板高度是固定 px（useState(240)/useState(160) 直接写 style.height）→
 *   默认在右栏下方留一块固定空白；且高度存于页面组件 state，切页/切章重挂载即丢。
 *
 * ⚠️ jsdom 无盒模型（offsetHeight / getBoundingClientRect 恒 0）：
 *   - 「铺满 + 2:1」以 **flex 结构**为契约（两面板纯 flex 比例分配、无固定 px 高），
 *     真实像素呈现待人工 / GUI 复验（spec §13 视觉复验清单）。
 *   - 拖拽换算需要「面板合计高度」这一基准，jsdom 不可测 → stubPanelHeights 提供
 *     确定性盒高**镜像真实布局**，锁的是「拖拽 → 比例的接线与方向/夹值」；
 *     不 stub 时实现按「未布局 → 忽略本次拖拽」处理（见实现处的 span 守卫）。
 * ──────────────────────────────────────────────────────────────────────────── */

/** 从渲染结果读「context 面板占两面板合计的比例」——只看占比语义，与 grow 的表示形式无关。 */
function contextShare(): number {
  const growContext = parseFloat(screen.getByTestId('rail-panel-context').style.flexGrow);
  const growSummary = parseFloat(screen.getByTestId('rail-panel-summary').style.flexGrow);
  return growContext / (growContext + growSummary);
}

/** 面板盒高 stub 的原始描述符（用例后还原，避免污染同文件其他用例） */
const REAL_OFFSET_HEIGHT = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight');

/** 为两面板提供确定性盒高（镜像真实布局的 2:1），使拖拽比例换算基准在 jsdom 下可测。 */
function stubPanelHeights(contextH: number, summaryH: number): void {
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
    configurable: true,
    get(this: HTMLElement) {
      if (this.dataset.testid === 'rail-panel-context') return contextH;
      if (this.dataset.testid === 'rail-panel-summary') return summaryH;
      return 0;
    },
  });
}

/** 拖一次 row-resize 手柄：mousedown → mousemove(dy) → mouseup（mouseup 落盘持久化）。 */
function dragRailResize(handle: HTMLElement, dy: number): void {
  fireEvent.mouseDown(handle, { clientY: 100 });
  fireEvent.mouseMove(window, { clientY: 100 + dy });
  fireEvent.mouseUp(window);
}

/** 拖一次右栏宽度手柄：往左拖 dx px → 右栏变宽 dx（镜像 #747 方向）。 */
function dragRailWidth(drag: HTMLElement, dx: number): void {
  fireEvent.mouseDown(drag, { clientX: 300, clientY: 100 });
  fireEvent.mouseMove(window, { clientX: 300 - dx, clientY: 100 });
  fireEvent.mouseUp(window);
}

describe('写作页 — 右栏两面板 2:1 铺满 + 比例/宽度持久化（#1378）', () => {
  afterEach(() => {
    if (REAL_OFFSET_HEIGHT) Object.defineProperty(HTMLElement.prototype, 'offsetHeight', REAL_OFFSET_HEIGHT);
  });

  it('#1378 默认铺满：两面板纯 flex 比例分配（无固定 px 高）→ 不留固定空白，占比 2:1', () => {
    renderWritingPage();
    const context = screen.getByTestId('rail-panel-context');
    const summary = screen.getByTestId('rail-panel-summary');

    // 反向断言（可证伪核心）：旧形态 style.height = '240px'/'160px' 固定高 + flex:none
    //   → 右栏下方固定留白、且高度与容器无关。改回固定 px 本断言必须 FAIL。
    expect(context.style.height).toBe('');
    expect(summary.style.height).toBe('');
    expect(context.style.flexGrow).not.toBe('');
    expect(summary.style.flexGrow).not.toBe('');

    // 铺满：basis 归零 + 两面板均参与伸缩（合计吃掉右栏剩余高度，无「固定空白」可言）
    expect(context.style.flexBasis).toBe('0%');
    expect(summary.style.flexBasis).toBe('0%');

    // 默认 2:1（context 占 2/3）
    expect(contextShare()).toBeCloseTo(2 / 3, 6);
    expect(parseFloat(context.style.flexGrow)).toBeGreaterThan(parseFloat(summary.style.flexGrow));
  });

  it('#1378 拖拽分隔条（#703 语义升级：px 高 → 比例）→ 比例跟随（向下拖 context 占比变大），并夹在 [0.2, 0.8] 内不塌陷', () => {
    stubPanelHeights(480, 240); // 合计 720px 的 2:1 备态
    renderWritingPage();
    const context = screen.getByTestId('rail-panel-context');
    const summary = screen.getByTestId('rail-panel-summary');
    const handle = screen.getByTestId('rail-resize-handle-0');

    // 下移 72px / 合计 720px = +0.1 → 2/3 + 0.1
    dragRailResize(handle, 72);
    expect(contextShare()).toBeCloseTo(2 / 3 + 0.1, 4);
    expect(parseFloat(context.style.flexGrow)).toBeGreaterThan(parseFloat(summary.style.flexGrow));

    // 向上猛拖 → 夹在上限侧的比例下限（summary 不得被压成 0 / 负）
    dragRailResize(handle, -5000);
    expect(contextShare()).toBeCloseTo(0.2, 6);
    expect(parseFloat(summary.style.flexGrow)).toBeGreaterThan(0);

    // 向下猛拖 → 夹在比例上限（context 不得吃光 summary）
    dragRailResize(handle, 5000);
    expect(contextShare()).toBeCloseTo(0.8, 6);
    expect(parseFloat(context.style.flexGrow)).toBeGreaterThan(0);
  });

  it('#1378 比例持久化：拖拽结束落盘（键含项目）→ 卸载重挂载回读保持', () => {
    stubPanelHeights(480, 240);
    const first = renderWritingPage();
    dragRailResize(screen.getByTestId('rail-resize-handle-0'), 72);

    const saved = JSON.parse(localStorage.getItem(railLayoutStorageKey('p1')) ?? 'null') as {
      split: number;
    } | null;
    expect(saved).not.toBeNull();
    expect(saved?.split).toBeCloseTo(2 / 3 + 0.1, 4);

    // 卸载（等价于切页/切章离开写作页）→ 重新挂载
    first.unmount();
    const second = renderWritingPage();
    expect(contextShare()).toBeCloseTo(saved?.split ?? 0, 6);

    // 反向断言：清掉记忆 → 回到默认 2:1（证明持久化确实是重挂载比例的来源）
    second.unmount();
    localStorage.clear();
    renderWritingPage();
    expect(contextShare()).toBeCloseTo(2 / 3, 6);
  });

  it('#1378 右栏宽度一并持久化（#720 拖拽结果原来同样只存组件 state）→ 重挂载保持', () => {
    const first = renderWritingPage();
    const rail = screen.getByTestId('right-rail');
    const startW = parseInt(rail.style.width, 10);
    dragRailWidth(screen.getByTestId('right-col-drag'), 100);

    const afterW = parseInt(rail.style.width, 10);
    expect(afterW).toBeGreaterThan(startW);
    const saved = JSON.parse(localStorage.getItem(railLayoutStorageKey('p1')) ?? 'null') as {
      width: number;
    } | null;
    expect(saved?.width).toBe(afterW);

    first.unmount();
    renderWritingPage();
    expect(parseInt(screen.getByTestId('right-rail').style.width, 10)).toBe(afterW);
  });

  it('#1378 项目维度隔离：切到另一项目读回该项目自己的右栏布局', () => {
    stubPanelHeights(480, 240);
    localStorage.setItem(railLayoutStorageKey('p1'), JSON.stringify({ split: 0.5, width: 300 }));
    localStorage.setItem(railLayoutStorageKey('p2'), JSON.stringify({ split: 0.8, width: 400 }));
    renderWritingPage();
    expect(contextShare()).toBeCloseTo(0.5, 6);
    expect(parseInt(screen.getByTestId('right-rail').style.width, 10)).toBe(300);

    // 切项目（writing.tsx 的 effectiveProjectId 变化）→ 回读 p2 的记忆
    act(() => {
      useProjectStore.setState({
        projects: [
          { id: 'p1', name: '青云志', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, config: {}, created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z' },
          { id: 'p2', name: '北风录', tags: ['武侠'], language: 'zh-CN', target_words: 500000, config: {}, created_at: '2026-08-02T10:00:00Z', updated_at: '2026-08-06T10:00:00Z' },
        ],
        currentProjectId: 'p2',
        loading: false,
        error: null,
      });
    });
    expect(contextShare()).toBeCloseTo(0.8, 6);
    expect(parseInt(screen.getByTestId('right-rail').style.width, 10)).toBe(400);
  });
});
