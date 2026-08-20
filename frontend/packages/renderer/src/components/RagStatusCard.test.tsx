/**
 * #525 RED 契约：RagStatusCard 向量模型选择器（设置页模型分类内嵌卡）。
 *
 * 契约（GREEN 实现，本文件只写测试不改 src/）：
 * - rag-embedding-select：向量模型 Select trigger（枚举注册表 type=embedding 模型，
 *   选项 value/label = `${provider.name}/${model.id}`，如 zhipu/embedding-3）
 * - 切换模型 → 保存调 api/vector.ts 新导出 putEmbeddingModel(provider, modelId)
 *   （PUT /api/v1/vector/embedding-model）→ 成功后重新 fetchVectorStatus 刷新状态
 * - 保存后指纹 reason=model_changed → rag-stale-banner（含模型已变更文案）+
 *   rag-reindex-btn → rag-confirm-dialog → rag-confirm-ok → postVectorReindex（镜像 #276 形态）
 * - providers 无 embedding 模型 → Select 隐藏（rag-status-card 仍渲染）
 *
 * Mock 形态：vi.mock('../api/vector')（fetchVectorStatus/postVectorReindex/putEmbeddingModel）；
 * 真 store（useModelsStore.setState 注入 providers / useProjectStore.setState 注入 currentProjectId）；
 * i18n 真实 useI18n（testid 断言为主；banner 文案断言默认 zh 渲染值，镜像 settings.persistence.test.tsx）。
 *
 * RED 预期：组件未实现 Select/putEmbeddingModel → 用例 1-4 FAIL（element-missing / mock 未被调用）；
 * 用例 5（无 embedding 模型 → Select 隐藏）PASS = 守护用例（当前实现无 Select，符合断言）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RagStatusCard } from './RagStatusCard';
import {
  fetchVectorStatus,
  postVectorReindex,
  putEmbeddingModel,
  type VectorStatusDto,
} from '../api/vector';
import { useModelsStore, type ProviderConfig } from '../stores/models';
import { useProjectStore } from '../stores/project';
import { useToastStore } from '../stores/toast';

vi.mock('../api/vector', () => ({
  fetchVectorStatus: vi.fn(),
  postVectorReindex: vi.fn(),
  putEmbeddingModel: vi.fn(),
}));

const fetchVectorStatusMock = vi.mocked(fetchVectorStatus);
const postVectorReindexMock = vi.mocked(postVectorReindex);
const putEmbeddingModelMock = vi.mocked(putEmbeddingModel);

/** 注册表 fixtures：zhipu 含 embedding-3（embedding）+ glm-4（chat）；ollama 含 nomic-embed-text（embedding） */
const PROVIDERS: ProviderConfig[] = [
  {
    id: 1, name: 'zhipu', base_url: 'https://open.bigmodel.cn/api/paas/v4', default_model: 'glm-4',
    models: [
      { id: 'embedding-3', type: 'embedding', roles: ['rag'] },
      { id: 'glm-4', type: 'chat', roles: ['main'] },
    ],
    key_saved: true, max_retries: 3, timeout: 60,
    created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  },
  {
    id: 2, name: 'ollama', base_url: 'http://127.0.0.1:11434', default_model: '',
    models: [{ id: 'nomic-embed-text', type: 'embedding', roles: ['rag'] }],
    key_saved: false, max_retries: 3, timeout: 60,
    created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  },
];

/** 全 chat 模型 providers（用例 5：无 embedding 模型 → Select 隐藏） */
const CHAT_ONLY_PROVIDERS: ProviderConfig[] = [
  {
    id: 1, name: 'zhipu', base_url: 'https://open.bigmodel.cn/api/paas/v4', default_model: 'glm-4',
    models: [{ id: 'glm-4', type: 'chat', roles: ['main'] }],
    key_saved: true, max_retries: 3, timeout: 60,
    created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  },
];

/** 当前生效 embedding 模型 = zhipu/embedding-3（fresh 状态） */
const FRESH_STATUS: VectorStatusDto = {
  configured_fp: {
    schema_version: 1,
    embedding: { provider: 'zhipu', model_id: 'embedding-3', base_url: 'http://api.test/v1', dimension: 1024 },
    chunking: { mode: 'fixed', chunk_size: 500, overlap_ratio: 0, chunker_version: 1 },
    indexed_at: '2026-08-12T08:00:00Z',
    status: 'fresh',
  },
  indexed_fp: {
    schema_version: 1,
    embedding: { provider: 'zhipu', model_id: 'embedding-3', base_url: 'http://api.test/v1', dimension: 1024 },
    chunking: { mode: 'fixed', chunk_size: 500, overlap_ratio: 0, chunker_version: 1 },
    indexed_at: '2026-08-12T08:00:00Z',
    status: 'fresh',
  },
  stale: false,
  reason: null,
  dimension_mismatch: false,
};

const PUT_RESULT = { ok: true as const, provider: 'ollama', model_id: 'nomic-embed-text' };

