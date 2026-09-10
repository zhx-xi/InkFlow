/**
 * 设定库页数据面变更订阅接线（F23 §15.6.2 / #1088 批 A3）
 *
 * 契约：LibraryPage 登记 map / map_pin / character(+group/relation) / outline(+plot_point/story_arc)
 * 八个项目域；事件到达（含重连兜底 event=null）→ 复用既有 reloadKey 全量重拉（FR 粒度裁决，
 * 不新增 store 局部更新路径）。self-originated（source=gui）与非当前项目事件不触发重拉
 * （过滤在 useDataChangeSubscription 内，本文件验证页面消费面）。
 *
 * mock：src/api/event-stream（捕获帧回调手动驱动，同 hooks/useDataChangeSubscription.test.ts）
 * + src/api/client 的 apiFetch（断言端点重拉次数）；订阅调度层自带 300ms 防抖 → 以真实
 * 计时器等待（emitAndSettle 400ms）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, render, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { LibraryPage } from './library';
import { apiFetch } from '../api/client';
import { subscribeDataChanges, type DataChangeFrame } from '../api/event-stream';
import { useKernelStore } from '../stores/kernel';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';

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

/** 帧回调捕获（订阅建立后由 mock 实现赋值） */
let emit: (ev: DataChangeFrame) => void;
/** 重连回调捕获（重连成功 → 订阅者收到 event=null 兜底全量 refetch） */
let resync: () => void;

function ev(patch: Partial<DataChangeFrame> = {}): DataChangeFrame {
  return { domain: 'map', op: 'create', resource_id: 'm1', project_id: 'p1', source: 'cli', ...patch };
}

/** 命中某端点的拉取次数（strip querystring，契约 = 该端点被再次拉取） */
function fetchCount(path: string): number {
  return apiFetchMock.mock.calls.filter((c) => String(c[0]).split('?')[0] === path).length;
}

/** 驱动一个事件帧并推进超过防抖窗口（300ms） */
async function emitAndSettle(frame: DataChangeFrame): Promise<void> {
  await act(async () => {
    emit(frame);
    await new Promise((resolve) => setTimeout(resolve, 400));
  });
}

