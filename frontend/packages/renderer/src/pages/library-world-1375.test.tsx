/**
 * #1375 世界观条目页四处（①创建按钮语义拆分 / ②分类栏并集+待注册+一键注册 / ④× 移入框内）——页面级契约。
 *
 * 覆盖（issue #1375 + specs/f19-gui/world.md N11/N12/N13，已拍板 2026-09-22 ①A+②A+④）：
 *   ① world-cat-add「新建分类」恒开分类对话框（不随选中分类改变语义——#568 语义切换退役）；
 *      world-cat-add-entry「新建条目」选中分类时启用、未选中禁用（title「请先选择分类」）；
 *      world 分支移除「去创建」（library-create-btn，由新建条目钮承担）
 *   ② 分类栏 = 已注册分类 ∪ 条目实际使用类别（并集）；未注册类别 = 虚线 chip +「待注册」注记
 *      + ＋ 一键注册（POST world-categories，默认抽象类）
 *   ④ 分类 chip 的 × 在圆角框内（DOM 内嵌于 chip 容器）+ 未 hover 隐藏（opacity-0 → group-hover:opacity-100）
 *
 * RED 预期（实现前）：world-cat-add-entry / world-cat-chip-* / world-cat-register-* 均不存在 → getByTestId 失败。
 * 可证伪自证：去掉 ② 并集逻辑（pending 恒空）→ 用例「② 分类栏并集」「② 一键注册」必须 FAIL。
 *
 * mock 结构仿 library-world-fixes.test.tsx（#641）：apiFetch vi.mock + stores 播种。
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

/**
 * #1375 seed：根「世界观」+ 三个子条目——「青云山」category=地理（已注册）、
 * 「祭剑大典」category=文化（**未注册** → ②A 待注册并集来源）、
 * 「东荒」category=地图（保留类别 → **不进并集**：#389 地图归地图工作台，列表页不渲染该 chip）。
 * world-categories 只含「地理」；POST /world-categories 追加（一键注册断言 POST body + chips 转正式）。
 */
