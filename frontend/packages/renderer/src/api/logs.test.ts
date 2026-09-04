/**
 * #496 统一日志页 API 契约测试（RED）——contract-496.md §5。
 *
 * ⚠️ 本文件 = 契约。GREEN 新建 src/api/logs.ts（镜像 api/search.ts 形态：
 * apiFetch + URLSearchParams，缺省参数不携带），必须导出：
 * - interface LogRecordDto / LogsQueryParams / LogsResponseDto（字段见 §5）
 * - fetchLogs(params: LogsQueryParams): Promise<LogsResponseDto>
 *   → GET /api/v1/logs?<qs>，后端 F7 信封 {ok,data} —— 解包 data 返回
 *     （实现：const env = await apiFetch<{ok:boolean;data:LogsResponseDto}>(url); return env.data）
 * - fetchLogMessages(lng: string): Promise<Record<string, string>>
 *   → GET /api/v1/i18n/messages?lng=<encodeURIComponent(lng)> → env.data
 *
 * URL 序列化契约（§5，RED 断言 fetch URL）：
 * - level / caller_type / project_id / from / to / q / correlation_id 仅非空携带
 *   （undefined 与空串都不携带）；
 * - page / limit 仅在传入时携带：page=0 不携带（后端默认 0/50），page>0 显式携带；
 *   limit 页面固定传 50；
 * - project_id 传前端项目 UUID 串原样（URLSearchParams encode）。
 *
 * 测试策略：不 mock ./client（#107 vi.mock 闭包坑）——直接 stub 全局 fetch，
 * apiFetch 真实执行；window.INKFLOW_API 注入固定 baseURL/token
 * （镜像 api/client.test.ts / api/logging.test.ts / search.test.ts 形态）。
 * URL 用 new URL 解析 searchParams 精确断言（中文参数 decode 后等价）。
 *
 * RED 预期：./logs 模块不存在 → 收集期 module-not-found（类 1 契约缺口，
 * GREEN 建文件即愈）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from './client';
import { fetchLogMessages, fetchLogs } from './logs';

const BASE = 'http://api.test';

/** GET /logs 响应 data（结构镜像 §5 LogsResponseDto + LogRecordDto 子集） */
const logsData = {
  items: [
    {
      timestamp: '2026-09-04T01:00:00.000Z',
      level: 'INFO',
      logger: 'renderer',
      caller_type: 'frontend',
      caller_name: 'WritingPage',
      event: 'create_chapter',
      message_key: 'log.event.create_chapter',
      params: { title: '第一章' },
      correlation_id: '',
    },
  ],
  total: 120,
  offset: 0,
  limit: 50,
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

describe('fetchLogs — URL 序列化（§5）', () => {
  it('【R】全参拼入 GET /api/v1/logs：level/caller_type/project_id/from/to/q/correlation_id/page/limit', async () => {
    mockFetchOnce({ ok: true, data: logsData });
    await fetchLogs({
      level: 'INFO,WARN,ERROR',
      caller_type: 'api,agent,tool,cli,mcp',
      project_id: 'u-1',
      from: '2026-09-01T08:00',
      to: '2026-09-02T08:00',
      q: '崩溃',
      correlation_id: 'c-42',
      page: 2,
      limit: 50,
    });

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(init?.method).toBe('GET');
    const parsed = new URL(String(url));
    expect(parsed.pathname).toBe('/api/v1/logs');
    expect(parsed.searchParams.get('level')).toBe('INFO,WARN,ERROR');
    expect(parsed.searchParams.get('caller_type')).toBe('api,agent,tool,cli,mcp');
    expect(parsed.searchParams.get('project_id')).toBe('u-1');
    expect(parsed.searchParams.get('from')).toBe('2026-09-01T08:00');
    expect(parsed.searchParams.get('to')).toBe('2026-09-02T08:00');
    expect(parsed.searchParams.get('q')).toBe('崩溃'); // encodeURIComponent 后解码等价
    expect(parsed.searchParams.get('correlation_id')).toBe('c-42');
    expect(parsed.searchParams.get('page')).toBe('2');
    expect(parsed.searchParams.get('limit')).toBe('50');
  });

  it('【R】仅非空携带：空串参数不携带、page=0 不携带（后端默认 0/50）', async () => {
    mockFetchOnce({ ok: true, data: logsData });
    await fetchLogs({
      level: 'INFO,WARN,ERROR',
      limit: 50,
      page: 0,
      q: '',
      correlation_id: '',
      from: '',
      to: '',
    });

    const url = new URL(String(vi.mocked(fetch).mock.calls[0][0]));
    expect(url.searchParams.get('level')).toBe('INFO,WARN,ERROR');
    expect(url.searchParams.get('limit')).toBe('50');
    expect(url.searchParams.has('page')).toBe(false);
    expect(url.searchParams.has('q')).toBe(false);
    expect(url.searchParams.has('correlation_id')).toBe(false);
    expect(url.searchParams.has('from')).toBe(false);
    expect(url.searchParams.has('to')).toBe(false);
  });

  it('【R】空参数对象 → 无任何 query 参数（后端全默认）', async () => {
    mockFetchOnce({ ok: true, data: logsData });
    await fetchLogs({});

    const url = new URL(String(vi.mocked(fetch).mock.calls[0][0]));
    expect([...url.searchParams.keys()]).toEqual([]);
  });

  it('【R】page>0 显式携带：page:1 → URL page=1（limit 仍传 50）', async () => {
    mockFetchOnce({ ok: true, data: logsData });
    await fetchLogs({ page: 1, limit: 50 });

    const url = new URL(String(vi.mocked(fetch).mock.calls[0][0]));
    expect(url.searchParams.get('page')).toBe('1');
    expect(url.searchParams.get('limit')).toBe('50');
  });
});

describe('fetchLogs — F7 信封解包（§5）', () => {
  it('【R】响应 {ok:true,data:{items,total,offset,limit}} → 解包返回 data', async () => {
    mockFetchOnce({ ok: true, data: logsData });
    const result = await fetchLogs({ limit: 50, page: 0 });

    expect(result.total).toBe(120);
    expect(result.offset).toBe(0);
    expect(result.limit).toBe(50);
    expect(result.items).toHaveLength(1);
    expect(result.items[0].message_key).toBe('log.event.create_chapter');
    // 返回的是 data 而非信封本身（无 ok 字段透传）
    expect(result).not.toHaveProperty('ok');
  });

  it('【R】HTTP 非 2xx → ApiError（status/detail 透传，apiFetch 统一错误面）', async () => {
    mockFetchOnce({ detail: '查询参数非法' }, 422);
    await expect(fetchLogs({})).rejects.toBeInstanceOf(ApiError);
    try {
      await fetchLogs({});
    } catch (e) {
      expect((e as ApiError).status).toBe(422);
      expect((e as ApiError).detail).toBe('查询参数非法');
    }
  });
});

describe('fetchLogMessages — 远端消息目录拉取（§5）', () => {
  it('【R】GET /api/v1/i18n/messages?lng=<lng> → env.data 解包', async () => {
    const remoteDir = { 'log.event.create_chapter': '远端模板 {title}' };
    mockFetchOnce({ ok: true, data: remoteDir });
    const result = await fetchLogMessages('en');

    const url = new URL(String(vi.mocked(fetch).mock.calls[0][0]));
    expect(url.pathname).toBe('/api/v1/i18n/messages');
    expect(url.searchParams.get('lng')).toBe('en');
    expect(result).toEqual(remoteDir);
  });

  it('【R】lng 经 URLSearchParams 编码（zh 语言码往返等价）', async () => {
    mockFetchOnce({ ok: true, data: {} });
    await fetchLogMessages('zh');

    const raw = String(vi.mocked(fetch).mock.calls[0][0]);
    const url = new URL(raw);
    expect(url.searchParams.get('lng')).toBe('zh');
    expect(url.searchParams.toString()).toBe('lng=zh');
  });
});
