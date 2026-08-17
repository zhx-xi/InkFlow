/**
 * books API 封装契约测试（F44 阶段1 GUI，spec v1.1 §3.1 + S1a #441 后端唯一真相）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须新建 src/api/books.ts 并匹配：
 *
 * export interface PlannerQuestion {
 *   id: string;
 *   text: string;
 *   template: string;
 * }
 * export interface PlannerStartResponse {
 *   session_id: string;
 *   round: number;
 *   questions: PlannerQuestion[];
 *   max_rounds: number;
 * }
 * export interface PlannerRespondRequest {
 *   answers: Record<string, string>;
 *   auto?: boolean;
 * }
 * export interface WritingPlanDto {
 *   id: string;
 *   project_id: string;
 *   title: string;
 *   status: string;
 *   root_outline_id: string | null;
 *   character_ids: string[];
 *   limits: Record<string, number>;
 *   progress: Record<string, string>;
 *   execution_refs: Record<string, string>;
 *   thread_id: string | null;
 *   created_at: string;
 *   updated_at: string;
 * }
 * export interface PlannerRespondResponse {
 *   session_id: string;
 *   round: number;
 *   completed: boolean;
 *   questions: PlannerQuestion[];
 *   writing_plan: WritingPlanDto | null;
 * }
 * export interface PlannerSessionDto {
 *   id: string;
 *   project_id: string;
 *   status: string;
 *   one_liner: string;
 *   round: number;
 *   asked_questions: PlannerQuestion[];
 *   answers: Record<string, string>;
 *   authorized: string[];
 *   writing_plan_id: string | null;
 *   created_at: string;
 *   updated_at: string;
 * }
 * export interface BookRunRequest {
 *   writing_plan_id: string;
 *   limits?: Record<string, number>;
 *   mode?: string;
 * }
 * export interface BookRunResponse {
 *   run_id: string;
 *   status: string;
 * }
 * export interface RunStatusCounters {
 *   max_chapters: number;
 *   max_agent_calls: number;
 *   agent_calls: number;
 *   chapters_written: number;
 *   // S2a（#445）扩展：可选键（旧后端/旧数据无 → undefined，向后兼容）
 *   max_tokens?: number;
 *   tokens_used?: number;
 *   tokens_warning?: boolean;
 * }
 * export interface RunStatusResponse {
 *   run_id: string;
 *   status: string;
 *   progress: Record<string, string>;
 *   counters: RunStatusCounters;
 * }
 *
 * export function startPlanner(body: { project_id: string; one_liner: string }): Promise<PlannerStartResponse>
 * export function respondPlanner(sessionId: string, body: PlannerRespondRequest): Promise<PlannerRespondResponse>
 * export function getPlannerSession(sessionId: string): Promise<PlannerSessionDto>
 * export function startBookRun(body: BookRunRequest): Promise<BookRunResponse>
 * export function getBookRunStatus(runId: string): Promise<RunStatusResponse>
 *
 * 端点契约（S1a backend api/routers/books.py 实证，勿重新推断）：
 * - POST /api/v1/agent/books/planner（201）→ {session_id, round, questions, max_rounds}
 * - POST /api/v1/agent/books/planner/{session_id}/respond（200）→ {session_id, round, completed, questions, writing_plan}
 * - GET /api/v1/agent/books/planner/{session_id}（200）→ PlannerSession 全量
 * - POST /api/v1/agent/books/runs（202）→ {run_id, status}
 * - GET /api/v1/agent/books/runs/{run_id}（200）→ {run_id, status, progress, counters}
 *
 * ⚠️ F44 阶段3（#337 卷级 HITL）增量——GREEN 必须追加：
 *
 * export interface HitlPayload {
 *   question: string;
 *   volume_index?: number;
 *   progress?: Record<string, string>; // 卷边界：章 outline_id → done/failed
 *   failed?: string[];                  // 卷失败：failed 章列表
 * }
 * // RunStatusResponse 加可选键（向后兼容，勿改必填）：
 * //   waiting_hitl?: boolean; hitl_payload?: HitlPayload | null;
 * export interface ConfirmRunRequest { approved?: boolean; decision?: string; }
 * export interface ConfirmRunResponse {
 *   run_id: string;
 *   status: string;
 *   hitl_payload?: HitlPayload | null;
 * }
 * export function confirmBookRun(runId: string, body: ConfirmRunRequest): Promise<ConfirmRunResponse>
 *
 * 端点契约（S1a backend api/routers/books.py get_run_status/confirm_run + book_service 实证）：
 * - GET /runs/{id} 顶层可选键 waiting_hitl / hitl_payload（waiting_hitl 恒 = status==='waiting_hitl'）
 * - POST /runs/{id}/confirm（200）→ {run_id, status, hitl_payload?}
 *   body: ConfirmRunRequest {approved?: bool, decision?: str}；404 运行不存在 / 422 非 waiting_hitl
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  startPlanner,
  respondPlanner,
  getPlannerSession,
  startBookRun,
  getBookRunStatus,
  confirmBookRun,
} from './books';
import { apiFetch } from './client';

vi.mock('./client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const question1 = { id: 'q1', text: '题材：悬疑为主，还是悬疑+科幻混合？', template: '悬疑为主，但加入 ___ 元素' };

beforeEach(() => {
  apiFetchMock.mockReset();
});

describe('startPlanner — POST /planner', () => {
  it('透传 project_id + one_liner，返回第一轮问题', async () => {
    apiFetchMock.mockResolvedValue({
      session_id: 'sess-1',
      round: 1,
      questions: [question1],
      max_rounds: 5,
    });
    await startPlanner({ project_id: 'p1', one_liner: '写一本关于时间旅者的悬疑小说' });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/books/planner', {
      method: 'POST',
      body: { project_id: 'p1', one_liner: '写一本关于时间旅者的悬疑小说' },
    });
  });
});

describe('respondPlanner — POST /planner/{session_id}/respond', () => {
  it('提交 answers（按问题 id 逐键）', async () => {
    apiFetchMock.mockResolvedValue({
      session_id: 'sess-1',
      round: 2,
      completed: false,
      questions: [{ id: 'q4', text: '配角：需要几个主要配角？', template: '___ 个' }],
      writing_plan: null,
    });
    await respondPlanner('sess-1', { answers: { q1: '悬疑为主，加入时间悖论' } });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/books/planner/sess-1/respond', {
      method: 'POST',
      body: { answers: { q1: '悬疑为主，加入时间悖论' }, auto: false },
    });
  });

  it('auto=true 时不带 answers 键（全部你决定）', async () => {
    apiFetchMock.mockResolvedValue({
      session_id: 'sess-1',
      round: 1,
      completed: true,
      questions: [],
      writing_plan: {
        id: 'wp-1',
        project_id: 'p1',
        title: '写一本关于时间旅者的悬疑小说',
        status: 'auto',
        root_outline_id: null,
        character_ids: [],
        limits: { max_chapters: 1, max_agent_calls: 1 },
        progress: {},
        execution_refs: {},
        thread_id: null,
        created_at: '2026-08-17T10:00:00Z',
        updated_at: '2026-08-17T10:00:00Z',
      },
    });
    await respondPlanner('sess-1', { answers: {}, auto: true });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/books/planner/sess-1/respond', {
      method: 'POST',
      body: { answers: {}, auto: true },
    });
  });
});

describe('getPlannerSession — GET /planner/{session_id}', () => {
  it('返回会话全量（含 answers/authorized 快照）', async () => {
    apiFetchMock.mockResolvedValue({
      id: 'sess-1',
      project_id: 'p1',
      status: 'drafting',
      one_liner: '写一本关于时间旅者的悬疑小说',
      round: 2,
      asked_questions: [question1],
      answers: { q1: '悬疑为主' },
      authorized: ['配角自定'],
      writing_plan_id: null,
      created_at: '2026-08-17T10:00:00Z',
      updated_at: '2026-08-17T10:00:00Z',
    });
    await getPlannerSession('sess-1');
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/books/planner/sess-1');
  });
});

describe('startBookRun — POST /runs', () => {
  it('提交 writing_plan_id 启动书级运行（202 语义）', async () => {
    apiFetchMock.mockResolvedValue({ run_id: 'wp-1', status: 'completed' });
    await startBookRun({ writing_plan_id: 'wp-1' });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/books/runs', {
      method: 'POST',
      body: { writing_plan_id: 'wp-1' },
    });
  });
});

describe('getBookRunStatus — GET /runs/{run_id}', () => {
  it('返回运行状态（进度树 + 计数器）', async () => {
    apiFetchMock.mockResolvedValue({
      run_id: 'wp-1',
      status: 'completed',
      progress: { 'o-ch1': 'done' },
      counters: { max_chapters: 1, max_agent_calls: 1, agent_calls: 1, chapters_written: 1 },
    });
    await getBookRunStatus('wp-1');
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/books/runs/wp-1');
  });
});

describe('getBookRunStatus — 阶段2 counters 扩展（S2a #445 确认型：apiFetch 透传）', () => {
  it('返回 7 键 counters（max_tokens/tokens_used/tokens_warning 透传）', async () => {
    const counters = {
      max_chapters: 5,
      max_agent_calls: 10,
      agent_calls: 2,
      chapters_written: 1,
      max_tokens: 200000,
      tokens_used: 12345,
      tokens_warning: true,
    };
    apiFetchMock.mockResolvedValue({
      run_id: 'wp-1',
      status: 'running',
      progress: { 'o-c1': 'done' },
      counters,
    });
    const res = await getBookRunStatus('wp-1');
    // 透传断言（api 层零加工）；类型契约见文件头 docstring RunStatusCounters
    expect(res.counters.max_tokens).toBe(200000);
    expect(res.counters.tokens_used).toBe(12345);
    expect(res.counters.tokens_warning).toBe(true);
  });
});

describe('confirmBookRun — POST /runs/{run_id}/confirm（F44 阶段3 #337 卷级 HITL）', () => {
  it('approved=true 透传（卷边界确认，decision 省略）', async () => {
    apiFetchMock.mockResolvedValue({ run_id: 'wp-1', status: 'running' });
    await confirmBookRun('wp-1', { approved: true });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/books/runs/wp-1/confirm', {
      method: 'POST',
      body: { approved: true },
    });
  });

  it('带 decision 透传（卷失败恢复决策 continue）', async () => {
    apiFetchMock.mockResolvedValue({ run_id: 'wp-1', status: 'completed' });
    await confirmBookRun('wp-1', { approved: true, decision: 'continue' });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/books/runs/wp-1/confirm', {
      method: 'POST',
      body: { approved: true, decision: 'continue' },
    });
  });
});

describe('getBookRunStatus — 阶段3 HITL 字段透传（确认型：api 层零加工，RED 期即 PASS 刻意）', () => {
  it('waiting_hitl/hitl_payload 透传（卷边界形态）', async () => {
    apiFetchMock.mockResolvedValue({
      run_id: 'wp-1',
      status: 'waiting_hitl',
      progress: { 'o-c1': 'done' },
      counters: { max_chapters: 1, max_agent_calls: 1, agent_calls: 1, chapters_written: 1 },
      waiting_hitl: true,
      hitl_payload: { question: '确认继续下一卷？', volume_index: 0, progress: { 'o-c1': 'done' } },
    });
    const res = await getBookRunStatus('wp-1');
    // 透传断言（mock 返回啥函数透传啥，GREEN 零加工即可满足）
    expect(res.waiting_hitl).toBe(true);
    expect(res.hitl_payload?.question).toBe('确认继续下一卷？');
    expect(res.hitl_payload?.progress?.['o-c1']).toBe('done');
  });
});
