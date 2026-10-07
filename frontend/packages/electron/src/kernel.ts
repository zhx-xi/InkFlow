/**
 * 主进程纯函数（#78 Electron 壳 + F31 #167 GUI 托盘常驻）：
 * INKFLOW_READY 行解析 / 指数退避 / 内核命令定位 / kernel.json 读写 /
 * 内核复用判定（三态）/ 托盘菜单 label 格式化。
 *
 * 本文件不 import electron——可在 vitest node 环境直接运行
 * （src/kernel.test.ts + src/kernel.state.test.ts 契约）。
 * 契约来源：specs/f19-gui/spec.md §3.2；specs/f31-gui-tray/spec.md §2.1/§5.3/§5.4/§5.6。
 */
import { spawn, type ChildProcess } from 'node:child_process';
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
  /**
   * kernel.json 状态文件绝对路径（#1237）。提供时注入 `--port-file`，与 CLI
   * （`ensure_kernel` → `_default_spawn_cmd`）**同源**，使 GUI 内核也写 kernel.json，
   * 从而被 CLI/MCP/探针发现并复用（单例语义）。缺省不注入（兼容旧调用/测试）。
   */
  stateFile?: string;
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
 * ③ 默认 dev → backend\\.venv\\Scripts\\python.exe -m inkflow serve --port 0。
 *
 * #1237：分支②③（我方自有的 serve 调用形态）在返回前统一追加 `--port-file <stateFile>`
 * （opts.stateFile 提供时），与 CLI 侧 `_default_spawn_cmd` 同源 —— 避免同族路径分叉（用户偏好）。
 *
 * 分支①（env.INKFLOW_KERNEL_CMD）**不注入**：该逃逸口是操作者给定的**任意可执行文件 + 任意参数**
 * （既有契约测试用 `notepad.exe --help` 锁定），其语义不是「inkflow serve」，追加 serve 专属参数
 * 会把 `--help` 变成「`--help` 带一个值」→ 真实场景未定义行为。
 * 该分支下 GUI 不写 kernel.json 属于**逃逸口自身的已知边界**（操作者已接管内核启动），
 * 并在启动时打 warning 以便归因；如需发现通道请勿使用该逃逸口。
 */
export function resolveKernelCommand(opts: ResolveKernelCommandOptions): KernelCommand {
  const { isEscapeHatch, ...base } = resolveKernelCommandBase(opts);
  // 逃逸口：操作者已接管内核启动，参数逐字保留（不追加 serve 专属参数）
  if (isEscapeHatch || opts.stateFile === undefined || opts.stateFile === '') {
    return base;
  }
  return { command: base.command, args: [...base.args, '--port-file', opts.stateFile] };
}

function resolveKernelCommandBase(
  opts: ResolveKernelCommandOptions,
): KernelCommand & { isEscapeHatch: boolean } {
  const envCmd = opts.env?.INKFLOW_KERNEL_CMD;
  if (envCmd !== undefined && envCmd.trim() !== '') {
    const [command, ...args] = envCmd.trim().split(/\s+/);
    return { command, args, isEscapeHatch: true };
  }
  if (opts.isPackaged) {
    return {
      command: opts.packagedKernelPath ?? 'resources/kernel/inkflow.exe',
      args: ['serve', '--port', '0'],
      isEscapeHatch: false,
    };
  }
  return {
    command:
      opts.devKernelPath ??
      'backend\\.venv\\Scripts\\python.exe',
    args: ['-m', 'inkflow', 'serve', '--port', '0'],
    isEscapeHatch: false,
  };
}

/**
 * 连续失败阈值（spec §3.2.4 / §3.7 M6，Q2 拍板 B）：连续 6 次失败后停止自动重拉、
 * 弹错误框；退避序列 1+2+4+8+16+30s 封顶全部生效，约 1 分钟自愈窗口。
 */
export const MAX_CONSECUTIVE_FAILURES = 6;

