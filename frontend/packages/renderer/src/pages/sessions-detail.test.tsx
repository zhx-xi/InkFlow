/**
 * #1015 会话详情弹层 RED 契约（spec specs/f19-gui/sessions.md §6.1/§6.3 N11-N13/N16）
 *
 * ⚠️ 本文件 = 契约。GREEN 必须匹配：
 * - 访谈卡标题 session-title-<planner.id>、执行卡标题 session-title-<session.id>
 *   由裸 <span> 改 <button>（testid 不变），点击 → 统一只读详情弹层。
 * - 弹层组件 src/components/SessionDetailDialog.tsx：
 *   session-detail-dialog（role=dialog aria-modal）/ session-detail-title /
 *   session-detail-close（关闭）/ session-detail-loading / session-detail-error。
 * - variant=pl（访谈）：懒加载 GET /api/v1/agent/books/planner/{id}
 *   （api/books.ts getPlannerSession）→ 问答对 session-detail-qa-<q.id>
 *   （问题文本 + 答案文本，未答占位）+ 确认项 session-detail-confirmed-<key>
 *   （value + source）+ 计划行 session-detail-writing-plan（writing_plan_id 非空，
 *   含 plan id 文本；GUI 无独立 plan 页，v1 不做导航，§6.4 裁定）。
 * - variant=ex（执行）：api/sessions.ts 新增 fetchSessionLogs(sessionId, params?)
 *   → GET /api/v1/sessions/{id}/logs（懒加载）→ 日志时间线 session-detail-log-<seq>
 *   （message 文本）+ 元信息 session-detail-meta-status（status 原值）。
 *   ⚠️ 数据源裁定：issue 建议 GET /agent/runs/{id} 系错误假设（F24/F27 两表无关联），
 *   详情 = sessions 详情 + logs 端点（spec §6.4）。
 * - 归档执行卡（is_deleted=true）：弹层底部 session-detail-restore（恢复入口）→
 *   调 restoreSession + ok toast；活动卡无该按钮（守护）。
 * - 加载失败（reject）→ session-detail-error 文案，弹层不崩溃（可关闭）。
 * - AI 对话卡标题行为不回归：点击仍导航（/writing），不弹详情弹层（守护用例）。
 *
 * Mock 依赖：../api/sessions（含新导出 fetchSessionLogs）+ ../api/books
 * （getPlannerSession）+ ../api/client（apiFetch：/projects、/chat/conversations）。
 * store 播种镜像 sessions.test.tsx。
 *
 * RED 预期：当前 sessions.tsx 访谈/执行标题为裸 span（无 onClick）→ 点击后无
 * session-detail-dialog → 契约用例在标题点击或 findByTestId FAIL；守护用例 PASS。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { SessionsPage } from './sessions';
import {
  fetchPlannerSessions,
  fetchSessionLogs,
  fetchSessions,
  restoreSession,
} from '../api/sessions';
import { getPlannerSession } from '../api/books';
import { getRun as _getRun } from '../api/runs';
import { apiFetch } from '../api/client';
import { useThemeStore } from '../stores/theme';
import { useProjectStore, type Project } from '../stores/project';
import { useChapterStore, type ChapterMeta } from '../stores/chapter';
import { useToastStore } from '../stores/toast';

vi.mock('../api/sessions', () => ({
  fetchSessions: vi.fn(),
  fetchPlannerSessions: vi.fn(),
  archiveSession: vi.fn(),
  deleteSession: vi.fn(),
  restoreSession: vi.fn(),
  // #1015：履历日志懒加载（wire 契约见 api/sessions.test.ts）
  fetchSessionLogs: vi.fn(),
}));
vi.mock('../api/books', () => ({
  getPlannerSession: vi.fn(),
}));
// #1029：run 轨迹懒加载（ADR-056 软锚 → getRun）
vi.mock('../api/runs', () => ({
  getRun: vi.fn(),
}));
vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const fetchSessionsMock = vi.mocked(fetchSessions);
const fetchPlannerSessionsMock = vi.mocked(fetchPlannerSessions);
const restoreSessionMock = vi.mocked(restoreSession);
const fetchSessionLogsMock = vi.mocked(fetchSessionLogs);
const getPlannerSessionMock = vi.mocked(getPlannerSession);
const getRunMock = vi.mocked(_getRun);
const apiFetchMock = vi.mocked(apiFetch);

import type { PlannerSessionDto, SessionDto, SessionViewDto } from '../api/sessions';
import type { AgentRunDto } from '../api/runs';

interface ChatConversationDto {
  conversation_id: string;
  project_id: string;
  project_name: string | null;
  title: string;
  last_message: string;
  message_count: number;
  is_deleted: boolean;
  updated_at: string;
}

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

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname}{location.search}</div>;
}

function renderSessionsPage() {
  return render(
    <MemoryRouter initialEntries={['/sessions']}>
      <SessionsPage />
      <Routes>
        <Route path="/writing" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

const conversations: ChatConversationDto[] = [
  {
    conversation_id: 'conv-1',
    project_id: 'p1',
    project_name: '仙侠长篇',
    title: '打斗场景',
    last_message: '帮我写一段打斗场景',
    message_count: 3,
    is_deleted: false,
    updated_at: '2026-08-21T10:00:00Z',
  },
];

beforeEach(() => {
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: makeProjects(), currentProjectId: 'p1', loading: false, error: null });
  useToastStore.setState({ toasts: [] });
  useChapterStore.setState({
    volumes: [],
    chapters: [] as ChapterMeta[],
    treeProjectId: null,
    currentChapterId: null,
    content: '',
    loading: false,
    error: null,
  });

  fetchSessionsMock.mockReset();
  fetchPlannerSessionsMock.mockReset();
  restoreSessionMock.mockReset();
  fetchSessionLogsMock.mockReset();
  getPlannerSessionMock.mockReset();
  getRunMock.mockReset();
  apiFetchMock.mockReset();

  fetchSessionsMock.mockResolvedValue({
    items: [
      makeSession({ id: 'ex-active-p1', project_id: 'p1', title: '第三章续写', status: 'active' }),
      makeSession({
        id: 'ex-archived-p1',
        project_id: 'p1',
        title: '第二章草稿润色',
        status: 'completed',
        is_deleted: true,
        // #1069 NIT-9：completed_at 显示点专项（'2026-08-10T09:30:00Z' → +08 17:30:00）
        completed_at: '2026-08-10T09:30:00Z',
      }),
    ],
    total: 2,
    offset: 0,
    limit: 50,
  });
  // 访谈列表：已完成 + 访谈中（drafting 也可点开，状态不限）
  const planners: PlannerSessionDto[] = [
    {
      id: 'pl-done',
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
    {
      id: 'pl-drafting',
      project_id: 'p1',
      status: 'drafting',
      one_liner: '续写访谈',
      round: 1,
      asked_questions: [],
      answers: {},
      authorized: [],
      writing_plan_id: null,
      created_at: '2026-08-10T09:00:00Z',
      updated_at: '2026-08-10T09:00:00Z',
    },
  ];
  fetchPlannerSessionsMock.mockResolvedValue({ items: planners, total: 2, offset: 0, limit: 50 });

  // 履历日志默认成功 mock（失败用例单独 mockRejectedValueOnce）
  fetchSessionLogsMock.mockResolvedValue({
    items: [
      {
        id: 'log-1',
        session_id: 'ex-active-p1',
        seq: 1,
        level: 'info',
        message: '开始生成第三章',
        payload: {},
        created_at: '2026-08-10T08:01:00Z',
      },
      {
        id: 'log-2',
        session_id: 'ex-active-p1',
        seq: 2,
        level: 'ok',
        message: '草稿已保存',
        payload: {},
        created_at: '2026-08-10T08:05:00Z',
      },
    ],
    total: 2,
    offset: 0,
    limit: 200,
  });
  // planner 详情快照（弹层懒加载结果）
  getPlannerSessionMock.mockResolvedValue({
    id: 'pl-done',
    project_id: 'p1',
    status: 'completed',
    one_liner: '仙侠长篇 80 万字',
    round: 2,
    asked_questions: [
      { id: 'q1', text: '主角出身？', template: 'origin' },
      { id: 'q2', text: '核心冲突？', template: 'conflict' },
    ],
    answers: { q1: '山村少年' },
    authorized: [],
    writing_plan_id: 'plan-9',
    created_at: '2026-08-10T08:00:00Z',
    updated_at: '2026-08-10T08:30:00Z',
    confirmed_items: [{ key: 'genre', value: '仙侠', source: 'user' }],
    conflicts: [],
    confirming: false,
  } as PlannerSessionDto);
  restoreSessionMock.mockResolvedValue({ id: 'ex-archived-p1' } as SessionDto);
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/projects') {
      return { items: makeProjects(), total: 2, offset: 0, limit: 50 };
    }
    if (path.startsWith('/api/v1/chat/conversations')) {
      return { items: conversations, total: conversations.length };
    }
    return { ok: true };
  });
});

describe('#1015 访谈卡详情弹层（N11，决策点 1 拍板 A）', () => {
  it('点击已完成访谈卡标题 → 弹层懒加载 planner 快照：问答轮次/确认项/写作计划行', async () => {
    const user = userEvent.setup();
    renderSessionsPage();
    await screen.findByTestId('session-title-pl-done');
    await user.click(screen.getByTestId('session-title-pl-done'));

    await screen.findByTestId('session-detail-dialog');
    expect(getPlannerSessionMock).toHaveBeenCalledWith('pl-done');
    // 问答对：q1 已答（问题 + 答案）
    const qa1 = await screen.findByTestId('session-detail-qa-q1');
    expect(qa1).toHaveTextContent('主角出身？');
    expect(qa1).toHaveTextContent('山村少年');
    // q2 未答 → 仍渲染问题（占位答案）
    expect(await screen.findByTestId('session-detail-qa-q2')).toHaveTextContent('核心冲突？');
    // 确认项
    expect(await screen.findByTestId('session-detail-confirmed-genre')).toHaveTextContent('仙侠');
    // 写作计划行（含 plan id 文本；不做导航，§6.4）
    expect(await screen.findByTestId('session-detail-writing-plan')).toHaveTextContent('plan-9');
  });

  it('弹层关闭：点 session-detail-close → dialog 移除，卡片仍在', async () => {
    const user = userEvent.setup();
    renderSessionsPage();
    await screen.findByTestId('session-title-pl-done');
    await user.click(screen.getByTestId('session-title-pl-done'));
    const close = await screen.findByTestId('session-detail-close');
    await user.click(close);
    await waitFor(() => {
      expect(screen.queryByTestId('session-detail-dialog')).not.toBeInTheDocument();
    });
    expect(screen.getByTestId('session-title-pl-done')).toBeInTheDocument();
  });

  it('drafting 访谈卡也可点开（状态不限：访谈中/已完成/已跳过）', async () => {
    const user = userEvent.setup();
    renderSessionsPage();
    await screen.findByTestId('session-title-pl-drafting');
    await user.click(screen.getByTestId('session-title-pl-drafting'));
    await screen.findByTestId('session-detail-dialog');
  });

  it('N16：planner 快照加载失败 → session-detail-error，不崩溃可关闭', async () => {
    getPlannerSessionMock.mockRejectedValueOnce(new Error('planner down'));
    const user = userEvent.setup();
    renderSessionsPage();
    await screen.findByTestId('session-title-pl-done');
    await user.click(screen.getByTestId('session-title-pl-done'));
    await screen.findByTestId('session-detail-error');
    await user.click(screen.getByTestId('session-detail-close'));
    await waitFor(() => {
      expect(screen.queryByTestId('session-detail-dialog')).not.toBeInTheDocument();
    });
  });
});

describe('#1015 执行会话卡详情弹层（N12/N13，数据源 = sessions 详情 + logs，spec §6.4）', () => {
  it('点击活动执行卡标题 → 弹层元信息 + 履历日志时间线（懒加载 GET /sessions/{id}/logs）', async () => {
    const user = userEvent.setup();
    renderSessionsPage();
    await screen.findByTestId('session-title-ex-active-p1');
    await user.click(screen.getByTestId('session-title-ex-active-p1'));

    await screen.findByTestId('session-detail-dialog');
    expect(fetchSessionLogsMock).toHaveBeenCalledTimes(1);
    expect(fetchSessionLogsMock.mock.calls[0][0]).toBe('ex-active-p1');
    // 元信息：状态原值
    expect(await screen.findByTestId('session-detail-meta-status')).toHaveTextContent('active');
    // #1069（ADR-055）：started_at 本地显示（'2026-08-10T08:00:00Z' → +08:00 16:00:00），原始串不直出
    expect(screen.getByText('2026-08-10 16:00:00')).toBeInTheDocument();
    expect(screen.queryByText('2026-08-10T08:00:00Z')).not.toBeInTheDocument();
    // 日志逐条（seq 锚点 + message 文本）
    expect(await screen.findByTestId('session-detail-log-1')).toHaveTextContent('开始生成第三章');
    expect(screen.getByTestId('session-detail-log-1')).toHaveTextContent('2026-08-10 16:01:00');
    expect(screen.getByTestId('session-detail-log-2')).toHaveTextContent('草稿已保存');
    expect(screen.getByTestId('session-detail-log-2')).toHaveTextContent('2026-08-10 16:05:00');
    // 活动态无恢复入口
    expect(screen.queryByTestId('session-detail-restore')).not.toBeInTheDocument();
  });

  it('点击归档执行卡标题 → 弹层只读 + session-detail-restore；点击 → restoreSession + ok toast', async () => {
    const user = userEvent.setup();
    renderSessionsPage();
    await screen.findByTestId('session-title-ex-archived-p1');
    await user.click(screen.getByTestId('session-title-ex-archived-p1'));

    const dialog = await screen.findByTestId('session-detail-dialog');
    expect(dialog).toBeInTheDocument();
    // 归档元信息 + 日志仍可看（后端 list_logs 不因归档过滤，履历保留契约）
    expect(await screen.findByTestId('session-detail-meta-status')).toHaveTextContent('completed');
    // #1069 NIT-9：completed_at 经 formatTimestamp 本地显示，原始 ISO 串不直出
    expect(screen.getByTestId('session-detail-meta-status').parentElement).toHaveTextContent(
      '2026-08-10 17:30:00',
    );
    expect(screen.getByTestId('session-detail-meta-status').parentElement?.textContent).not.toContain(
      '2026-08-10T09:30:00Z',
    );
    expect(await screen.findByTestId('session-detail-log-1')).toBeInTheDocument();
    await user.click(await screen.findByTestId('session-detail-restore'));
    await waitFor(() => {
      expect(restoreSessionMock).toHaveBeenCalledWith('ex-archived-p1');
    });
    await waitFor(() => {
      expect(useToastStore.getState().toasts.some((x) => x.type === 'ok')).toBe(true);
    });
  });

  it('N16：logs 加载失败 → session-detail-error，不崩溃可关闭', async () => {
    fetchSessionLogsMock.mockRejectedValueOnce(new Error('logs down'));
    const user = userEvent.setup();
    renderSessionsPage();
    await screen.findByTestId('session-title-ex-active-p1');
    await user.click(screen.getByTestId('session-title-ex-active-p1'));
    await screen.findByTestId('session-detail-error');
    await user.click(screen.getByTestId('session-detail-close'));
    await waitFor(() => {
      expect(screen.queryByTestId('session-detail-dialog')).not.toBeInTheDocument();
    });
  });
});

describe('#1029 执行会话详情 ↔ agentic 决策轨迹关联（ADR-056，spec §6.1/§6.3 N22-N24）', () => {
  /**
   * 契约（ADR-056 决策 A，软锚）：
   * - session.context['agent_run_id'] 非空 → 弹层追加决策轨迹区块，懒加载
   *   GET /api/v1/agent/runs/{id}（api/runs.ts getRun）：
   *   session-detail-trace-<index> 轻量行（步骤序号 + 工具名 + 结果摘要）
   *   + session-detail-trace-link「查看执行详情」跳 /writing。
   * - 无该键 = 不渲染区块、不发 run 请求（存量会话降级，维持 #1028 形态）。
   * - run 加载失败 → session-detail-trace-error 占位，其余部分不崩溃。
   */
  const RUN_ID = '9f1c7d20-1a2b-4c3d-8e4f-5a6b7c8d9e0f';

  function makeRunDto(): AgentRunDto {
    return {
      id: RUN_ID,
      project_id: 'p1',
      chapter_id: null,
      mode: 'agentic',
      status: 'completed',
      steps: [
        {
          index: 0,
          message_content: '我先看大纲',
          reasoning: '需要先读大纲确认走向',
          tokens: 12,
          tool_calls: [
            {
              step_index: 0,
              tool_name: 'read_outline',
              arguments: {},
              result: '大纲已读取',
              is_error: false,
            },
          ],
        },
        {
          index: 1,
          message_content: '写草稿',
          tool_calls: [
            {
              step_index: 1,
              tool_name: 'save_draft',
              arguments: {},
              result: '草稿已保存',
              is_error: false,
            },
          ],
          tokens: 20,
        },
      ],
      final_content: '正文',
      draft_id: null,
      model: 'glm-4',
      token_usage_total: 32,
      terminated_by: '',
      created_at: '2026-08-10T08:10:00Z',
      updated_at: '2026-08-10T08:20:00Z',
    };
  }

  it('N22：context.agent_run_id 非空 → 轨迹区块逐步骤渲染 + 跳转入口', async () => {
    fetchSessionsMock.mockResolvedValue({
      items: [
        makeSession({
          id: 'ex-anchored-p1',
          project_id: 'p1',
          title: '带锚执行',
          status: 'completed',
          context: { agent_run_id: RUN_ID },
        }),
      ],
      total: 1,
      offset: 0,
      limit: 50,
    });
    fetchSessionLogsMock.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200 });
    getRunMock.mockResolvedValue(makeRunDto());

    const user = userEvent.setup();
    renderSessionsPage();
    await screen.findByTestId('session-title-ex-anchored-p1');
    await user.click(screen.getByTestId('session-title-ex-anchored-p1'));

    await screen.findByTestId('session-detail-dialog');
    // 懒加载既有 run 端点（runId = context 锚）
    await waitFor(() => {
      expect(getRunMock).toHaveBeenCalledWith(RUN_ID);
    });
    // 逐步骤轻量行：步骤序号 + 工具名 + 结果摘要
    const trace0 = await screen.findByTestId('session-detail-trace-0');
    expect(trace0).toHaveTextContent('read_outline');
    expect(trace0).toHaveTextContent('大纲已读取');
    const trace1 = await screen.findByTestId('session-detail-trace-1');
    expect(trace1).toHaveTextContent('save_draft');
    expect(trace1).toHaveTextContent('草稿已保存');
    // 跳转执行详情入口
    const traceLink = screen.getByTestId('session-detail-trace-link');
    expect(traceLink).toBeInTheDocument();
    // N22 契约：点击跳转入口 → 导航写作页。⚠️ 断言必须含 chapter_id 才能证伪
    // 「落编辑器/无参」分支（run.chapter_id 为 null 时实现走裸 /writing，两分支都含
    // /writing → 仅断言 /writing 是恒真，见评审 finding #2）。
    expect(traceLink.tagName).toBe('BUTTON');
    await user.click(traceLink);
    await waitFor(() => {
      expect(screen.getByTestId('location-probe')).toHaveTextContent('/writing');
    });
    // 裸 chapter_id 的 run（makeRunDto chapter_id=null）→ 不拼查询参数（无 chapter_id key）
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/writing');
    expect(screen.getByTestId('location-probe').textContent).not.toContain('chapter_id');
  });

  it('N22 分支：run.chapter_id 非空 → 跳转 URL 携带 chapter_id（证伪恒真断言）', async () => {
    fetchSessionsMock.mockResolvedValue({
      items: [
        makeSession({
          id: 'ex-anchored-p1',
          project_id: 'p1',
          title: '带锚执行',
          status: 'completed',
          context: { agent_run_id: RUN_ID },
        }),
      ],
      total: 1,
      offset: 0,
      limit: 50,
    });
    fetchSessionLogsMock.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200 });
    getRunMock.mockResolvedValue({ ...makeRunDto(), chapter_id: 'ch-42' });

    const user = userEvent.setup();
    renderSessionsPage();
    await screen.findByTestId('session-title-ex-anchored-p1');
    await user.click(screen.getByTestId('session-title-ex-anchored-p1'));
    await screen.findByTestId('session-detail-dialog');
    await user.click(await screen.findByTestId('session-detail-trace-link'));

    await waitFor(() => {
      expect(screen.getByTestId('location-probe')).toHaveTextContent('/writing?chapter_id=ch-42');
    });
  });

  it('N23：存量会话（context 无 agent_run_id）→ 不渲染轨迹区块、不发 run 请求（不回归 #1028）', async () => {
    fetchSessionLogsMock.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200 });

    const user = userEvent.setup();
    renderSessionsPage();
    await screen.findByTestId('session-title-ex-active-p1');
    await user.click(screen.getByTestId('session-title-ex-active-p1'));

    await screen.findByTestId('session-detail-dialog');
    // 元信息 + 日志仍在（#1028 形态）
    expect(await screen.findByTestId('session-detail-meta-status')).toHaveTextContent('active');
    // 轨迹区块零渲染 + run 端点零请求 + 无错误提示
    expect(screen.queryByTestId('session-detail-trace-0')).not.toBeInTheDocument();
    expect(screen.queryByTestId('session-detail-trace-link')).not.toBeInTheDocument();
    expect(screen.queryByTestId('session-detail-trace-error')).not.toBeInTheDocument();
    expect(getRunMock).not.toHaveBeenCalled();
  });

  it('N24：agent_run_id 存在但 getRun 失败 → trace-error 占位，弹层其余部分不崩溃', async () => {
    fetchSessionsMock.mockResolvedValue({
      items: [
        makeSession({
          id: 'ex-anchored-p1',
          project_id: 'p1',
          title: '带锚执行',
          status: 'completed',
          context: { agent_run_id: RUN_ID },
        }),
      ],
      total: 1,
      offset: 0,
      limit: 50,
    });
    fetchSessionLogsMock.mockResolvedValue({
      items: [
        {
          id: 'log-1',
          session_id: 'ex-anchored-p1',
          seq: 1,
          level: 'info',
          message: '开始执行',
          payload: {},
          created_at: '2026-08-10T08:10:00Z',
        },
      ],
      total: 1,
      offset: 0,
      limit: 200,
    });
    getRunMock.mockRejectedValueOnce(new Error('run gone'));

    const user = userEvent.setup();
    renderSessionsPage();
    await screen.findByTestId('session-title-ex-anchored-p1');
    await user.click(screen.getByTestId('session-title-ex-anchored-p1'));

    await screen.findByTestId('session-detail-dialog');
    expect(await screen.findByTestId('session-detail-trace-error')).toBeInTheDocument();
    // 其余部分不受影响
    expect(await screen.findByTestId('session-detail-log-1')).toHaveTextContent('开始执行');
    expect(screen.queryByTestId('session-detail-error')).not.toBeInTheDocument();
  });

  it('N23 边界：context 为退化形态（null / 非对象 / 空串锚）→ 不崩溃、不渲染轨迹区块', async () => {
    fetchSessionsMock.mockResolvedValue({
      items: [
        // LenientJSON 容错路径可能给出 null / 标量（非 object）；空串锚不算锚
        makeSession({ id: 'ex-null-ctx', title: 'null 上下文', context: null as unknown as Record<string, unknown> }),
        makeSession({ id: 'ex-scalar-ctx', title: '标量上下文', context: 42 as unknown as Record<string, unknown> }),
        makeSession({ id: 'ex-empty-anchor', title: '空串锚', context: { agent_run_id: '' } }),
        makeSession({ id: 'ex-nonstr-anchor', title: '非串锚', context: { agent_run_id: 123 } }),
      ],
      total: 4,
      offset: 0,
      limit: 50,
    });
    fetchSessionLogsMock.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200 });

    const user = userEvent.setup();
    renderSessionsPage();

    for (const id of ['ex-null-ctx', 'ex-scalar-ctx', 'ex-empty-anchor', 'ex-nonstr-anchor']) {
      await screen.findByTestId(`session-title-${id}`);
      await user.click(screen.getByTestId(`session-title-${id}`));
      await screen.findByTestId('session-detail-dialog');
      // 均不得渲染轨迹区块，也不得因读取 context 崩溃
      expect(screen.queryByTestId('session-detail-trace-0')).not.toBeInTheDocument();
      expect(screen.queryByTestId('session-detail-trace-link')).not.toBeInTheDocument();
      expect(screen.queryByTestId('session-detail-trace-error')).not.toBeInTheDocument();
      await user.click(screen.getByTestId('session-detail-close'));
      await waitFor(() => {
        expect(screen.queryByTestId('session-detail-dialog')).not.toBeInTheDocument();
      });
    }
    expect(getRunMock).not.toHaveBeenCalled();
  });
});

describe('#1015 守护：AI 对话卡导航行为不回归（#770）', () => {
  it('点击 AI 对话卡标题 → 导航 /writing（不弹详情弹层）', async () => {
    const user = userEvent.setup();
    renderSessionsPage();
    await screen.findByTestId('session-title-conv-conv-1');
    await user.click(screen.getByTestId('session-title-conv-conv-1'));
    await waitFor(() => {
      expect(screen.getByTestId('location-probe')).toHaveTextContent('/writing');
    });
    expect(screen.queryByTestId('session-detail-dialog')).not.toBeInTheDocument();
  });
});
