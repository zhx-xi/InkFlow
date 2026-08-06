/**
 * App 路由集成测试（Issue #105 导航重构 RED 阶段，spec §7.2 信息架构：HashRouter 四页 + 侧边导航）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现（App.tsx 布局改造 + components/AppNav.tsx + pages/library.tsx +
 * pages/settings.tsx）必须匹配以下路由/testid/i18n key；既有 testid 契约
 * （project-card / editor / project-tree 等）不删不改。
 *
 * 路由（HashRouter；/agents 删除——spec §7.10 Q1=A 拍板）：
 *   /writing /projects /library /settings，默认 /
 *
 * 侧边导航（AppNav，容器 data-testid="app-nav"）：
 * - 四个主入口 link，可访问名 = t('nav.writing'|'nav.projects'|'nav.library'|'nav.settings')
 *   （「写作 / 项目 / 设定库 / 设置」；i18n 新 key nav.library / nav.settings 由 GREEN 补 zh.ts/en.ts）
 * - Agent 快捷入口：系统分组 link（data-testid="nav-item-agent"，可访问名「Agent」）→ 进入设置页 Agent 分类。
 *   ⚠️ #105 修复批契约：测试点击 link 本身（不再点 appnav-agent-shortcut 包装 div——App.tsx 不得有
 *   jsdom 专用事件委托；包装 div 仅作 testid 锚点，点击它不产生导航）
 *
 * 设定库页（pages/library.tsx，根 data-testid="library-page"）：
 * - 未选择项目空态：data-testid="library-empty" + 文案 t('lib.empty.title')（「选择或新建项目开始构建设定」）
 *   + 按钮 data-testid="library-go-projects"（t('lib.empty.goProjects')「前往项目页」）→ 点击回 /projects
 * - 项目选择器：data-testid="library-project-select"，aria-label「当前项目」（原生 <select> 或 Radix combobox；
 *   option 可访问名 = 项目名如「青云志」；原生 select 时 option value = 项目 id）
 * - 选择项目后：data-testid="library-breadcrumb" 含项目名与当前分类（如「设定库 · 青云志 / 角色」）
 *   + data-testid="library-tabs" 六分类 tab：角色/世界观/大纲/时间线/伏笔/知识库 RAG
 *   （i18n keys：lib.tab.characters / lib.tab.world / lib.tab.outline / lib.tab.timeline /
 *   lib.tab.foreshadow / lib.tab.rag）
 *
 * 设置页（pages/settings.tsx，根 data-testid="settings-page"）：
 * - 左侧分类导航 data-testid="settings-nav"，五分类文案：常规/模型/Agent/模板/账户
 *   （i18n keys：set.general / set.models / set.agent / set.templates / set.account）
 * - Agent 分类面板 data-testid="settings-agent-panel"（迁移自 AgentChainCard，四角色开关语义保留）
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

const seedVolumes = [{ id: 'v1', title: '第一卷 风起', order_index: 0 }];
const seedChapters = [
  { id: 'c1', title: '第1章 初见', volume_id: 'v1', order_index: 0, word_count: 2347 },
  { id: 'c2', title: '第2章 夜谈', volume_id: 'v1', order_index: 1, word_count: 0 },
];

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  // HashRouter 依赖 window.location.hash——测试间导航会残留 hash（如 #/settings），
  // 必须重置，否则后续测试初始路由漂移（#79 三页往返实测 #/agents 残留导致 project-card 找不到）
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

describe('App 路由集成（HashRouter 四页 + 侧边导航）', () => {
  it('默认路由显示项目页：加载项目列表并渲染卡片', async () => {
    render(<App />);
    expect(screen.getByRole('heading', { name: '我的项目' })).toBeInTheDocument();
    // 项目列表异步加载 → 卡片出现（RED：占位页无 loadProjects）
    expect(await screen.findByTestId('project-card')).toHaveTextContent('青云志');
  });

  it('侧边导航「写作」→ 写作页：三栏 + 项目树卷/章渲染', async () => {
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

  it('侧边导航「设定库」→ 设定库页：无项目空态 + 前往项目页按钮回项目页', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('link', { name: '设定库' }));
    const library = await screen.findByTestId('library-page');
    // 未选择项目空态（spec §7.3）
    expect(within(library).getByTestId('library-empty')).toHaveTextContent('选择或新建项目开始构建设定');
    // 前往项目页 → 路由切换回 /projects
    await user.click(within(library).getByTestId('library-go-projects'));
    expect(screen.getByRole('heading', { name: '我的项目' })).toBeInTheDocument();
  });

  it('设定库选择项目后：面包屑含项目名 + 六分类 tab 渲染', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('link', { name: '设定库' }));
    const library = await screen.findByTestId('library-page');
    // 项目选择器（当前项目下拉）：原生 select 或 Radix combobox 两分支兼容
    const selector = within(library).getByTestId('library-project-select');
    if (selector.tagName === 'SELECT') {
      await user.selectOptions(selector, 'p1');
    } else {
      await user.click(selector);
      await user.click(await screen.findByRole('option', { name: '青云志' }));
    }
    // 面包屑「设定库 · 项目名 / 分类」
    await waitFor(() => {
      expect(within(library).getByTestId('library-breadcrumb')).toHaveTextContent('青云志');
    });
    // 六分类 tab
    const tabs = within(library).getByTestId('library-tabs');
    for (const tab of ['角色', '世界观', '大纲', '时间线', '伏笔', '知识库 RAG']) {
      expect(within(tabs).getByText(tab)).toBeInTheDocument();
    }
  });

  it('侧边导航「设置」→ 设置页：五分类导航渲染', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('link', { name: '设置' }));
    const page = await screen.findByTestId('settings-page');
    expect(window.location.hash).toMatch(/settings/);
    const nav = within(page).getByTestId('settings-nav');
    for (const name of ['常规', '模型', 'Agent', '模板', '账户']) {
      expect(within(nav).getByText(name)).toBeInTheDocument();
    }
  });

  it('Agent 快捷入口 → 设置页 Agent 分类面板（点击 nav-item-agent link 本身）', async () => {
    const user = userEvent.setup();
    render(<App />);
    // #105 修复批契约：点击 link 本身（真实浏览器行为），不再依赖 App 层事件委托
    await user.click(screen.getByTestId('nav-item-agent'));
    expect(window.location.hash).toMatch(/settings/);
    expect(await screen.findByTestId('settings-page')).toBeInTheDocument();
    expect(await screen.findByTestId('settings-agent-panel')).toBeInTheDocument();
  });

  it('#105 修复批契约：包装 div 无委托逻辑——点击 appnav-agent-shortcut div 不导航', async () => {
    const user = userEvent.setup();
    render(<App />);
    // RED：当前 App.tsx 根部 handleShortcutClick 委托接管 div 点击 → 导航到 /settings（本断言失败）。
    // GREEN：App.tsx 删除委托后，div 仅作 testid 锚点，点击无任何导航。
    await user.click(screen.getByTestId('appnav-agent-shortcut'));
    expect(window.location.hash).not.toMatch(/settings/);
  });

  it('四页往返导航：项目 → 写作 → 设定库 → 设置 → 项目', async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByTestId('project-card');

    await user.click(screen.getByRole('link', { name: '写作' }));
    expect(screen.getByTestId('editor')).toBeInTheDocument();

    await user.click(screen.getByRole('link', { name: '设定库' }));
    expect(await screen.findByTestId('library-page')).toBeInTheDocument();

    await user.click(screen.getByRole('link', { name: '设置' }));
    expect(await screen.findByTestId('settings-page')).toBeInTheDocument();

    await user.click(screen.getByRole('link', { name: '项目' }));
    expect(screen.getByRole('heading', { name: '我的项目' })).toBeInTheDocument();
    expect(await screen.findByTestId('project-card')).toBeInTheDocument();
  });
});
