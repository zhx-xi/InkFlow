/**
 * #1487 / ADR-066 ①④ —— 内核冲突（退出码 3）自愈控制器（spec f31 §5.3 / §7 边界 17）。
 *
 * 从 main.ts 拆出（`ci_cd/check_file_length.py` 900 行门禁：main.ts 触限 → 「超限优先拆分」）。
 * 纯逻辑（不 import electron）：宿主经 `KernelConflictHost` 注入 app / 模块状态 / 计时器。
 *
 * 语义：
 * - `stopConflictingKernel()`：读**机器级注册表**，命中「kind 相同 + data_dir 不同」的存活实例
 *   → `taskkill` 停旧（**先停旧**，1B：不允许跨 data_dir 并存）；
 * - `onKernelConflict(child)`：内核以退出码 3 退出 = 预期内的准入拒绝（机器级限 1 生效），
 *   **不**进退避重拉链路，改走自愈；
 * - `recoverFromConflict()`：同 data_dir 状态文件已就绪 → 复用；否则「先停旧、起新」；
 *   超过 `MAX_RECOVERIES` → 交宿主走既有「启动失败」对话框。
 */
import type { ChildProcess } from 'node:child_process';
import {
  killKernelByPid,
  readInstanceRegistry,
  resolveMachineRegistryDir,
  selectConflictingInstance,
  type KernelInfo,
  type KernelInstance,
} from './kernel';

/** 冲突自愈上限（超出 → 宿主弹「启动失败」；防「停旧起新」死循环） */
export const MAX_CONFLICT_RECOVERIES = 2;
/** 停旧后重拉前的间隔（让 OS 完成进程回收/互斥释放） */
const RESTART_DELAY_MS = 200;
/** taskkill 等待宽限（与 #78 stopKernel 同口径） */
const KILL_GRACE_MS = 3_000;

/** 宿主（main.ts）注入的副作用面（纯逻辑与 electron/模块状态解耦） */
export interface KernelConflictHost {
  /** 该 child 是否仍是当前内核进程（旧进程残留回调需忽略） */
  isCurrentKernel(child: ChildProcess): boolean;
  /** 当前 kernel.json 路径（null = 不可用 → 停机/复用均无从谈起） */
  getStateFilePath(): string | null;
  /** 本次实例 kind（GUI 侧：isPackaged ? 'prod' : 'dev'） */
  getKind(): string;
  /** app.getPath('appData')；不可用（测试 mock）→ null */
  getAppDataPath(): string | null;
  /** 清空当前内核引用（kernelProcess/kernelInfo/pendingReadyPayload） */
  clearKernelRefs(): void;
  /** 停止健康检查/看门狗/重启计时器 */
  clearTimers(): void;
  /** 刷新托盘菜单 */
  rebuildTray(): void;
  /** 登记重启计时器（宿主持有，便于 _1488 统一清理） */
  scheduleRestart(fn: () => void, ms: number): void;
  /** 是否正在退出（stopping） */
  isStopping(): boolean;
  /** 复用既有内核（同 data_dir 状态文件已就绪）→ 命中则已接续健康检查 */
  tryReuseAndAttach(): Promise<KernelInfo | null>;
  /** 拉起内核 */
  spawnKernel(): void;
  /** 自愈超限 → 宿主走既有失败对话框 */
  onGiveUp(): Promise<void>;
  logConflict(pid: number | undefined): void;
  logStopOld(instance: KernelInstance): void;
}

export interface KernelConflictController {
  /** 内核以退出码 3 退出时调用（清理 + 调度自愈） */
  onKernelConflict(child: ChildProcess): void;
  /** 机器级既有实例（不同 data_dir）→ 先停旧；返回是否真的停掉了旧内核 */
  stopConflictingKernel(): Promise<boolean>;
  /** 内核成功就绪 → 自愈计数清零 */
  resetRecoveries(): void;
}

export function createKernelConflictController(
  host: KernelConflictHost
): KernelConflictController {
  let recoveries = 0;

  /** 机器级既有实例（kind 相同 + data_dir 不同）→ taskkill 停旧（1B：不得并存） */
  async function stopConflictingKernel(): Promise<boolean> {
    const stateFilePath = host.getStateFilePath();
    const dir = resolveMachineRegistryDir(
      host.getKind() === 'prod',
      stateFilePath,
      host.getAppDataPath()
    );
    if (dir === null || stateFilePath === null) {
      return false;
    }
    const conflict = selectConflictingInstance(
      readInstanceRegistry(dir),
      host.getKind(),
      dirnameOf(stateFilePath)
    );
    if (conflict === null) {
      return false;
    }
    host.logStopOld(conflict);
    await killKernelByPid(conflict.pid, { graceMs: KILL_GRACE_MS });
    return true;
  }

  /** 自愈：同 data_dir 复用 → 否则「先停旧、起新」；超限 → 交宿主机报错 */
  async function recoverFromConflict(): Promise<void> {
    if (host.isStopping()) {
      return;
    }
    recoveries += 1;
    if (recoveries > MAX_CONFLICT_RECOVERIES) {
      await host.onGiveUp();
      return;
    }
    if (await host.tryReuseAndAttach()) {
      return;
    }
    await stopConflictingKernel();
    host.spawnKernel();
  }

  function onKernelConflict(child: ChildProcess): void {
    if (!host.isCurrentKernel(child)) {
      return;
    }
    host.logConflict(child.pid);
    host.clearTimers();
    host.clearKernelRefs();
    host.rebuildTray();
    if (host.isStopping()) {
      return;
    }
    host.scheduleRestart(() => {
      void recoverFromConflict();
    }, RESTART_DELAY_MS);
  }

  return {
    onKernelConflict,
    stopConflictingKernel,
    resetRecoveries: () => {
      recoveries = 0;
    },
  };
}

/** 取路径的父目录（避免在纯模块里 import node:path 仅为一处调用） */
function dirnameOf(filePath: string): string {
  const normalized = filePath.replace(/[\\/]+$/, '');
  const idx = Math.max(normalized.lastIndexOf('/'), normalized.lastIndexOf('\\'));
  return idx <= 0 ? normalized : normalized.slice(0, idx);
}
