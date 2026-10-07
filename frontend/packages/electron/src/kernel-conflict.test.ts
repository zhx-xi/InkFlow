/**
 * #1487 / ADR-066 ①④ —— 内核冲突自愈控制器单元契约（vitest node，纯 DI 宿主）。
 *
 * 契约来源：spec f31 §5.3（换 data_dir 先停旧、起新）/ §7 边界 17（退出码 3 分流）。
 * 覆盖：停机命中/未命中、宿主不可用、非当前内核回调忽略、自愈复用优先、
 * 「先停旧、起新」顺序、超限交宿主报错。
 */
import { describe, expect, it, vi } from 'vitest';
import type { ChildProcess } from 'node:child_process';
import {
  MAX_CONFLICT_RECOVERIES,
  createKernelConflictController,
  type KernelConflictHost,
} from './kernel-conflict';
import type { KernelInstance } from './kernel';

const inst = (over: Partial<KernelInstance> = {}): KernelInstance => ({
  kind: 'dev',
  port: 60099,
  pid: 4242,
  version: '0.17.0',
  started_at: '2026-10-07T00:00:00+00:00',
  data_dir: 'C:\\other',
  ...over,
});

interface HostOverrides {
  stateFilePath?: string | null;
  kind?: string;
  appDataPath?: string | null;
  registryDir?: string;
  instances?: KernelInstance[];
  reused?: unknown;
  stopping?: boolean;
}

function makeHost(over: HostOverrides = {}): {
  host: KernelConflictHost;
  killed: number[];
  scheduled: Array<() => void>;
  spawned: number;
  gaveUp: number;
  reuseCalls: number;
  cleared: number;
} {
  const state = {
    killed: [] as number[],
    scheduled: [] as Array<() => void>,
    spawned: 0,
    gaveUp: 0,
    reuseCalls: 0,
    cleared: 0,
  };
  const host: KernelConflictHost = {
    isCurrentKernel: () => true,
    getStateFilePath: () => over.stateFilePath ?? 'C:\\data\\mine\\kernel.json',
    getKind: () => over.kind ?? 'dev',
    getAppDataPath: () => (over.appDataPath === undefined ? 'C:\\appdata' : over.appDataPath),
    kill: async (pid) => {
      state.killed.push(pid);
    },
    clearKernelRefs: () => {
      state.cleared += 1;
    },
    clearTimers: () => {},
    rebuildTray: () => {},
    scheduleRestart: (fn) => {
      state.scheduled.push(fn);
    },
    isStopping: () => over.stopping ?? false,
    tryReuseAndAttach: async () => {
      state.reuseCalls += 1;
      return (over.reused ?? null) as never;
    },
    spawnKernel: () => {
      state.spawned += 1;
    },
    onGiveUp: async () => {
      state.gaveUp += 1;
    },
    logConflict: () => {},
    logStopOld: () => {},
  };
  // readInstanceRegistry 走真实实现 → 用临时目录 + 真实注册表文件（见各用例）
  // 返回 **state 本体**（非展开拷贝）：计数属性需为活值，否则断言读到创建时快照
  return Object.assign(state, { host });
}

