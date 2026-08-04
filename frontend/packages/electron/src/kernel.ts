/**
 * 主进程纯函数（#78 Electron 壳）：INKFLOW_READY 行解析 / 指数退避 / 内核命令定位。
 *
 * 本文件不 import electron——可在 vitest node 环境直接运行（src/kernel.test.ts 契约）。
 * 契约来源：specs/f19-gui/spec.md §3.2。
 */

/** 内核就绪信息（backend/src/inkflow/cli/commands/serve.py #77 交付行格式） */
export interface KernelInfo {
  port: number;
  token: string;
  pid: number;
  version: string;
}

/** INKFLOW_READY 行：`INKFLOW_READY {"port":..., "token":..., "pid":..., "version":...}` */
const READY_LINE_PATTERN = /^INKFLOW_READY\s+(\{.*\})\s*$/;

function isKernelInfo(value: unknown): value is KernelInfo {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const record = value as Record<string, unknown>;
  return (
    typeof record.port === 'number' &&
    typeof record.pid === 'number' &&
    typeof record.token === 'string' &&
    typeof record.version === 'string'
  );
}

/**
 * 解析 INKFLOW_READY 行。
 * - 多行输入只取含 INKFLOW_READY 前缀的行；
 * - 畸形 JSON / 字段类型不符 → null 且不抛异常。
 */
export function parseReadyLine(line: string): KernelInfo | null {
  for (const singleLine of line.split(/\r?\n/)) {
    const match = READY_LINE_PATTERN.exec(singleLine);
    if (!match) {
      continue;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(match[1]);
    } catch {
      return null;
    }
    if (!isKernelInfo(parsed)) {
      return null;
    }
    return parsed;
  }
  return null;
}

/**
 * 崩溃拉起指数退避（spec §3.2.4）：1→2→4→8→16s，第 6 次失败起恒为 30s 封顶。
 * failureCount <= 0 按 1 处理（返回 1000ms）。
 */
export function nextBackoffDelayMs(failureCount: number): number {
  const count = Math.max(1, Math.floor(failureCount));
  if (count >= 6) {
    return 30_000;
  }
  return 1000 * 2 ** (count - 1);
}

export interface ResolveKernelCommandOptions {
  isPackaged: boolean;
  env?: Record<string, string | undefined>;
}

export interface KernelCommand {
  command: string;
  args: string[];
}

/**
 * 内核命令定位三分支（spec §3.2.1）：
 * ① env.INKFLOW_KERNEL_CMD 存在 → trim 后按空白 split，首段 command 其余 args（优先级最高）；
 * ② isPackaged=true → resources/kernel/inkflow.exe serve --port 0；
 * ③ 默认 dev → backend\.venv\Scripts\python.exe -m inkflow serve --port 0。
 */
export function resolveKernelCommand(opts: ResolveKernelCommandOptions): KernelCommand {
  const envCmd = opts.env?.INKFLOW_KERNEL_CMD;
  if (envCmd !== undefined && envCmd.trim() !== '') {
    const [command, ...args] = envCmd.trim().split(/\s+/);
    return { command, args };
  }
  if (opts.isPackaged) {
    return { command: 'resources/kernel/inkflow.exe', args: ['serve', '--port', '0'] };
  }
  return {
    command: 'backend\\.venv\\Scripts\\python.exe',
    args: ['-m', 'inkflow', 'serve', '--port', '0'],
  };
}

/**
 * 连续失败阈值（spec §3.2.4 / §3.7 M6，Q2 拍板 B）：连续 6 次失败后停止自动重拉、
 * 弹错误框；退避序列 1+2+4+8+16+30s 封顶全部生效，约 1 分钟自愈窗口。
 */
export const MAX_CONSECUTIVE_FAILURES = 6;
