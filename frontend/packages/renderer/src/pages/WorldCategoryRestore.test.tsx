/**
 * #588（2026-08-22 复验缺陷）：世界观已有根条目（parent_id===null）后无法创建子分类。
 *
 * 现状（#567 引入的隐藏逻辑）：hasRootWorld=true 时同时隐藏两处创建入口——
 *   - 列表态右上「新建」按钮 library-create-btn（library.tsx L600 `!(activeCat==='world' && hasRootWorld)`）
 *   - 世界观工具栏「新建分类」world-cat-add（WorldCatActionButtons showCreate={!hasRootWorld}）
 * → 根条目存在时用户无法继续创建条目（子分类/子世界观），树被锁死。
 *
 * 本文件为 #588 RED 契约，独立成文件：library.test.tsx #567 用例（L833-862）断言同场景「隐藏」，
 * 语义相反——同文件并存会造成双向矛盾（任一时刻必有一方 FAIL），故按
 * 「已有同场景避免重复语义」拆分。GREEN 时需翻转 #567 用例断言为「可见」。
 *
 * 契约（世界观点击 tab 后）：
 * - 有根条目：world-cat-add 与 library-create-btn 均可见（可创建子分类）→ 当前 RED FAIL
 * - 空世界观（无根条目）：创建入口存在（空态 CTA + 新建分类）→ 现状 PASS（守护）
 * - 有根条目：地图视图入口 map-view-entry 保留（非创建类视图入口）→ 现状 PASS（守护）
 *
 * mock 模式对齐 library.test.tsx / library-p2.test.tsx（MemoryRouter + useProjectStore 播种 +
 * apiFetchMock 分发 world-settings 端点）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
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
  id: 'p1', name: '青云志', genre: '玄幻', language: 'zh-CN', target_words: 800000, config: {},
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};

function renderLibrary(initialPath = '/library') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <LibraryPage />
      <Routes>
        <Route path="/projects" element={<div />} />
        <Route path="/writing" element={<div />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  useToastStore.setState({ toasts: [] }); // 防跨用例 toast 残留误判
  // 默认兜底：projects 单项目；world-settings/maps 空列表（用例内覆盖）
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

describe('设定库页 — 世界观根条目后仍可创建子分类（#588）', () => {
  /** 世界观端点返回已有根条目（parent_id=null，#567 单例语义：一项目一根） */
  function mockWorldWithRoot() {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/world-settings')
        return {
          items: [
            { id: 'w1', name: '世界观', parent_id: null, category: '', content: '公元 2048 年灵气复苏。', created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-01T10:00:00Z' },
          ],
          total: 1, offset: 0, limit: 50,
        };
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
  }

  it('#588 已有根世界观条目：新建分类入口仍可见（可创建子分类）', async () => {
    mockWorldWithRoot();
    const user = userEvent.setup();
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    // 根条目存在 → 树视图渲染（非空态）
    await waitFor(() => expect(screen.getByTestId('library-list')).toBeInTheDocument());
    // RED 核心：当前实现 hasRootWorld 隐藏两处创建入口 → 以下断言 FAIL
    // 工具栏「新建分类」（WorldCatActionButtons 容器内）
    expect(screen.getByTestId('world-cat-add')).toBeInTheDocument();
    // 列表态右上「新建」入口
    expect(screen.getByTestId('library-create-btn')).toBeInTheDocument();
    // 守护：地图视图入口保留（非创建类，不应受影响）
    expect(screen.getByTestId('map-view-entry')).toBeInTheDocument();
  });

  it('#588 空世界观（无根条目）：创建入口存在（空态 CTA + 新建分类）——现状守护', async () => {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    const user = userEvent.setup();
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    // 空态（beforeEach 默认 world-settings 空列表）
    await screen.findByTestId('library-tab-empty');
    // 空态 CTA「去创建」+ 世界观空态工具栏「新建分类」均为创建入口
    expect(screen.getByTestId('library-tab-empty-cta')).toBeInTheDocument();
    expect(screen.getByTestId('world-cat-add')).toBeInTheDocument();
  });
});
