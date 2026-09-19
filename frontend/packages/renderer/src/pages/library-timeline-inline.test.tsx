/**
 * #1302 时间线/伏笔行内编辑与删除入口（spec §5.1 D12 形态复用；对齐 LibraryItemList.tsx:148-167 先例）。
 *
 * ==================== RED 契约 ====================
 *
 * 【缺口】后端 CRUD 端点全齐（backend/src/inkflow/api/routers/timeline.py:259 PATCH / :275 DELETE；
 *   foreshadowings.py:196 PATCH / :215 DELETE），且 library.tsx 已持有编辑/删除全套机制
 *   （PATCH_ENDPOINTS/DELETE_ENDPOINTS 已含 timeline/foreshadow，:68-82；editing/pendingDelete
 *   状态 :127/:131；handleSave :387 / handleDelete :422；ConfirmDialog :869）。
 *   唯一缺口 = **TimelineView 未接 onEdit/onDelete**（library.tsx:777-781 只传三个 props），
 *   故时间线行内无任何编辑/删除入口。
 *
 * 【本契约断言】TimelineView 行内补编辑/删除入口，形态照抄 LibraryItemList.tsx:148-149
 *   （group-hover + focus-within 双触发，保证键盘可达）：
 * - N1 时间线每行有 tl-edit-<id> + tl-delete-<id>（编辑/删除入口浮现）
 * - N2 既有按钮保留：tl-check-one-<id> 不得被挤掉（列表 = 编辑/删除/单事件检查共存）
 * - N3 无障碍：操作容器带 focus-within:opacity-100（仅 hover 不可达键盘用户 → 必须带）
 * - N4 点 tl-edit-<id> → LibraryCreateDialog 以编辑模式打开（预填该事件标题到
 *   library-create-dialog 的 library-create-name 输入框）
 * - N5 点 tl-delete-<id> → 二次确认（lib-confirm-dialog）→ 确认 → DELETE 扁平端点
 * - N6 DELETE 成功后 → 列表重新拉取（reloadKey 机制）+ 条目消失
 * - N7 伏笔同为扁平分类，行内 lib-edit-/lib-delete- 入口存在（LibraryItemList 承载）
 *
 * RED 预期：N1-N6 因 tl-edit-<id>/tl-delete-<id> 不存在而 element-missing FAIL；
 *   N7 已绿（LibraryItemList 既有形态）→ 作回归守护，防止本次改动破坏伏笔入口。
 * 零 SyntaxError / ReferenceError / TypeError。
 *
 * 【自证】去掉 TimelineView 的行内操作块 → N1/N2/N3/N4/N5/N6 必 FAIL（见 PR 说明的变异验证）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { LibraryPage } from './library';
import { apiFetch } from '../api/client';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const projectP1 = {
  id: 'p1', name: '青云志', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, config: {},
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};

/** 时间线事件 seed（§2.9 字段；id/title 可区分，供编辑预填与删除定位） */
const evA: Record<string, unknown> = {
  id: 'evA', title: '甲 登基', description: '甲登基', time_value: 300, time_unit: 'year',
  time_display: '300 年', narrative_position: 3, timeline_flag: false,
};
const evB: Record<string, unknown> = {
  id: 'evB', title: '乙 失踪', description: '', time_value: null, time_unit: null,
  time_display: '未知', narrative_position: 1, timeline_flag: false,
};
const evC: Record<string, unknown> = {
  id: 'evC', title: '丙 初现', description: '', time_value: 100, time_unit: 'year',
  time_display: '100 年', narrative_position: 2, timeline_flag: false,
};

/** 时间线双视图（叙事序：evB→evC→evA） */
const timelineView: Record<string, unknown> = {
  project_id: 'p1',
  total: 3,
  event_timeline: [evC, evA, evB],
  narrative_order: [evB, evC, evA],
};

