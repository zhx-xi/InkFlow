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
import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { WritingPage } from './writing';
import { apiFetch } from '../api/client';
import { streamPipeline, executePipeline, confirmExecution } from '../api/pipeline';
import { createChatConversation, saveChatMessage } from '../api/chat';
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
