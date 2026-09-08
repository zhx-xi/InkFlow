/**
 * e2e-isolation.ts 模块契约（S3f-T3 R3，contract-s3f-t3 §1.3）。
 *
 * createIsolatedEnv(tag, extra?) → IsolatedEnv { dataDir, userDataDir, env, cleanup }：
 * - dataDir     = mkdtempSync(join(tmpdir(), `inkflow-e2e-${tag}-`))   （内核数据隔离）
 * - userDataDir = 同上、`-ud` 后缀                                      （渲染层 --user-data-dir）
 * - env         = { ...process.env, INKFLOW_DATA_DIR: dataDir } + extra 覆盖（extra 优先）
 * - cleanup     = async rmDirWithRetry（#1033：仅瞬态码重试、非瞬态立即抛、耗尽抛最后错误）
 *
 * 纯 Node 模块（禁 import @playwright/test，#415 vitest 加载约束）；spec（e2e-isolation.spec.ts
 * / e2e-rag-fake.spec.ts）与 vitest 双加载。
 *
 * RED 形态（#1033）：rmDirWithRetry / waitForProcessExit / ensureProcessExited 尚未实现 →
 * vitest import 期 Cannot find export（本文件 collection FAIL）。
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import {
  createIsolatedEnv,
  ensureProcessExited,
  rmDirWithRetry,
  waitForProcessExit,
  type IsolatedEnv,
} from './e2e-isolation';

/** 本文件创建的 env 清单——afterEach 兜底清理，防断言中途失败遗留临时目录 */
const created: IsolatedEnv[] = [];

afterEach(async () => {
  for (const env of created.splice(0)) {
    try {
      await env.cleanup();
    } catch {
      // cleanup 幂等：清理失败不掩盖用例结论
    }
  }
});

describe('createIsolatedEnv（S3f-T3 §1.3 四断言）', () => {
  it('① 目录真实存在且 env 回写 INKFLOW_DATA_DIR', () => {
    const env = createIsolatedEnv('t1');
    created.push(env);
    // mkdtemp 前缀约定：dataDir 带 tag、userDataDir 带 -ud- 后缀（供 spec 双隔离）
    expect(env.dataDir.startsWith(path.join(tmpdir(), 'inkflow-e2e-t1-'))).toBe(true);
    expect(env.userDataDir.startsWith(path.join(tmpdir(), 'inkflow-e2e-t1-ud-'))).toBe(true);
    expect(existsSync(env.dataDir)).toBe(true);
    expect(existsSync(env.userDataDir)).toBe(true);
    // env 回写：INKFLOW_DATA_DIR 指向 dataDir；其余键继承 process.env
    expect(env.env.INKFLOW_DATA_DIR).toBe(env.dataDir);
    expect(env.env.PATH).toBe(process.env.PATH);
  });

  it('② extra 覆盖优先（含 INKFLOW_DATA_DIR 键 + 自定义键）', () => {
    const env = createIsolatedEnv('t2', { INKFLOW_DATA_DIR: 'extra-override-value', CUSTOM_EXTRA: 'v' });
    created.push(env);
    // extra 在 base（process.env + INKFLOW_DATA_DIR=dataDir）之后展开 → 同键覆盖
    expect(env.env.INKFLOW_DATA_DIR).toBe('extra-override-value');
    expect(env.env.CUSTOM_EXTRA).toBe('v');
    // 目录仍独立创建（env 键可被 extra 改写，目录生命周期不受影响）
    expect(env.dataDir).not.toBe('extra-override-value');
    expect(existsSync(env.dataDir)).toBe(true);
  });

  it('③ cleanup 幂等：目录消失 + 重复调用不抛', async () => {
    const env = createIsolatedEnv('t3');
    expect(existsSync(env.dataDir)).toBe(true);
    expect(existsSync(env.userDataDir)).toBe(true);
    await env.cleanup();
    expect(existsSync(env.dataDir)).toBe(false);
    expect(existsSync(env.userDataDir)).toBe(false);
    // rmDirWithRetry 幂等：缺目录不抛（重复 cleanup / 外部已删均安全）
    await expect(env.cleanup()).resolves.toBeUndefined();
  });

  it('④ 两次调用目录不同（per-test 隔离前提）', () => {
    const a = createIsolatedEnv('t4');
    const b = createIsolatedEnv('t4');
    created.push(a, b);
    expect(a.dataDir).not.toBe(b.dataDir);
    expect(a.userDataDir).not.toBe(b.userDataDir);
    expect(a.env.INKFLOW_DATA_DIR).not.toBe(b.env.INKFLOW_DATA_DIR);
  });
});

