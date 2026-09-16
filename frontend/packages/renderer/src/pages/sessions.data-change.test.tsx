/**
 * 会话页数据面变更订阅接线（F23 §15.6.2 / #1090 批次 B）
 *
 * 契约（父侧设计裁定表 §3）：SessionsPage 登记 ['session']；事件到达 → 既有
 * `setReloadKey(k => k + 1)` 重新驱动三路列表 effect（三路均已依赖 reloadKey）：
 * - 执行会话：fetchSessions({includeDeleted:true}) → GET /api/v1/sessions
 * - 访谈会话：fetchPlannerSessions()            → GET /api/v1/agent/books/planner
 * - AI 对话：fetchChatConversations(...)        → GET /api/v1/chat/conversations
 * 端点路径实测自 src/api/sessions.ts:81 / api/sessions.ts:107 / api/chat.ts:227（均走 apiFetch）。
 * 全局会话（project_id 缺省）按 §15.6.3 全局生效；其他项目事件 / self-originated 不触发。
 *
 * mock：src/api/event-stream（捕获 emit/resync 手动驱动）+ src/api/client 的 apiFetch（端点
 * 计数；不 mock api/sessions 模块，直接锁真实端点路径）；其余端点一律空列表兜底。
 * 订阅调度层自带 300ms 防抖 → 真实计时器等待（emitAndSettle 400ms）。
 *
 * ⚠️ RED 阶段本页尚未接线 → subscribeDataChanges 永不被调用；renderAndSubscribe 限时轮询
 * 后静默放行（不 assert 订阅建立），保证失败落在「事件到达但三路端点未重拉」的断言上。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, render, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { SessionsPage } from './sessions';
import { apiFetch } from '../api/client';
import { subscribeDataChanges, type DataChangeFrame } from '../api/event-stream';
import { useKernelStore } from '../stores/kernel';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

vi.mock('../api/event-stream', () => ({ subscribeDataChanges: vi.fn() }));

const apiFetchMock = vi.mocked(apiFetch);
const subscribeMock = vi.mocked(subscribeDataChanges);

const projectP1 = {
  id: 'p1', name: '青云志', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, config: {},
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};

/** 三路列表端点（stripped path 即契约锚点） */
const SESSIONS_PATH = '/api/v1/sessions';
const PLANNER_PATH = '/api/v1/agent/books/planner';
const CHAT_PATH = '/api/v1/chat/conversations';

let emit: (ev: DataChangeFrame) => void;
let resync: () => void;

function ev(patch: Partial<DataChangeFrame> = {}): DataChangeFrame {
  return { domain: 'session', op: 'update', resource_id: 's1', project_id: 'p1', source: 'cli', ...patch };
}

function fetchCount(path: string): number {
  return apiFetchMock.mock.calls.filter((c) => String(c[0]).split('?')[0] === path).length;
}

/** 三路端点当前拉取快照（「事件 → 全量重拉」的观测面） */
function listsSnapshot(): Record<string, number> {
  return {
    sessions: fetchCount(SESSIONS_PATH),
    planner: fetchCount(PLANNER_PATH),
    chat: fetchCount(CHAT_PATH),
  };
}

async function emitAndSettle(frame: DataChangeFrame): Promise<void> {
  await act(async () => {
    emit(frame);
    await new Promise((resolve) => setTimeout(resolve, 400));
  });
}

/** 驱动重连兜底（event=null，无防抖，立即投递） */
async function triggerResync(): Promise<void> {
  await act(async () => {
    resync();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function renderAndSubscribe(): Promise<void> {
  render(
    <MemoryRouter initialEntries={['/sessions']}>
      <SessionsPage />
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
  localStorage.clear();
  useKernelStore.setState({ status: 'ready', booted: true, healthFailures: 0 });
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useToastStore.setState({ toasts: [] });
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
    // 三路列表端点：空列表形态（契约只看「是否被再次拉取」）
    if (path.startsWith('/api/v1/sessions')) return { items: [], total: 0, offset: 0, limit: 50 };
    if (path.startsWith('/api/v1/agent/books/planner')) return { items: [], total: 0 };
    if (path.startsWith('/api/v1/chat/conversations')) return { items: [], total: 0 };
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

afterEach(() => {
  useKernelStore.setState({ status: 'booting', booted: false, healthFailures: 0 });
});

describe('会话页 — 数据面变更订阅接线（F23 §15.6.2 / #1090 B）', () => {
  it('session 事件（当前项目）→ 三路列表端点全量重拉', async () => {
    await renderAndSubscribe();
    await waitFor(() => expect(fetchCount(SESSIONS_PATH)).toBeGreaterThan(0));
    const before = listsSnapshot();

    await emitAndSettle(ev({ domain: 'session', op: 'update', resource_id: 's1' }));

    const after = listsSnapshot();
    expect(after.sessions).toBeGreaterThan(before.sessions);
    expect(after.planner).toBeGreaterThan(before.planner);
    expect(after.chat).toBeGreaterThan(before.chat);
  });

  it('session 事件（project_id 缺省 = 全局会话）→ 三路列表端点全量重拉', async () => {
    await renderAndSubscribe();
    await waitFor(() => expect(fetchCount(SESSIONS_PATH)).toBeGreaterThan(0));
    const before = listsSnapshot();

    await emitAndSettle({ domain: 'session', op: 'create', resource_id: 's9', source: 'cli' });

    const after = listsSnapshot();
    expect(after.sessions).toBeGreaterThan(before.sessions);
    expect(after.planner).toBeGreaterThan(before.planner);
    expect(after.chat).toBeGreaterThan(before.chat);
  });

  it('反例：其他项目（p2）的 session 事件不触发重拉', async () => {
    await renderAndSubscribe();
    await waitFor(() => expect(fetchCount(SESSIONS_PATH)).toBeGreaterThan(0));
    const before = listsSnapshot();

    await emitAndSettle(ev({ domain: 'session', project_id: 'p2' }));

    expect(listsSnapshot()).toEqual(before);
  });

  it('反例：self-originated（source=gui）不触发重拉', async () => {
    await renderAndSubscribe();
    await waitFor(() => expect(fetchCount(SESSIONS_PATH)).toBeGreaterThan(0));
    const before = listsSnapshot();

    await emitAndSettle(ev({ domain: 'session', source: 'gui' }));

    expect(listsSnapshot()).toEqual(before);
  });

  it('重连兜底（event=null）→ 三路列表端点全量重拉', async () => {
    await renderAndSubscribe();
    await waitFor(() => expect(fetchCount(SESSIONS_PATH)).toBeGreaterThan(0));
    const before = listsSnapshot();

    await triggerResync();

    const after = listsSnapshot();
    expect(after.sessions).toBeGreaterThan(before.sessions);
    expect(after.planner).toBeGreaterThan(before.planner);
    expect(after.chat).toBeGreaterThan(before.chat);
  });
});
