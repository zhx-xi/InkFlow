/**
 * S3f-T3 E2E 数据隔离基建（contract-s3f-t3 §1.3 R3）。
 *
 * createIsolatedEnv(tag, extra?) → IsolatedEnv { dataDir, userDataDir, env, cleanup }：
 * - dataDir     = mkdtempSync(join(tmpdir(), `inkflow-e2e-${tag}-`))   （内核数据隔离）
 * - userDataDir = 同上、`-ud` 后缀                                      （渲染层 --user-data-dir）
 * - env         = { ...process.env, INKFLOW_DATA_DIR: dataDir } + extra 覆盖（extra 优先）
 * - cleanup     = async：rmDirWithRetry 依次删除 dataDir / userDataDir
 *
 * cleanup 重试 + 不吞错契约（#1033，CI run 34252685269 / job 102150759463 实证）：
 * Windows 上 app.close() 后内核 python 子进程可能仍持有 <dataDir>/inkflow.db 与 chroma
 * sqlite 句柄 → rmSync force:true 只吞 ENOENT，EPERM/EBUSY/ENOTEMPTY/EACCES 仍会抛进
 * finally 使全 PASS 用例误红。故 rmDirWithRetry 仅对瞬态码重试（默认 40 次 × 250ms = 10s
 * 预算），非瞬态码 / 非 Error 立即重抛，耗尽后抛最后一次错误——绝不吞错掩盖用例结论；
 * 实测（probe，#1033）：并行双实例正常释放约 10ms（3/3 轮），10s 预算为 AV 扫描 /
 * 冷启动瞬态留约 1000x 余量——罕见瞬时锁而非永久泄漏；
 * spec 清理前应先 ensureProcessExited 等内核释放句柄。同类两处历史 try/catch 吞错
 * （e2e-debug-triad / e2e-packaged）已统一委托本模块，不再吞。
 *
 * 纯 Node 模块（禁 import @playwright/test，#415 vitest 加载约束）；spec 与 vitest 双加载。
 */
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

/** rmSync 在 Windows 句柄占用时的瞬态码集合（force:true 只吞 ENOENT） */
export const TRANSIENT_RM_CODES: ReadonlySet<string> = new Set([
  'EPERM',
  'EBUSY',
  'ENOTEMPTY',
  'EACCES',
]);

export interface RmDirRetryOptions {
  retries?: number;
  delayMs?: number;
  rm?: (dir: string) => void;
  sleep?: (ms: number) => Promise<void>;
}

/** 真实 setTimeout sleep（默认实现；单测可注入替身避免空等） */
const realSleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * 删除目录并仅对瞬态错误码重试（#1033）。
 * - 总尝试次数 = retries + 1（默认 41 次，预算 40 × 250ms = 10s），两次尝试之间 sleep(delayMs)
 * - 仅当抛错 code ∈ TRANSIENT_RM_CODES 才重试；其他错误码 / 非 Error 立即重抛
 * - 尝试耗尽 → 抛最后一次错误（绝不吞错）
 */
export async function rmDirWithRetry(dir: string, options?: RmDirRetryOptions): Promise<void> {
  const retries = options?.retries ?? 40;
  const delayMs = options?.delayMs ?? 250;
  const rm = options?.rm ?? ((d: string) => rmSync(d, { recursive: true, force: true }));
  const sleep = options?.sleep ?? realSleep;
  let lastError: unknown;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      rm(dir);
      return;
    } catch (err) {
      const code = (err as { code?: unknown }).code;
      if (typeof code !== 'string' || !TRANSIENT_RM_CODES.has(code)) {
        throw err;
      }
      lastError = err;
      if (attempt < retries) {
        await sleep(delayMs);
      }
    }
  }
  throw lastError;
}

/** pid 存活探活（信号 0；EPERM = 存在但无权限 → 视为存活，其余抛错视为已退出） */
export function isProcessAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    return (err as NodeJS.ErrnoException).code === 'EPERM';
  }
}

/**
 * 轮询等进程退出（每 100ms 探活一次），never throws。
 * 默认超时 10s；返回 true = 已退出，false = 超时仍存活。
 */
export async function waitForProcessExit(
  pid: number,
  timeoutMs = 10_000,
  isAlive: (pid: number) => boolean = isProcessAlive
): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!isAlive(pid)) {
      return true;
    }
    await realSleep(100);
  }
  return !isAlive(pid);
}

/**
 * 确保进程退出，never throws（#1033：spec 清理前等内核释放 inkflow.db/chroma 句柄）。
 * 先等 timeoutMs（默认 10s）；仍存活则 best-effort kill（默认 process.kill(pid)），
 * 吞掉 kill 的一切错误——ESRCH 表示已退出、EPERM 表示无法发信号、其余同理——随后
 * 仍等 graceMs（默认 2s）再返回。kill 仅是尽力而为的加速手段，句柄仍被占用的响亮
 * 失败闸门是后续 rmDirWithRetry（耗尽后抛最后一次错误），而不是本次 kill。
 */
export async function ensureProcessExited(
  pid: number,
  options: {
    timeoutMs?: number;
    graceMs?: number;
    isAlive?: (pid: number) => boolean;
    kill?: (pid: number) => void;
    sleep?: (ms: number) => Promise<void>;
  } = {}
): Promise<void> {
  const { timeoutMs = 10_000, graceMs = 2_000, isAlive = isProcessAlive, sleep = realSleep } = options;
  const kill = options.kill ?? ((p: number) => process.kill(p));
  if (await waitForProcessExit(pid, timeoutMs, isAlive)) {
    return;
  }
  try {
    kill(pid);
  } catch (err) {
    void err;  // best-effort: swallow all kill errors (ESRCH / EPERM / others)
  }
  await sleep(graceMs);
}

export interface IsolatedEnv {
  dataDir: string;
  userDataDir: string;
  env: Record<string, string | undefined>;
  cleanup(): Promise<void>;
}

export function createIsolatedEnv(tag: string, extra?: Record<string, string>): IsolatedEnv {
  const dataDir = mkdtempSync(path.join(tmpdir(), `inkflow-e2e-${tag}-`));
  const userDataDir = mkdtempSync(path.join(tmpdir(), `inkflow-e2e-${tag}-ud-`));
  return {
    dataDir,
    userDataDir,
    env: { ...process.env, INKFLOW_DATA_DIR: dataDir, ...extra },
    cleanup: async () => {
      await rmDirWithRetry(dataDir);
      await rmDirWithRetry(userDataDir);
    },
  };
}
