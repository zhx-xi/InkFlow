/**
 * S3f-T3 E2E 数据隔离基建（contract-s3f-t3 §1.3 R3）。
 *
 * createIsolatedEnv(tag, extra?) → IsolatedEnv { dataDir, userDataDir, env, cleanup }：
 * - dataDir     = mkdtempSync(join(tmpdir(), `inkflow-e2e-${tag}-`))   （内核数据隔离）
 * - userDataDir = 同上、`-ud` 后缀                                      （渲染层 --user-data-dir）
 * - env         = { ...process.env, INKFLOW_DATA_DIR: dataDir } + extra 覆盖（extra 优先）
 * - cleanup(options?) = cleanupIsolatedEnv({ dataDir, userDataDir }, options)（#1040）：
 *   ① 严格按序等 options.pids 中每个非 undefined pid 退出（ensureProcessExited 默认
 *      timeoutMs=10s / graceMs=2s；已退出的 pid 单次探活即返回，零等待）
 *   ② 按序删除 dataDir（默认 DEFAULT_RM_BUDGET = 40 次 × 250ms = 10s）
 *   ③ 按序删除 userDataDir（默认 USER_DATA_RM_BUDGET = 80 次 × 500ms = 40s 放宽预算）
 *   无参 cleanup() 向后兼容：不等任何 pid；dataDir 用默认预算、userDataDir 用放宽预算。
 *
 * cleanup 重试 + 不吞错契约（#1033，CI run 34252685269 / job 102150759463 实证）：
 * Windows 上 app.close() 后内核 python 子进程可能仍持有 <dataDir>/inkflow.db 与 chroma
 * sqlite 句柄 → rmSync force:true 只吞 ENOENT，EPERM/EBUSY/ENOTEMPTY/EACCES 仍会抛进
 * finally 使全 PASS 用例误红。故 rmDirWithRetry 仅对瞬态码重试（默认 40 次 × 250ms = 10s
 * 预算；userDataDir 放宽 80 次 × 500ms），非瞬态码 / 非 Error 立即重抛，耗尽后抛最后一次
 * 错误——绝不吞错掩盖用例结论；#1040 追加：任何最终抛出的错误对象（重试耗尽 / 非瞬态
 * 立即重抛）先附残留诊断（默认 listResiduals = readdirSync(dir, { recursive: true }) 取前
 * residualLimit=5 项 → error.dir / .residuals；Error 另在 message 追加「残留前 N 项: …」），
 * 仍是原错误对象，诊断永不改变主流程结论。
 * 实测（probe，#1033）：并行双实例正常释放约 10ms（3/3 轮），10s 预算为 AV 扫描 /
 * 冷启动瞬态留约 1000x 余量——罕见瞬时锁而非永久泄漏；#1040 spec 清理统一走
 * cleanupIsolatedEnv：先 ensureProcessExited 等句柄持有者（内核 + 渲染层）退出再删目录。
 * 同类两处历史 try/catch 吞错
 * （e2e-debug-triad / e2e-packaged）已统一委托本模块，不再吞。
 *
 * 纯 Node 模块（禁 import @playwright/test，#415 vitest 加载约束）；spec 与 vitest 双加载。
 */
import { mkdtempSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

/** rmSync 在 Windows 句柄占用时的瞬态码集合（force:true 只吞 ENOENT） */
export const TRANSIENT_RM_CODES: ReadonlySet<string> = new Set([
  'EPERM',
  'EBUSY',
  'ENOTEMPTY',
  'EACCES',
]);

/** 目录删除预算（总尝试次数 = retries + 1；预算耗时 ≈ retries × delayMs） */
export interface RmDirBudget {
  retries?: number;
  delayMs?: number;
}

/** dataDir 默认删除预算：40 次 × 250ms = 10s（内核数据句柄占用窗口短） */
export const DEFAULT_RM_BUDGET = { retries: 40, delayMs: 250 };

/** userDataDir 放宽删除预算：80 次 × 500ms = 40s（Chromium 缓存句柄释放慢） */
export const USER_DATA_RM_BUDGET = { retries: 80, delayMs: 500 };

export interface RmDirRetryOptions extends RmDirBudget {
  rm?: (dir: string) => void;
  sleep?: (ms: number) => Promise<void>;
  /** 重试耗尽时的残留诊断器（返回目录内前 limit 项；诊断永不改变主流程结论） */
  listResiduals?: (dir: string, limit: number) => string[];
  /** 残留诊断条数上限（默认 5） */
  residualLimit?: number;
}

/** 真实 setTimeout sleep（默认实现；单测可注入替身避免空等） */
const realSleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

/** 默认残留诊断：readdirSync recursive 取前 limit 项；任何异常返回 []（诊断永不抛） */
const defaultListResiduals = (dir: string, limit: number): string[] => {
  try {
    return readdirSync(dir, { encoding: 'utf8', recursive: true }).slice(0, limit);
  } catch {
    return [];
  }
};

/** 给将抛出的错误对象附加残留诊断（#1040：仍是原错误对象；诊断永不改变主流程结论） */
const attachResidualDiagnostics = (
  error: unknown,
  dir: string,
  listResiduals: (d: string, limit: number) => string[],
  residualLimit: number
): void => {
  if (typeof error !== 'object' || error === null) {
    return;
  }
  try {
    const residuals = listResiduals(dir, residualLimit);
    if (!Array.isArray(residuals)) {
      return;
    }
    (error as { dir?: string }).dir = dir;
    (error as { residuals?: string[] }).residuals = residuals;
    if (error instanceof Error && !error.message.includes('残留前 ')) {
      error.message += `（残留前 ${residuals.length} 项: ${residuals.join(' | ')}）`;
    }
  } catch {
    // lister/附加诊断自身故障属旁路：不附加半截诊断，原错误对象原样继续抛出
    return;
  }
};

/**
 * 删除目录并仅对瞬态错误码重试（#1033）。
 * - 总尝试次数 = retries + 1（默认 41 次，预算 40 × 250ms = 10s），两次尝试之间 sleep(delayMs)
 * - 仅当抛错 code ∈ TRANSIENT_RM_CODES 才重试；其他错误码 / 非 Error 立即重抛
 * - 最终抛出的错误对象（耗尽或非瞬态立即重抛）先附残留诊断，再抛原对象（#1040 绝不吞错）
 */
export async function rmDirWithRetry(dir: string, options?: RmDirRetryOptions): Promise<void> {
  const retries = options?.retries ?? 40;
  const delayMs = options?.delayMs ?? 250;
  const rm = options?.rm ?? ((d: string) => rmSync(d, { recursive: true, force: true }));
  const sleep = options?.sleep ?? realSleep;
  const listResiduals = options?.listResiduals ?? defaultListResiduals;
  const residualLimit = options?.residualLimit ?? 5;
  let lastError: unknown;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      rm(dir);
      return;
    } catch (err) {
      const code = (err as { code?: unknown }).code;
      if (typeof code !== 'string' || !TRANSIENT_RM_CODES.has(code)) {
        attachResidualDiagnostics(err, dir, listResiduals, residualLimit);
        throw err;
      }
      lastError = err;
      if (attempt < retries) {
        await sleep(delayMs);
      }
    }
  }
  // #1040：重试耗尽抛前附残留诊断——仍抛同一个 lastError 对象（契约 rejects.toBe(err) 断言同一性）
  attachResidualDiagnostics(lastError, dir, listResiduals, residualLimit);
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
  isAlive: (pid: number) => boolean = isProcessAlive,
  sleep: (ms: number) => Promise<void> = realSleep
): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!isAlive(pid)) {
      return true;
    }
    await sleep(100);
  }
  return !isAlive(pid);
}

/** ensureProcessExited 的可注入选项（#1040 具名导出，供 cleanupIsolatedEnv 转发） */
export interface EnsureProcessExitedOptions {
  timeoutMs?: number;
  graceMs?: number;
  isAlive?: (pid: number) => boolean;
  kill?: (pid: number) => void;
  sleep?: (ms: number) => Promise<void>;
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
  options: EnsureProcessExitedOptions = {}
): Promise<void> {
  const { timeoutMs = 10_000, graceMs = 2_000, isAlive = isProcessAlive, sleep = realSleep } = options;
  const kill = options.kill ?? ((p: number) => process.kill(p));
  if (await waitForProcessExit(pid, timeoutMs, isAlive, sleep)) {
    return;
  }
  try {
    kill(pid);
  } catch (err) {
    void err;  // best-effort: swallow all kill errors (ESRCH / EPERM / others)
  }
  await sleep(graceMs);
}

