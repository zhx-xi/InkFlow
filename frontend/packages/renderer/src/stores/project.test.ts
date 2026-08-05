/**
 * project store 测试契约（Issue #79 RED 阶段，spec §4.2.2 / §4.4）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须匹配以下导出/签名：
 *
 * 新增 REST actions（当前骨架缺失 → RED）：
 * - loadProjects(): Promise<void>
 *     GET /api/v1/projects → {items: Project[], total, offset, limit}
 *     → setProjects(items)；随后对每个项目 GET /api/v1/projects/{id}/chapters
 *     → {items: Chapter[]} 计算 chapterProgress（written = word_count>0 章节数，total = items.length）
 *     设计假设：Project DTO 不含章节数（domain/models/project.py 核实），
 *     卡片进度由列表加载时按项目 N+1 拉取（本地 GUI 项目数少，可接受）；
 *     进度请求失败不阻塞列表（忽略，仅列表请求失败置 error）。
 * - createProject(input: NewProjectInput): Promise<Project>
 *     POST /api/v1/projects（201）→ 新项目插入列表头部 + selectProject(new.id)
 * - selectProject(id: string | null): void —— currentProjectId（项目卡片「写作中」标记依据）
 *
 * 状态转换契约：loading true→false；失败 → error 文案 + loading false。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act } from '@testing-library/react';
import { useProjectStore } from './project';
import { apiFetch } from '../api/client';
import type { Project, NewProjectInput } from './project';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

/** 构造符合后端 Project DTO 的样例 */
function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: 'p1',
    name: '青云志',
    genre: '玄幻',
    language: 'zh-CN',
    target_words: 800000,
    config: {},
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-08-05T10:00:00Z',
    ...overrides,
  };
}

function makeChapter(overrides: Record<string, unknown> = {}) {
  return {
    id: 'c1',
    project_id: 'p1',
    volume_id: null,
    title: '第1章 初见',
    content: '',
    word_count: 0,
    order_index: 0,
    ...overrides,
  };
}

beforeEach(() => {
  apiFetchMock.mockReset();
  // 重置 store 初始态（zustand 测试间隔离）
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null, chapterProgress: {} });
});

describe('project store — 契约面（GREEN 必须提供）', () => {
  it('暴露 REST actions: loadProjects / createProject / selectProject', () => {
    const s = useProjectStore.getState();
    expect(typeof s.loadProjects).toBe('function');
    expect(typeof s.createProject).toBe('function');
    expect(typeof s.selectProject).toBe('function');
  });
});

