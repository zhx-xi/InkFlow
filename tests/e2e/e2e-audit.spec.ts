/**
 * F34 章节审计 GUI 最小版 E2E（Issue #208，spec §8.1 Q3=C / §9.1 E2E 层 / M11）
 *
 * 运行方式：
 *   cd frontend
 *   pnpm --filter renderer build          # 生成 renderer/dist/
 *   pnpm --filter inkflow-electron build  # 生成 out/main.js
 *   pnpm --filter inkflow-electron test:e2e e2e-audit
 *
 * 场景（确认闭环 = 功能定义，Q3=C）：
 * - 写作页打开章节 → 点工具栏「审计」按钮 → 报告弹层出现
 *   （真实内核 + 无 LLM key：LLM 检查降级 → 报告 degraded 标记，但确定性检查返回——弹层仍正常展示）
 * - 点「接受」→ 弹层关闭 → 内核 audit-logs 落库 status=accepted（单一真相源）
 * - 拒绝路径：点「拒绝」→ note 输入框出现 → 输入原因 → 点「拒绝」→ 弹层关闭 → audit-logs rejected + note
 *
 * 基建复用 e2e-writing.spec.ts 模式（launchApp/kernelFetch/createProjectViaUi 同构）。
 */
import path from 'node:path';
import {
  test,
  expect,
  _electron as electron,
  type ElectronApplication,
  type Page,
} from '@playwright/test';

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const FRONTEND_DIR = path.join(REPO_ROOT, 'frontend');
const MAIN_JS = 'packages/electron/out/main.js';

interface KernelInfo {
  pid: number;
  port: number;
  token: string;
}

async function readKernelInfo(
  app: ElectronApplication
): Promise<KernelInfo | undefined> {
  return app.evaluate(() => (globalThis as { __kernelInfo?: KernelInfo }).__kernelInfo);
}

async function waitKernelInfo(app: ElectronApplication, timeoutMs = 60_000): Promise<KernelInfo> {
  const deadline = Date.now() + timeoutMs;
  let info: KernelInfo | undefined;
  while (Date.now() < deadline) {
    info = await readKernelInfo(app);
    if (info) return info;
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`__kernelInfo 未在 ${timeoutMs}ms 内注入（内核未就绪）`);
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

async function launchApp(): Promise<{ app: ElectronApplication; window: Page; kernel: KernelInfo }> {
  const app = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR });
  const window = await app.firstWindow();
  const kernel = await waitKernelInfo(app);
  return { app, window, kernel };
}

async function createProjectViaUi(window: Page, name: string): Promise<void> {
  await window.getByTestId('new-project-btn').click();
  const dlg = window.getByRole('dialog');
  await window.getByLabel('书名').fill(name);
  await dlg.getByRole('button', { name: '创建' }).click();
  await expect(window.getByTestId('project-tree')).toBeVisible({ timeout: 15_000 });
}

async function findProjectId(kernel: KernelInfo, name: string): Promise<string> {
  const res = await kernelFetch(kernel, '/api/v1/projects');
  expect(res.ok).toBe(true);
  const data = (await res.json()) as { items: Array<{ id: string; name: string }> };
  const project = data.items.find((p) => p.name === name);
  expect(project, `项目「${name}」应已创建并持久化`).toBeTruthy();
  return project!.id;
}

test.describe.configure({ timeout: 120_000 });

/** 预置：创建项目 + 一章（带正文），返回 pid + cid */
async function seedChapter(
  window: Page,
  kernel: KernelInfo
): Promise<{ pid: string; cid: string }> {
  const name = `E2E-审计-${Date.now()}`;
  await createProjectViaUi(window, name);
  const pid = await findProjectId(kernel, name);
  const res = await kernelFetch(kernel, `/api/v1/projects/${pid}/chapters`, {
    method: 'POST',
    body: { title: '第一章 审计测试', content: '审计测试正文内容。' },
  });
  expect(res.status).toBe(201);
  const ch = (await res.json()) as { id: string };
  return { pid, cid: ch.id };
}

