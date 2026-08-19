/**
 * BookPlannerPanel 契约测试（F44 阶段1 GUI + v1.2 #475 对话式访谈）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须匹配 src/components/BookPlannerPanel.tsx：
 *
 * export function BookPlannerPanel(props: { projectId: string })
 *
 * 结构 testid：
 * - book-planner-panel（容器）
 * - 启动态：book-one-liner（一句话 textarea/input）/ book-planner-start（启动按钮）
 * - 访谈态（对话式消息流，v1.2）：
 *   - book-msg-list（消息流容器，仅 drafting 渲染）
 *   - user 消息：book-msg-user-<index>（one_liner/answer/confirm/auto 统一 user 消息）
 *   - assistant 问题消息：book-question-<qid>（保留既有 testid，消息内嵌问题文本）
 *   - 模板 chip：book-template-<qid>（点击填入 book-answer，保留既有）
 *   - 冲突回问：book-msg-conflict-<qid>（kind=conflict 问题消息的警示样式）
 *   - 确认汇总卡片：book-confirm-card（confirming=true 时渲染）+ 确定项行
 *     book-confirm-item-<key> + 确认按钮 book-confirm-ok + 修改按钮 book-confirm-edit-<key>
 *   - 修改编辑态：book-confirm-edit-input-<key>（输入新值）+ book-confirm-edit-submit-<key>（提交回问）
 *   - 输入区：book-answer（自由文本回答）/ book-send（发送）/ book-auto（全部你决定）
 * - 完成态：book-plan-title / book-plan-status / book-start-run（开始写作→委托按钮）
 *   / book-limits-chapters / book-limits-calls / book-limits-tokens / book-limits-sessions
 *   （阶段2 上限配置数字输入，初始值 = project.config.extra.book_max_*）
 *   / book-limits-save（阶段2 保存上限按钮）
 *   / book-start-error（阶段2 startRun 失败内联文案，含 409「该章已有内容，拒绝重跑」）
 * - 运行态：book-run-panel（BookRunPanel 容器，委托后显示）
 *
 * 行为契约（镜像 ChatPanel #379 先例 + S1a respond 语义 + v1.2 §5.1 PR-2）：
 * - 初始 idle：显示 one-liner 输入 + 启动按钮（无消息流）
 * - 点启动 → startPlanner(projectId, oneLiner) → store.messages 构建 → 消息流渲染
 * - 消息流 = store.messages（spec「聊天消息本地 store」），组件纯渲染不本地管理消息
 * - 问题即模板：点 book-template-<qid> → 模板文本填入 book-answer（可编辑）
 * - 回答 + 发送 → store.respond({qid: text}) → 下一轮问题（completed=false）或完成态
 * - kind=conflict 问题消息 → book-msg-conflict-<qid> 警示样式（冲突内容 + 待确认）
 * - confirming=true（store.sessionConfirming）→ 渲染 book-confirm-card：
 *   - 点 book-confirm-ok → store.respondConfirm()（总体确认通过）
 *   - 点 book-confirm-edit-<key> → 编辑输入框出现 → 输入新值 + 提交
 *     → store.respond({key: 新值})（修改后回 questioning 重问）
 * - 点 book-auto → store.respondAuto()（全部你决定）→ 直接完成态
 * - completed → 显示 writingPlan 标题 + 状态徽标 + 「开始写作」按钮 + 上限配置表单
 * - 点 book-start-run → store.startRun(planId) → 委托后切换渲染 BookRunPanel
 * - 阶段2：startRun 失败（409 安全阀）→ book-start-error 显示「该章已有内容，拒绝重跑」
 * - 阶段2：上限保存 → useBookLimits.save → PATCH /projects/{id} {config: {extra}}
 * - 错误 → 错误文案显示（book-planner-error），不切换阶段
 *
 * i18n key（GREEN 补 zh.ts/en.ts）：book.oneLiner / book.start / book.question /
 * book.template.copy / book.answer.placeholder / book.send / book.auto / book.plan.ready /
 * book.plan.auto / book.startRun / book.error / book.confirm.title（确认汇总标题）/
 * book.confirm.ok（确认）/ book.confirm.edit（修改）/ book.confirm.editSubmit（提交修改）/
 * book.conflict.label（冲突警示）
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BookPlannerPanel } from './BookPlannerPanel';
import { useBookStore } from '../stores/book';
import { useProjectStore, type Project } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import { useModelsStore, type ProviderConfig } from '../stores/models';
import { useToastStore } from '../stores/toast';
import { apiFetch, ApiError } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

/** #474：已配置模型种子 provider（key_saved=true + chat 模型），默认播种让既有用例行为不变 */
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
const q4 = { id: 'q4', text: '配角：需要几个主要配角？', template: '___ 个' };
const round1 = [q1, q2, q3];
const round2 = [q4];