/** 伏笔 seed（扁平分类；LibraryItemList 承载 lib-edit-/lib-delete-） */
const fsA: Record<string, unknown> = {
  id: 'fsA', title: '玉佩来历', description: '伏笔描述', status: 'open', extra: {},
};

function renderLibrary() {
  return render(
    <MemoryRouter initialEntries={['/library']}>
      <LibraryPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  useToastStore.setState({ toasts: [] });
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/timeline') {
      return { project_id: 'p1', total: 0, event_timeline: [], narrative_order: [] };
    }
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

/**
 * 播种 p1 + 时间线双视图 + 记录 DELETE 调用（timeline 分类）。
 * timelineList 每次请求返回浅拷贝 → 删除后可改为「不含被删项」验证列表刷新。
 */
function mockTimeline(list: Record<string, unknown>) {
  let current = list;
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/timeline') {
      const events = (current.event_timeline as Array<Record<string, unknown>>).map((e) => ({ ...e }));
      const narrative = (current.narrative_order as Array<Record<string, unknown>>).map((e) => ({ ...e }));
      return { project_id: 'p1', total: events.length, event_timeline: events, narrative_order: narrative };
    }
    if (path === '/api/v1/projects/p1/timeline/check') {
      return { checked: 0, skipped: 0, consistent: true, conflicts: [], flashbacks: [] };
    }
    if (init?.method === 'DELETE') return { ok: true };
    if (init?.method === 'PATCH') return { ok: true };
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
  act(() => {
    useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
  });
  return {
    /** 模拟服务端删除后返回的列表（供「删除后刷新」断言） */
    setList(next: Record<string, unknown>) {
      current = next;
    },
  };
}

/** 切到时间线 tab 并等事件行渲染 */
async function openTimelineTab(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('tab', { name: '时间线' }));
  await waitFor(() =>
    expect(within(screen.getByTestId('library-list')).getAllByRole('listitem')).toHaveLength(3),
  );
}

/** 行内操作按钮序列（tl-edit-<id>）→ 事件 id 序列（DOM 行序基准） */
const editRowIds = () =>
  screen.getAllByTestId(/^tl-edit-/).map((el) => el.getAttribute('data-testid')!.replace('tl-edit-', ''));

/** timeline 列表端点 GET 次数（删除后刷新断言基准） */
const timelineGetCount = () =>
  apiFetchMock.mock.calls.filter((c) => c[0] === '/api/v1/projects/p1/timeline').length;

