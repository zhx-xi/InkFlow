/**
 * F4 可观测性 debug 三层联动 E2E 黑盒契约（S3f-T1，contract-s3f-t1 §2.7）
 *
 * 覆盖 GUI 壳 × 内核两层 INKFLOW_DEBUG 联动：
 *   A 三层联动开：env INKFLOW_DEBUG=1 → 内核 debug token（'inkflow-debug-token'）
 *     + /docs 200 + 壳 DevTools 自动开（isDevToolsOpened true）
 *   B 默认关：无 INKFLOW_DEBUG env → 随机 token + /docs 404（【R 核心 RED：当前恒 200】）
 *     + DevTools 不开
 *   C env=0 > instance.env=1：APPDATA 预置 instance.env INKFLOW_DEBUG=1 + env 显式 0
 *     → 内核 debug=False（随机 token）+ /docs 404（【R 经 G1】）
 *
 * RED 预期：B/C 的 /docs 404 断言现 FAIL（api 层 /docs 恒注册 200，G1 未实现）；
 * A 现 PASS = 联动回归守护（G1 修复后 docs 200 语义转为「debug 放行」仍需保持）。
 * DevTools 自动开 = did-finish-load + isDebugMode() → openDevTools（main.ts §F51 D2）。
 *
 * 基建自包含（#140 spec 自包含原则：readKernelInfo/waitKernelInfo 复制，
 * 不 import 其他 spec）。launch 全部传 env（含 INKFLOW_DATA_DIR=<mkdtemp> 隔离，
 * 真实用户数据零污染 + 防 config.json 锚点漂移；finally 清理统一委托
 * e2e-isolation.rmDirWithRetry（#1033：瞬态 EPERM 重试，不吞错）。
 * instance.env 文件写入在 spec 内用 node:fs（跑在 Node 端，纯 ASCII 内容）。
 *
 * 运行（GREEN 后）：INKFLOW_KERNEL_CMD=<backend venv> python -m inkflow serve --port 0
 *   cd frontend/packages/electron && playwright test e2e-debug-triad.spec.ts
 * CI：ci.yml e2e-frontend-shell job run 命令追加 e2e-debug-triad（contract §4，GREEN/父侧登记）
 */
import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';
import {
  test,
  expect,
  _electron as electron,
  type ElectronApplication,
} from '@playwright/test';
import { ensureProcessExited, rmDirWithRetry } from './e2e-isolation';

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

/** 等待内核就绪（轮询 __kernelInfo 注入；CI 冷启动 chromadb+内核 >20s；#1077 对齐主进程 90s×2 重启预算，默认 240s） */
async function waitKernelInfo(app: ElectronApplication, timeoutMs = 240_000): Promise<KernelInfo> {
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

/** mkdtemp 隔离目录（每次 launch 独立；cleanup 委托 rmDirWithRetry 重试瞬态句柄占用） */
function makeIsolation(prefix = 'inkflow-e2e-debug-'): { dir: string; cleanup: () => Promise<void> } {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  return {
    dir,
    // #1033：不再吞错——瞬态码交给 rmDirWithRetry 重试，其余错误照抛
    cleanup: () => rmDirWithRetry(dir),
  };
}

/**
 * 基础 env：继承本进程 env（含 INKFLOW_KERNEL_CMD），剥除会干扰 debug 判定的显式键
 * ——INKFLOW_DEBUG（用例各自注入目标值）/ INKFLOW_DEBUG_TOKEN（serve debug token 可覆盖
 * 环境键，剥除后回落契约常量 'inkflow-debug-token'，断言确定性）。
 * 统一注入 INKFLOW_DEBUG_NO_BROWSER=1（F51 v1.1 #949 逃生门）：debug 态 serve 不再自动弹
 * 系统浏览器打开 /docs（弹窗零断言贡献，纯本地噪音）；/docs 可达性由 docsStatus fetch
 * 断言（HTTP 门控与浏览器无关），三层联动语义不受影响。
 */
function baseEnv(): Record<string, string> {
  const env: Record<string, string> = {};
  for (const [k, v] of Object.entries(process.env)) {
    if (v !== undefined && k !== 'INKFLOW_DEBUG' && k !== 'INKFLOW_DEBUG_TOKEN' && k !== 'INKFLOW_DEBUG_NO_BROWSER') {
      env[k] = v;
    }
  }
  env.INKFLOW_DEBUG_NO_BROWSER = '1';
  return env;
}

/** 主窗口 DevTools 是否打开（openDevTools 自动开真值；无窗口视为 false） */
async function isDevToolsOpened(app: ElectronApplication): Promise<boolean> {
  return app.evaluate(({ BrowserWindow }) => {
    const win = BrowserWindow.getAllWindows()[0];
    return win ? win.webContents.isDevToolsOpened() : false;
  });
}

/** GET /docs 状态（无 token：非 debug 404 先于 token 401，docs_gate 外层） */
async function docsStatus(port: number): Promise<number> {
  return (await fetch(`http://127.0.0.1:${port}/docs`)).status;
}

/** GET /health 带 token（READY 契约：200 = 内核健康） */
async function healthStatus(port: number, token: string): Promise<number> {
  const res = await fetch(`http://127.0.0.1:${port}/health`, {
    headers: { 'X-InkFlow-Token': token },
  });
  return res.status;
}

// Electron 启动 + 内核冷启动较慢（每用例独立 launch + 独立数据目录），放宽整文件超时
test.describe.configure({ timeout: 360_000 });

test('A 三层联动开：INKFLOW_DEBUG=1 → debug token + /docs 200 + DevTools 自动开（§2.7 用例 1）', async () => {
  const iso = makeIsolation();
  let kernelPid: number | undefined;
  try {
    const env = { ...baseEnv(), INKFLOW_DEBUG: '1', INKFLOW_DATA_DIR: iso.dir };
    const app = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR, env });
    try {
      await app.firstWindow();
      const kernel = await waitKernelInfo(app);
      kernelPid = kernel.pid;
      // 【G 现 PASS】serve debug → 可预测 token（GUI→内核 env 继承实证）
      expect(kernel.token).toBe('inkflow-debug-token');
      // 【G】G1 修复后 docs 门控按 config.debug 放行 → 仍 200（现恒 200，守护 debug 路径不破）
      expect(await docsStatus(kernel.port)).toBe(200);
      // READY 契约不破：/health 带 token 200
      expect(await healthStatus(kernel.port, kernel.token)).toBe(200);
      // DevTools 自动开（did-finish-load + isDebugMode → openDevTools；轮询等待窗口加载）
      await expect.poll(() => isDevToolsOpened(app), { timeout: 30_000 }).toBe(true);
    } finally {
      await app.close();
    }
  } finally {
    // 等内核进程释放 inkflow.db/chroma 句柄后再删除隔离目录（Windows EPERM 根因，#1033）
    if (kernelPid !== undefined) {
      await ensureProcessExited(kernelPid, { timeoutMs: 10_000 });
    }
    await iso.cleanup();
  }
});

