/** 内核状态单一真相源（Issue #384 层 1）：三态 status + booted 门控开关，轮询生命周期归 store 管 */
import { create } from 'zustand';
import { apiFetch } from '../api/client';

export type KernelStatus = 'booting' | 'ready' | 'failed';

export interface KernelState {
  status: KernelStatus;
  booted: boolean;
  healthFailures: number;
  checkHealth: () => Promise<void>;
  startPolling: () => void;
  stopPolling: () => void;
  retry: () => void;
}

const POLL_INTERVAL_MS = 5000;
/** 启动期连续失败阈值：POLL_INTERVAL_MS=5000 → t=0/5/10 三次连续失败 ≈ 10s 时间窗 */
const FAILURE_THRESHOLD = 3;

let timer: ReturnType<typeof setInterval> | null = null;

export const useKernelStore = create<KernelState>((set, get) => ({
  status: 'booting',
  booted: false,
  healthFailures: 0,
  checkHealth: async () => {
    try {
      await apiFetch('/health');
      set({ status: 'ready', booted: true, healthFailures: 0 });
    } catch {
      const healthFailures = get().healthFailures + 1;
      if (get().booted || healthFailures >= FAILURE_THRESHOLD) {
        set({ status: 'failed', healthFailures });
      } else {
        set({ healthFailures }); // 未达阈值：保持 booting，只更新计数
      }
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
    set({ status: 'booting', healthFailures: 0 });
    void get().checkHealth();
  },
}));
