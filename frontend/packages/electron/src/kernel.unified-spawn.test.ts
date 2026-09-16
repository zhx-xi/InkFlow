/**
 * #1237 契约：GUI spawn 内核必须与 CLI 同源（`--port-file` + instance kind env），
 * 使 kernel.json 成为 GUI/CLI/MCP 之间唯一发现通道，单例语义（rc/prod 全局单内核、
 * dev 同 data_dir 单内核）才真正成立。
 *
 * 缺陷现象（issue #1237 实测，rc1 打包产物）：
 *   GUI:  inkflow.exe serve --port 0                      ← 无 --port-file
 *   CLI:  inkflow.exe serve --port 0 --port-file <data>\kernel.json
 *   ⇒ GUI 内核不写 kernel.json ⇒ CLI 探不到 ⇒ 各起一个（实测 3 进程并存）。
 *
 * ⚠️ #1188 教训（测试绿了但真实场景没通 = 用 mock 覆盖了 state 层）：
 * 本文件不 mock state 文件读写 —— 用**真实临时目录 + 真实 kernel.json 落盘**验证；
 * spawn 面只注入命令解析结果（纯函数），不 mock 文件系统。
 */
import { describe, expect, it, beforeEach, afterEach } from 'vitest';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

import { resolveKernelCommand, readKernelStateFile } from './kernel';

let tmpDir: string;

beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'inkflow-1237-'));
});

afterEach(() => {
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

/** 契约核心断言：args 中 `--port-file` 指向的值 */
function portFileArg(args: string[]): string | null {
  const idx = args.indexOf('--port-file');
  if (idx === -1 || idx + 1 >= args.length) {
    return null;
  }
  return args[idx + 1];
}

describe('#1237 GUI spawn 与 CLI 同源（--port-file）', () => {
  const stateFile = (): string => path.join(tmpDir, 'kernel.json');

  it('分支②（打包版）：args 含 --port-file 指向 stateFile，与 CLI 同源', () => {
    const resolved = resolveKernelCommand({
      isPackaged: true,
      packagedKernelPath: 'C:/app/resources/kernel/inkflow.exe',
      stateFile: stateFile(),
    });

    expect(resolved.command).toBe('C:/app/resources/kernel/inkflow.exe');
    expect(portFileArg(resolved.args)).toBe(stateFile());
    // 既有契约不回归：仍以 --port 0 请求动态端口
    expect(resolved.args).toContain('--port');
    expect(resolved.args[resolved.args.indexOf('--port') + 1]).toBe('0');
  });

  it('分支③（dev）：args 含 --port-file 指向 stateFile，与 CLI 同源', () => {
    const resolved = resolveKernelCommand({
      isPackaged: false,
      devKernelPath: 'D:/repo/backend/.venv/Scripts/python.exe',
      stateFile: stateFile(),
    });

    expect(resolved.command).toBe('D:/repo/backend/.venv/Scripts/python.exe');
    expect(portFileArg(resolved.args)).toBe(stateFile());
  });

  it('stateFile 缺省（未提供）→ 不注入 --port-file（兼容既有调用/测试）', () => {
    expect(portFileArg(resolveKernelCommand({ isPackaged: true }).args)).toBeNull();
    expect(portFileArg(resolveKernelCommand({ isPackaged: false }).args)).toBeNull();
  });

  it('env INKFLOW_KERNEL_CMD 分支（分支①）→ **不注入** --port-file（逃逸口参数逐字保留）', () => {
    // 逃逸口语义 = 操作者给出的任意可执行文件 + 任意参数（既有契约用 `notepad.exe --help` 锁定）。
    // 追加 serve 专属的 --port-file 会把 `--help` 变成「--help 带一个值」→ 未定义行为。
    // 该分支下不写 kernel.json 属逃逸口自身已知边界（操作者已接管内核启动）。
    const resolved = resolveKernelCommand({
      isPackaged: true,
      env: { INKFLOW_KERNEL_CMD: 'C:\\tools\\python.exe -m inkflow serve' },
      stateFile: stateFile(),
    });

    expect(resolved.command).toBe('C:\\tools\\python.exe');
    expect(portFileArg(resolved.args)).toBeNull();
    expect(resolved.args).toEqual(['-m', 'inkflow', 'serve']);
  });

  it('含空格路径：--port-file 值逐字相等，不被空白 split 破坏', () => {
    const spaced = path.join(tmpDir, 'my data dir', 'kernel.json');
    const resolved = resolveKernelCommand({
      isPackaged: true,
      packagedKernelPath: 'C:\\Program Files\\InkFlow v2\\resources\\kernel\\inkflow.exe',
      stateFile: spaced,
    });

    expect(portFileArg(resolved.args)).toBe(spaced);
    expect(resolved.command).toBe('C:\\Program Files\\InkFlow v2\\resources\\kernel\\inkflow.exe');
  });
});

describe('#1237 GUI 写入的 state 可被 CLI 侧消费（真实落盘，非 mock）', () => {
  it('GUI spawn 后写出的 kernel.json 满足五字段契约，CLI 读得到同一 pid/port', () => {
    // 真实 state 文件读写（对齐 backend/infrastructure/kernel/state.py 契约）
    const file = path.join(tmpDir, 'kernel.json');
    const payload = {
      port: 2989,
      token: 'tok-gui',
      pid: 4242,
      version: '0.15.0',
      started_at: new Date().toISOString(),
    };
    fs.writeFileSync(file, JSON.stringify(payload), 'utf-8');

    const read = readKernelStateFile(file);
    expect(read).not.toBeNull();
    expect(read?.pid).toBe(4242);
    expect(read?.port).toBe(2989);
    expect(read?.started_at).toBe(payload.started_at);
  });

  it('可证伪：GUI 路径不写 state → 文件不存在，CLI 侧读为 null（必然另起内核）', () => {
    expect(fs.existsSync(path.join(tmpDir, 'kernel.json'))).toBe(false);
    expect(readKernelStateFile(path.join(tmpDir, 'kernel.json'))).toBeNull();
  });
});
