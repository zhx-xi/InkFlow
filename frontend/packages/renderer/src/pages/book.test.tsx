/**
 * book 页契约测试（F44 阶段1 GUI，spec v1.1 §5.1 GUI 小节 + §8.1 pages/book.tsx）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须新建 src/pages/book.tsx 并匹配：
 *
 * export function BookPage(): JSX.Element
 *
 * 结构 testid：
 * - book-page（页面根）
 * - book-page-empty（无项目空态：文案 + 前往项目页按钮）
 * - book-project（当前项目显示）
 * - BookPlannerPanel 嵌入（book-planner-panel）
 *
 * 行为契约（主路径闭环：访谈→委托→展开行→状态，M3b 验收）：
 * - 无项目 → book-page-empty + 前往项目页按钮（navigate /projects）
 * - 有项目 → 渲染 book-planner-panel
 * - 完整闭环（mock API）：启动访谈 → 回答轮1 → 回答轮2 → completed
 *   → 显示 writingPlan → 点开始写作 → startRun → BookRunPanel 显示运行状态
 *
 * App 路由：/book（App.tsx TITLE_BY_PATH 加 '/book': 'nav.book'；AppNav 写作区
 * nav-item-book 入口 href=/book）
 *
 * i18n key（GREEN 补 zh.ts/en.ts）：nav.book / book.empty.title / book.empty.goProjects
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { BookPage } from './book';
import { apiFetch } from '../api/client';
import { useProjectStore } from '../stores/project';
import { useBookStore } from '../stores/book';
import { useThemeStore } from '../stores/theme';
import { useModelsStore, type ProviderConfig } from '../stores/models';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

/** #474：已配置模型种子 provider（key_saved=true + chat 模型），默认播种让既有主路径用例行为不变 */
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

const q1 = { id: 'q1', text: '题材：悬疑为主，还是悬疑+科幻混合？', template: '悬疑为主，但加入 ___ 元素' };
const q2 = { id: 'q2', text: '篇幅：预计多少字？', template: '约 ___ 字' };
const q3 = { id: 'q3', text: '主角：能否一句话描述主角？', template: '主角是 ___' };
const round1 = [q1, q2, q3];
const round2 = [{ id: 'q4', text: '配角：需要几个主要配角？', template: '___ 个' }];

const wp = {
  id: 'wp-1',
  project_id: 'p1',
  title: '写一本关于时间旅者的悬疑小说',
  status: 'ready',
  root_outline_id: 'o-1',
  character_ids: [],
  limits: { max_chapters: 1, max_agent_calls: 1 },
  progress: {},
  execution_refs: {},
  thread_id: null,
  created_at: '2026-08-17T10:00:00Z',
  updated_at: '2026-08-17T10:00:00Z',
};

beforeEach(() => {
  apiFetchMock.mockReset();
  // #474：默认播种已配置模型（主路径用例点 book-planner-start 需通过前置校验）
  useModelsStore.setState({ providers: [READY_PROVIDER], loading: false, error: null });
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  useBookStore.setState({
    sessionId: null,
    round: 0,
    questions: [],
    answers: {},
    authorized: [],
    sessionStatus: 'idle',
    oneLiner: '',
    writingPlan: null,
    runId: null,
    runStatus: null,
    progress: {},
    counters: null,
    loading: false,
    error: null,
  });
});

describe('book 页 — 无项目空态', () => {
  it('无项目 → book-page-empty + 前往项目页按钮', async () => {
    render(
      <MemoryRouter>
        <BookPage />
      </MemoryRouter>,
    );
    expect(screen.getByTestId('book-page')).toBeInTheDocument();
    expect(screen.getByTestId('book-page-empty')).toBeInTheDocument();
    expect(screen.getByTestId('book-page-go-projects')).toBeInTheDocument();
  });
});