/**
 * 半启动失败兜底（#1059）：run 抛错时 close app 恰好 1 次，再重抛原错误对象。
 * run 成功 → 原样返回结果且不调 close；close 自身抛错被吞，绝不掩盖原始错误。
 */
export async function withAppClosedOnFailure<T>(
  app: { close(): Promise<void> },
  run: () => Promise<T>
): Promise<T> {
  try {
    return await run();
  } catch (err) {
    try {
      await app.close();
    } catch {
      // 半启动失败的 close 兜底：绝不掩盖原始错误
    }
    throw err;
  }
}

export interface CleanupTarget {
  dataDir: string;
  userDataDir: string;
}

export interface CleanupIsolatedEnvOptions {
  /** 句柄持有者 pid（内核 / 渲染层）；undefined 项跳过；默认 []（不等任何进程） */
  pids?: ReadonlyArray<number | undefined>;
  timeoutMs?: number; // ensureProcessExited 等待预算（默认 10_000）
  graceMs?: number; // ensureProcessExited kill 后宽限（默认 2_000）
  dataDirBudget?: RmDirBudget; // dataDir 删除预算（默认 DEFAULT_RM_BUDGET）
  userDataDirBudget?: RmDirBudget; // userDataDir 删除预算（默认 USER_DATA_RM_BUDGET）
  ensureExited?: (pid: number, options?: EnsureProcessExitedOptions) => Promise<void>;
  rmDir?: (dir: string, options?: RmDirRetryOptions) => Promise<void>;
  isAlive?: (pid: number) => boolean;
  kill?: (pid: number) => void;
  sleep?: (ms: number) => Promise<void>;
  rm?: (dir: string) => void;
  listResiduals?: (dir: string, limit: number) => string[];
  residualLimit?: number;
}

/**
 * 隔离环境整体清理（#1040：先等句柄持有者退出，再按严格顺序删目录，不并发）。
 * ① 按序 await ensureExited 每个非 undefined pid（已退出单次探活即返回，零等待）；
 * ② rmDir(dataDir, { ...dataDirBudget, rm, sleep, listResiduals, residualLimit })；
 * ③ 同参数 rmDir(userDataDir)（默认预算不同：dataDir 40×250ms / userDataDir 80×500ms）。
 * 默认 ensureExited = ensureProcessExited、rmDir = rmDirWithRetry；任何失败都不吞错。
 */
export async function cleanupIsolatedEnv(
  target: CleanupTarget,
  options?: CleanupIsolatedEnvOptions
): Promise<void> {
  const {
    pids = [],
    timeoutMs = 10_000,
    graceMs = 2_000,
    dataDirBudget = DEFAULT_RM_BUDGET,
    userDataDirBudget = USER_DATA_RM_BUDGET,
    ensureExited = ensureProcessExited,
    rmDir = rmDirWithRetry,
    isAlive,
    kill,
    sleep,
    rm,
    listResiduals,
    residualLimit,
  } = options ?? {};
  for (const pid of pids) {
    if (pid !== undefined) {
      await ensureExited(pid, { timeoutMs, graceMs, isAlive, kill, sleep });
    }
  }
  await rmDir(target.dataDir, { ...dataDirBudget, rm, sleep, listResiduals, residualLimit });
  await rmDir(target.userDataDir, { ...userDataDirBudget, rm, sleep, listResiduals, residualLimit });
}

export interface IsolatedEnv {
  dataDir: string;
  userDataDir: string;
  env: Record<string, string | undefined>;
  cleanup(options?: CleanupIsolatedEnvOptions): Promise<void>;
}

export function createIsolatedEnv(tag: string, extra?: Record<string, string>): IsolatedEnv {
  const dataDir = mkdtempSync(path.join(tmpdir(), `inkflow-e2e-${tag}-`));
  const userDataDir = mkdtempSync(path.join(tmpdir(), `inkflow-e2e-${tag}-ud-`));
  return {
    dataDir,
    userDataDir,
    env: { ...process.env, INKFLOW_DATA_DIR: dataDir, ...extra },
    cleanup: (options?: CleanupIsolatedEnvOptions) =>
      cleanupIsolatedEnv({ dataDir, userDataDir }, options),
  };
}
