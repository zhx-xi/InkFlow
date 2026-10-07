/**
 * #1487 / ADR-066 —— 内核单实例化补全的纯函数契约（vitest node）。
 *
 * 契约来源：
 * - spec f30 §5.5/§5.6（内核自持互斥 + 空闲回收 env 注入）
 * - spec f31 §5.1（tray-only 启动形态）/ §5.3（换 data_dir 先停旧、起新）/ §7 边界 17
 *
 * 纯函数层（`kernel.ts`）：启动形态判定、spawn env 注入、冲突退出码、注册表目录分域、
 * 阻塞实例筛选。真实装配（main.ts 的 spawn/不建窗/停机顺序）另见 main.kernel-singleton.test.ts。
 */
import { describe, expect, it } from 'vitest';
import {
  DEFAULT_KERNEL_IDLE_TIMEOUT_SECONDS,
  IDLE_TIMEOUT_ENV,
  KERNEL_CONFLICT_EXIT_CODE,
  TRAY_ONLY_ENV,
  TRAY_ONLY_FLAG,
  argvHasTrayOnly,
  isKernelConflictExit,
  kernelSpawnEnv,
  registryDirForKind,
  resolveTrayOnly,
  selectConflictingInstance,
  type KernelInstance,
} from './kernel';

const inst = (over: Partial<KernelInstance> = {}): KernelInstance => ({
  kind: 'prod',
  port: 51234,
  pid: 4242,
  version: '0.17.0',
  started_at: '2026-10-07T00:00:00+00:00',
  data_dir: 'C:\\data\\a',
  ...over,
});

describe('resolveTrayOnly / argvHasTrayOnly（spec f31 §5.1 1.3）', () => {
  it('argv 含 --tray-only → true', () => {
    expect(argvHasTrayOnly(['electron', '--tray-only'])).toBe(true);
    expect(resolveTrayOnly(['electron', TRAY_ONLY_FLAG], {})).toBe(true);
  });

  it('env INKFLOW_TRAY_ONLY 真值（不区分大小写/空白）→ true', () => {
    for (const v of ['1', 'true', 'ON', ' yes ']) {
      expect(resolveTrayOnly(['electron'], { [TRAY_ONLY_ENV]: v })).toBe(true);
    }
  });

  it('无 argv / env 假值 → false（常规启动，建主窗口）', () => {
    expect(resolveTrayOnly(['electron'], {})).toBe(false);
    for (const v of ['0', 'false', 'off', '']) {
      expect(resolveTrayOnly(['electron'], { [TRAY_ONLY_ENV]: v })).toBe(false);
    }
  });
});

describe('kernelSpawnEnv（spec f31 §5.4 1.3：注入空闲回收默认值）', () => {
  it('未设置 → 注入默认 1800s + PYTHONIOENCODING', () => {
    const env = kernelSpawnEnv({ PATH: 'x' });
    expect(env[IDLE_TIMEOUT_ENV]).toBe(String(DEFAULT_KERNEL_IDLE_TIMEOUT_SECONDS));
    expect(env.PYTHONIOENCODING).toBe('utf-8');
    expect(env.PATH).toBe('x'); // 既有 env 保留
  });

  it('显式设置（含关闭值 0）→ 原样保留，不覆盖', () => {
    expect(kernelSpawnEnv({ [IDLE_TIMEOUT_ENV]: '2' })[IDLE_TIMEOUT_ENV]).toBe('2');
    expect(kernelSpawnEnv({ [IDLE_TIMEOUT_ENV]: '0' })[IDLE_TIMEOUT_ENV]).toBe('0');
  });
});

describe('isKernelConflictExit（ADR-066 ①）', () => {
  it('仅退出码 3 判为冲突（不进退避重拉链路）', () => {
    expect(isKernelConflictExit(KERNEL_CONFLICT_EXIT_CODE)).toBe(true);
    expect(KERNEL_CONFLICT_EXIT_CODE).toBe(3);
    for (const c of [0, 1, 2, 4, 130, null, undefined]) {
      expect(isKernelConflictExit(c)).toBe(false);
    }
  });
});

describe('registryDirForKind（ADR-066 ③ 按 kind 分域）', () => {
  it('dev → <data_dir>/running（同 data_dir 单内核，worktree 互不干扰）', () => {
    expect(registryDirForKind('dev', 'C:\\d\\kernel.json', 'C:\\appdata')).toBe(
      'C:\\d\\running'
    );
  });

  it('rc / prod → 机器级 <appData>/InkFlow/running（不随 data_dir 变）', () => {
    expect(registryDirForKind('prod', 'C:\\d\\kernel.json', 'C:\\appdata')).toBe(
      'C:\\appdata\\InkFlow\\running'
    );
    expect(registryDirForKind('rc', null, 'C:\\appdata')).toBe('C:\\appdata\\InkFlow\\running');
  });

  it('dev 且无状态文件路径 → null（无法定位 data_dir）', () => {
    expect(registryDirForKind('dev', null, 'C:\\appdata')).toBeNull();
  });
});

describe('selectConflictingInstance（spec f31 §5.3 1B：先停旧、起新）', () => {
  it('kind 相同 + data_dir 不同 → 命中（需停机重启）', () => {
    const found = selectConflictingInstance([inst({ data_dir: 'C:\\other' })], 'prod', 'C:\\mine');
    expect(found?.pid).toBe(4242);
  });

  it('data_dir 相同（大小写/相对归一）→ 不算冲突（交给复用判定）', () => {
    expect(selectConflictingInstance([inst({ data_dir: 'c:\\MINE' })], 'prod', 'C:\\mine')).toBeNull();
  });

  it('rc 条目不阻塞 prod（kind 不同）', () => {
    expect(selectConflictingInstance([inst({ kind: 'rc', data_dir: 'C:\\other' })], 'prod', 'C:\\mine')).toBeNull();
  });

  it('dataDir 未知（null）→ 任一同 kind 存活实例都算阻塞（保守，不并存）', () => {
    expect(selectConflictingInstance([inst({ data_dir: 'C:\\other' })], 'prod', null)?.pid).toBe(4242);
  });

  it('无存活条目 → null（直接 spawn）', () => {
    expect(selectConflictingInstance([], 'prod', 'C:\\mine')).toBeNull();
  });
});
