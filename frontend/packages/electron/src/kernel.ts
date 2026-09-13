/**
 * 主进程纯函数（#78 Electron 壳 + F31 #167 GUI 托盘常驻）：
 * INKFLOW_READY 行解析 / 指数退避 / 内核命令定位 / kernel.json 读写 /
 * 内核复用判定（三态）/ 托盘菜单 label 格式化。
 *
 * 本文件不 import electron——可在 vitest node 环境直接运行
 * （src/kernel.test.ts + src/kernel.state.test.ts 契约）。
 * 契约来源：specs/f19-gui/spec.md §3.2；specs/f31-gui-tray/spec.md §2.1/§5.3/§5.4/§5.6。
 */
import * as fs from 'node:fs';
import * as path from 'node:path';

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
  /** 打包版内核绝对路径（#187 任意 cwd 启动修复）；缺省回落相对路径兼容旧调用/测试 */
  packagedKernelPath?: string;
  /** dev 内核 python 绝对路径（#1153 worktree ENOENT 修复）；缺省回落相对路径兼容旧调用/测试 */
  devKernelPath?: string;
  env?: Record<string, string | undefined>;
}

export interface KernelCommand {
  command: string;
  args: string[];
}

/**
 * 内核命令定位三分支（spec §3.2.1）：
 * ① env.INKFLOW_KERNEL_CMD 存在 → trim 后按空白 split，首段 command 其余 args（优先级最高）；
 * ② isPackaged=true → resources/kernel/inkflow.exe serve --port 0；packagedKernelPath 提供时用绝对路径（#187 任意 cwd 启动）；
 * ③ 默认 dev → backend\.venv\Scripts\python.exe -m inkflow serve --port 0。
 */
export function resolveKernelCommand(opts: ResolveKernelCommandOptions): KernelCommand {
  const envCmd = opts.env?.INKFLOW_KERNEL_CMD;
  if (envCmd !== undefined && envCmd.trim() !== '') {
    const [command, ...args] = envCmd.trim().split(/\s+/);
    return { command, args };
  }
  if (opts.isPackaged) {
    return {
      command: opts.packagedKernelPath ?? 'resources/kernel/inkflow.exe',
      args: ['serve', '--port', '0'],
    };
  }
  return {
    command:
      opts.devKernelPath ??
      'backend\\.venv\\Scripts\\python.exe',
    args: ['-m', 'inkflow', 'serve', '--port', '0'],
  };
}

/**
 * 连续失败阈值（spec §3.2.4 / §3.7 M6，Q2 拍板 B）：连续 6 次失败后停止自动重拉、
 * 弹错误框；退避序列 1+2+4+8+16+30s 封顶全部生效，约 1 分钟自愈窗口。
 */
export const MAX_CONSECUTIVE_FAILURES = 6;

/** kernel.json 状态文件五字段（F30 §2.1 契约，spec f31 §2.1 消费侧） */
export interface KernelState {
  port: number;
  token: string;
  pid: number;
  version: string;
  started_at: string;
}

function isKernelState(value: unknown): value is KernelState {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const record = value as Record<string, unknown>;
  return (
    typeof record.port === 'number' &&
    typeof record.token === 'string' &&
    typeof record.pid === 'number' &&
    typeof record.version === 'string' &&
    typeof record.started_at === 'string'
  );
}

/**
 * 读取 kernel.json 状态文件（spec f31 §2.1 / §5.3）。
 * 文件不存在 / JSON 解析失败 / 非对象 / 缺字段 / 字段类型错 → null（不抛异常）。
 */
export function readKernelStateFile(filePath: string): KernelState | null {
  let raw: string;
  try {
    raw = fs.readFileSync(filePath, 'utf-8');
  } catch {
    return null;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isKernelState(parsed)) {
    return null;
  }
  return parsed;
}

/**
 * 原子写 kernel.json（spec f31 §5.4 / M8）：同目录 `.tmp-<随机>` 临时文件
 * → writeFileSync → renameSync；payload 五字段 = 调用方四字段 + started_at（ISO 字符串）。
 */
