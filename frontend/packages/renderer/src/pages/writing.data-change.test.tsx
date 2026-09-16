/**
 * 写作页数据面变更订阅接线（F23 §15.6.2 / #1090 批次 B）
 *
 * 契约（父侧设计裁定表 §3）：WritingPage 登记 ['chapter', 'volume'] 两个项目域；
 * 事件到达 → 回调执行 `if (currentProjectId) void loadChapterTree(currentProjectId)`
 * （useChapterStore.loadChapterTree = GET /api/v1/projects/{pid}/volumes +
 * GET /api/v1/projects/{pid}/chapters，卷/章两面同属一棵树 → 两个端点计数都应增长）。
 * 「仅当前项目」由 hook 的 affectsCurrent 保证（project_id 缺省 = 全局生效；其他项目
 * 事件不触发）；source=gui 自产事件在调度层跳过。重连兜底（event=null）同样重拉。
 *
 * mock：src/api/event-stream（捕获 emit/resync 手动驱动）+ src/api/client 的 apiFetch
 * （断端点计数）+ 有副作用的 api 模块（pipeline / chat，整页挂载不触发，仅防 import 期
 * 真实网络）+ 播种 stores（chapter / project / kernel）。镜像 writing.test.tsx 形态。
 * 订阅调度层自带 300ms 防抖 → 真实计时器等待（emitAndSettle 400ms）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, render, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { WritingPage } from './writing';
import { apiFetch } from '../api/client';
import { subscribeDataChanges, type DataChangeFrame } from '../api/event-stream';
import { useChapterStore } from '../stores/chapter';
import { useKernelStore } from '../stores/kernel';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';
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

vi.mock('../api/event-stream', () => ({ subscribeDataChanges: vi.fn() }));

const apiFetchMock = vi.mocked(apiFetch);
const subscribeMock = vi.mocked(subscribeDataChanges);

const projectP1 = {
  id: 'p1', name: '青云志', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, config: {},
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};

const seedVolumes = [{ id: 'v1', title: '第一卷 风起', order_index: 0 }];
const seedChapters = [
  { id: 'c1', title: '第1章 初见', volume_id: 'v1', order_index: 0, word_count: 2347 },
];

let emit: (ev: DataChangeFrame) => void;
let resync: () => void;

function ev(patch: Partial<DataChangeFrame> = {}): DataChangeFrame {
  return { domain: 'chapter', op: 'create', resource_id: 'c9', source: 'cli', ...patch };
}

/** 命中某端点的拉取次数（strip querystring，契约 = 该端点被再次拉取） */
function fetchCount(path: string): number {
  return apiFetchMock.mock.calls.filter((c) => String(c[0]).split('?')[0] === path).length;
}

async function emitAndSettle(frame: DataChangeFrame): Promise<void> {
  await act(async () => {
    emit(frame);
    await new Promise((resolve) => setTimeout(resolve, 400));
  });
}

/** 卷/章两个端点的当前拉取快照（loadChapterTree 的观测面） */
function treeSnapshot(): { volumes: number; chapters: number } {
  return {
    volumes: fetchCount('/api/v1/projects/p1/volumes'),
    chapters: fetchCount('/api/v1/projects/p1/chapters'),
  };
}

/**
 * 渲染整页并等待单例订阅建立 + 冲刷挂载期在途请求（loadChapterTree / fetchConfig / 草稿）。
 *
 * ⚠️ RED 阶段本页尚未接线 → subscribeDataChanges 永不被调用；此处**不 assert 订阅建立**
 * （否则 RED 失败形态会退化为 harness 超时），改为限时轮询后静默放行 —— 失败必须落在
 * 「事件到达但端点未重拉」的断言上。
 */
