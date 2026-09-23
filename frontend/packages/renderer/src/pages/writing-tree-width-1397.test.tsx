/**
 * #1397：写作页**左栏**（项目树）宽度拖拽结果持久化 —— #1378 同族缺口契约。
 *
 * 现象：#702 起左栏宽度是受控 state（`writing.tsx: useState(208)`），但**无任何存储读写**
 *   → 拖完切页 / 切章 / 重挂载即回默认 208px（右栏的同类缺口已由 #1378 修掉）。
 *
 * 本文件锁三件事：
 * 1. 拖拽仍是「实时改宽度」的既有形态（#702 不回归）；
 * 2. mouseup 落盘到与右栏**同一键** `inkflow.rail_layout.<projectId>` 的 `treeWidth` 字段，
 *    且**部分写**不覆盖同键的 `split` / `width`（反向断言）；
 * 3. 卸载重挂载 / 切项目按记忆回读；越界夹 160~360；损坏回退 208。
 *
 * ⚠️ jsdom 无盒模型：宽度契约只读 `aside.style.width`（实现侧 treeWidth 受控），
 *   真实像素拖拽手感待人工 / GUI 复验（见 specs/f19-gui/writing.md §14）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { WritingPage } from './writing';
import { apiFetch } from '../api/client';
import { streamPipeline, executePipeline, confirmExecution } from '../api/pipeline';
import { createChatConversation, saveChatMessage } from '../api/chat';
import {
  DEFAULT_RAIL_SPLIT,
  DEFAULT_RAIL_WIDTH,
  DEFAULT_TREE_WIDTH,
  TREE_WIDTH_MAX,
  TREE_WIDTH_MIN,
  railLayoutStorageKey,
} from '../lib/railLayout';
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

/** WritingPage 需要 Router 上下文（useSearchParams）；统一用 MemoryRouter 包裹渲染 */
function renderWritingPage() {
  return render(
    <MemoryRouter initialEntries={['/writing']}>
      <WritingPage />
    </MemoryRouter>
  );
}

const seedVolumes = [{ id: 'v1', title: '第一卷 风起', order_index: 0 }];
const seedChapters = [
  { id: 'c1', title: '第1章 初见', volume_id: 'v1', order_index: 0, word_count: 2347 },
  { id: 'c2', title: '第2章 夜谈', volume_id: 'v1', order_index: 1, word_count: 0 },
];

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

const P1 = {
  id: 'p1',
  name: '青云志',
  tags: ['玄幻'],
  language: 'zh-CN',
  target_words: 800000,
  config: {},
  created_at: '2026-08-01T10:00:00Z',
  updated_at: '2026-08-05T10:00:00Z',
};
const P2 = {
  id: 'p2',
  name: '北风录',
  tags: ['武侠'],
  language: 'zh-CN',
  target_words: 500000,
  config: {},
  created_at: '2026-08-02T10:00:00Z',
  updated_at: '2026-08-06T10:00:00Z',
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
    volumes: seedVolumes,
    chapters: seedChapters,
    treeProjectId: 'p1',
    currentChapterId: 'c1',
    content: '已有正文第一段。',
    loading: false,
    error: null,
  });
  useProjectStore.setState({ projects: [P1], currentProjectId: 'p1', loading: false, error: null });
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

/** 左栏容器宽度（px）；实现侧 `style={{ width: treeWidth }}` 受控 */
function treeWidthPx(): number {
  return parseInt(screen.getByTestId('project-tree').style.width, 10);
}

/** 读落盘对象（键按项目隔离） */
function storedLayout(projectId: string): Record<string, unknown> | null {
  const raw = localStorage.getItem(railLayoutStorageKey(projectId));
  return raw === null ? null : (JSON.parse(raw) as Record<string, unknown>);
}

/** 拖一次左栏 col-resize 手柄：mousedown → mousemove(dx) → mouseup（mouseup 落盘）。 */
function dragTreeWidth(dx: number): void {
  const handle = screen.getByTestId('tree-resize-handle');
  fireEvent.mouseDown(handle, { clientX: 208, clientY: 100 });
  fireEvent.mouseMove(window, { clientX: 208 + dx, clientY: 100 });
  fireEvent.mouseUp(window);
}