/** spawn 前的命令解析入参（main.ts 组装 app/process 侧事实，本函数只做纯判定） */
export interface ResolveSpawnCommandOptions {
  isPackaged: boolean;
  env: NodeJS.ProcessEnv;
  /** process.resourcesPath in packaged mode (undefined in tests) */
  resourcesPath?: string;
  repoRoot: string;
  stateFile?: string;
  cwd: string;
}

/**
 * spawn 用命令解析（#1382 从 main.ts 纯搬迁，行为逐字不变）：
 * 按 resolveKernelCommand 三分支定位后，dev 相对命令再以 [repoRoot, cwd] 探测绝对路径；
 * 探测不到则原样返回，交给 spawn 报错 → 进入崩溃拉起/错误对话框。
 */
export function resolveSpawnCommand(opts: ResolveSpawnCommandOptions): KernelCommand {
  const resolved = resolveKernelCommand({
    isPackaged: opts.isPackaged,
    env: opts.env,
    // #187 任意 cwd 启动：打包版传绝对路径（process.resourcesPath 定位 resources/kernel/inkflow.exe）；
    // #192：app.getAppPath() 打包版返回 app.asar 是错误基准（join 出不存在路径 → ENOENT），
    // process.resourcesPath 是标准定位；truthy 守卫兼容测试 mock 缺失该属性（同款防御）
    packagedKernelPath:
      opts.isPackaged && opts.resourcesPath
        ? path.join(opts.resourcesPath, 'kernel', 'inkflow.exe')
        : undefined,
    // #1153：dev 绝对路径（#187 同款；repoRoot 上溯 → worktree 覆盖成立）
    devKernelPath: opts.isPackaged
      ? undefined
      : path.join(opts.repoRoot, 'backend', '.venv', 'Scripts', 'python.exe'),
    stateFile: opts.stateFile, // #1237：注入 --port-file，与 CLI 同源（恢复单例语义）
  });
  if (opts.isPackaged || path.isAbsolute(resolved.command)) {
    return resolved;
  }
  for (const base of [opts.repoRoot, opts.cwd]) {
    const absolute = path.resolve(base, resolved.command);
    if (fs.existsSync(absolute)) {
      return { command: absolute, args: resolved.args };
    }
  }
  return resolved;
}

/** 残留进程回收：taskkill 进程树（Windows 下 child.kill 可能杀不干净子进程） */
export function killProcessTree(child: ChildProcess): void {
  if (child.pid === undefined) {
    return;
  }
  try {
    const killer = spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], {
      windowsHide: true,
      stdio: 'ignore',
    });
    killer.on('error', () => {
      // taskkill 不可用时退化为 child.kill
    });
  } catch {
    // 忽略：退化为 child.kill
  }
  try {
    child.kill();
  } catch {
    // 进程已退出
  }
}

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
export type KernelInstanceKind = 'dev' | 'rc' | 'prod' | 'release';
export interface KernelInstance {
  kind: KernelInstanceKind;
  port: number;
  pid: number;
  version: string;
  started_at: string;
  data_dir: string;
}

/**
 * 可接受的 kind（#1487 / ADR-066 ③ 修正跨语言契约错位）：
 * 后端 `VALID_KINDS = ("dev","rc","prod")`（ADR-059 1.3 已把 release 重命名为 prod），
 * 而本文件此前只认 `release` → **后端写的 prod 条目被静默丢弃**（托盘/重启判据都瞎）。
 * 现同时接受 `prod`（现行）与 `release`（旧版遗留条目兼容）。
 */
