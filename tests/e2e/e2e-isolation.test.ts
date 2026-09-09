/**
 * e2e-isolation.ts 模块契约（S3f-T3 R3，contract-s3f-t3 §1.3）。
 *
 * createIsolatedEnv(tag, extra?) → IsolatedEnv { dataDir, userDataDir, env, cleanup }：
 * - dataDir     = mkdtempSync(join(tmpdir(), `inkflow-e2e-${tag}-`))   （内核数据隔离）
 * - userDataDir = 同上、`-ud` 后缀                                      （渲染层 --user-data-dir）
 * - env         = { ...process.env, INKFLOW_DATA_DIR: dataDir } + extra 覆盖（extra 优先）
 * - cleanup     = async cleanupIsolatedEnv（#1040：先等句柄持有者退出；dataDir 40×250ms / userDataDir 80×500ms）
 *
 * 纯 Node 模块（禁 import @playwright/test，#415 vitest 加载约束）；spec（e2e-isolation.spec.ts
 * / e2e-rag-fake.spec.ts）与 vitest 双加载。
 *
 * RED 形态（#1033）：rmDirWithRetry / waitForProcessExit / ensureProcessExited 尚未实现 →
 * vitest import 期 Cannot find export（本文件 collection FAIL）。
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import {
  cleanupIsolatedEnv,
  createIsolatedEnv,
  ensureProcessExited,
  rmDirWithRetry,
  waitForProcessExit,
  withAppClosedOnFailure,
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
    // #1059：注入 sleep 现已透传到轮询（DI 接缝补全）→ 总次数不再恒为 1；
    // 保留原意「kill 后仍走 grace 等待」= 最后一次 sleep 是 graceMs(0)
    expect(sleep).toHaveBeenLastCalledWith(0);
  });
});


describe('cleanupIsolatedEnv（#1040：先等句柄持有者退出再删；userDataDir 预算放宽）', () => {
  it('pid 已退出 → 单次探活零等待，随后按序删除 dataDir/userDataDir', async () => {
    const iso = createIsolatedEnv('c1');
    created.push(iso);
    const isAlive = vi.fn(() => false);
    const sleep = vi.fn(async () => undefined);
    const rmDir = vi.fn(async () => undefined);
    await cleanupIsolatedEnv(iso, { pids: [4242], isAlive, sleep, rmDir });
    // 已退出：单次探活、零 sleep（不引入无谓等待）
    expect(isAlive).toHaveBeenCalledTimes(1);
    expect(isAlive).toHaveBeenCalledWith(4242);
    expect(sleep).not.toHaveBeenCalled();
    // 两目录各删一次，顺序 = dataDir → userDataDir
    expect(rmDir).toHaveBeenCalledTimes(2);
    expect(rmDir.mock.calls[0][0]).toBe(iso.dataDir);
    expect(rmDir.mock.calls[1][0]).toBe(iso.userDataDir);
    // 先等（探活）再删（调用序）
    expect(isAlive.mock.invocationCallOrder[0]).toBeLessThan(rmDir.mock.invocationCallOrder[0]);
  });

  it('pid 未退出 → 轮询等到退出后才删（等待严格先于删除）', async () => {
    const iso = createIsolatedEnv('c2');
    created.push(iso);
    const isAlive = vi.fn().mockReturnValueOnce(true).mockReturnValueOnce(false);
    const rmDir = vi.fn(async () => undefined);
    await cleanupIsolatedEnv(iso, { pids: [4243], timeoutMs: 5_000, isAlive, rmDir });
    // 首次探活存活 → 轮询一次 → 第二次死亡 → 才删
    expect(isAlive).toHaveBeenCalledTimes(2);
    expect(isAlive.mock.invocationCallOrder[1]).toBeLessThan(rmDir.mock.invocationCallOrder[0]);
  });

  it('pid 超时仍存活 → best-effort kill 后仍继续删除（不抛）', async () => {
    const iso = createIsolatedEnv('c3');
    created.push(iso);
    const isAlive = vi.fn(() => true);
    const kill = vi.fn();
    const sleep = vi.fn(async () => undefined);
    const rmDir = vi.fn(async () => undefined);
    await expect(
      cleanupIsolatedEnv(iso, { pids: [4244], timeoutMs: 50, graceMs: 0, isAlive, kill, sleep, rmDir })
    ).resolves.toBeUndefined();
    expect(kill).toHaveBeenCalledTimes(1);
    expect(rmDir).toHaveBeenCalledTimes(2);
  });

  it('pids 含 undefined（未 launch / 无 pid）→ 跳过等待，仅删目录', async () => {
    const iso = createIsolatedEnv('c4');
    created.push(iso);
    const isAlive = vi.fn(() => false);
    const rmDir = vi.fn(async () => undefined);
    await cleanupIsolatedEnv(iso, { pids: [undefined, undefined], isAlive, rmDir });
    expect(isAlive).not.toHaveBeenCalled();
    expect(rmDir).toHaveBeenCalledTimes(2);
  });

  it('userDataDir 预算放宽（80×500ms），dataDir 保持 40×250ms', async () => {
    const iso = createIsolatedEnv('c5');
    created.push(iso);
    const rmDir = vi.fn(async () => undefined);
    await cleanupIsolatedEnv(iso, { rmDir });
    expect(rmDir).toHaveBeenNthCalledWith(
      1,
      iso.dataDir,
      expect.objectContaining({ retries: 40, delayMs: 250 })
    );
    expect(rmDir).toHaveBeenNthCalledWith(
      2,
      iso.userDataDir,
      expect.objectContaining({ retries: 80, delayMs: 500 })
    );
  });

  it('真实删除两目录（无注入，端到端）', async () => {
    const iso = createIsolatedEnv('c6');
    expect(existsSync(iso.dataDir)).toBe(true);
    expect(existsSync(iso.userDataDir)).toBe(true);
    await cleanupIsolatedEnv(iso, { pids: [] });
    expect(existsSync(iso.dataDir)).toBe(false);
    expect(existsSync(iso.userDataDir)).toBe(false);
  });
});

describe('rmDirWithRetry 残留诊断（#1040：耗尽报错带残留清单前 N 项，仍抛原错误对象）', () => {
  it('非瞬态立即重抛：保留原错误对象 + 附加残留清单（注入 lister）', async () => {
    const dir = path.join(tmpdir(), 'rm-residual-injected-tmp');
    const err = new Error('EPERM: operation not permitted, unlink ...');
    const rm = vi.fn(() => {
      throw err;
    });
    const listResiduals = vi.fn(() => ['GPUCache/index', 'Local Storage/leveldb/LOCK']);
    await expect(
      rmDirWithRetry(dir, {
        retries: 1,
        rm,
        sleep: async () => undefined,
        listResiduals,
        residualLimit: 2,
      })
    ).rejects.toBe(err);
    expect(listResiduals).toHaveBeenCalledWith(dir, 2);
    expect(err.message).toContain('GPUCache/index');
    expect((err as Error & { residuals?: string[] }).residuals).toEqual([
      'GPUCache/index',
      'Local Storage/leveldb/LOCK',
    ]);
  });

  it('默认 lister 列出真实目录条目（耗尽路径，非 Error 也附加诊断）', async () => {
    const dir = mkdtempSync(path.join(tmpdir(), 'rm-residual-real-'));
    writeFileSync(path.join(dir, 'locked.txt'), 'x');
    const err: { code: string; residuals?: string[] } = { code: 'EPERM' };
    const rm = vi.fn(() => {
      throw err;
    });
    await expect(rmDirWithRetry(dir, { retries: 0, rm, sleep: async () => undefined })).rejects.toBe(
      err
    );
    expect(err.residuals).toContain('locked.txt');
    rmSync(dir, { recursive: true, force: true });
  });
});

  it('注入 lister 抛错不改变主流程结论：不附加诊断且仍抛原错误对象', async () => {
    const dir = path.join(tmpdir(), 'rm-residual-lister-throws-tmp');
    const err: { code: string; dir?: string; residuals?: string[] } = { code: 'EPERM' };
    const rm = vi.fn(() => {
      throw err;
    });
    const listResiduals = vi.fn(() => {
      throw new Error('lister boom');
    });
    await expect(
      rmDirWithRetry(dir, { retries: 1, rm, sleep: async () => undefined, listResiduals })
    ).rejects.toBe(err);
    // 诊断是旁路：自身故障不得替换原错误，也不得留下半截诊断
    expect(listResiduals).toHaveBeenCalledTimes(1);
    expect(err.residuals).toBeUndefined();
    expect(err.dir).toBeUndefined();
  });

describe('withAppClosedOnFailure（#1059：半启动失败不留孤儿 Electron）', () => {
  it('run 成功 → 原样返回结果且不 close', async () => {
    const close = vi.fn(async () => undefined);
    const result = await withAppClosedOnFailure({ close }, async () => 'ok');
    expect(result).toBe('ok');
    expect(close).not.toHaveBeenCalled();
  });

  it('run 抛错 → close 恰好 1 次且重抛原错误', async () => {
    const err = new Error('waitKernelInfo 超时');
    const close = vi.fn(async () => undefined);
    await expect(
      withAppClosedOnFailure({ close }, async () => {
        throw err;
      })
    ).rejects.toBe(err);
    expect(close).toHaveBeenCalledTimes(1);
  });

  it('close 自身抛错不掩盖原错误（仍重抛原错误）', async () => {
    const err = new Error('launch 半途失败');
    const close = vi.fn(async () => {
      throw new Error('close boom');
    });
    await expect(
      withAppClosedOnFailure({ close }, async () => {
        throw err;
      })
    ).rejects.toBe(err);
    expect(close).toHaveBeenCalledTimes(1);
  });
});

describe('残留诊断幂等 / 轮询 sleep DI（#1059：低危观察项收编）', () => {
  it('同一错误对象跨两次调用：message 残留标记只追加一次（幂等）', async () => {
    const dir = path.join(tmpdir(), 'rm-residual-idempotent-tmp');
    const err = new Error('EPERM: operation not permitted');
    const rm = vi.fn(() => {
      throw err;
    });
    const listResiduals = vi.fn(() => ['a']);
    const options = { retries: 0, rm, sleep: async () => undefined, listResiduals };
    await expect(rmDirWithRetry(dir, options)).rejects.toBe(err);
    await expect(rmDirWithRetry(dir, options)).rejects.toBe(err);
    expect((err.message.match(/残留前 /g) ?? []).length).toBe(1);
    expect(listResiduals).toHaveBeenCalledTimes(2);
  });

  it('waitForProcessExit：注入 sleep 生效（轮询间隔走 DI，不再硬编码真实等待）', async () => {
    const isAlive = vi.fn().mockReturnValueOnce(true).mockReturnValueOnce(false);
    const sleep = vi.fn(async () => undefined);
    await expect(waitForProcessExit(4246, 10_000, isAlive, sleep)).resolves.toBe(true);
    expect(sleep).toHaveBeenCalledWith(100);
    expect(isAlive).toHaveBeenCalledTimes(2);
  });

  it('ensureProcessExited：注入 sleep 透传到轮询', async () => {
    const isAlive = vi.fn(() => true);
    const kill = vi.fn();
    const sleep = vi.fn(async () => undefined);
    await expect(
      ensureProcessExited(4247, { timeoutMs: 200, graceMs: 0, isAlive, kill, sleep })
    ).resolves.toBeUndefined();
    expect(kill).toHaveBeenCalledTimes(1);
    expect(sleep.mock.calls.some((c) => c[0] === 100)).toBe(true);
  });
});
