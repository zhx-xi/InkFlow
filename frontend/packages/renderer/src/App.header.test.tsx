/**
 * App 顶栏视觉打磨契约（Issue #98 RED 阶段，spec §5.2.7 差距 #1 + §5.2.8 品牌接入）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 AppLayout 顶栏必须匹配：
 *
 * - 移除 `{theme} / {lang}` 调试文本：theme=paper/lang=zh 时「paper / zh」不得渲染
 *   （现状 App.tsx L36-38 渲染 → RED 缺口）
 * - 品牌接入（Q3=C 拍板：图标 + 文字）：
 *   - 顶栏（role=banner）内渲染品牌 logo <img>（评审 F7：图标为装饰性，alt="" + aria-hidden，
 *     品牌语义由相邻文字承载——断言 img 存在而非可访问名）
 *   - 顶栏仍渲染「InkFlow」文字（t('app.brand')，既有 App.test.tsx 冒烟契约保持）
 * - 设计假设：logo 为 <img>（react 静态资源），不要求特定 src/文件名；
 *   主题变体切换（paper/night/ink → 三版 svg）属视觉契约（§5.5 M4，vision 走查），不在此断言
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
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

describe('App 顶栏 — 调试残留清理 + 品牌 logo（#98 §5.2.7/5.2.8）', () => {
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
});
