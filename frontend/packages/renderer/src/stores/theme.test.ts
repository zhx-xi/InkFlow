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
 *
 * ⚠️ F32 设置持久化（#152，spec §5.2/§5.3/§9.4）RED 段（2026-08-08）——设计假设清单：
 * - stores/theme.ts 扩展（导出名保持 useThemeStore，§12 D4）：新增字段 font（FontKey，
 *   默认 'sans'）/ closeBehavior（CloseBehavior，默认 'tray'）/ trayHintDismissed（默认 false）
 *   + 方法 setFont（视觉 setter）/ setCloseBehavior / setTrayHintDismissed（行为 setter，
 *   均返回 Promise）/ initFromBackend（异步加载，AppLayout 挂载调用一次）
 * - api/client.ts 新增 fetchSettings() / patchSettings()（GET/PATCH /api/v1/settings，§3）；
 *   AppSettings 响应字段 snake_case：theme/bg/lang/font/close_behavior/tray_hint_dismissed；
 *   PATCH 请求体 = 部分更新对象（如 { theme: 'night' }），响应恒全量（免二次 GET）
 * - initFromBackend 流程（§5.2 步骤 ②③④⑤）：ensureApiReady → fetchSettings →
 *   theme 覆盖三分支：后端 theme≠'paper'（用户显式选过）→ 覆盖；后端 'paper'（无显式选择
 *   记录）+ 本地快照有记录 → 保留本地值（不覆盖本地显式选择，评审 🔴-1）；后端 'paper' +
 *   本地无记录 → 保留当前值（系统深色策略首帧结果，不覆盖）
 *   → 回写 localStorage 'inkflow.ui'（含 font 新字段；closeBehavior/trayHintDismissed
 *   不落缓存，避免陈旧值误导——启动后由后端覆盖）→ IPC 桥接（§5.3）：close_behavior≠'tray'
 *   → window.INKFLOW_API.settings.setCloseBehavior(v)；tray_hint_dismissed=true →
 *   settings.dismissTrayHint()；无 INKFLOW_API（浏览器 dev，§7 边界 #13）可选链吞掉
 *   → 失败（fetch reject）：console.warn + 保持快照 + 不抛错（§7 边界 #2，启动期静默不弹 toast）
 * - 视觉 setter（setTheme/setBg/setLang/setFont，§5.2 setter 流程）：乐观更新（立即生效）+
 *   localStorage 回写 + fire-and-forget PATCH（patchSettings({...})）；PATCH 失败 → err toast
 *   「保存失败」（store 内 pushToast——store 非组件不能调 useI18n，agent.ts 硬编码中文先例）+
 *   本地值保留（不回滚，§7 边界 #7，下次启动以后端为准）
 * - 行为 setter（setCloseBehavior/setTrayHintDismissed，§5.3）：PATCH 成功 → 才 IPC 推送 →
 *   store 更新；PATCH 失败 → err toast + 值回弹（保持原值）+ 不推送 IPC + 不 rethrow
 *   （fire-and-forget 语义：页面侧 void 调用，err toast 由 store 内 pushToast，§7 边界 #8）
 * - 本文件 mock '../api/client' 仅替换 fetchSettings/patchSettings（apiFetch/ensureApiReady/
 *   errorMessage 保持真实——ensureApiReady 在 jsdom 非 Electron 环境立即 resolve 无需 mock）；
 *   window.INKFLOW_API.settings 假命名空间经 Object.defineProperty 注入（#167 F31
 *   setInjected 先例）
 * - RED 预期：GREEN 前新契约断言 FAIL 于 is-not-a-function（initFromBackend/setFont/
 *   setCloseBehavior/setTrayHintDismissed 缺失 → TypeError: ... is not a function）与
 *   断言型缺口（setTheme 零 PATCH 调用 → toHaveBeenCalledWith FAIL）；既有 12 用例保持绿
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, waitFor } from '@testing-library/react';
import { useThemeStore } from './theme';
import { useToastStore } from './toast';
import type { CloseBehavior } from '../api/client';
import type { Lang, ThemeBg, ThemeName } from '../theme';

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

// ⚠️ F32：fetchSettings/patchSettings 契约 mock（api/client.ts 新增函数；GREEN 落地后
// 工厂仍只替换这两个函数，apiFetch/ensureApiReady 保持真实）
const { fetchSettingsMock, patchSettingsMock } = vi.hoisted(() => ({
  fetchSettingsMock: vi.fn(),
  patchSettingsMock: vi.fn(),
}));

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, fetchSettings: fetchSettingsMock, patchSettings: patchSettingsMock };
});

const STORAGE_KEY = 'inkflow.ui';

