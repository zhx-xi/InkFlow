/**
 * #1440 恢复上一稿 集成测试（真实内核往返，vitest.integration.config.ts 收集）。
 *
 * 范围：`restorePreviousContent(chapterId)` 的**真实 HTTP 契约** ——
 *   ① 正常路径：PATCH 覆盖正文后（#1430 A2 自动落 previous_content），
 *      调 restore → 200 章 JSON，content ⇄ previous_content **互换**；
 *      再调一次 → 切回原值（双向可逆）。
 *   ② 读面：章节列表 `GET /projects/{pid}/chapters` 的 items 亦带 previous_content
 *      （GUI 徽标数据源，本单**零后端改动**的实证）。
 *   ③ 错误映射：无可恢复旧稿 → ApiError(409, '无可恢复的旧稿')；章不存在 → ApiError(404)。
 *
 * 数据隔离：INKFLOW_DATA_DIR 指向仓库 `.tmp/`（gitignored 工作区）；内核 afterAll kill
 * （Windows 兜底 taskkill /T /F，镜像 books-reset.integration.test.ts）。
 */

import { spawn, spawnSync, type ChildProcess } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { fetchAllChapters, restorePreviousContent } from '../chapters';
import { apiFetch, ApiError } from '../client';
import {
  MAX_LAUNCH_ATTEMPTS,
  READY_TIMEOUT_MS,
  launchWithRetry,
  probeFreePort,
} from '../../test/kernel-harness';

const TEST_TOKEN = 'w8-restore-previous-integration-token';
const READY_PREFIX = 'INKFLOW_READY ';

interface ReadyPayload {
  port: number;
  token: string;
}

/** 章 JSON（后端 model_dump(mode="json")；仅取本测试用到的字段） */
interface ChapterDto {
  id: string;
  title: string;
  content: string;
  previous_content: string | null;
}

// 本文件（src/api/__integration__/）→ 仓库根
const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..', '..', '..');

/** Python 解释器解析：env INKFLOW_TEST_PYTHON 优先 → 本 worktree backend/.venv → 主仓兜底 */
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

/** 单次尝试：spawn 真实内核（不可达 LLM base_url，避免任何真实模型依赖） */
async function spawnKernelOnce(port: number): Promise<ReadyPayload> {
  killKernel();
  const python = resolvePython();
  child = spawn(python, ['-m', 'inkflow', 'serve', '--port', String(port), '--token', TEST_TOKEN], {
    cwd: join(repoRoot, 'backend'),
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
    env: {
      ...process.env,
      PYTHONUNBUFFERED: '1',
      INKFLOW_DATA_DIR: join(repoRoot, '.tmp', `w8-restore-previous-${Date.now()}`),
      INKFLOW_LLM_BASE_URL: 'http://127.0.0.1:1/v1',
    },
  });

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
      reject(
        new Error(`等待 INKFLOW_READY 超时（${READY_TIMEOUT_MS}ms）\n--- 内核 stderr ---\n${stderrBuf}`),
      );
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
    body: { name: 'W8-恢复上一稿-集成', language: 'zh', target_words: 1000 },
  })) as { id: string };
  projectId = created.id;
}, READY_TIMEOUT_MS * MAX_LAUNCH_ATTEMPTS + 20_000);

afterAll(() => {
  killKernel();
  delete window.INKFLOW_API;
});

let seq = 0;

/** 建章（初始正文 = 第一稿） */
async function createChapter(content: string): Promise<ChapterDto> {
  seq += 1;
  return (await apiFetch(`/api/v1/projects/${projectId}/chapters`, {
    method: 'POST',
    body: { title: `第${seq}章 集成用例`, content },
  })) as ChapterDto;
}

/** PATCH 覆盖正文（触发 #1430 A2 的 previous_content 落位） */
async function overwriteContent(chapterId: string, content: string): Promise<ChapterDto> {
  return (await apiFetch(`/api/v1/chapters/${chapterId}`, {
    method: 'PATCH',
    body: { content },
  })) as ChapterDto;
}

describe('#1440 恢复上一稿 × 真实内核', () => {
  it('覆盖正文落旧稿 → restore 互换 content/previous_content → 再 restore 切回（双向可逆）', async () => {
    const created = await createChapter('第一稿正文');
    const afterOverwrite = await overwriteContent(created.id, '第二稿正文');
    expect(afterOverwrite.content).toBe('第二稿正文');
    expect(afterOverwrite.previous_content).toBe('第一稿正文');

    const restored = await restorePreviousContent(created.id);
    expect(restored.id).toBe(created.id);
    expect(restored.content).toBe('第一稿正文');
    expect(restored.previous_content).toBe('第二稿正文');

    // 再恢复 → 切回（可逆）
    const backAgain = await restorePreviousContent(created.id);
    expect(backAgain.content).toBe('第二稿正文');
    expect(backAgain.previous_content).toBe('第一稿正文');
  });

  it('章节列表 items 亦带 previous_content（GUI 徽标数据源，零后端改动实证）', async () => {
    const created = await createChapter('列表旧稿');
    await overwriteContent(created.id, '列表新稿');

    const { items } = await fetchAllChapters(projectId);
    const row = items.find((c) => c.id === created.id);
    expect(row).toBeDefined();
    expect((row as { previous_content?: string | null }).previous_content).toBe('列表旧稿');
  });

  it('无可恢复旧稿 → ApiError(409)，detail=无可恢复的旧稿', async () => {
    const created = await createChapter('仅此一稿');

    const err = (await restorePreviousContent(created.id).catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(409);
    expect(err.detail).toContain('无可恢复的旧稿');
  });

  it('章不存在 → ApiError(404)，detail=章节不存在', async () => {
    const err = (await restorePreviousContent('00000000-0000-7000-8000-000000000000').catch(
      (e: unknown) => e,
    )) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.detail).toContain('章节不存在');
  });
});
