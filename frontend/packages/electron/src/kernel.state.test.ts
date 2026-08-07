/**
 * 主进程内核状态纯函数测试契约（F31 #167 GUI 托盘常驻，RED 阶段）
 *
 * 契约来源：specs/f31-gui-tray/spec.md
 *   - §2.1 kernel.json 五字段 {port, token, pid, version, started_at} 消费契约
 *     （读取规则：文件不存在 / JSON 解析失败 → 视为无内核）
 *   - §5.3 内核复用判定（Node 侧三态：读文件 → 进程存活 → /health 200，
 *     三者全真 = 复用；任一失败 → null）
 *   - §5.4 GUI spawn 内核后原子写 kernel.json（临时文件 + rename 语义，五字段齐全，
 *     started_at 为 ISO 字符串）
 *   - §5.6 内核状态菜单 label 格式化（`内核状态: 运行中 (port 端口 · pid PID)` /
 *     `内核状态: 未运行`）
 *   - §9 测试策略：kernel.json 读写（正常/损坏/缺字段/原子写）；进程存活判定
 *     （存在/不存在）；/health 探测（200/非 200/超时）；复用判定组合（四分支）
 *
 * 被测模块 src/kernel.ts 新增纯函数（RED 阶段尚不存在——本文件以 namespace import
 * 引用，缺导出时调用抛 TypeError「kernel.xxx is not a function」= 预期 RED 形态）：
 *   readKernelStateFile / writeKernelStateFile / isProcessAlive / probeHealth /
 *   tryReuseKernel / formatKernelMenuLabel
 *
 * ⚠️ 复用判定组合的设计说明：tryReuseKernel 对 readKernelStateFile / isProcessAlive /
 * probeHealth 的调用是模块内直接引用——vitest（同 Jest）无法拦截模块内部调用
 * （vi.mock 只能替换导出绑定，内部引用仍指向原函数）。故四分支采用**真实集成式**
 * 实现：真实临时 kernel.json + 真实 node:http /health server（X-InkFlow-Token 校验）+
 * 真实 process.pid / 超大 pid 探测——分支覆盖与「mock 三函数」等价，且无 mock 脆弱性。
 *
 * 本文件不 import electron（纯函数），vitest node 环境可直接运行。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { createServer, type Server, type IncomingMessage, type ServerResponse } from 'node:http';
import * as kernel from './kernel';

/** kernel.json 五字段（F30 §2.1 契约；本地类型——kernel.ts 尚未导出 KernelState） */
interface KernelState {
  port: number;
  token: string;
  pid: number;
  version: string;
  started_at: string;
}

/** 每个用例独立临时目录（用后即焚） */
function makeTempDir(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'inkflow-kernel-state-'));
}

