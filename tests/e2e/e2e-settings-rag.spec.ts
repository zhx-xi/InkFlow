/**
 * 设置页 RAG 向量状态区块 E2E（#276 G7，范围 5）——自 e2e-settings.spec.ts 拆出（#1064）。
 *
 * 拆分动机：e2e-settings.spec.ts 已 875 行（逼近 900 护栏），且本块的隔离需求与其余
 * 用例不同（下详）。按仓库 900 边界拆分惯例（cf. e2e-library-f43.spec.ts）独立成文件。
 *
 * 隔离策略（#1064 根因修复）：原实现只隔离渲染层（--user-data-dir），内核数据目录共享，
 * 靠 setup 阶段按 `e2e-rag` 名前缀清理测试 provider「保证注册表确定性」——该保证不成立：
 * 非 `e2e-rag*` 命名的 provider、其他 spec 在同一共享 DB 的写入、以及 chroma 持久目录
 * 状态都会残留，使本块用例的 RAG 状态断言依赖跨用例/跨 spec 的可变共享状态
 * （#1063 CI 实证：3/4 用例集中失败/抖动，且两条断言互相矛盾）。
 * 现改用 createIsolatedEnv（e2e-isolation / e2e-f59-reasoning 既有范式）：每用例独立
 * INKFLOW_DATA_DIR + 独立 --user-data-dir → 注册表仅含内核 seed（4 个内置 provider 均
 * 无 embedding 模型），前提确定；cleanup 先等内核/渲染进程退出再带预算删目录。
 *
 * 运行方式：
 *   cd frontend
 *   pnpm --filter renderer build          # 生成 renderer/dist/
 *   pnpm --filter inkflow-electron build  # 生成 out/main.js
 *   pnpm --filter inkflow-electron test:e2e e2e-settings-rag
 *
 * 父侧范围裁定（2026-08-12）：E2E 环境无真实 embedding API 端点，reindex 成功闭环
 * （fresh 持久化/日志断言）由真实模型冒烟（M3-M7 门禁）覆盖；此处只做 UI 状态流断言
 * （横幅/按钮/对话框/负例），全部无需真实 embedding 调用——不点击 reindex 确认。
 * 依赖：G1-G5 后端 vector status 端点、G6 设置页 RAG 区块 testid。
 */
import path from 'node:path';
import {
  test,
  expect,
  _electron as electron,
  type ElectronApplication,
  type Page,
} from '@playwright/test';
import { ensureModelConfigured } from './e2e-model-ready';
import { createIsolatedEnv, type IsolatedEnv } from './e2e-isolation';

// 本文件位于 <repoRoot>/tests/e2e/ → 仓库根 → frontend 目录
const REPO_ROOT = path.resolve(__dirname, '..', '..');
const FRONTEND_DIR = path.join(REPO_ROOT, 'frontend');
const MAIN_JS = 'packages/electron/out/main.js';

interface KernelInfo {
  pid: number;
  port: number;
  token: string;
}

