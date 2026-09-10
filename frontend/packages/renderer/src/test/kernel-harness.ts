/**
 * kernel-harness —— 内核启动机制（#1068）
 *
 * 把「内核启动重试 + 端口预检」从集成测试文件抽成可注入模块，使启动机制能被确定性
 * 单测（无需真起内核）。本模块只负责两件事：
 *
 * 1. probeFreePort：spawn 前在 127.0.0.1 上探测一个空闲端口并立即释放，把该端口显式
 *    传给内核（`--port <N>`），替代 `--port 0` 盲选——内核内部 bind(0)→close()→uvicorn
 *    再 bind 存在竞态窗口。
 * 2. launchWithRetry：单次启动失败（READY 超时 / 提前退出）→ 由调用方 kill 清理 → 重试，
 *    最多 attempts 次；全部失败时抛出的错误消息按顺序含每一次失败原因（CI 可诊断）。
 *
 * 背景：#534 的 30s→60s 一次性加大已证伪（CI 冷 runner 上内核 import 树 11s 被 Defender
 * 扫描放大到 >60s）；#1068 的主修是「失败重启」，放大超时仅作兜底。
 *
 * 约束：只依赖 node: 内建（node:net）；不在本模块内 spawn 内核——spawn 由调用方通过
 * spawnOnce 注入，便于单测，且本文件在 jsdom / node 两种环境下都可能被加载。
 */
import { createServer } from 'node:net';

/** 单次启动尝试等待 INKFLOW_READY 的预算（#1068 兜底：60s → 90s） */
export const READY_TIMEOUT_MS = 90_000;

/** 最大启动尝试次数（#1068：单次尝试已被 CI 证伪，允许失败后二次 spawn） */
export const MAX_LAUNCH_ATTEMPTS = 2;

/** 单次启动尝试的结果记录（成功时 error 为 null） */
export interface LaunchAttempt {
  /** 1-based 尝试序号 */
  attempt: number;
  /** 该次尝试使用的端口（端口预检失败时为 null） */
  port: number | null;
  /** 成功为 null；失败为该次抛出的错误 */
  error: Error | null;
}

/**
 * 在 host（默认 127.0.0.1）上探测一个空闲端口并立即释放（系统动态分配，连续调用不重复）。
 *
 * 必须异步：`listen(0)` 的 bind 是异步的，只有 `listening` 事件之后 `server.address()`
 * 才拿得到系统分配端口（同步读取会拿到 null）。绑定失败（`error` 事件）→ reject，把
 * 「本机无法绑定回环」前置暴露，而不是拖到 READY 超时。
 */
export function probeFreePort(host = '127.0.0.1'): Promise<number> {
  return new Promise<number>((resolve, reject) => {
    const server = createServer();
    server.once('error', reject);
    server.listen(0, host, () => {
      const address = server.address();
      if (address === null || typeof address === 'string') {
        server.close();
        reject(new Error('端口预检失败：未能取得监听端口'));
        return;
      }
      const port = address.port;
      server.close(() => resolve(port));
    });
  });
}

/**
 * 带重试的内核启动：每次尝试先做端口预检，再把预检端口交给 spawnOnce。
 *
 * - 预检 reject → 立即向调用方冒泡，不调 spawnOnce（本机无法绑定回环时不做无谓 spawn）。
 * - spawnOnce 抛错 → 记录本次尝试（attempt/port/error）并回调 onAttemptFailed，
 *   若还有剩余次数则继续下一次尝试。
 * - 全部尝试失败 → reject 一个 Error，消息按尝试顺序含每一次失败原因。
 * - 首次即成功 → probe 只调 1 次、attempts 只含 1 条（不产生多余的预检/尝试）。
 */
export async function launchWithRetry<T>(opts: {
  attempts: number;
  spawnOnce: (port: number) => Promise<T>;
  onAttemptFailed?: (a: LaunchAttempt) => void;
  probe?: () => Promise<number>;
}): Promise<{ ready: T; attempts: LaunchAttempt[] }> {
  const probe = opts.probe ?? probeFreePort;
  const attempts: LaunchAttempt[] = [];

  for (let attempt = 1; attempt <= opts.attempts; attempt += 1) {
    const port = await probe();
    try {
      const ready = await opts.spawnOnce(port);
      attempts.push({ attempt, port, error: null });
      return { ready, attempts };
    } catch (err) {
      const record: LaunchAttempt = {
        attempt,
        port,
        error: err instanceof Error ? err : new Error(String(err)),
      };
      attempts.push(record);
      opts.onAttemptFailed?.(record);
    }
  }

  const reasons = attempts
    .map((a) => {
      const port = a.port ?? 'n/a';
      const reason = a.error?.message ?? '未知错误';
      return `第 ${a.attempt} 次尝试（端口 ${port}）：${reason}`;
    })
    .join('\n');
  throw new Error(`内核启动失败（已尝试 ${attempts.length} 次）：\n${reasons}`);
}
