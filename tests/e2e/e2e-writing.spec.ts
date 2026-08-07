/**
 * 写作页域 E2E（ADR-028 E1 拆分自 electron-pages.spec.ts）
 *
 * 运行方式：
 *   cd frontend
 *   pnpm --filter renderer build          # 生成 renderer/dist/
 *   pnpm --filter inkflow-electron build  # 生成 out/main.js
 *   pnpm --filter inkflow-electron test:e2e e2e-writing
 *
 * 基建（复用 electron-pages.spec.ts 模式）：
 * - _electron.launch + waitKernelInfo（__kernelInfo 注入轮询，窗口交互前必须先等内核就绪，否则 401）
 * - 真实内核 + 真实渲染：创建项目 = 真实 POST 落库；用例间用唯一书名 `E2E-<场景>-<ts>` 隔离数据
 * - 每个用例独立 launch app（workers=1，串行）
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

/** 等待内核就绪（轮询 __kernelInfo 注入；CI 冷启动 chromadb+内核 >20s，默认 30s） */
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

/** 带 token 的内核 API 请求（JSON body 自动序列化） */
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

/** 启动应用（Electron + 真实内核），等待窗口与内核就绪 */
async function launchApp(): Promise<{ app: ElectronApplication; window: Page; kernel: KernelInfo }> {
  const app = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR });
  const window = await app.firstWindow();
  const kernel = await waitKernelInfo(app);
  return { app, window, kernel };
}

/**
 * 通过 UI 创建项目：new-project-btn → 对话框填书名 → 「创建」。
 * 契约：创建成功 → navigate('/writing')，等待写作页 project-tree 出现。
 */
async function createProjectViaUi(window: Page, name: string): Promise<void> {
  await window.getByTestId('new-project-btn').click();
  const dlg = window.getByRole('dialog');
  // getByLabel 通过关联 label / aria-label 查找（dialog 内唯一）
  await window.getByLabel('书名').fill(name);
  await dlg.getByRole('button', { name: '创建' }).click();
  await expect(window.getByTestId('project-tree')).toBeVisible({ timeout: 15_000 });
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

/** 侧边栏导航（AppNav 链接文本：项目 / 写作 / 设定库 / 设置；NavLink 与 Agent 快捷 Link 均为 role=link） */
async function gotoNav(window: Page, name: string): Promise<void> {
  await window.getByRole('link', { name }).click();
}

test.describe.configure({ timeout: 120_000 });

// ────────────────────────────────────────────────────────────────
// 3. 写作页：卷/章树渲染 + 点章节 → 编辑器显示正文
// ────────────────────────────────────────────────────────────────
test('写作页：卷/章树渲染（tree-volume/tree-chapter）→ 选章节 → 编辑器正文', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-树-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);

    // 内核 API 预置：1 卷 + 2 章（带正文）——模拟已有内容的项目
    const volRes = await kernelFetch(kernel, `/api/v1/projects/${pid}/volumes`, {
      method: 'POST',
      body: { title: '第一卷 风起' },
    });
    expect(volRes.status).toBe(201);
    const vol = (await volRes.json()) as { id: string };
    const seedChapters: Array<{ title: string; content: string }> = [
      { title: '第一章 初见', content: '第一章正文内容。' },
      { title: '第二章 夜谈', content: '第二章正文内容。' },
    ];
    for (const ch of seedChapters) {
      const r = await kernelFetch(kernel, `/api/v1/projects/${pid}/chapters`, {
        method: 'POST',
        body: { title: ch.title, volume_id: vol.id, content: ch.content },
      });
      expect(r.status).toBe(201);
    }

    // 重挂载写作页触发 loadChapterTree（加载 API 预置的卷/章）
    await gotoNav(window, '项目');
    await gotoNav(window, '写作');
    await expect(window.getByTestId('project-tree')).toBeVisible();

    // 卷节点渲染
    const tree = window.getByTestId('project-tree');
    await expect(tree.getByTestId('tree-volume')).toHaveCount(1);
    await expect(tree.getByTestId('tree-volume')).toContainText('第一卷 风起');

    // 点章节 → 成为当前章（data-testid=tree-chapter + data-current=true）
    await tree.getByRole('button', { name: /第一章 初见/ }).click();
    const current = tree.getByTestId('tree-chapter');
    await expect(current).toHaveCount(1);
    await expect(current).toHaveAttribute('data-current', 'true');
    await expect(current).toContainText('第一章 初见');

    // 编辑器显示选中章节正文（selectChapter 拉取 GET /chapters/{id}）
    await expect(window.getByTestId('chapter-editor')).toHaveValue('第一章正文内容。');
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// 4. 写作页：工具栏保存 → 正文持久化到内核
// ────────────────────────────────────────────────────────────────
test('写作页：新建章节 → 输入正文 → 工具栏保存 → 内核持久化', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-保存-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);

    // UI 新建章节（底部「+ 新建章节」→ 输入标题 → Enter；创建后自动成为当前章）
    await window.getByRole('button', { name: /新建章节/ }).click();
    // exact: 编辑器 textarea 的 placeholder 也含「新建章节」子串，必须精确匹配树底部输入框
    const titleInput = window.getByPlaceholder('新建章节', { exact: true });
    await titleInput.fill('保存测试章节');
    await titleInput.press('Enter');
    await expect(window.getByTestId('tree-chapter')).toContainText('保存测试章节');

    // 编辑器输入正文
    const editor = window.getByTestId('chapter-editor');
    const text = `E2E 保存正文 ${Date.now()}`;
    await editor.fill(text);

    // 工具栏保存
    await window.getByTestId('toolbar-save').click();

    // 轮询内核：正文已持久化（PATCH /chapters/{id} 异步完成）
    await expect
      .poll(
        async () => {
          const listRes = await kernelFetch(kernel, `/api/v1/projects/${pid}/chapters`);
          const list = (await listRes.json()) as {
            items: Array<{ id: string; title: string }>;
          };
          const ch = list.items.find((c) => c.title === '保存测试章节');
          if (!ch) return null;
          const detailRes = await kernelFetch(kernel, `/api/v1/chapters/${ch.id}`);
          return ((await detailRes.json()) as { content: string }).content;
        },
        { timeout: 10_000 }
      )
      .toBe(text);
  } finally {
    await app.close();
  }
});
