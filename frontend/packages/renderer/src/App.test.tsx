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
 *
 * ⚠️ F32 设置持久化（#152，spec §5.2 步骤 ②）扩展（2026-08-08）——设计假设清单：
 * - App.tsx AppLayout 挂载 useEffect → useThemeStore.initFromBackend()（恰好一次，依赖 []）
 * - 本文件新增用例以「渲染前替换 store action」断言调用（zustand selector 读 state 对象，
 *   替换必须先于 render；GREEN 补全 stores/theme.ts 后替换/恢复写法仍成立，cast 可删）
 * - apiFetch mock 增补 /api/v1/settings 分支：GREEN 后其余用例挂载 App 时真实
 *   initFromBackend 会经 fetchSettings → GET /api/v1/settings（防落入兜底 items 信封
 *   造成 theme=undefined 污染 store；RED 阶段该分支无调用方，零影响）
 * - RED 预期：GREEN 前 App.tsx 无 initFromBackend 调用 → initSpy 零调用 → waitFor 超时 FAIL；
 *   既有 3 用例保持绿
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
    // F32（#152）：settings 端点——GREEN 后其余用例挂载 App 时真实 initFromBackend 经
    // fetchSettings 拉取（防落入兜底 items 信封 → theme=undefined 污染 store）
    if (path === '/api/v1/settings') {
      return { theme: 'paper', bg: 'default', lang: 'zh', font: 'sans', close_behavior: 'tray', tray_hint_dismissed: false };
    }
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

/**
 * F32 设置持久化（#152，spec §5.2 步骤 ②）：AppLayout 挂载 → initFromBackend 调用契约。
 * RED 预期：GREEN 前 App.tsx 无 initFromBackend 调用 → initSpy 零调用 → waitFor 超时 FAIL。
 * 注意：渲染前替换 store action（AppLayout useEffect 经 selector/getState 读 state 对象）；
 * RED 阶段 store 无该方法 → 替换键为多余键（无害），GREEN 后为真实 action 替换。
 */
describe('App 骨架 — F32 设置加载（spec §5.2）', () => {
  it('AppLayout 挂载 → useThemeStore.initFromBackend 被调用（恰好一次，依赖空数组不重复触发）', async () => {
    type ThemeStateF32 = ReturnType<typeof useThemeStore.getState> & {
      initFromBackend: () => Promise<void>;
    };
    const original = (useThemeStore.getState() as ThemeStateF32).initFromBackend;
    const initSpy = vi.fn(async () => {});
    useThemeStore.setState({ initFromBackend: initSpy } as unknown as Partial<ThemeStateF32>);
    try {
      render(<App />);
      // GREEN 前零调用 → waitFor 超时 = RED；GREEN 后恰好一次（挂载 useEffect 依赖 []）
      await waitFor(() => expect(initSpy).toHaveBeenCalledTimes(1));
    } finally {
      useThemeStore.setState({ initFromBackend: original } as unknown as Partial<ThemeStateF32>);
    }
  });
});
