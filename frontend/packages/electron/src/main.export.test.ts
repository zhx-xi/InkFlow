/**
 * 主进程导出 / 文件对话框 IPC 测试契约（RED 阶段）
 *
 * 被测模块 src/main.ts 新增三个 ipcMain.handle（GREEN 实现前未注册 → handler 缺失 /
 * 断言失败 = 预期 RED）：
 *   - file:get-default-location → 返回 app.getPath('desktop')
 *   - dialog:choose-directory   → dialog.showOpenDialog({ properties: ['openDirectory'] })；
 *                                 选中 → filePaths[0]；取消（canceled: true）→ null
 *   - file:save-export          → 参数 { path, filename, content } →
 *                                 writeFile(path.join(path, filename), content, 'utf8') →
 *                                 返回 { path: path.join(path, filename), filename }；
 *                                 path / filename 为空 → 抛错误（不写文件）
 *
 * mock 设计（仿 main.tray.test.ts / main.window-controls.test.ts，差异点必须理解）：
 * - vi.hoisted electron mock：app.whenReady 立即 resolve → import './main' 时完整执行
 *   启动回调（单实例锁 + IPC 注册 + createMainWindow + spawnKernel + Tray 创建）。
 * - 本文件【不重复】托盘/窗口控制/启动链路的既有断言（main.tray.test.ts /
 *   main.window-controls.test.ts 专责）——只测新增 3 个 ipcMain.handle 的行为契约。
 * - electron mock 相比既有范本新增两面：app.getPath（vi.fn → 'C:\\Users\\test\\Desktop'）
 *   与 dialog.showOpenDialog（vi.fn → Promise.resolve）——三个新 handler 的数据源。
 * - vi.mock('node:fs/promises')：writeFile = vi.fn().mockResolvedValue(undefined)。
 *   ⚠️ 只 mock promises 面：kernel.ts 的 kernel.json 读写走 node:fs 同步 API
 *   （readFileSync/writeFileSync/renameSync），不受影响；tryReuseKernel 读真实
 *   repo/backend/data/kernel.json（不存在 → null）→ 确定性回落 spawnKernel（惰性假 child，
 *   无真实进程/网络副作用）。
 * - 三个 handler 均无模块级可变状态（只委托 mock），无需 freshInstance 换实例；
 *   ⚠️ 但默认实例的 ipcMain.handle 注册记录在 import 时即就绪（whenReady 立即 resolve），
 *   beforeAll 直接提取 handler。不使用 vi.resetModules。
 * - 触发方式：ipcMain.handle 的 handler 签名 = (event, ...args) → 从
 *   vi.mocked(ipcMain.handle).mock.calls 捕获 handler 后 await handler(null, ...args) 直调。
 */
import { describe, it, expect, beforeAll, beforeEach, afterAll, vi, type Mock } from 'vitest';
import path from 'node:path';
import { writeFile } from 'node:fs/promises';
import { ipcMain } from 'electron';
import './main';

type AnyHandler = (...args: unknown[]) => void;
type IpcHandleHandler = (event: unknown, ...args: unknown[]) => unknown;

/** file:save-export 载荷（renderer → main） */
interface SaveExportPayload {
  path: string;
  filename: string;
  content: string;
}

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

  // createMainWindow / app 的事件 handler 存储（按事件名，测试手动触发）
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

  const trayInstance = {
    setContextMenu: vi.fn(),
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
      // 新增契约面：file:get-default-location 数据源
      getPath: vi.fn(() => 'C:\\Users\\test\\Desktop'),
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
      // 新增契约面：dialog:choose-directory 数据源
      showOpenDialog: vi.fn(() => Promise.resolve({ canceled: true, filePaths: [] })),
    },
    Tray: vi.fn(() => trayInstance),
    nativeImage: { createFromPath: vi.fn(() => ({ isEmpty: () => false })) },
  };
});

vi.mock('electron', () => electronMock);
vi.mock('node:child_process', () => ({ spawn: electronMock.__spawn }));
vi.mock('node:fs/promises', () => ({ writeFile: vi.fn().mockResolvedValue(undefined) }));

const appMock = electronMock.app as { getPath: Mock; isPackaged: boolean };
const dialogMock = electronMock.dialog as { showOpenDialog: Mock };
const writeFileMock = vi.mocked(writeFile);

