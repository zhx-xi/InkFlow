/**
 * #486 会话/记忆 UI — 导航项契约（会话 / 记忆）
 *
 * ⚠️ 本文件 = 契约（独立文件，勿改既有 AppNav.test.tsx）。GREEN 在 AppNav.tsx
 * 系统组（SYSTEM_ITEMS）加入两项：
 * - { key: 'sessions', href: '/sessions', labelKey: 'nav.sessions', icon: History（lucide，自定）}
 * - { key: 'memory', href: '/memory', labelKey: 'nav.memory', icon: Brain（lucide，自定）}
 * - 渲染 NavLink → data-testid="nav-item-sessions" / "nav-item-memory"
 * - i18n：zh.ts nav.sessions='会话' nav.memory='记忆'；
 *   en.ts nav.sessions='Sessions' nav.memory='Memory'
 *
 * RED 预期：nav-item-sessions / nav-item-memory 缺失 → element-missing（类 3 契约缺口）。
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

describe('AppNav — 会话导航项（#486）', () => {
  it('nav-item-sessions 存在且 href=/sessions', () => {
    renderNav();
    expect(screen.getByTestId('nav-item-sessions')).toHaveAttribute('href', '/sessions');
  });

  it('文案 = t(nav.sessions)（zh 下「会话详情」——#836 按钮跳 /sessions）', () => {
    renderNav();
    expect(screen.getByTestId('nav-item-sessions')).toHaveTextContent('会话详情');
  });

  it('点击 nav-item-sessions → location.pathname=/sessions', async () => {
    const user = userEvent.setup();
    renderNav();
    await user.click(screen.getByTestId('nav-item-sessions'));
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/sessions');
  });
});

describe('AppNav — 设定库分类选中态（#548）', () => {
  it('路径 /library?cat=characters 时仅 characters 选中（其余分类不 active）', () => {
    renderNav('/library?cat=characters');
    const chars = screen.getByTestId('nav-item-characters');
    const world = screen.getByTestId('nav-item-world');
    expect(chars.className).toContain('bg-accent-weak');
    expect(world.className).not.toContain('bg-accent-weak');
  });

  it('路径 /library?cat=world 时仅 world 选中', () => {
    renderNav('/library?cat=world');
    const chars = screen.getByTestId('nav-item-characters');
    const world = screen.getByTestId('nav-item-world');
    expect(world.className).toContain('bg-accent-weak');
    expect(chars.className).not.toContain('bg-accent-weak');
  });
});

describe('AppNav — 记忆导航项（#486）', () => {
  it('nav-item-memory 存在且 href=/memory', () => {
    renderNav();
    expect(screen.getByTestId('nav-item-memory')).toHaveAttribute('href', '/memory');
  });

  it('文案 = t(nav.memory)（zh 下「记忆」）', () => {
    renderNav();
    expect(screen.getByTestId('nav-item-memory')).toHaveTextContent('记忆');
  });

  it('点击 nav-item-memory → location.pathname=/memory', async () => {
    const user = userEvent.setup();
    renderNav();
    await user.click(screen.getByTestId('nav-item-memory'));
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/memory');
  });
});
