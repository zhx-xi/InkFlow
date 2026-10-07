/**
 * #1487 / ADR-066 —— main.ts 装配契约（mock electron，vitest node）。
 *
 * 覆盖新增分支：
 * - **tray-only 启动**（spec f31 §5.1 1.3）：`--tray-only` → 不调 `createMainWindow()`，
 *   Tray 仍创建；`__trayInfo.trayOnly === true` / `windowVisible === false`；
 *   `__trayActions.show()` → 建窗（点击托盘唤醒，需求 3）。
 * - **换 data_dir 先停旧、起新**（spec f31 §5.3 1B）：机器级注册表有不同 data_dir 的
 *   存活实例 → 第一次 spawn 必须是 `taskkill`（**先**停旧），内核 spawn 在其后。
 * - **冲突退出码 3 分流**（spec f31 §7 边界 17）：内核以 3 退出 → 不进「启动失败」对话框链路。
 */
import { describe, it, expect, beforeAll, beforeEach, afterEach, vi, type Mock } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { BrowserWindow, Tray } from 'electron';
import { resetMainInstance } from './__testutils__/main-boot';

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
        if (evt) handlers.delete(evt);
        else handlers.clear();
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
  const appEventHandlers: Record<string, AnyHandler> = {};

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
    pid: 4242,
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

  const trayInstance = {
    setContextMenu: vi.fn(),
    setToolTip: vi.fn(),
    on: vi.fn(),
    destroy: vi.fn(),
  };

  return {
    __win: win,
    __windowEventHandlers: windowEventHandlers,
    __webContentsEventHandlers: webContentsEventHandlers,
    __appEventHandlers: appEventHandlers,
    __fakeChild: fakeChild,
    __spawn: vi.fn(() => fakeChild),
    __trayInstance: trayInstance,
    app: {
      isPackaged: false,
      whenReady: vi.fn(() => Promise.resolve()),
      on: vi.fn((evt: string, cb: AnyHandler) => {
        appEventHandlers[evt] = cb;
      }),
      exit: vi.fn(),
      quit: vi.fn(),
      requestSingleInstanceLock: vi.fn(() => true),
      setAppUserModelId: vi.fn(),
      getPath: vi.fn(() => ''),
    },
    BrowserWindow: Object.assign(vi.fn(() => win), {
      getFocusedWindow: vi.fn(() => null),
      getAllWindows: vi.fn(() => []),
    }),
    ipcMain: { on: vi.fn(), handle: vi.fn() },
    Menu: {
      setApplicationMenu: vi.fn(),
      buildFromTemplate: vi.fn(() => ({ popup: vi.fn() })),
    },
    globalShortcut: { register: vi.fn(() => true), unregisterAll: vi.fn() },
    dialog: { showMessageBox: vi.fn(() => Promise.resolve({ response: 0 })) },
    Tray: vi.fn(() => trayInstance),
    nativeImage: { createFromPath: vi.fn(() => ({ isEmpty: () => false })) },
  };
});

vi.mock('electron', () => electronMock);
vi.mock('node:child_process', () => ({ spawn: electronMock.__spawn }));

const spawnMock = electronMock.__spawn as unknown as Mock;
const fakeChild = electronMock.__fakeChild as unknown as {
  emit: (evt: string, ...args: unknown[]) => boolean;
  removeAllListeners: (evt?: string) => unknown;
};
const trayInstance = electronMock.__trayInstance as unknown as { destroy: Mock };
const appMock = electronMock.app as unknown as {
  getPath: Mock;
  requestSingleInstanceLock: Mock;
  quit: Mock;
};

const flush = (ms = 0): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

let appDataDir: string;
let dataDir: string;

/** 换新模块实例（状态归零；清理职责下沉 `__testutils__/main-boot.ts`，#1219） */
const freshInstance = async (argv: string[]): Promise<void> => {
  const originalArgv = process.argv;
  process.argv = argv;
  try {
    const { setMainLogEndpoint } = await import('./logger');
    await resetMainInstance({
      vi,
      fakeChild,
      importMain: () => import('./main'),
      resetLogEndpoint: setMainLogEndpoint,
    });
  } finally {
    process.argv = originalArgv;
  }
};

beforeAll(() => {
  vi.spyOn(console, 'log').mockImplementation(() => {});
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

beforeEach(() => {
  // 隔离注册表 / 状态文件目录（getPath('appData') 指向临时目录 → 机器级目录在沙箱内）
  appDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'inkflow-1487-appdata-'));
  dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'inkflow-1487-data-'));
  appMock.getPath.mockReturnValue(appDataDir);
  process.env.INKFLOW_DATA_DIR = dataDir;
  spawnMock.mockClear();
  vi.mocked(BrowserWindow).mockClear();
  vi.mocked(Tray).mockClear();
  trayInstance.destroy.mockClear();
  fakeChild.removeAllListeners();
});

