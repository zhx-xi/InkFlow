/**
 * GUI 拉起的内核 stderr 落盘契约（#1382，吸收 #1388 的编码根治）
 *
 * 缺口（issue #1382）：main.ts 的 spawn stdio 为 `['ignore','pipe','pipe']`，
 * stderr 仅 `console.error` 转发 → 内核进程退出后**无文件留痕**，
 * 前台/打包场景下的裸 traceback 不可取证（结构化日志不含异常栈）。
 *
 * 修复形态（方案 C，最小改动、不破 READY 链）：
 * 保持管道不变，仅把 **stderr** 分流落盘到 `data_dir/logs/kernel-gui.err.log`；
 * 同时给 spawn 注入 `PYTHONIOENCODING=utf-8`，使落盘文件是**单一 UTF-8** 编码
 * （#1388 根因：内核 stdout 走 Windows ANSI 代码页 → 与 UTF-8 事件行混编）。
 *
 * 契约：
 * 1. spawn 形态回归：stdio 仍为 `['ignore','pipe','pipe']`（方案 A 的 fd 形态会让
 *    `child.stdout` 变 null → READY 解析链断，本用例是**反向守护**）；
 * 2. spawn env 注入 `PYTHONIOENCODING=utf-8`，且**保留**既有 env（增量注入，非替换）；
 * 3. 内核 stderr 数据 → 追加写 `data_dir/logs/kernel-gui.err.log`，严格 UTF-8 可读；
 * 4. 每次 spawn 落一条定位横幅（pid + 命令）→ 内核静默的健康冷启动也有留痕；
 * 5. READY 链回归：stdout 的 INKFLOW_READY 行仍被解析并进入 ready 分支；
 * 6. 落盘目标不可用 → 降级：不抛、stderr 仍 console.error 转发、内核照常拉起。
 *
 * ⚠️ 本文件**不**断言「全局 fetch 调用次数」（#888-S3 先例：新增任何 fetch 会连带翻红），
 *    只断言与自身语义相关的 URL 出现（见用例 5）。
 */
import { afterAll, afterEach, beforeAll, describe, expect, it, vi, type Mock } from 'vitest';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import * as path from 'node:path';
import { dialog } from 'electron';
import './main';

type AnyHandler = (...args: unknown[]) => void;

const electronMock = vi.hoisted(() => {
  const createEmitter = () => {
    const handlers = new Map<string, AnyHandler[]>();
    const emitter = {
      on(evt: string, cb: AnyHandler) {
        const arr = handlers.get(evt) ?? [];
        arr.push(cb);
        handlers.set(evt, arr);
        return emitter;
      },
      once(evt: string, cb: AnyHandler) {
        return emitter.on(evt, cb);
      },
      removeListener() {
        return emitter;
      },
      removeAllListeners(evt?: string) {
        if (evt) {
          handlers.delete(evt);
        } else {
          handlers.clear();
        }
        return emitter;
      },
      emit(evt: string, ...args: unknown[]) {
        (handlers.get(evt) ?? []).forEach((cb) => cb(...args));
        return true;
      },
      resume() {},
      pause() {},
      setEncoding() {},
      pipe() {
        return emitter;
      },
    };
    return emitter;
  };

  const windowEventHandlers: Record<string, AnyHandler> = {};
  const webContentsEventHandlers: Record<string, AnyHandler> = {};

  const win = {
    minimize: vi.fn(),
    unmaximize: vi.fn(),
    maximize: vi.fn(),
    close: vi.fn(),
    hide: vi.fn(),
    show: vi.fn(),
    focus: vi.fn(),
    restore: vi.fn(),
    isMinimized: vi.fn(() => false),
    isMaximized: vi.fn(() => false),
    isDestroyed: () => false,
    setTitle: vi.fn(),
    on: vi.fn((evt: string, cb: AnyHandler) => {
      windowEventHandlers[evt] = cb;
    }),
    webContents: {
      on: vi.fn((evt: string, cb: AnyHandler) => {
        webContentsEventHandlers[evt] = cb;
      }),
      send: vi.fn(),
    },
    loadFile: vi.fn(() => Promise.resolve()),
  };

  const childEmitter = createEmitter();
  const fakeChild = {
    pid: 4242 as number | undefined,
    exitCode: null as number | null,
    stdout: createEmitter(),
    stderr: createEmitter(),
    on: childEmitter.on,
    once: childEmitter.once,
    emit: childEmitter.emit,
    removeListener: childEmitter.removeListener,
    removeAllListeners: childEmitter.removeAllListeners,
    kill: vi.fn(() => true),
  };

  const trayInstance = { setContextMenu: vi.fn(), on: vi.fn(), destroy: vi.fn() };

  return {
    __win: win,
    __fakeChild: fakeChild,
    __spawn: vi.fn(() => fakeChild),
    __trayInstance: trayInstance,
    app: {
      isPackaged: false,
      whenReady: vi.fn(() => Promise.resolve()),
      on: vi.fn(),
      exit: vi.fn(),
      quit: vi.fn(),
      requestSingleInstanceLock: vi.fn(() => true),
      setAppUserModelId: vi.fn(),
      getPath: vi.fn(() => 'C:\\Users\\test\\AppData\\Roaming'),
    },
    BrowserWindow: Object.assign(vi.fn(() => win), { getFocusedWindow: vi.fn(() => null) }),
    ipcMain: { on: vi.fn(), handle: vi.fn() },
    Menu: { setApplicationMenu: vi.fn(), buildFromTemplate: vi.fn(() => ({ popup: vi.fn() })) },
    globalShortcut: { register: vi.fn(() => true), unregisterAll: vi.fn() },
    dialog: {
      showMessageBox: vi.fn(() => Promise.resolve({ response: 0 })),
      showOpenDialog: vi.fn(() => Promise.resolve({ canceled: true, filePaths: [] })),
    },
    Tray: vi.fn(() => trayInstance),
    nativeImage: { createFromPath: vi.fn(() => ({ isEmpty: () => false })) },
  };
});