async function renderAndSubscribe(): Promise<void> {
  render(
    <MemoryRouter initialEntries={['/writing']}>
      <WritingPage />
    </MemoryRouter>,
  );
  for (let i = 0; i < 50 && subscribeMock.mock.calls.length === 0; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
  }
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

beforeEach(() => {
  apiFetchMock.mockReset();
  subscribeMock.mockReset();
  emit = () => {};
  resync = () => {};
  subscribeMock.mockImplementation(async (onEvent, _onError, onReconnect) => {
    emit = onEvent;
    resync = onReconnect ?? (() => {});
    return () => {};
  });
  window.INKFLOW_API = { baseURL: 'http://test.local', token: 'tok-1' };
  localStorage.clear();
  useKernelStore.setState({ status: 'ready', booted: true, healthFailures: 0 });
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useToastStore.setState({ toasts: [] });
  useChapterStore.setState({
    volumes: seedVolumes, chapters: seedChapters, treeProjectId: 'p1', currentChapterId: 'c1',
    content: '已有正文第一段。', loading: false, error: null,
  });
  useProjectStore.setState({
    projects: [projectP1],
    currentProjectId: 'p1',
    loading: false,
    error: null,
  });
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/projects') {
      return { items: [projectP1], total: 1, offset: 0, limit: 50 };
    }
    if (path === '/api/v1/projects/p1/volumes') return { items: seedVolumes };
    if (path === '/api/v1/projects/p1/chapters') {
      return { items: seedChapters, total: 1, offset: 0, limit: 50 };
    }
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

afterEach(() => {
  delete window.INKFLOW_API;
  useKernelStore.setState({ status: 'booting', booted: false, healthFailures: 0 });
});

describe('写作页 — 数据面变更订阅接线（F23 §15.6.2 / #1090 B）', () => {
  it('chapter 事件（当前项目）→ 卷章树全量重拉（volumes + chapters 双端点）', async () => {
    await renderAndSubscribe();
    await waitFor(() => expect(treeSnapshot().volumes).toBeGreaterThan(0));
    const before = treeSnapshot();

    await emitAndSettle(ev({ domain: 'chapter', op: 'create', resource_id: 'c9' }));

    const after = treeSnapshot();
    expect(after.volumes).toBeGreaterThan(before.volumes);
    expect(after.chapters).toBeGreaterThan(before.chapters);
  }, 15000);

  it('volume 事件（当前项目）→ 卷章树全量重拉（卷删除级联移章，两面同刷）', async () => {
    await renderAndSubscribe();
    await waitFor(() => expect(treeSnapshot().volumes).toBeGreaterThan(0));
    const before = treeSnapshot();

    await emitAndSettle(ev({ domain: 'volume', op: 'delete', resource_id: 'v1' }));

    const after = treeSnapshot();
    expect(after.volumes).toBeGreaterThan(before.volumes);
    expect(after.chapters).toBeGreaterThan(before.chapters);
  }, 15000);

  it('反例：其他项目（p2）的 chapter 事件不触发重拉', async () => {
    await renderAndSubscribe();
    await waitFor(() => expect(treeSnapshot().volumes).toBeGreaterThan(0));
    const before = treeSnapshot();

    await emitAndSettle(ev({ domain: 'chapter', project_id: 'p2' }));

    expect(treeSnapshot()).toEqual(before);
  }, 15000);

  it('反例：self-originated（source=gui）不触发重拉', async () => {
    await renderAndSubscribe();
    await waitFor(() => expect(treeSnapshot().volumes).toBeGreaterThan(0));
    const before = treeSnapshot();

    await emitAndSettle(ev({ domain: 'chapter', source: 'gui' }));

    expect(treeSnapshot()).toEqual(before);
  }, 15000);

  it('重连兜底（event=null）→ 卷章树全量重拉', async () => {
    await renderAndSubscribe();
    await waitFor(() => expect(treeSnapshot().volumes).toBeGreaterThan(0));
    const before = treeSnapshot();

    await act(async () => {
      resync();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(treeSnapshot().volumes).toBeGreaterThan(before.volumes);
  }, 15000);
});
