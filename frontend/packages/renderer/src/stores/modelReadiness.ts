/**
 * F60 首启模型就绪 store（#934 §5.1/§5.6）——GUI 门控与语义检索置灰的单一真相。
 *
 * 判据来源：`GET /api/v1/settings/model-readiness`（后端派生判据，spec §2.1）。
 * 失败（网络/500）→ readiness=null（按「未就绪」保守处理，不阻塞可重试）。
 *
 * #1218 自愈：查询不再是一次性的——`startPolling` / `stopPolling` 让 App 在**未就绪**
 * 期间持续重查（镜像 `useKernelStore` 的轮询模式），外部（CLI/API/另一窗口）完成配置后
 * 主 UI 自动放行，无需手动刷新/重启。
 */
import { create } from 'zustand';
import { apiFetch } from '../api/client';

export interface ModelReadiness {
  ready: boolean;
  has_chat_model: boolean;
  has_embedding_model: boolean;
  reason: 'ready' | 'no_provider' | 'no_chat_model' | 'no_key';
}

interface ModelReadinessState {
  readiness: ModelReadiness | null;
  loading: boolean;
  /** 查询就绪判据（GET /api/v1/settings/model-readiness）；失败 → readiness=null */
  load: () => Promise<void>;
  /** #1218：未就绪期间持续重查（幂等；就绪后自行停止） */
  startPolling: () => void;
  /** #1218：停止重查（卸载时调用，防定时器泄漏） */
  stopPolling: () => void;
}

/** #1218 未就绪重查间隔（与 useKernelStore.POLL_INTERVAL_MS 同量级：轮询是兜底，代价可忽略） */
export const READINESS_POLL_INTERVAL_MS = 5000;

//: #1218 模块级单例定时器（镜像 useKernelStore）——App 实例与测试共享，stopPolling 可外部复位
let timer: ReturnType<typeof setInterval> | null = null;

export const useModelReadinessStore = create<ModelReadinessState>((set, get) => ({
  readiness: null,
  loading: false,

  load: async () => {
    set({ loading: true });
    try {
      const data = await apiFetch<ModelReadiness>('/api/v1/settings/model-readiness');
      set({ readiness: data, loading: false });
    } catch {
      // spec §7 边界 #6：查询失败不阻塞 GUI——按未就绪处理，可重试
      set({ readiness: null, loading: false });
    }
  },

  startPolling: () => {
    if (timer !== null) return; // 幂等
    void get().load();
    timer = setInterval(() => {
      if (get().readiness?.ready === true) {
        get().stopPolling(); // 就绪即停：避免无谓请求
        return;
      }
      void get().load();
    }, READINESS_POLL_INTERVAL_MS);
  },

  stopPolling: () => {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  },
}));

/**
 * N2 判据：语义检索是否可用（需 embedding 模型）。
 *
 * null（未查询/查询失败）→ false（保守：不可用）。
 */
export function canUseSemanticSearch(readiness: ModelReadiness | null): boolean {
  return readiness?.has_embedding_model === true;
}

/** 引导/主路径共用的模型管理入口 hash 路由（R5「前往配置」跳转目标）。 */
export const MODEL_SETTINGS_ROUTE = '/settings?cat=models';
