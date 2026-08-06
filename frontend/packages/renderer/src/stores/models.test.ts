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
 *     ⚠️ F10 评审修正（2026-08-06）：契约与 mock 一律 {items,total} 信封——后端真实
 *     返回即信封；「裸数组兼容」分支（Array.isArray）为死代码，GREEN 删除
 * - addProvider(input: { name: string; base_url: string; api_key?: string }): Promise<ProviderConfig>
 *     POST /api/v1/provider-configs（body 含 name / base_url）→ 返回创建结果并加入列表
 * - addModel(providerId: string, model: ProviderModel): Promise<void>（F3 评审新增，spec §8.2③ L929 多选一次性添加）
 *     PATCH /api/v1/provider-configs/{providerId}，body.models = 追加后完整数组
 *     （后端 ProviderConfigUpdate.models 为 exclude_unset 整体替换——只发新模型会覆盖丢失既有模型，
 *     必须携带「既有 models + 新 model」全量；多选添加 = UI 对每个选中模型调用一次或合并调用，store 契约按单模型）；
 *     成功 → 该 provider 的 models 更新为追加后列表（以 PATCH 响应为准）；失败 → error + 列表不变
 * - deleteProvider(id: string): Promise<void>
 *     DELETE /api/v1/provider-configs/{id}；成功 → 从列表移除；
 *     失败（内置 seed 不可删 / 被绑定 used_by）→ error + 列表不变
 * - selectModel(id: string | null): void — 设置选中模型（null 清除）
 * - setRoleBinding(role: keyof RoleBindingDraft, modelId: string): void — 绑定草稿局部更新
 *
 * RED 预期（本批为评审修复契约，实现已存在）：addModel 未实现 → is-not-a-function
 * （类 2 契约缺口）；其余既有用例保持绿（F10 mock 信封修正后仍绿——实现已按信封消费）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act } from '@testing-library/react';
import { useModelsStore, type ProviderConfig, type ProviderModel } from './models';
import { apiFetch, ApiError } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

/**
 * F3 契约增强类型：addModel 尚未在 ModelsState 声明（GREEN 补全后此 cast 可删）。
 * RED 阶段测试直接引用未实现 action 会使 tsc 报属性不存在——cast 保持文件类型健全，
 * 运行时仍走真实 store（addModel 缺失 → TypeError = 预期 RED 证据）。
 */
type ModelsStateWithAddModel = ReturnType<typeof useModelsStore.getState> & {
  addModel: (providerId: string, model: ProviderModel) => Promise<void>;
};
const stateWithAddModel = () => useModelsStore.getState() as ModelsStateWithAddModel;

const EMPTY_BINDING = { main: '', architect: '', writer: '', auditor: '', reviser: '', embedding: '' };

const PROVIDERS: ProviderConfig[] = [
  {
    id: 1, name: 'openai', base_url: 'https://api.openai.com/v1', default_model: 'gpt-4o',
    models: [
      { id: 'gpt-4o', type: 'chat', roles: ['main', 'writer'] },
      { id: 'text-embedding-3-small', type: 'embedding', roles: ['rag'] },
    ],
    key_saved: true, max_retries: 3, timeout: 60,
    created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  },
  {
    id: 2, name: 'deepseek', base_url: 'https://api.deepseek.com', default_model: 'deepseek-chat',
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
  it('暴露 actions: loadProviders / addProvider / addModel / deleteProvider / selectModel / setRoleBinding', () => {
    const s = useModelsStore.getState();
    expect(typeof s.loadProviders).toBe('function');
    expect(typeof s.addProvider).toBe('function');
    // F3 评审新增：addModel（模型多选一次性添加，spec §8.2③ L929）
    expect(typeof stateWithAddModel().addModel).toBe('function');
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
    // F10 评审修正：mock 统一 {items,total} 信封（后端真实返回形状；裸数组兼容分支为死代码）
    apiFetchMock.mockResolvedValue({ items: PROVIDERS, total: 2, offset: 0, limit: 50 });
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
      id: 3, name: 'ollama', base_url: 'http://127.0.0.1:11434', default_model: '',
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
    expect(providers.some((p) => p.id === 3)).toBe(true);
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
      await useModelsStore.getState().deleteProvider(2);
    });
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/v1/provider-configs/2',
      expect.objectContaining({ method: 'DELETE' }),
    );
    const providers = useModelsStore.getState().providers;
    expect(providers.some((p) => p.id === 2)).toBe(false);
    expect(providers.some((p) => p.id === 1)).toBe(true);
  });

  it('deleteProvider 失败（内置 seed 不可删）：error + 列表不变', async () => {
    apiFetchMock.mockResolvedValue({ items: PROVIDERS, total: 2, offset: 0, limit: 50 });
    await act(async () => {
      await useModelsStore.getState().loadProviders();
    });
    apiFetchMock.mockRejectedValue(new ApiError(409, '内置 Provider 不可删除'));
    await act(async () => {
      await useModelsStore.getState().deleteProvider(1);
    });
    const s = useModelsStore.getState();
    expect(s.error).toContain('内置 Provider 不可删除');
    expect(s.providers).toHaveLength(2);
  });
});

describe('models store — 添加模型（F3 评审新增，spec §8.2③ L929 多选一次性添加）', () => {
  it('addModel 成功：PATCH /api/v1/provider-configs/{id}（body.models = 追加后完整数组）→ store 更新', async () => {
    // 播种：openai provider 已加载（2 个既有模型）
    apiFetchMock.mockResolvedValue({ items: PROVIDERS, total: 2, offset: 0, limit: 50 });
    await act(async () => {
      await useModelsStore.getState().loadProviders();
    });

    const newModel: ProviderModel = { id: 'gpt-4o-mini', type: 'chat', roles: ['writer'] };
    // PATCH 响应 = 追加后的 ProviderConfig（后端整体替换后返回完整实体）
    const updated: ProviderConfig = {
      ...PROVIDERS[0],
      models: [...PROVIDERS[0].models, newModel],
    };
    apiFetchMock.mockResolvedValue(updated);
    await act(async () => {
      await stateWithAddModel().addModel(1, newModel);
    });

    // 整体替换语义：body.models 必须携带既有模型 + 新模型（只发新模型会覆盖丢失）
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/v1/provider-configs/1',
      expect.objectContaining({
        method: 'PATCH',
        body: expect.objectContaining({
          models: expect.arrayContaining([
            expect.objectContaining({ id: 'gpt-4o' }),
            expect.objectContaining({ id: 'text-embedding-3-small' }),
            expect.objectContaining({ id: 'gpt-4o-mini', type: 'chat', roles: ['writer'] }),
          ]),
        }),
      }),
    );
    // store 状态更新：openai 的 models = 追加后列表
    const openai = useModelsStore.getState().providers.find((p) => p.id === 1);
    expect(openai?.models.map((m) => m.id)).toEqual(['gpt-4o', 'text-embedding-3-small', 'gpt-4o-mini']);
    expect(useModelsStore.getState().error).toBeNull();
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
