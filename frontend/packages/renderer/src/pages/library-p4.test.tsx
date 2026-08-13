/**
 * F43 P4（specs/f43-setting-library-crud/spec.md v1.3 §5.16/§5.17/§6 P3+P4 表/§9.6 T1-T8）：
 * 设定库时间线 tab——时间线双序切换（叙事序/世界序）+ 两级检查（工具栏整体检查 + 事件行内单事件检查）。
 *
 * ⚠️ 本批契约拆分至独立文件 library-p4.test.tsx（对齐 library-p1.test.tsx / library-p2.test.tsx 先例：
 * library.test.tsx 超 900 行护栏，兄弟文件拆分；自带全套基础设施）。
 *
 * ==================== GREEN 契约（library.tsx 时间线 tab + 新组件 TimelineView + i18n zh/en §6 P3+P4 表） ====================
 *
 * 【前端数据获取改造（§5.16 必做）】
 * timeline 分类从「仅取 event_timeline」改为「取完整 TimelineView」：
 * GET /api/v1/projects/{pid}/timeline → TimelineView {project_id, total,
 *   event_timeline:[...], narrative_order:[...]}——事件字段 {id,title,description,
 *   time_value,time_unit,time_display,narrative_position,timeline_flag}。
 * 两个数组即后端排序结果（世界序 event_timeline：time_value 升序、None 排末尾；
 * 叙事序 narrative_order：narrative_position 升序）；双序切换仅本地切换显示数组，
 * 零额外请求（T2/T3 断言 timeline GET 次数不变）。mock 必须返回完整双视图，
 * 只返回 event_timeline 则叙事序无数据。
 *
 * 【testid 清单】
 * 工具栏：timeline-toolbar（时间线 tab 工具栏容器，含双序 chips + 整体检查按钮 + 图例）
 * 双序 chips：tl-view-narrative（叙事序，默认激活 aria-pressed=true）/
 *   tl-view-world（世界序，aria-pressed=false）
 * 整体检查按钮：tl-check-all（点击 → GET /projects/{pid}/timeline/check → 结果 toast）
 * 行内单事件检查按钮：tl-check-one-<id>（每个事件行渲染一个，<id> = 事件 id，
 *   如 tl-check-one-evA；行序断言以这些按钮的 DOM 顺序为准）
 * 图例：tl-legend（文本「点=叙事顺序 · 时间轴=世界内时间」，lib.tlLegend）
 *
 * 【端点 + 响应形状】
 * GET /api/v1/projects/{pid}/timeline/check
 *   → {checked, skipped, consistent, conflicts:[{conflict_type,prev,next,message}],
 *      flashbacks:[...]}
 *   consistent=true → toast「未发现矛盾事件」（lib.tlCheckOK）；
 *   consistent=false → toast「发现 {n} 处时间矛盾」（lib.tlCheckWarn，n = conflicts.length）
 * GET /api/v1/timeline/events/{id}/check
 *   → {event_id, checked, consistent, conflicts, flashbacks}
 *   checked=false → toast「该事件无时间信息，跳过检查」（lib.tlCheckSkip）；
 *   consistent=true → toast「与上下文一致」（lib.tlCheckEventOK）；
 *   否则 → toast 显示第一条 conflict.message（原文）
 *
 * 【i18n key（zh/en §6 P3+P4 表，GREEN 补）】
 * lib.tlView.narrative（叙事序）/ lib.tlView.world（世界序）/ lib.tlCheck（一致性检查）/
 *   lib.tlCheckOne（单事件检查）/ lib.tlLegend（图例文案）/
 *   lib.tlCheckOK（未发现矛盾事件）/ lib.tlCheckWarn（发现 {n} 处时间矛盾）/
 *   lib.tlCheckSkip（该事件无时间信息，跳过检查）/ lib.tlCheckEventOK（与上下文一致）
 *
 * 【交互契约（GREEN 必守）】
 * - 双序 chips 为可点击元素（button 风格），激活态 aria-pressed=true；默认激活叙事序
 *   （T1：tl-view-narrative aria-pressed=true 且列表 = narrative_order）
 * - 点 tl-view-world → 列表 = event_timeline（time_value 升序、None 末尾），
 *   激活态迁移 + 零额外请求（T2）
 * - 点 tl-view-narrative → 列表 = narrative_order（narrative_position 升序）（T3）
 * - 点 tl-check-all → GET /timeline/check → 结果 toast（T4/T5）
 * - 点 tl-check-one-<id> → GET /timeline/events/<id>/check → 结果 toast（T6/T7/T8）
 *
 * RED 预期：以上 testid 全部不存在（P4 时间线双序/两级检查未实现，时间线 tab 仍为
 * 单序列表）→ element-missing 断言 FAIL（类 3 契约缺口）；零 SyntaxError /
 * ReferenceError / TypeError / Transform failed。T1-T8 共 8 it。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
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
  id: 'p1', name: '青云志', genre: '玄幻', language: 'zh-CN', target_words: 800000, config: {},
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};
const projectP2 = {
  id: 'p2', name: '归墟记', genre: '仙侠', language: 'zh-CN', target_words: 500000, config: {},
  created_at: '2026-08-02T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};

/**
 * P4 seed 事件（§2.9 timeline 事件字段）。可区分双序：
 * - 世界序（time_value 升序、None 末尾）：evC(100) → evA(300) → evB(None)
 * - 叙事序（narrative_position 升序）：evB(1) → evC(2) → evA(3)
 * 两个序列完全不同 → 双序切换是否生效可被严格区分。
 */
