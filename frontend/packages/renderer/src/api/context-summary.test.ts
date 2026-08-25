/**
 * 章节摘要 API 契约测试（T3 章节摘要）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须在 src/api/context.ts 尾部追加（不改既有 assembleContext）：
 *
 * export interface ChapterSummaryDto { summary: string; chapter_id: string; }
 * export async function getChapterSummary(chapterId: string): Promise<ChapterSummaryDto>
 *   → GET /api/v1/context/chapters/{chapterId}/summary
 * export async function refreshChapterSummary(chapterId: string): Promise<ChapterSummaryDto>
 *   → POST /api/v1/context/chapters/{chapterId}/summary/refresh（无 body）
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { getChapterSummary, refreshChapterSummary } from './context';
import { apiFetch } from './client';

vi.mock('./client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

beforeEach(() => {
  apiFetchMock.mockReset();
});

/** 与后端 DTO 对齐的完整章节摘要对象 */
const summaryDto = {
  summary: '第3章：少年雨夜渡口收信…',
  chapter_id: 'c1',
};

describe('context API — getChapterSummary（获取章节摘要）', () => {
  it('按 chapterId 查询 → GET /api/v1/context/chapters/{id}/summary', async () => {
    apiFetchMock.mockResolvedValue(summaryDto as never);
    await getChapterSummary('c1');
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/context/chapters/c1/summary');
  });

  it('返回完整 ChapterSummaryDto', async () => {
    apiFetchMock.mockResolvedValue(summaryDto as never);
    await expect(getChapterSummary('c1')).resolves.toEqual(summaryDto);
  });
});

describe('context API — refreshChapterSummary（刷新章节摘要）', () => {
  it('→ POST /api/v1/context/chapters/{id}/summary/refresh（无 body）', async () => {
    apiFetchMock.mockResolvedValue(summaryDto as never);
    await refreshChapterSummary('c1');
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/context/chapters/c1/summary/refresh', {
      method: 'POST',
    });
  });

  it('返回完整 ChapterSummaryDto', async () => {
    apiFetchMock.mockResolvedValue(summaryDto as never);
    await expect(refreshChapterSummary('c1')).resolves.toEqual(summaryDto);
  });
});
