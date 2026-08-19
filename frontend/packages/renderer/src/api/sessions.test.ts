/**
 * #486 会话/记忆 UI — 会话 API 契约测试（F24 sessions + F44 PlannerSession 列表）
 *
 * ⚠️ 本文件 = 契约。GREEN 新建 src/api/sessions.ts，必须导出：
 * - interface SessionDto { id: string; session_type: string; status: string;
 *   project_id: string | null; title: string; description: string;
 *   context: Record<string, unknown>; result: Record<string, unknown>; error: string;
 *   started_at: string; paused_at: string | null; completed_at: string | null;
 *   is_deleted: boolean; created_at: string; updated_at: string }
 * - interface SessionViewDto { session: SessionDto; log_count: number;
 *   last_log: { id: string; session_id: string; seq: number; level: string;
 *   message: string; payload: Record<string, unknown>; created_at: string } | null }
 * - interface SessionListResponse { items: SessionViewDto[]; total: number; offset: number; limit: number }
 * - interface FetchSessionsParams { includeDeleted?: boolean; sessionType?: string;
 *   status?: string; limit?: number; offset?: number }
 * - fetchSessions(params: FetchSessionsParams): Promise<SessionListResponse>
 *   → GET /api/v1/sessions?include_deleted=&session_type=&status=&limit=&offset=
 *   （includeDeleted/session_type/status 显式携带；limit/offset 缺省不携带）
 * - archiveSession(sessionId: string): Promise<void>
 *   → DELETE /api/v1/sessions/{id}（无 force 查询参数 = 归档语义，204）
 * - deleteSession(sessionId: string): Promise<void>
 *   → DELETE /api/v1/sessions/{id}?force=true（真实删除，204）
 * - restoreSession(sessionId: string): Promise<SessionDto>
 *   → POST /api/v1/sessions/{id}/restore（解除归档 → Session）
 * - interface PlannerSessionDto { id: string; project_id: string; status: string;
 *   one_liner: string; round: number; asked_questions: PlannerQuestion[];
 *   answers: Record<string, string>; authorized: string[];
 *   confirmed_items?: ConfirmedItem[]; conflicts?: ConflictRecord[]; confirming?: boolean;
 *   writing_plan_id: string | null; created_at: string; updated_at: string }
 *   （PlannerQuestion/ConfirmedItem/ConflictRecord 复用 src/api/books.ts 导出）
 * - fetchPlannerSessions(params?: { projectId?: string; status?: string; limit?: number; offset?: number })
 *   → GET /api/v1/agent/books/planner?project_id=&status=&limit=&offset=
 *   （可选参数缺省不携带）→ PlannerSessionListResponse { items, total, offset, limit }
 *
 * 测试策略：镜像 api/search.test.ts —— 不 mock ../api/client，直接 spy 全局 fetch
 * （apiFetch 真实执行），window.INKFLOW_API 注入固定 baseURL/token。
 *
 * RED 预期：./sessions 模块不存在 → 收集期 module-not-found（类 1 契约缺口）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from './client';
import {
  archiveSession,
  deleteSession,
  fetchPlannerSessions,
  fetchSessions,
  restoreSession,
} from './sessions';

const BASE = 'http://api.test';
const SID = '3f2e1d4a-0000-4000-8000-000000000001';

/** 契约结构镜像（GREEN 类型从 sessions.ts 导出；本文件内联镜像供 mock 播种） */
interface SessionDto {
  id: string;
  session_type: string;
  status: string;
  project_id: string | null;
  title: string;
  description: string;
  context: Record<string, unknown>;
  result: Record<string, unknown>;
  error: string;
  started_at: string;
  paused_at: string | null;
  completed_at: string | null;
  is_deleted: boolean;
  created_at: string;
  updated_at: string;
}

interface SessionViewDto {
  session: SessionDto;
  log_count: number;
  last_log: { id: string; session_id: string; seq: number; level: string; message: string; payload: Record<string, unknown>; created_at: string } | null;
}

const sessionDto: SessionDto = {
  id: SID,
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
};

const sessionViewDto: SessionViewDto = { session: sessionDto, log_count: 2, last_log: null };

function mockFetchOnce(body: unknown, status = 200): void {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    }),
  );
}

