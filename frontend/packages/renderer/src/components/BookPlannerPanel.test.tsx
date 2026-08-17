/**
 * BookPlannerPanel 契约测试（F44 阶段1 GUI，spec v1.1 §5.1 GUI 小节）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须新建 src/components/BookPlannerPanel.tsx 并匹配：
 *
 * export function BookPlannerPanel(props: { projectId: string }): JSX.Element
 *
 * 结构 testid：
 * - book-planner-panel（容器）
 * - 启动态：book-one-liner（一句话 textarea/input）/ book-planner-start（启动按钮）
 * - 访谈态：book-question-<qid>（问题文本）/ book-template-<qid>（模板按钮，点击填入回答框）
 *   / book-answer（回答输入）/ book-send（发送）/ book-auto（全部你决定按钮）
 * - 完成态：book-plan-title / book-plan-status / book-start-run（开始写作→委托按钮）
 * - 运行态：book-run-panel（BookRunPanel 容器，委托后显示）
 *
 * 行为契约（镜像 ChatPanel #379 先例 + S1a respond 语义）：
 * - 初始 idle：显示 one-liner 输入 + 启动按钮（无问题区）
 * - 点启动 → startPlanner(projectId, oneLiner) → 显示第一轮问题（≤5 问）
 * - 问题即模板：点 book-template-<qid> → 模板文本填入 book-answer（可编辑）
 * - 回答 + 发送 → store.respond({qid: text}) → 下一轮问题（completed=false）或完成态
 * - 点 book-auto → store.respondAuto()（全部你决定）→ 直接完成态
 * - completed → 显示 writingPlan 标题 + 状态徽标 + 「开始写作」按钮
 * - 点 book-start-run → store.startRun(planId) → 委托后切换渲染 BookRunPanel
 * - 错误 → 错误文案显示（book-planner-error），不切换阶段
 *
 * i18n key（GREEN 补 zh.ts/en.ts）：book.oneLiner / book.start / book.question /
 * book.template.copy / book.answer.placeholder / book.send / book.auto / book.plan.ready /
 * book.plan.auto / book.startRun / book.error
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BookPlannerPanel } from './BookPlannerPanel';
import { useBookStore } from '../stores/book';
import { useThemeStore } from '../stores/theme';
import { apiFetch } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

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
  apiFetchMock.mockResolvedValue({ run_id: 'wp-1', status: 'completed' });
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
  });
});

describe('BookPlannerPanel — 启动访谈', () => {
  it('渲染 book-planner-panel + one-liner 输入 + 启动按钮', () => {
    render(<BookPlannerPanel projectId="p1" />);
    expect(screen.getByTestId('book-planner-panel')).toBeInTheDocument();
    expect(screen.getByTestId('book-one-liner')).toBeInTheDocument();
    expect(screen.getByTestId('book-planner-start')).toBeInTheDocument();
  });

  it('输入一句话 + 点启动 → 渲染第一轮问题（问题即模板）', async () => {
    const user = userEvent.setup();
    const startSpy = vi.spyOn(useBookStore.getState(), 'startPlanner').mockResolvedValue();
    useBookStore.setState({
      sessionId: 'sess-1',
      round: 1,
      questions: round1,
      sessionStatus: 'drafting',
      oneLiner: '写一本关于时间旅者的悬疑小说',
    });
    render(<BookPlannerPanel projectId="p1" />);
    await user.type(screen.getByTestId('book-one-liner'), '写一本关于时间旅者的悬疑小说');
    await user.click(screen.getByTestId('book-planner-start'));
    await waitFor(() => {
      expect(startSpy).toHaveBeenCalledWith('p1', '写一本关于时间旅者的悬疑小说');
    });
    expect(await screen.findByTestId('book-question-q1')).toHaveTextContent('题材');
    expect(screen.getByTestId('book-question-q2')).toHaveTextContent('篇幅');
    expect(screen.getByTestId('book-question-q3')).toHaveTextContent('主角');
  });
});

describe('BookPlannerPanel — 问题即模板 + 回答发送', () => {
  it('点模板按钮 → 模板文本填入回答输入框（可编辑）', async () => {
    const user = userEvent.setup();
    useBookStore.setState({
      sessionId: 'sess-1',
      round: 1,
      questions: round1,
      sessionStatus: 'drafting',
    });
    render(<BookPlannerPanel projectId="p1" />);
    await user.click(await screen.findByTestId('book-template-q1'));
    const answer = screen.getByTestId('book-answer') as HTMLTextAreaElement;
    expect(answer.value).toContain('悬疑为主');
    // 可编辑：追加文本
    await user.type(answer, '，加入时间悖论');
    expect((screen.getByTestId('book-answer') as HTMLTextAreaElement).value).toContain('时间悖论');
  });

  it('回答 + 发送 → store.respond({qid: text}) → 下一轮问题', async () => {
    const user = userEvent.setup();
    const respondSpy = vi.spyOn(useBookStore.getState(), 'respond').mockResolvedValue();
    useBookStore.setState({
      sessionId: 'sess-1',
      round: 1,
      questions: round1,
      sessionStatus: 'drafting',
    });
    render(<BookPlannerPanel projectId="p1" />);
    await user.type(screen.getByTestId('book-answer'), '悬疑为主');
    await user.click(screen.getByTestId('book-send'));
    await waitFor(() => {
      expect(respondSpy).toHaveBeenCalledWith({ q1: '悬疑为主' });
    });
    // completed=false → 下一轮问题渲染
    useBookStore.setState({ round: 2, questions: round2 });
    expect(await screen.findByTestId('book-question-q4')).toHaveTextContent('配角');
  });
});

describe('BookPlannerPanel — 全部你决定 + 完成态 + 委托', () => {
  it('点 book-auto → store.respondAuto()（全部你决定）', async () => {
    const user = userEvent.setup();
    const autoSpy = vi.spyOn(useBookStore.getState(), 'respondAuto').mockResolvedValue();
    useBookStore.setState({
      sessionId: 'sess-1',
      round: 1,
      questions: round1,
      sessionStatus: 'drafting',
    });
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
    useBookStore.setState({
      sessionId: 'sess-1',
      round: 1,
      questions: round1,
      sessionStatus: 'drafting',
      error: '网络错误',
    });
    render(<BookPlannerPanel projectId="p1" />);
    expect(screen.getByTestId('book-planner-error')).toHaveTextContent('网络错误');
    expect(screen.queryByTestId('book-start-run')).not.toBeInTheDocument();
  });
});
