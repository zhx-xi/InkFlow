/**
 * #496 统一日志页域 E2E（contract-496 §7，CI 裁判；本地 pnpm --filter inkflow-electron test:e2e e2e-logs）
 *
 * 基建（镜像 e2e-projects.spec.ts，单文件自包含，禁 import 其它 spec）：
 * - _electron.launch + waitKernelInfo（__kernelInfo 注入轮询，窗口交互前必须先等内核就绪，否则 401）
 * - 真实内核 + 真实渲染；每个用例清空持久化 UI 偏好（inkflow.ui）保证中文文案确定性
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

/**
 * 直达日志页（清空持久化 UI 偏好保证中文文案确定性）：
 * reload 后等 app-nav（门控 boot 完成）→ hash 切到 #/logs → logs-page 可见。
 */
async function gotoLogs(window: Page): Promise<void> {
  await window.evaluate(() => localStorage.clear());
  await window.reload();
  await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });
  await window.evaluate(() => {
    location.hash = '#/logs';
  });
  await expect(window.getByTestId('logs-page')).toBeVisible({ timeout: 15_000 });
}

/** 直调内核 API（镜像 e2e-projects fetchKernel：带 token + 204 短路；spec 自包含不 import） */
async function kernelFetch(kernel: KernelInfo, path: string, init?: RequestInit): Promise<any> {
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

test.describe.configure({ timeout: 120_000 });

// ────────────────────────────────────────────────────────────────
// 1. 日志页路由直达：logs-page 渲染 + 分类 tab 4 个 + 默认级别 INFO
// ────────────────────────────────────────────────────────────────
test('日志页：导航 #/logs → 页面渲染 + 四个分类 tab + 默认级别 INFO', async () => {
  const { app, window } = await launchApp();
  try {
    await gotoLogs(window);

    // 分类 tab（role=tab）四枚
    for (const name of ['全部', '内核', 'GUI', 'AI']) {
      await expect(window.getByRole('tab', { name })).toBeVisible();
    }
    // 默认级别 INFO 文案
    await expect(window.getByTestId('log-level-select')).toContainText('INFO');
    // 默认「全部」tab aria-selected
    await expect(window.getByRole('tab', { name: '全部' })).toHaveAttribute('aria-selected', 'true');
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// 2. POST 造记录 + 刷新：真实落库往返 → log-row 出现且 message 渲染中文文案
// ────────────────────────────────────────────────────────────────
test('日志页：POST 结构化记录 + 点刷新 → 新记录出现且 message 渲染（zh）', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    await gotoLogs(window);

    const corrId = `e2e-${Date.now()}`;
    await kernelFetch(kernel, '/api/v1/logs', {
      method: 'POST',
      body: JSON.stringify({
        level: 'INFO',
        caller_type: 'frontend',
        caller_name: 'e2e-logs',
        event: 'e2e_probe',
        message_key: 'log.event.page_load',
        params: { page: 'E2E' },
        correlation_id: corrId,
      }),
    });

    // 刷新 → 重查列表；按唯一 correlation_id 定位本用例记录
    await window.getByTestId('log-refresh-btn').click();
    const row = window.getByTestId('log-row').filter({ hasText: corrId });
    await expect(row.first()).toBeVisible({ timeout: 15_000 });
    await expect(row.first().getByTestId('log-message')).toContainText('页面加载：E2E');
  } finally {
    await app.close();
  }
});

// ────────────────────────────────────────────────────────────────
// 3. 点 kernel tab → GET /logs 请求携带 caller_type 多值（api,agent,tool,cli,mcp）
// ────────────────────────────────────────────────────────────────
test('日志页：点内核 tab → /logs 请求 caller_type 含 api 与 mcp', async () => {
  const { app, window } = await launchApp();
  try {
    await gotoLogs(window);

    const pending = window.waitForRequest((req) => req.url().includes('/api/v1/logs'));
    await window.getByTestId('log-tab-kernel').click();
    const req = await pending;

    const url = req.url();
    expect(url).toContain('caller_type=');
    expect(url).toContain('api');
    expect(url).toContain('mcp');
  } finally {
    await app.close();
  }
});
