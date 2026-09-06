/**
 * #957 F58 §4.3：远端 i18n 目录消费（GET /api/v1/i18n/messages，F57 双层）。
 * load 单飞：loadedLang 命中或同 lang 在途 → 直接 return；失败静默（保留旧值，tScope 走本地回退）。
 * 依赖方向：stores/i18n → api/logs（fetchLogMessages）→ api/client，无环。
 */
import { create } from 'zustand';
import { fetchLogMessages } from '../api/logs';
import { tStatic } from '../i18n/useI18n';

/** 同 lang 在途标记（模块级；与 store 状态解耦，防双 fetch） */
let inflightLang: string | null = null;

/** 简单占位替换：{n} → params[n]（与 useI18n 同语义） */
function interpolate(template: string, params?: Record<string, string | number>): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (_, key: string) =>
    key in params ? String(params[key]) : `{${key}}`,
  );
}

export const useI18nMessagesStore = create<{
  messages: Record<string, string>;
  loadedLang: string | null;
  load: (lang: string) => Promise<void>;
}>((set, get) => ({
  messages: {},
  loadedLang: null,
  load: async (lang: string): Promise<void> => {
    if (get().loadedLang === lang || inflightLang === lang) return;
    inflightLang = lang;
    try {
      const messages = await fetchLogMessages(lang);
      // 空目录（如 {ok:true} 无 data 的兜底响应）按 {} 处理，本地回退仍可用
      set({ messages: messages ?? {}, loadedLang: lang });
    } catch {
      // 失败静默：messages/loadedLang 不变
    } finally {
      inflightLang = null;
    }
  },
}));

/**
 * 双层取词 hook：远端目录命中 > 本地 t()（含 zh 回退链）。
 * 纯状态读取（zustand/theme getState），不订阅 React——渲染时随组件重渲刷新；
 * 测试可在组件外直接调用 useTScope()。
 */
export function useTScope(): (key: string, params?: Record<string, string | number>) => string {
  return (key, params) => {
    const remote = useI18nMessagesStore.getState().messages[key];
    if (remote !== undefined) return interpolate(remote, params);
    return tStatic(key, params);
  };
}