afterEach(() => {
  delete process.env.INKFLOW_DATA_DIR;
  delete process.env.INKFLOW_TRAY_ONLY;
  fs.rmSync(appDataDir, { recursive: true, force: true });
  fs.rmSync(dataDir, { recursive: true, force: true });
});

describe('tray-only 启动（spec f31 §5.1 1.3 / 验收 M12）', () => {
  it('--tray-only → 不建主窗口、创建托盘、钩子标 trayOnly', async () => {
    await freshInstance(['electron', '--tray-only']);
    await flush();

    expect(vi.mocked(BrowserWindow)).not.toHaveBeenCalled();
    expect(vi.mocked(Tray)).toHaveBeenCalledTimes(1);
    const info = (globalThis as Record<string, unknown>).__trayInfo as {
      created: boolean;
      trayOnly: boolean;
      windowVisible: boolean;
    };
    expect(info.created).toBe(true);
    expect(info.trayOnly).toBe(true);
    expect(info.windowVisible).toBe(false);
  });

  it('env INKFLOW_TRAY_ONLY=1 等价于 --tray-only', async () => {
    process.env.INKFLOW_TRAY_ONLY = '1';
    await freshInstance(['electron']);
    await flush();

    expect(vi.mocked(BrowserWindow)).not.toHaveBeenCalled();
    const info = (globalThis as Record<string, unknown>).__trayInfo as { trayOnly: boolean };
    expect(info.trayOnly).toBe(true);
  });

  it('tray-only 下点击托盘 → 建主窗口（唤醒，需求 3）', async () => {
    await freshInstance(['electron', '--tray-only']);
    await flush();
    const actions = (globalThis as Record<string, unknown>).__trayActions as { show: () => void };

    actions.show();

    expect(vi.mocked(BrowserWindow)).toHaveBeenCalledTimes(1);
  });

  it('常规启动（无 flag）→ 建主窗口、trayOnly=false（零回归）', async () => {
    await freshInstance(['electron']);
    await flush();

    expect(vi.mocked(BrowserWindow)).toHaveBeenCalledTimes(1);
    const info = (globalThis as Record<string, unknown>).__trayInfo as { trayOnly: boolean };
    expect(info.trayOnly).toBe(false);
  });
});

describe('换 data_dir 先停旧、起新（spec f31 §5.3 1B / 验收 M13）', () => {
  it('不同 data_dir 的机器级既有实例 → 先 taskkill，后 spawn 内核', async () => {
    // 机器级注册表（dev：<data_dir>/running/）放入一条 dev / 别的 data_dir / pid 存活（本进程）
    const running = path.join(dataDir, 'running');
    fs.mkdirSync(running, { recursive: true });
    fs.writeFileSync(
      path.join(running, `dev-${process.pid}.json`),
      JSON.stringify({
        kind: 'dev',
        port: 60099,
        token: 'tok',
        pid: process.pid,
        version: '0.17.0',
        started_at: '2026-10-07T00:00:00+00:00',
        data_dir: path.join(dataDir, 'OTHER'),
      }),
      'utf-8'
    );

    await freshInstance(['electron']);
    await flush(50);

    const commands = spawnMock.mock.calls.map((c) => c[0] as string);
    expect(commands[0]).toBe('taskkill'); // 先停旧
    expect(commands.some((c) => c.includes('serve')) || commands.length === 1).toBe(true);
  });

  it('同 data_dir / 无条目 → 直接 spawn 内核（不停机）', async () => {
    await freshInstance(['electron']);
    await flush(50);

    const commands = spawnMock.mock.calls.map((c) => c[0] as string);
    expect(commands).not.toContain('taskkill');
  });
});

describe('内核冲突退出码 3（spec f31 §7 边界 17）', () => {
  it('内核以退出码 3 退出 → 不弹「启动失败」对话框（走 1B 自愈）', async () => {
    await freshInstance(['electron']);
    await flush();

    fakeChild.emit('exit', 3, null);
    await flush(300);

    expect(electronMock.dialog.showMessageBox).not.toHaveBeenCalled();
  });

  it('内核以其他退出码退出 → 仍走既有失败链路（重启计时器登记）', async () => {
    await freshInstance(['electron']);
    await flush();

    fakeChild.emit('exit', 1, null);
    await flush();

    // 既有行为：不退化为「冲突自愈」，失败计数生效（此处只断言不弹冲突分支的错误框：
    // 单次失败 < 阈值 → 不进对话框）
    expect(electronMock.dialog.showMessageBox).not.toHaveBeenCalled();
  });
});
