/**
 * #1152 E2E：首启引导「步骤 2 模型探测 + 落库」全链路（真实内核 + 真实 GUI）。
 *
 * 背景（用户 2026-09-14 三次复验暴露的缺陷族）：
 *   - 缺陷 A：`discoverChatModels` 在 `provider.base_url === null`（实测 openai 就是）
 *     时 `null.trim()` 抛 TypeError → 循环中断 → 探测结果丢失 → 下拉退回静态候选
 *     （用户看到 `v4-flash`，非 provider 真实 /models 列表）。
 *   - 缺陷 B：步骤 2 选定模型后只 PATCH `default_model`，从不写 `models[]`
 *     → 设置页「模型表」为空，用户以为没生效、需手动再加。
 *
 * 与既有 spec 的差异（**重要**）：
 *   本 spec 测的正是**引导页本身**，故**不得**调 `ensureModelConfigured()`
 *   （那会预置模型把门控放行，抹掉被测状态）。隔离数据目录 = 全新安装态 = 引导态。
 *
 * 断言策略（全自动，不依赖真实 LLM / 真实网络）：
 *   - 探测类端点走**真实内核**，但用一个**必然失败**的 base_url（如 127.0.0.1:1），
 *     断言其"失败但可读"契约；真正的探测成功路径由单测（mock）覆盖。
 *   - 落库类（缺陷 B）走真实内核 + 真实 PATCH + 复读，**完全确定性**。
 *   - 引导页渲染走真实 Electron（GUI 实物）。
 *
 * 契约来源：issue #1152 用户复验（第三条评论）。
 */
import path from 'node:path';
import {
  test,
  expect,
  _electron as electron,
  type ElectronApplication,
} from '@playwright/test';
import { createIsolatedEnv, withAppClosedOnFailure, type IsolatedEnv } from './e2e-isolation';

// 本文件位于 <repoRoot>/tests/e2e/ → 仓库根 → frontend
const REPO_ROOT = path.resolve(__dirname, '..', '..');
const FRONTEND_DIR = path.join(REPO_ROOT, 'frontend');
const MAIN_JS = 'packages/electron/out/main.js';

interface KernelInfo {
  pid: number;
  port: number;
  token: string;
}

interface ProviderRow {
  id: number;
  name: string;
  base_url: string | null;
  default_model: string | null;
  key_saved: boolean;
  models: Array<{ id: string; type: string; roles?: string[] }>;
}

/** 读主进程测试钩子（dev 模式暴露 globalThis.__kernelInfo，#1041 序列化根治） */
async function readKernelInfo(app: ElectronApplication): Promise<KernelInfo | undefined> {
  try {
    const raw = await app.evaluate(() => {
      const info = (globalThis as { __kernelInfo?: KernelInfo }).__kernelInfo;
      return info ? JSON.stringify(info) : null;
    });
    return raw ? (JSON.parse(raw) as KernelInfo) : undefined;
  } catch {
    return undefined;
  }
}

/** 等内核就绪（默认 240s，对齐 e2e-isolation） */
async function waitKernelInfo(app: ElectronApplication, timeoutMs = 240_000): Promise<KernelInfo> {
  const deadline = Date.now() + timeoutMs;
  let info: KernelInfo | undefined;
  while (Date.now() < deadline) {
    info = await readKernelInfo(app);
    if (info) return info;
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`__kernelInfo 未在 ${timeoutMs}ms 内注入（内核未就绪）`);
}

function headers(k: KernelInfo): Record<string, string> {
  return { 'X-InkFlow-Token': k.token, 'Content-Type': 'application/json' };
}

