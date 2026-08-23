/**
 * 轻量标签注册表（stores/tags.ts）测试契约（#595 D7=A 拍板 / #596 回归护栏）。
 *
 * ⚠️ 本文件 = 契约。注册表语义（specs/f1-project-service/spec.md §2.1）：
 * - 预设建议 = 本项目已用 tags ∪ 旧 genre 枚举值（PROJECT_GENRE_LEGACY），去重保序
 * - 仅作建议，不约束自定义输入（本 store 只聚合，不校验）
 *
 * 由于 #595 已实现 stores/tags.ts（GREEN），本文件为**已交付功能回归测试**
 * （非 RED→GREEN 新功能）；全部用例应即时 PASS。覆盖：
 * - 初始 suggestions = 旧 genre 枚举（11 项保序）
 * - loadSuggestions() 缺省读项目 store 聚合；loadSuggestions(projects) 传显式列表
 * - 跨项目聚合去重保序（重叠 tag 只保留一次，首个出现位置）
 * - 空 tags 项目不新增建议项
 * - Project.tags 缺省（undefined）的安全路径（flatMap ?? []）
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useTagsStore, PROJECT_GENRE_LEGACY } from './tags';
import { useProjectStore, type Project } from './project';

function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: 'p1',
    name: '青云志',
    tags: [],
    language: 'zh-CN',
    target_words: 0,
    config: {},
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-08-05T10:00:00Z',
    ...overrides,
  };
}

beforeEach(() => {
  // 重置两个 store（zustand 单例跨测试污染隔离）
  useTagsStore.setState({ suggestions: [...PROJECT_GENRE_LEGACY] });
  useProjectStore.setState({
    projects: [],
    currentProjectId: null,
    loading: false,
    error: null,
    chapterProgress: {},
  });
});

describe('轻量标签注册表 stores/tags.ts（#595 D7=A / #596）', () => {
  it('初始 suggestions = 旧 genre 枚举（11 项保序）', () => {
    expect(useTagsStore.getState().suggestions).toEqual(PROJECT_GENRE_LEGACY);
    expect(PROJECT_GENRE_LEGACY).toHaveLength(11);
  });

  it('loadSuggestions() 缺省读项目 store 聚合：legacy ∪ 已用 tags', () => {
    useProjectStore.setState({
      projects: [
        makeProject({ id: 'p1', tags: ['玄幻', '热血'] }),
        makeProject({ id: 'p2', tags: ['升级流'] }),
      ],
    });
    useTagsStore.getState().loadSuggestions();
    // '玄幻' 已在 legacy（保序保留首个位置）；新增 '热血' / '升级流' 追加于 legacy 后
    expect(useTagsStore.getState().suggestions).toEqual([
      ...PROJECT_GENRE_LEGACY,
      '热血',
      '升级流',
    ]);
  });

  it('loadSuggestions(projects) 传显式列表：聚合去重（legacy 与传入重叠不重复）', () => {
    useTagsStore.getState().loadSuggestions([
      makeProject({ id: 'p1', tags: ['武侠', '热血'] }),
    ]);
    // '武侠' 已在 legacy；仅 '热血' 为新建议项
    expect(useTagsStore.getState().suggestions).toEqual([...PROJECT_GENRE_LEGACY, '热血']);
  });

  it('跨项目聚合去重保序：重叠 tags 只保留一次（首个出现位置）且无重复', () => {
    useProjectStore.setState({
      projects: [
        makeProject({ id: 'p1', tags: ['热血', '升级流'] }),
        makeProject({ id: 'p2', tags: ['热血', '无限流'] }),
      ],
    });
    useTagsStore.getState().loadSuggestions();
    const s = useTagsStore.getState().suggestions;
    expect(s).toEqual([...PROJECT_GENRE_LEGACY, '热血', '升级流', '无限流']);
    expect(new Set(s).size).toBe(s.length); // 无重复
  });

  it('空 tags 项目不新增建议项：suggestions 保持 legacy', () => {
    useProjectStore.setState({ projects: [makeProject({ id: 'p1', tags: [] })] });
    useTagsStore.getState().loadSuggestions();
    expect(useTagsStore.getState().suggestions).toEqual(PROJECT_GENRE_LEGACY);
  });

  it('Project.tags 缺省（undefined）安全：flatMap ?? [] 不抛且不新增', () => {
    const noTags = makeProject({ id: 'p1' });
    delete (noTags as Partial<Project>).tags;
    useProjectStore.setState({ projects: [noTags] });
    expect(() => useTagsStore.getState().loadSuggestions()).not.toThrow();
    expect(useTagsStore.getState().suggestions).toEqual(PROJECT_GENRE_LEGACY);
  });
});
