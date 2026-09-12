/**
 * 模型管理 store（Issue #106，spec §8.2③ / §8.3 / §8.6 M3/M4）：
 * provider 注册表加载/增删 + 选中模型 + 角色绑定草稿（六槽位）。
 */
import { create } from 'zustand';
import { apiFetch, errorMessage } from '../api/client';

export interface ProviderModel {
  id: string;
  type: 'chat' | 'embedding';
  roles: string[];
  /** F59 M2 回显：模型是否支持思考；null/undefined = 未探测（能力未知） */
  supports_reasoning?: boolean | null;
  /** F59 #965：手动覆盖标记（仅注册表存有手动值时响应携带；其余条目无此键） */
  supports_reasoning_manual?: boolean | null;
}

export interface ProviderConfig {
  id: number;
  name: string;
  base_url: string;
  default_model: string;
  models: ProviderModel[];
  key_saved: boolean;
  max_retries: number;
  timeout: number;
  created_at: string;
  updated_at: string;
}

/** 列表端点响应信封（§4.4 惯例：{ items, total, offset, limit }） */
export interface ProviderListResponse {
  items: ProviderConfig[];
  total: number;
  offset?: number;
  limit?: number;
}

/**
 * #1129：chat 模型候选的第二数据源（GET /api/v1/provider-configs/chat-model-options）。
 *
 * 注册表 `models[]` 之外的真实可用模型（项目级 / 全局默认），用于让
 * `selectChatModelOptions` 与后端就绪判据同源。
 */
export interface ChatModelOptionSource {
  /** 项目级 config.model 中可解析为 chat 的候选 */
  project_models?: string[];
  /** 全局默认（config.llm_default_model） */
  default_model?: string;
}

/** #1129 下拉同源端点响应（字段与后端契约一致） */
export interface ChatModelOptionsResponse extends ChatModelOptionSource {
  options: Array<{ provider: string; model: string; source: string; has_key: boolean }>;
  chat_models: string[];
  available_model: string;
}

/** 角色绑定草稿：写作主模型 + 四角色 + RAG embedding（六槽位） */
export interface RoleBindingDraft {
  main: string;
  architect: string;
  writer: string;
  auditor: string;
  reviser: string;
  embedding: string;
}

export const EMPTY_ROLE_BINDING: RoleBindingDraft = {
  main: '',
  architect: '',
  writer: '',
  auditor: '',
  reviser: '',
  embedding: '',
};

export interface AddProviderInput {
  name: string;
  base_url: string;
  api_key?: string;
}

interface ModelsState {
  providers: ProviderConfig[];
  loading: boolean;
  error: string | null;
  selectedModelId: string | null;
  roleBinding: RoleBindingDraft;
  /** #1129：注册表之外的 chat 候选（项目级 / 全局默认），由 loadProviders 一并拉取 */
  chatModelSource: ChatModelOptionSource;

  loadProviders: () => Promise<void>;
  addProvider: (input: AddProviderInput) => Promise<ProviderConfig>;
  /** #936 C：options.force=true 跳过保存前探测门禁（用户确认强制保存后调用） */
  addModel: (
    providerId: number,
    model: ProviderModel,
    options?: { force?: boolean },
  ) => Promise<void>;
  /** F59 #965：手动覆盖思考能力（true/false=强制，null=恢复自动探测）→ PATCH models 全量替换 */
  setModelReasoning: (
    providerId: number,
    modelId: string,
    value: boolean | null,
    options?: { force?: boolean },
  ) => Promise<void>;
  deleteProvider: (id: number) => Promise<void>;
  selectModel: (id: string | null) => void;
  setRoleBinding: (role: keyof RoleBindingDraft, modelId: string) => void;
}

