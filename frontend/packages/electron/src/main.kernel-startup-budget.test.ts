/**
 * 内核启动看门狗预算契约（#1077 e2e-frontend-settings flaky 根治，RED 阶段）
 *
 * 背景：main.ts 的启动看门狗 READY_TIMEOUT_MS 原为 15_000，而 CI 冷 runner 内核
 * import 树实测 ≈60s（#1068 量化：litellm/mcp/langchain 全树 + Defender 放大）、
 * 本地 warm ≈20-30s——全部 > 15s。即内核每次都在即将 INKFLOW_READY 前被 watchdog
 * 主动 kill → 退避 1s → 从零重 spawn → 又在 15s 被杀。E2E 的 waitKernelInfo 轮询
 * 窗口内经历 3-4 个「15s 杀进程」循环，__kernelInfo 永远没机会注入 —— 这不是
 * 「等得不够久」，是「重试编排把冷启动进程反复处死」（#1045/#896/#1077 同签名族）。
 *
 * 契约（对齐 #1068 集成层 kernel-harness.ts 的 READY_TIMEOUT_MS = 90_000，
 * Electron 通道同口径）：
 * 1. spawn 后 60s（CI 冷启动实测线）内 watchdog 不得触发失败 → 无 kill、无重 spawn、
 *    无错误对话框；
 * 2. 90s 预算耗尽 → 判启动失败：kill 恰好 1 次（onKernelFailure → killProcessTree），
 *    退避 1s 后重 spawn 恰 1 次；
 * 3. READY 在预算内晚到（80s，< 90s）→ 恢复路径：__kernelInfo 注入 + inkflow:ready
 *    推送 + 健康检查启动（E2E 通道成功形态），且 watchdog 已撤销不再误杀。
 *
 * mock 设计：复制 main.export.test.ts 的 vi.hoisted electron mock 范本
 * （whenReady 立即 resolve + 惰性假 child + vi.mock('node:child_process')），
 * 用例用 freshInstance（removeAllListeners → resetModules → 动态 import）换新模块
 * 实例（consecutiveFailures/kernelProcess/watchdog 状态归零，实测先例
 * main.window-controls.test.ts 组 D/E）。fake timers 在 freshInstance 之前启用，
 * boot 内 spawnKernel 挂载的 watchdog 走虚拟时钟。
 */
import { describe, it, expect, beforeAll, afterEach, afterAll, vi, type Mock } from 'vitest';
import { app, dialog } from 'electron';
import './main';

type AnyHandler = (...args: unknown[]) => void;

