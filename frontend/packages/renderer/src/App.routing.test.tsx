/**
 * App 路由集成测试（Issue #79 RED 阶段，spec §4.2 路由：HashRouter 三页 + 默认 /projects）
 *
 * ⚠️ 本文件 = 契约。断言三页经真实 App（HashRouter + 顶栏导航）联通：
 * - 默认路由（/）→ 项目页：项目列表加载并渲染卡片（依赖 loadProjects → RED）
 * - 导航「写作」→ 写作页：编辑器 + 项目树卷/章渲染（依赖写作页挂载加载树 → RED）
 * - 导航「Agent 配置」→ Agent 页：模型接入卡片（依赖 §4.2.3 结构 → RED）
 * - 回到「项目」→ 项目页仍在
 *
 * 与既有 App.test.tsx（冒烟，保持绿）互补：本文件断言渲染层真实契约。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
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

const seedVolumes = [{ id: 'v1', title: '第一卷 风起', order_index: 0 }];
const seedChapters = [
  { id: 'c1', title: '第1章 初见', volume_id: 'v1', order_index: 0, word_count: 2347 },
  { id: 'c2', title: '第2章 夜谈', volume_id: 'v1', order_index: 1, word_count: 0 },
];

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  // HashRouter 依赖 window.location.hash——测试间导航会残留 hash（如 #/agents），
  // 必须重置，否则后续测试初始路由漂移（三页往返测试实测 #/agents 残留导致 project-card 找不到）
  window.location.hash = '';
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  useChapterStore.setState({ volumes: [], chapters: [], currentChapterId: null, content: '', loading: false, error: null });

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
    if (path === '/api/v1/projects/p1/chapters') return { items: seedChapters, total: 2, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/volumes') return { items: seedVolumes };
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

describe('App 路由集成（HashRouter 三页）', () => {
  it('默认路由显示项目页：加载项目列表并渲染卡片', async () => {
    render(<App />);
    expect(screen.getByRole('heading', { name: '我的项目' })).toBeInTheDocument();
    // 项目列表异步加载 → 卡片出现（RED：占位页无 loadProjects）
    expect(await screen.findByTestId('project-card')).toHaveTextContent('青云志');
  });

  it('导航「写作」→ 写作页：三栏 + 项目树卷/章渲染', async () => {
    const user = userEvent.setup();
    render(<App />);
    // 写作页挂载后加载当前项目卷章树（契约：写作页挂载自动 loadChapterTree）
    await user.click(screen.getByRole('link', { name: '写作' }));
    expect(screen.getByTestId('editor')).toBeInTheDocument();
    expect(screen.getByTestId('project-tree')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId('project-tree')).toHaveTextContent('第一卷 风起');
      expect(screen.getByTestId('project-tree')).toHaveTextContent('第1章 初见');
    });
  });

  it('导航「Agent 配置」→ Agent 页：模型接入卡片渲染', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('link', { name: 'Agent 配置' }));
    expect(screen.getByRole('heading', { name: 'Agent 与模型配置' })).toBeInTheDocument();
    expect(screen.getByTestId('agent-llm-card')).toBeInTheDocument();
    expect(screen.getByTestId('agent-chain-card')).toBeInTheDocument();
    expect(screen.getByTestId('agent-appearance-card')).toBeInTheDocument();
  });

  it('三页往返导航：项目 → 写作 → Agent → 项目', async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByTestId('project-card');

    await user.click(screen.getByRole('link', { name: '写作' }));
    expect(screen.getByTestId('editor')).toBeInTheDocument();

    await user.click(screen.getByRole('link', { name: 'Agent 配置' }));
    expect(screen.getByTestId('agent-llm-card')).toBeInTheDocument();

    await user.click(screen.getByRole('link', { name: '项目' }));
    expect(screen.getByRole('heading', { name: '我的项目' })).toBeInTheDocument();
    expect(await screen.findByTestId('project-card')).toBeInTheDocument();
  });
});