describe('project store — 状态与状态转换', () => {
  it('初始状态：空列表 / 无当前项目 / 未加载 / 无错误', () => {
    const s = useProjectStore.getState();
    expect(s.projects).toEqual([]);
    expect(s.currentProjectId).toBeNull();
    expect(s.loading).toBe(false);
    expect(s.error).toBeNull();
    expect(s.chapterProgress).toEqual({});
  });

  it('loadProjects 成功：填充列表 + 计算章节进度 + 复位 loading/error', async () => {
    const projects = [makeProject({ id: 'p1', name: '青云志' }), makeProject({ id: 'p2', name: '山海经' })];
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects') return { items: projects, total: 2, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/chapters') {
        // 3 章有正文（word_count>0）、9 章空白 → written=3, total=12
        return { items: [...Array(12).keys()].map((i) => makeChapter({ id: `c${i}`, word_count: i < 3 ? 500 : 0 })), total: 12, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/projects/p2/chapters') return { items: [], total: 0, offset: 0, limit: 50 };
      throw new Error(`unexpected path: ${path}`);
    });

    await act(async () => {
      await useProjectStore.getState().loadProjects();
    });

    const s = useProjectStore.getState();
    expect(s.projects).toHaveLength(2);
    expect(s.projects[0].name).toBe('青云志');
    expect(s.loading).toBe(false);
    expect(s.error).toBeNull();
    expect(s.chapterProgress).toEqual({ p1: { written: 3, total: 12 }, p2: { written: 0, total: 0 } });
  });

  it('loadProjects 请求期间 loading=true（转换可观测）', async () => {
    let resolveList!: (v: unknown) => void;
    apiFetchMock.mockImplementation(
      () => new Promise((resolve) => { resolveList = resolve; }) as Promise<unknown>,
    );
    const p = useProjectStore.getState().loadProjects();
    expect(useProjectStore.getState().loading).toBe(true);
    resolveList({ items: [], total: 0, offset: 0, limit: 50 });
    await act(async () => { await p; });
    expect(useProjectStore.getState().loading).toBe(false);
  });

  it('loadProjects 失败：error 记录 + loading 复位 + 列表不更新', async () => {
    apiFetchMock.mockRejectedValue(new Error('内核未就绪'));
    await act(async () => {
      await useProjectStore.getState().loadProjects();
    });
    const s = useProjectStore.getState();
    expect(s.error).toContain('内核未就绪');
    expect(s.loading).toBe(false);
    expect(s.projects).toEqual([]);
  });

  it('createProject：POST /api/v1/projects → 新项目插入头部并选中', async () => {
    const created = makeProject({ id: 'p9', name: '青山入我怀' });
    apiFetchMock.mockResolvedValue(created);
    const input: NewProjectInput = { name: '青山入我怀', genre: '言情', language: 'zh-CN', target_words: 800000 };

    let returned!: Project;
    await act(async () => {
      returned = await useProjectStore.getState().createProject(input);
    });

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/projects', {
      method: 'POST',
      body: { name: '青山入我怀', genre: '言情', language: 'zh-CN', target_words: 800000 },
    });
    expect(returned.id).toBe('p9');
    const s = useProjectStore.getState();
    expect(s.projects[0].id).toBe('p9');
    expect(s.currentProjectId).toBe('p9');
  });

  it('selectProject：设置当前项目 id（写作中标记依据）', () => {
    act(() => {
      useProjectStore.getState().selectProject('p1');
    });
    expect(useProjectStore.getState().currentProjectId).toBe('p1');
    act(() => {
      useProjectStore.getState().selectProject(null);
    });
    expect(useProjectStore.getState().currentProjectId).toBeNull();
  });
});

/**
 * #105 Coverage-Gap 补测（非 RED）：单项目进度拉取失败 catch 分支（L103-105，
 * 忽略不阻塞列表）+ 四个基础 setter 函数调用面
 * （setProjects/setCurrentProject/setLoading/setError）。
 */
describe('project store — 进度失败兜底与 setter 组（#105 补测）', () => {
  it('loadProjects：单项目进度拉取失败 → 忽略（列表仍可用，仅缺该进度）', async () => {
    const projects = [makeProject({ id: 'p1', name: '青云志' }), makeProject({ id: 'p2', name: '山海经' })];
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects') return { items: projects, total: 2, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/chapters') throw new Error('进度获取失败');
      if (path === '/api/v1/projects/p2/chapters') {
        return { items: [makeChapter({ id: 'c1', word_count: 500 })], total: 1, offset: 0, limit: 50 };
      }
      throw new Error(`unexpected path: ${path}`);
    });

    await act(async () => {
      await useProjectStore.getState().loadProjects();
    });

    const s = useProjectStore.getState();
    expect(s.projects).toHaveLength(2);
    expect(s.error).toBeNull();
    expect(s.loading).toBe(false);
    expect(s.chapterProgress).toEqual({ p2: { written: 1, total: 1 } });
  });

  it('setter 组：setProjects / setCurrentProject / setLoading / setError 同步状态', () => {
    const p = makeProject();
    act(() => {
      const s = useProjectStore.getState();
      s.setProjects([p]);
      s.setCurrentProject('p1');
      s.setLoading(true);
      s.setError('临时错误');
    });
    const s = useProjectStore.getState();
    expect(s.projects).toEqual([p]);
    expect(s.currentProjectId).toBe('p1');
    expect(s.loading).toBe(true);
    expect(s.error).toBe('临时错误');
  });
});
