/**
 * #486 会话/记忆 UI — 会话页（访谈会话 + 执行会话：归档/恢复/删除）RED 阶段契约测试
 *
 * ⚠️ 本文件 = 契约。GREEN 新建 src/pages/sessions.tsx（命名导出 SessionsPage），必须匹配：
 *
 * 接线（Mock 依赖）：
 * - SessionsPage 必须 import 自 '../api/sessions'：fetchPlannerSessions /
 *   fetchSessions / archiveSession / deleteSession / restoreSession
 *   （本文件 vi.mock 该模块；GREEN 若改 import 源 → mock 不生效 → 测试炸，属契约违约）
 * - 挂载即并行加载：fetchPlannerSessions() + fetchSessions({ includeDeleted: true })
 *   （会话页展示全部会话含归档——一次拉取，chips 切换为前端本地过滤，不重拉）
 * - 操作 wire：
 *   归档（活动行）→ archiveSession(id)
 *   恢复（归档行）→ restoreSession(id)
 *   删除（两态行皆可）→ 二次确认 Dialog → deleteSession(id)
 * - 操作后列表行状态跟随变化（实现可重拉或本地更新——测试用状态化 mock 数组
 *   保证两种实现最终态一致，见 #478 模式；archive/restore/delete 的 mock
 *   implementation 同步改写共享数组，fetch* 读同一数组）
 *
 * data-testid 即契约：
 * - sessions-page 根容器
 * - 访谈会话区块：planner-section；planner-card（卡片）；行内：
 *   planner-status-<id>（status 文案）、planner-one-liner-<id>、
 *   planner-confirmed-<id>（「已确定 N 项」类文案）、planner-writing-plan-<id>
 *   （writing_plan_id 非空时渲染）；空态 planner-empty；加载中 planner-loading；
 *   前往书页按钮 planner-go-book（t('sessions.planner.goBook')）→ 跳 /book
 * - 执行会话区块：sessions-section；筛选 chips（aria-pressed）：
 *   sessions-filter-all / sessions-filter-active / sessions-filter-archived
 *   （「全部/活动/已归档」，纯前端本地过滤，切换不触发重拉）
 *   行：session-card；行内 session-title-<id>（title 文案）、session-status-<id>、
 *   session-type-<id>、session-archived-<id>（仅 is_deleted=true 时渲染）、
 *   操作按钮：session-archive-<id>（仅活动行）、session-restore-<id>（仅归档行）、
 *   session-delete-<id>（两态行皆渲染）
 *   删除确认 Dialog：session-delete-dialog + session-delete-cancel +
 *   session-delete-confirm；空态 sessions-empty
 *
 * i18n key（GREEN 补 zh.ts/en.ts）：
 * sessions.title='会话' sessions.planner.title='访谈会话'
 * sessions.planner.empty='暂无访谈会话' sessions.planner.goBook='前往书页访谈'
 * sessions.planner.status.drafting='访谈中' sessions.planner.status.completed='已完成'
 * sessions.planner.status.declined='已跳过'
 * sessions.planner.confirmed='已确定 {n} 项' sessions.planner.writingPlan='已生成写作计划'
 * sessions.runs.title='执行会话' sessions.filter.all='全部' sessions.filter.active='活动'
 * sessions.filter.archived='已归档' sessions.status.active='进行中' sessions.status.paused='已暂停'
 * sessions.status.completed='已完成' sessions.status.failed='失败'
 * sessions.type.writing='写作' sessions.type.task='任务'
 * sessions.archived='已归档' sessions.archive='归档' sessions.restore='恢复'
 * sessions.delete='删除' sessions.delete.dialog.title='删除会话？'
 * sessions.delete.dialog.desc='此操作将永久删除会话，不可恢复。'
 * sessions.delete.confirm='确定删除' sessions.delete.cancel='取消' sessions.empty='暂无会话'
 * sessions.archivedToast='已归档' sessions.restoredToast='已恢复' sessions.deletedToast='已删除'
 *
 * RED 预期：./sessions 模块不存在 → 收集期 module-not-found（类 1 契约缺口）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { SessionsPage } from './sessions';
import {
  archiveSession,
  deleteSession,
  fetchPlannerSessions,
  fetchSessions,
  restoreSession,
} from '../api/sessions';
import { useThemeStore } from '../stores/theme';

vi.mock('../api/sessions', () => ({
  fetchSessions: vi.fn(),
  fetchPlannerSessions: vi.fn(),
  archiveSession: vi.fn(),
  deleteSession: vi.fn(),
  restoreSession: vi.fn(),
}));

const fetchSessionsMock = vi.mocked(fetchSessions);
const fetchPlannerSessionsMock = vi.mocked(fetchPlannerSessions);
const archiveSessionMock = vi.mocked(archiveSession);
const deleteSessionMock = vi.mocked(deleteSession);
const restoreSessionMock = vi.mocked(restoreSession);
import type { PlannerSessionDto, SessionDto, SessionViewDto } from '../api/sessions';

/** 状态化会话数组（fetch* 读同一数组；archive/restore/delete 改写同一数组） */
let sessions: SessionViewDto[];
let plannerItems: PlannerSessionDto[];