/** v1.2：消息流种子（startPlanner 后 store.messages 的等价形态） */
const msgUserOneLiner = { id: 'm1', role: 'user', kind: 'one_liner', text: '写一本关于时间旅者的悬疑小说' };
const msgQ1 = { id: 'm2', role: 'assistant', kind: 'question', questionId: 'q1', text: q1.text, template: q1.template };
const msgQ2 = { id: 'm3', role: 'assistant', kind: 'question', questionId: 'q2', text: q2.text, template: q2.template };
const msgQ3 = { id: 'm4', role: 'assistant', kind: 'question', questionId: 'q3', text: q3.text, template: q3.template };
const messagesRound1 = [msgUserOneLiner, msgQ1, msgQ2, msgQ3];
const msgQ4 = { id: 'm5', role: 'assistant', kind: 'question', questionId: 'q4', text: q4.text, template: q4.template };
const messagesRound2 = [...messagesRound1, { id: 'm6', role: 'user', kind: 'answer', text: '悬疑为主' }, msgQ4];

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

/** 播种 drafting 对话态（消息流 + 当前轮问题） */
function seedDrafting(messages: unknown[], questions: unknown[] = round1, extra: Record<string, unknown> = {}) {
  useBookStore.setState({
    sessionId: 'sess-1',
    round: 1,
    messages: messages as never,
    questions: questions as never,
    sessionStatus: 'drafting',
    ...extra,
  });
}

beforeEach(() => {
  apiFetchMock.mockReset();
  // #474：默认播种已配置模型 + provider-configs GET 返回同款（防 GREEN 挂载/发送时 loadProviders 覆盖）
  useModelsStore.setState({ providers: [READY_PROVIDER], loading: false, error: null });
  useToastStore.setState({ toasts: [] });
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/provider-configs') {
      return { items: [READY_PROVIDER], total: 1, offset: 0, limit: 50 };
    }
    return { run_id: 'wp-1', status: 'completed' };
  });
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
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
    // v1.2 #475 新字段默认值（RED 期播种合法：Zustand 合并未知键，GREEN 后生效）
    messages: [],
    confirmedItems: [],
    conflicts: [],
    sessionConfirming: false,
  });
});

describe('BookPlannerPanel — 启动访谈', () => {
  it('渲染 book-planner-panel + one-liner 输入 + 启动按钮', () => {
    render(<BookPlannerPanel projectId="p1" />);
    expect(screen.getByTestId('book-planner-panel')).toBeInTheDocument();
    expect(screen.getByTestId('book-one-liner')).toBeInTheDocument();
    expect(screen.getByTestId('book-planner-start')).toBeInTheDocument();
  });

  it('输入一句话 + 点启动 → 消息流渲染第一轮问题（问题即模板）', async () => {
    const user = userEvent.setup();
    const startSpy = vi.spyOn(useBookStore.getState(), 'startPlanner').mockResolvedValue();
    seedDrafting(messagesRound1, round1, { oneLiner: '写一本关于时间旅者的悬疑小说' });
    render(<BookPlannerPanel projectId="p1" />);
    await user.type(screen.getByTestId('book-one-liner'), '写一本关于时间旅者的悬疑小说');
    await user.click(screen.getByTestId('book-planner-start'));
    await waitFor(() => {
      expect(startSpy).toHaveBeenCalledWith('p1', '写一本关于时间旅者的悬疑小说');
    });
    // 消息流容器 + 消息内嵌问题（保留既有 book-question-<qid>）
    expect(screen.getByTestId('book-msg-list')).toBeInTheDocument();
    expect(screen.getByTestId('book-question-q1')).toHaveTextContent('题材');
    expect(screen.getByTestId('book-question-q2')).toHaveTextContent('篇幅');
    expect(screen.getByTestId('book-question-q3')).toHaveTextContent('主角');
  });
});

