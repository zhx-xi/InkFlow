/**
 * ⚠️ 契约文件（Issue #105 导航重构 RED 阶段，spec §7.2 信息架构方案 A，用户确认）
 *
 * GREEN 新建 src/components/AppNav.tsx（命名导出 AppNav），必须匹配：
 *
 * 结构（data-testid 即契约）：
 * - app-nav：侧边栏根容器（<nav>）
 * - nav-group-<key>：三分组容器，key ∈ writing | library | system（写作区/设定库/系统）
 * - nav-item-<key>：导航项（必须用 NavLink），key 与路由映射：
 *   writing → /writing（nav.writing 已有）｜projects → /projects（nav.projects 已有）
 *   library → /library（新 key nav.library）
 *   characters → /library?cat=characters｜world → /library?cat=world
 *   outline → /library?cat=outline｜timeline → /library?cat=timeline
 *   foreshadow → /library?cat=foreshadow｜rag → /library?cat=rag
 *   models → 占位（#106 未实现：禁用项，点击不导航；新 key nav.models）
 *   agent → /settings?cat=agent（Agent 快捷入口，新 key nav.agent）
 *   settings → /settings（新 key nav.settings）
 * - nav-collapse-btn：展开态折叠按钮；nav-expand-btn：折叠态展开按钮
 *
 * 行为：
 * - 默认展开：app-nav 无 data-collapsed；点击 nav-collapse-btn → data-collapsed="true"
 *   （jsdom 无法测 52px 宽度，data-collapsed 属性即折叠窄条契约，spec §7.2「52px 图标窄条」）
 * - 折叠态点击 nav-expand-btn → data-collapsed 移除（可恢复）
 * - active 态：NavLink 激活时 aria-current="page"（react-router 内建，GREEN 必须用 NavLink）
 * - 品牌区：app-nav 内 logo（img，装饰性 alt="" aria-hidden="true"，三主题变体 GREEN 自定）
 *   + t('app.brand') 文字
 *
 * 新增 i18n key（GREEN 补 zh.ts/en.ts；nav.agents 随 /agents 路由删除，spec §7.10 Q1=A）：
 * nav.library='设定库' nav.settings='设置' nav.models='模型管理' nav.agent='Agent'
 * nav.group.writing='写作区' nav.group.library='设定库' nav.group.system='系统'
 * nav.lib.characters='角色' nav.lib.world='世界观' nav.lib.outline='大纲'
 * nav.lib.timeline='时间线' nav.lib.foreshadow='伏笔' nav.lib.rag='知识库 RAG'
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { AppNav } from './AppNav';
import { useThemeStore } from '../stores/theme';

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname}{location.search}</div>;
}

function renderNav(initialPath = '/writing') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <AppNav />
      <Routes>
        <Route path="/writing" element={<LocationProbe />} />
        <Route path="/projects" element={<LocationProbe />} />
        <Route path="/library" element={<LocationProbe />} />
        <Route path="/settings" element={<LocationProbe />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

/** 导航项 key → NavLink href（models 为 #106 占位，不在此表） */
const NAV_LINKS: Array<[string, string]> = [
  ['writing', '/writing'],
  ['projects', '/projects'],
  ['library', '/library'],
  ['characters', '/library?cat=characters'],
  ['world', '/library?cat=world'],
  ['outline', '/library?cat=outline'],
  ['timeline', '/library?cat=timeline'],
  ['foreshadow', '/library?cat=foreshadow'],
  ['rag', '/library?cat=rag'],
  ['agent', '/settings?cat=agent'],
  ['settings', '/settings'],
];

beforeEach(() => {
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('AppNav — 结构与分组', () => {
  it('品牌区：logo（装饰性 img）+ InkFlow 文字', () => {
    renderNav();
    const nav = screen.getByTestId('app-nav');
    const logo = nav.querySelector('img');
    expect(logo).not.toBeNull();
    expect(logo as Element).toHaveAttribute('alt', '');
    expect(logo as Element).toHaveAttribute('aria-hidden', 'true');
    expect(screen.getByText('InkFlow')).toBeInTheDocument();
  });

  it('三分组容器齐全（写作区/设定库/系统）', () => {
    renderNav();
    expect(screen.getByTestId('nav-group-writing')).toBeInTheDocument();
    expect(screen.getByTestId('nav-group-library')).toBeInTheDocument();
    expect(screen.getByTestId('nav-group-system')).toBeInTheDocument();
  });

  it('11 个导航链接：testid 齐全 + NavLink href 与路由契约一致；models 占位项渲染', () => {
    renderNav();
    for (const [key, href] of NAV_LINKS) {
      expect(screen.getByTestId(`nav-item-${key}`)).toHaveAttribute('href', href);
    }
    // 模型管理：#106 未实现，占位项渲染（无 href 契约，点击行为见折叠/跳转 describe）
    expect(screen.getByTestId('nav-item-models')).toBeInTheDocument();
  });

  it('导航文案：写作/项目用既有 key，设定库/设置/RAG 用新 key', () => {
    renderNav();
    expect(screen.getByTestId('nav-item-writing')).toHaveTextContent('写作');
    expect(screen.getByTestId('nav-item-projects')).toHaveTextContent('项目');
    expect(screen.getByTestId('nav-item-library')).toHaveTextContent('设定库');
    expect(screen.getByTestId('nav-item-settings')).toHaveTextContent('设置');
    expect(screen.getByTestId('nav-item-rag')).toHaveTextContent('知识库 RAG');
  });
});

describe('AppNav — 折叠（spec §7.2：52px 窄条可恢复）', () => {
  it('默认展开 → 点击折叠 → data-collapsed="true" → 点击展开按钮恢复', async () => {
    const user = userEvent.setup();
    renderNav();
    const nav = screen.getByTestId('app-nav');
    expect(nav).not.toHaveAttribute('data-collapsed');

    await user.click(screen.getByTestId('nav-collapse-btn'));
    expect(nav).toHaveAttribute('data-collapsed', 'true');

    await user.click(screen.getByTestId('nav-expand-btn'));
    expect(nav).not.toHaveAttribute('data-collapsed');
  });
});

describe('AppNav — active 态（NavLink isActive → aria-current="page"）', () => {
  it('/writing 下写作项高亮，项目/设定库不高亮', () => {
    renderNav('/writing');
    expect(screen.getByTestId('nav-item-writing')).toHaveAttribute('aria-current', 'page');
    expect(screen.getByTestId('nav-item-projects')).not.toHaveAttribute('aria-current');
    expect(screen.getByTestId('nav-item-library')).not.toHaveAttribute('aria-current');
  });

  it('/settings?cat=agent 下设置项高亮', () => {
    renderNav('/settings?cat=agent');
    expect(screen.getByTestId('nav-item-settings')).toHaveAttribute('aria-current', 'page');
    expect(screen.getByTestId('nav-item-agent')).not.toHaveAttribute('aria-current');
  });
});

describe('AppNav — 跳转', () => {
  it('Agent 快捷入口：点击 → 直达设置页 Agent 分类 /settings?cat=agent', async () => {
    const user = userEvent.setup();
    renderNav();
    await user.click(screen.getByTestId('nav-item-agent'));
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/settings?cat=agent');
  });

  it('设定库分类直达：点击角色 → /library?cat=characters', async () => {
    const user = userEvent.setup();
    renderNav();
    await user.click(screen.getByTestId('nav-item-characters'));
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/library?cat=characters');
  });

  it('模型管理占位：#106 前为禁用项，点击不导航', () => {
    renderNav();
    fireEvent.click(screen.getByTestId('nav-item-models'));
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/writing');
  });
});