function makeSession(overrides: Partial<SessionDto> = {}): SessionViewDto {
  const s: SessionDto = {
    id: 's1',
    session_type: 'writing',
    status: 'active',
    project_id: 'p1',
    title: '第三章续写',
    description: '',
    context: {},
    result: {},
    error: '',
    started_at: '2026-08-10T08:00:00Z',
    paused_at: null,
    completed_at: null,
    is_deleted: false,
    created_at: '2026-08-10T08:00:00Z',
    updated_at: '2026-08-10T08:00:00Z',
    ...overrides,
  };
  return { session: s, log_count: 0, last_log: null };
}

function renderSessionsPage(initialPath = '/sessions') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <SessionsPage />
      <Routes>
        <Route path="/book" element={<div data-testid="book-probe" />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });

  sessions = [
    makeSession({ id: 's-active', title: '活跃写作' }),
    makeSession({ id: 's-archived', title: '已归档写作', status: 'completed', is_deleted: true }),
  ];
  plannerItems = [
    {
      id: 'pl-1',
      project_id: 'p1',
      status: 'drafting',
      one_liner: '仙侠长篇 80 万字',
      round: 2,
      asked_questions: [],
      answers: {},
      authorized: [],
      confirmed_items: [],
      conflicts: [],
      confirming: false,
      writing_plan_id: null,
      created_at: '2026-08-10T08:00:00Z',
      updated_at: '2026-08-10T08:00:00Z',
    },
  ];

  fetchSessionsMock.mockReset();
  fetchPlannerSessionsMock.mockReset();
  archiveSessionMock.mockReset();
  deleteSessionMock.mockReset();
  restoreSessionMock.mockReset();

  fetchSessionsMock.mockResolvedValue({ items: sessions, total: sessions.length, offset: 0, limit: 50 });
  fetchPlannerSessionsMock.mockResolvedValue({
    items: plannerItems,
    total: plannerItems.length,
    offset: 0,
    limit: 50,
  });
  // 状态化操作 mock：改写共享数组（页面重拉或本地更新两种实现最终态一致）
  archiveSessionMock.mockImplementation(async (id: string) => {
    const view = sessions.find((v) => v.session.id === id);
    if (view) view.session.is_deleted = true;
  });
  restoreSessionMock.mockImplementation(async (id: string): Promise<SessionDto> => {
    const view = sessions.find((v) => v.session.id === id);
    if (!view) return makeSession({ id }).session;
    view.session.is_deleted = false;
    return view.session;
  });
  deleteSessionMock.mockImplementation(async (id: string) => {
    sessions = sessions.filter((v) => v.session.id !== id);
  });
});

describe('会话页 — 访谈会话区块', () => {
  it('挂载渲染访谈卡片：one_liner / status 文案 / confirmed 数', async () => {
    plannerItems[0].confirmed_items = [
      { key: 'genre', value: '仙侠', source: 'user' },
      { key: 'length', value: '80万字', source: 'user' },
    ];
    renderSessionsPage();
    expect(await screen.findByTestId('planner-card')).toBeInTheDocument();
    expect(screen.getByTestId('planner-one-liner-pl-1')).toHaveTextContent('仙侠长篇 80 万字');
    expect(screen.getByTestId('planner-status-pl-1')).toHaveTextContent('访谈中');
    expect(screen.getByTestId('planner-confirmed-pl-1')).toHaveTextContent('2');
  });

  it('writing_plan_id 非空 → 已生成计划徽标渲染', async () => {
    plannerItems[0].writing_plan_id = 'wp-1';
    renderSessionsPage();
    expect(await screen.findByTestId('planner-writing-plan-pl-1')).toBeInTheDocument();
  });

  it('访谈会话空态：planner-empty + 前往书页按钮跳 /book', async () => {
    plannerItems.length = 0;
    const user = userEvent.setup();
    renderSessionsPage();
    expect(await screen.findByTestId('planner-empty')).toBeInTheDocument();
    await user.click(screen.getByTestId('planner-go-book'));
    expect(screen.getByTestId('book-probe')).toBeInTheDocument();
  });
});