/** 驱动重连兜底（无防抖，立即投递 event=null） */
async function triggerResync(): Promise<void> {
  await act(async () => {
    resync();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function renderLibrary(initialPath = '/library') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <LibraryPage />
    </MemoryRouter>,
  );
}

/** 渲染并等待单例订阅建立（订阅在 ensureApiReady 之后异步发起） */
async function renderAndSubscribe(initialPath = '/library'): Promise<void> {
  renderLibrary(initialPath);
  await waitFor(() => expect(subscribeMock).toHaveBeenCalled());
  // 冲刷挂载期在途请求（项目列表 / 分类端点）→ 避免测试收尾 act 警告
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
    if (path.startsWith('/api/v1/projects/p1/maps')) {
      return { items: [], total: 0, offset: 0, limit: 50 };
    }
    if (path.startsWith('/api/v1/projects/p1/characters')) {
      return { items: [{ id: 'c1', name: '林晚' }], total: 1, offset: 0, limit: 50 };
    }
    if (path.startsWith('/api/v1/projects/p1/outlines')) {
      return { items: [{ id: 'o1', name: '卷一 风起' }], total: 1, offset: 0, limit: 50 };
    }
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

afterEach(() => {
  useKernelStore.setState({ status: 'booting', booted: false, healthFailures: 0 });
});

describe('设定库页 — 数据面变更订阅（F23 §15.6.2 / #1088 A3）', () => {
  it('map 事件（外部写入）→ 地图列表端点全量重拉', async () => {
    await renderAndSubscribe();
    await waitFor(() => expect(fetchCount('/api/v1/projects/p1/maps')).toBeGreaterThan(0));
    const before = fetchCount('/api/v1/projects/p1/maps');

    await emitAndSettle(ev({ domain: 'map', op: 'create', resource_id: 'm9' }));

    expect(fetchCount('/api/v1/projects/p1/maps')).toBeGreaterThan(before);
  });

  it('character 事件 → 角色分类端点全量重拉（当前 tab = characters）', async () => {
    await renderAndSubscribe();
    await waitFor(() =>
      expect(fetchCount('/api/v1/projects/p1/characters')).toBeGreaterThan(0),
    );
    const before = fetchCount('/api/v1/projects/p1/characters');

    await emitAndSettle(ev({ domain: 'character', op: 'update', resource_id: 'c1' }));

    expect(fetchCount('/api/v1/projects/p1/characters')).toBeGreaterThan(before);
  });

  it('character_relation 子实体事件同样触发角色面重拉', async () => {
    await renderAndSubscribe();
    await waitFor(() =>
      expect(fetchCount('/api/v1/projects/p1/characters')).toBeGreaterThan(0),
    );
    const before = fetchCount('/api/v1/projects/p1/characters');

    await emitAndSettle(ev({ domain: 'character_relation', op: 'create', resource_id: 'r1' }));

    expect(fetchCount('/api/v1/projects/p1/characters')).toBeGreaterThan(before);
  });

  it('outline 事件（当前 tab = outline）→ 大纲端点全量重拉', async () => {
    await renderAndSubscribe('/library?cat=outline');
    await waitFor(() => expect(fetchCount('/api/v1/projects/p1/outlines')).toBeGreaterThan(0));
    const before = fetchCount('/api/v1/projects/p1/outlines');

    await emitAndSettle(ev({ domain: 'outline', op: 'create', resource_id: 'o9' }));

    expect(fetchCount('/api/v1/projects/p1/outlines')).toBeGreaterThan(before);
  });

  it('story_arc 子实体事件同样触发大纲面重拉', async () => {
    await renderAndSubscribe('/library?cat=outline');
    await waitFor(() => expect(fetchCount('/api/v1/projects/p1/outlines')).toBeGreaterThan(0));
    const before = fetchCount('/api/v1/projects/p1/outlines');

    await emitAndSettle(ev({ domain: 'story_arc', op: 'delete', resource_id: 'a1' }));

    expect(fetchCount('/api/v1/projects/p1/outlines')).toBeGreaterThan(before);
  });

  it('重连兜底（event=null）→ 全量重拉（不受 domain 过滤限制）', async () => {
    await renderAndSubscribe('/library?cat=outline');
    await waitFor(() => expect(fetchCount('/api/v1/projects/p1/maps')).toBeGreaterThan(0));
    const mapsBefore = fetchCount('/api/v1/projects/p1/maps');
    const outlinesBefore = fetchCount('/api/v1/projects/p1/outlines');

    await triggerResync();

    expect(fetchCount('/api/v1/projects/p1/maps')).toBeGreaterThan(mapsBefore);
    expect(fetchCount('/api/v1/projects/p1/outlines')).toBeGreaterThan(outlinesBefore);
  });

  it('反例：self-originated（source=gui）不触发重拉', async () => {
    await renderAndSubscribe();
    await waitFor(() => expect(fetchCount('/api/v1/projects/p1/maps')).toBeGreaterThan(0));
    const before = fetchCount('/api/v1/projects/p1/maps');

    await emitAndSettle(ev({ domain: 'map', source: 'gui' }));

    expect(fetchCount('/api/v1/projects/p1/maps')).toBe(before);
  });

  it('反例：其他项目的事件不触发当前项目重拉', async () => {
    await renderAndSubscribe();
    await waitFor(() => expect(fetchCount('/api/v1/projects/p1/maps')).toBeGreaterThan(0));
    const before = fetchCount('/api/v1/projects/p1/maps');

    await emitAndSettle(ev({ domain: 'map', project_id: 'p2' }));

    expect(fetchCount('/api/v1/projects/p1/maps')).toBe(before);
  });
});