function cleanupTempDir(dir: string): void {
  fs.rmSync(dir, { recursive: true, force: true });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('readKernelStateFile（kernel.json 读取，spec §2.1 / §5.3）', () => {
  it('文件不存在 → null（视为无内核）', () => {
    const dir = makeTempDir();
    try {
      expect(kernel.readKernelStateFile(path.join(dir, 'nonexistent.json'))).toBeNull();
    } finally {
      cleanupTempDir(dir);
    }
  });

  it('JSON 损坏（解析失败）→ null 且不抛异常', () => {
    const dir = makeTempDir();
    try {
      const file = path.join(dir, 'kernel.json');
      fs.writeFileSync(file, '{"port": 51234, oops', 'utf-8');
      expect(() => kernel.readKernelStateFile(file)).not.toThrow();
      expect(kernel.readKernelStateFile(file)).toBeNull();
    } finally {
      cleanupTempDir(dir);
    }
  });

  it('JSON 合法但非对象（裸数字）→ null', () => {
    const dir = makeTempDir();
    try {
      const file = path.join(dir, 'kernel.json');
      fs.writeFileSync(file, '42', 'utf-8');
      expect(kernel.readKernelStateFile(file)).toBeNull();
    } finally {
      cleanupTempDir(dir);
    }
  });

  it('五字段缺一（缺 started_at）→ null', () => {
    const dir = makeTempDir();
    try {
      const file = path.join(dir, 'kernel.json');
      fs.writeFileSync(
        file,
        JSON.stringify({ port: 51234, token: 't0k3n', pid: 4242, version: '0.5.0' }),
        'utf-8'
      );
      expect(kernel.readKernelStateFile(file)).toBeNull();
    } finally {
      cleanupTempDir(dir);
    }
  });

  it('字段类型错（port 为字符串）→ null', () => {
    const dir = makeTempDir();
    try {
      const file = path.join(dir, 'kernel.json');
      fs.writeFileSync(
        file,
        JSON.stringify({
          port: '51234',
          token: 't0k3n',
          pid: 4242,
          version: '0.5.0',
          started_at: '2026-08-08T00:00:00.000Z',
        }),
        'utf-8'
      );
      expect(kernel.readKernelStateFile(file)).toBeNull();
    } finally {
      cleanupTempDir(dir);
    }
  });

  it('五字段齐全 → 返回完整 KernelState 对象', () => {
    const dir = makeTempDir();
    try {
      const file = path.join(dir, 'kernel.json');
      const state: KernelState = {
        port: 51234,
        token: 't0k3n',
        pid: 4242,
        version: '0.5.0',
        started_at: '2026-08-08T00:00:00.000Z',
      };
      fs.writeFileSync(file, JSON.stringify(state), 'utf-8');
      expect(kernel.readKernelStateFile(file)).toEqual(state);
    } finally {
      cleanupTempDir(dir);
    }
  });
});

describe('writeKernelStateFile（原子写，spec §5.4 / M8）', () => {
  it('写入后可读且五字段齐全（started_at 为 ISO 字符串）', () => {
    const dir = makeTempDir();
    try {
      const file = path.join(dir, 'kernel.json');
      kernel.writeKernelStateFile(file, { port: 51234, token: 't0k3n', pid: 4242, version: '0.5.0' });
      const parsed = JSON.parse(fs.readFileSync(file, 'utf-8')) as KernelState;
      expect(parsed.port).toBe(51234);
      expect(parsed.token).toBe('t0k3n');
      expect(parsed.pid).toBe(4242);
      expect(parsed.version).toBe('0.5.0');
      expect(typeof parsed.started_at).toBe('string');
      expect(Number.isNaN(Date.parse(parsed.started_at))).toBe(false);
    } finally {
      cleanupTempDir(dir);
    }
  });

  it('原子写语义：完成后目录内无临时文件残留（临时文件 + rename）', () => {
    const dir = makeTempDir();
    try {
      const file = path.join(dir, 'kernel.json');
      kernel.writeKernelStateFile(file, { port: 1, token: 'a', pid: 2, version: '0.5.0' });
      expect(fs.readdirSync(dir)).toEqual(['kernel.json']);
    } finally {
      cleanupTempDir(dir);
    }
  });

  it('重复写入覆盖旧值（后写胜出）', () => {
    const dir = makeTempDir();
    try {
      const file = path.join(dir, 'kernel.json');
      kernel.writeKernelStateFile(file, { port: 1, token: 'old', pid: 2, version: '0.1.0' });
      kernel.writeKernelStateFile(file, { port: 51234, token: 'new', pid: 4242, version: '0.5.0' });
      const parsed = JSON.parse(fs.readFileSync(file, 'utf-8')) as KernelState;
      expect(parsed.token).toBe('new');
      expect(parsed.port).toBe(51234);
    } finally {
      cleanupTempDir(dir);
    }
  });
});

describe('isProcessAlive（进程存活判定，spec §5.3 / §9）', () => {
  it('存在的 pid（process.pid）→ true', () => {
    expect(kernel.isProcessAlive(process.pid)).toBe(true);
  });

  it('不存在的 pid（超大）→ false（process.kill(pid, 0) 捕获 ESRCH）', () => {
    expect(kernel.isProcessAlive(99999999)).toBe(false);
  });
});

describe('probeHealth（/health 探测，spec §3 / §5.3 / §9）', () => {
  it('200 → true，且 fetch 带 X-InkFlow-Token 头与 AbortSignal 超时', async () => {
    const fetchMock = vi.fn(() => Promise.resolve({ ok: true, status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(kernel.probeHealth(51234, 't0k3n')).resolves.toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:51234/health',
      expect.objectContaining({
        headers: { 'X-InkFlow-Token': 't0k3n' },
        signal: expect.any(AbortSignal),
      })
    );
  });

  it('非 200 → false', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: false, status: 503 })));
    await expect(kernel.probeHealth(51234, 't0k3n')).resolves.toBe(false);
  });

  it('网络错误（fetch reject）→ false 且不抛异常', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('ECONNREFUSED'))));
    await expect(kernel.probeHealth(51234, 't0k3n')).resolves.toBe(false);
  });

  it('超时（AbortSignal.timeout 触发 abort）→ false', async () => {
    const fetchMock = vi.fn(
      (_url: string, init: { signal: AbortSignal }) =>
        new Promise((_resolve, reject) => {
          init.signal.addEventListener('abort', () => {
            reject(new DOMException('The operation was aborted.', 'AbortError'));
          });
        })
    );
    vi.stubGlobal('fetch', fetchMock);
    await expect(kernel.probeHealth(51234, 't0k3n', 100)).resolves.toBe(false);
  }, 10_000);
});