// ⚠️ F32：AppSettings 契约类型（api/client.ts 新增；字段 snake_case 对齐后端 JSON，§3.2）
type FontKey = 'serif' | 'sans' | 'mono';
interface AppSettings {
  theme: ThemeName;
  bg: ThemeBg;
  lang: Lang;
  font: FontKey;
  close_behavior: CloseBehavior;
  tray_hint_dismissed: boolean;
}

/** F32：GET /settings 空表全默认响应（§3.2） */
const DEFAULT_SETTINGS: AppSettings = {
  theme: 'paper',
  bg: 'default',
  lang: 'zh',
  font: 'sans',
  close_behavior: 'tray',
  tray_hint_dismissed: false,
};

// ⚠️ F32：theme store 扩展契约的测试侧类型（GREEN 补全 stores/theme.ts 后此 cast 可删；
// esbuild 不查类型但 RED 验证要求 tsc --noEmit 绿——运行时仍走真实 store，
// 缺失方法 → TypeError = 预期 RED 证据）
type ThemeStateF32 = ReturnType<typeof useThemeStore.getState> & {
  font: FontKey;
  closeBehavior: CloseBehavior;
  trayHintDismissed: boolean;
  // #199（2026-08-09）：setter 返回 Promise<boolean>（成功 true / 失败 false，内部 catch 不 rethrow）——
  // 给设置页顶部保存指示提供精确持久化结果信号；GREEN 后类型与真实 store 对齐
  setFont: (f: FontKey) => Promise<boolean>;
  setCloseBehavior: (b: CloseBehavior) => Promise<boolean>;
  setTrayHintDismissed: (v: boolean) => Promise<boolean>;
  initFromBackend: () => Promise<void>;
};
const themeStateF32 = () => useThemeStore.getState() as ThemeStateF32;

/** resetModules 后重新 import theme store（重新计算初始态） */
async function freshThemeStore() {
  vi.resetModules();
  const mod = await import('./theme');
  return mod.useThemeStore;
}

