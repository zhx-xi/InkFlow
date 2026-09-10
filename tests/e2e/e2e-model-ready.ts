/**
 * F60 #934 E2E 首启引导门控基建：把「已配置模型」的安装态预置进隔离内核。
 *
 * 背景：#934 之后 App 在「无可用 chat 模型」时渲染首启引导（全覆盖主 UI）。
 * E2E 使用 mkdtemp 隔离数据目录 = 全新安装态 → 所有测「其它功能」的 spec 会被
 * 引导挡住而误红。本模块提供 ensureModelConfigured()：经内核 API 幂等预置
 * 一个含 chat 模型的 provider + key，使 readiness 判据转 true，等价于
 * 「用户已完成首启引导」的安装态。
 *
 * 纯 Node 模块（禁 import @playwright/test，#415 vitest 加载约束）；
 * 不依赖 tests/e2e 内其他 helper，可被任意 spec 直接调用。
 */

/** 与各 spec 本地 KernelInfo 结构一致（pid/port/token） */
export interface KernelInfoLike {
  pid: number;
  port: number;
  token: string;
}

/** 预置 provider 名（内置 seed 已含 deepseek 行，此处幂等复用） */
const PROVIDER_NAME = 'deepseek';
/** 预置 chat 模型裸名（ProviderModel.id） */
const CHAT_MODEL_ID = 'deepseek-chat';
/** 预置 API Key 值（E2E 桩值，仅用于让 key_saved=true；不发起真实 LLM 调用） */
const FAKE_API_KEY = 'sk-e2e-f60-placeholder';

interface ApiResult {
  status: number;
  data: unknown;
}

/** 直调内核 API（镜像各 spec 既有 apiJson：非 2xx 抛错；204 → data undefined） */
async function apiJson(
  kernel: KernelInfoLike,
  method: string,
  pathname: string,
  body?: unknown,
): Promise<ApiResult> {
  const res = await fetch(`http://127.0.0.1:${kernel.port}${pathname}`, {
    method,
    headers: {
      'X-InkFlow-Token': kernel.token,
      'Content-Type': 'application/json',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`kernel API ${method} ${pathname} -> ${res.status}: ${detail}`);
  }
  const data = res.status === 204 ? undefined : await res.json();
  return { status: res.status, data };
}

/**
 * 幂等预置「可解析 chat 模型 + 有效 key」安装态（#934 F60）。
 *
 * 步骤（全部幂等，可重复调用）：
 *  1. 读 GET /provider-configs 找 deepseek 行（内置 seed 保证存在）
 *  2. 该行 models 无 chat 条目 → PATCH 补 {id:'deepseek-chat', type:'chat'}
 *  3. POST /settings/llm-keys 存 E2E 桩 key（使 key_saved=true）
 *
 * 完成后 GET /settings/model-readiness 应为 ready=true。
 * 返回该判据响应（供 spec 断言/调试）。
 */
export async function ensureModelConfigured(kernel: KernelInfoLike): Promise<unknown> {
  const listing = await apiJson(kernel, 'GET', '/api/v1/provider-configs');
  const items = (listing.data as { items?: Array<{ id: number; name: string; models?: Array<{ id: string; type: string; roles?: string[] }> }> })?.items ?? [];
  const row = items.find((p) => p.name === PROVIDER_NAME);

  if (row) {
    const models = row.models ?? [];
    const hasChat = models.some((m) => m.type === 'chat');
    if (!hasChat) {
      // PATCH models 为整体替换语义（F3 契约）→ 携带既有条目 + 新 chat 条目
      await apiJson(kernel, 'PATCH', `/api/v1/provider-configs/${row.id}`, {
        models: [...models, { id: CHAT_MODEL_ID, type: 'chat', roles: [] }],
      });
    }
  } else {
    // 兜底：无内置行（seed 未跑）→ 显式创建 provider + chat 模型
    await apiJson(kernel, 'POST', '/api/v1/provider-configs', {
      name: PROVIDER_NAME,
      base_url: 'https://api.deepseek.com/v1',
      models: [{ id: CHAT_MODEL_ID, type: 'chat', roles: [] }],
    });
  }

  // key_saved 判据来源（幂等 upsert）
  await apiJson(kernel, 'POST', '/api/v1/settings/llm-keys', {
    provider: PROVIDER_NAME,
    api_key: FAKE_API_KEY,
  });

  const readiness = await apiJson(kernel, 'GET', '/api/v1/settings/model-readiness');
  return readiness.data;
}
