/**
 * 主题/背景/语言 store（spec §4.3：localStorage 持久化 + 默认策略）
 * —— F32 设置持久化（#152）扩展为统一设置 store（spec §5.2/§5.3）：
 * 视觉设置乐观更新 + 回写缓存 + fire-and-forget PATCH；行为设置 PATCH 成功后才 IPC 推送；
 * initFromBackend 双轨加载（localStorage 快照 → 后端覆盖 → 缓存回写 → 主进程桥接）。
 * 导出名保持 useThemeStore（零破坏既有 import：App.tsx / AppearanceCard / settings.tsx / 测试）。
 */
import { create } from 'zustand';
import {
  ensureApiReady,
  fetchSettings,
  patchSettings,
  type AppSettings,
  type AppSettingsUpdate,
  type CloseBehavior,
} from '../api/client';
import { BG_BY_THEME, type FontKey, type Lang, type ThemeBg, type ThemeName } from '../theme';
import { useToastStore } from './toast';

const STORAGE_KEY = 'inkflow.ui';

/** 缓存层快照（'inkflow.ui'；closeBehavior/trayHintDismissed 不落缓存——无首帧语义，启动后由后端覆盖） */
interface CachedUi {
  theme: ThemeName;
  bg: ThemeBg;
  lang: Lang;
  font: FontKey;
}

function readSaved(): CachedUi | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<CachedUi>;
    return {
      theme: parsed.theme ?? 'paper',
      bg: parsed.bg ?? 'default',
      lang: parsed.lang ?? 'zh',
      font: parsed.font ?? 'sans',
    };
  } catch {
    return null;
  }
}

function writeCache(ui: CachedUi): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(ui));
}

function initialTheme(): ThemeName {
  const saved = readSaved();
  if (saved?.theme) return saved.theme;
  // 默认策略：未手动选择且系统深色偏好 → 夜航；否则素笺
  const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
  return prefersDark ? 'night' : 'paper';
}

/** 失败提示：store 非组件不能调 useI18n，硬编码中文（agent.ts 先例） */
function pushSaveFailed(): void {
  useToastStore.getState().pushToast('err', '保存失败');
}

/** 视觉设置 PATCH：#199 返回持久化结果信号（成功 true / 失败 false，内部 catch 不 rethrow）；
 * 失败 err toast，本地值保留不回滚（§5.2 setter 流程，§7 边界 #7） */
function persistVisual(patch: AppSettingsUpdate): Promise<boolean> {
  return patchSettings(patch)
    .then(() => true)
    .catch(() => {
      pushSaveFailed();
      return false;
    });
}

interface ThemeState {
  theme: ThemeName;
  bg: ThemeBg;
  lang: Lang;
  font: FontKey;
  closeBehavior: CloseBehavior;
  trayHintDismissed: boolean;
  /** #399：用户已通过 UI 视觉 setter 交互标记——initFromBackend 异步返回后端旧值时视觉字段不覆盖（竞态守卫） */
  visualTouched: boolean;

  /** 视觉设置（乐观更新 + 缓存回写 + PATCH）：theme 背景随主题过滤（BG_BY_THEME）；
   * #199：返回持久化结果信号（成功 true / 失败 false） */
  setTheme: (theme: ThemeName) => Promise<boolean>;
  setBg: (bg: ThemeBg) => Promise<boolean>;
  setLang: (lang: Lang) => Promise<boolean>;
  setFont: (font: FontKey) => Promise<boolean>;
  /** 行为设置：PATCH 成功 → IPC 推送主进程 → store 更新；失败 → err toast + 值回弹（§5.3）；
   * #199：返回持久化结果信号（成功 true / 失败 false，不 rethrow） */
  setCloseBehavior: (closeBehavior: CloseBehavior) => Promise<boolean>;
  setTrayHintDismissed: (trayHintDismissed: boolean) => Promise<boolean>;
  /** 双轨加载（§5.2 步骤 ②③④⑤）：ensureApiReady → GET → theme 三分支覆盖 → 缓存回写 → 主进程桥接 */
  initFromBackend: () => Promise<void>;
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: initialTheme(),
  bg: readSaved()?.bg ?? 'default',
  lang: readSaved()?.lang ?? 'zh',
  font: readSaved()?.font ?? 'sans',
  closeBehavior: 'tray',
  trayHintDismissed: false,
  visualTouched: false,