async function api(
  k: KernelInfo,
  method: string,
  pathname: string,
  body?: unknown
): Promise<{ status: number; data: unknown }> {
  const res = await fetch(`http://127.0.0.1:${k.port}${pathname}`, {
    method,
    headers: headers(k),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data: unknown;
  try {
    data = res.status === 204 ? undefined : await res.json();
  } catch {
    data = undefined;
  }
  return { status: res.status, data };
}

async function listProviders(k: KernelInfo): Promise<ProviderRow[]> {
  const r = await api(k, 'GET', '/api/v1/provider-configs');
  return ((r.data as { items?: ProviderRow[] })?.items ?? []) as ProviderRow[];
}

/** 启动隔离 GUI（**不**预置模型 —— 保持引导态） */
async function launchFresh(
  iso: IsolatedEnv
): Promise<{ app: ElectronApplication; kernel: KernelInfo }> {
  const app = await electron.launch({
    args: [MAIN_JS, `--user-data-dir=${iso.userDataDir}`],
    cwd: FRONTEND_DIR,
    env: iso.env as Record<string, string>,
  });
  return withAppClosedOnFailure(app, async () => {
    await app.firstWindow();
    const kernel = await waitKernelInfo(app);
    return { app, kernel };
  });
}

test.describe.configure({ mode: 'serial', timeout: 420_000 });

test('#1152-E2E：全新安装态 = 引导态 + 步骤 2 探测与落库契约', async () => {
  const iso = createIsolatedEnv('setup1152');
  let app: ElectronApplication | undefined;
  let kernelPid: number | undefined;
  try {
    const launched = await launchFresh(iso);
    app = launched.app;
    kernelPid = launched.kernel.pid;
    const k = launched.kernel;

    // ── E1：全新数据目录 → readiness=false（引导态，未被 ensureModelConfigured 抹掉）──
    const rd = await api(k, 'GET', '/api/v1/settings/model-readiness');
    expect(rd.status).toBe(200);
    const own = rd.data as { ready: boolean; has_chat_model: boolean };
    expect(own.ready).toBe(false);
    expect(own.has_chat_model).toBe(false);

    // ── E4：GUI 实物 —— 引导页渲染 ──
    const win = await app.firstWindow();
    await expect(win.getByTestId('setup-guide')).toBeVisible({ timeout: 30_000 });
    // 三步指示就位
    await expect(win.getByTestId('setup-step-1')).toBeVisible();
    await expect(win.getByTestId('setup-step-2')).toBeVisible();
    await expect(win.getByTestId('setup-step-3')).toBeVisible();

    // ── E2：缺陷 A —— base_url 为空的 provider 不得让探测整体崩（真实内核契约）──
    // 前置：制造一个 base_url=null 的 provider（镜像实测 openai 行）
    const created = await api(k, 'POST', '/api/v1/provider-configs?force=true', {
      name: 'e2e-nullbase',
      models: [],
    });
    // 内置 provider 的 base_url 可能非空；这里显式 PATCH 成空以复刻 null 场景
    const createdId = (created.data as { id?: number })?.id;
    expect(created.status).toBe(201);
    expect(createdId).toBeGreaterThan(0);
    const patched = await api(k, 'PATCH', `/api/v1/provider-configs/${createdId}?force=true`, {
      base_url: '',
    });
    expect(patched.status).toBe(200);

    // 该 provider 的 base_url 现为空 → 后端探测应返回**可读失败**（200 + ok:false），
    // 而非 500/异常逃逸（前端据此跳过它、继续探测其余 provider）
    const probeEmpty = await api(k, 'POST', '/api/v1/provider-configs/models', {
      base_url: '',
      provider: 'e2e-nullbase',
    });
    // base_url 为空 → 后端 Pydantic 校验拒绝（422），这是**契约内**行为：
    // 前端必须在调用前就跳过空 base_url（单测 D9 锁定该分支），故此处只需确认
    // 后端不 500（即"空 base_url 不会导致服务端爆炸"）
    expect([200, 422]).toContain(probeEmpty.status);

    // 对照：**非空** base_url（不可达地址）→ 200 + ok:false + 可读 message（不 500）
    const probeUnreachable = await api(k, 'POST', '/api/v1/provider-configs/models', {
      base_url: 'http://127.0.0.1:1',
      provider: 'e2e-nullbase',
    });
    expect(probeUnreachable.status).toBe(200);
    const probeBody = probeUnreachable.data as { ok: boolean; message?: string };
    expect(probeBody.ok).toBe(false);
    expect(typeof probeBody.message).toBe('string');
    expect((probeBody.message ?? '').length).toBeGreaterThan(0);

    // ── E3：缺陷 B —— 选定模型后必须落进 models[]（真实 PATCH + 复读）──
    const rowsBefore = await listProviders(k);
    const target = rowsBefore.find((p) => p.name === 'deepseek');
    expect(target, '内置 deepseek provider 应存在（seed）').toBeTruthy();
    const beforeModels = target!.models ?? [];

    // 模拟前端步骤 2 成功路径（SetupGuide.handleTestConnection 的实际 PATCH 形态）：
    // 剥 provider/ 前缀 → 幂等剔除 → 追加 chat 条目 → 与 default_model 同一次 PATCH
    const selected = 'deepseek/deepseek-chat';
    const sep = selected.indexOf('/');
    const bare = (sep === -1 ? selected : selected.slice(sep + 1)).trim();
    const nextModels = beforeModels.filter((m) => m.id !== bare);
    nextModels.push({ id: bare, type: 'chat', roles: [] });

    const patchedP = await api(k, 'PATCH', `/api/v1/provider-configs/${target!.id}?force=true`, {
      default_model: selected,
      models: nextModels,
    });
    expect(patchedP.status).toBe(200);

    // 复读：models[] 必须含该 chat 条目（设置页「模型表」的数据源）
    const rowsAfter = await listProviders(k);
    const after = rowsAfter.find((p) => p.name === 'deepseek');
    expect(after, 'deepseek provider 复读应存在').toBeTruthy();
    const chatIds = (after!.models ?? []).filter((m) => m.type === 'chat').map((m) => m.id);
    expect(chatIds).toContain(bare);
    expect(after!.default_model).toBe(selected);

    // 幂等反例守护：再 PATCH 同一模型一次 → chat 条目数不增（不重复落表）
    const again = (after!.models ?? []).filter((m) => m.id !== bare);
    again.push({ id: bare, type: 'chat', roles: [] });
    await api(k, 'PATCH', `/api/v1/provider-configs/${target!.id}?force=true`, {
      default_model: selected,
      models: again,
    });
    const rows3 = await listProviders(k);
    const after3 = rows3.find((p) => p.name === 'deepseek');
    const chatIds3 = (after3!.models ?? []).filter((m) => m.type === 'chat' && m.id === bare);
    expect(chatIds3).toHaveLength(1);

    // ── E5：落库后 readiness 转 true（引导页可退出，闭环）──
    // deepseek 已有 key（本 spec 未存 key → 需先存，否则 reason=no_key）
    await api(k, 'POST', '/api/v1/settings/llm-keys', {
      provider: 'deepseek',
      api_key: 'sk-e2e-stub-1152',
    });
    const rd2 = await api(k, 'GET', '/api/v1/settings/model-readiness');
    const own2 = rd2.data as { ready: boolean; has_chat_model: boolean };
    expect(own2.has_chat_model).toBe(true);
    expect(own2.ready).toBe(true);
  } finally {
    const electronPid = app?.process()?.pid;
    if (app) {
      await app.close();
    }
    await iso.cleanup({ pids: [kernelPid, electronPid], timeoutMs: 10_000 });
  }
});