const electronMock = vi.hoisted(() => {
  // 迷你事件发射器：win.on / child.on 等存 handler，测试里手动触发（readline 兼容面：
  // on/once/removeListener/emit/resume/pause/setEncoding/pipe 均提供）
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

  // spawnKernel 的惰性假 child：child.on/emit 必须共享同一 emitter（否则 emit 不触发）
  const childEmitter = createEmitter();
  const fakeChild = {
    pid: 4242,
    exitCode: null,
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
      getPath: vi.fn(() => 'C:\\Users\\test\\AppData\\Roaming'),
    },
    BrowserWindow: Object.assign(vi.fn(() => win), {
      getFocusedWindow: vi.fn(() => null),
    }),
    ipcMain: { on: vi.fn(), handle: vi.fn() },
    Menu: {
      setApplicationMenu: vi.fn(),
      buildFromTemplate: vi.fn(() => ({ popup: vi.fn() })),
    },
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
vi.mock('node:fs/promises', () => ({ writeFile: vi.fn().mockResolvedValue(undefined) }));

const win = electronMock.__win as unknown as {
  webContents: { send: Mock };
  isMaximized: Mock;
};
const fakeChild = electronMock.__fakeChild as unknown as {
  pid: number | undefined;
  exitCode: number | null;
  stdout: { emit: (evt: string, ...args: unknown[]) => boolean; removeAllListeners: (evt?: string) => unknown };
  stderr: { removeAllListeners: (evt?: string) => unknown };
  emit: (evt: string, ...args: unknown[]) => boolean;
  removeAllListeners: (evt?: string) => unknown;
  kill: Mock;
};
const spawnMock = electronMock.__spawn as unknown as Mock;

const READY_LINE = (port: number, token: string): string =>
  `INKFLOW_READY {"port":${port},"token":"${token}","pid":7,"version":"0.1.0"}\n`;

/** 触发一次 INKFLOW_READY（line 回调同步执行；kernelProcess 必须 === child 才生效） */
const emitReady = (port = 51234, token = 'a'): void => {
  fakeChild.stdout.emit('data', Buffer.from(READY_LINE(port, token)));
};

/** 内核 spawn 调用次数（排除 killProcessTree 的 taskkill 干扰） */
const kernelSpawnCount = (): number =>
  spawnMock.mock.calls.filter((c: unknown[]) => c[0] !== 'taskkill').length;

/** 新模块实例（boot 即 spawnKernel 一次 + 挂 watchdog；状态归零，先例 main.window-controls.test.ts） */
const freshInstance = async (): Promise<void> => {
  fakeChild.removeAllListeners();
  fakeChild.stdout.removeAllListeners();
  fakeChild.stderr.removeAllListeners();
  delete (globalThis as { __kernelInfo?: unknown }).__kernelInfo;
  vi.resetModules();
  await import('./main');
};

describe('#1077 内核启动看门狗预算（READY_TIMEOUT_MS 对齐 #1068 = 90s）', () => {
  beforeAll(() => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.mocked(dialog.showMessageBox).mockClear();
    vi.mocked(dialog.showMessageBox).mockResolvedValue({ response: 0 });
  });

  afterAll(() => {
    vi.restoreAllMocks();
  });

  it('spawn 后 60s 内（CI 冷启动实测线）watchdog 不误杀：无 kill、无重 spawn、无错误对话框', async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve({ ok: true })),
    );
    await freshInstance();
    const spawnBefore = kernelSpawnCount();
    const killBefore = fakeChild.kill.mock.calls.length;
    // 推进 60s：旧实现（15s watchdog）此处已触发 3-4 轮「误杀 → 退避 → 重 spawn」循环
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fakeChild.kill.mock.calls.length).toBe(killBefore);
    expect(kernelSpawnCount()).toBe(spawnBefore);
    expect(dialog.showMessageBox).not.toHaveBeenCalled();
  });

  it('90s 预算耗尽 → 判启动失败：kill 恰 1 次，退避 1s 后重 spawn 恰 1 次', async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve({ ok: true })),
    );
    await freshInstance();
    const spawnBefore = kernelSpawnCount();
    const killBefore = fakeChild.kill.mock.calls.length;
    await vi.advanceTimersByTimeAsync(90_000);
    // 旧实现（15s）在 90s 窗口内 kill ≥3 次（每轮循环 +1），恒不等于 killBefore + 1 → RED
    expect(fakeChild.kill.mock.calls.length).toBe(killBefore + 1);
    expect(dialog.showMessageBox).not.toHaveBeenCalled(); // 单次失败 < 6 次阈值，不弹框
    await vi.advanceTimersByTimeAsync(1_000); // 失败 #1 退避 → 重拉
    expect(kernelSpawnCount()).toBe(spawnBefore + 1);
  });

  it('READY 于 80s 晚到（< 90s 预算）→ 恢复：__kernelInfo 注入 + inkflow:ready 推送 + watchdog 撤销', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(() => Promise.resolve({ ok: true }));
    vi.stubGlobal('fetch', fetchMock);
    await freshInstance();
    const killBefore = fakeChild.kill.mock.calls.length;
    // 先推进 80s：旧实现此处 kernelProcess 已被反复处死（kill>0）→ 前置条件即被拆穿
    await vi.advanceTimersByTimeAsync(80_000);
    expect(fakeChild.kill.mock.calls.length).toBe(killBefore);
    emitReady(51234, 't-late');
    await vi.advanceTimersByTimeAsync(0);
    expect((globalThis as { __kernelInfo?: unknown }).__kernelInfo).toEqual({
      pid: 4242,
      port: 51234,
      token: 't-late',
    });
    expect(win.webContents.send).toHaveBeenCalledWith('inkflow:ready', {
      baseURL: 'http://127.0.0.1:51234',
      token: 't-late',
    });
    // 健康检查已启动（READY → 立即 GET /health 一次）
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('/health'))).toBe(true);
    // watchdog 已撤销：再推进 90s 也不得再触发失败处理
    await vi.advanceTimersByTimeAsync(90_000);
    expect(fakeChild.kill.mock.calls.length).toBe(killBefore);
  });
});
