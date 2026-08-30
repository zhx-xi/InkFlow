/**
 * #741 世界观地图树三缺陷 — 缺陷①（页面级）：创建「根」世界观时隐藏「类别」输入框。
 *
 * 事实：LibraryCreateDialog 已有 isRoot prop（isRoot=true 时 L286 `{!isRoot && (<Field label={t('lib.create.category')}>...}`
 * 隐藏「类别」输入框），但调用方 pages/library.tsx（L783-797 `<LibraryCreateDialog ...>`）未传 isRoot →
 * 创建根世界观（未选分类 activeWorldCat===null、非编辑）时「类别」框仍显示。
 *
 * RED 契约（当前实现 FAIL）：世界观 tab 未选分类（activeWorldCat=null）空态创建根世界观 → 对话框不得渲染「类别」输入框。
 * 守护契约（当前 PASS，修复后须保持）：选中分类（activeWorldCat 非空）创建子条目 → 「类别」输入框正常渲染。
 *
 * mock 结构仿 library-world-fixes.test.tsx（#641）：apiFetch vi.mock + useProjectStore/useThemeStore/useToastStore 播种。
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

/** #741 seed：world-settings 返回 items（根世界观创建场景传 [] → 空态 CTA 是唯一创建入口）；world-categories 返回 cats。 */
function seedWorld(
  items: Array<{ id: string; name: string; parent_id: string | null; category: string }>,
  cats: Array<{ id: string; name: string; count?: number }> = [],
) {
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/world-settings') return { items, total: items.length, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/world-categories') return { items: cats, total: cats.length, offset: 0, limit: 50 };
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
}

/** 登录世界观 tab 并等待列表渲染（非空态场景） */
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

describe('设定库页 — 根世界观创建隐藏「类别」输入框（#741 缺陷①）', () => {
  it('未选分类（activeWorldCat=null）空态创建根世界观：对话框不渲染「类别」输入框（RED：library.tsx 未传 isRoot → 当前「类别」框出现）', async () => {
    seedWorld([], []);
    const user = userEvent.setup();
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    // 无根条目 → 空态 CTA（创建根世界观的唯一入口；world 空态无 library-list）
    await waitFor(() => expect(screen.getByTestId('library-tab-empty-cta')).toBeInTheDocument());
    await user.click(screen.getByTestId('library-tab-empty-cta'));

    // 对话框确实打开（world 创建表单：名称在场）
    expect(screen.getByTestId('library-create-dialog')).toBeInTheDocument();
    expect(screen.getByLabelText('名称')).toBeInTheDocument();

    // RED：当前 library.tsx L783-797 未传 isRoot → LibraryCreateDialog 默认 isRoot=undefined（falsy）
    // → L286 类别 Field 渲染 → queryByLabelText('类别') 命中 → 本断言 FAIL。
    // GREEN 契约：library.tsx 在「world + activeWorldCat===null + 非编辑」时传 isRoot=true → 类别框消失。
    expect(screen.queryByLabelText('类别')).not.toBeInTheDocument();
  });

  it('选中分类（activeWorldCat 非空）创建子条目：对话框渲染「类别」输入框（守护，修复后仍须保持）', async () => {
    seedWorld(
      [{ id: 'w1', name: '世界观', parent_id: null, category: '' }],
      [{ id: 'wc1', name: '秘境', count: 1 }],
    );
    const user = userEvent.setup();
    renderLibrary();
    await goWorldTab(user);
    // 选中分类 chip → activeWorldCat 置位 → 顶部「去创建」按钮出现（items.length>0 分支）
    await user.click(screen.getByTestId('world-cat-filter-秘境'));
    await user.click(screen.getByTestId('library-create-btn'));

    expect(screen.getByTestId('library-create-dialog')).toBeInTheDocument();
    // 非根创建（activeWorldCat 非空）→ 类别输入框必须存在（修复实现不得误伤此路径）
    expect(screen.getByLabelText('类别')).toBeInTheDocument();
  });
});
