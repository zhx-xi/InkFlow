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
}

export const useChapterStore = create<ChapterState>((set, get) => ({
  volumes: [],
  chapters: [],
  currentChapterId: null,
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
      set({ volumes, chapters: chapterData.items, currentChapterId: null, content: '', loading: false });
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
}));
