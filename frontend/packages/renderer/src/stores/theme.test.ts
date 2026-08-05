/**
 * theme store 行为契约测试（spec §4.3：默认策略 / localStorage 持久化 / 背景变体随主题过滤）
 *
 * ⚠️ Issue #105 §6.3⑤ 契约升级：store 不再内联 validBgs，引用 ../theme 的 BG_BY_THEME
 * （单一来源）。本文件通过 vi.mock('../theme') 把 BG_BY_THEME 缩水为仅含 default，
 * 验证 setTheme 的合法背景判定跟随 BG_BY_THEME —— 若实现仍内联 validBgs（现状），
 * mock 不生效 → 新断言 FAIL（= RED 证据）。GREEN 后 store 改为引用 BG_BY_THEME 即转绿。
 *
 * 本 store 已实现（骨架阶段），测试 = 现有行为契约（预期 GREEN 保持通过）。
 * 注意：store 初始态在模块加载时计算（读 localStorage + matchMedia），
 * 默认策略测试用 vi.resetModules() + 重新 import 获取新鲜实例。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act } from '@testing-library/react';
import { useThemeStore } from './theme';

// §6.3⑤ 单一来源契约：合法背景列表必须来自 BG_BY_THEME（store 不得内联维护）。
// 缩水版 mock：若 store 引用 BG_BY_THEME，则 ochre/navy/parchment 对任何主题都非法；
// 若内联 validBgs（现状），则这些值仍被当作合法 → 下方断言失败。
vi.mock('../theme', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../theme')>();
  return {
    ...actual,
    BG_BY_THEME: { paper: ['default'], night: ['default'], ink: ['default'] },
  };
});

const STORAGE_KEY = 'inkflow.ui';

/** resetModules 后重新 import theme store（重新计算初始态） */
async function freshThemeStore() {
  vi.resetModules();
  const mod = await import('./theme');
  return mod.useThemeStore;
}

beforeEach(() => {
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('theme store — 初始默认策略（spec §4.3）', () => {
  it('首次访问（无持久化、无深色偏好）→ 素笺 paper', () => {
    expect(useThemeStore.getState().theme).toBe('paper');
    expect(useThemeStore.getState().bg).toBe('default');
  });

  it('未手动选择且系统 prefers-color-scheme: dark → 夜航 night', async () => {
    vi.stubGlobal('matchMedia', () => ({ matches: true }));
    const store = await freshThemeStore();
    expect(store.getState().theme).toBe('night');
    expect(store.getState().bg).toBe('default');
  });

  it('手动选择（localStorage）覆盖系统偏好', async () => {
    vi.stubGlobal('matchMedia', () => ({ matches: true }));
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ theme: 'ink', bg: 'ochre', lang: 'zh' }));
    const store = await freshThemeStore();
    expect(store.getState().theme).toBe('ink');
    expect(store.getState().bg).toBe('ochre');
  });

  it('持久化数据损坏（非法 JSON）→ 回退默认素笺', async () => {
    localStorage.setItem(STORAGE_KEY, '{not-json');
    const store = await freshThemeStore();
    expect(store.getState().theme).toBe('paper');
  });
});

describe('theme store — setTheme / setBg / setLang', () => {
  it('setTheme：持久化到 localStorage（inkflow.ui 含 theme/bg/lang）', () => {
    act(() => {
      useThemeStore.getState().setTheme('ink');
    });
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY)!) as Record<string, string>;
    expect(saved.theme).toBe('ink');
    expect(saved.lang).toBe('zh');
  });

  it('背景变体随主题过滤：非法组合回退 default（parchment 属 paper，切 ink 不合法 → default）', () => {
    act(() => {
      useThemeStore.getState().setBg('parchment');
    });
    act(() => {
      useThemeStore.getState().setTheme('ink');
    });
    expect(useThemeStore.getState().bg).toBe('default');
  });

  it('背景变体过滤：非法组合回退 default，且回退粘性（切回原主题不自动恢复）', () => {
    act(() => {
      useThemeStore.getState().setTheme('night');
      useThemeStore.getState().setBg('navy');
    });
    act(() => {
      useThemeStore.getState().setTheme('ink'); // navy 属 night，对 ink 非法 → default
    });
    expect(useThemeStore.getState().bg).toBe('default');
    act(() => {
      useThemeStore.getState().setTheme('night'); // 回退是粘性的：切回 night 保持 default
    });
    expect(useThemeStore.getState().bg).toBe('default');
  });

  it('背景变体合法时跨主题保留（default 对所有主题合法）', () => {
    act(() => {
      useThemeStore.getState().setTheme('night');
      useThemeStore.getState().setBg('default');
    });
    act(() => {
      useThemeStore.getState().setTheme('ink');
    });
    expect(useThemeStore.getState().bg).toBe('default');
  });

  it('setBg：持久化 + 状态更新', () => {
    act(() => {
      useThemeStore.getState().setBg('parchment');
    });
    expect(useThemeStore.getState().bg).toBe('parchment');
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!).bg).toBe('parchment');
  });

  it('setLang：持久化 + 状态更新（zh ↔ en）', () => {
    act(() => {
      useThemeStore.getState().setLang('en');
    });
    expect(useThemeStore.getState().lang).toBe('en');
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!).lang).toBe('en');
    act(() => {
      useThemeStore.getState().setLang('zh');
    });
    expect(useThemeStore.getState().lang).toBe('zh');
  });
});

describe('theme store — validBgs 单一来源（Issue #105 §6.3⑤）', () => {
  // 本组契约：store 的合法背景判定必须引用 ../theme 的 BG_BY_THEME（mock 为仅含 default）。
  // 真实 BG_BY_THEME 语义（既有测试覆盖）：ink 合法 bg = default/ochre，paper 合法 = default/parchment。
  // 下方断言在 mock 缩水版下验证「引用关系」：ochre 对 ink 不再合法 → 回退 default。
  // 当前内联 validBgs 实现（[default, ochre]）会让 ochre 保留 → 本组 FAIL = RED 证据。
  it('setTheme 合法 bg 来自 BG_BY_THEME：ochre 对 ink 非法时回退 default（不再内联 validBgs）', () => {
    act(() => {
      useThemeStore.getState().setBg('ochre');
      useThemeStore.getState().setTheme('ink');
    });
    // mocked BG_BY_THEME.ink = ['default']：引用单一来源 → ochre 非法 → default
    expect(useThemeStore.getState().bg).toBe('default');
  });

  it('setTheme 回退同步持久化：localStorage 不残留非法背景组合', () => {
    act(() => {
      useThemeStore.getState().setBg('navy');
      useThemeStore.getState().setTheme('paper');
    });
    // mocked BG_BY_THEME.paper = ['default']：navy 非法 → default，且持久化同步
    expect(useThemeStore.getState().bg).toBe('default');
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!).bg).toBe('default');
  });

  it('setTheme 合法 bg 保留（default 对所有主题合法，跨主题不丢）', () => {
    act(() => {
      useThemeStore.getState().setTheme('night');
      useThemeStore.getState().setBg('default');
      useThemeStore.getState().setTheme('ink');
    });
    expect(useThemeStore.getState().bg).toBe('default');
  });
});
