/**
 * useBookLimits 契约测试（F44 阶段2 GUI，spec v1.1 §5.2 GUI 小节「多维上限配置 UI」Q2=C）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须新建 src/hooks/useBookLimits.ts 并匹配：
 *
 * export interface BookLimitsValues {
 *   max_chapters: number | null;
 *   max_agent_calls: number | null;
 *   max_tokens: number | null;
 *   max_sessions: number | null;
 * }
 * export function useBookLimits(projectId: string): {
 *   values: BookLimitsValues;          // project.config.extra.book_max_*（缺失 → null）
 *   setValue: (field: keyof BookLimitsValues, value: number | null) => void;
 *   save: () => Promise<boolean>;      // updateConfig(projectId, {extra: 合并}) → true/false
 *   saving: boolean;
 *   error: string | null;
 * }
 *
 * 行为契约（Q2=C：项目级 ProjectConfig.extra 是上限默认载体，读取优先级
 * 请求显式 > 项目级 extra > 默认常量；本 hook 只管理项目级 extra 的 book_max_* 4 键）：
 * - values 初始 = project.config.extra 的 book_max_chapters / book_max_agent_calls /
 *   book_max_tokens / book_max_sessions（数字或 null）
 * - setValue(field, num) → 本地 values 更新（不立即持久化，不发请求）
 * - save() → projectStore.updateConfig(projectId, { extra: 合并 })
 *   - extra 合并语义：保留既有键 + 覆盖 book_max_*（value 非 null 才写键；null 删除键）
 *   - 成功返回 true；失败返回 false + error 设置（errorMessage）
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useBookLimits } from './useBookLimits';
import { useProjectStore, type Project } from '../stores/project';
import { apiFetch } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const projectP1: Project = {
  id: 'p1',
  name: '时间旅者',
  tags: ['悬疑'],
  language: 'zh',
  target_words: 800000,
  config: {
    extra: { book_max_chapters: 5, book_max_tokens: 200000 },
  },
  created_at: '2026-08-17T10:00:00Z',
  updated_at: '2026-08-17T10:00:00Z',
};

beforeEach(() => {
  apiFetchMock.mockReset();
  apiFetchMock.mockResolvedValue({ ok: true });
  useProjectStore.setState({
    projects: [projectP1],
    currentProjectId: 'p1',
    loading: false,
    error: null,
    chapterProgress: {},
  });
});

describe('useBookLimits — 初始值', () => {
  it('values 从 project.config.extra 的 book_max_* 读取（缺失 → null）', () => {
    const { result } = renderHook(() => useBookLimits('p1'));
    expect(result.current.values).toEqual({
      max_chapters: 5,
      max_agent_calls: null,
      max_tokens: 200000,
      max_sessions: null,
    });
  });
});

describe('useBookLimits — setValue', () => {
  it('setValue 更新本地 values（不立即持久化，不发请求）', () => {
    const { result } = renderHook(() => useBookLimits('p1'));
    act(() => {
      result.current.setValue('max_chapters', 8);
      result.current.setValue('max_sessions', 2);
    });
    expect(result.current.values.max_chapters).toBe(8);
    expect(result.current.values.max_sessions).toBe(2);
    expect(apiFetchMock).not.toHaveBeenCalled();
  });
});

describe('useBookLimits — save 持久化', () => {
  it('save → PATCH /projects/p1 {config: {extra: 合并}} + 本地 project store 更新', async () => {
    const { result } = renderHook(() => useBookLimits('p1'));
    act(() => {
      result.current.setValue('max_chapters', 8);
    });
    let ok = false;
    await act(async () => {
      ok = await result.current.save();
    });
    expect(ok).toBe(true);
    // 合并语义：保留既有 book_max_tokens + 覆盖 book_max_chapters
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/projects/p1', {
      method: 'PATCH',
      body: {
        config: {
          extra: { book_max_tokens: 200000, book_max_chapters: 8 },
        },
      },
    });
    // updateConfig 本地合并 → config.extra 更新
    const p = useProjectStore.getState().projects.find((x) => x.id === 'p1');
    expect(p?.config.extra?.book_max_chapters).toBe(8);
    expect(p?.config.extra?.book_max_tokens).toBe(200000);
  });

  it('save 时 value=null 的字段从 extra 删除（不写键）', async () => {
    const { result } = renderHook(() => useBookLimits('p1'));
    act(() => {
      result.current.setValue('max_sessions', 2);
      result.current.setValue('max_agent_calls', null);
      result.current.setValue('max_sessions', null);
    });
    await act(async () => {
      await result.current.save();
    });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/projects/p1', {
      method: 'PATCH',
      body: {
        config: {
          extra: { book_max_tokens: 200000, book_max_chapters: 5 },
        },
      },
    });
  });

  it('save 失败 → 返回 false + error 设置', async () => {
    apiFetchMock.mockRejectedValue(new Error('网络错误'));
    const { result } = renderHook(() => useBookLimits('p1'));
    let ok = true;
    await act(async () => {
      ok = await result.current.save();
    });
    expect(ok).toBe(false);
    expect(result.current.error).toBe('网络错误');
  });
});