describe('rmDirWithRetry（#1033：瞬态码重试 / 非瞬态立即抛 / 耗尽抛最后错误）', () => {
  it('瞬态 EPERM 重试后成功：rm 恰好 3 次且 resolve', async () => {
    const rm = vi
      .fn()
      .mockImplementationOnce(() => {
        throw { code: 'EPERM' };
      })
      .mockImplementationOnce(() => {
        throw { code: 'EPERM' };
      });
    await expect(
      rmDirWithRetry(path.join(tmpdir(), 'rm-retry-eperm-tmp'), {
        rm,
        sleep: async () => undefined,
      })
    ).resolves.toBeUndefined();
    expect(rm).toHaveBeenCalledTimes(3);
  });

  it('非瞬态 EINVAL 不重试：reject 原错误且 rm 恰好 1 次', async () => {
    const err = { code: 'EINVAL' };
    const rm = vi.fn(() => {
      throw err;
    });
    await expect(
      rmDirWithRetry(path.join(tmpdir(), 'rm-nontransient-tmp'), {
        rm,
        sleep: async () => undefined,
      })
    ).rejects.toBe(err);
    expect(rm).toHaveBeenCalledTimes(1);
  });

  it('重试耗尽：retries=2 恒 EPERM → reject 最后一个错误且 rm 恰好 3 次', async () => {
    const e1 = { code: 'EPERM' };
    const e2 = { code: 'EPERM' };
    const e3 = { code: 'EPERM' };
    const rm = vi
      .fn()
      .mockImplementationOnce(() => {
        throw e1;
      })
      .mockImplementationOnce(() => {
        throw e2;
      })
      .mockImplementationOnce(() => {
        throw e3;
      });
    await expect(
      rmDirWithRetry(path.join(tmpdir(), 'rm-exhausted-tmp'), {
        retries: 2,
        rm,
        sleep: async () => undefined,
      })
    ).rejects.toBe(e3);
    expect(rm).toHaveBeenCalledTimes(3);
  });
});

describe('waitForProcessExit / ensureProcessExited（#1033：注入探活，无真实进程）', () => {
  it('waitForProcessExit：注入 isAlive 第 2 次轮询报告死亡 → true', async () => {
    const isAlive = vi.fn().mockReturnValueOnce(true).mockReturnValueOnce(false);
    await expect(waitForProcessExit(4242, 10_000, isAlive)).resolves.toBe(true);
    expect(isAlive).toHaveBeenCalledTimes(2);
  });

  it('waitForProcessExit：isAlive 恒真 → 超时 false（不抛）', async () => {
    const isAlive = vi.fn(() => true);
    await expect(waitForProcessExit(4243, 250, isAlive)).resolves.toBe(false);
  });

  it('ensureProcessExited：isAlive 恒真 → kill 恰好 1 次且 resolve（不抛）', async () => {
    const kill = vi.fn();
    const isAlive = vi.fn(() => true);
    await expect(
      ensureProcessExited(4244, {
        timeoutMs: 250,
        graceMs: 50,
        isAlive,
        kill,
        sleep: async () => undefined,
      })
    ).resolves.toBeUndefined();
    expect(kill).toHaveBeenCalledTimes(1);
  });

  it('ensureProcessExited：kill 抛 EPERM 也不抛（best-effort，仍等 graceMs）', async () => {
    const kill = vi.fn(() => {
      throw { code: 'EPERM' };
    });
    const isAlive = vi.fn(() => true);
    const sleep = vi.fn(async () => undefined);
    await expect(
      ensureProcessExited(4245, {
        timeoutMs: 200,
        graceMs: 0,
        isAlive,
        kill,
        sleep,
      })
    ).resolves.toBeUndefined();
    expect(kill).toHaveBeenCalledTimes(1);
    expect(sleep).toHaveBeenCalledTimes(1);
  });
});