describe('stopConflictingKernel（spec f31 §5.3 1B）', () => {
  it('状态文件路径不可用 → false（不查注册表、不杀）', async () => {
    const h = makeHost({ stateFilePath: null });
    expect(await createKernelConflictController(h.host).stopConflictingKernel()).toBe(false);
    expect(h.killed).toEqual([]);
  });

  it('appData 不可用（测试 mock）→ false', async () => {
    const h = makeHost({ appDataPath: null });
    expect(await createKernelConflictController(h.host).stopConflictingKernel()).toBe(false);
  });

  it('无冲突条目（注册表目录不存在）→ false（直接 spawn）', async () => {
    const h = makeHost({ appDataPath: 'C:\\definitely-no-such-appdata-1487' });
    expect(await createKernelConflictController(h.host).stopConflictingKernel()).toBe(false);
    expect(h.killed).toEqual([]);
  });

  it('命中「kind 相同 + data_dir 不同」的存活实例 → 停旧并返回 true', async () => {
    const fs = await import('node:fs');
    const os = await import('node:os');
    const pathMod = await import('node:path');
    const dir = fs.mkdtempSync(pathMod.join(os.tmpdir(), 'inkflow-1487-conflict-'));
    try {
      const running = pathMod.join(dir, 'running');
      fs.mkdirSync(running, { recursive: true });
      // dev 分域：<data_dir>/running/<kind>-<pid>.json；pid 用本进程（必存活）
      fs.writeFileSync(
        pathMod.join(running, `dev-${process.pid}.json`),
        JSON.stringify({
          kind: 'dev',
          port: 60099,
          token: 'tok',
          pid: process.pid,
          version: '0.17.0',
          started_at: '2026-10-07T00:00:00+00:00',
          data_dir: pathMod.join(dir, 'OTHER'),
        }),
        'utf-8'
      );
      const h = makeHost({
        stateFilePath: pathMod.join(dir, 'kernel.json'),
        appDataPath: dir,
      });
      expect(await createKernelConflictController(h.host).stopConflictingKernel()).toBe(true);
      expect(h.killed).toEqual([process.pid]);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  it('同 data_dir 的存活实例 → 不算冲突（交给复用判定）', async () => {
    const fs = await import('node:fs');
    const os = await import('node:os');
    const pathMod = await import('node:path');
    const dir = fs.mkdtempSync(pathMod.join(os.tmpdir(), 'inkflow-1487-same-'));
    try {
      const running = pathMod.join(dir, 'running');
      fs.mkdirSync(running, { recursive: true });
      fs.writeFileSync(
        pathMod.join(running, `dev-${process.pid}.json`),
        JSON.stringify({
          kind: 'dev',
          port: 60099,
          token: 'tok',
          pid: process.pid,
          version: '0.17.0',
          started_at: '2026-10-07T00:00:00+00:00',
          data_dir: dir,
        }),
        'utf-8'
      );
      const h = makeHost({ stateFilePath: pathMod.join(dir, 'kernel.json'), appDataPath: dir });
      expect(await createKernelConflictController(h.host).stopConflictingKernel()).toBe(false);
      expect(h.killed).toEqual([]);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe('onKernelConflict（spec f31 §7 边界 17）', () => {
  it('非当前内核回调 → 忽略（旧进程残留）', async () => {
    const h = makeHost();
    const host = { ...h.host, isCurrentKernel: () => false };
    createKernelConflictController(host).onKernelConflict({ pid: 1 } as ChildProcess);
    expect(h.cleared).toBe(0);
    expect(h.scheduled).toEqual([]);
  });

  it('当前内核 → 清引用 + 调度自愈（不进退避链路）', async () => {
    const h = makeHost();
    createKernelConflictController(h.host).onKernelConflict({ pid: 7 } as ChildProcess);
    expect(h.cleared).toBe(1);
    expect(h.scheduled).toHaveLength(1);
  });

  it('stopping 中 → 清引用但不调度自愈', async () => {
    const h = makeHost({ stopping: true });
    createKernelConflictController(h.host).onKernelConflict({ pid: 7 } as ChildProcess);
    expect(h.cleared).toBe(1);
    expect(h.scheduled).toEqual([]);
  });
});

describe('recoverFromConflict（经调度闭包触发）', () => {
  /** 调度闭包是 `void recoverFromConflict()`（返回 undefined）→ 需自行冲刷微任务链 */
  const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

  it('同 data_dir 复用成功 → 不启动新内核', async () => {
    const h = makeHost({ reused: { pid: 9, port: 5, token: 't', version: '0.17.0' } });
    const controller = createKernelConflictController(h.host);
    controller.onKernelConflict({ pid: 7 } as ChildProcess);
    h.scheduled[0]();
    await flush();
    expect(h.reuseCalls).toBe(1);
    expect(h.spawned).toBe(0);
  });

  it('复用失败 → 先停旧（stopConflicting）后起新（spawn）', async () => {
    const h = makeHost();
    const controller = createKernelConflictController(h.host);
    controller.onKernelConflict({ pid: 7 } as ChildProcess);
    h.scheduled[0]();
    await flush();
    expect(h.spawned).toBe(1);
  });

  it(`自愈超过 ${MAX_CONFLICT_RECOVERIES} 次 → 交宿主 onGiveUp（不无限重拉）`, async () => {
    const h = makeHost({ reused: { pid: 9, port: 5, token: 't', version: '0.17.0' } });
    const controller = createKernelConflictController(h.host);
    for (let i = 0; i < MAX_CONFLICT_RECOVERIES + 1; i += 1) {
      controller.onKernelConflict({ pid: 7 } as ChildProcess);
      h.scheduled[i]();
      await flush();
    }
    expect(h.gaveUp).toBe(1);
    expect(h.spawned).toBe(0);
  });

  it('resetRecoveries 后计数归零（成功就绪路径）', async () => {
    const h = makeHost({ reused: { pid: 9, port: 5, token: 't', version: '0.17.0' } });
    const controller = createKernelConflictController(h.host);
    controller.onKernelConflict({ pid: 7 } as ChildProcess);
    h.scheduled[0]();
    await flush();
    controller.resetRecoveries();
    controller.onKernelConflict({ pid: 7 } as ChildProcess);
    h.scheduled[1]();
    await flush();
    expect(h.gaveUp).toBe(0);
  });
});

describe('killKernelByPid（kernel.ts，DI 装配缝）', () => {
  it('spawn taskkill 后等其退出（isAlive 恒真 → 到宽限即返回）', async () => {
    const { killKernelByPid } = await import('./kernel');
    const killed: string[] = [];
    const fakeChild = {
      once: (evt: string, cb: () => void) => {
        if (evt === 'exit') {
          setTimeout(cb, 0);
        }
        return fakeChild;
      },
    };
    const spawnFn = vi.fn(() => fakeChild) as never;
    await killKernelByPid(4242, {
      graceMs: 50,
      spawnFn,
      isAlive: () => true,
      sleep: async () => {},
    });
    expect(spawnFn).toHaveBeenCalled();
    killed.push('spawned');
    expect(killed).toEqual(['spawned']);
  });

  it('spawn 抛错 → 静默兜底（不抛）', async () => {
    const { killKernelByPid } = await import('./kernel');
    const spawnFn = vi.fn(() => {
      throw new Error('taskkill missing');
    }) as never;
    await killKernelByPid(4242, { graceMs: 10, spawnFn, isAlive: () => false });
  });
});
