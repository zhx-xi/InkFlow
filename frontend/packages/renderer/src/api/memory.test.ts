/**
 * #486 会话/记忆 UI — 记忆 API 契约测试（F28 agent memory 端点消费）
 *
 * ⚠️ 本文件 = 契约。GREEN 新建 src/api/memory.ts，必须导出：
 * - interface MemorySummaryDto { content: string; anchor_hash: string;
 *   anchor_count: number; model: string; updated_at: string }
 * - interface MemorySummariesResponse { project_id: string;
 *   project: MemorySummaryDto | null; user: MemorySummaryDto | null }
 * - fetchMemorySummaries(projectId: string): Promise<MemorySummariesResponse>
 *   → GET /api/v1/agent/memory/summaries?project_id=
 * - interface SummarizeMemoryResponse { project_id: string; summarized: boolean;
 *   project: MemorySummaryDto | null; user: MemorySummaryDto | null }
 * - summarizeMemory(projectId: string, force?: boolean): Promise<SummarizeMemoryResponse>
 *   → POST /api/v1/agent/memory/summarize?project_id=&force=（force 缺省不携带；显式 true 携带）
 * - interface ProjectPreferenceDto { id: string; project_id: string; category: string;
 *   pattern: string; value: string; confidence: number; count: number;
 *   source_events: string[]; created_at: string; updated_at: string }
 * - interface UserPreferenceDto { id: string; category: string; pattern: string;
 *   value: string; confidence: number; count: number; project_count: number;
 *   source_projects: string[]; source_events: string[]; created_at: string; updated_at: string }
 * - interface PreferencesResponse<T = ProjectPreferenceDto> { items: T[]; total: number }
 * - fetchProjectPreferences(projectId: string): Promise<PreferencesResponse>
 *   → GET /api/v1/agent/preferences?project_id=
 * - removeProjectPreference(preferenceId: string): Promise<void>
 *   → DELETE /api/v1/agent/preferences/{id}
 * - fetchUserPreferences(): Promise<PreferencesResponse<UserPreferenceDto>>
 *   → GET /api/v1/agent/user-preferences
 * - removeUserPreference(preferenceId: string): Promise<void>
 *   → DELETE /api/v1/agent/user-preferences/{id}
 *
 * #521 追加（2026-08-20 拍板：手动添加/编辑记忆）：
 * - interface PreferenceInput { category: string; pattern: string; value: string }
 * - createProjectPreference(projectId: string, input: PreferenceInput): Promise<ProjectPreferenceDto>
 *   → POST /api/v1/agent/preferences，body { project_id: projectId, ...input }
 * - createUserPreference(input: PreferenceInput): Promise<UserPreferenceDto>
 *   → POST /api/v1/agent/user-preferences，body input（无 project_id）
 * - updateProjectPreference(preferenceId: string, input: PreferenceInput): Promise<ProjectPreferenceDto>
 *   → PATCH /api/v1/agent/preferences/{preferenceId}，body input
 * - updateUserPreference(preferenceId: string, input: PreferenceInput): Promise<UserPreferenceDto>
 *   → PATCH /api/v1/agent/user-preferences/{preferenceId}，body input
 *
 * 测试策略：镜像 api/search.test.ts —— 不 mock ../api/client，直接 spy 全局 fetch。
 *
 * RED 预期：./memory 模块不存在 → 收集期 module-not-found（类 1 契约缺口）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from './client';
import {
  createProjectPreference,
  createUserPreference,
  fetchMemorySummaries,
  fetchProjectPreferences,
  fetchUserPreferences,
  removeProjectPreference,
  removeUserPreference,
  summarizeMemory,
  updateProjectPreference,
  updateUserPreference,
} from './memory';

const BASE = 'http://api.test';
const PID = '3f2e1d4a-0000-4000-8000-000000000002';
const PREF_ID = '3f2e1d4a-0000-4000-8000-000000000003';

const summaryDto = {
  content: '用户偏好使用「低声道」替代「说」，主角称呼为林晚。',
  anchor_hash: 'abc123',
  anchor_count: 3,
  model: 'deepseek-v4-flash',
  updated_at: '2026-08-10T08:00:00Z',
};

const prefDto = {
  id: PREF_ID,
  project_id: PID,
  category: 'style_word',
  pattern: '说',
  value: '低声道',
  confidence: 0.75,
  count: 3,
  source_events: ['ev1', 'ev2', 'ev3'],
  created_at: '2026-08-10T08:00:00Z',
  updated_at: '2026-08-10T08:00:00Z',
};

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

describe('记忆总结 — summaries / summarize', () => {
  it('fetchMemorySummaries → GET /api/v1/agent/memory/summaries?project_id=', async () => {
    mockFetchOnce({ project_id: PID, project: summaryDto, user: null });
    const result = await fetchMemorySummaries(PID);

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(init?.method).toBe('GET');
    const parsed = new URL(String(url));
    expect(parsed.pathname).toBe('/api/v1/agent/memory/summaries');
    expect(parsed.searchParams.get('project_id')).toBe(PID);
    expect(result.project?.content).toContain('低声道');
    expect(result.project?.anchor_count).toBe(3);
    expect(result.user).toBeNull();
  });

  it('summarizeMemory(force=true) → POST summarize?project_id=&force=true（提取记忆入口）', async () => {
    mockFetchOnce({ project_id: PID, summarized: true, project: summaryDto, user: null });
    const result = await summarizeMemory(PID, true);

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(init?.method).toBe('POST');
    const parsed = new URL(String(url));
    expect(parsed.pathname).toBe('/api/v1/agent/memory/summarize');
    expect(parsed.searchParams.get('project_id')).toBe(PID);
    expect(parsed.searchParams.get('force')).toBe('true');
    expect(result.summarized).toBe(true);
    expect(result.project?.model).toBe('deepseek-v4-flash');
  });

  it('summarizeMemory 缺省 force 不携带', async () => {
    mockFetchOnce({ project_id: PID, summarized: false, project: null, user: null });
    await summarizeMemory(PID);
    const url = new URL(String(vi.mocked(fetch).mock.calls[0][0]));
    expect(url.searchParams.has('force')).toBe(false);
  });
});

describe('偏好 — 项目级 / 用户级', () => {
  it('fetchProjectPreferences → GET /api/v1/agent/preferences?project_id=（items/total 解析）', async () => {
    mockFetchOnce({ items: [prefDto], total: 1 });
    const result = await fetchProjectPreferences(PID);

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(init?.method).toBe('GET');
    const parsed = new URL(String(url));
    expect(parsed.pathname).toBe('/api/v1/agent/preferences');
    expect(parsed.searchParams.get('project_id')).toBe(PID);
    expect(result.total).toBe(1);
    expect(result.items[0].pattern).toBe('说');
    expect(result.items[0].value).toBe('低声道');
    expect(result.items[0].category).toBe('style_word');
  });

  it('removeProjectPreference → DELETE /api/v1/agent/preferences/{id}', async () => {
    mockFetchOnce({ preference_id: PREF_ID, deleted: true });
    await removeProjectPreference(PREF_ID);

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(init?.method).toBe('DELETE');
    expect(new URL(String(url)).pathname).toBe(`/api/v1/agent/preferences/${PREF_ID}`);
  });

  it('fetchUserPreferences → GET /api/v1/agent/user-preferences（UserPreference 字段解析）', async () => {
    const userPref = {
      id: 'up-1',
      category: 'addressing',
      pattern: '她',
      value: '林晚',
      confidence: 0.8,
      count: 4,
      project_count: 2,
      source_projects: [PID, 'p2'],
      source_events: ['ev1'],
      created_at: '2026-08-10T08:00:00Z',
      updated_at: '2026-08-10T08:00:00Z',
    };
    mockFetchOnce({ items: [userPref], total: 1 });
    const result = await fetchUserPreferences();

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(init?.method).toBe('GET');
    expect(new URL(String(url)).pathname).toBe('/api/v1/agent/user-preferences');
    expect(result.total).toBe(1);
    expect(result.items[0].project_count).toBe(2);
    expect(result.items[0].value).toBe('林晚');
  });

  it('removeUserPreference → DELETE /api/v1/agent/user-preferences/{id}', async () => {
    mockFetchOnce({ preference_id: 'up-1', deleted: true });
    await removeUserPreference('up-1');

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(init?.method).toBe('DELETE');
    expect(new URL(String(url)).pathname).toBe('/api/v1/agent/user-preferences/up-1');
  });

  it('HTTP 非 2xx → ApiError（404 透传）', async () => {
    mockFetchOnce({ detail: '偏好不存在' }, 404);
    await expect(fetchProjectPreferences(PID)).rejects.toBeInstanceOf(ApiError);
  });
});

describe('偏好 — 手动添加 / 编辑（#521）', () => {
  it('createProjectPreference → POST /api/v1/agent/preferences，body 含 project_id + category/pattern/value', async () => {
    mockFetchOnce({ ...prefDto, id: 'pref-new' });
    const input = { category: 'addressing', pattern: '她', value: '林晚' };
    const result = await createProjectPreference(PID, input);

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(init?.method).toBe('POST');
    expect(new URL(String(url)).pathname).toBe('/api/v1/agent/preferences');
    expect(JSON.parse(String(init?.body))).toEqual({ project_id: PID, ...input });
    expect(result.project_id).toBe(PID);
    expect(result.pattern).toBe('说');
  });

  it('createUserPreference → POST /api/v1/agent/user-preferences，body 无 project_id', async () => {
    mockFetchOnce({
      id: 'upref-new',
      category: 'style_word',
      pattern: '说',
      value: '低声道',
      confidence: 0.7,
      count: 1,
      project_count: 1,
      source_projects: [PID],
      source_events: [],
      created_at: '2026-08-20T08:00:00Z',
      updated_at: '2026-08-20T08:00:00Z',
    });
    const input = { category: 'style_word', pattern: '说', value: '低声道' };
    const result = await createUserPreference(input);

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(init?.method).toBe('POST');
    expect(new URL(String(url)).pathname).toBe('/api/v1/agent/user-preferences');
    expect(JSON.parse(String(init?.body))).toEqual(input);
    expect(result.value).toBe('低声道');
  });

  it('updateProjectPreference → PATCH /api/v1/agent/preferences/{id}，body = input', async () => {
    mockFetchOnce({ ...prefDto, value: '轻声道' });
    const input = { category: 'style_word', pattern: '说', value: '轻声道' };
    const result = await updateProjectPreference(PREF_ID, input);

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(init?.method).toBe('PATCH');
    expect(new URL(String(url)).pathname).toBe(`/api/v1/agent/preferences/${PREF_ID}`);
    expect(JSON.parse(String(init?.body))).toEqual(input);
    expect(result.value).toBe('轻声道');
  });

  it('updateUserPreference → PATCH /api/v1/agent/user-preferences/{id}，body = input', async () => {
    mockFetchOnce({
      id: 'up-1',
      category: 'addressing',
      pattern: '她',
      value: '晚晚',
      confidence: 0.8,
      count: 4,
      project_count: 2,
      source_projects: [PID, 'p2'],
      source_events: ['ev1'],
      created_at: '2026-08-10T08:00:00Z',
      updated_at: '2026-08-20T09:00:00Z',
    });
    const input = { category: 'addressing', pattern: '她', value: '晚晚' };
    const result = await updateUserPreference('up-1', input);

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(init?.method).toBe('PATCH');
    expect(new URL(String(url)).pathname).toBe('/api/v1/agent/user-preferences/up-1');
    expect(JSON.parse(String(init?.body))).toEqual(input);
    expect(result.value).toBe('晚晚');
  });
});
