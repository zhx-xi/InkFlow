/**
 * GUI 内核 stderr 落盘（#1382，方案 C：保持管道，仅 stderr 分流落盘）。
 *
 * 背景：main.ts spawn 的 stdio 为 `['ignore','pipe','pipe']`，stderr 只经
 * `console.error` 转发 → 内核进程退出即丢，前台/打包场景下的裸 traceback
 * **无文件可查**（结构化日志只记 instrumented 调用，不含异常栈）。
 *
 * 契约（与 src/kernel-log.test.ts 同源）：
 * 1. 路径 = `<data_dir>/logs/kernel-gui.err.log`；data_dir 为 null / 空串 → null
 *    （调用方据此降级为「仅 console.error」，不得影响内核启动）；
 * 2. 打开 = 递归建目录 + **追加**（多轮内核重启不抹掉上一轮痕迹）；
 * 3. 写入 = 原始字节原样落盘（不转码、不补时间戳、不改行）——内核侧 stdout/stderr
 *    已强制 UTF-8（spawn env `PYTHONIOENCODING=utf-8`，#1388），落盘文件即单一编码；
 * 4. 降级 = 任何失败都静默（返回 null / 跳过本次写入），**绝不抛**：落盘是排障面，
 *    不得成为内核启动关键路径的新故障点；
 * 5. 关闭 = 幂等（重复 close / close(null) 不抛；关闭后写入静默 no-op）。
 *
 * 本文件不 import electron——可在 vitest node 环境直接运行。
 */
import * as fs from 'node:fs';
import * as path from 'node:path';

/** 落盘文件名（调用方 + 测试共用同一常量，避免字面量漂移） */
export const KERNEL_GUI_ERR_LOG_NAME = 'kernel-gui.err.log';

/**
 * `<dataDir>/logs/kernel-gui.err.log`；dataDir 为 null / 空串 → null
 * （调用方降级为仅 console.error 转发）。
 */
export function kernelErrLogPath(dataDir: string | null): string | null {
  if (!dataDir) {
    return null;
  }
  return path.join(dataDir, 'logs', KERNEL_GUI_ERR_LOG_NAME);
}

/** 已打开的落盘句柄（对外只暴露 filePath，fd 为模块私有状态） */
export interface KernelErrLog {
  readonly filePath: string;
}

/** 句柄内部形态：fd === null 表示已关闭（关闭后写入静默 no-op） */
interface KernelErrLogHandle extends KernelErrLog {
  fd: number | null;
}

function asHandle(log: KernelErrLog | null): KernelErrLogHandle | null {
  if (log === null || !('fd' in log)) {
    return null;
  }
  return log as KernelErrLogHandle;
}

/**
 * 打开（追加模式）落盘句柄：filePath 为 null → null；父目录缺失则**递归创建**；
 * 任何失败（权限 / 路径被文件占用 / 磁盘满）→ null，绝不抛。
 */
export function openKernelErrLog(filePath: string | null): KernelErrLog | null {
  if (!filePath) {
    return null;
  }
  try {
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    const fd = fs.openSync(filePath, 'a');
    const handle: KernelErrLogHandle = { filePath, fd };
    return handle;
  } catch {
    // 降级：调用方仅 console.error 转发
    return null;
  }
}

/**
 * 追加写内核 stderr：句柄为 null / 已关闭 → 静默 no-op；
 * Buffer **逐字节原样**落盘、string 按 UTF-8 编码；任何失败（含句柄已失效）静默吞掉。
 */
export function appendKernelStderr(log: KernelErrLog | null, chunk: Buffer | string): void {
  const handle = asHandle(log);
  const fd = handle?.fd;
  if (fd === undefined || fd === null) {
    return;
  }
  try {
    if (typeof chunk === 'string') {
      fs.writeSync(fd, chunk, null, 'utf-8');
    } else {
      fs.writeSync(fd, chunk);
    }
  } catch {
    // 落盘失败静默：排障面不得反向阻断内核
  }
}

/**
 * spawn 定位横幅（一条一行）：
 * `<ISO 时间戳> [gui] kernel spawn pid=<pid|unknown> cmd=<command + ' ' + args.join(' ')>`
 * —— 内核静默的健康冷启动也有留痕，且可据 pid/命令定位重启。
 * （时间戳**不加**方括号：契约测试锚定行首 `^\d{4}-\d{2}-\d{2}T...`，见 kernel-log.test.ts。）
 */
export function appendKernelSpawnBanner(
  log: KernelErrLog | null,
  info: { pid: number | undefined; command: string; args: readonly string[] }
): void {
  const pidLabel = info.pid !== undefined ? String(info.pid) : 'unknown';
  const cmdline = [info.command, ...info.args].join(' ');
  appendKernelStderr(log, `${new Date().toISOString()} [gui] kernel spawn pid=${pidLabel} cmd=${cmdline}\n`);
}

/** 关闭句柄：null / 已关闭 → no-op；幂等，绝不抛（关闭后写入静默失败）。 */
export function closeKernelErrLog(log: KernelErrLog | null): void {
  const handle = asHandle(log);
  if (handle === null || handle.fd === null) {
    return;
  }
  try {
    fs.closeSync(handle.fd);
  } catch {
    // 已关闭 / 句柄失效：容忍
  } finally {
    handle.fd = null;
  }
}
