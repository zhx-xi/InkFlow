/**
 * #699 世界观分类删除修复：POST 成功后必须用响应真实 id 替换乐观临时 id（wc-{Date.now()}），
 * 否则 DELETE 用临时 id → 后端 404。契约：WorldCategoryEntity 含 kind；handleWorldCatSave(name, kind)。
 * 该文件为本 issue 新建（此前无 useWorldCategories 测试）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { apiFetch } from '../api/client';
import { useWorldCategories } from './useWorldCategories';
import { useThemeStore } from '../stores/theme';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

beforeEach(() => {
  apiFetchMock.mockReset();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useToastStore.setState({ toasts: [] });
});

/** 通用 mock：初始 GET 空列表；POST world-categories 返回真实实体（id=cat-1） */
function mockApiWithPost() {
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === '/api/v1/projects/p1/world-categories' && init?.method === 'POST') {
      return { id: 'cat-1', name: '势力', kind: 'geo' };
    }
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
}

describe('useWorldCategories — #699 删除修复 + kind', () => {
  it('POST 成功后用响应真实 id 替换乐观临时 id（删除不再 404）', async () => {
    mockApiWithPost();
    const { result } = renderHook(() => useWorldCategories('p1', 'world', 0));
    await act(async () => {
      await result.current.handleWorldCatSave('势力', 'geo');
    });
    // POST body 含 name + kind
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/projects/p1/world-categories', {
      method: 'POST',
      body: { name: '势力', kind: 'geo' },
    });
    // 列表项 id = 响应真实 id（非 wc-{Date.now()} 临时 id）
    expect(result.current.worldCategoryList[0]?.id).toBe('cat-1');
  });

  it('DELETE 用真实 id → 调用 /world-categories/{id} 并移除列表项', async () => {
    mockApiWithPost();
    const { result } = renderHook(() => useWorldCategories('p1', 'world', 0));
    await act(async () => {
      await result.current.handleWorldCatSave('势力', 'geo');
    });
    await act(async () => {
      await result.current.handleWorldCatDelete('cat-1');
    });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/world-categories/cat-1', { method: 'DELETE' });
    expect(result.current.worldCategoryList).toHaveLength(0);
  });
});
