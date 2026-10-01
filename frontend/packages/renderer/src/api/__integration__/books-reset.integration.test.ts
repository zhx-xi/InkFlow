/**
 * #1288 book run reset 集成测试（真实内核往返，vitest.integration.config.ts 收集）。
 *
 * 范围：`resetBookRun(runId)` 的**真实 HTTP 契约**——
 *   ① 正常路径：对真实存在的 WritingPlan（status=ready）调 reset → 200 {run_id, status:'ready'}，
 *      随后 `getBookRunStatus` 读回 status=ready + progress 空（清执行态语义实证）。
 *   ② 错误映射：不存在的 run id → ApiError(404, '运行不存在')（非 KernelOfflineError）。
 *
 * 计划来源 = **真实 planner 确定性降级链**：内核以不可达 LLM base_url 启动
 * （INKFLOW_LLM_BASE_URL=http://127.0.0.1:1/v1）→ `_generate_questions` 失败 → planner 走既有
 * ROUND1→ROUND2→complete 确定性推进（planner_service.py `_respond_deterministic`），
 * 故本测试不依赖任何真实/假 LLM 语义，可确定性跑完访谈拿到 WritingPlan。
 *
 * 数据隔离：INKFLOW_DATA_DIR 指向仓库 `.tmp/`（gitignored 工作区），不污染开发库；
 * 内核由 afterAll kill（Windows 兜底 taskkill /T /F，镜像 client.integration.test.ts）。
 */

import { spawn, spawnSync, type ChildProcess } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import {
  getBookRunStatus,
  resetBookRun,
  respondPlanner,
  startPlanner,
  type PlannerRespondResponse,
} from '../books';
import { apiFetch, ApiError } from '../client';
import {
  MAX_LAUNCH_ATTEMPTS,
  READY_TIMEOUT_MS,
  launchWithRetry,
  probeFreePort,
} from '../../test/kernel-harness';

const TEST_TOKEN = 'w4-book-reset-integration-token';
const READY_PREFIX = 'INKFLOW_READY ';

interface ReadyPayload {
  port: number;
  token: string;
}

// 本文件（src/api/__integration__/）→ 仓库根
const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..', '..', '..');

/** Python 解释器解析：env INKFLOW_TEST_PYTHON 优先 → 仓库 backend/.venv → 本地开发默认路径 */
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
let baseURL = '';
let projectId = '';

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

/** 单次尝试：spawn 真实内核（不可达 LLM base_url → planner 走确定性降级） */
async function spawnKernelOnce(port: number): Promise<ReadyPayload> {
  killKernel();
  const python = resolvePython();
  child = spawn(
    python,
    ['-m', 'inkflow', 'serve', '--port', String(port), '--token', TEST_TOKEN],
    {
      cwd: join(repoRoot, 'backend'),
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
      env: {
        ...process.env,
        PYTHONUNBUFFERED: '1',
        // 隔离数据目录（仓库 .tmp/，gitignored）+ 不可达 LLM（planner 确定性降级，不依赖真实模型）
        INKFLOW_DATA_DIR: join(repoRoot, '.tmp', `w4-book-reset-${Date.now()}`),
        INKFLOW_LLM_BASE_URL: 'http://127.0.0.1:1/v1',
      },
    },
  );

  const stdout = child.stdout;
  const stderr = child.stderr;
  if (!stdout || !stderr) {
    killKernel();
    throw new Error('内核子进程 stdout/stderr 管道不可用');
  }
  let stderrBuf = '';
  stderr.on('data', (chunk: Buffer) => {
    stderrBuf += chunk.toString();
  });

  const lines = createInterface({ input: stdout });
  return new Promise<ReadyPayload>((resolve, reject) => {
    const timer = setTimeout(() => {
      killKernel();
      reject(new Error(`等待 INKFLOW_READY 超时（${READY_TIMEOUT_MS}ms）\n--- 内核 stderr ---\n${stderrBuf}`));
    }, READY_TIMEOUT_MS);

    const fail = (err: Error): void => {
      clearTimeout(timer);
      killKernel();
      reject(new Error(`${err.message}\n--- 内核 stderr ---\n${stderrBuf}`));
    };

    lines.on('line', (line) => {
      const idx = line.indexOf(READY_PREFIX);
      if (idx === -1) return;
      clearTimeout(timer);
      try {
        resolve(JSON.parse(line.slice(idx + READY_PREFIX.length)) as ReadyPayload);
      } catch (err) {
        fail(new Error(`INKFLOW_READY 解析失败：${line}（${String(err)}）`));
      }
    });
    child!.on('exit', (code, signal) => fail(new Error(`内核提前退出 code=${code} signal=${signal ?? 'none'}`)));
    child!.on('error', (err) => fail(new Error(`内核启动失败：${err.message}`)));
  });
}

