/**
 * #641 世界观分类批修复契约（rc4 GUI 三缺陷）：
 * ① 分类重复列出（world-categories 返回同名时 chips 不重复）
 * ② 分类栏「去创建」（world-cat-add）在选中分类时打开「该分类下新建具体条目」表单（library-create-dialog），
 *    而非「新建分类」表单（world-cat-dialog）。
 * ③ 已创建分类有删除入口（world-cat-delete-<name>），调用 DELETE /api/v1/world-categories/{id}，成功后从列表移除。
 *
 * ⚠️ 本文件 = #641 契约（前端组件测试，TDD RED→GREEN）。当前实现 FAIL，GREEN 实现必须匹配。
 * 守护/回归：既有「未选分类时 world-cat-add 新建分类（POST /world-categories）」契约（library-p2 #389）不破坏。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { LibraryPage } from './library';
import { apiFetch } from '../api/client';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const projectP1 = {
  id: 'p1', name: '青云志', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, config: {},
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};

function renderLibrary() {
  return render(
    <MemoryRouter initialEntries={['/library']}>
      <LibraryPage />
      <Routes>
        <Route path="/projects" element={<div data-testid="projects-probe" />} />
        <Route path="/writing" element={<div data-testid="writing-probe" />} />
      </Routes>
    </MemoryRouter>,
  );
}

/** #641 mock：world-settings 返回一个根条目（让工具栏/树渲染）；world-categories 返回 cats。 */
function seedWorldCategories(cats: Array<{ id: string; name: string; count?: number }>) {
  const items = [
    { id: 'w1', name: '世界观', parent_id: null, category: '', content: '', created_at: '', updated_at: '' },
  ];
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/world-settings') return { items, total: items.length, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/world-categories') return { items: cats, total: cats.length, offset: 0, limit: 50 };
    if (path.startsWith('/api/v1/world-categories/') && init?.method === 'DELETE') return { ok: true };
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
}

/** 登录世界观 tab 并等待列表渲染 */
async function goWorldTab(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('tab', { name: '世界观' }));
  await waitFor(() => expect(screen.getByTestId('library-list')).toBeInTheDocument());
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1', loading: false, error: null });
  useToastStore.setState({ toasts: [] });
});

describe('设定库页 — 世界观分类批修复（#641）', () => {
  it('① 分类去重：world-categories 返回同名分类时，chips 只列出一次（不重复）', async () => {
    // 同名「秘境」返回两次（模拟后端聚合重复/乐观追加重复）
    seedWorldCategories([
      { id: 'wc1', name: '秘境', count: 1 },
      { id: 'wc2', name: '秘境', count: 1 },
    ]);
    const user = userEvent.setup();
    renderLibrary();
    await goWorldTab(user);

    // RED：当前实现 worldCategoryList.map(name) 不去重 → 两个同名 chip 渲染 → length 2 → FAIL
    const chips = screen.getAllByTestId('world-cat-filter-秘境');
    expect(chips).toHaveLength(1);
  });

  it('② 分类栏「去创建」：选中分类 chip 后点 world-cat-add → 打开「新建具体条目」表单（library-create-dialog）而非「新建分类」（world-cat-dialog）', async () => {
    seedWorldCategories([{ id: 'wc1', name: '秘境', count: 1 }]);
    const user = userEvent.setup();
    renderLibrary();
    await goWorldTab(user);

    // 选中「秘境」分类 chip → activeWorldCat 置位
    await user.click(screen.getByTestId('world-cat-filter-秘境'));
    // 分类栏「去创建」= world-cat-add（工具栏 + 按钮），选中分类时语义 = 建该分类下具体条目
    await user.click(screen.getByTestId('world-cat-add'));

    // RED：当前实现 onAddCategory 恒开 world-cat-dialog（创建分类）→ 下面断言 FAIL
    expect(screen.getByTestId('library-create-dialog')).toBeInTheDocument();
    expect(screen.queryByTestId('world-cat-dialog')).not.toBeInTheDocument();
  });

  it('③ 分类删除：已创建分类 chip 有删除入口；点击 → DELETE /api/v1/world-categories/{id} + 从列表移除', async () => {
    seedWorldCategories([{ id: 'wc1', name: '秘境', count: 1 }]);
    const user = userEvent.setup();
    renderLibrary();
    await goWorldTab(user);

    // 分类 chip 渲染删除入口（#641：当前实现无删除按钮 → getByTestId FAIL）
    const delBtn = screen.getByTestId('world-cat-delete-秘境');
    await user.click(delBtn);
    await waitFor(() => {
      expect(
        apiFetchMock.mock.calls.some(
          (c) => c[0] === '/api/v1/world-categories/wc1' && c[1]?.method === 'DELETE',
        ),
      ).toBe(true);
    });
    // 删除成功后该分类 chip 从列表移除
    await waitFor(() => {
      expect(screen.queryByTestId('world-cat-filter-秘境')).not.toBeInTheDocument();
    });
  });
});
