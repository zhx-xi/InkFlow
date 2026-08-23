/** 轻量标签注册表（#595 拍板 D7=A）：预设建议 = 本项目已用 tags ∪ 旧 genre 枚举值。
 *  纯前端聚合（无网络）；NewProjectDialog / project-settings 从此取预设建议。
 *  镜像 stores/project.ts 的 zustand 写法。 */
import { create } from 'zustand';
import { useProjectStore, type Project } from './project';

/** 旧 genre 枚举值（迁移保留为预设建议，11 项与 #595 前 NewProjectDialog GENRES 同源） */
export const PROJECT_GENRE_LEGACY = [
  '玄幻', '科幻', '言情', '仙侠', '武侠', '都市', '历史', '游戏', '悬疑', '奇幻', '其他',
];

interface TagsState {
  suggestions: string[];
  /** 聚合所有项目已用 tags ∪ 旧 genre 枚举值（去重保序）；缺省参数读项目 store */
  loadSuggestions: (projects?: Project[]) => void;
}

export const useTagsStore = create<TagsState>((set) => ({
  suggestions: [...PROJECT_GENRE_LEGACY],
  loadSuggestions: (projects) => {
    const list = projects ?? useProjectStore.getState().projects;
    const used = list.flatMap((p) => p.tags ?? []);
    set({ suggestions: Array.from(new Set([...PROJECT_GENRE_LEGACY, ...used])) });
  },
}));
