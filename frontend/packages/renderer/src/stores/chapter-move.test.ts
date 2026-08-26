/**
 * chapter store moveChapter 契约测试（Issue #674 章节拖拽归卷，RED 阶段）
 *
 * GREEN 实现必须为 src/stores/chapter.ts 新增 moveChapter 并并入 ChapterState：
 * - moveChapter(chapterId: string, targetVolumeId: string | null): Promise<ChapterMeta>
 *     POST /api/v1/chapters/{chapterId}/move?target_volume_id={targetVolumeId}
 *     （targetVolumeId 为 null → 不带 query，章节置为无卷归属）
 *     → 成功后把返回的 Chapter 按 id 替换进 chapters 列表
 *
 * ⚠️ 后端真实端点（backend/src/inkflow/api/routers/chapter.py L175）为
 *    POST /chapters/{id}/move?target_volume_id=，返回 ch.model_dump(mode="json")。
 *    任务书里「PATCH /chapters/{id}/move」是笔误，契约按 POST 写。
 *
 * 测试方法镜像 chapter-volumes.test.ts：vi.mock('../api/client') 替换 apiFetch + act() 包裹 store action。
 * RED 期 store 尚无 moveChapter → 用本地 ChapterMoveActions 契约签名访问（GREEN 并入 ChapterState 后自然匹配）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act } from '@testing-library/react';
import { useChapterStore } from './chapter';
import { apiFetch } from '../api/client';
import type { ChapterMeta } from './chapter';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

/** RED 期契约签名（GREEN 实现并入 ChapterState 后此接口即被满足） */
interface ChapterMoveActions {
  moveChapter: (chapterId: string, targetVolumeId: string | null) => Promise<ChapterMeta>;
}

const actions = () => useChapterStore.getState() as unknown as ChapterMoveActions;

const chapters: ChapterMeta[] = [
  { id: 'c1', title: '第1章 初见', volume_id: 'v1', order_index: 0, word_count: 2347 },
  { id: 'c2', title: '第2章 夜谈', volume_id: null, order_index: 1, word_count: 0 },
];

beforeEach(() => {
  apiFetchMock.mockReset();
  useChapterStore.setState({
    volumes: [],
    chapters: [],
    currentChapterId: null,
    content: '',
    loading: false,
    error: null,
    treeProjectId: null,
  });
});

describe('chapter store — moveChapter 契约面（#674 拖拽归卷，GREEN 必须提供）', () => {
  it('暴露 moveChapter(chapterId, targetVolumeId) action（function 类型）', () => {
    const a = actions();
    expect(typeof a.moveChapter).toBe('function');
  });
});

describe('chapter store — moveChapter 调用契约', () => {
  it('POST /chapters/{id}/move?target_volume_id={v} → 按 id 替换 chapters 中该章 volume_id', async () => {
    const updated: ChapterMeta = { id: 'c2', title: '第2章 夜谈', volume_id: 'v1', order_index: 1, word_count: 0 };
    apiFetchMock.mockResolvedValue(updated);
    useChapterStore.setState({ chapters });

    await act(async () => {
      await actions().moveChapter('c2', 'v1');
    });

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/chapters/c2/move?target_volume_id=v1', {
      method: 'POST',
    });
    const s = useChapterStore.getState();
    expect(s.chapters.find((c) => c.id === 'c2')?.volume_id).toBe('v1');
    expect(s.chapters.find((c) => c.id === 'c1')?.volume_id).toBe('v1'); // c1 不受影响
  });

  it('targetVolumeId 为 null → 不带 query（章节置为无卷归属）', async () => {
    const updated: ChapterMeta = { id: 'c1', title: '第1章 初见', volume_id: null, order_index: 0, word_count: 2347 };
    apiFetchMock.mockResolvedValue(updated);
    useChapterStore.setState({ chapters });

    await act(async () => {
      await actions().moveChapter('c1', null);
    });

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/chapters/c1/move', { method: 'POST' });
    expect(useChapterStore.getState().chapters.find((c) => c.id === 'c1')?.volume_id).toBeNull();
    expect(useChapterStore.getState().chapters.find((c) => c.id === 'c2')?.volume_id).toBeNull(); // c2 不受影响
  });
});