const evA: Record<string, unknown> = {
  id: 'evA', title: '甲 登基', description: '', time_value: 300, time_unit: 'year',
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

/** 完整 TimelineView（§5.16：双数组即后端排序结果；前端仅本地切换显示数组） */
const timelineView: Record<string, unknown> = {
  project_id: 'p1',
  total: 3,
  event_timeline: [evC, evA, evB],  // 世界序：time_value 升序，None 排末尾
  narrative_order: [evB, evC, evA], // 叙事序：narrative_position 升序
};

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname}{location.search}</div>;
}

function renderLibrary(initialPath = '/library') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <LibraryPage />
      <Routes>
        <Route path="/projects" element={<LocationProbe />} />
        <Route path="/writing" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  useToastStore.setState({ toasts: [] }); // 防跨用例 toast 残留误判
  // 默认兜底 URL 分发：projects 双项目；timeline 完整双视图（空数组）；check 端点默认 consistent；其余空列表
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/projects') return { items: [projectP1, projectP2], total: 2, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/timeline') {
      return { project_id: 'p1', total: 0, event_timeline: [], narrative_order: [] };
    }
    if (path === '/api/v1/projects/p1/timeline/check') {
      return { checked: 0, skipped: 0, consistent: true, conflicts: [], flashbacks: [] };
    }
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

