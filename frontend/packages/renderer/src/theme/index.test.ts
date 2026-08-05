/**
 * theme 模块薄弱分支补测（Issue #104 覆盖率：行 70.27% → 目标 ≥99%）
 *
 * 覆盖点（对应 src/theme/index.ts）：
 * - applyTheme 双写 html/body dataset（theme + bg，bg 缺省 default）
 * - resolveInitialTheme：localStorage 有效值 / 有 theme 无 bg / 损坏 JSON /
 *   无值 + prefers-dark true / 无值 + prefers-dark false
 * - useThemeEffect：挂载应用主题 + html lang；theme/bg/lang 切换
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { applyTheme, resolveInitialTheme, useThemeEffect } from './index';
import { useThemeStore } from '../stores/theme';

function stubMatchMedia(matches: boolean): ReturnType<typeof vi.fn> {
  const matchMediaMock = vi.fn().mockReturnValue({
    matches,
    media: '(prefers-color-scheme: dark)',
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
  vi.stubGlobal('matchMedia', matchMediaMock);
  return matchMediaMock;
}

beforeEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('applyTheme — html/body 双写', () => {
  it('theme + bg 双写 html 与 body dataset', () => {
    applyTheme('night', 'navy');
    expect(document.documentElement.dataset.theme).toBe('night');
    expect(document.documentElement.dataset.bg).toBe('navy');
    expect(document.body.dataset.theme).toBe('night');
    expect(document.body.dataset.bg).toBe('navy');
  });

  it('bg 缺省 → default', () => {
    applyTheme('ink');
    expect(document.documentElement.dataset.theme).toBe('ink');
    expect(document.documentElement.dataset.bg).toBe('default');
    expect(document.body.dataset.bg).toBe('default');
  });
});

describe('resolveInitialTheme — localStorage / 系统偏好', () => {
  it('localStorage 有效值 → 原样返回（theme + bg）', () => {
    localStorage.setItem('inkflow.ui', JSON.stringify({ theme: 'ink', bg: 'ochre' }));
    expect(resolveInitialTheme()).toEqual({ theme: 'ink', bg: 'ochre' });
  });

  it('有 theme 无 bg → bg 回退 default', () => {
    localStorage.setItem('inkflow.ui', JSON.stringify({ theme: 'night' }));
    expect(resolveInitialTheme()).toEqual({ theme: 'night', bg: 'default' });
  });

  it('损坏 JSON → 回退系统偏好分支', () => {
    localStorage.setItem('inkflow.ui', '{broken-json');
    stubMatchMedia(false);
    expect(resolveInitialTheme()).toEqual({ theme: 'paper', bg: 'default' });
  });

  it('无值 + 系统深色偏好 → night/default', () => {
    stubMatchMedia(true);
    expect(resolveInitialTheme()).toEqual({ theme: 'night', bg: 'default' });
  });

  it('无值 + 系统浅色偏好 → paper/default', () => {
    stubMatchMedia(false);
    expect(resolveInitialTheme()).toEqual({ theme: 'paper', bg: 'default' });
  });

  it('matchMedia 不存在 → 按浅色回退 paper', () => {
    // beforeEach 已 unstubAllGlobals：jsdom 无 matchMedia → 可选链兜底
    expect(resolveInitialTheme()).toEqual({ theme: 'paper', bg: 'default' });
  });
});

describe('useThemeEffect — 挂载应用 + 切换跟随', () => {
  it('挂载：应用 store 主题到 html/body + 设置 html lang', () => {
    useThemeStore.setState({ theme: 'night', bg: 'navy', lang: 'zh' });
    renderHook(() => useThemeEffect());

    expect(document.documentElement.dataset.theme).toBe('night');
    expect(document.documentElement.dataset.bg).toBe('navy');
    expect(document.body.dataset.theme).toBe('night');
    expect(document.body.dataset.bg).toBe('navy');
    expect(document.documentElement.lang).toBe('zh-CN');
  });

  it('语言切换 zh → en：html lang 更新', () => {
    renderHook(() => useThemeEffect());
    expect(document.documentElement.lang).toBe('zh-CN');

    act(() => {
      useThemeStore.getState().setLang('en');
    });
    expect(document.documentElement.lang).toBe('en');
  });

  it('主题切换：应用新主题并过滤非法背景变体（navy 不属于 ink → default）', () => {
    useThemeStore.setState({ theme: 'paper', bg: 'navy', lang: 'zh' });
    renderHook(() => useThemeEffect());

    act(() => {
      useThemeStore.getState().setTheme('ink');
    });
    expect(document.documentElement.dataset.theme).toBe('ink');
    expect(document.documentElement.dataset.bg).toBe('default');
    expect(document.body.dataset.bg).toBe('default');
  });

  it('背景切换：应用新背景', () => {
    useThemeStore.setState({ theme: 'night', bg: 'default', lang: 'zh' });
    renderHook(() => useThemeEffect());

    act(() => {
      useThemeStore.getState().setBg('navy');
    });
    expect(document.documentElement.dataset.bg).toBe('navy');
    expect(document.body.dataset.bg).toBe('navy');
  });
});
