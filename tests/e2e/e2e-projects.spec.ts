/**
 * 项目页域 E2E（ADR-028 E1 拆分自 electron-pages.spec.ts）
 *
 * 运行方式：
 *   cd frontend
 *   pnpm --filter renderer build          # 生成 renderer/dist/
 *   pnpm --filter inkflow-electron build  # 生成 out/main.js
 *   pnpm --filter inkflow-electron test:e2e e2e-projects
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

/** 启动应用（Electron + 真实内核），等待窗口与内核就绪 */
async function launchApp(): Promise<{ app: ElectronApplication; window: Page; kernel: KernelInfo }> {
  const app = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR });
  const window = await app.firstWindow();
  const kernel = await waitKernelInfo(app);
  return { app, window, kernel };
}

/** 侧边栏导航（AppNav 链接文本：项目 / 写作 / 设定库 / 设置；NavLink 与 Agent 快捷 Link 均为 role=link） */
async function gotoNav(window: Page, name: string): Promise<void> {
  await window.getByRole('link', { name }).click();
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

test.describe.configure({ timeout: 120_000 });

// ────────────────────────────────────────────────────────────────
// 1. 项目页：新建对话框 → 创建项目 → 项目卡片出现（含书名）
// ────────────────────────────────────────────────────────────────
test('项目页：创建项目 → 项目卡片出现（含书名，真实落库）', async () => {
  const { app, window } = await launchApp();
  try {
    const name = `E2E-项目-${Date.now()}`;
    await createProjectViaUi(window, name);

    // 回项目页断言卡片（filter 精确匹配书名，避免历史数据干扰）
    await gotoNav(window, '项目');
    const card = window.getByTestId('project-card').filter({ hasText: name });
    await expect(card).toHaveCount(1);
    await expect(card).toContainText('玄幻'); // 默认题材
    await expect(card).toContainText(/800,?000/); // 默认目标字数
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// 2. 项目页 → 写作页导航：创建自动跳转 + 侧边栏往返闭环
// ────────────────────────────────────────────────────────────────
test('项目→写作页导航：创建后自动跳转 + 侧边栏「项目/写作」往返', async () => {
  const { app, window } = await launchApp();
  try {
    const name = `E2E-导航-${Date.now()}`;
    await createProjectViaUi(window, name);

    // 创建成功 → 自动进入写作页（契约：navigate('/writing')）
    expect(await window.evaluate(() => location.hash)).toContain('/writing');
    await expect(window.getByTestId('project-tree')).toBeVisible();

    // 侧边栏「项目」→ 回项目页
    await gotoNav(window, '项目');
    expect(await window.evaluate(() => location.hash)).toContain('/projects');
    await expect(window.getByTestId('new-project-btn')).toBeVisible();

    // 侧边栏「写作」→ 再进写作页（回退首个项目，树正常渲染）
    await gotoNav(window, '写作');
    expect(await window.evaluate(() => location.hash)).toContain('/writing');
    await expect(window.getByTestId('project-tree')).toBeVisible();
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// 3. #232 项目卡片点击 → 写作页（项目上下文切换）
// ────────────────────────────────────────────────────────────────
test('#232 项目卡片点击：多项目点击卡片 → 写作页项目上下文切换（writing-badge 跟随）', async () => {
  const { app, window } = await launchApp();
  try {
    const nameA = `E2E-卡A-${Date.now()}`;
    const nameB = `E2E-卡B-${Date.now()}`;
    // 创建两个项目（末次创建 B → 当前项目 = B）
    await createProjectViaUi(window, nameA);
    await gotoNav(window, '项目');
    await createProjectViaUi(window, nameB);
    await gotoNav(window, '项目');

    // 点击 A 卡片 → 跳转写作页（项目上下文切换为 A）
    const cardA = window.getByTestId('project-card').filter({ hasText: nameA });
    await cardA.click();
    expect(await window.evaluate(() => location.hash)).toContain('/writing');
    await expect(window.getByTestId('project-tree')).toBeVisible({ timeout: 15_000 });

    // 回项目页断言 A 为当前项目（writing-badge 跟随），B 无 badge
    await gotoNav(window, '项目');
    const badgeA = window.getByTestId('project-card').filter({ hasText: nameA }).getByTestId('writing-badge');
    await expect(badgeA).toBeVisible();
    const badgeB = window.getByTestId('project-card').filter({ hasText: nameB }).getByTestId('writing-badge');
    await expect(badgeB).toHaveCount(0);
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// 4. #143 项目页深度：模板创建（模板下拉 → 选模板 → 创建成功 → 列表刷新 + 落库）
// ────────────────────────────────────────────────────────────────
test('项目页：模板下拉选 Agent 模板创建 → 卡片出现 + config.template_id 落库', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    // 前置：经内核 API 构造模板（CI 全新库无 seed 模板；AgentTemplateCreate 仅 name 必填）
    const tplName = `E2E-TPL-${Date.now()}`;
    const tpl = await fetchKernel(kernel, '/api/v1/agent-templates', {
      method: 'POST',
      body: JSON.stringify({ name: tplName }),
    });
    const tplId = String(tpl.id);

    const name = `E2E-模板-${Date.now()}`;
    await window.getByTestId('new-project-btn').click();
    const dlg = window.getByRole('dialog');
    // 模板下拉（Radix Select：trigger aria-label='Agent 模板'，选项 portal 展开）
    await dlg.getByLabel('Agent 模板').click();
    await window.getByRole('option', { name: tplName }).click();
    await window.getByLabel('书名').fill(name);
    await dlg.getByRole('button', { name: '创建', exact: true }).click();
    await expect(window.getByTestId('project-tree')).toBeVisible({ timeout: 15_000 });

    // 回项目页断言卡片（列表刷新：新项目出现）
    await gotoNav(window, '项目');
    const card = window.getByTestId('project-card').filter({ hasText: name });
    await expect(card).toHaveCount(1);
    await expect(card).toContainText('玄幻');

    // 落库断言：config.template_id === String(tplId)（后端存 str；#107 契约）
    await expect
      .poll(
        async () => {
          const { items } = await fetchKernel(kernel, '/api/v1/projects');
          const proj = items.find((p: { name: string }) => p.name === name);
          if (!proj) return undefined;
          const detail = await fetchKernel(kernel, `/api/v1/projects/${proj.id}`);
          return detail.config?.template_id;
        },
        { timeout: 10_000 }
      )
      .toBe(tplId);
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// 5. #143 项目页深度：多项目网格渲染（2 卡片并存 + 末位新建卡片入口）
// ────────────────────────────────────────────────────────────────
test('项目页：多项目渲染（2 卡片并存 + new-project-card 末位入口）', async () => {
  const { app, window } = await launchApp();
  try {
    const nameA = `E2E-多A-${Date.now()}`;
    const nameB = `E2E-多B-${Date.now()}`;
    await createProjectViaUi(window, nameA);
    await gotoNav(window, '项目');
    await createProjectViaUi(window, nameB);
    await gotoNav(window, '项目');

    const cardA = window.getByTestId('project-card').filter({ hasText: nameA });
    const cardB = window.getByTestId('project-card').filter({ hasText: nameB });
    await expect(cardA).toHaveCount(1);
    await expect(cardB).toHaveCount(1);
    await expect(cardA).toContainText('玄幻');
    await expect(cardB).toContainText('玄幻');

    // 有项目时网格末位虚线新建卡片入口（空态不渲染）
    await expect(window.getByTestId('new-project-card')).toBeVisible();
    // 当前项目 = 最后创建 B（writing-badge 唯一跟随）
    await expect(
      window.getByTestId('project-card').filter({ hasText: nameB }).getByTestId('writing-badge')
    ).toBeVisible();
    await expect(
      window.getByTestId('project-card').filter({ hasText: nameA }).getByTestId('writing-badge')
    ).toHaveCount(0);
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// 6. #143 项目页深度：删除同步 + 空态（UI 无删除按钮 → 内核 API 删除 →
//    导航往返列表刷新消失 → 删光 → projects-empty + 空态 CTA 打开对话框）
// ────────────────────────────────────────────────────────────────
test('项目页：删除项目列表同步消失 + 空态（projects-empty + CTA 打开对话框）', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-删除-${Date.now()}`;
    await createProjectViaUi(window, name);
    await gotoNav(window, '项目');
    await expect(window.getByTestId('project-card').filter({ hasText: name })).toHaveCount(1);

    // 经内核 API 删除（204；UI 无删除入口，范围留痕 PR body）
    const { items } = await fetchKernel(kernel, '/api/v1/projects');
    const proj = items.find((p: { name: string }) => p.name === name);
    expect(proj, '内核应存在该项目').toBeTruthy();
    await fetchKernel(kernel, `/api/v1/projects/${proj.id}`, { method: 'DELETE' });

    // 导航往返触发 loadProjects 重拉 → 卡片消失
    await gotoNav(window, '写作');
    await gotoNav(window, '项目');
    await expect(window.getByTestId('project-card').filter({ hasText: name })).toHaveCount(0);

    // 删光全部项目 → 空态（模拟 CI 全新库语义；删除后列表同步刷新）
    const all = await fetchKernel(kernel, '/api/v1/projects');
    for (const p of all.items) {
      await fetchKernel(kernel, `/api/v1/projects/${p.id}`, { method: 'DELETE' });
    }
    await gotoNav(window, '写作');
    await gotoNav(window, '项目');
    await expect(window.getByTestId('projects-empty')).toBeVisible();

    // 空态 CTA（scope 到空态容器，避免与顶栏 new-project-btn 同文案 strict violation）
    await window.getByTestId('projects-empty').getByRole('button', { name: '新建项目' }).click();
    await expect(window.getByRole('dialog')).toBeVisible();
    await window.getByRole('dialog').getByRole('button', { name: '取消', exact: true }).click();
    await expect(window.getByRole('dialog')).toHaveCount(0);
    await expect(window.getByTestId('projects-empty')).toBeVisible();
  } finally {
    await app.close();
  }
});

/** 直调内核 API（E3 契约 helper 复制：带 token + 204 短路；spec 自包含不 import） */
async function fetchKernel(kernel: KernelInfo, path: string, init?: RequestInit): Promise<any> {
  const res = await fetch(`http://127.0.0.1:${kernel.port}${path}`, {
    ...init,
    headers: {
      'X-InkFlow-Token': kernel.token,
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });
  if (res.status === 204) return undefined; // 204 无 body，防 res.json() 抛错
  return res.json();
}