describe('BookPlannerPanel — 对话式消息流（v1.2 #475）', () => {
  it('消息流渲染 user one_liner + assistant 问题（book-msg-list + book-msg-user / book-question）', () => {
    seedDrafting(messagesRound1, round1);
    render(<BookPlannerPanel projectId="p1" />);
    const list = screen.getByTestId('book-msg-list');
    // user 消息（one_liner）
    expect(within(list).getByTestId('book-msg-user-0')).toHaveTextContent('写一本关于时间旅者的悬疑小说');
    // assistant 问题消息
    expect(within(list).getByTestId('book-question-q1')).toHaveTextContent('题材');
    expect(within(list).getByTestId('book-question-q2')).toHaveTextContent('篇幅');
  });

  it('问题即模板：点 book-template-<qid> → 模板文本填入 book-answer（可编辑）', async () => {
    const user = userEvent.setup();
    seedDrafting(messagesRound1, round1);
    render(<BookPlannerPanel projectId="p1" />);
    await user.click(screen.getByTestId('book-template-q1'));
    const answer = screen.getByTestId('book-answer') as HTMLTextAreaElement;
    expect(answer.value).toContain('悬疑为主');
    // 可编辑：追加文本
    await user.type(answer, '，加入时间悖论');
    expect((screen.getByTestId('book-answer') as HTMLTextAreaElement).value).toContain('时间悖论');
  });

  it('回答 + 发送 → store.respond({qid: text}) → 下一轮问题', async () => {
    const user = userEvent.setup();
    const respondSpy = vi.spyOn(useBookStore.getState(), 'respond').mockResolvedValue();
    seedDrafting(messagesRound1, round1);
    render(<BookPlannerPanel projectId="p1" />);
    await user.type(screen.getByTestId('book-answer'), '悬疑为主');
    await user.click(screen.getByTestId('book-send'));
    await waitFor(() => {
      expect(respondSpy).toHaveBeenCalledWith({ q1: '悬疑为主' });
    });
    // completed=false → 下一轮问题消息渲染（store 更新后）
    useBookStore.setState({ round: 2, messages: messagesRound2 as never, questions: round2 as never });
    expect(await screen.findByTestId('book-question-q4')).toHaveTextContent('配角');
  });

  it('kind=conflict 问题消息 → book-msg-conflict-<qid> 警示样式（冲突内容 + 待确认）', () => {
    const conflictMsg = {
      id: 'm-c1',
      role: 'assistant',
      kind: 'question',
      questionId: 'q6',
      text: '5 个配角对 10 万字篇幅偏多，建议 2-3 个——仍按 5 个？',
      questionKind: 'conflict',
    };
    seedDrafting([msgUserOneLiner, conflictMsg], [{ id: 'q6', text: conflictMsg.text, kind: 'conflict' }], {
      conflicts: [
        { round: 2, question_id: 'q5', answer: '配角 5 个', conflict_with: '篇幅/复杂度合理性', resolution: 'pending' },
      ],
    });
    render(<BookPlannerPanel projectId="p1" />);
    const conflict = screen.getByTestId('book-msg-conflict-q6');
    expect(conflict).toBeInTheDocument();
    expect(conflict).toHaveTextContent('配角');
    // 冲突警示文案（i18n book.conflict.label 或冲突内容）
    expect(conflict.textContent?.length).toBeGreaterThan(0);
  });

  it('confirming=true + confirm_summary 消息 → 确定项汇总卡片（确认/修改按钮）', async () => {
    const user = userEvent.setup();
    const confirmSpy = vi.spyOn(useBookStore.getState(), 'respondConfirm').mockResolvedValue();
    const summaryMsg = {
      id: 'm-sum',
      role: 'assistant',
      kind: 'confirm_summary',
      text: '确认以下设定？',
      confirmedItems: [
        { key: '题材', value: '悬疑 + 时间悖论科幻', source: 'user' },
        { key: '篇幅', value: '10 万字', source: 'user' },
      ],
    };
    seedDrafting([msgUserOneLiner, summaryMsg], [], {
      sessionConfirming: true,
      confirmedItems: summaryMsg.confirmedItems,
    });
    render(<BookPlannerPanel projectId="p1" />);
    const card = screen.getByTestId('book-confirm-card');
    expect(card).toBeInTheDocument();
    expect(screen.getByTestId('book-confirm-item-题材')).toHaveTextContent('悬疑 + 时间悖论科幻');
    expect(screen.getByTestId('book-confirm-item-篇幅')).toHaveTextContent('10 万字');
    // 确认 → respondConfirm()
    await user.click(screen.getByTestId('book-confirm-ok'));
    await waitFor(() => {
      expect(confirmSpy).toHaveBeenCalled();
    });
  });

  it('点修改按钮 → 编辑输入框出现 → 输入新值 + 提交 → store.respond({key: 新值}) 回问', async () => {
    const user = userEvent.setup();
    const respondSpy = vi.spyOn(useBookStore.getState(), 'respond').mockResolvedValue();
    const summaryMsg = {
      id: 'm-sum',
      role: 'assistant',
      kind: 'confirm_summary',
      text: '确认以下设定？',
      confirmedItems: [{ key: '题材', value: '悬疑 + 时间悖论科幻', source: 'user' }],
    };
    seedDrafting([msgUserOneLiner, summaryMsg], [], {
      sessionConfirming: true,
      confirmedItems: summaryMsg.confirmedItems,
    });
    render(<BookPlannerPanel projectId="p1" />);
    await user.click(screen.getByTestId('book-confirm-edit-题材'));
    // 编辑输入框出现 → 输入新值 → 提交
    const input = screen.getByTestId('book-confirm-edit-input-题材');
    await user.type(input, '悬疑 + 硬科幻');
    await user.click(screen.getByTestId('book-confirm-edit-submit-题材'));
    await waitFor(() => {
      expect(respondSpy).toHaveBeenCalledWith({ 题材: '悬疑 + 硬科幻' });
    });
  });
});

