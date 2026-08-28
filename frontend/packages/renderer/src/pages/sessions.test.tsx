/**
 * #725 会话页重构 — 统一窗口 / 按项目分区 / 检索同栏 / 归档回归 RED 契约测试
 *
 * ⚠️ 本文件 = 契约。GREEN 重构 src/pages/sessions.tsx（命名导出 SessionsPage），必须匹配：
 *
 * 布局（Q1=A 统一 / Q2 按项目分区 / 检索同栏 / Q3 归档回归）：
 * - 移除「访谈会话 / 执行会话 / AI 对话」三个独立分区（planner-section /
 *   sessions-section / chat-conversations-section 不再渲染），统一为一个
 *   data-testid="session-directory" 目录，三类会话合并展示（类型徽标区分）。
 * - 顶部项目选择器 data-testid="sessions-project-select"（镜像 library.tsx 的
 *   library-project-select；复用 useProjectStore 的 projects/currentProjectId/selectProject）。
 * - 检索框 data-testid="sessions-search"（input）与会话目录同栏，按 标题/项目名/最后消息 过滤。
 * - filter chips（全部/活动/已归档）作用于整个目录（本地过滤，不重拉）。
 * - 每张卡片 data-testid="session-directory-card"，行内：
 *   session-type-<id>（类型徽标：AI 对话 / 访谈 / 执行）、session-title-<id>、
 *   session-status-<id>（执行会话）、session-archived-<id>（仅归档态）、
 *   session-archive-<id>（仅活动态）、session-restore-<id>（仅归档态）、session-delete-<id>。
 * - 空态 sessions-empty；删除确认 dialog：session-delete-dialog/-cancel/-confirm。
 *
 * 数据流（Q2 拍板：前端拉全量 + 按 currentProjectId 前端过滤分组）：
 * - 挂载：useProjectStore.loadProjects()（apiFetch GET /api/v1/projects）+ fetchSessions({includeDeleted:true})
 *   + fetchPlannerSessions() + fetchChatConversations({includeDeleted:true})（apiFetch GET /api/v1/chat/conversations）。
 * - 目录 = 当前项目 的执行会话（project_id===currentProjectId ∪ is_deleted）+ 访谈会话 + AI 对话（project_id 匹配）
 *   合并，按 updated_at/created_at 倒序，类型徽标区分。
 * - 项目切换 → selectProject(id) → 目录切换（仅显示该项目会话）。
 *
 * 接线（Mock 依赖）：
 * - ../api/sessions：fetchSessions / fetchPlannerSessions / archiveSession / deleteSession / restoreSession
 *   （本文件 vi.mock；GREEN 若改 import 源 → mock 不生效 → 测试炸，属契约违约）
 * - ../api/client：apiFetch（chat 对话 GET/POST/DELETE + /api/v1/projects 走 apiFetch mock 分发）
 * - useProjectStore：直接 setState 播种 projects/currentProjectId（不 vi.mock，组件读真 store）
 * - useThemeStore：setState({ lang: 'zh' })
 *
 * i18n key（GREEN 补，走子词典 i18n/sessions-ux.ts 避免 zh.ts 900 护栏）：
 * - sessions.projectSelect（复用 lib.projectSelect='当前项目'）
 * - sessions.search.placeholder='搜索会话标题 / 项目 / 最后消息…'
 * - sessions.badge.ai='AI 对话' sessions.badge.interview='访谈' sessions.badge.execution='执行'
 *
 * RED 预期：当前实现为旧三区（planner-section/sessions-section/chat-conversations-section）→
 * 本文件全部 describe 的断言（session-directory / sessions-project-select / sessions-search 等）FAIL。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within, waitFor, act } from '@testing-library/react';
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
import { apiFetch } from '../api/client';
import { useThemeStore } from '../stores/theme';
import { useProjectStore, type Project } from '../stores/project';

vi.mock('../api/sessions', () => ({
  fetchSessions: vi.fn(),
  fetchPlannerSessions: vi.fn(),
  archiveSession: vi.fn(),
  deleteSession: vi.fn(),
  restoreSession: vi.fn(),
}));
// apiFetch mock：项目列表 + chat 对话（/projects、/chat/conversations）分发
vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const fetchSessionsMock = vi.mocked(fetchSessions);
const fetchPlannerSessionsMock = vi.mocked(fetchPlannerSessions);
const archiveSessionMock = vi.mocked(archiveSession);
const deleteSessionMock = vi.mocked(deleteSession);
const restoreSessionMock = vi.mocked(restoreSession);
const apiFetchMock = vi.mocked(apiFetch);
import type { PlannerSessionDto, SessionDto, SessionViewDto } from '../api/sessions';

interface ChatConversationDto {
  conversation_id: string;
  project_id: string;
  project_name: string | null;
  last_message: string;
  message_count: number;
  is_deleted: boolean;
  updated_at: string;
}

// 类型卡片统一 id（全局唯一，防执行/访谈/AI对话 id 冲突）
// 执行会话 id：ex-active-p1 / ex-archived-p1 / ex-p2
// 访谈会话 id：pl-p1
// AI 对话 id：conv-conv-1 / conv-conv-2（conversation_id，#744 多线程：同 project 可有多个）

let sessions: SessionViewDto[]; // 执行会话
let plannerItems: PlannerSessionDto[]; // 访谈会话
let conversations: ChatConversationDto[]; // AI 对话

function makeSession(overrides: Partial<SessionDto> = {}): SessionViewDto {
  const s: SessionDto = {
    id: 'ex-active-p1',
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

function makeProjects(): Project[] {
  const base = {
    tags: [] as string[],
    language: 'zh',
    target_words: 800000,
    config: {} as Project['config'],
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
  };
  return [
    { id: 'p1', name: '仙侠长篇', ...base },
    { id: 'p2', name: '另一项目', ...base },
  ];
}

function renderSessionsPage() {
  return render(
    <MemoryRouter initialEntries={['/sessions']}>
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
  // #725 按项目分区：显式设置当前项目（默认 p1）+ projects，避免跨用例 currentProjectId 残留/依赖组件的默认回退
  useProjectStore.setState({ projects: makeProjects(), currentProjectId: 'p1', loading: false, error: null });

  // 执行会话：p1 下 1 活动 + 1 归档；p2 下 1 活动
  sessions = [
    makeSession({ id: 'ex-active-p1', project_id: 'p1', title: '第三章续写', status: 'active' }),
    makeSession({
      id: 'ex-archived-p1',
      project_id: 'p1',
      title: '第二章草稿润色',
      status: 'completed',
      is_deleted: true,
    }),
    makeSession({ id: 'ex-p2', project_id: 'p2', title: '另一项目会话', status: 'paused' }),
  ];
  // 访谈会话：p1 下 1 条
  plannerItems = [
    {
      id: 'pl-p1',
      project_id: 'p1',
      status: 'completed',
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
  // AI 对话：p1 活动（仙侠长篇），p2 归档（null 项目名）
  conversations = [
    {
      conversation_id: 'conv-1',
      project_id: 'p1',
      project_name: '仙侠长篇',
      last_message: '帮我写一段打斗场景',
      message_count: 3,
      is_deleted: false,
      updated_at: '2026-08-21T10:00:00Z',
    },
    {
      conversation_id: 'conv-2',
      project_id: 'p2',
      project_name: null,
      last_message: '聊聊角色设定',
      message_count: 1,
      is_deleted: true,
      updated_at: '2026-08-20T09:00:00Z',
    },
  ];

  fetchSessionsMock.mockReset();
  fetchPlannerSessionsMock.mockReset();
  archiveSessionMock.mockReset();
  deleteSessionMock.mockReset();
  restoreSessionMock.mockReset();
  apiFetchMock.mockReset();

  fetchSessionsMock.mockResolvedValue({ items: sessions, total: sessions.length, offset: 0, limit: 50 });
  fetchPlannerSessionsMock.mockResolvedValue({
    items: plannerItems,
    total: plannerItems.length,
    offset: 0,
    limit: 50,
  });
  // 状态化操作 mock（执行会话）：改写共享数组（镜像 #478 模式，两种实现最终态一致）
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
  // apiFetch 分发：/api/v1/projects（loadProjects）+ /api/v1/chat/conversations（#547/#581 聚合）
  apiFetchMock.mockImplementation(async (path: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET';
    if (path === '/api/v1/projects' && method === 'GET') {
      return { items: makeProjects(), total: 2, offset: 0, limit: 50 };
    }
    if (path.startsWith('/api/v1/projects/') && path.endsWith('/chapters') && method === 'GET') {
      return { items: [], total: 0, offset: 0, limit: 50 };
    }
    if (path.startsWith('/api/v1/chat/conversations')) {
      if (method === 'GET') {
        return { items: conversations, total: conversations.length };
      }
      const restoreMatch = path.match(/^\/api\/v1\/chat\/conversations\/([^/]+)\/restore$/);
      if (restoreMatch) {
        // #744：恢复按 conversation_id 匹配（非 project_id）
        const conv = conversations.find((c) => c.conversation_id === restoreMatch[1]);
        return conv ? { ...conv, is_deleted: false } : { ok: true };
      }
      return { ok: true };
    }
    return { ok: true };
  });
});

describe('会话页 — 移除「访谈/执行/AI对话」独立分区（Q1=A 统一窗口）', () => {
  it('三个旧分区均不再渲染（planner-section / sessions-section / chat-conversations-section）', async () => {
    renderSessionsPage();
    await screen.findByTestId('session-directory');
    expect(screen.queryByTestId('planner-section')).not.toBeInTheDocument();
    expect(screen.queryByTestId('sessions-section')).not.toBeInTheDocument();
    expect(screen.queryByTestId('chat-conversations-section')).not.toBeInTheDocument();
  });
});

describe('会话页 — 统一窗口（AI 对话 + 访谈 + 执行 合并展示）', () => {
  it('p1 项目目录合并三类会话：数目 4（执行 2 + 访谈 1 + AI 对话 1）', async () => {
    renderSessionsPage();
    const cards = await screen.findAllByTestId('session-directory-card');
    expect(cards).toHaveLength(4);
  });

  it('卡片带类型徽标（AI 对话 / 访谈 / 执行 三态）', async () => {
    renderSessionsPage();
    await screen.findAllByTestId('session-directory-card');
    expect(screen.getByTestId('session-type-conv-conv-1')).toBeInTheDocument();
    expect(screen.getByTestId('session-type-pl-p1')).toBeInTheDocument();
    expect(screen.getByTestId('session-type-ex-active-p1')).toBeInTheDocument();
  });
});

describe('会话页 — 按项目分区（Q2，镜像 library 项目选择器 + 按 currentProjectId 过滤）', () => {
  it('挂载渲染项目选择器；默认 p1 → 目录只显示 p1 会话（p2 会话不可见）', async () => {
    renderSessionsPage();
    expect(screen.getByTestId('sessions-project-select')).toBeInTheDocument();
    await screen.findAllByTestId('session-directory-card');
    expect(screen.getByTestId('session-title-ex-active-p1')).toBeInTheDocument();
    // p2 的执行会话 / p2 的 AI 对话都不应在 p1 目录可见
    expect(screen.queryByTestId('session-title-ex-p2')).not.toBeInTheDocument();
    expect(screen.queryByTestId('session-type-conv-conv-2')).not.toBeInTheDocument();
  });

  it('切换项目（selectProject p2）→ 目录只显示 p2 会话（p1 会话不可见）', async () => {
    renderSessionsPage();
    await screen.findAllByTestId('session-directory-card');
    act(() => useProjectStore.getState().selectProject('p2'));
    const cards = await screen.findAllByTestId('session-directory-card');
    // p2：执行会话 ex-p2 + AI 对话 conv-conv-2
    expect(cards).toHaveLength(2);
    expect(screen.getByTestId('session-title-ex-p2')).toBeInTheDocument();
    expect(screen.queryByTestId('session-title-ex-active-p1')).not.toBeInTheDocument();
  });
});

describe('会话页 — 检索同栏（sessions-search 与会话目录同栏，按关键字段过滤）', () => {
  it('渲染检索框；输入标题关键词 → 目录仅显示匹配项', async () => {
    const user = userEvent.setup();
    renderSessionsPage();
    await screen.findAllByTestId('session-directory-card');
    const search = screen.getByTestId('sessions-search');
    expect(search).toBeInTheDocument();

    await user.type(search, '第三章');
    // 仅 ex-active-p1 标题含「第三章」；其余过滤
    await waitFor(() => {
      expect(screen.getByTestId('session-title-ex-active-p1')).toBeInTheDocument();
      expect(screen.queryByTestId('session-title-pl-p1')).not.toBeInTheDocument();
      expect(screen.queryByTestId('session-type-conv-conv-1')).not.toBeInTheDocument();
    });
  });
});

describe('会话页 — 归档回归（Q3：归档两个会话，刷新后两个都显示）', () => {
  it('Q3 归档回归：p1 两个执行会话均归档 → 统一目录完整合并三类（4 张），两个归档执行都显示 + 访谈/AI 对话不因归档隐藏', async () => {
    // 覆盖两个执行会话为已归档（都在 p1）
    sessions = [
      makeSession({
        id: 'ex-archived-p1',
        project_id: 'p1',
        title: '第二章草稿润色',
        status: 'completed',
        is_deleted: true,
      }),
      makeSession({
        id: 'ex-archived-p1b',
        project_id: 'p1',
        title: '第一章初稿重写',
        status: 'completed',
        is_deleted: true,
      }),
    ];
    fetchSessionsMock.mockResolvedValue({ items: sessions, total: sessions.length, offset: 0, limit: 50 });
    renderSessionsPage();
    const cards = await screen.findAllByTestId('session-directory-card');
    // 无条件合并：2 归档执行 + 1 访谈 + 1 AI 对话 = 4 张（统一窗口不因执行会话归档隐藏访谈/对话）
    expect(cards).toHaveLength(4);
    // Q3 回归核心：两个归档执行会话都显示（带归档徽标），不丢任何一条
    expect(screen.getByTestId('session-archived-ex-archived-p1')).toBeInTheDocument();
    expect(screen.getByTestId('session-archived-ex-archived-p1b')).toBeInTheDocument();
    // 统一窗口：访谈 / AI 对话卡仍显示（不因执行会话归档而隐藏）
    expect(screen.getByTestId('session-title-pl-p1')).toBeInTheDocument();
    expect(screen.getByTestId('session-title-conv-conv-1')).toBeInTheDocument();
    // 归档 filter 下：仅显示两个归档执行（访谈/对话被 is_deleted 过滤）
    const user = userEvent.setup();
    await user.click(screen.getByTestId('sessions-filter-archived'));
    await waitFor(() => {
      expect(screen.getByTestId('session-title-ex-archived-p1')).toBeInTheDocument();
      expect(screen.getByTestId('session-title-ex-archived-p1b')).toBeInTheDocument();
      expect(screen.queryByTestId('session-title-pl-p1')).not.toBeInTheDocument();
      expect(screen.queryByTestId('session-title-conv-conv-1')).not.toBeInTheDocument();
    });
  });
});

describe('会话页 — filter chips 作用于整个目录（本地过滤，不重拉）', () => {
  it('默认全部显示；切「已归档」只显示归档卡；切「活动」只显示活动卡', async () => {
    const user = userEvent.setup();
    renderSessionsPage();
    await screen.findAllByTestId('session-directory-card');

    await user.click(screen.getByTestId('sessions-filter-archived'));
    // p1 归档：ex-archived-p1（执行会话）
    expect(screen.getByTestId('session-title-ex-archived-p1')).toBeInTheDocument();
    expect(screen.queryByTestId('session-title-ex-active-p1')).not.toBeInTheDocument();

    await user.click(screen.getByTestId('sessions-filter-active'));
    expect(screen.getByTestId('session-title-ex-active-p1')).toBeInTheDocument();
    expect(screen.queryByTestId('session-title-ex-archived-p1')).not.toBeInTheDocument();

    // 本地过滤：fetchSessions 仍只被调用 1 次（无重拉）
    expect(fetchSessionsMock).toHaveBeenCalledTimes(1);
  });
});

describe('会话页 — 归档 / 恢复 / 删除（执行会话）', () => {
  it('归档：点 session-archive-ex-active-p1 → archiveSession(id) → 行转归档（徽标 + 恢复按钮）', async () => {
    const user = userEvent.setup();
    renderSessionsPage();
    await screen.findByTestId('session-title-ex-active-p1');

    await user.click(screen.getByTestId('session-archive-ex-active-p1'));
    expect(archiveSessionMock).toHaveBeenCalledWith('ex-active-p1');
    await waitFor(() => {
      expect(screen.getByTestId('session-archived-ex-active-p1')).toBeInTheDocument();
      expect(screen.getByTestId('session-restore-ex-active-p1')).toBeInTheDocument();
      expect(screen.queryByTestId('session-archive-ex-active-p1')).not.toBeInTheDocument();
    });
  });

  it('恢复：归档行点 session-restore-ex-archived-p1 → restoreSession(id) → 徽标消失、归档按钮出现', async () => {
    const user = userEvent.setup();
    renderSessionsPage();
    await screen.findByTestId('session-title-ex-archived-p1');

    await user.click(screen.getByTestId('session-restore-ex-archived-p1'));
    expect(restoreSessionMock).toHaveBeenCalledWith('ex-archived-p1');
    await waitFor(() => {
      expect(screen.queryByTestId('session-archived-ex-archived-p1')).not.toBeInTheDocument();
      expect(screen.getByTestId('session-archive-ex-archived-p1')).toBeInTheDocument();
    });
  });

  it('删除：取消二次确认不删；确认后 deleteSession(id) → 行消失', async () => {
    const user = userEvent.setup();
    renderSessionsPage();
    await screen.findByTestId('session-title-ex-active-p1');

    await user.click(screen.getByTestId('session-delete-ex-active-p1'));
    const dialog = await screen.findByTestId('session-delete-dialog');
    await user.click(within(dialog).getByTestId('session-delete-cancel'));
    expect(deleteSessionMock).not.toHaveBeenCalled();
    expect(screen.getByTestId('session-title-ex-active-p1')).toBeInTheDocument();

    await user.click(screen.getByTestId('session-delete-ex-active-p1'));
    const dialog2 = await screen.findByTestId('session-delete-dialog');
    await user.click(within(dialog2).getByTestId('session-delete-confirm'));
    expect(deleteSessionMock).toHaveBeenCalledWith('ex-active-p1');
    await waitFor(() => {
      expect(screen.queryByTestId('session-title-ex-active-p1')).not.toBeInTheDocument();
    });
  });
});

describe('会话页 — AI 对话卡（统一目录内，含归档/恢复/删除）', () => {
  it('p1 AI 对话卡显示 project_name/最后消息/条数；活动态渲染归档+删除按钮', async () => {
    renderSessionsPage();
    await screen.findAllByTestId('session-directory-card');
    const p1Card = screen.getByTestId('session-title-conv-conv-1').closest('[data-testid="session-directory-card"]');
    expect(p1Card).toBeTruthy();
    expect(within(p1Card as HTMLElement).getByText('帮我写一段打斗场景')).toBeInTheDocument();
    expect(within(p1Card as HTMLElement).getByText('3 条')).toBeInTheDocument();
    expect(screen.getByTestId('chat-conv-archive-conv-1')).toBeInTheDocument();
    expect(screen.getByTestId('chat-conv-delete-conv-1')).toBeInTheDocument();
  });

  it('归档 AI 对话：点 chat-conv-archive-conv-1 → DELETE conversations/conv-1 + 转归档态（徽标+恢复按钮）', async () => {
    const user = userEvent.setup();
    renderSessionsPage();
    await screen.findAllByTestId('session-directory-card');

    await user.click(screen.getByTestId('chat-conv-archive-conv-1'));
    const delCall = apiFetchMock.mock.calls.find(
      ([p, init]) => p === '/api/v1/chat/conversations/conv-1' && (init as RequestInit)?.method === 'DELETE',
    );
    expect(delCall).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByTestId('chat-conv-archived-conv-1')).toBeInTheDocument();
      expect(screen.getByTestId('chat-conv-restore-conv-1')).toBeInTheDocument();
    });
  });

  it('#744 核心：同一 project 两个 conversation 线程都显示、message_count 各自正确（conversation_id 区分，非 project_id 单例聚合）', async () => {
    // 覆盖：p1 下两条独立线程（#744 后端按 conversation 聚合）
    conversations = [
      {
        conversation_id: 'conv-a',
        project_id: 'p1',
        project_name: '仙侠长篇',
        last_message: '帮我写一段打斗场景',
        message_count: 3,
        is_deleted: false,
        updated_at: '2026-08-21T10:00:00Z',
      },
      {
        conversation_id: 'conv-b',
        project_id: 'p1',
        project_name: '仙侠长篇',
        last_message: '聊聊角色设定',
        message_count: 5,
        is_deleted: false,
        updated_at: '2026-08-22T10:00:00Z',
      },
    ];
    renderSessionsPage();
    await screen.findAllByTestId('session-directory-card');
    // RED：当前 src 按 project_id 单例聚合 → conv 卡 testid 为 session-title-conv-p1（无 conv-a/conv-b）→ FAIL
    expect(screen.getByTestId('session-title-conv-conv-a')).toBeInTheDocument();
    expect(screen.getByTestId('session-title-conv-conv-b')).toBeInTheDocument();
    // 条数各自正确（卡按 conversation_id 区分）
    const cardA = screen.getByTestId('session-title-conv-conv-a').closest('[data-testid="session-directory-card"]');
    const cardB = screen.getByTestId('session-title-conv-conv-b').closest('[data-testid="session-directory-card"]');
    expect(cardA).toBeTruthy();
    expect(cardB).toBeTruthy();
    expect(within(cardA as HTMLElement).getByText('3 条')).toBeInTheDocument();
    expect(within(cardB as HTMLElement).getByText('5 条')).toBeInTheDocument();
  });
});
