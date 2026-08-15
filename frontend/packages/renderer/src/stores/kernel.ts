/** 内核状态单一真相源（Issue #384 层 1）：三态 status + booted 门控开关，轮询生命周期归 store 管 */
import { create } from 'zustand';
import { apiFetch } from '../api/client';

export type KernelStatus = 'booting' | 'ready' | 'failed';

export interface KernelState {
  status: KernelStatus;
  booted: boolean;
  checkHealth: () => Promise<void>;
  startPolling: () => void;
  stopPolling: () => void;
  retry: () => void;
}

const POLL_INTERVAL_MS = 5000;

let timer: ReturnType<typeof setInterval> | null = null;

export const useKernelStore = create<KernelState>((set, get) => ({
  status: 'booting',
  booted: false,
  checkHealth: async () => {
    try {
      await apiFetch('/health');
      set({ status: 'ready', booted: true });
    } catch {
      set({ status: 'failed' });
    }
  },
  startPolling: () => {
    if (timer !== null) return; // 幂等
    void get().checkHealth();
    timer = setInterval(() => void get().checkHealth(), POLL_INTERVAL_MS);
  },
  stopPolling: () => {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  },
  retry: () => {
    set({ status: 'booting' });
    void get().checkHealth();
  },
}));