beforeEach(() => {
  localStorage.clear();
  // F32（#152）：mock 重置 + 默认成功响应（fire-and-forget PATCH 链安全）；
  // 扩展字段重置防测试间污染（GREEN 后 setState 字面量即可，cast 可删）
  fetchSettingsMock.mockReset();
  patchSettingsMock.mockReset();
  patchSettingsMock.mockResolvedValue({ ...DEFAULT_SETTINGS });
  useToastStore.setState({ toasts: [] });
  useThemeStore.setState({
    theme: 'paper', bg: 'default', lang: 'zh',
    font: 'sans', closeBehavior: 'tray', trayHintDismissed: false,
    // #399：visualTouched 守卫重置（模块单例跨用例污染防护；GREEN 后真实字段）
    visualTouched: false,
  } as unknown as Partial<ThemeStateF32>);
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

/**
 * F32 设置持久化（#152，spec §5.2）：initFromBackend 双轨加载契约
 * （localStorage 快照 → 后端覆盖 → 缓存回写；后端不可达静默兜底）。
 * RED 预期：GREEN 前 initFromBackend 不存在 → 全部 is-not-a-function（TypeError）FAIL。
 */
describe('theme store — F32 initFromBackend 双轨加载（spec §5.2）', () => {
  it('后端显式 theme=night → store.theme 覆盖为 night（跨设备/重启保留）', async () => {
    fetchSettingsMock.mockResolvedValue({ ...DEFAULT_SETTINGS, theme: 'night' });
    await act(async () => {
      await themeStateF32().initFromBackend();
    });
    expect(useThemeStore.getState().theme).toBe('night');
  });

  it('后端默认 paper + 本地有记录（本地 night）→ 保留本地 night（评审 🔴-1：后端 paper = 无显式选择，不覆盖本地显式选择）', async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ theme: 'night', bg: 'default', lang: 'zh' }));
    useThemeStore.setState({ theme: 'night', bg: 'default', lang: 'zh' });
    fetchSettingsMock.mockResolvedValue({ ...DEFAULT_SETTINGS, theme: 'paper' });
    await act(async () => {
      await themeStateF32().initFromBackend();
    });
    expect(useThemeStore.getState().theme).toBe('night');
  });

  it('后端默认 paper + 本地无记录 → 保留系统深色策略结果（新用户首帧 night 不被覆盖，§5.2 第三分支）', async () => {
    vi.stubGlobal('matchMedia', () => ({ matches: true }));
    const store = await freshThemeStore(); // ① 首帧：无快照 + 系统深色 → night
    expect(store.getState().theme).toBe('night');
    fetchSettingsMock.mockResolvedValue({ ...DEFAULT_SETTINGS, theme: 'paper' });
    await act(async () => {
      await (store.getState() as ThemeStateF32).initFromBackend();
    });
    expect(store.getState().theme).toBe('night');
  });

  it('缓存回写：initFromBackend 成功 → localStorage inkflow.ui 含 font 新字段（closeBehavior/trayHintDismissed 不落缓存）', async () => {
    fetchSettingsMock.mockResolvedValue({
      theme: 'night', bg: 'navy', lang: 'en', font: 'serif',
      close_behavior: 'quit', tray_hint_dismissed: true,
    });
    await act(async () => {
      await themeStateF32().initFromBackend();
    });
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY)!) as Record<string, unknown>;
    expect(saved).toEqual({ theme: 'night', bg: 'navy', lang: 'en', font: 'serif' });
  });

  it('后端不可达：fetchSettings reject → store 保持快照 + console.warn 被调用 + 不抛错（§7 边界 #2 静默兜底，不弹 toast）', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      fetchSettingsMock.mockRejectedValue(new Error('Kernel unreachable'));
      await act(async () => {
        await themeStateF32().initFromBackend(); // 不抛错 = 契约
      });
      expect(useThemeStore.getState().theme).toBe('paper'); // 快照保持（beforeEach 重置值）
      expect(useThemeStore.getState().font).toBe('sans');
      expect(warnSpy).toHaveBeenCalled();
      expect(useToastStore.getState().toasts).toHaveLength(0); // 启动期静默，不弹 toast
    } finally {
      warnSpy.mockRestore();
    }
  });

  it('#399：用户已通过 UI setTheme 选择 → initFromBackend 异步返回后端旧值不覆盖（visualTouched 守卫）', async () => {
    // 模拟 E2E 顶栏用例（e2e-settings.spec.ts:180）竞态时序：reload 后 initFromBackend 在途，
    // 用户点击「夜航」→ fetch 才返回后端旧值 ink（上一用例 PATCH 落库残留）——用户选择必须优先。
    // GREEN 前 initFromBackend 无条件 set theme=ink → toBe('night') FAIL = RED。
    let resolveFetch!: (v: typeof DEFAULT_SETTINGS) => void;
    fetchSettingsMock.mockImplementation(
      () => new Promise((res) => {
        resolveFetch = res;
      }),
    );
    const pending = themeStateF32().initFromBackend(); // 挂起中（fetch 未返回）
    act(() => {
      useThemeStore.getState().setTheme('night'); // 用户点击「夜航 · 深色」
    });
    await act(async () => {
      resolveFetch({ ...DEFAULT_SETTINGS, theme: 'ink' }); // 后端残留 ink 返回
      await pending;
    });
    expect(useThemeStore.getState().theme).toBe('night'); // 用户选择优先，不被覆盖
  });
});

/**
 * F32 设置持久化（#152，spec §5.2 setter 流程）：视觉设置乐观更新 + PATCH 后端同步。
 * RED 预期：GREEN 前 setTheme 只写 localStorage 零 PATCH → toHaveBeenCalledWith FAIL；
 * setFont 不存在 → is-not-a-function。
 */
describe('theme store — F32 视觉 setter 后端同步（spec §5.2）', () => {
  it('setTheme：PATCH body {theme} + localStorage 回写 + store 更新（乐观更新）', () => {
    act(() => {
      themeStateF32().setTheme('night');
    });
    expect(patchSettingsMock).toHaveBeenCalledWith({ theme: 'night' });
    expect(useThemeStore.getState().theme).toBe('night');
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!).theme).toBe('night');
  });

  it('setTheme PATCH reject → err toast「保存失败」+ 本地值保留（乐观更新不回滚，§7 边界 #7）', async () => {
    patchSettingsMock.mockRejectedValue(new Error('network down'));
    act(() => {
      themeStateF32().setTheme('night');
    });
    expect(useThemeStore.getState().theme).toBe('night'); // 本地值保留
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!).theme).toBe('night');
    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts.some((t) => t.type === 'err' && t.message === '保存失败')).toBe(true);
    });
  });

  it('setFont：PATCH body {font} + localStorage 回写 + store 更新（font 首次纳入持久化）', () => {
    act(() => {
      themeStateF32().setFont('serif');
    });
    expect(patchSettingsMock).toHaveBeenCalledWith({ font: 'serif' });
    expect(useThemeStore.getState().font).toBe('serif');
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!).font).toBe('serif');
  });
});

