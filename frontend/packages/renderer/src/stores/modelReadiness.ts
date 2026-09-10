/**
 * F60 首启模型就绪 store（#934 §5.1/§5.6）——GUI 门控与语义检索置灰的单一真相。
 *
 * 判据来源：`GET /api/v1/settings/model-readiness`（后端派生判据，spec §2.1）。
 * 失败（网络/500）→ readiness=null（按「未就绪」保守处理，不阻塞可重试）。
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
}

export const useModelReadinessStore = create<ModelReadinessState>((set) => ({
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
