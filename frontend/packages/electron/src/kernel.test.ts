/**
 * 主进程纯函数单元测试契约（#78 Electron 壳，RED 阶段）
 *
 * 契约来源：specs/f19-gui/spec.md §3.2（INKFLOW_READY 行解析 / 指数退避 / 内核命令定位）
 * 被测模块 src/kernel.ts 尚未实现（由 Codex 按本契约实现）——当前运行预期
 * 「Failed to resolve import ./kernel」失败（RED 确认）。
 * 本文件不 import electron（纯函数），vitest node 环境可直接运行。
 */
import { describe, it, expect } from 'vitest';
import {
  parseReadyLine,
  nextBackoffDelayMs,
  resolveKernelCommand,
  MAX_CONSECUTIVE_FAILURES,
} from './kernel';

describe('parseReadyLine（INKFLOW_READY 行解析，spec §3.2.2）', () => {
  it('正常行 → 解析出 {port, token, pid, version}', () => {
    // 真实格式见 backend/src/inkflow/cli/commands/serve.py（#77 交付）
    const line =
      'INKFLOW_READY {"port": 38291, "token": "aB3x...", "pid": 4821, "version": "0.3.0"}';
    expect(parseReadyLine(line)).toEqual({
      port: 38291,
      token: 'aB3x...',
      pid: 4821,
      version: '0.3.0',
    });
  });

  it('非 INKFLOW_READY 前缀的行 → null（普通日志 / 空行 / 裸前缀）', () => {
    expect(
      parseReadyLine('INFO:     Uvicorn running on http://127.0.0.1:38291')
    ).toBeNull();
    expect(parseReadyLine('')).toBeNull();
    expect(parseReadyLine('INKFLOW_READY')).toBeNull();
  });

  it('畸形 JSON → null 且不抛异常', () => {
    expect(() => parseReadyLine('INKFLOW_READY {port: 38291}')).not.toThrow();
    expect(parseReadyLine('INKFLOW_READY {port: 38291}')).toBeNull();
    // JSON 合法但字段类型不符 KernelInfo → null（防实现只 JSON.parse 不校验结构）
    expect(
      parseReadyLine(
        'INKFLOW_READY {"port": "x", "token": 1, "pid": "y", "version": 2}'
      )
    ).toBeNull();
  });

  it('多行输入只匹配含 INKFLOW_READY 的行', () => {
    const multiLine = [
      '2026-08-04 10:00:00 [INFO] loading config...',
      'INKFLOW_READY {"port": 38291, "token": "t0k3n", "pid": 4821, "version": "0.3.0"}',
      '2026-08-04 10:00:01 [INFO] kernel started',
    ].join('\n');
    expect(parseReadyLine(multiLine)).toEqual({
      port: 38291,
      token: 't0k3n',
      pid: 4821,
      version: '0.3.0',
    });
  });
});

describe('nextBackoffDelayMs（指数退避，spec §3.2.4）', () => {
  it('退避序列：failureCount 1..5 → 1s/2s/4s/8s/16s', () => {
    expect(nextBackoffDelayMs(1)).toBe(1000);
    expect(nextBackoffDelayMs(2)).toBe(2000);
    expect(nextBackoffDelayMs(3)).toBe(4000);
    expect(nextBackoffDelayMs(4)).toBe(8000);
    expect(nextBackoffDelayMs(5)).toBe(16000);
  });

  it('第 6 次失败起恒为 30s 封顶（不再增长）', () => {
    expect(nextBackoffDelayMs(6)).toBe(30000);
    expect(nextBackoffDelayMs(7)).toBe(30000);
    expect(nextBackoffDelayMs(10)).toBe(30000);
    expect(nextBackoffDelayMs(100)).toBe(30000);
  });
});

describe('resolveKernelCommand（内核命令定位三分支，spec §3.2.1）', () => {
  it('分支①：env.INKFLOW_KERNEL_CMD 存在 → 值按空白 split，首段为 command、剩余段为 args', () => {
    expect(
      resolveKernelCommand({
        isPackaged: false,
        env: { INKFLOW_KERNEL_CMD: 'C:\\tools\\python.exe' },
      })
    ).toEqual({ command: 'C:\\tools\\python.exe', args: [] });

    expect(
      resolveKernelCommand({
        isPackaged: false,
        env: { INKFLOW_KERNEL_CMD: 'C:\\tools\\python.exe -m inkflow serve' },
      })
    ).toEqual({
      command: 'C:\\tools\\python.exe',
      args: ['-m', 'inkflow', 'serve'],
    });
  });

  it('分支①优先级：env 覆盖优先于 isPackaged', () => {
    expect(
      resolveKernelCommand({
        isPackaged: true,
        env: { INKFLOW_KERNEL_CMD: 'C:\\tools\\python.exe' },
      }).command
    ).toBe('C:\\tools\\python.exe');
  });

  it('分支②：isPackaged=true → resources/kernel/inkflow.exe，args 固定 serve --port 0', () => {
    expect(resolveKernelCommand({ isPackaged: true })).toEqual({
      command: 'resources/kernel/inkflow.exe',
      args: ['serve', '--port', '0'],
    });
    expect(resolveKernelCommand({ isPackaged: true, env: {} })).toEqual({
      command: 'resources/kernel/inkflow.exe',
      args: ['serve', '--port', '0'],
    });
  });

  it('分支③：默认 dev → backend\\.venv\\Scripts\\python.exe -m inkflow serve --port 0', () => {
    expect(resolveKernelCommand({ isPackaged: false })).toEqual({
      command: 'backend\\.venv\\Scripts\\python.exe',
      args: ['-m', 'inkflow', 'serve', '--port', '0'],
    });
    expect(resolveKernelCommand({ isPackaged: false, env: {} })).toEqual({
      command: 'backend\\.venv\\Scripts\\python.exe',
      args: ['-m', 'inkflow', 'serve', '--port', '0'],
    });
  });
});

describe('MAX_CONSECUTIVE_FAILURES（连续失败阈值，spec §3.2.4 / §3.7 M6）', () => {
  it('= 6：连续 6 次失败后停止自动重拉（弹错误对话框；退避序列 1+2+4+8+16+30s 封顶生效，约 1 分钟自愈窗口，Q2 拍板 B）', () => {
    expect(MAX_CONSECUTIVE_FAILURES).toBe(6);
  });
});