/**
 * F32 设置持久化（#152，spec §5.3）：行为设置 PATCH 成功才 IPC 推送 + 启动初始化桥接。
 * RED 预期：GREEN 前 setCloseBehavior/setTrayHintDismissed/initFromBackend 不存在 →
 * is-not-a-function FAIL（零 IPC 调用）。
 */
describe('theme store — F32 IPC 桥接（spec §5.3）', () => {
  /** window.INKFLOW_API.settings mock（#167 F31 三通道：get/set-close-behavior + dismiss-tray-hint） */
  function createSettingsApiMock() {
    return {
      getCloseBehavior: vi.fn().mockResolvedValue('tray'),
      setCloseBehavior: vi.fn().mockResolvedValue(undefined),
      dismissTrayHint: vi.fn().mockResolvedValue(undefined),
    };
  }

  /** 注入假命名空间（settings 命名空间尚不在 ApiConfig 类型内 → unknown 透传 + Object.defineProperty，#167 setInjected 先例） */
  function setInjected(api: unknown): void {
    Object.defineProperty(window, 'INKFLOW_API', {
      configurable: true,
      value: api,
    });
  }

  let settingsApi: ReturnType<typeof createSettingsApiMock>;

  beforeEach(() => {
    settingsApi = createSettingsApiMock();
    setInjected({ settings: settingsApi });
  });

  afterEach(() => {
    setInjected(undefined);
  });

  it('setCloseBehavior：PATCH 成功后才 IPC 推送 + store 更新（§5.3 顺序契约：持久化先行，D9）', async () => {
    patchSettingsMock.mockResolvedValue({ ...DEFAULT_SETTINGS, close_behavior: 'quit' });
    await act(async () => {
      await themeStateF32().setCloseBehavior('quit');
    });
    expect(patchSettingsMock).toHaveBeenCalledWith({ close_behavior: 'quit' });
    expect(settingsApi.setCloseBehavior).toHaveBeenCalledWith('quit');
    expect(useThemeStore.getState().closeBehavior).toBe('quit');
    // PATCH 调用先于 IPC 推送（持久化成功才推送）
    expect(patchSettingsMock.mock.invocationCallOrder[0]).toBeLessThan(
      settingsApi.setCloseBehavior.mock.invocationCallOrder[0],
    );
  });

  it('setCloseBehavior：PATCH reject → 不推送 IPC + store 值回弹（保持原值）+ err toast（§7 边界 #8 诚实一致）', async () => {
    patchSettingsMock.mockRejectedValue(new Error('network down'));
    let rejected = false;
    await act(async () => {
      try {
        await themeStateF32().setCloseBehavior('quit');
      } catch {
        rejected = true; // 契约：失败不 rethrow（fire-and-forget，页面侧 void 调用）
      }
    });
    expect(rejected).toBe(false);
    expect(useThemeStore.getState().closeBehavior).toBe('tray'); // 回弹
    expect(settingsApi.setCloseBehavior).not.toHaveBeenCalled(); // 不推送
    expect(useToastStore.getState().toasts.some((t) => t.type === 'err')).toBe(true);
  });

  it('initFromBackend 遇 close_behavior=quit → IPC settings.setCloseBehavior(quit) 被调用 + store 更新', async () => {
    fetchSettingsMock.mockResolvedValue({ ...DEFAULT_SETTINGS, close_behavior: 'quit' });
    await act(async () => {
      await themeStateF32().initFromBackend();
    });
    expect(settingsApi.setCloseBehavior).toHaveBeenCalledWith('quit');
    expect(useThemeStore.getState().closeBehavior).toBe('quit');
    expect(settingsApi.dismissTrayHint).not.toHaveBeenCalled();
  });

  it('initFromBackend 遇 tray_hint_dismissed=true → IPC settings.dismissTrayHint 被调用（close_behavior=tray 不推送 setCloseBehavior）', async () => {
    fetchSettingsMock.mockResolvedValue({ ...DEFAULT_SETTINGS, tray_hint_dismissed: true });
    await act(async () => {
      await themeStateF32().initFromBackend();
    });
    expect(settingsApi.dismissTrayHint).toHaveBeenCalledTimes(1);
    expect(useThemeStore.getState().trayHintDismissed).toBe(true);
    expect(settingsApi.setCloseBehavior).not.toHaveBeenCalled();
  });

  it('无 window.INKFLOW_API（浏览器 dev）→ initFromBackend 不崩、不推送 IPC、持久化值仍入 store（§7 边界 #13 可选链）', async () => {
    setInjected(undefined);
    fetchSettingsMock.mockResolvedValue({ ...DEFAULT_SETTINGS, close_behavior: 'quit', tray_hint_dismissed: true });
    await act(async () => {
      await themeStateF32().initFromBackend();
    });
    expect(useThemeStore.getState().closeBehavior).toBe('quit');
    expect(useThemeStore.getState().trayHintDismissed).toBe(true);
  });

  it('setTrayHintDismissed(true)：PATCH 成功 → IPC dismissTrayHint + store 更新（§6.2 开关链路）', async () => {
    patchSettingsMock.mockResolvedValue({ ...DEFAULT_SETTINGS, tray_hint_dismissed: true });
    await act(async () => {
      await themeStateF32().setTrayHintDismissed(true);
    });
    expect(patchSettingsMock).toHaveBeenCalledWith({ tray_hint_dismissed: true });
    expect(settingsApi.dismissTrayHint).toHaveBeenCalledTimes(1);
    expect(useThemeStore.getState().trayHintDismissed).toBe(true);
  });

  it('setTrayHintDismissed(true)：PATCH reject → 不推送 IPC + store 回弹 + err toast', async () => {
    patchSettingsMock.mockRejectedValue(new Error('network down'));
    let rejected = false;
    await act(async () => {
      try {
        await themeStateF32().setTrayHintDismissed(true);
      } catch {
        rejected = true;
      }
    });
    expect(rejected).toBe(false);
    expect(useThemeStore.getState().trayHintDismissed).toBe(false);
    expect(settingsApi.dismissTrayHint).not.toHaveBeenCalled();
    expect(useToastStore.getState().toasts.some((t) => t.type === 'err')).toBe(true);
  });
});