export function writeKernelStateFile(
  filePath: string,
  info: { port: number; token: string; pid: number; version: string }
): void {
  const payload: KernelState = {
    ...info,
    started_at: new Date().toISOString(),
  };
  const tmpPath = path.join(
    path.dirname(filePath),
    `.tmp-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
  );
  fs.writeFileSync(tmpPath, JSON.stringify(payload), 'utf-8');
  fs.renameSync(tmpPath, filePath);
}

/**
 * 进程存活判定（spec f31 §5.3）：process.kill(pid, 0) 成功 → true；
 * 抛异常（ESRCH / EPERM 等）→ false。
 */
export function isProcessAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

/**
 * /health 探测（spec f31 §3 / §5.3）：X-InkFlow-Token 头 + AbortSignal.timeout 超时；
 * 非 200 / fetch 网络错误 / 超时 → false（不抛异常）。
 */
export async function probeHealth(port: number, token: string, timeoutMs?: number): Promise<boolean> {
  try {
    const res = await fetch(`http://127.0.0.1:${port}/health`, {
      headers: { 'X-InkFlow-Token': token },
      signal: AbortSignal.timeout(timeoutMs ?? 3_000),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/**
 * 内核复用判定组合（spec f31 §5.3 / §9）：读 kernel.json → pid 存活 → /health 200，
 * 三者全真 = 复用（返回 kernelInfo 四字段）；任一失败 → null。
 */
export async function tryReuseKernel(
  stateFile: string,
  opts?: { healthTimeoutMs?: number }
): Promise<KernelInfo | null> {
  const state = readKernelStateFile(stateFile);
  if (state === null) {
    return null;
  }
  if (!isProcessAlive(state.pid)) {
    return null;
  }
  if (!(await probeHealth(state.port, state.token, opts?.healthTimeoutMs))) {
    return null;
  }
  return { port: state.port, token: state.token, pid: state.pid, version: state.version };
}

/**
 * 托盘菜单内核状态 label（spec f31 §5.6）：
 * 运行中 → `内核状态: 运行中 (port 端口 · pid PID)`；未运行 → `内核状态: 未运行`。
 */
export function formatKernelMenuLabel(info: { port: number; pid: number } | null): string {
  if (info === null) {
    return '内核状态: 未运行';
  }
  return `内核状态: 运行中 (${info.port} 端口 · ${info.pid} PID)`;
}

/** 单个存活内核实例（F30 1.2 §2.4.2 注册表条目；托盘展示用，不含 token） */
export interface KernelInstance {
  kind: 'dev' | 'rc' | 'release';
  port: number;
  pid: number;
  version: string;
  started_at: string;
  data_dir: string;
}

const INSTANCE_KINDS = ['dev', 'rc', 'release'] as const;

function isKernelInstance(value: unknown): value is KernelInstance {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const r = value as Record<string, unknown>;
  return (
    typeof r.kind === 'string' &&
    (INSTANCE_KINDS as readonly string[]).includes(r.kind) &&
    typeof r.port === 'number' &&
    typeof r.pid === 'number' &&
    typeof r.version === 'string' &&
    typeof r.started_at === 'string' &&
    typeof r.data_dir === 'string'
  );
}

/**
 * 读实例注册表（#1153 / ADR-059 ④，spec f31 §2.4）。
 *
 * - 目录不存在 → []（不抛错）
 * - 只收 *.json；JSON 非法 / 字段缺失 / kind 非三值 → 跳过
 * - pid 已死的条目**不返回**，并顺带删除其文件（惰性 GC，无守护进程）
 * - 不返回 token（最小暴露面）
 * - 顺序稳定：started_at 升序，同刻按 pid
 */
export function readInstanceRegistry(dir: string): KernelInstance[] {
  let names: string[];
  try {
    names = fs.readdirSync(dir);
  } catch {
    return [];
  }

  const alive: KernelInstance[] = [];
  for (const name of names) {
    if (!name.endsWith('.json')) {
      continue;
    }
    const filePath = path.join(dir, name);
    const st = readRegistryEntry(filePath);
    if (st === null) {
      // 损坏/不合法 = 垃圾，清理（无法判定归属）
      removeQuietly(filePath);
      continue;
    }
    if (!isProcessAlive(st.pid)) {
      // 惰性 GC：僵尸条目（内核被 taskkill /F 时不会走自己的 finally）
      removeQuietly(filePath);
      continue;
    }
    alive.push(st);
  }

  alive.sort((a, b) =>
    a.started_at === b.started_at ? a.pid - b.pid : a.started_at < b.started_at ? -1 : 1
  );
  return alive;
}

function readRegistryEntry(filePath: string): KernelInstance | null {
  let raw: string;
  try {
    raw = fs.readFileSync(filePath, 'utf-8');
  } catch {
    return null;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isKernelInstance(parsed)) {
    return null;
  }
  // 显式挑字段，绝不透传原对象：注册表文件含 token，
  // 而 KernelInstance 契约不含 token（最小暴露面，spec f31 §2.4）。
  return {
    kind: parsed.kind,
    port: parsed.port,
    pid: parsed.pid,
    version: parsed.version,
    started_at: parsed.started_at,
    data_dir: parsed.data_dir,
  };
}

function removeQuietly(filePath: string): void {
  try {
    fs.unlinkSync(filePath);
  } catch {
    // 已被并发读方清理 / 权限问题：容忍，下轮再试
  }
}

/**
 * 托盘菜单实例区 label（#1153 / ADR-059 ④，spec f31 §5.6.1）。
 *
 * 0/1 实例保持既有单行形态（零回归，对齐 formatKernelMenuLabel）；
 * ≥2 实例渲染「内核实例 (N)」+ 每实例一行（用户诉求：防止不知情多开）。
 */
export function formatInstanceMenuLabel(instances: KernelInstance[]): string[] {
  if (instances.length === 0) {
    return ['内核状态: 未运行'];
  }
  if (instances.length === 1) {
    const only = instances[0];
    return [`内核状态: 运行中 (${only.port} 端口 · ${only.pid} PID)`];
  }
  const kindLabel: Record<KernelInstance['kind'], string> = {
    dev: 'dev',
    rc: 'rc',
    release: '正式',
  };
  return [
    `内核实例 (${instances.length})`,
    ...instances.map(
      (i) =>
        `● ${kindLabel[i.kind]} :${i.port}  pid ${i.pid}  ${i.data_dir}`
    ),
  ];
}
