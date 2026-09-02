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

  // ⚠️ #187 rc1 发布缺陷（2026-08-08）：isPackaged 分支硬编码相对路径 → 从任意 cwd
  // 命令行启动 GUI 时 spawn ENOENT（Explorer 双击/快捷方式 cwd=app 目录才正常）。
  // RED 契约：packagedKernelPath 提供时命令必须用绝对路径（主进程传 app.getAppPath() 定位）。
  it('分支②a：isPackaged=true + packagedKernelPath → 使用绝对路径（#187 任意 cwd 启动）', () => {
    expect(
      resolveKernelCommand({
        isPackaged: true,
        packagedKernelPath: 'C:/app/resources/kernel/inkflow.exe',
      })
    ).toEqual({
      command: 'C:/app/resources/kernel/inkflow.exe',
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

/**
 * S3f-T2 契约锁定（contract-s3f-t2 §1 R1，F5 打包冻结黑盒）：resolveKernelCommand 对
 * 「含空格 / 中文安装路径」的数组语义锁定——command 原样保留（含空格/中文），args 恒为
 * 数组元素（spawn 直传免引号转义），防未来「字符串拼接命令 + 手工加引号」回归（f19 M2
 * 手工门禁脚本化；main.ts:404-409 spawn args 数组天然正确的实证契约）。
 */
describe('resolveKernelCommand 空格/中文路径契约锁定（S3f-T2 R1 追加）', () => {
  // S3f-T2 契约锁定（args 数组空格安全，防未来字符串拼接回归）：分支②a packagedKernelPath
  // 为 Program Files（含空格）安装目录 → command 逐字原样保留空格，args 各项不含空格。
  it('packagedKernelPath = C:\\Program Files\\InkFlow v2（含空格）→ command 逐字相等 + args==[serve,--port,0] 各项无空格', () => {
    const packagedKernelPath =
      'C:\\Program Files\\InkFlow v2\\resources\\kernel\\inkflow.exe';
    const resolved = resolveKernelCommand({ isPackaged: true, packagedKernelPath });
    expect(resolved.command).toBe(
      'C:\\Program Files\\InkFlow v2\\resources\\kernel\\inkflow.exe'
    );
    expect(resolved.args).toEqual(['serve', '--port', '0']);
    // args 数组元素不含空格 = spawn 免引号安全的可判定信号（若未来改字符串拼接，
    // 元素会被空格切开/需引号转义 → 本断言红，锁定数组语义）
    expect(resolved.args.every((arg) => !arg.includes(' '))).toBe(true);
    // command 含空格原样保留（引号需求永不出现）
    expect(resolved.command.includes(' ')).toBe(true);
  });

  // S3f-T2 契约锁定（args 数组空格安全，防未来字符串拼接回归）：中文 + 空格混合路径
  // （NSIS 可选安装目录 / 便携解压目录的用户常见形态，f19 M2 ②）→ 同上语义。
  it('packagedKernelPath = D:\\我的 项目（中文 + 空格）→ command 逐字相等 + args==[serve,--port,0] 各项无空格', () => {
    const packagedKernelPath =
      'D:\\我的 项目\\InkFlow\\resources\\kernel\\inkflow.exe';
    const resolved = resolveKernelCommand({ isPackaged: true, packagedKernelPath });
    expect(resolved.command).toBe(
      'D:\\我的 项目\\InkFlow\\resources\\kernel\\inkflow.exe'
    );
    expect(resolved.args).toEqual(['serve', '--port', '0']);
    expect(resolved.args.every((arg) => !arg.includes(' '))).toBe(true);
    expect(resolved.command.includes(' ')).toBe(true);
  });

  // S3f-T2 契约锁定：分支① INKFLOW_KERNEL_CMD 按空白 split 拆「带引号路径」为已知边界
  // （f51 §5.5 声明不扩展逃生口）——command 止于首个空格且保留前导引号（现状语义文档化，
  // 防未来静默「修复」破坏既有语义而未同步 f51 §5.5）。带空格/中文路径应走
  // packagedKernelPath 或 INKFLOW_KERNEL_CMD 无空格路径，勿依赖引号解析。
  it('INKFLOW_KERNEL_CMD 带引号空格路径 → 锁定现状语义：command=首 token（引号不解析，已知边界）', () => {
    expect(
      resolveKernelCommand({
        isPackaged: false,
        env: {
          INKFLOW_KERNEL_CMD:
            '"C:\\tools\\my inkflow\\python.exe" -m inkflow serve',
        },
      })
    ).toEqual({
      command: '"C:\\tools\\my',
      args: ['inkflow\\python.exe"', '-m', 'inkflow', 'serve'],
    });
  });
});