beforeEach(() => {
  Object.defineProperty(window, 'INKFLOW_API', {
    configurable: true,
    value: { baseURL: BASE, token: 'test-token' },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('fetchSessions — URL 拼装', () => {
  it('includeDeleted=true / sessionType / status / limit / offset 拼入 URL', async () => {
    mockFetchOnce({ items: [sessionViewDto], total: 1, offset: 0, limit: 20 });
    await fetchSessions({
      includeDeleted: true,
      sessionType: 'writing',
      status: 'completed',
      limit: 20,
      offset: 10,
    });

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(init?.method).toBe('GET');
    expect(String(url)).toContain(`${BASE}/api/v1/sessions?`);
    const parsed = new URL(String(url));
    expect(parsed.pathname).toBe('/api/v1/sessions');
    expect(parsed.searchParams.get('include_deleted')).toBe('true');
    expect(parsed.searchParams.get('session_type')).toBe('writing');
    expect(parsed.searchParams.get('status')).toBe('completed');
    expect(parsed.searchParams.get('limit')).toBe('20');
    expect(parsed.searchParams.get('offset')).toBe('10');
  });

  it('缺省参数不携带（include_deleted 默认后端 False；limit/offset 后端默认 50/0）', async () => {
    mockFetchOnce({ items: [], total: 0, offset: 0, limit: 50 });
    await fetchSessions({});

    const url = new URL(String(vi.mocked(fetch).mock.calls[0][0]));
    expect(url.searchParams.has('include_deleted')).toBe(false);
    expect(url.searchParams.has('session_type')).toBe(false);
    expect(url.searchParams.has('limit')).toBe(false);
    expect(url.searchParams.has('offset')).toBe(false);
  });
});

describe('fetchSessions — 响应解析与错误契约', () => {
  it('响应解析：items[0].session.title / log_count / total', async () => {
    mockFetchOnce({ items: [sessionViewDto], total: 1, offset: 0, limit: 50 });
    const result = await fetchSessions({ includeDeleted: true });
    expect(result.total).toBe(1);
    expect(result.items[0].session.title).toBe('第三章续写');
    expect(result.items[0].log_count).toBe(2);
    expect(result.items[0].session.is_deleted).toBe(false);
  });

  it('HTTP 非 2xx → ApiError（status/detail 透传）', async () => {
    mockFetchOnce({ detail: '会话不存在' }, 404);
    await expect(fetchSessions({})).rejects.toBeInstanceOf(ApiError);
    try {
      await fetchSessions({});
    } catch (e) {
      expect((e as ApiError).status).toBe(404);
      expect((e as ApiError).detail).toBe('会话不存在');
    }
  });
});

describe('archiveSession / deleteSession / restoreSession — 归档删除 wire', () => {
  it('archiveSession → DELETE /api/v1/sessions/{id}（无 force 参数 = 归档）', async () => {
    mockFetchOnce(null, 204);
    await archiveSession(SID);

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(init?.method).toBe('DELETE');
    expect(new URL(String(url)).pathname).toBe(`/api/v1/sessions/${SID}`);
    expect(new URL(String(url)).searchParams.has('force')).toBe(false);
  });

  it('deleteSession → DELETE /api/v1/sessions/{id}?force=true（真实删除）', async () => {
    mockFetchOnce(null, 204);
    await deleteSession(SID);

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(init?.method).toBe('DELETE');
    const parsed = new URL(String(url));
    expect(parsed.pathname).toBe(`/api/v1/sessions/${SID}`);
    expect(parsed.searchParams.get('force')).toBe('true');
  });

  it('restoreSession → POST /api/v1/sessions/{id}/restore → SessionDto', async () => {
    mockFetchOnce({ ...sessionDto, is_deleted: false });
    const restored = await restoreSession(SID);

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(init?.method).toBe('POST');
    expect(new URL(String(url)).pathname).toBe(`/api/v1/sessions/${SID}/restore`);
    expect(restored.is_deleted).toBe(false);
    expect(restored.title).toBe('第三章续写');
  });
});

describe('fetchPlannerSessions — 访谈会话列表', () => {
  const plannerItem = {
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
  };

  it('GET /api/v1/agent/books/planner（projectId/status/limit 拼入 URL，缺省不携带）', async () => {
    mockFetchOnce({ items: [plannerItem], total: 1, offset: 0, limit: 50 });
    await fetchPlannerSessions({ projectId: 'p1', status: 'completed', limit: 20 });

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(init?.method).toBe('GET');
    const parsed = new URL(String(url));
    expect(parsed.pathname).toBe('/api/v1/agent/books/planner');
    expect(parsed.searchParams.get('project_id')).toBe('p1');
    expect(parsed.searchParams.get('status')).toBe('completed');
    expect(parsed.searchParams.get('limit')).toBe('20');

    mockFetchOnce({ items: [], total: 0, offset: 0, limit: 50 });
    await fetchPlannerSessions();
    const parsed2 = new URL(String(vi.mocked(fetch).mock.calls[0][0]));
    expect(parsed2.searchParams.has('project_id')).toBe(false);
    expect(parsed2.searchParams.has('status')).toBe(false);
  });

  it('响应解析：items[0].one_liner / status / writing_plan_id', async () => {
    mockFetchOnce({ items: [plannerItem], total: 1, offset: 0, limit: 50 });
    const result = await fetchPlannerSessions();
    expect(result.total).toBe(1);
    expect(result.items[0].one_liner).toBe('仙侠长篇 80 万字');
    expect(result.items[0].status).toBe('drafting');
    expect(result.items[0].writing_plan_id).toBeNull();
  });
});