function seedWorld() {
  const items = [
    { id: 'w1', name: '世界观', parent_id: null, category: '', content: '', created_at: '', updated_at: '' },
    { id: 'w2', name: '青云山', parent_id: 'w1', category: '地理', content: '', created_at: '', updated_at: '' },
    { id: 'w3', name: '祭剑大典', parent_id: 'w1', category: '文化', content: '', created_at: '', updated_at: '' },
    { id: 'w4', name: '东荒', parent_id: 'w1', category: '地图', content: '', created_at: '', updated_at: '' },
  ];
  const categories: Array<{ id: string; name: string; kind?: string; count?: number }> = [
    { id: 'wc1', name: '地理', kind: 'geo', count: 1 },
  ];
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
    if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
    if (path.startsWith('/api/v1/projects/p1/world-settings')) return { items, total: items.length, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/world-categories' && init?.method === 'POST') {
      const cat = {
        id: `wc${categories.length + 1}`,
        name: (init.body as { name: string }).name,
        kind: (init.body as { kind?: string }).kind,
        count: 0,
      };
      categories.push(cat);
      return { ...cat, project_id: 'p1' };
    }
    if (path === '/api/v1/projects/p1/world-categories') {
      return { items: categories.map((c) => ({ ...c })), total: categories.length, offset: 0, limit: 50 };
    }
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

describe('设定库页 — 世界观条目页四处（#1375）', () => {
  it('① 新建分类恒开分类对话框：选中分类后点 world-cat-add 仍开 world-cat-dialog（语义不再随选中态切换）', async () => {
    seedWorld();
    const user = userEvent.setup();
    renderLibrary();
    await goWorldTab(user);
    // 选中「地理」分类 chip → #568 旧语义下 world-cat-add 会切成建条目；#1375 ①A 恒为建分类
    await user.click(screen.getByTestId('world-cat-filter-地理'));
    await user.click(screen.getByTestId('world-cat-add'));
    expect(screen.getByTestId('world-cat-dialog')).toBeInTheDocument();
    // 反向：不得打开建条目对话框（#568 语义切换已退役）
    expect(screen.queryByTestId('library-create-dialog')).not.toBeInTheDocument();
  });

  it('① 新建条目：未选中分类禁用（title 提示）；选中分类启用 → 点击开建条目对话框且类别预填', async () => {
    seedWorld();
    const user = userEvent.setup();
    renderLibrary();
    await goWorldTab(user);
    // 未选中分类 → 禁用 + 提示先选分类
    const entry = screen.getByTestId('world-cat-add-entry');
    expect(entry).toBeDisabled();
    expect(entry).toHaveAttribute('title', '请先选择分类');
    // 选中「地理」→ 启用
    await user.click(screen.getByTestId('world-cat-filter-地理'));
    expect(screen.getByTestId('world-cat-add-entry')).not.toBeDisabled();
    // 点击 → 建条目对话框（LibraryCreateDialog），类别预填选中分类名
    await user.click(screen.getByTestId('world-cat-add-entry'));
    await waitFor(() => expect(screen.getByTestId('library-create-dialog')).toBeInTheDocument());
    expect(screen.getByLabelText('类别')).toHaveValue('地理');
    expect(screen.getByTestId('library-create-dialog')).toHaveTextContent('创建分类');
  });

  it('① world 分支移除「去创建」：选中分类时 library-create-btn 不渲染（入口由新建条目钮承担）', async () => {
    seedWorld();
    const user = userEvent.setup();
    renderLibrary();
    await goWorldTab(user);
    await user.click(screen.getByTestId('world-cat-filter-地理'));
    expect(screen.queryByTestId('library-create-btn')).not.toBeInTheDocument();
  });

  it('② 分类栏并集：条目使用但未注册的类别（文化）显示为虚线 chip +「待注册」注记 + 一键注册 ＋', async () => {
    seedWorld();
    const user = userEvent.setup();
    renderLibrary();
    await goWorldTab(user);
    // 已注册「地理」= 正常 chip（无待注册标记、无 ＋）
    const geoChip = screen.getByTestId('world-cat-chip-地理');
    expect(geoChip).not.toHaveTextContent('待注册');
    expect(screen.queryByTestId('world-cat-register-地理')).not.toBeInTheDocument();
    // 未注册「文化」→ 并集 chip + 虚线 + 注记 + ＋
    const cultureChip = screen.getByTestId('world-cat-chip-文化');
    expect(cultureChip.className).toContain('border-dashed');
    expect(cultureChip).toHaveTextContent('待注册');
    expect(screen.getByTestId('world-cat-register-文化')).toBeInTheDocument();
    // 反向：待注册 chip 无删除 ×（未注册无删除语义）
    expect(screen.queryByTestId('world-cat-delete-文化')).not.toBeInTheDocument();
    // #389 既有契约守护：保留类别「地图」（条目已使用）不进并集——地图归地图工作台，列表页不渲染该 chip
    expect(screen.queryByTestId('world-cat-filter-地图')).not.toBeInTheDocument();
  });

  it('② 一键注册：点 ＋ → POST world-categories（默认 kind=abstract）→ chip 转正式样式（注记/＋ 消失）', async () => {
    seedWorld();
    const user = userEvent.setup();
    renderLibrary();
    await goWorldTab(user);
    await user.click(screen.getByTestId('world-cat-register-文化'));
    await waitFor(() => {
      const postCall = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/projects/p1/world-categories' && c[1]?.method === 'POST',
      );
      expect(postCall).toBeTruthy();
      expect((postCall![1]!.body as { name: string }).name).toBe('文化');
      expect((postCall![1]!.body as { kind?: string }).kind).toBe('abstract');
    });
    // chip 转正式：待注册注记与 ＋ 消失、出现删除 ×
    await waitFor(() => {
      expect(screen.getByTestId('world-cat-chip-文化')).not.toHaveTextContent('待注册');
    });
    expect(screen.queryByTestId('world-cat-register-文化')).not.toBeInTheDocument();
    expect(screen.getByTestId('world-cat-delete-文化')).toBeInTheDocument();
  });

  it('② 待注册 chip 参与筛选：点「文化」→ aria-pressed 置位 + 树过滤到该类别条目', async () => {
    seedWorld();
    const user = userEvent.setup();
    renderLibrary();
    await goWorldTab(user);
    await user.click(screen.getByTestId('world-cat-filter-文化'));
    expect(screen.getByTestId('world-cat-filter-文化')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('library-list')).toHaveTextContent('祭剑大典');
    expect(screen.getByTestId('library-list')).not.toHaveTextContent('青云山');
  });

  it('④ 删除按钮在 chip 框内：× 与筛选按钮同属 chip 容器；未 hover 隐藏（opacity-0 + group-hover:opacity-100）', async () => {
    seedWorld();
    const user = userEvent.setup();
    renderLibrary();
    await goWorldTab(user);
    const chip = screen.getByTestId('world-cat-chip-地理');
    const filter = screen.getByTestId('world-cat-filter-地理');
    const del = screen.getByTestId('world-cat-delete-地理');
    // DOM 结构断言：× 内嵌于 chip 容器（框内），与筛选按钮同容器（旧实现为容器外兄弟节点）
    expect(chip.contains(filter)).toBe(true);
    expect(chip.contains(del)).toBe(true);
    // 悬停显现契约：默认透明、hover 显现
    expect(del.className).toContain('opacity-0');
    expect(del.className).toContain('group-hover:opacity-100');
  });
});
