/**
 * #699 世界观分类 kind（geo/abstract）：chips 按类型显示图标（地理类 🗺 / 抽象类无）；「地图视图」入口仅地理类分类显示。
 * 从 library.test.tsx 拆出（library.test.tsx 超 900 行护栏），对齐 library-p*.test.tsx 先例。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
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
  id: 'p1', name: '青云志', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, config: {},
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname}{location.search}</div>;
}

function renderLibrary(initialPath = '/library') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
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
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  useToastStore.setState({ toasts: [] });
});

describe('设定库页 — 世界观分类 kind 图标 + 地图入口（#699）', () => {
  const cats = [
    { id: 'g1', name: '国家', kind: 'geo', count: 0 },
    { id: 'a1', name: '势力', kind: 'abstract', count: 0 },
  ];

  function mockWorld() {
    act(() => {
      useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1' });
    });
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects') return { items: [projectP1], total: 1, offset: 0, limit: 50 };
      if (path === '/api/v1/projects/p1/world-settings')
        return {
          items: [
            { id: 'w1', name: '九州', category: '', content: '', parent_id: null, created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-01T10:00:00Z' },
          ],
          total: 1, offset: 0, limit: 50,
        };
      if (path === '/api/v1/projects/p1/world-categories') return { items: cats, total: cats.length, offset: 0, limit: 50 };
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
  }

  it('分类 chips 按 kind 显示图标：地理类有 🗺，抽象类无', async () => {
    mockWorld();
    const user = userEvent.setup();
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    const geoChip = await screen.findByTestId('world-cat-filter-国家');
    const absChip = screen.getByTestId('world-cat-filter-势力');
    expect(geoChip).toHaveTextContent('🗺');
    expect(absChip).not.toHaveTextContent('🗺');
  });

  it('地图视图入口仅地理类分类显示：选中地理类显示，选中抽象类隐藏', async () => {
    mockWorld();
    const user = userEvent.setup();
    renderLibrary();
    await user.click(screen.getByRole('tab', { name: '世界观' }));
    await screen.findByTestId('world-cat-filter-国家');
    await user.click(screen.getByTestId('world-cat-filter-国家'));
    expect(screen.getByTestId('map-view-entry')).toBeInTheDocument();
    await user.click(screen.getByTestId('world-cat-filter-势力'));
    expect(screen.queryByTestId('map-view-entry')).not.toBeInTheDocument();
  });
});