let getDefaultLocationHandler: IpcHandleHandler;
let chooseDirectoryHandler: IpcHandleHandler;
let saveExportHandler: IpcHandleHandler;

beforeAll(() => {
  vi.spyOn(console, 'log').mockImplementation(() => {});
  vi.spyOn(console, 'error').mockImplementation(() => {});
  // 启动回调已在 import 时执行（whenReady 立即 resolve）→ 从 ipcMain.handle 注册记录取 handler
  const handleMock = vi.mocked(ipcMain.handle);
  getDefaultLocationHandler = handleMock.mock.calls.find(
    (c) => c[0] === 'file:get-default-location'
  )?.[1] as unknown as IpcHandleHandler;
  chooseDirectoryHandler = handleMock.mock.calls.find(
    (c) => c[0] === 'dialog:choose-directory'
  )?.[1] as unknown as IpcHandleHandler;
  saveExportHandler = handleMock.mock.calls.find(
    (c) => c[0] === 'file:save-export'
  )?.[1] as unknown as IpcHandleHandler;
});

beforeEach(() => {
  appMock.getPath.mockClear();
  dialogMock.showOpenDialog.mockClear();
  writeFileMock.mockClear();
  // mockClear 不重置实现：显式复位默认行为
  appMock.getPath.mockReturnValue('C:\\Users\\test\\Desktop');
  dialogMock.showOpenDialog.mockResolvedValue({ canceled: false, filePaths: ['D:\\out'] });
});

afterAll(() => {
  vi.restoreAllMocks();
});

describe('导出/文件对话框 IPC handler（RED 阶段契约）', () => {
  it('启动时注册 file:get-default-location / dialog:choose-directory / file:save-export 三个通道', () => {
    const channels = vi.mocked(ipcMain.handle).mock.calls.map((c) => c[0]);
    expect(channels).toEqual(
      expect.arrayContaining([
        'file:get-default-location',
        'dialog:choose-directory',
        'file:save-export',
      ])
    );
  });
});

describe('file:get-default-location', () => {
  it('返回 app.getPath("desktop")（mock 桌面路径）', async () => {
    expect(getDefaultLocationHandler).toBeDefined();
    expect(await getDefaultLocationHandler(null)).toBe('C:\\Users\\test\\Desktop');
    expect(appMock.getPath).toHaveBeenCalledWith('desktop');
  });
});

describe('dialog:choose-directory', () => {
  it('showOpenDialog({ properties: ["openDirectory"] })；选中目录 → 返回 filePaths[0]', async () => {
    expect(chooseDirectoryHandler).toBeDefined();
    expect(await chooseDirectoryHandler(null)).toBe('D:\\out');
    expect(dialogMock.showOpenDialog).toHaveBeenCalledWith({ properties: ['openDirectory'] });
  });

  it('用户取消（canceled: true）→ 返回 null', async () => {
    expect(chooseDirectoryHandler).toBeDefined();
    dialogMock.showOpenDialog.mockResolvedValue({ canceled: true, filePaths: [] });
    expect(await chooseDirectoryHandler(null)).toBeNull();
  });
});

describe('file:save-export', () => {
  it('writeFile(path.join(path, filename), content, "utf8") → 返回 { path, filename }', async () => {
    expect(saveExportHandler).toBeDefined();
    const payload: SaveExportPayload = {
      path: 'D:\\out',
      filename: '剑来.txt',
      content: '正文',
    };
    const result = await saveExportHandler(null, payload);
    expect(writeFileMock).toHaveBeenCalledWith(
      path.join('D:\\out', '剑来.txt'),
      '正文',
      'utf8'
    );
    expect(result).toEqual({ path: path.join('D:\\out', '剑来.txt'), filename: '剑来.txt' });
  });

  it('path 为空 → 抛错误（不写文件）', async () => {
    expect(saveExportHandler).toBeDefined();
    await expect(
      saveExportHandler(null, { path: '', filename: 'a.txt', content: 'x' })
    ).rejects.toThrow();
    expect(writeFileMock).not.toHaveBeenCalled();
  });

  it('filename 为空 → 抛错误（不写文件）', async () => {
    expect(saveExportHandler).toBeDefined();
    await expect(
      saveExportHandler(null, { path: 'D:\\out', filename: '', content: 'x' })
    ).rejects.toThrow();
    expect(writeFileMock).not.toHaveBeenCalled();
  });
});