beforeAll(async () => {
  const { ready } = await launchWithRetry({
    attempts: MAX_LAUNCH_ATTEMPTS,
    spawnOnce: spawnKernelOnce,
    probe: probeFreePort,
    onAttemptFailed: (a) => {
      console.warn(`内核第 ${a.attempt} 次启动失败：${a.error?.message ?? '未知错误'}`);
    },
  });
  baseURL = `http://127.0.0.1:${ready.port}`;
  window.INKFLOW_API = { baseURL, token: ready.token };
  const created = (await apiFetch('/api/v1/projects', {
    method: 'POST',
    body: { name: 'W4-Reset-集成', language: 'zh', target_words: 1000 },
  })) as { id: string };
  projectId = created.id;
}, READY_TIMEOUT_MS * MAX_LAUNCH_ATTEMPTS + 20_000);

afterAll(() => {
  killKernel();
  delete window.INKFLOW_API;
});

let planSeq = 0;

/**
 * 跑一轮真实访谈拿到 WritingPlan.id（LLM 不可达 → planner 确定性 ROUND1→ROUND2→complete）。
 * 每次 respond 用宽容映射 `{answer}`（服务端填当前轮第一个未答问题），故不锁死问题 id。
 */
async function createReadyPlan(): Promise<string> {
  planSeq += 1;
  const started = await startPlanner({
    project_id: projectId,
    one_liner: `集成测试用书面描述（第 ${planSeq} 次，仅验证重置语义）`,
  });
  const sessionId = started.session_id;
  let resp: PlannerRespondResponse = {
    session_id: sessionId,
    round: started.round,
    completed: false,
    questions: started.questions,
    writing_plan: null,
  };
  for (let i = 0; i < 15; i += 1) {
    if (resp.completed) {
      if (resp.writing_plan === null) throw new Error('planner completed 但未返回 writing_plan');
      return resp.writing_plan.id;
    }
    resp =
      resp.confirming === true
        ? await respondPlanner(sessionId, { confirm: true })
        : await respondPlanner(sessionId, { answers: { answer: `第 ${i + 1} 轮通用回答` } });
  }
  throw new Error(`planner 未在 15 轮内完成（session=${sessionId}）`);
}

describe('#1288 reset 运行 × 真实内核', () => {
  it('reset 已存在的计划 → 200 {run_id, status:"ready"}，读回 status=ready + progress 清空', async () => {
    const planId = await createReadyPlan();

    const res = await resetBookRun(planId);
    expect(res.run_id).toBe(planId);
    expect(res.status).toBe('ready');

    const status = await getBookRunStatus(planId);
    expect(status.status).toBe('ready');
    expect(status.progress).toEqual({});
  });

  it('reset 不存在的运行 → ApiError(404)，detail=运行不存在（非 KernelOfflineError）', async () => {
    const err = (await resetBookRun('00000000-0000-7000-8000-000000000000').catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.detail).toContain('运行不存在');
  });
});