vi.mock('electron', () => electronMock);
vi.mock('node:child_process', () => ({ spawn: electronMock.__spawn }));

const win = electronMock.__win as unknown as { webContents: { send: Mock } };
const fakeChild = electronMock.__fakeChild as unknown as {
  pid: number | undefined;
  stdout: { emit: (evt: string, ...args: unknown[]) => boolean; removeAllListeners: (evt?: string) => unknown };
  stderr: { emit: (evt: string, ...args: unknown[]) => boolean; removeAllListeners: (evt?: string) => unknown };
  removeAllListeners: (evt?: string) => unknown;
};
const spawnMock = electronMock.__spawn as unknown as Mock;
const consoleError = vi.spyOn(console, 'error');

const ERR_LOG_NAME = 'kernel-gui.err.log';
const tempDirs: string[] = [];

function makeTempDir(prefix: string): string {
  const dir = mkdtempSync(path.join(tmpdir(), prefix));
  tempDirs.push(dir);
  return dir;
}

/** 触发一次 INKFLOW_READY（stdout 行格式与 backend cli/commands/serve.py 交付行一致） */
function emitReady(port: number, token: string): void {
  fakeChild.stdout.emit(
    'data',
    Buffer.from(`INKFLOW_READY {"port":${port},"token":"${token}","pid":7,"version":"0.1.0"}\n`)
  );
}

/** 内核 spawn 调用（排除 killProcessTree 的 taskkill），取 [command, args, options] */
function kernelSpawnCall(): unknown[] {
  const call = spawnMock.mock.calls.find((c: unknown[]) => c[0] !== 'taskkill');
  expect(call, '内核未被 spawn').toBeDefined();
  return call as unknown[];
}

/** 换新 main 模块实例并等待 boot 续体跑完（spawnKernel 已挂载 stderr/stdout 监听） */
async function bootWithDataDir(dataDir: string): Promise<void> {
  vi.stubEnv('INKFLOW_DATA_DIR', dataDir);
  spawnMock.mockClear();
  fakeChild.removeAllListeners();
  fakeChild.stdout.removeAllListeners();
  fakeChild.stderr.removeAllListeners();
  delete (globalThis as { __kernelInfo?: unknown }).__kernelInfo;
  vi.resetModules();
  await import('./main');
  await vi.advanceTimersByTimeAsync(1);
}

beforeAll(() => {
  vi.spyOn(console, 'log').mockImplementation(() => {});
  consoleError.mockImplementation(() => {});
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.mocked(dialog.showMessageBox).mockClear();
});

afterAll(() => {
  consoleError.mockRestore();
  vi.restoreAllMocks();
  while (tempDirs.length > 0) {
    rmSync(tempDirs.pop() as string, { recursive: true, force: true });
  }
});

