// @vitest-environment node
/**
 * F1 真实 SSE 帧流黑盒（S3e，ADR-047 fake LLM）。
 *
 * 痛点：现 E2E 用 page.route 拦截 SSE 端点（interceptChatStream），从不经真实 SSE 帧协议。
 * 本测试：起真 fake LLM + 真内核（INKFLOW_LLM_BASE_URL 指向 fake），用真实 streamChat
 * POST /api/v1/chat/agent/stream，逐帧断言 delta 累积 / done 摘要 / error 帧（错误后重试）。
 *
 * 这本质是「真实内核 + 真实 LLM 替身」的集成层（vitest.integration.config.ts 收集，
 * 不含默认 unit run / coverage 口径——E2E 不计覆盖，本层同理，但提供真实帧协议实证）。
 */

import { spawn, spawnSync, type ChildProcess } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { apiFetch } from '../client';
import { streamChat, type ChatStreamBody } from '../chat';

// node env 下无 window：用 globalThis 充当（streamChat/apiFetch 读 window.INKFLOW_API）
(globalThis as unknown as { window: unknown }).window = globalThis;

const TEST_TOKEN = 'f1-integration-token';
const READY_TIMEOUT_MS = 60_000;

// 本文件（src/api/__integration__/）→ 仓库根
const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..', '..', '..');

function resolvePython(): string {
  if (process.env.INKFLOW_TEST_PYTHON) return process.env.INKFLOW_TEST_PYTHON;
  const candidates = [
    join(repoRoot, 'backend', '.venv', 'Scripts', 'python.exe'),
    'D:\\develop\\projects\\InkFlow\\backend\\.venv\\Scripts\\python.exe',
  ];
  const found = candidates.find((p) => existsSync(p));
  if (!found) throw new Error('找不到内核 Python 解释器（INKFLOW_TEST_PYTHON 或 backend/.venv）');
  return found;
}

let fakeChild: ChildProcess | null = null;
let kernelChild: ChildProcess | null = null;
let baseURL = '';
let projectId = '';

function killPs(p: ChildProcess | null): void {
  if (!p) return;
  const pid = p.pid;
  try { p.kill(); } catch { /* 已退出 */ }
  if (process.platform === 'win32' && pid) {
    try { spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore' }); } catch { /* ignore */ }
  }
}

/** 启动 fake LLM（python fake_llm_server.py），解析 FAKE_READY <port> */
async function startFakeLlm(): Promise<string> {
  const py = resolvePython();
  const helper = join(dirname(fileURLToPath(import.meta.url)), 'fake_llm_server.py');
  fakeChild = spawn(py, [helper], { stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
  const stdout = fakeChild.stdout;
  if (!stdout) throw new Error('fake LLM stdout 不可用');
  const lines = createInterface({ input: stdout });
  return new Promise<string>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('等待 FAKE_READY 超时')), READY_TIMEOUT_MS);
    lines.on('line', (line) => {
      const m = /^FAKE_READY (\d+)$/.exec(line.trim());
      if (!m) return;
      clearTimeout(timer);
      resolve(`http://127.0.0.1:${m[1]}/v1`);
    });
    fakeChild!.on('exit', (code) => reject(new Error(`fake LLM 提前退出 code=${code}`)));
  });
}

