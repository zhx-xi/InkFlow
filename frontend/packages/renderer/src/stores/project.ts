/** 项目/书籍 store（对齐 ProjectCreate/Project DTO，domain/models/project.py） */

export interface Project {
  id: string;
  name: string;
  /** #595：项目标签（自由多值，空数组 = 未设置；write_auto 题材 = tags 全拼） */
  tags: string[];
  language: string;
  target_words: number;
  config: ProjectConfig;
  created_at: string;
  updated_at: string;
}

/** ProjectConfig（domain/models/project.py：#225 三态语义）：
 *  agent_*: null=关闭（禁用角色）；字符串=开启且指定模型；
 *  "__default__"（AGENT_DEFAULT_SENTINEL）=跟随默认（预留，前端不暴露中间态 UI） */
/** #225 sentinel：跟随默认（后端契约预留；字符串=开启） */
export const AGENT_DEFAULT_SENTINEL = '__default__';

export interface ProjectConfig {
  model?: string | null;
  agent_architect?: string | null;
  agent_writer?: string | null;
  agent_auditor?: string | null;
  agent_reviser?: string | null;
  /** v1.5 #484：世界观顾问三态字段（null=关闭 / __default__=跟随默认 / provider/model=指定） */
  agent_worldview?: string | null;
  /** v1.5 #484：润色师三态字段（同 agent_worldview 三态语义） */
  agent_polisher?: string | null;
  temperature?: number;
  default_words?: number;
  writing_style?: string;
  /** #107：项目内绑定 Agent 模板（config JSON 零迁移，null = 解除引用；#523 起支持 builtin: 字符串键与自定义 id str） */
  template_id?: string | number | null;
  /** F42 #269：Agent 链执行拓扑（层级嵌套，外层=槽位 0-9、同层并行；空=默认模板模式） */
  agent_order?: string[][];
  /** F42 #296：自定义角色三态字段（key 带 agent_ 前缀，value 三态与 agent_* 相同：null=关闭/__default__=跟随默认/provider/model=指定） */
  agent_roles?: Record<string, string | null>;
  /** F46 #270：Agent 关联关系（DAG 编排，spec §2.1）——from/to 带 agent_ 前缀角色字段名，
   *  type ∈ sequential/data/conditional；空=纯 agent_order 基线 */
  agent_relations?: { from: string; to: string; type: string }[];
  /** Q2=C：项目级扩展字典（F44 多维上限 book_max_* 键载体） */
  extra?: Record<string, number | string | boolean>;
  /** #343：Supervisor/HITL 项目级配置（hitl_roles 非空时管线以 supervisor 模式执行，命中角色前中断等确认） */
  supervisor?: { hitl_roles?: string[] } | null;
}

export interface NewProjectInput {
  name: string;
  tags?: string[];
  language?: string;
  target_words?: number;
  config?: ProjectConfig;
  /** #107：新建项目选模板，POST body 透传（null/缺省 = 默认模板；#523 起支持 builtin: 字符串键与自定义 id str） */
  template_id?: string | number | null;
}

import { create } from 'zustand';
import { apiFetch, errorMessage } from '../api/client';

/** 章节进度（written = 已有正文章节数，total = 章节总数） */
export interface ChapterProgress {
  written: number;
  total: number;
}

interface ProjectListResponse {
  items: Project[];
  total: number;
  offset: number;
  limit: number;
}

interface ChapterListResponse {
  items: Array<{ id: string; word_count: number }>;
  total: number;
  offset: number;
  limit: number;
}

interface ProjectState {
  projects: Project[];
  currentProjectId: string | null;
  loading: boolean;
  error: string | null;
  chapterProgress: Record<string, ChapterProgress>;

  setProjects: (projects: Project[]) => void;
  setCurrentProject: (id: string | null) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;

