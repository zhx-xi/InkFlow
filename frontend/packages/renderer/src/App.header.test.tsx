/**
 * App 顶栏职责回归契约（Issue #105 RED 阶段，spec §7.2 顶栏：品牌 + 页面标题 + 主题/语言/内核状态，
 * 不再承担导航；#98 既有契约保持）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 AppLayout 顶栏（role=banner）必须匹配：
 *
 * - 品牌保留（#98 契约不删）：装饰性 logo <img>（alt="" + aria-hidden="true"，
 *   src 非 data: 且含 inkflow-icon-plain，主题三版切换属视觉契约）+ t('app.brand')「InkFlow」文字
 * - 页面标题在顶栏：当前路由页面标题（默认 /projects → t('pj.title')「我的项目」）；
 *   顶栏标题用**文本元素**（span/div，不用 heading 标签）——保持正文 h1 的 getByRole('heading') 契约唯一
 * - 导航移出顶栏：banner 内无任何 role=link；导航在侧边栏（data-testid="app-nav"，
 *   可访问名「写作/项目/设定库/设置」= t('nav.writing'|'nav.projects'|'nav.library'|'nav.settings')）
 * - 全局状态控件在顶栏：
 *   - 主题切换按钮 data-testid="header-theme-toggle"：点击触发 themeStore.setTheme（paper → 非 paper）
 *   - 语言控件 data-testid="header-lang"：显示当前语言（lang=zh → t('lang.zh')「中文」）
 *   - 内核状态：t('sb.kernel')「内核已连接」
 * - 既有断言保持：无「paper / zh」调试文本
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from './App';
import { apiFetch } from './api/client';
import { useProjectStore } from './stores/project';
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
  // 空列表即可——顶栏断言与项目列表内容无关
  apiFetchMock.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
});

describe('App 顶栏 — 职责回归：品牌 + 页面标题 + 全局状态（#105 §7.2）', () => {
  it('顶栏不渲染 {theme} / {lang} 调试文本（「paper / zh」不得出现）', async () => {
    render(<App />);
    // 等 loadProjects 完成（消化异步 setState，避免 act 警告）
    await waitFor(() => expect(useProjectStore.getState().loading).toBe(false));
    expect(screen.queryByText('paper / zh')).not.toBeInTheDocument();
  });

  it('品牌 logo 渲染：顶栏内 <img> 存在（装饰性 alt="" + aria-hidden，语义由文字承载）', async () => {
    render(<App />);
    await waitFor(() => expect(useProjectStore.getState().loading).toBe(false));
    const banner = screen.getByRole('banner');
    // aria-hidden 元素不在可访问性树——用 DOM 查询断言存在性（评审 F7：装饰性图标）
    const logo = banner.querySelector('img')!;
    expect(logo).not.toBeNull();
    expect(logo).toHaveAttribute('aria-hidden', 'true');
    // #98 修复回归契约：logo 必须为**独立文件引用**（`?url&no-inline` import）——CSP default-src 'self'
    // 阻止 data: 内联 svg（生产破图，naturalWidth=0 三次实测）——src 不得为 data: 且含资产路径
    const src = logo.getAttribute('src') ?? '';
    expect(src).not.toContain('data:');
    expect(src).toMatch(/inkflow-icon-plain/);
    // Q3=C：图标 + 文字并存（t('app.brand') 保留）
    expect(within(banner).getByText('InkFlow')).toBeInTheDocument();
  });

  it('页面标题出现在顶栏（默认 /projects → 「我的项目」）', async () => {
    render(<App />);
    await waitFor(() => expect(useProjectStore.getState().loading).toBe(false));
    const banner = screen.getByRole('banner');
    // 顶栏标题 = t('pj.title')；文本元素（非 heading——正文 h1「我的项目」仍承担 heading 语义）
    expect(within(banner).getByText('我的项目')).toBeInTheDocument();
  });

  it('导航链接不在顶栏：banner 内无 role=link，导航已移至侧边栏', async () => {
    render(<App />);
    await waitFor(() => expect(useProjectStore.getState().loading).toBe(false));
    const banner = screen.getByRole('banner');
    // 顶栏不再承担导航（spec §7.2 顶栏职责回归）
    // queryAllByRole：RED 下 banner 含 3 个导航链接 → 长度断言失败（干净的结构缺失失败形态）
    expect(within(banner).queryAllByRole('link')).toHaveLength(0);
    // 导航在侧边栏 app-nav（四入口）
    const nav = screen.getByTestId('app-nav');
    expect(within(nav).getByRole('link', { name: '写作' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: '设定库' })).toBeInTheDocument();
  });

  it('顶栏全局状态控件：主题切换触发 setTheme + 语言展示 + 内核状态', async () => {
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(useProjectStore.getState().loading).toBe(false));
    const banner = screen.getByRole('banner');
    // 主题切换按钮：点击 → themeStore.setTheme（paper → 非 paper，循环/切换方向由实现定）
    const toggle = within(banner).getByTestId('header-theme-toggle');
    await user.click(toggle);
    expect(useThemeStore.getState().theme).not.toBe('paper');
    // 语言控件：显示当前语言（zh → t('lang.zh')「中文」）
    expect(within(banner).getByTestId('header-lang')).toHaveTextContent('中文');
    // 内核状态：t('sb.kernel')
    expect(within(banner).getByText('内核已连接')).toBeInTheDocument();
  });
});
