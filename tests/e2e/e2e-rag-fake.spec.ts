/**
 * RAG reindex 成功闭环 E2E（S3f-T3 R6，contract-s3f-t3 §1.5）。
 *
 * 补 #276 刻意回避的「真 reindex 成功环」（e2e-settings.spec.ts L614-618 注释自陈：
 * E2E 环境无真实 embedding 端点 → 从不点 rag-confirm-ok）。本 spec 用 fake LLM
 * server（含 POST /v1/embeddings，§1.2 GREEN 后）提供确定性 embedding：
 *   spawn fake_llm_server.py 子进程（解析 FAKE_READY <port>）→ createIsolatedEnv
 *   隔离数据目录 launch → 内核 API 注册 provider-configs e2e-rag-fake
 *   （base_url = http://127.0.0.1:<port>/v1）+ settings/llm-keys → 预置 1 条世界观
 *   节点（含正文，SETTING 属 reindex 缺省 5 类型之一）→ 设置页模型分类 rag-status-card
 *   （镜像 e2e-settings L696-828 既有 testid）stale 态 → rag-reindex-btn →
 *   rag-confirm-ok → UI 轮询 fresh（横幅/按钮消失；fresh 态无独立 testid，
 *   RagStatusCard.tsx L168-170 裸 div）→ 内核 GET /vector/status 硬断言 stale=false。
 *
 * 职责分离（§1.5）：fake 收到 embedding 请求的实证在 pytest 面（TestEmbeddings），
 * E2E 面断 UI 闭环。双守卫 skip（venv python / fake server 脚本缺失，#167 先例）。
 *
 * 依赖 G2（fake /v1/embeddings）+ G4（隔离内核）——RED 阶段可收集不可跑绿；
 * CI 不登记（父侧裁定），GREEN 后本地定向跑：
 *   cd frontend/packages/electron && playwright test e2e-rag-fake.spec.ts
 */
import path from 'node:path';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import {
  test,
  expect,
  _electron as electron,
  type ElectronApplication,
  type Page,
} from '@playwright/test';
import { createIsolatedEnv, type IsolatedEnv } from './e2e-isolation';

// 本文件位于 <repoRoot>/tests/e2e/ → 仓库根 → frontend 目录
const REPO_ROOT = path.resolve(__dirname, '..', '..');
const FRONTEND_DIR = path.join(REPO_ROOT, 'frontend');
const MAIN_JS = 'packages/electron/out/main.js';
const VENV_PYTHON = path.join(REPO_ROOT, 'backend', '.venv', 'Scripts', 'python.exe');
const FAKE_SERVER_PY = path.join(
  REPO_ROOT,
  'frontend',
  'packages',
  'renderer',
  'src',
  'api',
  '__integration__',
  'fake_llm_server.py'
);

interface KernelInfo {
  pid: number;
  port: number;
  token: string;
}

/** 读主进程测试钩子（dev 模式暴露 globalThis.__kernelInfo，spec §3.6） */
async function readKernelInfo(app: ElectronApplication): Promise<KernelInfo | undefined> {
  return app.evaluate(() => (globalThis as { __kernelInfo?: KernelInfo }).__kernelInfo);
}

/** 等待内核就绪（轮询 __kernelInfo 注入；CI 冷启动 >20s，默认 60s） */
async function waitKernelInfo(app: ElectronApplication, timeoutMs = 60_000): Promise<KernelInfo> {
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

/** 直调内核 API：非 2xx 抛错；204 → data undefined（复制 e2e-settings apiJson） */
async function apiJson(
  kernel: KernelInfo,
  method: string,
  pathname: string,
  body?: unknown
): Promise<{ status: number; data: unknown }> {
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

/** launch：隔离 env（INKFLOW_DATA_DIR）+ 独立 --user-data-dir */
async function launchIsolated(
  iso: IsolatedEnv
): Promise<{ app: ElectronApplication; window: Page; kernel: KernelInfo }> {
  const app = await electron.launch({
    args: [MAIN_JS, `--user-data-dir=${iso.userDataDir}`],
    cwd: FRONTEND_DIR,
    env: iso.env as Record<string, string>,
  });
  const window = await app.firstWindow();
  const kernel = await waitKernelInfo(app);
  return { app, window, kernel };
}

/** 侧边栏导航（AppNav 链接文本：项目 / 写作 / 设定库 / 设置） */
async function gotoNav(window: Page, name: string): Promise<void> {
  await window.getByRole('link', { name }).click();
}

/** 通过 UI 创建项目（复制 e2e-settings createProjectViaUi；书名 + ≥1 题材 #595） */
async function createProjectViaUi(window: Page, name: string): Promise<void> {
  await window.getByTestId('new-project-btn').click();
  const dlg = window.getByRole('dialog');
  await window.getByLabel('书名').fill(name);
  await window.getByTestId('tags-select').click();
  await window.getByRole('option', { name: '玄幻' }).click();
  await dlg.getByRole('button', { name: '创建' }).click();
  await expect(window.getByTestId('project-tree')).toBeVisible({ timeout: 15_000 });
}

/** 从内核项目列表按书名查 id（断言存在） */
async function findProjectId(kernel: KernelInfo, name: string): Promise<string> {
  const { data } = await apiJson(kernel, 'GET', '/api/v1/projects');
  const items = (data as { items: Array<{ id: string | number; name: string }> }).items ?? [];
  const project = items.find((p) => p.name === name);
  expect(project, `项目「${name}」应已创建并持久化`).toBeTruthy();
  return String((project as { id: string | number }).id);
}

/** spawn fake LLM server（backend venv python 直跑启动器），解析 FAKE_READY <port> */
function spawnFakeServer(): Promise<{ port: number; kill: () => void }> {
  return new Promise((resolve, reject) => {
    const child = spawn(VENV_PYTHON, [FAKE_SERVER_PY], {
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });
    let settled = false;
    let buf = '';
    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        try {
          child.kill();
        } catch {
          // 已退出
        }
        reject(new Error('fake LLM server 未在 30s 内打印 FAKE_READY'));
      }
    }, 30_000);
    child.stdout.on('data', (chunk: Buffer) => {
      buf += chunk.toString('utf8');
      const m = buf.match(/FAKE_READY (\d+)/);
      if (m && !settled) {
        settled = true;
        clearTimeout(timer);
        resolve({
          port: Number(m[1]),
          kill: () => {
            try {
              child.kill();
            } catch {
              // 已退出
            }
          },
        });
      }
    });
    child.on('error', (err) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        reject(err);
      }
    });
  });
}