test('章节审计闭环：审计按钮 → 报告弹层 → 接受 → audit-logs accepted', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const { pid, cid } = await seedChapter(window, kernel);

    // 写作页选中章节（重挂载触发 loadChapterTree）
    await window.getByRole('link', { name: '项目' }).click();
    await window.getByRole('link', { name: '写作' }).click();
    await expect(window.getByTestId('project-tree')).toBeVisible();
    await window
      .getByTestId('project-tree')
      .getByRole('button', { name: /第一章 审计测试/ })
      .click();
    await expect(window.getByTestId('chapter-editor')).toHaveValue('审计测试正文内容。');

    // 点工具栏「审计」按钮 → 弹层出现（loading → 报告）
    await window.getByRole('button', { name: '审计' }).click();
    const dlg = window.getByRole('dialog');
    await expect(dlg).toBeVisible({ timeout: 15_000 });
    // 等待非 loading（报告或降级提示出现——无 LLM key 时 LLM 检查降级但确定性检查返回）
    await expect(dlg.getByTestId('audit-dialog-loading')).not.toBeVisible({ timeout: 30_000 });
    await expect(dlg).toContainText('第一章 审计测试');

    // 点「接受」→ 弹层关闭
    await dlg.getByRole('button', { name: '接受' }).click();
    await expect(dlg).not.toBeVisible({ timeout: 15_000 });

    // 内核 audit-logs 落库 accepted（确认闭环单一真相源）
    await expect
      .poll(
        async () => {
          const res = await kernelFetch(kernel, `/api/v1/projects/${pid}/audit-logs`);
          if (!res.ok) return null;
          const data = (await res.json()) as {
            logs: Array<{ chapter_id: string; status: string; confirmed_at: string | null }>;
          };
          const log = data.logs.find((l) => l.chapter_id === cid);
          return log ? { status: log.status, confirmed: log.confirmed_at !== null } : null;
        },
        { timeout: 15_000 }
      )
      .toEqual({ status: 'accepted', confirmed: true });
  } finally {
    await app.close();
  }
});

test('章节审计拒绝闭环：拒绝 → note 输入 → audit-logs rejected + note 落库', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const { pid, cid } = await seedChapter(window, kernel);

    await window.getByRole('link', { name: '项目' }).click();
    await window.getByRole('link', { name: '写作' }).click();
    await expect(window.getByTestId('project-tree')).toBeVisible();
    await window
      .getByTestId('project-tree')
      .getByRole('button', { name: /第一章 审计测试/ })
      .click();

    await window.getByRole('button', { name: '审计' }).click();
    const dlg = window.getByRole('dialog');
    await expect(dlg).toBeVisible({ timeout: 15_000 });
    await expect(dlg.getByTestId('audit-dialog-loading')).not.toBeVisible({ timeout: 30_000 });

    // 拒绝 → note 输入框 → 输入原因 → 再点拒绝
    await dlg.getByRole('button', { name: '拒绝' }).click();
    const note = dlg.getByTestId('audit-note-input');
    await note.fill('人设需再打磨');
    await dlg.getByRole('button', { name: '拒绝' }).click();
    await expect(dlg).not.toBeVisible({ timeout: 15_000 });

    // audit-logs rejected + note 落库
    await expect
      .poll(
        async () => {
          const res = await kernelFetch(kernel, `/api/v1/projects/${pid}/audit-logs`);
          if (!res.ok) return null;
          const data = (await res.json()) as {
            logs: Array<{ chapter_id: string; status: string; note: string }>;
          };
          const log = data.logs.find((l) => l.chapter_id === cid);
          return log ? { status: log.status, note: log.note } : null;
        },
        { timeout: 15_000 }
      )
      .toEqual({ status: 'rejected', note: '人设需再打磨' });
  } finally {
    await app.close();
  }
});