/**
 * #199（2026-08-09，rc4 复验缺陷）：设置保存反馈统一化——setter 需向调用方暴露
 * 持久化结果（Promise<boolean>：成功 true / 失败 false，内部 catch 不 rethrow），
 * 供设置页顶部「已保存」指示精确驱动。RED 预期：现状 setFont 返回 void、
 * 行为 setter 失败不 rethrow 但成功/失败无返回值 → resolves.toBe(true) 收到 undefined
 * 或 reject 泄漏（is-not-a-function 已由 F32 用例覆盖，本组为返回值语义升级）。
 */
describe('theme store — #199 setter 持久化结果（保存反馈信号）', () => {
  it('setFont 成功 → resolves true（PATCH 成功返回持久化成功信号）', async () => {
    patchSettingsMock.mockResolvedValue({ ...DEFAULT_SETTINGS, font: 'serif' });
    await expect(themeStateF32().setFont('serif')).resolves.toBe(true);
  });

  it('setFont PATCH reject → resolves false（不 rethrow，失败信号 = false）+ err toast + 本地值保留（乐观更新）', async () => {
    patchSettingsMock.mockRejectedValue(new Error('network down'));
    await expect(themeStateF32().setFont('serif')).resolves.toBe(false);
    expect(useThemeStore.getState().font).toBe('serif'); // 乐观更新不回滚
    expect(useToastStore.getState().toasts.some((t) => t.type === 'err')).toBe(true);
  });

  it('setCloseBehavior 成功 → resolves true（PATCH → IPC → store 更新全链路成功）', async () => {
    patchSettingsMock.mockResolvedValue({ ...DEFAULT_SETTINGS, close_behavior: 'quit' });
    await expect(themeStateF32().setCloseBehavior('quit')).resolves.toBe(true);
    expect(useThemeStore.getState().closeBehavior).toBe('quit');
  });

  it('setCloseBehavior PATCH reject → resolves false（不 rethrow）+ store 回弹 + err toast', async () => {
    patchSettingsMock.mockRejectedValue(new Error('network down'));
    await expect(themeStateF32().setCloseBehavior('quit')).resolves.toBe(false);
    expect(useThemeStore.getState().closeBehavior).toBe('tray'); // 回弹
    expect(useToastStore.getState().toasts.some((t) => t.type === 'err')).toBe(true);
  });

  it('setTrayHintDismissed 成功 → resolves true', async () => {
    patchSettingsMock.mockResolvedValue({ ...DEFAULT_SETTINGS, tray_hint_dismissed: true });
    await expect(themeStateF32().setTrayHintDismissed(true)).resolves.toBe(true);
    expect(useThemeStore.getState().trayHintDismissed).toBe(true);
  });

  it('setTrayHintDismissed PATCH reject → resolves false（不 rethrow）+ store 回弹 + err toast', async () => {
    patchSettingsMock.mockRejectedValue(new Error('network down'));
    await expect(themeStateF32().setTrayHintDismissed(true)).resolves.toBe(false);
    expect(useThemeStore.getState().trayHintDismissed).toBe(false);
    expect(useToastStore.getState().toasts.some((t) => t.type === 'err')).toBe(true);
  });
});