describe('BookPlannerPanel — 全部你决定 + 完成态 + 委托', () => {
  it('点 book-auto → store.respondAuto()（全部你决定）', async () => {
    const user = userEvent.setup();
    const autoSpy = vi.spyOn(useBookStore.getState(), 'respondAuto').mockResolvedValue();
    seedDrafting(messagesRound1, round1);
    render(<BookPlannerPanel projectId="p1" />);
    await user.click(screen.getByTestId('book-auto'));
    await waitFor(() => {
      expect(autoSpy).toHaveBeenCalled();
    });
  });

  it('completed → 显示计划标题 + 状态徽标 + 开始写作按钮', async () => {
    const user = userEvent.setup();
    useBookStore.setState({
      sessionId: 'sess-1',
      round: 2,
      questions: [],
      sessionStatus: 'completed',
      writingPlan: wp,
    });
    render(<BookPlannerPanel projectId="p1" />);
    expect(screen.getByTestId('book-plan-title')).toHaveTextContent('写一本关于时间旅者的悬疑小说');
    expect(screen.getByTestId('book-plan-status')).toBeInTheDocument();
    const runBtn = screen.getByTestId('book-start-run');
    expect(runBtn).toBeInTheDocument();
    await user.click(runBtn);
    await waitFor(() => {
      expect(useBookStore.getState().runId).toBe('wp-1');
    });
  });

  it('委托后（runId 非空）→ 渲染 BookRunPanel 容器', async () => {
    useBookStore.setState({
      sessionId: 'sess-1',
      round: 2,
      questions: [],
      sessionStatus: 'completed',
      writingPlan: wp,
      runId: 'wp-1',
      runStatus: 'completed',
    });
    render(<BookPlannerPanel projectId="p1" />);
    expect(await screen.findByTestId('book-run-panel')).toBeInTheDocument();
  });

  it('错误 → 显示 book-planner-error 文案，不切换阶段', async () => {
    seedDrafting(messagesRound1, round1, { error: '网络错误' });
    render(<BookPlannerPanel projectId="p1" />);
    expect(screen.getByTestId('book-planner-error')).toHaveTextContent('网络错误');
    expect(screen.queryByTestId('book-start-run')).not.toBeInTheDocument();
  });
});

