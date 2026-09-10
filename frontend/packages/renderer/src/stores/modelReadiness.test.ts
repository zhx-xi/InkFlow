/**
 * F60 首启模型就绪 store 契约（RED — #934 §5.1/§9.3）。
 *
 * ⚠️ 本文件 = 契约。GREEN 必须新建 src/stores/modelReadiness.ts，导出：
 *
 *   export interface ModelReadiness {
 *     ready: boolean;
 *     has_chat_model: boolean;
 *     has_embedding_model: boolean;
 *     reason: 'ready' | 'no_provider' | 'no_chat_model' | 'no_key';
 *   }
 *
 *   export const useModelReadinessStore = create<...>()  // 含：
 *     readiness: ModelReadiness | null   // null = 尚未查询/查询失败
 *     loading: boolean
 *     load: () => Promise<void>          // GET /api/v1/settings/model-readiness
 *
 *   export function canUseSemanticSearch(r: ModelReadiness | null): boolean
 *     // has_embedding_model 为 true 才可用（N2 置灰判据）
 *
 * 行为契约：
 * - load 成功 → readiness 填充 + loading=false
 * - load 失败（网络/500）→ readiness=null + loading=false（**不阻塞**：
 *   按「未就绪」处理，GUI 可重试——spec §7 边界 #6）
 * - canUseSemanticSearch(null) → false（未查询 = 不可用，保守）
 * - canUseSemanticSearch({has_embedding_model:true}) → true
 *
 * RED 预期：./modelReadiness 模块不存在 → module-not-found。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { apiFetch } from '../api/client';
import {
  canUseSemanticSearch,
  useModelReadinessStore,
  type ModelReadiness,
} from './modelReadiness';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const ready: ModelReadiness = {
  ready: true,
  has_chat_model: true,
  has_embedding_model: true,
  reason: 'ready',
};

const notReady: ModelReadiness = {
  ready: false,
  has_chat_model: false,
  has_embedding_model: false,
  reason: 'no_provider',
};

describe('modelReadiness store（#934）', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    useModelReadinessStore.setState({ readiness: null, loading: false });
  });

  it('load 成功 → readiness 填充 + loading=false', async () => {
    apiFetchMock.mockResolvedValue(ready);
    await useModelReadinessStore.getState().load();
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/settings/model-readiness');
    expect(useModelReadinessStore.getState().readiness).toEqual(ready);
    expect(useModelReadinessStore.getState().loading).toBe(false);
  });

  it('load 失败 → readiness=null + loading=false（不阻塞，可重试）', async () => {
    apiFetchMock.mockRejectedValue(new Error('boom'));
    await useModelReadinessStore.getState().load();
    expect(useModelReadinessStore.getState().readiness).toBeNull();
    expect(useModelReadinessStore.getState().loading).toBe(false);
  });

  it('未查询（null）→ canUseSemanticSearch=false（保守）', () => {
    expect(canUseSemanticSearch(null)).toBe(false);
  });

  it('有 embedding 模型 → canUseSemanticSearch=true（N2）', () => {
    expect(canUseSemanticSearch(ready)).toBe(true);
  });

  it('无 embedding 模型（跳过步骤 3）→ canUseSemanticSearch=false（N2 置灰）', () => {
    const skipped: ModelReadiness = { ...ready, has_embedding_model: false };
    expect(canUseSemanticSearch(skipped)).toBe(false);
  });

  it('未就绪（no_provider）→ canUseSemanticSearch=false', () => {
    expect(canUseSemanticSearch(notReady)).toBe(false);
  });
});
