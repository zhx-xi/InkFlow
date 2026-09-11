/**
 * S3f-T3 E2E 数据隔离试点 spec（R5，contract-s3f-t3 §1.4）。
 *
 * 证明用例（iso-A / iso-B，文件级 parallel + 外部 --workers=2 = 两用例真并发）：
 * 各自 createIsolatedEnv(tag) → 独立 INKFLOW_DATA_DIR（内核数据）+ 独立
 * --user-data-dir（渲染层）→ 独立 electron.launch → 内核 API 建唯一项目
 * （ASCII 名 `ISO-<A|B>-<ts>`）→ 各自 GET /projects 只见自己的项目（total 恒 1）
 * → 数据目录物理独立（tag 前缀 mkdtemp 不同）且各含 inkflow.db → finally 先
 * ensureProcessExited 等内核退出（释放 inkflow.db/chroma 句柄，#1033）再 cleanup。
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
import { ensureModelConfigured } from './e2e-model-ready';
import { createIsolatedEnv, withAppClosedOnFailure, type IsolatedEnv } from './e2e-isolation';

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
  // #1059：firstWindow / waitKernelInfo 半途失败（内核冷启动超时等）→ 兜底 close 不留孤儿
  return withAppClosedOnFailure(app, async () => {
    await app.firstWindow();
    const kernel = await waitKernelInfo(app);
    // F60 #934：隔离数据目录 = 全新安装态 → 预置「已配置模型」则门控放行
    await ensureModelConfigured(kernel);
    return { app, kernel };
  });
}

// 两用例真并发 = 文件级 parallel（配合 --workers=2）；独立数据目录故并发安全
test.describe.configure({ mode: 'parallel', timeout: 240_000 });

for (const [tag, label] of [
  ['iso-a', 'A'],
  ['iso-b', 'B'],
] as const) {
  test(`iso-${label}：独立数据目录 + 内核只见自己的项目（${tag}）`, async () => {
    const iso = createIsolatedEnv(tag);
    let app: ElectronApplication | undefined;
    let kernelPid: number | undefined;
    try {
      // ③a 两数据目录物理不同：tag 前缀 mkdtemp 天然不等（字符串断言见本行前缀）
      expect(path.basename(iso.dataDir)).toMatch(new RegExp(`^inkflow-e2e-${tag}-`));
      expect(path.basename(iso.userDataDir)).toMatch(new RegExp(`^inkflow-e2e-${tag}-ud-`));
      expect(iso.env.INKFLOW_DATA_DIR).toBe(iso.dataDir);

      const launched = await launchIsolated(iso);
      app = launched.app;
      kernelPid = launched.kernel.pid;

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
      const electronPid = app?.process()?.pid;
      if (app) {
        await app.close();
      }
      // #1040：先取 pid 再 close；cleanup 内部先等内核 + 渲染进程退出（释放 inkflow.db/chroma
      // 句柄，Windows EPERM 根因）再带预算删目录，不吞错
      await iso.cleanup({ pids: [kernelPid, electronPid], timeoutMs: 10_000 });
    }
  });
}
