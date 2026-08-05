/**
 * 工程冒烟测试（TDD 起点，Issue #105 升级：导航从顶栏三链接 → 侧边栏四入口）
 * 断言: App 挂载渲染品牌 + 四路由可达（HashRouter 在 jsdom 下正常）
 *
 * ⚠️ 本文件 = 契约（#105 导航重构升级）。GREEN 实现（App.tsx + components/AppNav.tsx）必须匹配：
 * - 侧边导航容器 data-testid="app-nav"（不再是顶栏导航）
 * - 四个主入口 link 位于 app-nav 内，可访问名 = t('nav.writing'|'nav.projects'|'nav.library'|'nav.settings')
 *   （「写作 / 项目 / 设定库 / 设置」；i18n 新 key nav.library / nav.settings 由 GREEN 补 zh.ts/en.ts）
 * - 默认路由（/）→ 项目页（「我的项目」标题，既有契约）
 * - 点击侧边「写作」→ 写作页（editor testid，既有契约）
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from './App';
import { apiFetch } from './api/client';
import { useProjectStore } from './stores/project';
import { useChapterStore } from './stores/chapter';
import { useThemeStore } from './stores/theme';

vi.mock('./api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  // HashRouter 依赖 window.location.hash——测试间导航会残留 hash，必须重置（App.routing.test.tsx 先例）
  window.location.hash = '';
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  useChapterStore.setState({ volumes: [], chapters: [], currentChapterId: null, content: '', loading: false, error: null });
  // 种子项目 p1：写作页挂载回退首个项目渲染 editor（冒烟确定性，与 App.routing.test.tsx 同源）
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === '/api/v1/projects' && (!init?.method || init.method === 'GET')) {
      return {
        items: [{
          id: 'p1', name: '青云志', genre: '玄幻', language: 'zh-CN', target_words: 800000, config: {},
          created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
        }],
        total: 1, offset: 0, limit: 50,
      };
    }
    if (path === '/api/v1/projects/p1/chapters') return { items: [], total: 0, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/volumes') return { items: [] };
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

describe('App 骨架', () => {
  it('渲染品牌与侧边四导航入口', async () => {
    render(<App />);
    // 消化 loadProjects 异步 setState（避免 act 警告噪音，App.header.test.tsx 先例）
    await waitFor(() => expect(useProjectStore.getState().loading).toBe(false));
    expect(screen.getByText('InkFlow')).toBeInTheDocument();
    const nav = screen.getByTestId('app-nav');
    expect(within(nav).getByRole('link', { name: '写作' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: '项目' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: '设定库' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: '设置' })).toBeInTheDocument();
  });

  it('默认路由显示项目页', async () => {
    render(<App />);
    await waitFor(() => expect(useProjectStore.getState().loading).toBe(false));
    expect(screen.getByRole('heading', { name: '我的项目' })).toBeInTheDocument();
  });

  it('点击侧边导航「写作」切换到写作页', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('link', { name: '写作' }));
    expect(screen.getByTestId('editor')).toBeInTheDocument();
  });
});