describe('book 页 — 主路径闭环（访谈→委托→展开行→状态）', () => {
  it('有项目 → 渲染 book-planner-panel；完整闭环：访谈→计划→委托→运行状态', async () => {
    const user = userEvent.setup();
    useProjectStore.setState({
      projects: [
        {
          id: 'p1',
          name: '青云志',
          tags: ['玄幻'],
          language: 'zh-CN',
          target_words: 800000,
          config: {},
          created_at: '2026-08-01T10:00:00Z',
          updated_at: '2026-08-05T10:00:00Z',
        },
      ],
      currentProjectId: 'p1',
      loading: false,
      error: null,
    });

    // URL 分发 mock：访谈 → 回答 → 运行（S1a 端点形状）
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/provider-configs') {
        return { items: [READY_PROVIDER], total: 1, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/agent/books/planner' && init?.method === 'POST') {
        return { session_id: 'sess-1', round: 1, questions: round1, max_rounds: 5 };
      }
      if (path === '/api/v1/agent/books/planner/sess-1/respond' && init?.method === 'POST') {
        const body = init.body as { answers?: Record<string, string>; auto?: boolean };
        if (body?.auto) {
          return {
            session_id: 'sess-1',
            round: 1,
            completed: true,
            questions: [],
            writing_plan: { ...wp, status: 'auto' },
          };
        }
        if (body?.answers?.q1) {
          return { session_id: 'sess-1', round: 2, completed: false, questions: round2, writing_plan: null };
        }
        return { session_id: 'sess-1', round: 2, completed: true, questions: [], writing_plan: wp };
      }
      if (path === '/api/v1/agent/books/runs' && init?.method === 'POST') {
        return { run_id: 'wp-1', status: 'completed' };
      }
      if (path === '/api/v1/agent/books/runs/wp-1') {
        return {
          run_id: 'wp-1',
          status: 'completed',
          progress: { 'o-ch1': 'done' },
          counters: { max_chapters: 1, max_agent_calls: 1, agent_calls: 1, chapters_written: 1 },
        };
      }
      throw new Error(`unexpected: ${path}`);
    });

    render(
      <MemoryRouter>
        <BookPage />
      </MemoryRouter>,
    );
    const panel = await screen.findByTestId('book-planner-panel');
    expect(within(panel).getByTestId('book-one-liner')).toBeInTheDocument();

    // 1. 启动访谈
    await user.type(within(panel).getByTestId('book-one-liner'), '写一本关于时间旅者的悬疑小说');
    await user.click(within(panel).getByTestId('book-planner-start'));
    expect(await within(panel).findByTestId('book-question-q1')).toHaveTextContent('题材');

    // 2. 回答轮1 → 轮2
    await user.type(within(panel).getByTestId('book-answer'), '悬疑为主');
    await user.click(within(panel).getByTestId('book-send'));
    expect(await within(panel).findByTestId('book-question-q4')).toHaveTextContent('配角');

    // 3. 回答轮2 → completed → 计划展示
    await user.type(within(panel).getByTestId('book-answer'), '2 个');
    await user.click(within(panel).getByTestId('book-send'));
    await waitFor(() => {
      expect(within(panel).getByTestId('book-plan-title')).toHaveTextContent('写一本关于时间旅者的悬疑小说');
    });

    // 4. 开始写作（委托）→ 运行面板 + 展开行 + 计数
    await user.click(within(panel).getByTestId('book-start-run'));
    const runPanel = await within(panel).findByTestId('book-run-panel');
    await waitFor(() => {
      expect(within(runPanel).getByTestId('run-status')).toHaveTextContent('completed');
    });
    expect(within(runPanel).getByTestId('trace-row-o-ch1')).toBeInTheDocument();
    expect(within(runPanel).getByTestId('run-counter-chapters')).toHaveTextContent('1');
    expect(within(runPanel).getByTestId('run-counter-calls')).toHaveTextContent('1');
  });

  it('「全部你决定」路径：auto → writingPlan(status=auto) → 委托', async () => {
    const user = userEvent.setup();
    useProjectStore.setState({
      projects: [
        {
          id: 'p1',
          name: '青云志',
          tags: ['玄幻'],
          language: 'zh-CN',
          target_words: 800000,
          config: {},
          created_at: '2026-08-01T10:00:00Z',
          updated_at: '2026-08-05T10:00:00Z',
        },
      ],
      currentProjectId: 'p1',
      loading: false,
      error: null,
    });
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/provider-configs') {
        return { items: [READY_PROVIDER], total: 1, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/agent/books/planner' && init?.method === 'POST') {
        return { session_id: 'sess-1', round: 1, questions: round1, max_rounds: 5 };
      }
      if (path === '/api/v1/agent/books/planner/sess-1/respond' && init?.method === 'POST') {
        const body = init.body as { auto?: boolean };
        if (body?.auto) {
          return {
            session_id: 'sess-1',
            round: 1,
            completed: true,
            questions: [],
            writing_plan: { ...wp, status: 'auto' },
          };
        }
        return { session_id: 'sess-1', round: 2, completed: false, questions: round2, writing_plan: null };
      }
      if (path === '/api/v1/agent/books/runs' && init?.method === 'POST') {
        return { run_id: 'wp-1', status: 'completed' };
      }
      if (path === '/api/v1/agent/books/runs/wp-1') {
        return {
          run_id: 'wp-1',
          status: 'completed',
          progress: { 'o-ch1': 'done' },
          counters: { max_chapters: 1, max_agent_calls: 1, agent_calls: 1, chapters_written: 1 },
        };
      }
      throw new Error(`unexpected: ${path}`);
    });

    render(
      <MemoryRouter>
        <BookPage />
      </MemoryRouter>,
    );
    const panel = await screen.findByTestId('book-planner-panel');
    await user.type(within(panel).getByTestId('book-one-liner'), '写一本关于时间旅者的悬疑小说');
    await user.click(within(panel).getByTestId('book-planner-start'));
    await within(panel).findByTestId('book-question-q1');
    await user.click(within(panel).getByTestId('book-auto'));
    await waitFor(() => {
      expect(within(panel).getByTestId('book-plan-status')).toBeInTheDocument();
    });
    await user.click(within(panel).getByTestId('book-start-run'));
    await waitFor(() => {
      expect(within(panel).getByTestId('run-status')).toHaveTextContent('completed');
    });
  });
});

