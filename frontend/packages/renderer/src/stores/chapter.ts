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

/** #976 草稿双轨树节点（kind='draft'：不进 ChapterMeta/字数统计，仅树轨渲染） */
export interface DraftTreeNode {
  kind: 'draft';
  id: string;
  draftId: string;
  summary: string;
  content: string;
  volume_id: string | null;
  created_at: string;
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
import type { DraftDto } from '../api/drafts';

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
  /** #976：项目待审批草稿（status=draft；树 = chapters + pendingDrafts 合流） */
  pendingDrafts: DraftTreeNode[];
  /** #976：审批弹层请求（树双击草稿置 draftId；null = 未请求） */
  approvalRequest: string | null;

  setTree: (volumes: Volume[], chapters: ChapterMeta[]) => void;
  setCurrentChapter: (id: string | null) => void;
  setContent: (content: string) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;

  loadChapterTree: (projectId: string) => Promise<void>;
  /** #976：拉取项目待审批草稿（失败静默，不阻断卷章树、不污染 error） */
  loadPendingDrafts: (projectId: string) => Promise<void>;
  /** #976：确认草稿（成功 → 同项目树+草稿双刷新） */
  confirmDraft: (draftId: string) => Promise<void>;
  /** #976：驳回草稿（成功 → 同项目树+草稿双刷新） */
  rejectDraft: (draftId: string) => Promise<void>;
  /** #976：请求审批草稿（跨组件入口，zustand 全局态承载） */
  requestApproval: (draftId: string) => void;
  clearApprovalRequest: () => void;
  selectChapter: (chapterId: string) => Promise<void>;
  saveContent: () => Promise<void>;
  createChapter: (projectId: string, title: string, volumeId?: string) => Promise<ChapterMeta>;
  moveChapter: (chapterId: string, targetVolumeId: string | null) => Promise<ChapterMeta>;
  patchChapter: (chapterId: string, title: string) => Promise<ChapterMeta>;
  deleteChapter: (chapterId: string) => Promise<void>;
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
  pendingDrafts: [],
  approvalRequest: null,

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
      });
      // #976：草稿轨与树同窗加载（loading 保持 true 直至草稿也拉完；草稿失败静默）
      await get().loadPendingDrafts(projectId);
      set({ loading: false });
    } catch (err) {
      set({ error: errorMessage(err), loading: false });
    }
  },

  loadPendingDrafts: async (projectId) => {
    try {
      const data = await apiFetch<{ items: DraftDto[] }>(
        `/api/v1/agent/drafts?project_id=${encodeURIComponent(projectId)}&status=draft`,
      );
      set({
        pendingDrafts: data.items.map((d) => ({
          kind: 'draft',
          id: `draft-${d.id}`,
          draftId: d.id,
          summary: d.summary,
          content: d.content,
          volume_id: d.volume_id ?? null,
          created_at: d.created_at,
        })),
      });
    } catch {
      // #976：树轨草稿失败静默（不阻断卷章树；审批弹层自带错误态）
    }
  },

  confirmDraft: async (draftId) => {
    await apiFetch(`/api/v1/agent/drafts/${draftId}/confirm`, { method: 'POST', body: {} });
    const treeProjectId = get().treeProjectId;
    if (treeProjectId) await get().loadChapterTree(treeProjectId);
  },

  rejectDraft: async (draftId) => {
    await apiFetch(`/api/v1/agent/drafts/${draftId}/reject`, { method: 'POST' });
    const treeProjectId = get().treeProjectId;
    if (treeProjectId) await get().loadChapterTree(treeProjectId);
  },

  requestApproval: (draftId) => set({ approvalRequest: draftId }),
  clearApprovalRequest: () => set({ approvalRequest: null }),

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

  patchChapter: async (chapterId, title) => {
    const patched = await apiFetch<ChapterMeta>(`/api/v1/chapters/${chapterId}`, {
      method: 'PATCH',
      body: { title },
    });
    set((s) => ({ chapters: s.chapters.map((c) => (c.id === patched.id ? patched : c)) }));
    return patched;
  },

  deleteChapter: async (chapterId) => {
    const { currentChapterId, chapters } = get();
    const target = chapters.find((c) => c.id === chapterId);
    const prevVolumeId = target?.volume_id ?? null;
    await apiFetch(`/api/v1/chapters/${chapterId}`, { method: 'DELETE' });
    const rest = chapters.filter((c) => c.id !== chapterId);
    set({ chapters: rest });
    if (currentChapterId === chapterId) {
      // 当前章被删：优先同卷下一个，其次任意剩余，皆无则置空
      const nextInVolume = rest.find((c) => c.volume_id === prevVolumeId) ?? rest[0] ?? null;
      if (nextInVolume) {
        set({ currentChapterId: nextInVolume.id });
        await get().selectChapter(nextInVolume.id); // 拉取新章正文
      } else {
        set({ currentChapterId: null, content: '' });
      }
    }
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