describe('会话页 — 执行会话列表与筛选', () => {
  it('挂载加载含归档全量：活动行 + 归档行（归档徽标）', async () => {
    renderSessionsPage();
    expect(await screen.findByTestId('session-title-s-active')).toBeInTheDocument();
    expect(fetchSessionsMock).toHaveBeenCalledWith({ includeDeleted: true });

    expect(screen.getByTestId('session-status-s-active')).toHaveTextContent('进行中');
    expect(screen.getByTestId('session-archived-s-archived')).toBeInTheDocument();
  });

  it('筛选 chips：默认全部；切「活动」只显示活动行；切「已归档」只显示归档行（本地过滤，不重拉）', async () => {
    const user = userEvent.setup();
    renderSessionsPage();
    await screen.findByTestId('session-title-s-active');

    await user.click(screen.getByTestId('sessions-filter-active'));
    expect(screen.getByTestId('sessions-filter-active')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('session-title-s-active')).toBeInTheDocument();
    expect(screen.queryByTestId('session-title-s-archived')).not.toBeInTheDocument();

    await user.click(screen.getByTestId('sessions-filter-archived'));
    expect(screen.queryByTestId('session-title-s-active')).not.toBeInTheDocument();
    expect(screen.getByTestId('session-title-s-archived')).toBeInTheDocument();

    // 本地过滤语义：无重拉（fetchSessions 仍只 1 次）
    expect(fetchSessionsMock).toHaveBeenCalledTimes(1);
  });

  it('空态：无会话 → sessions-empty', async () => {
    sessions.length = 0;
    renderSessionsPage();
    expect(await screen.findByTestId('sessions-empty')).toBeInTheDocument();
  });
});

describe('会话页 — 归档 / 恢复 / 删除', () => {
  it('归档：点 session-archive-s-active → archiveSession(id) → 行转归档（徽标 + 恢复按钮）', async () => {
    const user = userEvent.setup();
    renderSessionsPage();
    await screen.findByTestId('session-title-s-active');

    await user.click(screen.getByTestId('session-archive-s-active'));
    expect(archiveSessionMock).toHaveBeenCalledWith('s-active');
    await waitFor(() => {
      expect(screen.getByTestId('session-archived-s-active')).toBeInTheDocument();
      expect(screen.getByTestId('session-restore-s-active')).toBeInTheDocument();
      expect(screen.queryByTestId('session-archive-s-active')).not.toBeInTheDocument();
    });
  });

  it('恢复：归档行点 session-restore-s-archived → restoreSession(id) → 徽标消失、归档按钮出现', async () => {
    const user = userEvent.setup();
    renderSessionsPage();
    await screen.findByTestId('session-title-s-archived');

    await user.click(screen.getByTestId('session-restore-s-archived'));
    expect(restoreSessionMock).toHaveBeenCalledWith('s-archived');
    await waitFor(() => {
      expect(screen.queryByTestId('session-archived-s-archived')).not.toBeInTheDocument();
      expect(screen.getByTestId('session-archive-s-archived')).toBeInTheDocument();
    });
  });

  it('删除：取消二次确认不删；确认后 deleteSession(id) → 行消失', async () => {
    const user = userEvent.setup();
    renderSessionsPage();
    await screen.findByTestId('session-title-s-active');

    await user.click(screen.getByTestId('session-delete-s-active'));
    const dialog = await screen.findByTestId('session-delete-dialog');
    await user.click(within(dialog).getByTestId('session-delete-cancel'));
    expect(deleteSessionMock).not.toHaveBeenCalled();
    expect(screen.getByTestId('session-title-s-active')).toBeInTheDocument();

    await user.click(screen.getByTestId('session-delete-s-active'));
    const dialog2 = await screen.findByTestId('session-delete-dialog');
    await user.click(within(dialog2).getByTestId('session-delete-confirm'));
    expect(deleteSessionMock).toHaveBeenCalledWith('s-active');
    await waitFor(() => {
      expect(screen.queryByTestId('session-title-s-active')).not.toBeInTheDocument();
    });
  });
});