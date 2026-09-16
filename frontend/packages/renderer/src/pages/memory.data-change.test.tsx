/**
 * 记忆页数据面变更订阅接线（F23 §15.6.2 / #1090 批次 B，双作用域）
 *
 * 契约（父侧设计裁定表 §3）：MemoryPage 登记 ['memory']；事件到达 → 新增的
 * `setReloadKey(k => k + 1)` 重新驱动挂载加载 effect（GREEN 需把 reloadKey 并入
 * `[pid, pushToast, reloadKey]`）→ 三路端点全量重拉：
 * - 语义总结：fetchMemorySummaries(pid) → GET /api/v1/agent/memory/summaries
 * - 项目偏好：fetchProjectPreferences(pid) → GET /api/v1/agent/preferences
 * - 用户偏好：fetchUserPreferences()        → GET /api/v1/agent/user-preferences
 * 端点路径实测自 src/api/memory.ts:71/126/139（均走 apiFetch）。
 * 双作用域由 hook 的 affectsCurrent 保证：项目偏好事件带 pid 仅当前项目生效；
 * 用户偏好事件 project_id=null（§15.2.3 全局）对任意项目页生效；其他项目事件不触发。
 *
 * mock：src/api/event-stream（捕获 emit/resync 手动驱动）+ src/api/client 的 apiFetch（端点
 * 计数；不 mock api/memory 模块，直接锁真实端点路径）。其余端点一律空列表兜底。
 * 订阅调度层自带 300ms 防抖 → 真实计时器等待（emitAndSettle 400ms）。
 *
 * ⚠️ RED 阶段本页尚未接线 → subscribeDataChanges 永不被调用；renderAndSubscribe 限时轮询
 * 后静默放行（不 assert 订阅建立），保证失败落在「事件到达但端点未重拉」的断言上。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, render, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { MemoryPage } from './memory';
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

/** 三路记忆数据面端点（stripped path 即契约锚点） */
const SUMMARIES_PATH = '/api/v1/agent/memory/summaries';
const PROJECT_PREFS_PATH = '/api/v1/agent/preferences';
const USER_PREFS_PATH = '/api/v1/agent/user-preferences';

let emit: (ev: DataChangeFrame) => void;
let resync: () => void;

function ev(patch: Partial<DataChangeFrame> = {}): DataChangeFrame {
  return { domain: 'memory', op: 'update', resource_id: 'mem1', project_id: 'p1', source: 'cli', ...patch };
}

function fetchCount(path: string): number {
  return apiFetchMock.mock.calls.filter((c) => String(c[0]).split('?')[0] === path).length;
}

/** 三路端点当前拉取快照（「事件 → 全量重拉」的观测面） */
function memorySnapshot(): Record<string, number> {
  return {
    summaries: fetchCount(SUMMARIES_PATH),
    projectPrefs: fetchCount(PROJECT_PREFS_PATH),
    userPrefs: fetchCount(USER_PREFS_PATH),
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
    <MemoryRouter initialEntries={['/memory']}>
      <MemoryPage />
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
    if (path.startsWith(SUMMARIES_PATH)) {
      return { project_id: 'p1', project: null, user: null };
    }
    if (path.startsWith('/api/v1/agent/memory/stats')) {
      return {
        project_id: 'p1',
        agentic: { chapters: 0, direct_confirms: 0, avg_diff_chars: 0, modify_rate: 0, regenerate_rate: 0 },
        learned_preferences: 0,
        baseline_ref: '',
        user_preferences: null,
      };
    }
    // 项目偏好 / 用户偏好 / 其余端点：空列表形态
    return { items: [], total: 0 };
  });
});

afterEach(() => {
  useKernelStore.setState({ status: 'booting', booted: false, healthFailures: 0 });
});

describe('记忆页 — 数据面变更订阅接线（F23 §15.6.2 / #1090 B）', () => {
  it('memory 事件（当前项目 p1）→ 总结 + 项目偏好 + 用户偏好三路端点全量重拉', async () => {
    await renderAndSubscribe();
    await waitFor(() => expect(fetchCount(SUMMARIES_PATH)).toBeGreaterThan(0));
    const before = memorySnapshot();

    await emitAndSettle(ev({ domain: 'memory', op: 'update', resource_id: 'mem1' }));

    const after = memorySnapshot();
    expect(after.summaries).toBeGreaterThan(before.summaries);
    expect(after.projectPrefs).toBeGreaterThan(before.projectPrefs);
    expect(after.userPrefs).toBeGreaterThan(before.userPrefs);
  });

  it('memory 事件（project_id 缺省 = 全局用户偏好）→ 三路端点全量重拉', async () => {
    await renderAndSubscribe();
    await waitFor(() => expect(fetchCount(SUMMARIES_PATH)).toBeGreaterThan(0));
    const before = memorySnapshot();

    await emitAndSettle({ domain: 'memory', op: 'create', resource_id: 'up9', source: 'cli' });

    const after = memorySnapshot();
    expect(after.summaries).toBeGreaterThan(before.summaries);
    expect(after.projectPrefs).toBeGreaterThan(before.projectPrefs);
    expect(after.userPrefs).toBeGreaterThan(before.userPrefs);
  });

  it('反例：其他项目（p2）的 memory 事件不触发重拉', async () => {
    await renderAndSubscribe();
    await waitFor(() => expect(fetchCount(SUMMARIES_PATH)).toBeGreaterThan(0));
    const before = memorySnapshot();

    await emitAndSettle(ev({ domain: 'memory', project_id: 'p2' }));

    expect(memorySnapshot()).toEqual(before);
  });

  it('反例：self-originated（source=gui）不触发重拉', async () => {
    await renderAndSubscribe();
    await waitFor(() => expect(fetchCount(SUMMARIES_PATH)).toBeGreaterThan(0));
    const before = memorySnapshot();

    await emitAndSettle(ev({ domain: 'memory', source: 'gui' }));

    expect(memorySnapshot()).toEqual(before);
  });

  it('重连兜底（event=null）→ 三路端点全量重拉', async () => {
    await renderAndSubscribe();
    await waitFor(() => expect(fetchCount(SUMMARIES_PATH)).toBeGreaterThan(0));
    const before = memorySnapshot();

    await triggerResync();

    const after = memorySnapshot();
    expect(after.summaries).toBeGreaterThan(before.summaries);
    expect(after.projectPrefs).toBeGreaterThan(before.projectPrefs);
    expect(after.userPrefs).toBeGreaterThan(before.userPrefs);
  });
});