  setTheme: (theme) => {
    // 背景变体随主题过滤（BG_BY_THEME 校验，非法组合回退 default）
    const validBgs = BG_BY_THEME[theme];
    const bg = validBgs.includes(get().bg) ? get().bg : 'default';
    const { lang, font } = get();
    set({ theme, bg, visualTouched: true });
    writeCache({ theme, bg, lang, font });
    return persistVisual({ theme });
  },
  setBg: (bg) => {
    const { theme, lang, font } = get();
    set({ bg, visualTouched: true });
    writeCache({ theme, bg, lang, font });
    return persistVisual({ bg });
  },
  setLang: (lang) => {
    const { theme, bg, font } = get();
    set({ lang, visualTouched: true });
    writeCache({ theme, bg, lang, font });
    return persistVisual({ lang });
  },
  setFont: (font) => {
    const { theme, bg, lang } = get();
    set({ font, visualTouched: true });
    writeCache({ theme, bg, lang, font });
    return persistVisual({ font });
  },
  setCloseBehavior: async (closeBehavior) => {
    try {
      // 持久化先行（§5.3）：PATCH 成功才 IPC 推送 + store 更新
      await patchSettings({ close_behavior: closeBehavior });
      void window.INKFLOW_API?.settings?.setCloseBehavior(closeBehavior);
      const { theme, bg, lang, font } = get();
      set({ closeBehavior });
      writeCache({ theme, bg, lang, font });
      return true;
    } catch {
      // 失败 → err toast + store 不更新（Select 回弹），主进程行为不变（§7 边界 #8）
      pushSaveFailed();
      return false;
    }
  },
  setTrayHintDismissed: async (trayHintDismissed) => {
    try {
      await patchSettings({ tray_hint_dismissed: trayHintDismissed });
      // dismiss 单向：仅 true 时推送主进程（置位「本次会话不再提示」），false 无需复位
      if (trayHintDismissed) {
        void window.INKFLOW_API?.settings?.dismissTrayHint();
      }
      set({ trayHintDismissed });
      return true;
    } catch {
      pushSaveFailed();
      return false;
    }
  },
  initFromBackend: async () => {
    // ② 同步发出 GET（#399 契约：fetch 异步在途时用户交互守卫须已生效——测试以挂起
    // promise 注入竞态时序；真实 Electron 早发失败由下方就绪重试兜底）
    const settingsPromise = fetchSettings();
    // ① Electron 等 preload 注入（15s 兜底）；浏览器 dev 立即返回
    await ensureApiReady();
    const applySettings = (s: AppSettings): void => {
      const saved = readSaved();
      // #399：用户已交互（visualTouched=true）→ 四个视觉字段保留当前值，后端旧值不覆盖；
      // 行为字段（closeBehavior/trayHintDismissed）不受守卫影响，照常取后端值
      const touched = get().visualTouched;
      // ③ theme 三分支覆盖（spec §5.2）：后端非默认覆盖；后端 'paper'（无显式选择）保留本地/当前值
      const nextTheme = touched
        ? get().theme
        : s.theme !== 'paper'
          ? s.theme
          : (saved?.theme ?? get().theme);
      const nextBg = touched ? get().bg : s.bg;
      const nextLang = touched ? get().lang : s.lang;
      const nextFont = touched ? get().font : s.font;
      set({
        theme: nextTheme,
        bg: nextBg,
        lang: nextLang,
        font: nextFont,
        closeBehavior: s.close_behavior,
        trayHintDismissed: s.tray_hint_dismissed,
      });
      writeCache({ theme: nextTheme, bg: nextBg, lang: nextLang, font: nextFont });
      // ⑤ 主进程桥接（§5.3）：close_behavior 非默认 / tray_hint_dismissed 置位才推送；无 IPC 可选链吞掉
      const ipc = window.INKFLOW_API?.settings;
      if (ipc) {
        if (s.close_behavior !== 'tray') void ipc.setCloseBehavior(s.close_behavior);
        if (s.tray_hint_dismissed) void ipc.dismissTrayHint();
      }
    };
    try {
      applySettings(await settingsPromise);
    } catch {
      // #98 兜底：早发失败（preload 未注入 → 首请求 401/内核未起）→ 就绪后重试一次
      await ensureApiReady();
      try {
        applySettings(await fetchSettings());
      } catch (err) {
        // ④ 后端不可达 → 保持 ① 的值继续运行：warn 记录，不抛不 toast（§7 边界 #2/#3）
        console.warn('[settings] 后端设置加载失败，使用本地缓存:', err);
      }
    }
  },
}));