describe('#1302 时间线行内编辑/删除入口', () => {
  it('N1 每行渲染 tl-edit-<id> + tl-delete-<id>（编辑/删除入口存在，行序 = 显示数组序）', async () => {
    mockTimeline(timelineView);
    renderLibrary();
    const user = userEvent.setup();
    await openTimelineTab(user);
    // 编辑入口：每行一个，行序 = 叙事序（默认叙事序）
    await waitFor(() => expect(editRowIds()).toEqual(['evB', 'evC', 'evA']));
    // 删除入口：每行一个
    expect(screen.getAllByTestId(/^tl-delete-/)).toHaveLength(3);
    expect(screen.getByTestId('tl-delete-evA')).toBeInTheDocument();
    expect(screen.getByTestId('tl-delete-evB')).toBeInTheDocument();
    expect(screen.getByTestId('tl-delete-evC')).toBeInTheDocument();
  });

  it('N2 既有按钮保留：tl-check-one-<id> 与编辑/删除共存（每行 3 个操作按钮）', async () => {
    mockTimeline(timelineView);
    renderLibrary();
    const user = userEvent.setup();
    await openTimelineTab(user);
    // 既有单事件检查按钮未被挤掉
    await waitFor(() => expect(screen.getAllByTestId(/^tl-check-one-/)).toHaveLength(3));
    // 每个列表行同时含 3 个操作按钮（编辑 + 删除 + 单事件检查）
    const rows = within(screen.getByTestId('library-list')).getAllByRole('listitem');
    for (const row of rows) {
      expect(within(row).getAllByRole('button')).toHaveLength(3);
    }
  });

  it('N3 无障碍：操作容器带 focus-within:opacity-100（对齐 LibraryItemList 先例 D12）', async () => {
    mockTimeline(timelineView);
    renderLibrary();
    const user = userEvent.setup();
    await openTimelineTab(user);
    const editBtn = screen.getByTestId('tl-edit-evA');
    // 操作按钮所在的浮现容器 = 最近带 group-hover 的祖先
    const container = editBtn.closest('[class*="group-hover:opacity-100"]');
    expect(container).not.toBeNull();
    // 仅 hover 不可达键盘用户 → 必须同时带 focus-within
    expect(container!.className).toContain('focus-within:opacity-100');
    expect(container!.className).toContain('opacity-0');
  });

  it('N4 点 tl-edit-<id> → LibraryCreateDialog 以编辑模式打开（预填该事件标题）', async () => {
    mockTimeline(timelineView);
    renderLibrary();
    const user = userEvent.setup();
    await openTimelineTab(user);
    await user.click(screen.getByTestId('tl-edit-evA'));
    const dialog = await screen.findByTestId('library-create-dialog');
    expect(within(dialog).getByTestId('library-create-name')).toHaveValue('甲 登基');
  });

  it('N5 点 tl-delete-<id> → 二次确认 → 确认 → DELETE /api/v1/timeline/events/<id>', async () => {
    mockTimeline(timelineView);
    renderLibrary();
    const user = userEvent.setup();
    await openTimelineTab(user);
    await user.click(screen.getByTestId('tl-delete-evB'));
    // 二次确认弹出（对齐既有 lib-confirm-dialog 契约）
    const confirm = await screen.findByTestId('lib-confirm-dialog');
    expect(confirm).toBeInTheDocument();
    // 确认前不得发 DELETE（真的是「二次」确认）
    expect(apiFetchMock.mock.calls.filter((c) => (c[1] as Record<string, unknown>)?.method === 'DELETE')).toHaveLength(0);
    await user.click(screen.getByTestId('lib-confirm-ok'));
    await waitFor(() =>
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/timeline/events/evB', { method: 'DELETE' }),
    );
  });

  it('N6 删除成功后列表刷新：重新拉取 timeline 端点 + 被删条目消失', async () => {
    const handle = mockTimeline(timelineView);
    renderLibrary();
    const user = userEvent.setup();
    await openTimelineTab(user);
    const before = timelineGetCount();
    await user.click(screen.getByTestId('tl-delete-evB'));
    await screen.findByTestId('lib-confirm-dialog');
    // 服务端此时已不含 evB（下次 GET 返回该形状）
    handle.setList({ project_id: 'p1', total: 2, event_timeline: [evC, evA], narrative_order: [evC, evA] });
    await user.click(screen.getByTestId('lib-confirm-ok'));
    // 列表重新拉取
    await waitFor(() => expect(timelineGetCount()).toBeGreaterThan(before));
    // 被删条目消失
    await waitFor(() => expect(screen.queryByTestId('tl-delete-evB')).not.toBeInTheDocument());
  });
});

describe('#1302 伏笔行内编辑/删除入口（回归守护 + 分支确认）', () => {
  it('N7 伏笔 tab 行内 lib-edit-<id> / lib-delete-<id> 存在且可用（LibraryItemList 承载）', async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
      // #1300 起 foreshadow 为服务端分页分类（URL 带 ?limit=&offset=）→ 前缀匹配，勿写死裸路径
      if (path.startsWith('/api/v1/projects/p1/foreshadowings')) {
        return { items: [fsA], total: 1, offset: 0, limit: 50 };
      }
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    renderLibrary();
    const user = userEvent.setup();
    await user.click(screen.getByRole('tab', { name: '伏笔' }));
    await waitFor(() => expect(screen.getByTestId('lib-edit-fsA')).toBeInTheDocument());
    expect(screen.getByTestId('lib-delete-fsA')).toBeInTheDocument();
  });
});
