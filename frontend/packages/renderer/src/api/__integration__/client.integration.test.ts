/**
 * API client 集成测试（spec §4.7 集成（真实内核）层）
 *
 * 契约：beforeAll 启动真实内核子进程（`inkflow serve --port 0 --token <固定值>`），
 * 行缓冲解析 stdout 的 INKFLOW_READY 交付行拿到 {port, token}，
 * 注入 window.INKFLOW_API 后，用 apiFetch 断言真实 HTTP 往返：
 * 健康检查 / 业务端点 / 401 鉴权（缺 token、错 token）/ 网络失败 / 404 错误映射。
 * afterAll kill 内核（Windows 兜底 taskkill /T /F）。
 *
 * 注意：本文件被 vitest.config.ts 的 exclude 排除，只由 vitest.integration.config.ts 收集。
 *
 * 类型说明：renderer devDependencies 已显式加 @types/node@^20（2026-08-05），
 * 消除 pnpm 严格布局下 vite/vitest peer 嵌套多版本 @types/node 的全局声明污染
 * （此前 node:child_process/readline 解析出残缺类型，曾以 @ts-nocheck 规避，已移除）。
 */

import { spawn, spawnSync, type ChildProcess } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { apiFetch, ApiError, KernelOfflineError, type ApiConfig } from '../client';

const TEST_TOKEN = 'test-integration-token-abc123';
const READY_TIMEOUT_MS = 30_000;
const READY_PREFIX = 'INKFLOW_READY ';

interface ReadyPayload {
  port: number;
  token: string;
  pid: number;
  version: string;
}

interface ProjectList {
  items: unknown[];
  total: number;
  offset: number;
  limit: number;
}

// client.integration.test.ts → 仓库根：__integration__ → api → src → renderer → packages → frontend → 根
const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..', '..', '..');

/** Python 解释器解析：env INKFLOW_TEST_PYTHON 优先 → 仓库 backend/.venv（CI uv sync 产物）→ 本地开发默认路径 */
function resolvePython(): string {
  if (process.env.INKFLOW_TEST_PYTHON) return process.env.INKFLOW_TEST_PYTHON;
  const candidates = [
    join(repoRoot, 'backend', '.venv', 'Scripts', 'python.exe'),
    'D:\\develop\\projects\\InkFlow\\backend\\.venv\\Scripts\\python.exe',
  ];
  const found = candidates.find((p) => existsSync(p));
  if (!found) {
    throw new Error(
      `找不到内核 Python 解释器：请设置 INKFLOW_TEST_PYTHON，或先 uv sync 创建 backend/.venv（候选: ${candidates.join(', ')}）`,
    );
  }
  return found;
}

let child: ChildProcess | null = null;

/** 结束内核子进程：kill + Windows 兜底 taskkill /T /F（防子进程树残留占用端口） */
function killKernel(): void {
  if (child === null) return;
  const pid = child.pid;
  try {
    child.kill();
  } catch {
    /* 已退出 */
  }
  if (process.platform === 'win32' && pid) {
    try {
      spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore' });
    } catch {
      /* taskkill 不可用则忽略 */
    }
  }
  child = null;
}

/** 启动真实内核，等待 INKFLOW_READY 交付行并解析 {port, token} */
function startKernel(): Promise<ReadyPayload> {
  const python = resolvePython();
  child = spawn(python, ['-m', 'inkflow', 'serve', '--port', '0', '--token', TEST_TOKEN], {
    cwd: join(repoRoot, 'backend'),
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
  });

  const stdout = child.stdout;
  const stderr = child.stderr;
  if (!stdout || !stderr) {
    killKernel();
    return Promise.reject(new Error('内核子进程 stdout/stderr 管道不可用'));
  }
  // drain stderr，防缓冲区满阻塞子进程
  stderr.on('data', () => {});

  const lines = createInterface({ input: stdout });
  return new Promise<ReadyPayload>((resolve, reject) => {
    const timer = setTimeout(() => {
      killKernel();
      reject(new Error(`等待 INKFLOW_READY 超时（${READY_TIMEOUT_MS}ms）`));
    }, READY_TIMEOUT_MS);

    const fail = (err: Error): void => {
      clearTimeout(timer);
      killKernel();
      reject(err);
    };

    lines.on('line', (line) => {
      if (!line.startsWith(READY_PREFIX)) return;
      clearTimeout(timer);
      try {
        resolve(JSON.parse(line.slice(READY_PREFIX.length)) as ReadyPayload);
      } catch (err) {
        fail(new Error(`INKFLOW_READY 解析失败：${line}（${String(err)}）`));
      }
    });
    child!.on('exit', (code, signal) => {
      fail(new Error(`内核提前退出 code=${code} signal=${signal ?? 'none'}`));
    });
    child!.on('error', (err) => {
      fail(new Error(`内核启动失败：${err.message}`));
    });
  });
}

/** 临时替换 window.INKFLOW_API（getApiConfig 每次实时读取），用后恢复 */
async function withApiConfig(config: ApiConfig, fn: () => Promise<unknown>): Promise<unknown> {
  const original = window.INKFLOW_API;
  window.INKFLOW_API = config;
  try {
    return await fn();
  } finally {
    window.INKFLOW_API = original;
  }
}

let baseURL = '';

beforeAll(async () => {
  const ready = await startKernel();
  baseURL = `http://127.0.0.1:${ready.port}`;
  window.INKFLOW_API = { baseURL, token: ready.token };
}, READY_TIMEOUT_MS + 15_000);

afterAll(() => {
  killKernel();
  delete window.INKFLOW_API;
});

describe('apiFetch × 真实内核（inkflow serve）', () => {
  it('GET /health 带 token → 200，body 含 status/version/mode', async () => {
    const body = await apiFetch<{ status: string; version: string; mode: string }>('/health');
    expect(body.status).toBe('ok');
    expect(typeof body.version).toBe('string');
    expect(typeof body.mode).toBe('string');
  });

  it('GET /api/v1/projects 带 token → 200 业务往返（token 中间件放行）', async () => {
    const body = await apiFetch<ProjectList>('/api/v1/projects');
    expect(Array.isArray(body.items)).toBe(true);
    expect(typeof body.total).toBe('number');
  });

  it('无 token → 401 KernelOfflineError', async () => {
    const err = (await withApiConfig({ baseURL, token: '' }, () =>
      apiFetch('/health').catch((e: unknown) => e),
    )) as ApiError;
    expect(err).toBeInstanceOf(KernelOfflineError);
    expect(err.status).toBe(401);
  });

  it('错误 token → 401 KernelOfflineError', async () => {
    const err = (await withApiConfig({ baseURL, token: 'wrong-token' }, () =>
      apiFetch('/health').catch((e: unknown) => e),
    )) as ApiError;
    expect(err).toBeInstanceOf(KernelOfflineError);
    expect(err.status).toBe(401);
  });

  it('网络失败（端口未监听）→ KernelOfflineError("Kernel unreachable")', async () => {
    const err = (await withApiConfig({ baseURL: 'http://127.0.0.1:1', token: TEST_TOKEN }, () =>
      apiFetch('/health').catch((e: unknown) => e),
    )) as ApiError;
    expect(err).toBeInstanceOf(KernelOfflineError);
    expect(err.message).toBe('Kernel unreachable');
  });

  it('不存在路径 → ApiError(404)，非 KernelOfflineError', async () => {
    const err = (await apiFetch('/api/v1/nonexistent').catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err).not.toBeInstanceOf(KernelOfflineError);
    expect(err.status).toBe(404);
    expect(err.detail).toBe('Not Found');
  });
});
