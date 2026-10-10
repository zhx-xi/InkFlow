/**
 * 设定库页「AI 提取」入口 RED 契约测试（#652）。
 *
 * 【契约（父侧定稿；#1544 迁移：章节下拉 → 类型/范围选择）】
 * - library.tsx 工具栏新增按钮 data-testid='extract-entry-lib'（「AI 提取」，位于「新建」右侧）
 * - 仅当已选项目（currentProjectId 非 null）时渲染；点击 → 打开 AIExtractDialog
 * - dialog 打开时拉取章节列表 GET /api/v1/projects/{pid}/chapters + 卷列表
 *   GET /api/v1/projects/{pid}/volumes + 运行记录
 *   GET /api/v1/projects/{pid}/extractions/runs（镜像 AIExtractDialog 契约）
 *
 * 【RED 预期失败形态】extract-entry-lib 不存在（library.tsx 未加按钮 / AIExtractDialog 未挂载）
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
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

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname}{location.search}</div>;
}

function renderLibrary() {
  return render(
    <MemoryRouter initialEntries={['/library']}>
      <LibraryPage />
      <Routes>
        <Route path="/projects" element={<LocationProbe />} />
        <Route path="/writing" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useToastStore.setState({ toasts: [] });
  useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1', loading: false, error: null });
  // 镜像 library 页分类数据 + AIExtractDialog 的章节/运行记录
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
    if (path.startsWith('/api/v1/projects/p1/characters')) return { items: [{ id: 'c1', name: '林晚' }], total: 1, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/chapters')
      return { items: [{ id: 'ch1', title: '第三章 青云之巅', volume_id: null, order_index: 3, word_count: 3200 }], total: 1, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/extractions/runs') return { items: [], total: 0, offset: 0, limit: 50 };
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

describe('设定库页 — 「AI 提取」入口（#652）', () => {
  it('契约1：已选项目时工具栏渲染「AI 提取」按钮（extract-entry-lib）', async () => {
    renderLibrary();
    // 先等列表加载（确认页面进入项目态）
    await waitFor(() => expect(screen.getByTestId('library-list')).toBeInTheDocument());
    const btn = screen.getByTestId('extract-entry-lib');
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveTextContent(/AI 提取/);
  });

  it('契约2：点击「AI 提取」→ 打开 AIExtractDialog（拉取章节列表）', async () => {
    const user = userEvent.setup();
    renderLibrary();
    await waitFor(() => expect(screen.getByTestId('library-list')).toBeInTheDocument());
    await user.click(screen.getByTestId('extract-entry-lib'));
    // Dialog 打开：ai-extract-dialog 出现 + 类型单选渲染 + 拉取章节端点被调用
    const dlg = await screen.findByTestId('ai-extract-dialog');
    expect(within(dlg).getByText('AI 提取')).toBeInTheDocument();
    // #1544 迁移：旧 ai-extract-chapter 下拉已由「类型单选 + 范围选择」取代
    expect(within(dlg).getByTestId('ai-extract-type')).toBeInTheDocument();
    await waitFor(() => {
      expect(apiFetchMock.mock.calls.some((c) => c[0] === '/api/v1/projects/p1/chapters')).toBe(true);
      expect(apiFetchMock.mock.calls.some((c) => c[0] === '/api/v1/projects/p1/extractions/runs')).toBe(true);
    });
  });

  // ═══════════════════════════════════════════════════════════════════════════
  // #1566：弹框默认类型随来源页（同一实例跨分类复用 → 每次打开都要按当前页重置）
  // ═══════════════════════════════════════════════════════════════════════════
  it('契约3（#1566）：默认类型随来源页——角色页打开是「角色」，切到时间线页重开是「时间线」', async () => {
    const user = userEvent.setup();
    renderLibrary();
    await waitFor(() => expect(screen.getByTestId('library-list')).toBeInTheDocument());

    // 默认分类（角色）→ 「角色」
    await user.click(screen.getByTestId('extract-entry-lib'));
    let dlg = await screen.findByTestId('ai-extract-dialog');
    expect(
      within(within(dlg).getByTestId('ai-extract-type')).getByRole('radio', { name: '角色' }),
    ).toBeChecked();
    await user.click(within(dlg).getByRole('button', { name: '关闭' }));

    // 切到时间线分类（同一 AIExtractEntry 实例）→ 重开 → 「时间线」
    await user.click(within(screen.getByTestId('library-tabs')).getByRole('tab', { name: '时间线' }));
    await user.click(screen.getByTestId('extract-entry-lib'));
    dlg = await screen.findByTestId('ai-extract-dialog');
    expect(
      within(within(dlg).getByTestId('ai-extract-type')).getByRole('radio', { name: '时间线' }),
    ).toBeChecked();
  });

  it('契约4（#1566）：5 个分类页各自打开 → 默认选中对应类型', async () => {
    const user = userEvent.setup();
    const cases: Array<[string, string]> = [
      ['角色', '角色'],
      ['世界观', '世界观'],
      ['时间线', '时间线'],
      ['伏笔', '伏笔'],
      ['知识图谱', '知识图谱'],
    ];
    for (const [tab, kind] of cases) {
      const { unmount } = renderLibrary();
      await waitFor(() => expect(screen.getByTestId('library-list')).toBeInTheDocument());
      await user.click(within(screen.getByTestId('library-tabs')).getByRole('tab', { name: tab }));
      await user.click(screen.getByTestId('extract-entry-lib'));

      const dlg = await screen.findByTestId('ai-extract-dialog');
      expect(
        within(within(dlg).getByTestId('ai-extract-type')).getByRole('radio', { name: kind }),
        tab,
      ).toBeChecked();
      unmount();
    }
  });
});