describe('#1382 GUI 内核 stderr 落盘（方案 C：保持管道，stderr 分流落盘）', () => {
  it('spawn 形态回归 + 编码注入：stdio 仍为管道（READY 链依赖），env 增量注入 PYTHONIOENCODING=utf-8', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true })));
    vi.stubEnv('INKFLOW_TEST_SENTINEL_1382', 'sentinel-1382');

    await bootWithDataDir(makeTempDir('inkflow-1382-cfg-'));

    const [, , options] = kernelSpawnCall();
    const opts = options as { stdio?: unknown; env?: Record<string, string | undefined> };

    // ① 反向守护方案 A：stdio 一旦指向 fd，child.stdout 变 null → READY 解析链断
    expect(opts.stdio).toEqual(['ignore', 'pipe', 'pipe']);
    // ② 内核 stdout/stderr 以 UTF-8 写出（#1388 根因根治）
    expect(opts.env?.PYTHONIOENCODING).toBe('utf-8');
    // ③ 增量注入而非替换：既有 env 必须保留（否则内核丢掉 INKFLOW_DATA_DIR / PATH）
    expect(opts.env?.INKFLOW_TEST_SENTINEL_1382).toBe('sentinel-1382');
    expect(opts.env?.INKFLOW_DATA_DIR).toBe(process.env.INKFLOW_DATA_DIR);
  });

  it('stderr → 追加落盘 data_dir/logs/kernel-gui.err.log，且严格 UTF-8 可读（含中文裸 traceback）', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true })));
    const dataDir = makeTempDir('inkflow-1382-stderr-');
    const logPath = path.join(dataDir, 'logs', ERR_LOG_NAME);

    await bootWithDataDir(dataDir);

    fakeChild.stderr.emit('data', Buffer.from('Traceback (most recent call last):\n', 'utf-8'));
    fakeChild.stderr.emit('data', Buffer.from('数据库完整性错误：唯一约束冲突\n', 'utf-8'));

    expect(existsSync(logPath), `stderr 未落盘：${logPath}`).toBe(true);
    const text = readFileSync(logPath, 'utf-8'); // 严格 UTF-8：抛 UnicodeDecodeError 即失败
    expect(text).toContain('Traceback (most recent call last):');
    expect(text).toContain('数据库完整性错误：唯一约束冲突');
    // 语义不变：既有 console.error 转发保留（前台可继续实时看到）
    expect(consoleError).toHaveBeenCalledWith(expect.stringContaining('Traceback (most recent call last):'));
  });

  it('spawn 横幅：冷启动即留痕（pid + 命令），内核静默也非空文件', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true })));
    const dataDir = makeTempDir('inkflow-1382-banner-');
    const logPath = path.join(dataDir, 'logs', ERR_LOG_NAME);

    await bootWithDataDir(dataDir);

    const text = readFileSync(logPath, 'utf-8');
    expect(text).not.toBe('');
    expect(text).toMatch(/pid=4242/);
    expect(text).toMatch(/inkflow/);
  });

  it('READY 链回归：stdout 的 INKFLOW_READY 行仍被解析 → __kernelInfo 注入 + inkflow:ready 推送 + 健康检查启动', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(() => Promise.resolve({ ok: true }));
    vi.stubGlobal('fetch', fetchMock);

    await bootWithDataDir(makeTempDir('inkflow-1382-ready-'));

    emitReady(51234, 't-1382');
    await vi.advanceTimersByTimeAsync(0);

    expect((globalThis as { __kernelInfo?: unknown }).__kernelInfo).toEqual({
      pid: 4242,
      port: 51234,
      token: 't-1382',
    });
    expect(win.webContents.send).toHaveBeenCalledWith('inkflow:ready', {
      baseURL: 'http://127.0.0.1:51234',
      token: 't-1382',
    });
    // 只断言与自身语义相关的 URL（不断言全局 fetch 调用次数：#888-S3 脆弱断言先例）
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('/health'))).toBe(true);
  });

  it('落盘目标不可用 → 降级：boot 不抛、stderr 仍 console.error 转发、内核照常拉起', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true })));
    // 用「文件」冒充 data_dir → <file>/logs 无法创建
    const blocker = path.join(makeTempDir('inkflow-1382-degrade-'), 'not-a-directory');
    writeFileSync(blocker, 'x', 'utf-8');

    await expect(bootWithDataDir(blocker)).resolves.toBeUndefined();

    expect(kernelSpawnCall()[0]).toBeDefined();
    consoleError.mockClear();
    expect(() => fakeChild.stderr.emit('data', Buffer.from('内核输出：stderr 仍须可读\n', 'utf-8'))).not.toThrow();
    expect(consoleError).toHaveBeenCalledWith(expect.stringContaining('stderr 仍须可读'));
  });
});