describe('book 页 — 模型未配置前置校验（#474 P0）', () => {
  /**
   * 契约：页面级三入口覆盖——未配置模型（无 key_saved=true 的 chat provider）时
   * 点 book-planner-start：不发 POST /api/v1/agent/books/planner + toast 提示。
   * 已配置模型（beforeEach 默认播种 READY_PROVIDER）主路径闭环照常（既有用例）。
   */
  it('未配置模型 → 点 book-planner-start → toast + 不发 planner 请求', async () => {
    const user = userEvent.setup();
    useModelsStore.setState({ providers: [], loading: false, error: null });
    useProjectStore.setState({
      projects: [
        {
          id: 'p1',
          name: '青云志',
          tags: ['玄幻'],
          language: 'zh-CN',
          target_words: 800000,
          config: {},
          created_at: '2026-08-01T10:00:00Z',
          updated_at: '2026-08-05T10:00:00Z',
        },
      ],
      currentProjectId: 'p1',
      loading: false,
      error: null,
    });
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/provider-configs') {
        return { items: [], total: 0, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/projects/p1') return { id: 'p1', config: {} };
      throw new Error(`unexpected: ${path}`);
    });
    render(
      <MemoryRouter>
        <BookPage />
      </MemoryRouter>,
    );
    const panel = await screen.findByTestId('book-planner-panel');
    await user.type(within(panel).getByTestId('book-one-liner'), '写一本关于时间旅者的悬疑小说');
    await user.click(within(panel).getByTestId('book-planner-start'));
    const plannerCalls = apiFetchMock.mock.calls.filter(
      (c) => c[0] === '/api/v1/agent/books/planner' && (c[1] as { method?: string } | undefined)?.method === 'POST',
    );
    expect(plannerCalls).toHaveLength(0);
    expect(useToastStore.getState().toasts.some((t) => t.type === 'warn')).toBe(true);
  });
});

