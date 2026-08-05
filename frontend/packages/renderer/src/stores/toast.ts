/** Toast store（spec §6.2①：三态 / 2s 自动消失 / Q3=B 队列堆叠上限 3） */
import { create } from 'zustand';

export type ToastType = 'ok' | 'err' | 'warn';

export interface Toast {
  id: string;
  type: ToastType;
  message: string;
}

export interface ToastState {
  toasts: Toast[];
  pushToast: (type: ToastType, message: string) => void;
  dismissToast: (id: string) => void;
}

const TOAST_TTL_MS = 2000;
const MAX_TOASTS = 3;

let idCounter = 0;

/** 唯一非空 id：优先 crypto.randomUUID，兜底时间戳 + 计数器（jsdom/旧环境） */
function nextToastId(): string {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === 'function') return c.randomUUID();
  idCounter += 1;
  return `toast-${Date.now()}-${idCounter}`;
}

/** 每条 toast 的定时器句柄（手动 dismiss 时清理，防止定时器重复触发） */
const timers = new Map<string, ReturnType<typeof setTimeout>>();

export const useToastStore = create<ToastState>((set, get) => ({
  toasts: [],

  pushToast: (type, message) => {
    const id = nextToastId();
    const prev = get().toasts;
    // Q3=B：队列堆叠上限 3，第 4 条丢弃最早一条
    const dropped = prev.length >= MAX_TOASTS ? prev[prev.length - MAX_TOASTS] : undefined;
    set({ toasts: [...prev, { id, type, message }].slice(-MAX_TOASTS) });
    // 被弃条的定时器一并清理，避免 timers Map 泄漏（dismissToast 幂等，但定时器属无效）
    if (dropped !== undefined) {
      const timer = timers.get(dropped.id);
      if (timer !== undefined) {
        clearTimeout(timer);
        timers.delete(dropped.id);
      }
    }
    timers.set(id, setTimeout(() => get().dismissToast(id), TOAST_TTL_MS));
  },

  dismissToast: (id) => {
    const timer = timers.get(id);
    if (timer !== undefined) {
      clearTimeout(timer);
      timers.delete(id);
    }
    // 幂等：不存在的 id 直接 no-op
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
  },
}));