beforeEach(() => {
  fetchVectorStatusMock.mockReset();
  postVectorReindexMock.mockReset();
  putEmbeddingModelMock.mockReset();
  useModelsStore.setState({ providers: PROVIDERS });
  useProjectStore.setState({ currentProjectId: 'p1' });
  useToastStore.setState({ toasts: [] });
});

function renderCard() {
  return render(<RagStatusCard />);
}

describe('RagStatusCard — 向量模型选择器（#525）', () => {
  it('test_renders_embedding_model_select：Select 存在，选项含注册表 embedding 模型（provider/model）', async () => {
    fetchVectorStatusMock.mockResolvedValue(FRESH_STATUS);
    const user = userEvent.setup();
    renderCard();
    expect(await screen.findByTestId('rag-status-card')).toBeInTheDocument();

    const trigger = screen.getByTestId('rag-embedding-select');
    expect(trigger).toBeInTheDocument();
    await user.click(trigger);
    // Radix Select 选项（role=option；value/label = provider/model）
    expect(await screen.findByRole('option', { name: 'zhipu/embedding-3' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'ollama/nomic-embed-text' })).toBeInTheDocument();
  });

  it('test_select_current_model_value：Select 当前值 = configured_fp.embedding 的 provider/model', async () => {
    fetchVectorStatusMock.mockResolvedValue(FRESH_STATUS);
    renderCard();
    await screen.findByTestId('rag-status-card');
    // Radix SelectValue 渲染选中项文本到 trigger 内
    expect(screen.getByTestId('rag-embedding-select')).toHaveTextContent('zhipu/embedding-3');
  });

  it('test_switch_embedding_model_calls_api_and_refreshes：切换 → putEmbeddingModel(provider, modelId) + 刷新状态', async () => {
    fetchVectorStatusMock.mockResolvedValue(FRESH_STATUS);
    putEmbeddingModelMock.mockResolvedValue(PUT_RESULT);
    const user = userEvent.setup();
    renderCard();
    await screen.findByTestId('rag-status-card');

    await user.click(screen.getByTestId('rag-embedding-select'));
    await user.click(await screen.findByRole('option', { name: 'ollama/nomic-embed-text' }));

    // 保存调用：provider 与 model_id 拆分传入
    await waitFor(() => {
      expect(putEmbeddingModelMock).toHaveBeenCalledWith('ollama', 'nomic-embed-text');
    });
    // 保存成功 → 重新拉取状态（挂载 1 次 + 保存后 ≥1 次）
    await waitFor(() => {
      expect(fetchVectorStatusMock.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
  });

  it('test_model_changed_banner_and_reindex：保存后指纹 model_changed → stale banner + 重建确认 → postVectorReindex', async () => {
    const STALE_MODEL_CHANGED: VectorStatusDto = { ...FRESH_STATUS, stale: true, reason: 'model_changed' };
    fetchVectorStatusMock.mockResolvedValueOnce(FRESH_STATUS).mockResolvedValue(STALE_MODEL_CHANGED);
    putEmbeddingModelMock.mockResolvedValue(PUT_RESULT);
    const user = userEvent.setup();
    renderCard();
    await screen.findByTestId('rag-status-card');

    // ① 切换向量模型并保存（RED：Select 未实现 → 此处 element-missing FAIL）
    await user.click(screen.getByTestId('rag-embedding-select'));
    await user.click(await screen.findByRole('option', { name: 'ollama/nomic-embed-text' }));
    await waitFor(() => {
      expect(putEmbeddingModelMock).toHaveBeenCalledWith('ollama', 'nomic-embed-text');
    });

    // ② 保存后刷新返回 stale(reason=model_changed) → banner（含模型已变更文案）+ 重建按钮
    const banner = await screen.findByTestId('rag-stale-banner');
    expect(banner.textContent).toContain('模型已变更');
    expect(screen.getByTestId('rag-reindex-btn')).toBeInTheDocument();

    // ③ 重建确认流（镜像 #276 用例形态）
    await user.click(screen.getByTestId('rag-reindex-btn'));
    expect(await screen.findByTestId('rag-confirm-dialog')).toBeInTheDocument();
    await user.click(screen.getByTestId('rag-confirm-ok'));
    await waitFor(() => {
      expect(postVectorReindexMock).toHaveBeenCalledWith('p1');
    });
  });

  it('test_no_embedding_models_hides_select：无 embedding 模型 → Select 隐藏（守护用例）', async () => {
    useModelsStore.setState({ providers: CHAT_ONLY_PROVIDERS });
    fetchVectorStatusMock.mockResolvedValue(FRESH_STATUS);
    renderCard();
    await screen.findByTestId('rag-status-card');
    // 守护断言：当前实现（无 Select）与 GREEN 契约一致 → 本用例 PASS 允许
    expect(screen.queryByTestId('rag-embedding-select')).not.toBeInTheDocument();
  });
});