test('B 默认关：无 INKFLOW_DEBUG → 随机 token + /docs 404（G1 RED）+ DevTools 不开（§2.7 用例 2）', async () => {
  const iso = makeIsolation();
  let kernelPid: number | undefined;
  try {
    const env = { ...baseEnv(), INKFLOW_DATA_DIR: iso.dir };
    const app = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR, env });
    try {
      await app.firstWindow();
      const kernel = await waitKernelInfo(app);
      kernelPid = kernel.pid;
      // 【G 现 PASS】非 debug → 随机 token（≠ debug 常量）
      expect(kernel.token).not.toBe('inkflow-debug-token');
      // 【R 核心 RED：当前恒 200】非 debug 默认 /docs 必须 404（G1 docs 门控）
      expect(await docsStatus(kernel.port)).toBe(404);
      // READY 契约不破
      expect(await healthStatus(kernel.port, kernel.token)).toBe(200);
      // DevTools 不开：DevTools 自动开发生在 did-finish-load 后 ~1.5s+，至此 /docs 404 已证明
      // 过了 debug 分支（debug 时内核 /docs 必 200）→ 单次 evaluate 断言 false 即够
      expect(await isDevToolsOpened(app)).toBe(false);
    } finally {
      await app.close();
    }
  } finally {
    // 等内核进程释放 inkflow.db/chroma 句柄后再删除隔离目录（Windows EPERM 根因，#1033）
    if (kernelPid !== undefined) {
      await ensureProcessExited(kernelPid, { timeoutMs: 10_000 });
    }
    await iso.cleanup();
  }
});

test('C env=0 > instance.env=1：APPDATA 预置 instance.env=1 + env 显式 0 → 随机 token + /docs 404（§2.7 用例 3）', async () => {
  // appdata 隔离：instance.env 锚点（%APPDATA%/InkFlow/instance.env）搬到临时目录；
  // data 隔离：内核 data_dir 走 launch env INKFLOW_DATA_DIR（instance.env 未写该键）
  const appdataIso = makeIsolation('inkflow-e2e-debug-appdata-');
  const dataIso = makeIsolation('inkflow-e2e-debug-data-');
  let kernelPid: number | undefined;
  try {
    fs.mkdirSync(path.join(appdataIso.dir, 'InkFlow'), { recursive: true });
    fs.writeFileSync(
      path.join(appdataIso.dir, 'InkFlow', 'instance.env'),
      'INKFLOW_DEBUG=1\n',
      'utf8'
    );
    const env = {
      ...baseEnv(),
      INKFLOW_DEBUG: '0',
      INKFLOW_DATA_DIR: dataIso.dir,
      APPDATA: appdataIso.dir,
    };
    const app = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR, env });
    try {
      await app.firstWindow();
      const kernel = await waitKernelInfo(app);
      kernelPid = kernel.pid;
      // 【G 现 PASS】env 显式 0 不被 instance.env=1 覆盖（D8）→ 非 debug 随机 token
      expect(kernel.token).not.toBe('inkflow-debug-token');
      // 【R 经 G1】内核层 debug=False → /docs 404（当前恒 200 → FAIL）
      expect(await docsStatus(kernel.port)).toBe(404);
    } finally {
      await app.close();
    }
  } finally {
    // 等内核进程释放 inkflow.db/chroma 句柄后再删除隔离目录（Windows EPERM 根因，#1033）
    if (kernelPid !== undefined) {
      await ensureProcessExited(kernelPid, { timeoutMs: 10_000 });
    }
    await appdataIso.cleanup();
    await dataIso.cleanup();
  }
});
