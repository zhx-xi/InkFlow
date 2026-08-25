/**
 * chapter store 卷 CRUD 契约测试（Issue #648 卷管理 GUI CRUD，RED 阶段）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须为 src/stores/chapter.ts 新增以下方法（并入 ChapterState）：
 *
 * - createVolume(projectId: string, title: string): Promise<Volume>
 *     POST /api/v1/projects/{projectId}/volumes，body { title }
 *     → 成功后把返回的 Volume 追加进 volumes 列表
 * - patchVolume(volumeId: string, title: string): Promise<Volume>
 *     PATCH /api/v1/volumes/{volumeId}，body { title }
 *     → 成功后把返回的 Volume 按 id 替换进 volumes 列表
 * - deleteVolume(volumeId: string, mode: { delete_chapters?: boolean; move_to?: string }): Promise<void>
 *     mode.delete_chapters → DELETE /api/v1/volumes/{volumeId}?delete_chapters=true
 *     mode.move_to        → DELETE /api/v1/volumes/{volumeId}?move_to={move_to}
 *     → 成功后把该卷从 volumes 移除，并调用一次 loadChapterTree(当前 treeProjectId) 刷新（treeProjectId 存在时）
 *
 * 测试方法镜像 chapter.test.ts：vi.mock('../api/client') 替换 apiFetch + act() 包裹 store action。
 * RED 期 store 尚无这些方法 → 用本地 VolumeActions 契约签名访问（GREEN 并入 ChapterState 后自然匹配）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act } from '@testing-library/react';
import { useChapterStore } from './chapter';
import { apiFetch } from '../api/client';
import type { Volume } from './chapter';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const volumes: Volume[] = [
  { id: 'v1', title: '第一卷 风起', order_index: 0 },
  { id: 'v2', title: '第二卷 云涌', order_index: 1 },
];

/** RED 期契约签名（GREEN 实现并入 ChapterState 后此接口即被满足） */
interface VolumeActions {
  createVolume: (projectId: string, title: string) => Promise<Volume>;
  patchVolume: (volumeId: string, title: string) => Promise<Volume>;
  deleteVolume: (volumeId: string, mode: { delete_chapters?: boolean; move_to?: string }) => Promise<void>;
}

const actions = () => useChapterStore.getState() as unknown as VolumeActions;

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

describe('chapter store — 卷 CRUD 契约面（#648，GREEN 必须提供）', () => {
  it('暴露 createVolume / patchVolume / deleteVolume 三个 REST actions', () => {
    const a = actions();
    expect(typeof a.createVolume).toBe('function');
    expect(typeof a.patchVolume).toBe('function');
    expect(typeof a.deleteVolume).toBe('function');
  });
});

describe('chapter store — createVolume', () => {
  it('POST /projects/{id}/volumes body {title} → 追加返回的 Volume 到 volumes 尾部', async () => {
    const created: Volume = { id: 'v9', title: '第三卷 潮生', order_index: 2 };
    apiFetchMock.mockResolvedValue(created);
    useChapterStore.setState({ volumes });

    await act(async () => {
      await actions().createVolume('p1', '第三卷 潮生');
    });

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/projects/p1/volumes', {
      method: 'POST',
      body: { title: '第三卷 潮生' },
    });
    expect(useChapterStore.getState().volumes).toEqual([...volumes, created]);
  });
});

describe('chapter store — patchVolume', () => {
  it('PATCH /volumes/{id} body {title} → 按 id 替换 volumes 中的对应卷', async () => {
    const patched: Volume = { id: 'v1', title: '第一卷 风起（修订）', order_index: 0 };
    apiFetchMock.mockResolvedValue(patched);
    useChapterStore.setState({ volumes });

    await act(async () => {
      await actions().patchVolume('v1', '第一卷 风起（修订）');
    });

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/volumes/v1', {
      method: 'PATCH',
      body: { title: '第一卷 风起（修订）' },
    });
    expect(useChapterStore.getState().volumes).toEqual([patched, volumes[1]]);
  });
});

describe('chapter store — deleteVolume', () => {
  it('mode.delete_chapters → DELETE /volumes/{id}?delete_chapters=true，移除该卷并触发 loadChapterTree 刷新', async () => {
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/volumes/v1?delete_chapters=true' && init?.method === 'DELETE') return undefined;
      if (path === '/api/v1/projects/p1/volumes') return { items: [volumes[1]] };
      if (path === '/api/v1/projects/p1/chapters') return { items: [], total: 0, offset: 0, limit: 50 };
      throw new Error(`unexpected: ${path}`);
    });
    useChapterStore.setState({ volumes, treeProjectId: 'p1' });

    await act(async () => {
      await actions().deleteVolume('v1', { delete_chapters: true });
    });

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/volumes/v1?delete_chapters=true', { method: 'DELETE' });
    // 刷新触发：DELETE 之后又发起了 loadChapterTree 的 GET volumes（调用序在 DELETE 之后）
    const deleteIdx = apiFetchMock.mock.calls.findIndex(([p]) => p === '/api/v1/volumes/v1?delete_chapters=true');
    const refreshIdx = apiFetchMock.mock.calls.findIndex(([p]) => p === '/api/v1/projects/p1/volumes');
    expect(refreshIdx).toBeGreaterThan(deleteIdx);
    // 刷新后 volumes 来自后端返回（v1 已不在）
    const s = useChapterStore.getState();
    expect(s.volumes).toEqual([volumes[1]]);
    expect(s.treeProjectId).toBe('p1');
  });

  it('mode.move_to → DELETE /volumes/{id}?move_to={target}，移除该卷', async () => {
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/volumes/v1?move_to=v2' && init?.method === 'DELETE') return undefined;
      if (path === '/api/v1/projects/p1/volumes') return { items: [volumes[1]] };
      if (path === '/api/v1/projects/p1/chapters') return { items: [], total: 0, offset: 0, limit: 50 };
      throw new Error(`unexpected: ${path}`);
    });
    useChapterStore.setState({ volumes, treeProjectId: 'p1' });

    await act(async () => {
      await actions().deleteVolume('v1', { move_to: 'v2' });
    });

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/volumes/v1?move_to=v2', { method: 'DELETE' });
    expect(useChapterStore.getState().volumes).toEqual([volumes[1]]);
  });

  it('treeProjectId 为空 → 删除成功但不触发刷新（仅一次 DELETE 调用）', async () => {
    apiFetchMock.mockResolvedValue(undefined);
    useChapterStore.setState({ volumes, treeProjectId: null });

    await act(async () => {
      await actions().deleteVolume('v2', { delete_chapters: true });
    });

    expect(apiFetchMock).toHaveBeenCalledTimes(1);
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/volumes/v2?delete_chapters=true', { method: 'DELETE' });
    expect(useChapterStore.getState().volumes).toEqual([volumes[0]]);
  });
});