describe('设定库页 — F43 P4 时间线双序 + 两级检查（spec §5.16-5.17/§9.6 T1-T8）', () => {
  /**
   * 播种 p1 + 时间线双视图/两级检查端点 mock（用例级覆盖；seed 数组浅拷贝跨用例隔离）。
   * opts.overallCheck：整体检查响应；opts.eventChecks：按事件 id 分发的单事件检查响应。
   */
  function mockTimelineP4(
    timeline: Record<string, unknown>,
    opts: {
      overallCheck?: Record<string, unknown>;
      eventChecks?: Record<string, Record<string, unknown>>;
    } = {},
  ) {
    // 浅拷贝（跨用例 seed 不共享）
    const view: Record<string, unknown> = {
      project_id: timeline.project_id,
      total: timeline.total,
      event_timeline: (timeline.event_timeline as Array<Record<string, unknown>>).map((e) => ({ ...e })),
      narrative_order: (timeline.narrative_order as Array<Record<string, unknown>>).map((e) => ({ ...e })),
    };

    apiFetchMock.mockImplementation(async (path: string, _init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/projects') {
        return { items: [projectP1, projectP2], total: 2, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/projects/p1/timeline') {
        return view;
      }
      if (path === '/api/v1/projects/p1/timeline/check') {
        return opts.overallCheck ?? { checked: 3, skipped: 0, consistent: true, conflicts: [], flashbacks: [] };
      }
      const eventCheck = path.match(/^\/api\/v1\/timeline\/events\/([^/]+)\/check$/);
      if (eventCheck) {
        return (
          opts.eventChecks?.[eventCheck[1]]
          ?? { event_id: eventCheck[1], checked: true, consistent: true, conflicts: [], flashbacks: [] }
        );
      }
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    act(() => {
      useProjectStore.setState({ projects: [projectP1, projectP2], currentProjectId: 'p1' });
    });
  }

  /** 切到时间线 tab 并等待事件行渲染（加载骨架与真实列表共用 library-list testid，须等行数） */
  async function openTimelineTab(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole('tab', { name: '时间线' }));
    await waitFor(() =>
      expect(within(screen.getByTestId('library-list')).getAllByRole('listitem')).toHaveLength(3),
    );
  }

  /** 行序断言：各事件行内 tl-check-one-<id> 的 DOM 顺序 → 事件 id 序列（契约：每行一个检查按钮） */
  function rowIds(): string[] {
    return screen
      .getAllByTestId(/^tl-check-one-/)
      .map((el) => el.getAttribute('data-testid')!.replace('tl-check-one-', ''));
  }

  /** timeline 列表端 GET 次数（双序本地切换零请求断言基准） */
  const timelineGetCount = () =>
    apiFetchMock.mock.calls.filter((c) => c[0] === '/api/v1/projects/p1/timeline').length;

  it('T1 双序 chips 渲染 + 默认叙事序：tl-view-narrative 激活（aria-pressed=true）；tl-view-world 存在；图例渲染', async () => {
    mockTimelineP4(timelineView);
    renderLibrary();
    const user = userEvent.setup();
    await openTimelineTab(user);
    // 工具栏 + 双序 chips（GREEN：timeline-toolbar 内含 tl-view-narrative / tl-view-world）
    expect(screen.getByTestId('timeline-toolbar')).toBeInTheDocument();
    expect(screen.getByTestId('tl-view-narrative')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('tl-view-world')).toHaveAttribute('aria-pressed', 'false');
    // 图例（lib.tlLegend）
    expect(screen.getByTestId('tl-legend')).toHaveTextContent('点=叙事顺序 · 时间轴=世界内时间');
    // 默认显示叙事序数组（narrative_position 升序）
    await waitFor(() => expect(rowIds()).toEqual(['evB', 'evC', 'evA']));
  });

  it('T2 世界序切换：点 tl-view-world → 列表按 time_value 升序（None 排末尾）+ 零额外请求', async () => {
    mockTimelineP4(timelineView);
    renderLibrary();
    const user = userEvent.setup();
    await openTimelineTab(user);
    const getsBefore = timelineGetCount();
    await user.click(screen.getByTestId('tl-view-world'));
    // 世界序：evC(100) → evA(300) → evB(None 末尾)
    await waitFor(() => expect(rowIds()).toEqual(['evC', 'evA', 'evB']));
    // 激活态迁移 + 本地切换零请求（§5.16）
    expect(screen.getByTestId('tl-view-world')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('tl-view-narrative')).toHaveAttribute('aria-pressed', 'false');
    expect(timelineGetCount()).toBe(getsBefore);
  });

  it('T3 叙事序切换：世界序 → 点 tl-view-narrative → 列表按 narrative_position 升序', async () => {
    mockTimelineP4(timelineView);
    renderLibrary();
    const user = userEvent.setup();
    await openTimelineTab(user);
    // 先切世界序（确认切换生效）再切回叙事序
    await user.click(screen.getByTestId('tl-view-world'));
    await waitFor(() => expect(rowIds()).toEqual(['evC', 'evA', 'evB']));
    const getsBefore = timelineGetCount();
    await user.click(screen.getByTestId('tl-view-narrative'));
    // 叙事序：evB(1) → evC(2) → evA(3)
    await waitFor(() => expect(rowIds()).toEqual(['evB', 'evC', 'evA']));
    expect(screen.getByTestId('tl-view-narrative')).toHaveAttribute('aria-pressed', 'true');
    expect(timelineGetCount()).toBe(getsBefore);
  });

  it('T4 整体检查通过：点 tl-check-all → GET /timeline/check → consistent → toast「未发现矛盾事件」', async () => {
    mockTimelineP4(timelineView, {
      overallCheck: { checked: 3, skipped: 0, consistent: true, conflicts: [], flashbacks: [] },
    });
    renderLibrary();
    const user = userEvent.setup();
    await openTimelineTab(user);
    await user.click(screen.getByTestId('tl-check-all'));
    await waitFor(() => {
      expect(apiFetchMock.mock.calls.some((c) => c[0] === '/api/v1/projects/p1/timeline/check')).toBe(true);
      expect(useToastStore.getState().toasts.some((t) => t.message === '未发现矛盾事件')).toBe(true);
    });
  });

  it('T5 整体检查发现冲突：check 返回 conflicts 非空 → toast「发现 {n} 处时间矛盾」', async () => {
    const conflicts = [
      { conflict_type: 'order_conflict', prev: '丙 初现', next: '甲 登基', message: '甲 登基 应晚于 丙 初现' },
      { conflict_type: 'order_conflict', prev: '甲 登基', next: '乙 失踪', message: '乙 失踪 应晚于 甲 登基' },
    ];
    mockTimelineP4(timelineView, {
      overallCheck: { checked: 3, skipped: 0, consistent: false, conflicts, flashbacks: [] },
    });
    renderLibrary();
    const user = userEvent.setup();
    await openTimelineTab(user);
    await user.click(screen.getByTestId('tl-check-all'));
    await waitFor(() => {
      expect(useToastStore.getState().toasts.some((t) => t.message === '发现 2 处时间矛盾')).toBe(true);
    });
  });

  it('T6 单事件检查一致：点 tl-check-one-evA → GET /timeline/events/evA/check → toast「与上下文一致」', async () => {
    mockTimelineP4(timelineView, {
      eventChecks: { evA: { event_id: 'evA', checked: true, consistent: true, conflicts: [], flashbacks: [] } },
    });
    renderLibrary();
    const user = userEvent.setup();
    await openTimelineTab(user);
    await user.click(screen.getByTestId('tl-check-one-evA'));
    await waitFor(() => {
      expect(apiFetchMock.mock.calls.some((c) => c[0] === '/api/v1/timeline/events/evA/check')).toBe(true);
      expect(useToastStore.getState().toasts.some((t) => t.message === '与上下文一致')).toBe(true);
    });
  });

  it('T7 单事件检查冲突：check 返回冲突 → toast 显示第一条 message', async () => {
    mockTimelineP4(timelineView, {
      eventChecks: {
        evA: {
          event_id: 'evA', checked: true, consistent: false,
          conflicts: [
            { conflict_type: 'order_conflict', prev: '丙 初现', next: '甲 登基', message: '甲 登基 应晚于 丙 初现' },
            { conflict_type: 'order_conflict', prev: '甲 登基', next: '乙 失踪', message: '乙 失踪 应晚于 甲 登基' },
          ],
          flashbacks: [],
        },
      },
    });
    renderLibrary();
    const user = userEvent.setup();
    await openTimelineTab(user);
    await user.click(screen.getByTestId('tl-check-one-evA'));
    await waitFor(() => {
      expect(useToastStore.getState().toasts.some((t) => t.message === '甲 登基 应晚于 丙 初现')).toBe(true);
    });
  });

  it('T8 单事件检查跳过：check 返回 checked=false → toast「该事件无时间信息，跳过检查」', async () => {
    mockTimelineP4(timelineView, {
      eventChecks: { evB: { event_id: 'evB', checked: false, consistent: false, conflicts: [], flashbacks: [] } },
    });
    renderLibrary();
    const user = userEvent.setup();
    await openTimelineTab(user);
    await user.click(screen.getByTestId('tl-check-one-evB'));
    await waitFor(() => {
      expect(useToastStore.getState().toasts.some((t) => t.message === '该事件无时间信息，跳过检查')).toBe(true);
    });
  });
});
