/**
 * book store 测试契约（F44 阶段1 GUI，spec v1.1 §5.1 GUI 小节 + S1a #441 唯一真相）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须新建 src/stores/book.ts 并匹配：
 *
 * interface BookState {
 *   // 访谈状态（PlannerSession 驱动）
 *   sessionId: string | null;
 *   round: number;
 *   questions: PlannerQuestion[];
 *   answers: Record<string, string>;          // 已答问题 id → 回答文本
 *   authorized: string[];                     // 授权自定项（回答含「自定」）
 *   sessionStatus: 'idle' | 'drafting' | 'completed' | 'declined';
 *   oneLiner: string;
 *   // 计划产物
 *   writingPlan: WritingPlanDto | null;
 *   // 运行状态（run = WritingPlan.id，S1a 载体定稿）
 *   runId: string | null;
 *   runStatus: string | null;                 // completed/running/...
 *   progress: Record<string, string>;         // outline_id → PlanNodeStatus
 *   counters: RunStatusCounters | null;       // S2a 起含 max_tokens/tokens_used/tokens_warning
 *   progressStats: ProgressStats;             // 阶段2：progress 派生统计（章进度状态机）
 *   loading: boolean;
 *   error: string | null;
 *
 *   startPlanner(projectId: string, oneLiner: string): Promise<void>;
 *   respond(answers: Record<string, string>): Promise<void>;   // 回答当前轮问题
 *   respondAuto(): Promise<void>;                              // 全部你决定 → auto:true
 *   loadSession(sessionId: string): Promise<void>;
 *   startRun(planId: string, limits?: Record<string, number>): Promise<void>;  // POST /runs → runId（阶段2 可选 limits）
 *   loadRunStatus(runId: string): Promise<void>;               // GET /runs/{id} → progress/counters/progressStats
 *   reset(): void;                                             // 新一轮访谈前清空
 * }
 *
 * 行为契约（以 S1a respond 返回驱动阶段切换）：
 * - startPlanner → POST /planner → sessionStatus='drafting' + questions=round1 + round=1
 * - respond(answers) → POST /planner/{id}/respond {answers, auto:false}
 *   completed=false → round/questions 更新（下一轮）；completed=true → writingPlan 设置 + sessionStatus='completed'
 * - respondAuto() → POST /planner/{id}/respond {answers:{}, auto:true} → writingPlan(status=auto) + completed
 * - loadSession → GET /planner/{id} → 恢复会话快照
 * - startRun(planId, limits?) → POST /runs {writing_plan_id, ...(limits ? {limits} : {})} → runId + runStatus
 * - loadRunStatus(runId) → GET /runs/{runId} → progress + counters + progressStats 派生
 *   progressStats = {total, done, inProgress, failed, skipped, pending}（progress 值计数，阶段2）
 * - 失败 → error 设置（errorMessage），loading=false
 *
 * ⚠️ F44 阶段3（#337 卷级 HITL）增量——GREEN 必须追加：
 *
 * // state 新增（初始值）：
 * //   waitingHitl: boolean（false）；hitlPayload: HitlPayload | null（null）；confirming: boolean（false）
 * // action 新增：
 * //   confirmRun(approved: boolean, decision?: string): Promise<boolean>
 * //
 * // 行为契约（S1a backend api/routers/books.py confirm_run + book_service.get_status 实证）：
 * // - loadRunStatus 成功透传：waitingHitl = res.waiting_hitl === true；hitlPayload = res.hitl_payload ?? null
 * // - confirmRun：runId 为 null → 直接 return false；否则 POST /runs/{id}/confirm
 * //   body = decision ? {approved, decision} : {approved}
 * //   成功 → runStatus = res.status；
 * //     res.status==='waiting_hitl' && res.hitl_payload → waitingHitl=true + hitlPayload=新 payload（覆盖）
 * //     否则 → waitingHitl=false + hitlPayload=null；return true
 * //   失败 → error = errorMessage(err) + return false（confirming 请求期间 true，结束后 false）
 * // - reset 清空 waitingHitl/hitlPayload/confirming
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act } from '@testing-library/react';
import { useBookStore } from './book';
import { apiFetch, ApiError } from '../api/client';

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

const wpCompleted = {
  id: 'wp-1',
  project_id: 'p1',
  title: '写一本关于时间旅者的悬疑小说',
  status: 'ready',
  root_outline_id: 'o-1',
  character_ids: ['c-1'],
  limits: { max_chapters: 1, max_agent_calls: 1 },
  progress: {},
  execution_refs: {},
  thread_id: null,
  created_at: '2026-08-17T10:00:00Z',
  updated_at: '2026-08-17T10:00:00Z',
};

beforeEach(() => {
  apiFetchMock.mockReset();
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
    progressStats: { total: 0, done: 0, inProgress: 0, failed: 0, skipped: 0, pending: 0 },
    loading: false,
    error: null,
    // F44 阶段3（#337）新字段默认值（RED 期播种合法：Zustand 合并未知键，GREEN 后生效）
    waitingHitl: false,
    hitlPayload: null,
    confirming: false,
  });
});

describe('book store — 契约面（GREEN 必须提供）', () => {
  it('暴露 REST actions: startPlanner / respond / respondAuto / loadSession / startRun / loadRunStatus / reset', () => {
    const s = useBookStore.getState();
    expect(typeof s.startPlanner).toBe('function');
    expect(typeof s.respond).toBe('function');
    expect(typeof s.respondAuto).toBe('function');
    expect(typeof s.loadSession).toBe('function');
    expect(typeof s.startRun).toBe('function');
    expect(typeof s.loadRunStatus).toBe('function');
    expect(typeof s.reset).toBe('function');
  });

  it('初始状态：idle / 空问题 / 无计划 / 无运行', () => {
    const s = useBookStore.getState();
    expect(s.sessionId).toBeNull();
    expect(s.sessionStatus).toBe('idle');
    expect(s.questions).toEqual([]);
    expect(s.writingPlan).toBeNull();
    expect(s.runId).toBeNull();
  });
});

describe('book store — 访谈状态机', () => {
  it('startPlanner：POST /planner → drafting + 第一轮问题', async () => {
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/agent/books/planner' && init?.method === 'POST') {
        return { session_id: 'sess-1', round: 1, questions: round1, max_rounds: 5 };
      }
      throw new Error(`unexpected: ${path}`);
    });
    await act(async () => {
      await useBookStore.getState().startPlanner('p1', '写一本关于时间旅者的悬疑小说');
    });
    const s = useBookStore.getState();
    expect(s.sessionId).toBe('sess-1');
    expect(s.sessionStatus).toBe('drafting');
    expect(s.round).toBe(1);
    expect(s.questions).toHaveLength(3);
    expect(s.questions[0].template).toContain('___');
  });

  it('respond：completed=false → 下一轮问题；answers 按问题 id 记录', async () => {
    apiFetchMock.mockResolvedValue({
      session_id: 'sess-1',
      round: 2,
      completed: false,
      questions: round2,
      writing_plan: null,
    });
    useBookStore.setState({ sessionId: 'sess-1', round: 1, questions: round1, sessionStatus: 'drafting' });
    await act(async () => {
      await useBookStore.getState().respond({ q1: '悬疑为主，加入时间悖论' });
    });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/books/planner/sess-1/respond', {
      method: 'POST',
      body: { answers: { q1: '悬疑为主，加入时间悖论' }, auto: false },
    });
    const s = useBookStore.getState();
    expect(s.round).toBe(2);
    expect(s.questions).toEqual(round2);
    expect(s.answers.q1).toBe('悬疑为主，加入时间悖论');
  });

  it('respond：completed=true → writingPlan 设置 + sessionStatus=completed', async () => {
    apiFetchMock.mockResolvedValue({
      session_id: 'sess-1',
      round: 2,
      completed: true,
      questions: [],
      writing_plan: wpCompleted,
    });
    useBookStore.setState({ sessionId: 'sess-1', round: 2, questions: round2, sessionStatus: 'drafting' });
    await act(async () => {
      await useBookStore.getState().respond({ q4: '2 个' });
    });
    const s = useBookStore.getState();
    expect(s.sessionStatus).toBe('completed');
    expect(s.writingPlan?.id).toBe('wp-1');
    expect(s.writingPlan?.status).toBe('ready');
  });

  it('respondAuto：POST {answers:{}, auto:true} → writingPlan(status=auto)', async () => {
    apiFetchMock.mockResolvedValue({
      session_id: 'sess-1',
      round: 1,
      completed: true,
      questions: [],
      writing_plan: { ...wpCompleted, status: 'auto' },
    });
    useBookStore.setState({ sessionId: 'sess-1', round: 1, questions: round1, sessionStatus: 'drafting' });
    await act(async () => {
      await useBookStore.getState().respondAuto();
    });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/books/planner/sess-1/respond', {
      method: 'POST',
      body: { answers: {}, auto: true },
    });
    expect(useBookStore.getState().writingPlan?.status).toBe('auto');
    expect(useBookStore.getState().sessionStatus).toBe('completed');
  });

  it('respond 失败 → error 设置 + sessionStatus 保持 drafting', async () => {
    apiFetchMock.mockRejectedValue(new Error('网络错误'));
    useBookStore.setState({ sessionId: 'sess-1', round: 1, questions: round1, sessionStatus: 'drafting' });
    await act(async () => {
      await useBookStore.getState().respond({ q1: 'x' });
    });
    const s = useBookStore.getState();
    expect(s.error).toBe('网络错误');
    expect(s.sessionStatus).toBe('drafting');
  });
});

describe('book store — 运行状态（run = WritingPlan.id）', () => {
  it('startRun：POST /runs → runId + runStatus', async () => {
    apiFetchMock.mockResolvedValue({ run_id: 'wp-1', status: 'completed' });
    await act(async () => {
      await useBookStore.getState().startRun('wp-1');
    });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/books/runs', {
      method: 'POST',
      body: { writing_plan_id: 'wp-1' },
    });
    const s = useBookStore.getState();
    expect(s.runId).toBe('wp-1');
    expect(s.runStatus).toBe('completed');
  });

  it('loadRunStatus：GET /runs/{id} → progress + counters', async () => {
    apiFetchMock.mockResolvedValue({
      run_id: 'wp-1',
      status: 'completed',
      progress: { 'o-ch1': 'done' },
      counters: { max_chapters: 1, max_agent_calls: 1, agent_calls: 1, chapters_written: 1 },
    });
    await act(async () => {
      await useBookStore.getState().loadRunStatus('wp-1');
    });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/books/runs/wp-1');
    const s = useBookStore.getState();
    expect(s.progress['o-ch1']).toBe('done');
    expect(s.counters?.chapters_written).toBe(1);
  });

  it('reset：清空访谈 + 运行状态（新一轮）', () => {
    useBookStore.setState({
      sessionId: 'sess-1',
      round: 2,
      questions: round2,
      sessionStatus: 'completed',
      writingPlan: wpCompleted,
      runId: 'wp-1',
      runStatus: 'completed',
      progress: { 'o-ch1': 'done' },
    });
    useBookStore.getState().reset();
    const s = useBookStore.getState();
    expect(s.sessionId).toBeNull();
    expect(s.sessionStatus).toBe('idle');
    expect(s.writingPlan).toBeNull();
    expect(s.runId).toBeNull();
    expect(s.progress).toEqual({});
  });
});

describe('book store — 阶段2 进度状态机 + limits 透传（S2a #445）', () => {
  it('loadRunStatus 派生 progressStats（5 态计数）+ counters tokens 透传', async () => {
    apiFetchMock.mockResolvedValue({
      run_id: 'wp-1',
      status: 'running',
      progress: {
        'o-c1': 'done',
        'o-c2': 'in_progress',
        'o-c3': 'pending',
        'o-c4': 'failed',
        'o-c5': 'skipped',
      },
      counters: {
        max_chapters: 5,
        max_agent_calls: 10,
        agent_calls: 2,
        chapters_written: 1,
        max_tokens: 200000,
        tokens_used: 12345,
        tokens_warning: false,
      },
    });
    await act(async () => {
      await useBookStore.getState().loadRunStatus('wp-1');
    });
    const s = useBookStore.getState();
    expect(s.progressStats).toEqual({
      total: 5,
      done: 1,
      inProgress: 1,
      failed: 1,
      skipped: 1,
      pending: 1,
    });
    // S2a counters 扩展透传（max_tokens/tokens_used/tokens_warning）
    expect(s.counters?.max_tokens).toBe(200000);
    expect(s.counters?.tokens_used).toBe(12345);
    expect(s.counters?.tokens_warning).toBe(false);
  });

  it('startRun 可选 limits 参数 → body.limits 透传（Q2=C 请求显式优先级）', async () => {
    apiFetchMock.mockResolvedValue({ run_id: 'wp-1', status: 'completed' });
    await act(async () => {
      await useBookStore.getState().startRun('wp-1', { max_chapters: 5, max_tokens: 200000 });
    });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/books/runs', {
      method: 'POST',
      body: { writing_plan_id: 'wp-1', limits: { max_chapters: 5, max_tokens: 200000 } },
    });
    const s = useBookStore.getState();
    expect(s.runId).toBe('wp-1');
    expect(s.runStatus).toBe('completed');
  });

  it('startRun 不传 limits → body 无 limits 键（向后兼容）', async () => {
    apiFetchMock.mockResolvedValue({ run_id: 'wp-1', status: 'completed' });
    await act(async () => {
      await useBookStore.getState().startRun('wp-1');
    });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/books/runs', {
      method: 'POST',
      body: { writing_plan_id: 'wp-1' },
    });
  });

  it('reset 清空 progressStats（新一轮）', () => {
    useBookStore.setState({
      progressStats: { total: 3, done: 1, inProgress: 1, failed: 0, skipped: 0, pending: 1 },
    });
    useBookStore.getState().reset();
    expect(useBookStore.getState().progressStats).toEqual({
      total: 0,
      done: 0,
      inProgress: 0,
      failed: 0,
      skipped: 0,
      pending: 0,
    });
  });
});

describe('book store — 阶段3 卷级 HITL（#337 waitingHitl/hitlPayload/confirming/confirmRun）', () => {
  const boundaryPayload = {
    question: '确认继续下一卷？',
    volume_index: 0,
    progress: { 'o-c1': 'done' },
  };
  const newBoundaryPayload = {
    question: '确认继续下一卷？',
    volume_index: 1,
    progress: { 'o-c2': 'done' },
  };
  const failurePayload = {
    question: '卷执行失败，如何继续？',
    failed: ['o-c1', 'o-c2'],
  };

  it('契约面：confirmRun 是函数 + 初始 waitingHitl=false / hitlPayload=null / confirming=false', () => {
    const s = useBookStore.getState();
    expect(typeof s.confirmRun).toBe('function');
    expect(s.waitingHitl).toBe(false);
    expect(s.hitlPayload).toBeNull();
    expect(s.confirming).toBe(false);
  });

  it('loadRunStatus 透传 waiting_hitl=true + hitl_payload（卷边界形态）', async () => {
    apiFetchMock.mockResolvedValue({
      run_id: 'wp-1',
      status: 'waiting_hitl',
      progress: { 'o-c1': 'done' },
      counters: { max_chapters: 1, max_agent_calls: 1, agent_calls: 1, chapters_written: 1 },
      waiting_hitl: true,
      hitl_payload: boundaryPayload,
    });
    await act(async () => {
      await useBookStore.getState().loadRunStatus('wp-1');
    });
    const s = useBookStore.getState();
    expect(s.waitingHitl).toBe(true);
    expect(s.hitlPayload?.question).toBe('确认继续下一卷？');
    expect(s.hitlPayload?.progress?.['o-c1']).toBe('done');
  });

  it('confirmRun(true)：POST body {approved:true} → completed → 对话框关闭（waitingHitl=false + hitlPayload=null）', async () => {
    apiFetchMock.mockResolvedValue({ run_id: 'wp-1', status: 'completed' });
    useBookStore.setState({
      runId: 'wp-1',
      runStatus: 'waiting_hitl',
      // 中间态（非默认）播种：等待确认中 waitingHitl=true 成立
      // → 最终清零断言（false/null）在 RED 期必 FAIL（无该字段实现时清零永不发生），防假绿
      waitingHitl: true,
      hitlPayload: boundaryPayload,
    });
    const ok = await act(async () => {
      return useBookStore.getState().confirmRun(true);
    });
    expect(ok).toBe(true);
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/books/runs/wp-1/confirm', {
      method: 'POST',
      body: { approved: true },
    });
    const s = useBookStore.getState();
    expect(s.runStatus).toBe('completed');
    expect(s.waitingHitl).toBe(false);
    expect(s.hitlPayload).toBeNull();
  });

  it('confirmRun(false, abort)：POST body {approved:false, decision:abort} → 返回 true', async () => {
    apiFetchMock.mockResolvedValue({ run_id: 'wp-1', status: 'aborted' });
    useBookStore.setState({
      runId: 'wp-1',
      runStatus: 'waiting_hitl',
      waitingHitl: true,
      hitlPayload: failurePayload,
    });
    const ok = await act(async () => {
      return useBookStore.getState().confirmRun(false, 'abort');
    });
    expect(ok).toBe(true);
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/books/runs/wp-1/confirm', {
      method: 'POST',
      body: { approved: false, decision: 'abort' },
    });
    const s = useBookStore.getState();
    expect(s.runStatus).toBe('aborted');
    expect(s.waitingHitl).toBe(false);
  });

  it('confirmRun(true, supervisor)：响应仍 waiting_hitl + 新 payload → 对话框保持 + payload 覆盖', async () => {
    apiFetchMock.mockResolvedValue({
      run_id: 'wp-1',
      status: 'waiting_hitl',
      hitl_payload: newBoundaryPayload,
    });
    useBookStore.setState({
      runId: 'wp-1',
      runStatus: 'waiting_hitl',
      waitingHitl: true,
      hitlPayload: boundaryPayload,
    });
    const ok = await act(async () => {
      return useBookStore.getState().confirmRun(true, 'supervisor');
    });
    expect(ok).toBe(true);
    const s = useBookStore.getState();
    expect(s.runStatus).toBe('waiting_hitl');
    expect(s.waitingHitl).toBe(true);
    // 新 payload 覆盖旧 payload（下一卷边界暂停）
    expect(s.hitlPayload?.volume_index).toBe(1);
    expect(s.hitlPayload?.progress?.['o-c2']).toBe('done');
  });

  it('confirmRun 失败 → error 设置 + 返回 false + waitingHitl 保持', async () => {
    apiFetchMock.mockRejectedValue(new ApiError(409, '运行不在等待确认状态'));
    useBookStore.setState({
      runId: 'wp-1',
      runStatus: 'waiting_hitl',
      waitingHitl: true,
      hitlPayload: boundaryPayload,
    });
    const ok = await act(async () => {
      return useBookStore.getState().confirmRun(true);
    });
    expect(ok).toBe(false);
    const s = useBookStore.getState();
    expect(s.error).toBe('运行不在等待确认状态');
    expect(s.waitingHitl).toBe(true);
    expect(s.hitlPayload).toEqual(boundaryPayload);
  });

  it('reset 清空 waitingHitl/hitlPayload/confirming（非默认态播种 → 清零断言非假绿）', () => {
    useBookStore.setState({
      waitingHitl: true,
      hitlPayload: boundaryPayload,
      confirming: true,
    });
    useBookStore.getState().reset();
    const s = useBookStore.getState();
    expect(s.waitingHitl).toBe(false);
    expect(s.hitlPayload).toBeNull();
    expect(s.confirming).toBe(false);
  });
});