/** 读主进程测试钩子（dev 模式暴露 globalThis.__kernelInfo，spec §3.6） */
async function readKernelInfo(app: ElectronApplication): Promise<KernelInfo | undefined> {
  // 根治（#1041）：evaluate 返回 JSON 字符串快照——序列化在主进程内同步完成，
  // 跨边界只传原始 string，消除 object round-trip 的 GC 竞态（#451/#455 签名族）；
  // 瞬态异常（GC / Target closed）等价「__kernelInfo 尚未注入」→ undefined，
  // 轮询继续——waitKernelInfo 超时耗尽仍响亮抛错（对齐 readTrayInfo 防御先例）。
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

/** 等待内核就绪（轮询 __kernelInfo 注入；CI 冷启动 chromadb+内核 >20s；#1077 对齐主进程 90s×2 重启预算，默认 180s） */
async function waitKernelInfo(app: ElectronApplication, timeoutMs = 180_000): Promise<KernelInfo> {
  const deadline = Date.now() + timeoutMs;
  let info: KernelInfo | undefined;
  while (Date.now() < deadline) {
    info = await readKernelInfo(app);
    if (info) {
      return info;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`__kernelInfo 未在 ${timeoutMs}ms 内注入（内核未就绪）`);
}

/** 隔离启动：独立内核数据目录（INKFLOW_DATA_DIR，经 iso.env）+ 独立 --user-data-dir */
async function launchIso(
  iso: IsolatedEnv
): Promise<{ app: ElectronApplication; window: Page; kernel: KernelInfo }> {
  const app = await electron.launch({
    args: [MAIN_JS, `--user-data-dir=${iso.userDataDir}`],
    cwd: FRONTEND_DIR,
    env: iso.env as Record<string, string>,
  });
  const window = await app.firstWindow();
  const kernel = await waitKernelInfo(app);
  // F60 #934：隔离数据目录 = 全新安装态 → 预置「已配置模型」则门控放行
  await ensureModelConfigured(kernel);
  return { app, window, kernel };
}

/** 侧边栏导航（AppNav 链接文本：项目 / 写作 / 设定库 / 设置） */
async function gotoNav(window: Page, name: string): Promise<void> {
  await window.getByRole('link', { name }).click();
}

/** 通过 UI 创建项目（复制自 e2e-projects.spec.ts：new-project-btn → 对话框填书名 → 创建 → 自动跳写作页） */
async function createProjectViaUi(window: Page, name: string): Promise<void> {
  await window.getByTestId('new-project-btn').click();
  const dlg = window.getByRole('dialog');
  await window.getByLabel('书名').fill(name);
  await window.getByTestId('tags-select').click();
  await window.getByRole('option', { name: '玄幻' }).click();
  await dlg.getByRole('button', { name: '创建' }).click();
  await expect(window.getByTestId('project-tree')).toBeVisible({ timeout: 15_000 });
}

/** 直调内核 API（X-InkFlow-Token 认证 + JSON body）：非 2xx 抛错；204 → data undefined。 */
async function apiJson(
  kernel: KernelInfo,
  method: string,
  path: string,
  body?: unknown,
): Promise<{ status: number; data: unknown }> {
  const res = await fetch(`http://127.0.0.1:${kernel.port}${path}`, {
    method,
    headers: {
      'X-InkFlow-Token': kernel.token,
      'Content-Type': 'application/json',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`kernel API ${method} ${path} -> ${res.status}: ${detail}`);
  }
  const data = res.status === 204 ? undefined : await res.json();
  return { status: res.status, data };
}

/** 防御性清理：删同名残留 `e2e-rag*` provider（隔离数据目录下通常为空操作，保留兜底）。 */
async function cleanupRagTestProviders(kernel: KernelInfo): Promise<void> {
  const { data } = await apiJson(kernel, 'GET', '/api/v1/provider-configs');
  const items = (data as { items: Array<{ id: number; name: string }> }).items ?? [];
  for (const p of items) {
    if (p.name.startsWith('e2e-rag')) {
      await apiJson(kernel, 'DELETE', `/api/v1/provider-configs/${p.id}`);
    }
  }
}

/**
 * 配置 embedding provider（e2e-rag + 落盘 mock key）→ 201。
 * 另需 POST /api/v1/settings/llm-keys：G1-G5 _build_store 对非本地 embedding provider
 * 强制 key 存在（APIKeyManager.load 抛错 → RAGUnavailableError → status no_embedding）。
 */
async function ensureEmbeddingProvider(
  kernel: KernelInfo,
  modelId: string,
): Promise<{ status: number }> {
  await cleanupRagTestProviders(kernel);
  let created: { status: number; data: unknown };
  try {
    // #936 C：key 在本步之后才 POST → 探测门禁必拒（embedding 维度校验需凭据）；
    // 显式 force=true 跳过
    created = await apiJson(kernel, 'POST', '/api/v1/provider-configs?force=true', {
      name: 'e2e-rag',
      base_url: 'https://api.test.example/v1',
      models: [{ id: modelId, type: 'embedding' }],
    });
  } catch (err) {
    // 同名残留（422）→ 幂等复用：PATCH 刷新 models（正常已被 cleanup 清掉，仅兜底）
    if (!(err instanceof Error) || !/422/.test(err.message)) throw err;
    const { data } = await apiJson(kernel, 'GET', '/api/v1/provider-configs');
    const existing = ((data as { items: Array<{ id: number; name: string }> }).items ?? []).find(
      (p) => p.name === 'e2e-rag',
    );
    if (!existing) throw err;
    created = await apiJson(kernel, 'PATCH', `/api/v1/provider-configs/${existing.id}?force=true`, {
      base_url: 'https://api.test.example/v1',
      models: [{ id: modelId, type: 'embedding' }],
    });
  }
  await apiJson(kernel, 'POST', '/api/v1/settings/llm-keys', {
    provider: 'e2e-rag',
    api_key: 'e2e-mock-key',
  });
  return created;
}

/** 设置页 → 模型分类：ModelsPanel 挂载 → fetchVectorStatus → RAG 状态卡片出现。 */
async function openRagStatus(window: Page): Promise<void> {
  await gotoNav(window, '设置');
  await window.getByTestId('settings-cat-models').click();
  await expect(window.getByTestId('rag-status-card')).toBeVisible({ timeout: 15_000 });
}

// ─────────────────────────────────────────────────────────────────────────────
// RAG 向量状态区块（#276）——4 个 UI 状态流用例（无真实 embedding 调用）。
// 每用例独立内核数据目录（createIsolatedEnv）→ 注册表仅含内核 seed，前提确定（#1064）。
// ─────────────────────────────────────────────────────────────────────────────
test.describe('RAG 向量状态区块（#276）', () => {
  const mkIso = (): IsolatedEnv => createIsolatedEnv('settings-rag');

  test('rag_unknown_shows_stale_banner：无指纹 → unknown 视同 stale（模型名/横幅/按钮）', async () => {
    const iso = mkIso();
    const { app, window, kernel } = await launchIso(iso);
    try {
      await window.evaluate(() => localStorage.clear());
      await window.reload();
      await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

      await createProjectViaUi(window, 'RAG 测试项目');

      // Node fetch 直调内核配置 embedding provider（201）；注册表首个 embedding 模型 = configured_fp.model_id
      const created = await ensureEmbeddingProvider(kernel, 'text-embedding-test');
      expect(created.status).toBe(201);

      await openRagStatus(window);
      await expect(window.getByTestId('rag-model-name')).toContainText('text-embedding-test');
      const banner = window.getByTestId('rag-stale-banner');
      await expect(banner).toBeVisible();
      await expect(banner).toContainText('无索引指纹');
      await expect(window.getByTestId('rag-reindex-btn')).toBeVisible();
    } finally {
      const pids = [kernel.pid, app.process()?.pid];
      await app.close();
      // #1040/#1064：cleanup 先等内核 + 渲染进程退出（释放 inkflow.db/chroma 句柄）再带预算删目录，不吞错
      await iso.cleanup({ pids });
    }
  });

  test('rag_reindex_button_opens_confirm_dialog：点重新向量化 → 确认对话框出现（不点确认）', async () => {
    const iso = mkIso();
    const { app, window, kernel } = await launchIso(iso);
    try {
      await window.evaluate(() => localStorage.clear());
      await window.reload();
      await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

      await createProjectViaUi(window, 'RAG 测试项目');
      await ensureEmbeddingProvider(kernel, 'text-embedding-test');

      await openRagStatus(window);
      await window.getByTestId('rag-reindex-btn').click();
      const dlg = window.getByTestId('rag-confirm-dialog');
      await expect(dlg).toBeVisible();
      await expect(dlg).toContainText('将用当前模型全量重建向量索引');
      await expect(window.getByTestId('rag-confirm-ok')).toBeVisible();
      // 不点击确认：真实 reindex 会调 embedding API 失败（E2E 无真实端点）——本用例只锁 UI 链路
    } finally {
      const pids = [kernel.pid, app.process()?.pid];
      await app.close();
      // #1040/#1064：cleanup 先等内核 + 渲染进程退出（释放 inkflow.db/chroma 句柄）再带预算删目录，不吞错
      await iso.cleanup({ pids });
    }
  });

  test('rag_no_embedding_shows_hint：隔离注册表无 embedding provider → 提示态', async () => {
    const iso = mkIso();
    const { app, window, kernel } = await launchIso(iso);
    try {
      await window.evaluate(() => localStorage.clear());
      await window.reload();
      await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

      await createProjectViaUi(window, 'RAG 测试项目');
      // 隔离数据目录下注册表仅含内核 seed（4 个内置 provider 均无 embedding 模型）
      // → _resolve_embedding_spec 抛 RAGUnavailableError → status reason=no_embedding。
      // （原注释所述「本地无 BGE 模型文件 → HuggingFaceBgeEmbeddings 构造失败」已过时：
      //   ADR-051 迁移后装配走 LiteLLMEmbeddings，代码中已无本地 BGE fallback。）
      await cleanupRagTestProviders(kernel);

      await openRagStatus(window);
      await expect(window.getByTestId('rag-no-embedding')).toBeVisible();
      await expect(window.getByTestId('rag-model-name')).toHaveText('—');
      await expect(window.getByTestId('rag-stale-banner')).not.toBeVisible();
      await expect(window.getByTestId('rag-reindex-btn')).not.toBeVisible();
    } finally {
      const pids = [kernel.pid, app.process()?.pid];
      await app.close();
      // #1040/#1064：cleanup 先等内核 + 渲染进程退出（释放 inkflow.db/chroma 句柄）再带预算删目录，不吞错
      await iso.cleanup({ pids });
    }
  });

  test('rag_stale_persists_across_restart：stale（unknown）跨重启保留', async () => {
    // 重启用例 = 二次 launch + 二次内核冷启动，放宽单用例超时（F32 M3 模式）
    test.setTimeout(240_000);
    const iso = mkIso();
    const name = `RAG 重启项目-${Date.now()}`;

    // ── 第一程：创建项目 → 配置 embedding provider → 设置页确认横幅（unknown 态）──
    const first = await launchIso(iso);
    const firstPids = [first.kernel.pid, first.app.process()?.pid];
    try {
      await first.window.evaluate(() => localStorage.clear());
      await first.window.reload();
      await expect(first.window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

      await createProjectViaUi(first.window, name);
      await ensureEmbeddingProvider(first.kernel, 'text-embedding-test');

      await openRagStatus(first.window);
      await expect(first.window.getByTestId('rag-stale-banner')).toBeVisible();
    } finally {
      await first.app.close();
    }

    // ── 第二程：同 dataDir/userDataDir 重启 → 设置页横幅仍出现（unknown 态持久——未 reindex 过）──
    const second = await launchIso(iso);
    try {
      // currentProjectId 为内存态（无 persist）→ 项目页卡片重新选中本项目（#232）
      await gotoNav(second.window, '项目');
      await second.window.getByTestId('project-card').filter({ hasText: name }).click();
      await expect(second.window.getByTestId('project-tree')).toBeVisible({ timeout: 15_000 });

      await openRagStatus(second.window);
      const banner = second.window.getByTestId('rag-stale-banner');
      await expect(banner).toBeVisible();
      // 后端权威（只读）：指纹缺失跨重启稳定 = stale true / reason unknown（UI 横幅同源）
      const list = await apiJson(second.kernel, 'GET', '/api/v1/projects');
      const project = ((list.data as { items: Array<{ id: string; name: string }> }).items ?? []).find(
        (p) => p.name === name,
      );
      expect(project).toBeTruthy();
      await expect
        .poll(
          async () => {
            const r = await apiJson(
              second.kernel,
              'GET',
              `/api/v1/projects/${(project as { id: string }).id}/vector/status`,
            );
            const status = r.data as { stale?: boolean; reason?: string | null };
            return { stale: status.stale, reason: status.reason };
          },
          { timeout: 10_000 },
        )
        .toEqual({ stale: true, reason: 'unknown' });
    } finally {
      const pids = [second.kernel.pid, second.app.process()?.pid, ...firstPids];
      await second.app.close();
      // #1040/#1064：cleanup 先等内核 + 渲染进程退出（释放 inkflow.db/chroma 句柄）再带预算删目录，不吞错
      await iso.cleanup({ pids });
    }
  });
});
