/**
 * #1494 世界观页首开语义（#1481/PR #1491 建项目自动建根之后——「一项目一根」从**至多一根**
 * 收紧为**恒有且仅有一个根**）。
 *
 * 事实：新项目恒有 1 个默认根（后端常量 name、`parent_id=null`、`category=""`），世界观页首开
 * 不再是空态，而是一个孤立根节点 → 本轨只改**前端首屏/空态语义**，**零后端改动**。
 *
 * RED 契约（当前实现 FAIL，逐条实测留证）：
 *  ① 首开显示默认根（**非空态**）且根**自动选中高亮**（`data-selected="1"`）+ 根下**引导行**
 *     （`world-first-open-hint` = 「展开」的可见形态）；
 *  ② 根标题按**结构判据 isRoot** 渲染本地化文案（英文界面 = `World Overview`），**不匹配 name**
 *     → 把根改名后本地化仍生效（不直显用户改的名字）；
 *  ③ 已有分类时引导行 CTA = 「新建条目」→ 打开 `LibraryCreateDialog` 且为**非根**语义
 *     （「类别」输入在场 + 空值时 `library-create-category-required` 红字 + 保存禁用 → 不直送 4xx）。
 * 守护契约（当前 PASS，修复后须保持）：
 *  ④ 根被删且无子条目 → 空态 `library-tab-empty` 仍可达（D1(b) 保留空态定义）；
 *  ⑤ 根**有子条目**时高亮与引导行均不渲染（首开语义只对空根生效）。
 *
 * mock 结构仿 library-world-root-create.test.tsx（#741）：apiFetch vi.mock + store 播种。
 * 用 `?cat=world` 直达 tab（避免依赖 tab 文案随语言变化）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
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
  id: 'p1', name: '项目甲', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, config: {},
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};

function renderLibrary(initialPath = '/library?cat=world') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <LibraryPage />
      <Routes>
        <Route path="/projects" element={<div data-testid="projects-probe" />} />
      </Routes>
    </MemoryRouter>,
  );
}

/** #1494 seed：world-settings 返回 items（新项目 = 只有 1 个默认根）；world-categories 返回 cats。 */
function seedWorld(
  items: Array<{ id: string; name: string; parent_id: string | null; category: string; content?: string }>,
  cats: Array<{ id: string; name: string; count?: number }> = [],
) {
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
    if (path.startsWith('/api/v1/projects/p1/world-settings')) return { items, total: items.length, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/world-categories') return { items: cats, total: cats.length, offset: 0, limit: 50 };
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
}

/** 默认根条目（后端 #1481 建项目自动建根产物） */
const ROOT = { id: 'w1', name: '世界观总纲', parent_id: null, category: '', content: '' };

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1', loading: false, error: null });
  useToastStore.setState({ toasts: [] });
});

describe('设定库页 — 世界观首开语义（#1494）', () => {
  it('① 首开（零分类）：显示默认根（非空态）+ 根自动选中高亮 + 根下引导行 CTA = 新建分类', async () => {
    seedWorld([ROOT], []);
    renderLibrary();
    await waitFor(() => expect(screen.getByTestId('library-list')).toBeInTheDocument());

    // 非空态：根恒在 → 空态不可达
    expect(screen.queryByTestId('library-tab-empty')).not.toBeInTheDocument();

    // 根行：结构标记 + 自动选中高亮
    const root = screen.getByTestId('world-node-root');
    expect(root).toHaveAttribute('data-root', '1');
    expect(root).toHaveAttribute('data-selected', '1');

    // 根下引导行（= 「展开」的可见形态）
    const hint = screen.getByTestId('world-first-open-hint');
    expect(hint).toHaveTextContent('世界观总纲');
    // 零分类：CTA 引导先建分类（后端非根条目分类须为已注册分类，直开条目框 = 422）
    expect(within(hint).getByTestId('world-first-open-cta')).toHaveTextContent('新建分类');
  });

  it('② 根标题本地化（D3c）：英文界面显示 World Overview，且根改名后仍本地化（不匹配 name）', async () => {
    useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'en' });
    seedWorld([{ ...ROOT, name: '我改的名字' }], []);
    renderLibrary();
    await waitFor(() => expect(screen.getByTestId('library-list')).toBeInTheDocument());

    expect(screen.getByTestId('world-node-title-w1')).toHaveTextContent('World Overview');
    // 不匹配 name：改名后本地化仍生效（不回显用户改定的名字）
    expect(screen.queryByText('我改的名字')).not.toBeInTheDocument();
  });

  it('③ 首开（已有分类）：引导行 CTA = 新建条目 → 对话框为非根语义（类别必填 + 红字 + 保存禁用）', async () => {
    seedWorld([ROOT], [{ id: 'wc1', name: '秘境', count: 0 }]);
    const user = userEvent.setup();
    renderLibrary();
    await waitFor(() => expect(screen.getByTestId('world-first-open-hint')).toBeInTheDocument());

    const cta = screen.getByTestId('world-first-open-cta');
    expect(cta).toHaveTextContent('新建条目');
    await user.click(cta);

    // 非根语义：类别输入在场 + 空值红字 + 保存禁用 → 不会把用户直送 4xx
    expect(screen.getByTestId('library-create-dialog')).toBeInTheDocument();
    expect(screen.getByLabelText('类别')).toBeInTheDocument();
    expect(screen.getByTestId('library-create-category-required')).toBeInTheDocument();
    expect(screen.getByTestId('library-create-save')).toBeDisabled();
  });

  it('④ 守护：根被删且无子条目 → 空态 library-tab-empty 仍可达（D1(b) 保留空态定义）', async () => {
    seedWorld([], []);
    renderLibrary();
    expect(await screen.findByTestId('library-tab-empty')).toBeInTheDocument();
  });

  it('⑤ 守护：根有子条目 → 根不高亮、引导行不渲染（首开语义只对空根生效）', async () => {
    seedWorld(
      [ROOT, { id: 'w2', name: '地点甲', parent_id: 'w1', category: '地理', content: '' }],
      [{ id: 'wc1', name: '地理', count: 1 }],
    );
    renderLibrary();
    await waitFor(() => expect(screen.getByTestId('library-list')).toBeInTheDocument());

    const root = screen.getByTestId('world-node-root');
    expect(root).toHaveAttribute('data-root', '1');
    expect(root).not.toHaveAttribute('data-selected');
    expect(screen.queryByTestId('world-first-open-hint')).not.toBeInTheDocument();
  });
});
