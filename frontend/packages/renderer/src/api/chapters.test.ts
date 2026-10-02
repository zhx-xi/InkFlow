/**
 * 章节列表「翻全量」helper（Issue #1407）—— RED 契约。
 *
 * 背景：后端 `GET /api/v1/projects/{pid}/chapters` 是**分页端点**
 * （默认 limit=50、上限 100；响应 {items,total,offset,limit}，
 * 见 backend/src/inkflow/api/routers/chapter.py）。前端裸请求只拿第一页 →
 * >50 章项目在**章节树 / 项目卡片进度 / AI 提取章节下拉**三处被静默截断
 * （#1407，与 #1374 同族）。
 *
 * 本文件钉 `src/api/chapters.ts` 的 `fetchAllChapters` 契约（GREEN 必须提供）：
 * - 签名：`fetchAllChapters(projectId: string): Promise<{ items: ChapterListDto[]; total: number }>`
 * - **首页不带 query**（保持既有端点形状，兼容既有 mock / 调用面）；续页
 *   `?offset=<已取条数>&limit=100`（limit = 后端上限）
 * - 累计 >= total 即停：total 恰为整页倍数（100/200）时**不多发请求、不死循环**
 * - total 缺失 → 按单页收口（`total ?? items.length` 兜底），不抛错
 * - 续页返回空 items（含缺 `items` 键）→ 立即停止（防 total 虚高死循环）
 * - 返回 `total` = 响应体 total（#1407 D3：项目卡片进度分母用服务端全量，非页内条数）
 *
 * RED 预期：GREEN 前 `src/api/chapters.ts` 不存在 → module-not-found（文件级失败）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { fetchAllChapters, restorePreviousContent, type ChapterListDto } from './chapters';
import { apiFetch } from './client';

vi.mock('./client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const CHAPTERS_PATH = '/api/v1/projects/p1/chapters';

/** 造 N 章元数据（前 written 章有正文）；标题用通用占位符 */
function makeChapters(count: number, written = 0): ChapterListDto[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `c${i}`,
    title: `第${i + 1}章 测试`,
    volume_id: null,
    order_index: i,
    word_count: i < written ? 1000 : 0,
  }));
}

/** 忠实模拟后端分页语义：空 query → offset=0/limit=50（后端默认）；带 query 按参数切片（limit 上限 100） */
function makePagingBackend(all: ChapterListDto[]) {
  const calls: string[] = [];
  const fetch = async (path: string) => {
    if (!path.startsWith(CHAPTERS_PATH)) throw new Error(`unexpected path: ${path}`);
    const rest = path.slice(CHAPTERS_PATH.length);
    if (rest !== '' && !rest.startsWith('?')) throw new Error(`unexpected path: ${path}`);
    calls.push(path);
    const qs = new URLSearchParams(rest);
    const offset = Number(qs.get('offset') ?? 0);
    const limit = Math.min(Number(qs.get('limit') ?? 50), 100);
    return { items: all.slice(offset, offset + limit), total: all.length, offset, limit };
  };
  return { fetch, calls };
}

beforeEach(() => {
  apiFetchMock.mockReset();
});

