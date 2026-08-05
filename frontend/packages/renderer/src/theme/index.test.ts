/**
 * theme 模块测试契约（Issue #105 §6.3⑥：resolveInitialTheme 死代码已删除）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 src/theme/index.ts 必须匹配：
 * - resolveInitialTheme 已从模块中删除（全仓 0 引用，store 内 initialTheme() 为活实现）
 *   → 本文件不再 import/测试该函数（其测试组随实现一并移除）
 * - applyTheme 双写 html/body dataset（theme + bg，bg 缺省 default）
 * - useThemeEffect：挂载应用主题 + html lang；theme/bg/lang 切换
 *
 * 覆盖点（对应 src/theme/index.ts）：
 * - applyTheme 双写 html/body dataset（theme + bg，bg 缺省 default）
 * - useThemeEffect：挂载应用主题 + html lang；theme/bg/lang 切换
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { applyTheme, useThemeEffect } from './index';
import { useThemeStore } from '../stores/theme';

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