describe('tryReuseKernel（复用判定组合，spec §5.3 / §9）', () => {
  let server: Server | null = null;
  let dir: string;

  /** 真实 /health server：X-InkFlow-Token 匹配才返回 200（= 活） */
  async function startHealthServer(token = 't0k3n'): Promise<number> {
    server = createServer((req: IncomingMessage, res: ServerResponse) => {
      if (req.headers['x-inkflow-token'] === token) {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ status: 'ok', version: '0.5.0' }));
      } else {
        res.writeHead(401);
        res.end();
      }
    });
    await new Promise<void>((resolve) => server!.listen(0, '127.0.0.1', resolve));
    const address = server!.address();
    if (address === null || typeof address === 'string') {
      throw new Error('unexpected server address');
    }
    return address.port;
  }

  /** 取一个已释放的端口（health 失败分支：连接被拒） */
  async function getClosedPort(): Promise<number> {
    const s = createServer();
    await new Promise<void>((resolve) => s.listen(0, '127.0.0.1', resolve));
    const address = s.address();
    if (address === null || typeof address === 'string') {
      throw new Error('unexpected server address');
    }
    const port = address.port;
    await new Promise<void>((resolve) => s.close(() => resolve()));
    return port;
  }

  beforeEach(() => {
    dir = makeTempDir();
  });

  afterEach(() => {
    if (server) {
      server.close();
      server = null;
    }
    cleanupTempDir(dir);
  });

  it('全真组合：文件存在 + pid 存活 + /health 200 → 返回内核信息 {port,token,pid,version}', async () => {
    const port = await startHealthServer();
    const file = path.join(dir, 'kernel.json');
    kernel.writeKernelStateFile(file, { port, token: 't0k3n', pid: process.pid, version: '0.5.0' });
    await expect(kernel.tryReuseKernel(file)).resolves.toEqual({
      port,
      token: 't0k3n',
      pid: process.pid,
      version: '0.5.0',
    });
  });

  it('读失败：文件不存在 → null', async () => {
    await expect(kernel.tryReuseKernel(path.join(dir, 'nonexistent.json'))).resolves.toBeNull();
  });

  it('进程死：pid 不存在（崩溃残留）→ null', async () => {
    const file = path.join(dir, 'kernel.json');
    kernel.writeKernelStateFile(file, { port: 1, token: 't0k3n', pid: 99999999, version: '0.5.0' });
    await expect(kernel.tryReuseKernel(file)).resolves.toBeNull();
  });

  it('health 失败：pid 存活但 /health 连接被拒 → null', async () => {
    const closedPort = await getClosedPort();
    const file = path.join(dir, 'kernel.json');
    kernel.writeKernelStateFile(file, {
      port: closedPort,
      token: 't0k3n',
      pid: process.pid,
      version: '0.5.0',
    });
    await expect(kernel.tryReuseKernel(file)).resolves.toBeNull();
  });
});

describe('formatKernelMenuLabel（托盘菜单内核状态 label，spec §5.6）', () => {
  it('运行中 → `内核状态: 运行中 (port 端口 · pid PID)`', () => {
    expect(kernel.formatKernelMenuLabel({ port: 51234, pid: 4242 })).toBe(
      '内核状态: 运行中 (51234 端口 · 4242 PID)'
    );
  });

  it('未运行（null）→ `内核状态: 未运行`', () => {
    expect(kernel.formatKernelMenuLabel(null)).toBe('内核状态: 未运行');
  });
});