  loadProjects: () => Promise<void>;
  createProject: (input: NewProjectInput) => Promise<Project>;
  /** #107：项目内切换模板（PATCH body { config: patch }，本地 config 合并更新） */
  updateConfig: (id: string, patch: ProjectConfig) => Promise<void>;
  /** F43：项目重命名（PATCH body { name } → 本地更新；失败 rethrow，页面 catch → err toast） */
  renameProject: (id: string, name: string) => Promise<void>;
  /** #595：项目标签更新（PATCH body { tags } → 本地同步；失败 rethrow，页面 catch） */
  updateTags: (id: string, tags: string[]) => Promise<void>;
  /** F43：项目删除（DELETE → 本地移除 + currentProjectId 条件置 null + 清理 chapterProgress；失败 rethrow） */
  deleteProject: (id: string) => Promise<void>;
  selectProject: (id: string | null) => void;
}

export const useProjectStore = create<ProjectState>((set, get) => ({
  projects: [],
  currentProjectId: null,
  loading: false,
  error: null,
  chapterProgress: {},

  setProjects: (projects) => set({ projects }),
  setCurrentProject: (id) => set({ currentProjectId: id }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),

  loadProjects: async () => {
    set({ loading: true, error: null });
    try {
      const data = await apiFetch<ProjectListResponse>('/api/v1/projects');
      set({ projects: data.items });
      // 进度按项目 N+1 拉取（本地 GUI 项目数少可接受）；单项目进度失败不阻塞列表
      const chapterProgress: Record<string, ChapterProgress> = {};
      await Promise.all(
        data.items.map(async (project) => {
          try {
            const chapters = await apiFetch<ChapterListResponse>(
              `/api/v1/projects/${project.id}/chapters`,
            );
            chapterProgress[project.id] = {
              written: chapters.items.filter((c) => c.word_count > 0).length,
              total: chapters.items.length,
            };
          } catch {
            // 忽略：进度拉取失败仅缺卡片进度，列表仍可用
          }
        }),
      );
      set({ chapterProgress, loading: false });
    } catch (err) {
      set({ error: errorMessage(err), loading: false });
    }
  },

  createProject: async (input) => {
    const created = await apiFetch<Project>('/api/v1/projects', { method: 'POST', body: input });
    set({ projects: [created, ...get().projects], currentProjectId: created.id });
    return created;
  },

  updateConfig: async (id, patch) => {
    await apiFetch(`/api/v1/projects/${id}`, { method: 'PATCH', body: { config: patch } });
    set((s) => ({
      projects: s.projects.map((p) =>
        p.id === id ? { ...p, config: { ...p.config, ...patch } } : p,
      ),
    }));
  },

  // F43 §2.4/§5.6：失败 rethrow（不吞错，页面 catch → err toast）
  renameProject: async (id, name) => {
    await apiFetch(`/api/v1/projects/${id}`, { method: 'PATCH', body: { name } });
    set((s) => ({
      projects: s.projects.map((p) => (p.id === id ? { ...p, name } : p)),
    }));
  },

  // #595：项目标签（PATCH body { tags } → 本地 projects 同步；失败 rethrow，页面 catch）
  updateTags: async (id, tags) => {
    await apiFetch(`/api/v1/projects/${id}`, { method: 'PATCH', body: { tags } });
    set((s) => ({
      projects: s.projects.map((p) => (p.id === id ? { ...p, tags } : p)),
    }));
  },

  // F43 §2.4/§5.6：DELETE（apiFetch 204 → undefined，不解析 body）；本地三处同步：
  // projects 移除 / currentProjectId 条件置 null（E7）/ chapterProgress 删除键
  deleteProject: async (id) => {
    await apiFetch(`/api/v1/projects/${id}`, { method: 'DELETE' });
    set((s) => {
      const chapterProgress = { ...s.chapterProgress };
      delete chapterProgress[id];
      return {
        projects: s.projects.filter((p) => p.id !== id),
        currentProjectId: s.currentProjectId === id ? null : s.currentProjectId,
        chapterProgress,
      };
    });
  },

  selectProject: (id) => set({ currentProjectId: id }),
}));