export const useModelsStore = create<ModelsState>((set, get) => ({
  providers: [],
  loading: false,
  error: null,
  selectedModelId: null,
  roleBinding: { ...EMPTY_ROLE_BINDING },
  chatModelSource: {},

  loadProviders: async () => {
    set({ loading: true, error: null });
    try {
      // 列表端点惯例：{ items, total } 信封（F10 评审：后端真实返回即信封，
      // 裸数组兼容分支为死代码，已删除）
      const data = await apiFetch<ProviderListResponse>('/api/v1/provider-configs');
      const providers = data.items;
      // #1129：并行拉同源候选（项目级 / 全局默认）；失败不影响注册表加载
      const source = await fetchChatModelSource();
      set({ providers, chatModelSource: source, loading: false, error: null });
    } catch (err) {
      // 失败不清空已加载列表
      set({ error: errorMessage(err), loading: false });
    }
  },

  addProvider: async (input) => {
    const { name, base_url, api_key } = input;
    try {
      // Q3 主路径：填了 Key 先加密落盘（/settings/llm-keys），再注册 provider-configs
      if (api_key) {
        await apiFetch('/api/v1/settings/llm-keys', {
          method: 'POST',
          body: { provider: name, api_key },
        });
      }
      const created = await apiFetch<ProviderConfig>('/api/v1/provider-configs', {
        method: 'POST',
        body: { name, base_url },
      });
      set((s) => ({ providers: [...s.providers, created], error: null }));
      return created;
    } catch (err) {
      set({ error: errorMessage(err) });
      throw err;
    }
  },

  addModel: async (providerId, model, options) => {
    try {
      const target = get().providers.find((p) => p.id === providerId);
      if (!target) throw new Error('Provider 不存在');
      const force = options?.force === true;
      // #936 C：探测门禁失败 → 422（detail 含 force 提示）；force=true 重发跳过门禁
      const updated = await apiFetch<ProviderConfig>(
        `/api/v1/provider-configs/${providerId}${force ? '?force=true' : ''}`,
        {
          method: 'PATCH',
          // 后端 ProviderConfigUpdate.models 为 exclude_unset 整体替换：
          // 必须携带「既有 models + 新模型」全量，只发新模型会覆盖丢失（F3 契约）
          body: { models: [...target.models.filter((m) => m.id !== model.id), model] },
        },
      );
      set((s) => ({
        providers: s.providers.map((p) => (p.id === providerId ? updated : p)),
        error: null,
      }));
    } catch (err) {
      // 失败：error 设置 + 列表不变（deleteProvider 同款语义）；
      // #125 契约升级：rethrow（不吞）——AddModelDialog 批量保存依赖 reject 感知失败行
      set({ error: errorMessage(err) });
      throw err;
    }
  },

  setModelReasoning: async (providerId, modelId, value, options) => {
    try {
      const target = get().providers.find((p) => p.id === providerId);
      if (!target) throw new Error('Provider 不存在');
      // 全量替换：目标模型 supports_reasoning=value，其余模型原样保留（PATCH 覆盖语义）
      const models = target.models.map((m) =>
        m.id === modelId ? { ...m, supports_reasoning: value } : m,
      );
      // #936 C：条目内容有变 → 过探测门禁；force=true 跳过（用户确认强制保存）
      const force = options?.force === true;
      const updated = await apiFetch<ProviderConfig>(
        `/api/v1/provider-configs/${providerId}${force ? '?force=true' : ''}`,
        {
          method: 'PATCH',
          body: { models },
        },
      );
      set((s) => ({
        providers: s.providers.map((p) => (p.id === providerId ? updated : p)),
        error: null,
      }));
    } catch (err) {
      // 失败：error 设置 + 列表不变（镜像 addModel）；rethrow 供 UI 感知失败
      set({ error: errorMessage(err) });
      throw err;
    }
  },

  deleteProvider: async (id) => {
    try {
      await apiFetch(`/api/v1/provider-configs/${id}`, { method: 'DELETE' });
      set((s) => ({ providers: s.providers.filter((p) => p.id !== id), error: null }));
    } catch (err) {
      // 失败（内置 seed 409 / used_by）：列表不变，错误上抛到 error 状态
      set({ error: errorMessage(err) });
    }
  },

  selectModel: (id) => set({ selectedModelId: id }),

  setRoleBinding: (role, modelId) =>
    set((s) => ({ roleBinding: { ...s.roleBinding, [role]: modelId } })),
}));