describe('写作页 — 左栏宽度拖拽 + 持久化（#1397）', () => {
  it('#1397 默认宽 208px（无存储记忆）', () => {
    renderWritingPage();
    expect(treeWidthPx()).toBe(DEFAULT_TREE_WIDTH);
    expect(DEFAULT_TREE_WIDTH).toBe(208);
  });

  it('#1397 拖拽实时改宽（#702 不回归）+ mouseup 落盘到工作区布局键的 treeWidth 字段', () => {
    renderWritingPage();
    dragTreeWidth(100);
    expect(treeWidthPx()).toBe(308);

    // 落盘：同键（与右栏共用）+ 只带 treeWidth 的部分写
    const saved = storedLayout('p1');
    expect(saved?.treeWidth).toBe(308);

    // 反向断言（部分写不互相覆盖）：落盘对象里右栏两项仍是默认值，未被左栏写入清掉
    expect(saved?.split).toBeCloseTo(DEFAULT_RAIL_SPLIT, 10);
    expect(saved?.width).toBe(DEFAULT_RAIL_WIDTH);
  });

  it('#1397 持久化跨卸载重挂载保持；清掉记忆 → 回默认 208（反向断言记忆即来源）', () => {
    const first = renderWritingPage();
    dragTreeWidth(100);
    expect(treeWidthPx()).toBe(308);

    first.unmount();
    const second = renderWritingPage();
    expect(treeWidthPx()).toBe(308);

    // 反向断言：清掉记忆后重挂载必须回默认 —— 证明 308 确实来自持久化，而非组件内残留
    second.unmount();
    localStorage.clear();
    renderWritingPage();
    expect(treeWidthPx()).toBe(DEFAULT_TREE_WIDTH);
  });

  it('#1397 越界夹值：猛拖到底 / 到顶 → 夹在 160 / 360（与 ProjectTree 既有区间一致）', () => {
    renderWritingPage();
    dragTreeWidth(-5000);
    expect(treeWidthPx()).toBe(TREE_WIDTH_MIN);
    expect(storedLayout('p1')?.treeWidth).toBe(TREE_WIDTH_MIN);

    dragTreeWidth(5000);
    expect(treeWidthPx()).toBe(TREE_WIDTH_MAX);
    expect(storedLayout('p1')?.treeWidth).toBe(TREE_WIDTH_MAX);
  });

  it('#1397 存储损坏 / 非法 treeWidth → 回退默认 208，不崩 UI', () => {
    localStorage.setItem(railLayoutStorageKey('p1'), '{not-json');
    const first = renderWritingPage();
    expect(treeWidthPx()).toBe(DEFAULT_TREE_WIDTH);
    first.unmount();

    localStorage.setItem(
      railLayoutStorageKey('p1'),
      JSON.stringify({ split: 0.5, width: 300, treeWidth: 'wide' }),
    );
    renderWritingPage();
    expect(treeWidthPx()).toBe(DEFAULT_TREE_WIDTH);
  });

  it('#1397 项目维度隔离：切到另一项目读回该项目自己的左栏宽度', () => {
    localStorage.setItem(
      railLayoutStorageKey('p1'),
      JSON.stringify({ split: DEFAULT_RAIL_SPLIT, width: DEFAULT_RAIL_WIDTH, treeWidth: 300 }),
    );
    localStorage.setItem(
      railLayoutStorageKey('p2'),
      JSON.stringify({ split: DEFAULT_RAIL_SPLIT, width: DEFAULT_RAIL_WIDTH, treeWidth: 340 }),
    );
    renderWritingPage();
    expect(treeWidthPx()).toBe(300);

    act(() => {
      useProjectStore.setState({ projects: [P1, P2], currentProjectId: 'p2', loading: false, error: null });
    });
    expect(treeWidthPx()).toBe(340);
  });
});
