/**
 * Skill store（F40 #259，spec §3.1 / §3.2 / §5.4）：
 * 列表加载 / 上传 / 删除；镜像 src/stores/templates.ts 模式（apiFetch + errorMessage + zustand）。
 */
import { create } from 'zustand';
import { apiFetch, errorMessage } from '../api/client';

/** agent_ids 反查项（列表端点即含 name） */
export interface SkillRef {
  id: number;
  name: string;
}

/** Skill 实体（source 区分内置只读 / 用户上传；agent_ids 反查列表端点即含） */
export interface Skill {
  id: number;
  name: string;
  description: string;
  content: string;
  source: 'builtin' | 'user_upload';
  created_at: string;
  updated_at: string;
  agent_ids: SkillRef[];
}

/** 列表端点响应信封（§4.4 惯例：{ items, total }） */
export interface SkillListResponse {
  items: Skill[];
  total: number;
}

interface SkillsState {
  skills: Skill[];
  loading: boolean;
  error: string | null;

  loadSkills: () => Promise<void>;
  uploadSkill: (content: string) => Promise<Skill>;
  deleteSkill: (id: number) => Promise<void>;
}

export const useSkillsStore = create<SkillsState>((set) => ({
  skills: [],
  loading: false,
  error: null,

  loadSkills: async () => {
    set({ loading: true, error: null });
    try {
      const data = await apiFetch<SkillListResponse>('/api/v1/skills');
      set({ skills: data.items, loading: false, error: null });
    } catch (err) {
      // 失败：error 设置 + 保留原列表
      set({ error: errorMessage(err), loading: false });
    }
  },

  uploadSkill: async (content) => {
    try {
      const created = await apiFetch<Skill>('/api/v1/skills', {
        method: 'POST',
        body: { content },
      });
      set((s) => ({ skills: [...s.skills, created], error: null }));
      return created;
    } catch (err) {
      // 失败（422 / 同名 / 409）：error + rethrow（上传流程需感知失败）
      set({ error: errorMessage(err) });
      throw err;
    }
  },

  deleteSkill: async (id) => {
    try {
      await apiFetch(`/api/v1/skills/${id}`, { method: 'DELETE' });
      set((s) => ({ skills: s.skills.filter((skill) => skill.id !== id), error: null }));
    } catch (err) {
      // 失败（409 内置只读）：error + 列表不变（不 rethrow，同 templates.deleteTemplate）
      set({ error: errorMessage(err) });
    }
  },
}));