describe('BookPlannerPanel — 阶段2 上限配置 + 409 安全阀文案（spec §5.2）', () => {
  const projectP1: Project = {
    id: 'p1',
    name: '时间旅者',
    genre: '悬疑',
    language: 'zh',
    target_words: 800000,
    config: { extra: { book_max_chapters: 5, book_max_tokens: 200000 } },
    created_at: '2026-08-17T10:00:00Z',
    updated_at: '2026-08-17T10:00:00Z',
  };

  beforeEach(() => {
    useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
  });

  it('完成态显示上限配置表单（初始值来自 project.config.extra）', () => {
    useBookStore.setState({
      sessionId: 'sess-1',
      round: 2,
      questions: [],
      sessionStatus: 'completed',
      writingPlan: wp,
    });
    render(<BookPlannerPanel projectId="p1" />);
    expect(screen.getByTestId('book-plan-title')).toBeInTheDocument();
    // 4 个上限输入 + 保存按钮；初始值 = project.config.extra.book_max_*
    expect(screen.getByTestId('book-limits-chapters')).toHaveValue(5);
    expect(screen.getByTestId('book-limits-calls')).toBeInTheDocument();
    expect(screen.getByTestId('book-limits-tokens')).toHaveValue(200000);
    expect(screen.getByTestId('book-limits-sessions')).toBeInTheDocument();
    expect(screen.getByTestId('book-limits-save')).toBeInTheDocument();
  });

  it('修改上限 + 保存 → PATCH /projects/p1 {config: {extra}} + 本地 project 更新', async () => {
    const user = userEvent.setup();
    useBookStore.setState({
      sessionId: 'sess-1',
      round: 2,
      questions: [],
      sessionStatus: 'completed',
      writingPlan: wp,
    });
    render(<BookPlannerPanel projectId="p1" />);
    const chaptersInput = screen.getByTestId('book-limits-chapters');
    await user.clear(chaptersInput);
    await user.type(chaptersInput, '8');
    await user.click(screen.getByTestId('book-limits-save'));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/projects/p1', {
        method: 'PATCH',
        body: {
          config: { extra: expect.objectContaining({ book_max_chapters: 8, book_max_tokens: 200000 }) },
        },
      });
    });
    // 本地 project store 更新（updateConfig 合并）
    const p = useProjectStore.getState().projects.find((x) => x.id === 'p1');
    expect(p?.config.extra?.book_max_chapters).toBe(8);
  });

  it('startRun 409 安全阀 → 完成态显示 book-start-error「该章已有内容，拒绝重跑」', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockRejectedValueOnce(new ApiError(409, '该章已有内容，拒绝重跑'));
    useBookStore.setState({
      sessionId: 'sess-1',
      round: 2,
      questions: [],
      sessionStatus: 'completed',
      writingPlan: wp,
    });
    render(<BookPlannerPanel projectId="p1" />);
    await user.click(screen.getByTestId('book-start-run'));
    expect(await screen.findByTestId('book-start-error')).toHaveTextContent('该章已有内容，拒绝重跑');
    // 启动按钮仍在（409 提示后用户可修改上限/重试，不隐藏入口）
    expect(screen.getByTestId('book-start-run')).toBeInTheDocument();
  });
});

describe('BookPlannerPanel — 按钮改名 + 模型未配置前置校验（#474 P0）', () => {
  /**
   * 契约：
   * 1. book.start 按钮文案 = 「开始对话」（zh）/ 'Start Conversation'（en）——i18n 改名（GREEN 改 zh.ts/en.ts）
   * 2. 用户未配置模型（无 key_saved=true 的 chat provider）时点 book-planner-start：
   *    - 不发 startPlanner 请求（不发 AI 请求）
   *    - toast 提示（type='warn'，文案引导去配置）
   * 已配置模型（beforeEach 默认播种 READY_PROVIDER）行为不变：正常 startPlanner。
   *
   * i18n key（GREEN 补 zh.ts/en.ts）：common.modelNotConfigured
   */
  it('启动按钮文案 = 开始对话（zh）', () => {
    render(<BookPlannerPanel projectId="p1" />);
    expect(screen.getByTestId('book-planner-start')).toHaveTextContent('开始对话');
  });

  it('启动按钮文案 = Start Conversation（en）', () => {
    useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'en' });
    render(<BookPlannerPanel projectId="p1" />);
    expect(screen.getByTestId('book-planner-start')).toHaveTextContent('Start Conversation');
  });

  it('未配置模型（providers 空）→ 点 book-planner-start → toast + 不发 startPlanner', async () => {
    useModelsStore.setState({ providers: [], loading: false, error: null });
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/provider-configs') {
        return { items: [], total: 0, offset: 0, limit: 50 };
      }
      return { run_id: 'wp-1', status: 'completed' };
    });
    const user = userEvent.setup();
    const startSpy = vi.spyOn(useBookStore.getState(), 'startPlanner').mockResolvedValue();
    render(<BookPlannerPanel projectId="p1" />);
    await user.type(screen.getByTestId('book-one-liner'), '写一本关于时间旅者的悬疑小说');
    await user.click(screen.getByTestId('book-planner-start'));
    expect(useToastStore.getState().toasts.some((t) => t.type === 'warn')).toBe(true);
    expect(useToastStore.getState().toasts.some((t) => t.message.includes('配置'))).toBe(true);
    expect(startSpy).not.toHaveBeenCalled();
    startSpy.mockRestore();
  });

  it('已配置模型（默认播种）→ 点 book-planner-start → startPlanner 正常（行为不变）', async () => {
    const user = userEvent.setup();
    const startSpy = vi.spyOn(useBookStore.getState(), 'startPlanner').mockResolvedValue();
    render(<BookPlannerPanel projectId="p1" />);
    await user.type(screen.getByTestId('book-one-liner'), '写一本关于时间旅者的悬疑小说');
    await user.click(screen.getByTestId('book-planner-start'));
    await waitFor(() => {
      expect(startSpy).toHaveBeenCalledWith('p1', '写一本关于时间旅者的悬疑小说');
    });
    startSpy.mockRestore();
  });
});
