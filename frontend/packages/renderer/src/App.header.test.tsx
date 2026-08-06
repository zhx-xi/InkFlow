/**
 * App 顶栏契约（Issue #105 §7.2 顶栏职责回归 + #106 §8.2⑤ 顶栏主题/语言循环按钮 → Radix Select 契约升级）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 AppLayout 顶栏（role=banner）必须匹配：
 *
 * - 品牌保留（#98 契约不删）：装饰性 logo <img>（alt="" + aria-hidden="true"，
 *   src 非 data: 且含 inkflow-icon-plain，主题三版切换属视觉契约）+ t('app.brand')「InkFlow」文字
 * - 页面标题在顶栏：当前路由页面标题（默认 /projects → t('pj.title')「我的项目」）；
 *   顶栏标题用**文本元素**（span/div，不用 heading 标签）——保持正文 h1 的 getByRole('heading') 契约唯一
 * - 导航移出顶栏：banner 内无任何 role=link；导航在侧边栏（data-testid="app-nav"，
 *   可访问名「写作/项目/设定库/设置」= t('nav.writing'|'nav.projects'|'nav.library'|'nav.settings')）
 * - 全局状态控件在顶栏（#106 §8.2⑤ 契约升级，Q4=A 已拍板，2026-08-06）：
 *   - 主题 Radix Select：trigger data-testid="header-theme-select" + aria-label=t('ap.theme')「主题」
 *     （role=combobox）；选项 theme.paper/night/ink 三主题「素笺 · 纸张 / 夜航 · 深色 / 墨韵 · 东方」，
 *     展开可见全部选项；选择 → themeStore.setTheme（直达生效）
 *   - 语言 Radix Select：trigger data-testid="header-lang-select" + aria-label=t('ap.lang')「语言」
 *     （role=combobox）；选项 lang.zh/lang.en「中文 / EN」；选择 → themeStore.setLang（直达生效）
 *   - 与设置页联动：设置页常规分类主题 radio 切换 → 顶栏 Select 同步显示（共享 themeStore）
 *   - 循环按钮移除：header-theme-toggle / header-lang 不再存在
 *   - 内核状态：t('sb.kernel')「内核已连接」
 * - 既有断言保持：无「paper / zh」调试文本
 *
 * RED 预期（GREEN 前，2026-08-06 现状为循环按钮）：
 * - getByRole('combobox', { name: '主题'|'语言' }) → 找不到（按钮非 combobox）
 * - header-theme-select / header-lang-select testid 缺失
 * - header-theme-toggle / header-lang 仍存在 → queryByTestId 断言 FAIL
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
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
    expect(within(banner).queryAllByRole('link')).toHaveLength(0);
    // 导航在侧边栏 app-nav（四入口）
    const nav = screen.getByTestId('app-nav');
    expect(within(nav).getByRole('link', { name: '写作' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: '设定库' })).toBeInTheDocument();
  });
});

describe('App 顶栏 — 主题/语言 Radix Select 契约升级（#106 §8.2⑤，Q4=A）', () => {
  it('主题/语言为 combobox（aria-label 主题/语言 + 新 testid）+ 循环按钮移除 + 内核状态', async () => {
    render(<App />);
    await waitFor(() => expect(useProjectStore.getState().loading).toBe(false));
    const banner = screen.getByRole('banner');

    // combobox 语义 + aria-label（ap.theme / ap.lang 沿用）
    expect(within(banner).getByRole('combobox', { name: '主题' })).toBeInTheDocument();
    expect(within(banner).getByRole('combobox', { name: '语言' })).toBeInTheDocument();
    // 新 testid 契约（§8.2⑤）
    expect(within(banner).getByTestId('header-theme-select')).toBeInTheDocument();
    expect(within(banner).getByTestId('header-lang-select')).toBeInTheDocument();
    // 循环按钮移除（RED：现状仍存在 → FAIL）
    expect(within(banner).queryByTestId('header-theme-toggle')).not.toBeInTheDocument();
    expect(within(banner).queryByTestId('header-lang')).not.toBeInTheDocument();
    // 内核状态保留
    expect(within(banner).getByText('内核已连接')).toBeInTheDocument();
  });

  it('主题 Select：回读当前主题 + 展开可见全部选项（三主题）+ 选择直达生效（setTheme）', async () => {
    act(() => {
      useThemeStore.setState({ theme: 'night', bg: 'default' });
    });
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(useProjectStore.getState().loading).toBe(false));
    const banner = screen.getByRole('banner');
    const themeSelect = within(banner).getByTestId('header-theme-select');

    // 回读：trigger 显示当前主题
    expect(themeSelect).toHaveTextContent(/夜航/);

    // 展开可见全部选项（M5b：三主题）
    await user.click(themeSelect);
    expect(await screen.findByRole('option', { name: '素笺 · 纸张' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '夜航 · 深色' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '墨韵 · 东方' })).toBeInTheDocument();

    // 选择直达生效（M5b：选择 → setTheme）
    await user.click(screen.getByRole('option', { name: '素笺 · 纸张' }));
    expect(useThemeStore.getState().theme).toBe('paper');
    expect(within(banner).getByTestId('header-theme-select')).toHaveTextContent(/素笺/);
  });

  it('语言 Select：展开可见全部选项（双语）+ 选择直达生效（setLang）', async () => {
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(useProjectStore.getState().loading).toBe(false));
    const banner = screen.getByRole('banner');
    const langSelect = within(banner).getByTestId('header-lang-select');

    // 回读：zh → 中文
    expect(langSelect).toHaveTextContent('中文');

    // 展开可见全部选项（M5b：双语）
    await user.click(langSelect);
    expect(await screen.findByRole('option', { name: '中文' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'EN' })).toBeInTheDocument();

    // 选择直达生效（M5b：选择 → setLang）
    await user.click(screen.getByRole('option', { name: 'EN' }));
    expect(useThemeStore.getState().lang).toBe('en');
    expect(within(banner).getByTestId('header-lang-select')).toHaveTextContent('English');
  });

  it('与设置页联动：设置页常规分类主题 radio 切换 → 顶栏 Select 同步显示（共享 themeStore）', async () => {
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(useProjectStore.getState().loading).toBe(false));

    // 侧边导航 → 设置页（默认常规分类）
    const nav = screen.getByTestId('app-nav');
    await user.click(within(nav).getByRole('link', { name: '设置' }));

    // 常规分类主题 radio → 夜航
    await user.click(await screen.findByRole('radio', { name: /夜航/ }));
    expect(useThemeStore.getState().theme).toBe('night');

    // 顶栏 Select 同步（M5b：改设置页后顶栏同步）
    const banner = screen.getByRole('banner');
    expect(within(banner).getByTestId('header-theme-select')).toHaveTextContent(/夜航/);
  });
});