/** 启动真内核（INKFLOW_LLM_BASE_URL=fake + fake 默认模型），解析 INKFLOW_READY {port,token} */
async function startKernel(fakeBase: string): Promise<void> {
  const py = resolvePython();
  const env = {
    ...process.env,
    PYTHONUNBUFFERED: '1',
    INKFLOW_LLM_BASE_URL: fakeBase,
    INKFLOW_E2E_LLM_MODE: 'fake',
    INKFLOW_LLM_DEFAULT_MODEL: 'fake/correct',
    INKFLOW_DATA_DIR: join(repoRoot, '.tmp', `f1-${Date.now()}`),
  };
  kernelChild = spawn(py, ['-m', 'inkflow', 'serve', '--port', '0', '--token', TEST_TOKEN], {
    cwd: join(repoRoot, 'backend'),
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
    env,
  });
  const stdout = kernelChild.stdout;
  if (!stdout) throw new Error('kernel stdout 不可用');
  const lines = createInterface({ input: stdout });
  return new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('等待 INKFLOW_READY 超时')), READY_TIMEOUT_MS + 15_000);
    lines.on('line', (line) => {
      const idx = line.indexOf('INKFLOW_READY ');
      if (idx === -1) return;
      clearTimeout(timer);
      try {
        const ready = JSON.parse(line.slice(idx + 'INKFLOW_READY '.length));
        baseURL = `http://127.0.0.1:${ready.port}`;
        resolve();
      } catch (err) {
        reject(new Error(`INKFLOW_READY 解析失败：${line}（${String(err)}）`));
      }
    });
    kernelChild!.on('exit', (code) => reject(new Error(`kernel 提前退出 code=${code}`)));
  });
}

beforeAll(async () => {
  const fakeBase = await startFakeLlm();
  await startKernel(fakeBase);
  window.INKFLOW_API = { baseURL, token: TEST_TOKEN };
  // 建项目（streamChat 需要 project_id）
  const created = (await apiFetch('/api/v1/projects', { method: 'POST', body: { name: 'F1-SSE', language: 'zh', target_words: 1000 } })) as { id: string };
  projectId = created.id;
}, READY_TIMEOUT_MS + 20_000);

afterAll(() => {
  killPs(kernelChild);
  killPs(fakeChild);
  delete window.INKFLOW_API;
});

/** 跑一次真实 streamChat，收集 delta/done/error */
function runRealStream(body: ChatStreamBody): Promise<{ deltas: string[]; doneFrame: { type: string; done: boolean } | null; error: string | null }> {
  return new Promise((resolve) => {
    const deltas: string[] = [];
    let doneFrame: { type: string; done: boolean } | null = null;
    let error: string | null = null;
    void streamChat(body, {
      onDelta: (d) => deltas.push(d),
      onDone: (f) => { doneFrame = { type: f.type, done: f.done }; resolve({ deltas, doneFrame, error }); },
      onError: (m) => { error = m; resolve({ deltas, doneFrame, error }); },
    });
  });
}

describe('F1 真实 SSE 帧流黑盒（fake LLM + 真内核）', () => {
  it('delta 累积 + done 摘要帧（真实帧协议，非 page.route mock）', async () => {
    const res = await runRealStream({ project_id: projectId, prompt: '写一句话描述山间清晨' });
    // 真实 fake LLM 返回 correct fixture 的 content 前 4 字符切分
    expect(res.deltas.length).toBeGreaterThan(0);
    const combined = res.deltas.join('');
    expect(combined.length).toBeGreaterThan(0);
    // done 摘要帧（type=done, done=true）
    expect(res.doneFrame).not.toBeNull();
    expect(res.doneFrame!.type).toBe('done');
    expect(res.doneFrame!.done).toBe(true);
    // 无错误
    expect(res.error).toBeNull();
  });

  it('error 帧（[[fake-scenario:error-500]] 签名）→ onError 收到错误，不产生 done', async () => {
    const res = await runRealStream({ project_id: projectId, prompt: '[[fake-scenario:error-500]] 触发错误' });
    expect(res.error).not.toBeNull();
    expect(res.doneFrame).toBeNull();
  });

  it('错误后重试（去掉错误签名）→ 恢复正常 delta/done', async () => {
    // 先错误，再重试正确
    const errRes = await runRealStream({ project_id: projectId, prompt: '[[fake-scenario:error-500]] 错误' });
    expect(errRes.error).not.toBeNull();

    const okRes = await runRealStream({ project_id: projectId, prompt: '重试，写一句' });
    expect(okRes.error).toBeNull();
    expect(okRes.deltas.length).toBeGreaterThan(0);
    expect(okRes.doneFrame).not.toBeNull();
  });
});
