/**
 * ⚠️ 契约文件（Issue #106 models store RED 阶段，spec §8.2③ / §8.3 / §8.6 M3/M4）
 *
 * GREEN 新建 src/stores/models.ts，必须匹配：
 *
 * 导出：
 * - useModelsStore（zustand store）
 * - 类型（结构契约，字段名不可改）：
 *   ProviderModel = { id: string; type: 'chat' | 'embedding'; roles: string[] }
 *   ProviderConfig = { id, name, base_url, default_model: string,
 *     models: ProviderModel[], key_saved: boolean,
 *     max_retries: number, timeout: number, created_at: string, updated_at: string }
 *   RoleBindingDraft = { main, architect, writer, auditor, reviser, embedding: string }（六槽位）
 *
 * 状态：
 * - providers: ProviderConfig[]（初始 []）
 * - loading: boolean（初始 false）
 * - error: string | null（初始 null）
 * - selectedModelId: string | null（初始 null）
 * - roleBinding: RoleBindingDraft（初始六槽位全 ''）
 *
 * actions（签名即契约）：
 * - loadProviders(): Promise<void>
 *     GET /api/v1/provider-configs；响应 = FastAPI 列表包装
 *     { items: ProviderConfig[], total, offset, limit }（§4.4 列表端点先例，非裸数组）；
 *     成功 → providers 填充 + loading false；失败 → error + 保留原列表
 * - addProvider(input: { name: string; base_url: string; api_key?: string }): Promise<ProviderConfig>
 *     POST /api/v1/provider-configs（body 含 name / base_url）→ 返回创建结果并加入列表
 * - deleteProvider(id: string): Promise<void>
 *     DELETE /api/v1/provider-configs/{id}；成功 → 从列表移除；
 *     失败（内置 seed 不可删 / 被绑定 used_by）→ error + 列表不变
 * - selectModel(id: string | null): void — 设置选中模型（null 清除）
 * - setRoleBinding(role: keyof RoleBindingDraft, modelId: string): void — 绑定草稿局部更新
 *
 * RED 预期：./models 模块不存在 → module-not-found（类 1 契约缺口）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act } from '@testing-library/react';
import { useModelsStore, type ProviderConfig } from './models';
import { apiFetch, ApiError } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const EMPTY_BINDING = { main: '', architect: '', writer: '', auditor: '', reviser: '', embedding: '' };

const PROVIDERS: ProviderConfig[] = [
  {
    id: 'openai', name: 'openai', base_url: 'https://api.openai.com/v1', default_model: 'gpt-4o',
    models: [
      { id: 'gpt-4o', type: 'chat', roles: ['main', 'writer'] },
      { id: 'text-embedding-3-small', type: 'embedding', roles: ['rag'] },
    ],
    key_saved: true, max_retries: 3, timeout: 60,
    created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  },
  {
    id: 'deepseek', name: 'deepseek', base_url: 'https://api.deepseek.com', default_model: 'deepseek-chat',
    models: [{ id: 'deepseek-chat', type: 'chat', roles: ['architect'] }],
    key_saved: false, max_retries: 3, timeout: 60,
    created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  },
];

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useModelsStore.setState({
    providers: [],
    loading: false,
    error: null,
    selectedModelId: null,
    roleBinding: { ...EMPTY_BINDING },
  });
});

describe('models store — 契约面（GREEN 必须提供）', () => {
  it('暴露 actions: loadProviders / addProvider / deleteProvider / selectModel / setRoleBinding', () => {
    const s = useModelsStore.getState();
    expect(typeof s.loadProviders).toBe('function');
    expect(typeof s.addProvider).toBe('function');
    expect(typeof s.deleteProvider).toBe('function');
    expect(typeof s.selectModel).toBe('function');
    expect(typeof s.setRoleBinding).toBe('function');
  });
});

describe('models store — 初始态', () => {
  it('providers 空 / loading false / error null / selectedModelId null / 角色绑定六槽位空串', () => {
    const s = useModelsStore.getState();
    expect(s.providers).toEqual([]);
    expect(s.loading).toBe(false);
    expect(s.error).toBeNull();
    expect(s.selectedModelId).toBeNull();
    expect(s.roleBinding).toEqual(EMPTY_BINDING);
  });
});

describe('models store — provider 列表加载', () => {
  it('loadProviders 成功：GET /api/v1/provider-configs → providers 填充 + loading false', async () => {
    apiFetchMock.mockResolvedValue({ items: PROVIDERS, total: 2, offset: 0, limit: 50 });
    await act(async () => {
      await useModelsStore.getState().loadProviders();
    });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/provider-configs');
    const s = useModelsStore.getState();
    expect(s.providers).toHaveLength(2);
    expect(s.providers[0].name).toBe('openai');
    expect(s.providers[0].key_saved).toBe(true);
    expect(s.loading).toBe(false);
    expect(s.error).toBeNull();
  });

  it('loadProviders 失败：error 设置 + 原列表保留', async () => {
    apiFetchMock.mockResolvedValue(PROVIDERS);
    await act(async () => {
      await useModelsStore.getState().loadProviders();
    });
    apiFetchMock.mockRejectedValue(new ApiError(500, '内核异常'));
    await act(async () => {
      await useModelsStore.getState().loadProviders();
    });
    const s = useModelsStore.getState();
    expect(s.error).toContain('内核异常');
    expect(s.providers).toHaveLength(2); // 失败不覆盖已加载列表
  });

  it('loadProviders 挂起期间 loading=true，完成后复位 false', async () => {
    let resolveFetch!: (v: unknown) => void;
    apiFetchMock.mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve;
      }),
    );
    let p!: Promise<void>;
    act(() => {
      p = useModelsStore.getState().loadProviders();
    });
    expect(useModelsStore.getState().loading).toBe(true);

    resolveFetch({ items: [], total: 0, offset: 0, limit: 50 });
    await act(async () => {
      await p;
    });
    expect(useModelsStore.getState().loading).toBe(false);
  });
});

describe('models store — 添加 / 删除 provider', () => {
  it('addProvider 成功：POST /api/v1/provider-configs（body 含 name/base_url）→ 新 provider 加入列表', async () => {
    const created: ProviderConfig = {
      id: 'ollama', name: 'ollama', base_url: 'http://127.0.0.1:11434', default_model: '',
      models: [], key_saved: false, max_retries: 3, timeout: 60,
      created_at: '2026-08-06T10:00:00Z', updated_at: '2026-08-06T10:00:00Z',
    };
    apiFetchMock.mockResolvedValue(created);
    await act(async () => {
      await useModelsStore.getState().addProvider({ name: 'ollama', base_url: 'http://127.0.0.1:11434' });
    });
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/v1/provider-configs',
      expect.objectContaining({
        method: 'POST',
        body: expect.objectContaining({ name: 'ollama', base_url: 'http://127.0.0.1:11434' }),
      }),
    );
    const providers = useModelsStore.getState().providers;
    expect(providers.some((p) => p.id === 'ollama')).toBe(true);
  });

  it('addProvider 失败：error 设置 + 列表不变', async () => {
    apiFetchMock.mockRejectedValue(new ApiError(422, '名称已存在'));
    await act(async () => {
      await expect(
        useModelsStore.getState().addProvider({ name: 'openai', base_url: 'https://x' }),
      ).rejects.toThrow('名称已存在');
    });
    const s = useModelsStore.getState();
    expect(s.error).toContain('名称已存在');
    expect(s.providers).toEqual([]);
  });

  it('deleteProvider 成功：DELETE /api/v1/provider-configs/{id} → 从列表移除', async () => {
    apiFetchMock.mockResolvedValue({ items: PROVIDERS, total: 2, offset: 0, limit: 50 });
    await act(async () => {
      await useModelsStore.getState().loadProviders();
    });
    apiFetchMock.mockResolvedValue({ ok: true });
    await act(async () => {
      await useModelsStore.getState().deleteProvider('deepseek');
    });
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/v1/provider-configs/deepseek',
      expect.objectContaining({ method: 'DELETE' }),
    );
    const providers = useModelsStore.getState().providers;
    expect(providers.some((p) => p.id === 'deepseek')).toBe(false);
    expect(providers.some((p) => p.id === 'openai')).toBe(true);
  });

  it('deleteProvider 失败（内置 seed 不可删）：error + 列表不变', async () => {
    apiFetchMock.mockResolvedValue({ items: PROVIDERS, total: 2, offset: 0, limit: 50 });
    await act(async () => {
      await useModelsStore.getState().loadProviders();
    });
    apiFetchMock.mockRejectedValue(new ApiError(409, '内置 Provider 不可删除'));
    await act(async () => {
      await useModelsStore.getState().deleteProvider('openai');
    });
    const s = useModelsStore.getState();
    expect(s.error).toContain('内置 Provider 不可删除');
    expect(s.providers).toHaveLength(2);
  });
});

describe('models store — 选中模型', () => {
  it('selectModel 设置 / 清除选中模型', () => {
    act(() => {
      useModelsStore.getState().selectModel('gpt-4o');
    });
    expect(useModelsStore.getState().selectedModelId).toBe('gpt-4o');
    act(() => {
      useModelsStore.getState().selectModel(null);
    });
    expect(useModelsStore.getState().selectedModelId).toBeNull();
  });
});

describe('models store — 角色绑定草稿（主模型 / 四角色 / RAG embedding）', () => {
  it('setRoleBinding 局部更新：只改指定槽位，其余槽位不变', () => {
    act(() => {
      useModelsStore.getState().setRoleBinding('main', 'gpt-4o');
    });
    act(() => {
      useModelsStore.getState().setRoleBinding('embedding', 'text-embedding-3-small');
    });
    const b = useModelsStore.getState().roleBinding;
    expect(b.main).toBe('gpt-4o');
    expect(b.embedding).toBe('text-embedding-3-small');
    // 未涉及的槽位保持初始空串
    expect(b.architect).toBe('');
    expect(b.writer).toBe('');
    expect(b.auditor).toBe('');
    expect(b.reviser).toBe('');
  });

  it('六槽位逐一可设：主模型 + 四角色 + RAG embedding 互不覆盖', () => {
    const slots: Array<[keyof typeof EMPTY_BINDING, string]> = [
      ['main', 'gpt-4o'],
      ['architect', 'deepseek-chat'],
      ['writer', 'gpt-4o'],
      ['auditor', 'glm-4'],
      ['reviser', 'deepseek-chat'],
      ['embedding', 'text-embedding-3-small'],
    ];
    act(() => {
      for (const [role, modelId] of slots) {
        useModelsStore.getState().setRoleBinding(role, modelId);
      }
    });
    const b = useModelsStore.getState().roleBinding;
    for (const [role, modelId] of slots) {
      expect(b[role]).toBe(modelId);
    }
  });
});