/**
 * #1129：拉取注册表之外的 chat 候选（项目级 / 全局默认）。
 *
 * 端点内部已降级（永不 5xx），此处再兜一层：任何异常 → `{}`，
 * 绝不让下拉数据源拖垮 `loadProviders`（注册表加载是主路径）。
 */
async function fetchChatModelSource(): Promise<ChatModelOptionSource> {
  try {
    const data = await apiFetch<ChatModelOptionsResponse>(
      '/api/v1/provider-configs/chat-model-options',
    );
    return { project_models: data.project_models, default_model: data.default_model };
  } catch {
    return {};
  }
}

/** F42 #268：chat 模型扁平化选项（provider/model 格式，Q3）——供 AgentChainCard 与 AgentPanel 共用。
 *
 * #1129：注册表 `models[type=='chat']` 不是唯一数据源——正常路径（`llm set-key` 只写 key、
 * #735 D2 自动设默认只写 config.json）从不回写 models[]，只认注册表会让首启引导页下拉全空
 * （用户死路）。故并入后端同源端点的候选（项目级 / provider 默认 / 全局默认）。
 * `extra` 缺省 → 行为与 #1129 之前完全一致（纯注册表）。
 */
export function selectChatModelOptions(
  providers: ProviderConfig[],
  extra?: ChatModelOptionSource,
): Array<{ value: string; label: string }> {
  const options: Array<{ value: string; label: string }> = [];
  const seen = new Set<string>();
  const push = (value: string) => {
    if (!value || seen.has(value)) return;
    seen.add(value);
    options.push({ value, label: value });
  };
  for (const p of providers) {
    for (const m of p.models) {
      if (m.type === 'chat') push(`${p.name}/${m.id}`);
    }
  }
  for (const raw of [...(extra?.project_models ?? []), extra?.default_model ?? '']) {
    const model = (raw ?? '').trim();
    if (model.includes('/')) push(model);
  }
  return options;
}

/** #474：是否存在可用 chat 模型（provider key_saved=true 且含 chat 类型模型） */
export function hasChatModel(providers: ProviderConfig[]): boolean {
  return providers.some((p) => p.key_saved && p.models.some((m) => m.type === 'chat'));
}

/** #474：发送前确保模型注册表已加载并判定有可用 chat 模型（providers 空时先 loadProviders） */
export async function ensureModelReady(): Promise<boolean> {
  const s = useModelsStore.getState();
  if (s.providers.length === 0 && !s.loading) {
    await s.loadProviders();
  }
  return hasChatModel(useModelsStore.getState().providers);
}

/** F59-M3 (#964)：provider/model → supports_reasoning 能力判定（chat 选择器置灰数据源）。
 *
 * 模型串须为 'provider/model' 形态：先按 provider 名找 ProviderConfig，再按模型 id 找
 * ProviderModel；找不到 / model 为空 / supports_reasoning 为 null|undefined → null
 * （未知 = 不禁用，软降级 A5）；否则返回该布尔值。
 */
export function modelSupportsReasoning(
  providers: ProviderConfig[],
  model: string | null | undefined,
): boolean | null {
  if (!model) return null;
  const sep = model.indexOf('/');
  if (sep === -1) return null;
  const providerName = model.slice(0, sep);
  const modelId = model.slice(sep + 1);
  const provider = providers.find((p) => p.name === providerName);
  const entry = provider?.models.find((m) => m.id === modelId);
  if (!entry) return null;
  const supports = entry.supports_reasoning;
  return supports === undefined || supports === null ? null : supports;
}
