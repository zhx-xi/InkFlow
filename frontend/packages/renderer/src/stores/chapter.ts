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

import { create } from 'zustand';

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
}

export const useChapterStore = create<ChapterState>((set) => ({
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
}));
