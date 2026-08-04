/** 项目/书籍 store（对齐 ProjectCreate/Project DTO，domain/models/project.py） */

export interface Project {
  id: string;
  name: string;
  genre: string;
  language: string;
  target_words: number;
  config: ProjectConfig;
  created_at: string;
  updated_at: string;
}

/** ProjectConfig（domain/models/project.py：agent_* 为 None 表示默认模型） */
export interface ProjectConfig {
  model?: string | null;
  agent_architect?: string | null;
  agent_writer?: string | null;
  agent_auditor?: string | null;
  agent_reviser?: string | null;
  temperature?: number;
  writing_style?: string;
}

export interface NewProjectInput {
  name: string;
  genre?: string;
  language?: string;
  target_words?: number;
  config?: ProjectConfig;
}

import { create } from 'zustand';

interface ProjectState {
  projects: Project[];
  currentProjectId: string | null;
  loading: boolean;
  error: string | null;

  setProjects: (projects: Project[]) => void;
  setCurrentProject: (id: string | null) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
}

/** 骨架：状态与 action 签名已定，REST 逻辑与 TDD 测试在实现批次补全 */
export const useProjectStore = create<ProjectState>((set) => ({
  projects: [],
  currentProjectId: null,
  loading: false,
  error: null,

  setProjects: (projects) => set({ projects }),
  setCurrentProject: (id) => set({ currentProjectId: id }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
}));
