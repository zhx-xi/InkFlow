/**
 * 内核 GUI stderr 落盘模块契约（#1382，从 main.ts 抽出）
 *
 * 背景：GUI（Electron）拉起的内核 stderr 只经 `console.error` 转发 → 进程退出即丢，
 * 前台/打包场景下内核裸 traceback **无文件可查**（结构化日志只记 instrumented 调用、
 * 不含异常栈）。本模块把「stderr → data_dir/logs/kernel-gui.err.log」的落盘装配
 * 从 `main.ts` 抽出（后者恰 900 行，`ci_cd/check_file_length.py` 上限零余量）。
 *
 * 契约：
 * 1. 路径：`<data_dir>/logs/kernel-gui.err.log`；data_dir 为 null / 空串 → null
 *    （调用方据此降级为「仅 console.error」，不得影响内核启动）。
 * 2. 打开：日志目录不存在则**递归创建**；**追加**语义（多轮内核重启不抹掉上一轮痕迹）。
 * 3. 写入：原始字节原样落盘（不转码、不改行）——内核侧 stdout/stderr 已成 UTF-8
 *    （spawn env `PYTHONIOENCODING=utf-8`），落盘文件须严格 UTF-8 可读。
 * 4. 降级：路径不可用 / 写入失败 → 返回 null 或静默跳过，**绝不抛**
 *    （落盘是排障面，不得成为内核启动关键路径的新故障点）。
 * 5. 关闭：幂等（重复 close / close(null) 不抛）。
 *
 * 本文件不 import electron——可在 vitest node 环境直接运行。
 */
import { afterEach, describe, expect, it } from 'vitest';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import * as path from 'node:path';
import {
  KERNEL_GUI_ERR_LOG_NAME,
  appendKernelSpawnBanner,
  appendKernelStderr,
  closeKernelErrLog,
  kernelErrLogPath,
  openKernelErrLog,
} from './kernel-log';

const tempDirs: string[] = [];

function makeTempDir(): string {
  const dir = mkdtempSync(path.join(tmpdir(), 'inkflow-1382-'));
  tempDirs.push(dir);
  return dir;
}

afterEach(() => {
  while (tempDirs.length > 0) {
    rmSync(tempDirs.pop() as string, { recursive: true, force: true });
  }
});

describe('#1382 内核 GUI stderr 落盘模块', () => {
  it('路径契约：<data_dir>/logs/kernel-gui.err.log；data_dir 为 null/空串 → null（调用方降级）', () => {
    const dataDir = path.join('C:', 'Users', 'tester', 'AppData', 'Roaming', 'InkFlow');
    expect(kernelErrLogPath(dataDir)).toBe(path.join(dataDir, 'logs', KERNEL_GUI_ERR_LOG_NAME));
    expect(KERNEL_GUI_ERR_LOG_NAME).toBe('kernel-gui.err.log');
    expect(kernelErrLogPath(null)).toBeNull();
    expect(kernelErrLogPath('')).toBeNull();
  });

  it('打开即递归创建 logs 目录；追加语义：第二轮内核不覆盖第一轮痕迹', () => {
    // 父目录也不存在 → 必须递归创建（data_dir 可能是首启首次落盘）
    const logPath = kernelErrLogPath(path.join(makeTempDir(), 'nested', 'data')) as string;

    const first = openKernelErrLog(logPath);
    expect(first).not.toBeNull();
    appendKernelStderr(first, Buffer.from('第一轮内核输出\n', 'utf-8'));
    closeKernelErrLog(first);

    const second = openKernelErrLog(logPath);
    appendKernelStderr(second, Buffer.from('第二轮内核输出\n', 'utf-8'));
    closeKernelErrLog(second);

    const text = readFileSync(logPath, 'utf-8'); // 严格 UTF-8：抛错即失败
    expect(text).toContain('第一轮内核输出');
    expect(text).toContain('第二轮内核输出');
  });

  it('原始字节原样落盘（不转码/不补时间戳/不改行）：裸 traceback + 中文严格 UTF-8 可读', () => {
    const logPath = kernelErrLogPath(makeTempDir()) as string;
    const log = openKernelErrLog(logPath);
    const chunk = Buffer.from(
      'Traceback (most recent call last):\n数据库完整性错误：唯一约束冲突\n',
      'utf-8'
    );

    appendKernelStderr(log, chunk);
    closeKernelErrLog(log);

    const raw = readFileSync(logPath);
    expect(raw.equals(chunk)).toBe(true); // 逐字节一致：不转码、不改写
    expect(raw.toString('utf-8')).toContain('数据库完整性错误：唯一约束冲突');
  });

  it('降级：目标不可用 → open 返回 null 且不抛；null 句柄上的写入/关闭为静默 no-op', () => {
    // 用「文件」冒充 data_dir，其下无法创建 logs/ 目录
    const blocker = path.join(makeTempDir(), 'not-a-directory');
    writeFileSync(blocker, 'x', 'utf-8');
    const unusable = kernelErrLogPath(path.join(blocker, 'child')) as string;

    const opened = openKernelErrLog(unusable);
    expect(opened).toBeNull();

    expect(() => appendKernelStderr(opened, Buffer.from('内核输出\n', 'utf-8'))).not.toThrow();
    expect(() => appendKernelStderr(null, Buffer.from('内核输出\n', 'utf-8'))).not.toThrow();
    expect(() => appendKernelSpawnBanner(null, { pid: 1, command: 'x', args: [] })).not.toThrow();
    expect(() => closeKernelErrLog(opened)).not.toThrow();
    expect(() => closeKernelErrLog(null)).not.toThrow();
    expect(openKernelErrLog(null)).toBeNull();
  });

  it('关闭幂等：重复 close 不抛，且关闭后写入静默失败（不抛、不复活句柄）', () => {
    const logPath = kernelErrLogPath(makeTempDir()) as string;
    const log = openKernelErrLog(logPath);
    expect(log).not.toBeNull();

    closeKernelErrLog(log);
    expect(() => closeKernelErrLog(log)).not.toThrow();
    expect(() => appendKernelStderr(log, Buffer.from('关闭后输出\n', 'utf-8'))).not.toThrow();
    expect(readFileSync(logPath, 'utf-8')).not.toContain('关闭后输出');
  });

  it('spawn 横幅：ISO 时间戳 + pid + 命令落盘（内核静默时冷启动仍有留痕、可定位重启）', () => {
    const logPath = kernelErrLogPath(makeTempDir()) as string;
    const log = openKernelErrLog(logPath);

    appendKernelSpawnBanner(log, {
      pid: 4242,
      command: 'C:\\tools\\python.exe',
      args: ['-m', 'inkflow', 'serve', '--port', '0'],
    });
    closeKernelErrLog(log);

    const line = readFileSync(logPath, 'utf-8').trimEnd();
    expect(line).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/); // ISO 时间戳
    expect(line).toMatch(/\[gui\] kernel spawn pid=4242 cmd=.*inkflow serve/);
  });

  it('pid 缺失（内核秒退/未拿到 pid）→ 横幅仍落盘，pid 记为 unknown', () => {
    const logPath = kernelErrLogPath(makeTempDir()) as string;
    const log = openKernelErrLog(logPath);

    appendKernelSpawnBanner(log, { pid: undefined, command: 'inkflow.exe', args: ['serve'] });
    closeKernelErrLog(log);

    expect(readFileSync(logPath, 'utf-8')).toMatch(/pid=unknown .*inkflow\.exe serve/);
  });
});
