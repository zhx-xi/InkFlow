/**
 * #480 检索导航项契约（Issue #480 RAG embedding 增强检索）
 *
 * ⚠️ 本文件 = 契约（独立文件，勿改既有 AppNav.test.tsx）。GREEN 在 AppNav.tsx
 * 导航项数组（建议 LIBRARY_ITEMS 或新增检索组）加入检索项：
 * - { key: 'search', href: '/search', labelKey: 'nav.search', icon: Search（lucide，自定）}
 * - 渲染 NavLink → data-testid="nav-item-search"（NavLink 内建 aria-current 激活态）
 * - i18n：zh.ts nav.search='检索'；en.ts nav.search='Search'
 *
 * RED 预期：nav-item-search 缺失 → element-missing（类 3 契约缺口；
 * AppNav.tsx 存在但无该项，getByTestId 抛 TestingLibraryElementError）。
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
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
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('AppNav — 检索导航项（#480）', () => {
  it('nav-item-search 存在且 href=/search', () => {
    renderNav();
    expect(screen.getByTestId('nav-item-search')).toHaveAttribute('href', '/search');
  });

  it('文案 = t(nav.search)（zh 下「检索」）', () => {
    renderNav();
    expect(screen.getByTestId('nav-item-search')).toHaveTextContent('检索');
  });

  it('点击 nav-item-search → location.pathname=/search', async () => {
    const user = userEvent.setup();
    renderNav();
    await user.click(screen.getByTestId('nav-item-search'));
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/search');
  });
});