describe('book 页 — v1.2 #475 末尾总体确认主路径（confirming → 确认卡片 → respondConfirm → 完成）', () => {
  /**
   * 契约（spec v1.2 §3.2 示例 + §13 M14）：
   * - 真实 store + URL 分发 mock：启动访谈 → 回答 → 响应 confirming=true + questions 空
   *   + confirmed_items 全量 → 渲染 book-confirm-card + book-confirm-item-<key>
   * - 点 book-confirm-ok → respondConfirm → POST respond {confirm:true}
   *   → 响应 completed + writing_plan → 计划展示（book-plan-title）
   */
  it('确认卡片 → 点确认 → 完成计划展示（确认卡片主路径闭环）', async () => {
    const user = userEvent.setup();
    useProjectStore.setState({
      projects: [
        {
          id: 'p1',
          name: '青云志',
          tags: ['玄幻'],
          language: 'zh-CN',
          target_words: 800000,
          config: {},
          created_at: '2026-08-01T10:00:00Z',
          updated_at: '2026-08-05T10:00:00Z',
        },
      ],
      currentProjectId: 'p1',
      loading: false,
      error: null,
    });
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path === '/api/v1/provider-configs') {
        return { items: [READY_PROVIDER], total: 1, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/agent/books/planner' && init?.method === 'POST') {
        return {
          session_id: 'sess-1',
          round: 1,
          questions: round1,
          max_rounds: 5,
          confirmed_items: [],
          conflicts: [],
          confirming: false,
        };
      }
      if (path === '/api/v1/agent/books/planner/sess-1/respond' && init?.method === 'POST') {
        const body = init.body as { confirm?: boolean; answers?: Record<string, string> };
        if (body?.confirm) {
          return { session_id: 'sess-1', round: 4, completed: true, confirming: false, questions: [], writing_plan: wp };
        }
        if (body?.answers?.q1) {
          // 回答后 → confirming=true：questions 空 + 确定项全量（v1.2 §3.2 示例）
          return {
            session_id: 'sess-1',
            round: 4,
            completed: false,
            questions: [],
            writing_plan: null,
            confirmed_items: [
              { key: '题材', value: '悬疑 + 时间悖论科幻', source: 'user' },
              { key: '篇幅', value: '10 万字', source: 'llm_inferred' },
            ],
            conflicts: [],
            confirming: true,
          };
        }
        throw new Error(`unexpected respond body: ${JSON.stringify(body)}`);
      }
      throw new Error(`unexpected: ${path}`);
    });

    render(
      <MemoryRouter>
        <BookPage />
      </MemoryRouter>,
    );
    const panel = await screen.findByTestId('book-planner-panel');
    await user.type(within(panel).getByTestId('book-one-liner'), '写一本关于时间旅者的悬疑小说');
    await user.click(within(panel).getByTestId('book-planner-start'));
    await within(panel).findByTestId('book-question-q1');

    // 回答 → confirming=true → 确认卡片
    await user.type(within(panel).getByTestId('book-answer'), '悬疑为主');
    await user.click(within(panel).getByTestId('book-send'));
    const card = await within(panel).findByTestId('book-confirm-card');
    expect(within(card).getByTestId('book-confirm-item-题材')).toHaveTextContent('悬疑 + 时间悖论科幻');
    expect(within(card).getByTestId('book-confirm-item-篇幅')).toHaveTextContent('10 万字');

    // 点确认 → respondConfirm → completed → 计划展示
    await user.click(within(panel).getByTestId('book-confirm-ok'));
    await waitFor(() => {
      expect(within(panel).getByTestId('book-plan-title')).toHaveTextContent('写一本关于时间旅者的悬疑小说');
    });
  });
});
