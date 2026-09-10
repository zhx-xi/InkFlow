/**
 * kernel-harness 单元测试（#1068）
 *
 * 契约：把「内核启动重试 + 端口预检」从集成测试文件抽成可注入模块，使启动机制
 * 能被确定性单测（无需真起内核）。集成测试（src/api/__integration__/*.test.ts）
 * 用本模块启动内核，从而获得「失败重启」而非「单纯加大超时」的 flaky 根治。
 *
 * 背景：#534 的 30s→60s 一次性加大已证伪（CI 冷 runner 上内核 import 树 11s 被
 * 放大到 >60s）；#1068 要求启动重试（kill + 二次 spawn）+ 端口预检。
 */
import { describe, expect, it, vi } from 'vitest';

import {
  MAX_LAUNCH_ATTEMPTS,
  READY_TIMEOUT_MS,
  launchWithRetry,
  probeFreePort,
  type LaunchAttempt,
} from './kernel-harness';

describe('probeFreePort（#1068 端口预检）', () => {
  it('返回一个可绑定的回环端口（预检端口的可用性）', async () => {
    const port = await probeFreePort();
    expect(Number.isInteger(port)).toBe(true);
    expect(port).toBeGreaterThan(0);
    expect(port).toBeLessThanOrEqual(65535);

    // 真绑定验证：预检返回的端口确实可用（复用 node:net 直接 bind）
    const { createServer } = await import('node:net');
    const server = createServer();
    await new Promise<void>((resolve, reject) => {
      server.once('error', reject);
      server.listen(port, '127.0.0.1', () => resolve());
    });
    await new Promise<void>((resolve) => server.close(() => resolve()));
  });

  it('连续调用返回的端口互不相同（不是写死的常量）', async () => {
    const a = await probeFreePort();
    const b = await probeFreePort();
    const c = await probeFreePort();
    // 动态分配端口极小概率重复；断言「至少有一个不同」足以排除硬编码常量
    expect(new Set([a, b, c]).size).toBeGreaterThan(1);
  });
});

describe('launchWithRetry（#1068 启动重试）', () => {
  it('首次失败、第二次成功 → 返回 ready，且记录 2 次尝试', async () => {
    const spawnOnce = vi
      .fn<(port: number) => Promise<string>>()
      .mockRejectedValueOnce(new Error('第一次启动超时'))
      .mockResolvedValueOnce('ready-payload');

    const { ready, attempts } = await launchWithRetry({
      attempts: 2,
      spawnOnce,
      probe: async () => 40001,
    });

    expect(ready).toBe('ready-payload');
    expect(spawnOnce).toHaveBeenCalledTimes(2);
    expect(attempts).toHaveLength(2);
    expect(attempts[0].error).toBeInstanceOf(Error);
    expect(attempts[1].error).toBeNull();
  });

  it('每次尝试都做端口预检，且把预检端口传给 spawnOnce（不再用 --port 0 盲选）', async () => {
    const ports = [41001, 41002];
    let i = 0;
    const probe = vi.fn(async () => ports[i++]);
    const seen: number[] = [];
    const spawnOnce = vi.fn(async (port: number) => {
      seen.push(port);
      if (seen.length === 1) throw new Error('第一次失败');
      return 'ok';
    });

    await launchWithRetry({ attempts: 2, spawnOnce, probe });

    expect(probe).toHaveBeenCalledTimes(2);
    expect(seen).toEqual([41001, 41002]);
    // 关键契约：传给 spawn 的端口是预检结果，不是 0
    expect(seen.every((p) => p > 0)).toBe(true);
  });

  it('首次失败时回调 onAttemptFailed，携带尝试序号与错误', async () => {
    const failures: LaunchAttempt[] = [];
    const spawnOnce = vi
      .fn<(port: number) => Promise<string>>()
      .mockRejectedValueOnce(new Error('boom-1'))
      .mockResolvedValueOnce('ok');

    await launchWithRetry({
      attempts: 2,
      spawnOnce,
      probe: async () => 42001,
      onAttemptFailed: (a) => failures.push(a),
    });

    expect(failures).toHaveLength(1);
    expect(failures[0].attempt).toBe(1);
    expect(failures[0].error?.message).toBe('boom-1');
  });

  it('全部尝试失败 → reject，且错误消息含每一次失败的原因（可诊断）', async () => {
    const spawnOnce = vi
      .fn<(port: number) => Promise<string>>()
      .mockRejectedValueOnce(new Error('超时-A'))
      .mockRejectedValueOnce(new Error('超时-B'));

    await expect(
      launchWithRetry({ attempts: 2, spawnOnce, probe: async () => 43001 }),
    ).rejects.toThrow(/超时-A[\s\S]*超时-B/);

    expect(spawnOnce).toHaveBeenCalledTimes(2);
  });

  it('预检抛错（本机无法绑定回环）→ 冒泡，不做无谓的内核 spawn', async () => {
    const spawnOnce = vi.fn(async () => 'never');

    await expect(
      launchWithRetry({
        attempts: 2,
        spawnOnce,
        probe: async () => {
          throw new Error('EADDRNOTAVAIL: 无法绑定 127.0.0.1');
        },
      }),
    ).rejects.toThrow(/EADDRNOTAVAIL/);

    expect(spawnOnce).not.toHaveBeenCalled();
  });

  it('成功路径不产生多余的预检/尝试（首次即成功 → 1 次）', async () => {
    const probe = vi.fn(async () => 44001);
    const spawnOnce = vi.fn(async () => 'ready-first-try');

    const { ready, attempts } = await launchWithRetry({ attempts: 2, spawnOnce, probe });

    expect(ready).toBe('ready-first-try');
    expect(probe).toHaveBeenCalledTimes(1);
    expect(attempts).toHaveLength(1);
  });
});

describe('启动预算常量（#1068 契约）', () => {
  it('MAX_LAUNCH_ATTEMPTS 至少 2（单次尝试已被证伪）', () => {
    expect(MAX_LAUNCH_ATTEMPTS).toBeGreaterThanOrEqual(2);
  });

  it('READY_TIMEOUT_MS 不低于既有 60s 基线（仅兜底放大，非主修手段）', () => {
    expect(READY_TIMEOUT_MS).toBeGreaterThanOrEqual(60_000);
  });
});