test.describe.configure({ timeout: 240_000 });

test('RAG reindex 成功闭环：fake embedding → 确认 → UI fresh + 内核 stale=false', async () => {
  test.skip(
    !existsSync(VENV_PYTHON) || !existsSync(FAKE_SERVER_PY),
    '缺少 fake server 运行环境（backend/.venv python.exe 或 fake_llm_server.py）→ skip（#167 先例）'
  );
  const iso = createIsolatedEnv('rag-fake');
  let fake: { port: number; kill: () => void } | undefined;
  let app: ElectronApplication | undefined;
  try {
    // ① fake embedding server（G2 前无 /v1/embeddings → 后续 reindex 失败 = RED）
    fake = await spawnFakeServer();
    const launched = await launchIsolated(iso);
    app = launched.app;
    const { window, kernel } = launched;
    await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

    // ② 建项目（ASCII 名）+ 注册 embedding provider 指向 fake + 落盘 key
    const name = `RAG-FAKE-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);
    const created = await apiJson(kernel, 'POST', '/api/v1/provider-configs', {
      name: 'e2e-rag-fake',
      base_url: `http://127.0.0.1:${fake.port}/v1`,
      models: [{ id: 'e2e-embed-test', type: 'embedding' }],
    });
    expect(created.status).toBe(201);
    await apiJson(kernel, 'POST', '/api/v1/settings/llm-keys', {
      provider: 'e2e-rag-fake',
      api_key: 'fake-embed-key',
    });

    // ③ 预置世界观节点（含正文）→ reindex 走真实 embedding 调用链（SETTING ∈ 缺省 5 类型）
    // category='' 镜像 e2e-blackbox-contract presetWorldNodes 先例（父侧修复：
    // 非空分类须先经 world-categories 端点创建，否则 422「请先创建分类」gate）
    const world = await apiJson(kernel, 'POST', `/api/v1/projects/${pid}/world-settings`, {
      name: '云州大陆',
      category: '',
      content:
        '云州大陆地势西高东低，东临沧海，西接荒漠。宗门林立，以三山五派为尊，灵脉多藏于深山大泽之中。',
    });
    expect(world.status).toBe(201);

    // ④ 设置页模型分类 → rag-status-card stale 态（无索引指纹 reason=unknown）
    await gotoNav(window, '设置');
    await window.getByTestId('settings-cat-models').click();
    await expect(window.getByTestId('rag-status-card')).toBeVisible({ timeout: 15_000 });
    await expect(window.getByTestId('rag-model-name')).toContainText('e2e-embed-test');
    await expect(window.getByTestId('rag-stale-banner')).toBeVisible();
    await expect(window.getByTestId('rag-reindex-btn')).toBeVisible();

    // ⑤ 点 reindex → 确认对话框 → rag-confirm-ok（#276 既有用例刻意不点的成功环）
    await window.getByTestId('rag-reindex-btn').click();
    await expect(window.getByTestId('rag-confirm-dialog')).toBeVisible();
    await window.getByTestId('rag-confirm-ok').click();

    // ⑥ UI 轮询 fresh：确认框关闭 + stale 横幅消失 + reindex 按钮消失（fresh 无独立 testid）
    await expect
      .poll(
        async () => ({
          dialog: await window.getByTestId('rag-confirm-dialog').count(),
          banner: await window.getByTestId('rag-stale-banner').count(),
          reindexBtn: await window.getByTestId('rag-reindex-btn').count(),
        }),
        { timeout: 60_000 }
      )
      .toEqual({ dialog: 0, banner: 0, reindexBtn: 0 });
    await expect(window.getByTestId('rag-model-name')).toContainText('e2e-embed-test');

    // ⑦ 内核硬断言：指纹比对一致 → stale=false / reason=null（vector/status 响应契约）
    await expect
      .poll(
        async () => {
          const r = await apiJson(kernel, 'GET', `/api/v1/projects/${pid}/vector/status`);
          const s = r.data as { stale?: boolean; reason?: string | null };
          return { stale: s.stale ?? null, reason: s.reason ?? null };
        },
        { timeout: 60_000 }
      )
      .toEqual({ stale: false, reason: null });
  } finally {
    if (app) {
      await app.close();
    }
    if (fake) {
      fake.kill();
    }
    iso.cleanup();
  }
});