describe('fetchAllChapters — #1407 全量翻页契约', () => {
  it('【R】total=138、单页 50 → 取满 138 条（第 51 条起不丢），共 2 次请求', async () => {
    const backend = makePagingBackend(makeChapters(138));
    apiFetchMock.mockImplementation(backend.fetch);

    const res = await fetchAllChapters('p1');

    expect(res.items).toHaveLength(138);
    expect(res.total).toBe(138);
    expect(res.items[50].id).toBe('c50'); // 第 51 章（修复前不可见）
    expect(res.items[137].id).toBe('c137');
    expect(backend.calls).toEqual([
      CHAPTERS_PATH,
      `${CHAPTERS_PATH}?offset=50&limit=100`,
    ]);
  });

  it('【R】反例：total 恰为整页倍数（100）→ 取满且不发第 3 次请求（不死循环）', async () => {
    const backend = makePagingBackend(makeChapters(100));
    apiFetchMock.mockImplementation(backend.fetch);

    const res = await fetchAllChapters('p1');

    expect(res.items).toHaveLength(100);
    expect(res.total).toBe(100);
    expect(backend.calls).toHaveLength(2);
  });

  it('【R】反例：total 缺失 → 按单页收口（total 用 items.length 兜底），只发 1 次请求且不抛错', async () => {
    const page = makeChapters(50);
    apiFetchMock.mockImplementation(async () => ({ items: page }));

    const res = await fetchAllChapters('p1');

    expect(res.items).toHaveLength(50);
    expect(res.total).toBe(50);
    expect(apiFetchMock).toHaveBeenCalledTimes(1);
  });

  it('【R】反例：首页响应缺 items 键 → 空结果收口（total=0），不抛错', async () => {
    apiFetchMock.mockImplementation(async () => ({}));

    const res = await fetchAllChapters('p1');

    expect(res.items).toEqual([]);
    expect(res.total).toBe(0);
    expect(apiFetchMock).toHaveBeenCalledTimes(1);
  });

  it('【R】反例：total 虚高（138）但续页为空 → 立即停止（不死循环），已取条目保留', async () => {
    const first = makeChapters(50);
    let calls = 0;
    apiFetchMock.mockImplementation(async (path: string) => {
      calls += 1;
      // 硬上限：实现若不收敛（死循环）→ 立即显式失败而非挂到 vitest 超时
      if (calls > 5) throw new Error('fetchAllChapters 未收敛（疑似死循环）');
      return path === CHAPTERS_PATH
        ? { items: first, total: 138, offset: 0, limit: 50 }
        : { items: [], total: 138, offset: 50, limit: 100 };
    });

    const res = await fetchAllChapters('p1');

    expect(res.items).toHaveLength(50);
    expect(calls).toBe(2);
  });

  it('【R】反例：续页响应缺 items 键 → 立即停止（不死循环）', async () => {
    const first = makeChapters(50);
    let calls = 0;
    apiFetchMock.mockImplementation(async (path: string) => {
      calls += 1;
      if (calls > 5) throw new Error('fetchAllChapters 未收敛（疑似死循环）');
      return path === CHAPTERS_PATH ? { items: first, total: 138 } : {};
    });

    const res = await fetchAllChapters('p1');

    expect(res.items).toHaveLength(50);
    expect(calls).toBe(2);
  });

  it('【R】空项目（total=0）→ 单次请求返回空列表', async () => {
    const backend = makePagingBackend([]);
    apiFetchMock.mockImplementation(backend.fetch);

    const res = await fetchAllChapters('p1');

    expect(res.items).toEqual([]);
    expect(res.total).toBe(0);
    expect(backend.calls).toHaveLength(1);
  });
});

/**
 * #1440 恢复上一稿（GUI 入口接线）：契约面 = POST /api/v1/chapters/{id}/restore-previous。
 *
 * 后端（#1430 A2，已合入）语义：previous_content 写回 content（content ⇄ previous_content 互换）。
 * 本封装**无请求体**；错误映射交由调用方（apiFetch 已抛 ApiError：404 章不存在 / 409 无可恢复旧稿）。
 */
describe('restorePreviousContent — #1440 恢复上一稿封装', () => {
  it('POST /api/v1/chapters/{id}/restore-previous（无请求体）→ 返回章 JSON', async () => {
    const restored = {
      id: 'c1',
      title: '第1章 初见',
      volume_id: null,
      order_index: 0,
      word_count: 10,
      content: '旧稿',
      previous_content: '新稿',
    };
    apiFetchMock.mockResolvedValue(restored);

    const res = await restorePreviousContent('c1');

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/chapters/c1/restore-previous', {
      method: 'POST',
    });
    expect(res).toEqual(restored);
  });
});

