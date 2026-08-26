/** 章节/写作 store（卷章树 + 当前章节正文；SSE 完成时一次性 setContent 提交，§4.5） */

export interface Volume {
  id: string;
  title: string;
  order_index: number;
}

export interface ChapterMeta {
  id: string;
  title: string;
  volume_id: string | null;
  order_index: number;
  word_count: number;
}

/** 章节详情（含正文，selectChapter 拉取） */
export interface Chapter extends ChapterMeta {
  project_id: string;
  content: string;
}

interface ChapterListResponse {
  items: ChapterMeta[];
  total: number;
  offset: number;
  limit: number;
}

import { create } from 'zustand';
import { apiFetch, errorMessage } from '../api/client';

interface ChapterState {
  volumes: Volume[];
  chapters: ChapterMeta[];
  currentChapterId: string | null;
  /** 当前卷章树所属项目 id（#371：同项目 reload 保留当前章/正文；切项目清空） */
  treeProjectId: string | null;
  /** 当前章节正文（SSE done 帧/保存后提交） */
  content: string;
  loading: boolean;
  error: string | null;

  setTree: (volumes: Volume[], chapters: ChapterMeta[]) => void;
  setCurrentChapter: (id: string | null) => void;
  setContent: (content: string) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;

  loadChapterTree: (projectId: string) => Promise<void>;
  selectChapter: (chapterId: string) => Promise<void>;
  saveContent: () => Promise<void>;
  createChapter: (projectId: string, title: string, volumeId?: string) => Promise<ChapterMeta>;
  moveChapter: (chapterId: string, targetVolumeId: string | null) => Promise<ChapterMeta>;
  createVolume: (projectId: string, title: string) => Promise<Volume>;
  patchVolume: (volumeId: string, title: string) => Promise<Volume>;
  deleteVolume: (
    volumeId: string,
    mode: { delete_chapters?: boolean; move_to?: string },
  ) => Promise<void>;
}

export const useChapterStore = create<ChapterState>((set, get) => ({
  volumes: [],
  chapters: [],
  currentChapterId: null,
  treeProjectId: null,
  content: '',
  loading: false,
  error: null,

  setTree: (volumes, chapters) => set({ volumes, chapters }),
  setCurrentChapter: (id) => set({ currentChapterId: id }),
  setContent: (content) => set({ content }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),

  loadChapterTree: async (projectId) => {
    set({ loading: true, error: null });
    try {
      const { items: volumes } = await apiFetch<{ items: Volume[] }>(`/api/v1/projects/${projectId}/volumes`);
      const chapterData = await apiFetch<ChapterListResponse>(
        `/api/v1/projects/${projectId}/chapters`,
      );
      // #371：同项目 reload（treeProjectId 相同）保留当前章/正文——写作页挂载自动加载
      // 不清空已播种/已编辑内容；切项目/首次加载（不同或 null）→ 清空（#345 防旧项目残留）
      const sameProject = get().treeProjectId === projectId;
      set({
        volumes,
        chapters: chapterData.items,
        treeProjectId: projectId,
        ...(sameProject ? {} : { currentChapterId: null, content: '' }),
        loading: false,
      });
    } catch (err) {
      set({ error: errorMessage(err), loading: false });
    }
  },

  selectChapter: async (chapterId) => {
    set({ loading: true, error: null });
    try {
      const chapter = await apiFetch<Chapter>(`/api/v1/chapters/${chapterId}`, undefined);
      set({ currentChapterId: chapter.id, content: chapter.content, loading: false });
    } catch (err) {
      set({ error: errorMessage(err), loading: false });
    }
  },

  saveContent: async () => {
    const { currentChapterId, content } = get();
    if (currentChapterId === null) return; // 未选中章节静默跳过
    await apiFetch(`/api/v1/chapters/${currentChapterId}`, {
      method: 'PATCH',
      body: { content },
    });
  },

  createChapter: async (projectId, title, volumeId) => {
    const created = await apiFetch<ChapterMeta>(`/api/v1/projects/${projectId}/chapters`, {
      method: 'POST',
      body: { title, ...(volumeId !== undefined ? { volume_id: volumeId } : {}) },
    });
    set((s) => ({ chapters: [...s.chapters, created], currentChapterId: created.id }));
    return created;
  },

  moveChapter: async (chapterId, targetVolumeId) => {
    const query = targetVolumeId ? `?target_volume_id=${encodeURIComponent(targetVolumeId)}` : '';
    const updated = await apiFetch<ChapterMeta>(`/api/v1/chapters/${chapterId}/move${query}`, {
      method: 'POST',
    });
    set((s) => ({ chapters: s.chapters.map((c) => (c.id === updated.id ? updated : c)) }));
    return updated;
  },

  createVolume: async (projectId, title) => {
    const created = await apiFetch<Volume>(`/api/v1/projects/${projectId}/volumes`, {
      method: 'POST',
      body: { title },
    });
    set((s) => ({ volumes: [...s.volumes, created] }));
    return created;
  },

  patchVolume: async (volumeId, title) => {
    const patched = await apiFetch<Volume>(`/api/v1/volumes/${volumeId}`, {
      method: 'PATCH',
      body: { title },
    });
    set((s) => ({ volumes: s.volumes.map((v) => (v.id === patched.id ? patched : v)) }));
    return patched;
  },

  deleteVolume: async (volumeId, mode) => {
    const query = mode.delete_chapters
      ? `?delete_chapters=true`
      : mode.move_to
        ? `?move_to=${mode.move_to}`
        : '';
    await apiFetch(`/api/v1/volumes/${volumeId}${query}`, { method: 'DELETE' });
    set((s) => ({ volumes: s.volumes.filter((v) => v.id !== volumeId) }));
    const { treeProjectId } = get();
    if (treeProjectId) {
      await get().loadChapterTree(treeProjectId);
    }
  },
}));
