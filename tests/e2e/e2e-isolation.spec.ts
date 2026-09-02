/**
 * S3f-T3 E2E 数据隔离试点 spec（R5，contract-s3f-t3 §1.4）。
 *
 * 证明用例（iso-A / iso-B，文件级 parallel + 外部 --workers=2 = 两用例真并发）：
 * 各自 createIsolatedEnv(tag) → 独立 INKFLOW_DATA_DIR（内核数据）+ 独立
 * --user-data-dir（渲染层）→ 独立 electron.launch → 内核 API 建唯一项目
 * （ASCII 名 `ISO-<A|B>-<ts>`）→ 各自 GET /projects 只见自己的项目（total 恒 1）
 * → 数据目录物理独立（tag 前缀 mkdtemp 不同）且各含 inkflow.db → finally cleanup。
 *
 * 隔离机制依赖 G4（main.ts resolveKernelStatePath dev 分支感知 INKFLOW_DATA_DIR）：
 * G4 前壳复用判定读共享 backend/data/kernel.json → 后 launch 可能复用前一内核 →
 * 互见项目（total=2，RED）；G4 后各内核 kernel.json 落各自 dataDir → 隔离成立
 * （M3 证据，父侧 GREEN 后跑：playwright test e2e-isolation.spec.ts --workers=2）。
 *
 * RED 阶段：import './e2e-isolation'（模块不存在）→ tsc TS2307 / 收集 Cannot find
 * module——GREEN 实现后本文件即可收集与运行。
 */
import path from 'node:path';
import { existsSync } from 'node:fs';
import {
  test,
  expect,
  _electron as electron,
  type ElectronApplication,
} from '@playwright/test';
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

/** 直调内核 API（X-InkFlow-Token 认证 + JSON body）——复制既有 spec 模式 */
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

/** launch：per-test env（INKFLOW_DATA_DIR 隔离内核数据）+ 独立 --user-data-dir */
async function launchIsolated(
  iso: IsolatedEnv
): Promise<{ app: ElectronApplication; kernel: KernelInfo }> {
  const app = await electron.launch({
    args: [MAIN_JS, `--user-data-dir=${iso.userDataDir}`],
    cwd: FRONTEND_DIR,
    // IsolatedEnv.env 类型带 undefined（process.env 展开）——运行时均为字符串
    env: iso.env as Record<string, string>,
  });
  await app.firstWindow();
  const kernel = await waitKernelInfo(app);
  return { app, kernel };
}

// 两用例真并发 = 文件级 parallel（配合 --workers=2）；独立数据目录故并发安全
test.describe.configure({ mode: 'parallel', timeout: 180_000 });

for (const [tag, label] of [
  ['iso-a', 'A'],
  ['iso-b', 'B'],
] as const) {
  test(`iso-${label}：独立数据目录 + 内核只见自己的项目（${tag}）`, async () => {
    const iso = createIsolatedEnv(tag);
    let app: ElectronApplication | undefined;
    try {
      // ③a 两数据目录物理不同：tag 前缀 mkdtemp 天然不等（字符串断言见本行前缀）
      expect(path.basename(iso.dataDir)).toMatch(new RegExp(`^inkflow-e2e-${tag}-`));
      expect(path.basename(iso.userDataDir)).toMatch(new RegExp(`^inkflow-e2e-${tag}-ud-`));
      expect(iso.env.INKFLOW_DATA_DIR).toBe(iso.dataDir);

      const launched = await launchIsolated(iso);
      app = launched.app;

      // ① 各建唯一项目（ASCII 名含 worker 标签 + 时间戳）
      const name = `ISO-${label}-${Date.now()}`;
      const created = await kernelFetch(launched.kernel, '/api/v1/projects', {
        method: 'POST',
        body: { name },
      });
      expect(created.status).toBe(201);

      // ② 隔离性核心断言：只见自己的项目（total 恒 1 且名字 = 己方）
      const ownList = async (): Promise<{ total: number; firstName: string | null } | null> => {
        const res = await kernelFetch(launched.kernel, '/api/v1/projects');
        if (!res.ok) {
          return null;
        }
        const data = (await res.json()) as { items: Array<{ name: string }>; total: number };
        return { total: data.total, firstName: data.items[0]?.name ?? null };
      };
      await expect.poll(ownList, { timeout: 20_000 }).toEqual({ total: 1, firstName: name });
      // 对方 worker 并发建项目窗口复查：若误复用共享内核 → total 变 2（互污染证据）
      await new Promise((r) => setTimeout(r, 2000));
      expect(await ownList()).toEqual({ total: 1, firstName: name });

      // ③b 各数据目录含 inkflow.db（内核 data_dir/inkflow.db，config.py L247）
      await expect
        .poll(() => existsSync(path.join(iso.dataDir, 'inkflow.db')), { timeout: 10_000 })
        .toBe(true);
    } finally {
      if (app) {
        await app.close();
      }
      iso.cleanup();
    }
  });
}