const INSTANCE_KINDS = ['dev', 'rc', 'prod', 'release'] as const;

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
  const kindLabel: Record<KernelInstanceKind, string> = {
    dev: 'dev',
    rc: 'rc',
    prod: '正式',
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

// ── #1487 / ADR-066：内核自持互斥冲突 + tray-only + 机器级实例（纯函数，vitest node 可测）──

/** 内核自持存活期互斥被占时的退出码（与 backend `KERNEL_CONFLICT_EXIT_CODE` 同值） */
export const KERNEL_CONFLICT_EXIT_CODE = 3;
/** tray-only 启动开关（argv；同时经 env 冗余注入） */
export const TRAY_ONLY_FLAG = '--tray-only';
/** tray-only env 开关（`--tray-only` 不可用时的等价入口） */
export const TRAY_ONLY_ENV = 'INKFLOW_TRAY_ONLY';
/** 内核空闲回收阈值 env（backend `idle_reclaim.IDLE_TIMEOUT_ENV` 同名） */
export const IDLE_TIMEOUT_ENV = 'INKFLOW_KERNEL_IDLE_TIMEOUT';
/** 客户端拉起内核的默认空闲回收阈值（30 min；backend 同源默认值） */
export const DEFAULT_KERNEL_IDLE_TIMEOUT_SECONDS = 1800;

const TRUTHY_ENV_VALUES = ['1', 'true', 'on', 'yes'];

/** argv 是否显式请求 tray-only（用于 second-instance 分流：tray-only 再来一次不弹窗） */
export function argvHasTrayOnly(argv: readonly string[]): boolean {
  return argv.includes(TRAY_ONLY_FLAG);
}

/**
 * 启动形态判定（spec f31 §5.1 1.3 新增）：`--tray-only` 或 env `INKFLOW_TRAY_ONLY=1`
 * → tray-only（不建主窗口，只创建托盘；点击托盘 → 唤醒/创建主窗口）。
 */
export function resolveTrayOnly(argv: readonly string[], env: NodeJS.ProcessEnv): boolean {
  if (argvHasTrayOnly(argv)) {
    return true;
  }
  return TRUTHY_ENV_VALUES.includes((env[TRAY_ONLY_ENV] ?? '').trim().toLowerCase());
}

/**
 * spawn 内核的 env（spec f31 §5.4 1.3 新增）：注入 UTF-8 与**默认空闲回收阈值**。
 * 已显式设置 `INKFLOW_KERNEL_IDLE_TIMEOUT` 时原样保留（可覆盖/关闭）。
 */
export function kernelSpawnEnv(env: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  const result: NodeJS.ProcessEnv = { ...env, PYTHONIOENCODING: 'utf-8' };
  if (!result[IDLE_TIMEOUT_ENV]) {
    result[IDLE_TIMEOUT_ENV] = String(DEFAULT_KERNEL_IDLE_TIMEOUT_SECONDS);
  }
  return result;
}

/** 子进程退出码是否为「内核自持互斥被占」（ADR-066 ①：据此分流，不进退避重拉链路） */
export function isKernelConflictExit(code: number | null | undefined): boolean {
  return code === KERNEL_CONFLICT_EXIT_CODE;
}

/**
 * 注册表目录（ADR-066 ③ 按 kind 分域）：`dev` → `<data_dir>/running/`；
 * `rc`/`prod` → **机器级** `<appData>/InkFlow/running/`（不随 INKFLOW_DATA_DIR 变）。
 */
export function registryDirForKind(
  kind: string,
  stateFilePath: string | null,
  appDataPath: string
): string | null {
  if (kind === 'dev') {
    return stateFilePath === null ? null : path.join(path.dirname(stateFilePath), 'running');
  }
  return path.join(appDataPath, 'InkFlow', 'running');
}

/** 路径等价判定（Windows 大小写不敏感；两侧 resolve 归一相对/绝对） */
function samePath(a: string, b: string): boolean {
  return path.resolve(a).toLowerCase() === path.resolve(b).toLowerCase();
}

/**
 * 选出「阻塞本次拉起」的机器级既有实例（spec f31 §5.3 1.3 新增，用户拍板 1B）：
 * kind 相同 **且** data_dir 与本次不同 → 需要「先停旧、起新」。
 * 同 data_dir 的实例不在此列（交给复用判定 / 内核互斥兜底）。
 */
export function selectConflictingInstance(
  instances: KernelInstance[],
  kind: string,
  dataDir: string | null
): KernelInstance | null {
  for (const instance of instances) {
    if (instance.kind !== kind) {
      continue;
    }
    if (dataDir !== null && samePath(instance.data_dir, dataDir)) {
      continue;
    }
    return instance;
  }
  return null;
}
