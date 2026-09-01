/**
 * GUI 黑盒断言契约（ADR-048 §2）— 世界树域（tests/e2e）
 *
 * 覆盖 ADR-048 四类黑盒断言：
 *   G1 元素该有（正断言）     —— 有子节点的节点渲染 world-tree-toggle
 *   G2 元素不该有（负断言）   —— 叶子节点不渲染 world-node-childcount
 *   G3 数据→渲染           —— world-node-desc 渲染 item.content
 *   G4 层级/树正确          —— 父节点 world-node-childcount = 子数（层级）
 *
 * 补 e2e 缺口：`e2e-library[-f43].spec.ts` 覆盖了世界树 toggle/层级/筛选，
 * 但 world-node-childcount（G4）与 world-node-desc（G3）此前无 e2e 断言。
 *
 * LLM 用 fake（ADR-047 确定性）；数据经真实内核 API 预置（presetWorldNodes）。
 * 运行：pnpm --filter inkflow-electron test:e2e e2e-blackbox-contract
 */
import path from 'node:path';
import {
  test,
  expect,
  _electron as electron,
  type ElectronApplication,
  type Page,
} from '@playwright/test';

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
async function readKernelInfo(
  app: ElectronApplication
): Promise<KernelInfo | undefined> {
  return app.evaluate(() => (globalThis as { __kernelInfo?: KernelInfo }).__kernelInfo);
}

/** 等待内核就绪（轮询 __kernelInfo 注入；CI 冷启动 chromadb+内核 >20s，默认 60s） */
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

/** 启动应用（Electron + 真实内核），等待窗口与内核就绪 */
async function launchApp(): Promise<{ app: ElectronApplication; window: Page; kernel: KernelInfo }> {
  const app = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR });
  const window = await app.firstWindow();
  const kernel = await waitKernelInfo(app);
  return { app, window, kernel };
}

/** 侧边栏导航（AppNav 链接文本：项目 / 写作 / 设定库 / 设置） */
async function gotoNav(window: Page, name: string): Promise<void> {
  await window.getByRole('link', { name }).click();
}

/** 通过 UI 创建项目：new-project-btn → 对话框填书名 → 「创建」。 */
async function createProjectViaUi(window: Page, name: string): Promise<void> {
  await window.getByTestId('new-project-btn').click();
  const dlg = window.getByRole('dialog');
  await window.getByLabel('书名').fill(name);
  await window.getByTestId('tags-select').click();
  await window.getByRole('option', { name: '玄幻' }).click();
  await dlg.getByRole('button', { name: '创建' }).click();
  await expect(window.getByTestId('project-tree')).toBeVisible({ timeout: 15_000 });
}

async function kernelFetch(
  info: KernelInfo,
  pathname: string,
  init?: { method?: string; body?: unknown }
): Promise<Response> {
  return fetch(`http://127.0.0.1:${info.port}${pathname}`, {
    method: init?.method ?? 'GET',
    headers: {
      'X-InkFlow-Token': info.token,
      'Content-Type': 'application/json',
    },
    body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
  });
}

/** 从内核项目列表按书名查 id（断言存在） */
async function findProjectId(kernel: KernelInfo, name: string): Promise<string> {
  const res = await kernelFetch(kernel, '/api/v1/projects');
  expect(res.ok).toBe(true);
  const data = (await res.json()) as { items: Array<{ id: string; name: string }> };
  const project = data.items.find((p) => p.name === name);
  expect(project, `项目「${name}」应已创建并持久化`).toBeTruthy();
  return project!.id;
}

/** 打开设定库世界观 tab（返回 library-list 视图） */
async function openWorldTabPlain(window: Page): Promise<void> {
  await window.getByRole('tab', { name: '世界观' }).click();
  await expect(window.getByTestId('library-list')).toBeVisible({ timeout: 15_000 });
}

/** 预置世界观节点（parent 用名称引用，顺序保证父先建）；返回 name → id（内核 UUID） */
async function presetWorldNodes(
  kernel: KernelInfo,
  pid: string,
  nodes: Array<{ name: string; category: string; parent?: string }>
): Promise<Record<string, string>> {
  const ids: Record<string, string> = {};
  for (const n of nodes) {
    const res = await kernelFetch(kernel, `/api/v1/projects/${pid}/world-settings`, {
      method: 'POST',
      body: {
        name: n.name,
        category: n.category,
        content: 'E2E 预置',
        ...(n.parent !== undefined ? { parent_id: ids[n.parent] } : {}),
      },
    });
    expect(res.status).toBe(201);
    const created = (await res.json()) as { id: string };
    ids[n.name] = created.id;
  }
  return ids;
}

test.describe.configure({ timeout: 120_000 });

/**
 * 世界树黑盒契约（G1-G4，ADR-048 §2）：
 * - G4 层级：父节点 childcount = 子数（九州 2 子）
 * - G2 负断言：叶子节点（中州/东荒）不渲染 childcount
 * - G3 数据渲染：world-node-desc 渲染预置 content
 * - G1 正断言：有子节点的节点渲染 world-tree-toggle
 */
test('世界树黑盒契约：childcount 层级 + desc 数据渲染 + 叶子负断言（G1-G4）', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-契约-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);
    const ids = await presetWorldNodes(kernel, pid, [
      { name: '九州', category: '' },
      { name: '中州', category: '', parent: '九州' },
      { name: '东荒', category: '', parent: '九州' },
    ]);

    await gotoNav(window, '设定库');
    await expect(window.getByTestId('library-page')).toBeVisible({ timeout: 15_000 });
    await openWorldTabPlain(window);

    // G4 层级：父节点「九州」childcount = 2（两个子节点）
    await expect(window.getByTestId(`world-node-childcount-${ids['九州']}`)).toBeVisible();
    await expect(window.getByTestId(`world-node-childcount-${ids['九州']}`)).toContainText('2');

    // G2 负断言：叶子节点「中州」「东荒」不渲染 childcount（无子节点）
    await expect(window.getByTestId(`world-node-childcount-${ids['中州']}`)).toHaveCount(0);
    await expect(window.getByTestId(`world-node-childcount-${ids['东荒']}`)).toHaveCount(0);

    // G3 数据渲染：子节点 desc 渲染预置 content「E2E 预置」
    await expect(window.getByTestId(`world-node-desc-${ids['中州']}`)).toContainText('E2E 预置');

    // G1 正断言：有子节点的父节点渲染 toggle（无子节点叶子不渲染）
    await expect(window.getByTestId(`world-tree-toggle-${ids['九州']}`)).toBeVisible();
    await expect(window.getByTestId(`world-tree-toggle-${ids['东荒']}`)).toHaveCount(0);
  } finally {
    await app.close();
  }
});
