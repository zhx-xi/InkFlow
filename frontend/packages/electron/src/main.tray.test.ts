/**
 * 主进程托盘 / 关闭拦截 / 单实例 / IPC 测试契约（F31 #167 GUI 托盘常驻，RED 阶段）
 *
 * 契约来源：specs/f31-gui-tray/spec.md
 *   - §2.2 关闭行为内存态（CloseBehavior = 'tray' | 'quit'，默认 'tray'）+ trayHintDismissed
 *   - §2.3 IPC 契约：settings:get-close-behavior / settings:set-close-behavior /
 *     settings:dismiss-tray-hint（ipcMain.handle 幂等注册）+ inkflow:tray-hint（main→renderer）
 *   - §5.1 模式总览（单实例锁 → 内核连接 → 关闭拦截 → 托盘菜单）
 *   - §5.2 关闭拦截状态机：tray→preventDefault+hide+首次提示（内核保持）；quit→放行 →
 *     window-all-closed → shutdown；托盘「退出」→ tray.destroy() + shutdown()；tray 模式
 *     window-all-closed 不退出（条件退出，D5）
 *   - §5.5 单实例：requestSingleInstanceLock 失败 → app.quit()（不 spawn 不建窗）；
 *     second-instance → isMinimized?restore + show/focus，窗口销毁 → createMainWindow 重建
 *   - §5.6 托盘实现：nativeImage.createFromPath 图标、菜单「打开主窗口 / 内核状态 / 分隔 /
 *     退出」、点击图标 → 打开主窗口、退出 → shutdown + destroy
 *   - §8 文件结构（main.tray.test.ts CREATE）、§9 测试策略（关闭拦截状态机 / 单实例分支 /
 *     IPC handler / Tray 创建）
 *
 * 被测模块 src/main.ts 新增逻辑（RED 阶段未实现 → 断言失败 / TypeError = 预期 RED）：
 *   单实例锁 + second-instance + settings:* IPC handler + close 拦截 + Tray 创建/菜单/销毁 +
 *   window-all-closed 条件退出 + inkflow:tray-hint 首次提示。
 *
 * mock 设计（模仿 main.window-controls.test.ts，差异点必须理解）：
 * - vi.hoisted electron mock：app.whenReady 立即 resolve → import './main' 时完整执行
 *   启动回调（单实例锁 + IPC 注册 + createMainWindow + spawnKernel + Tray 创建）。
 * - vi.mock('node:child_process')：spawn 返回惰性假 child（迷你 EventEmitter，永不自动
 *   emit）——无真实进程/网络副作用；stopKernel 的完成经手动 fakeChild.emit('exit') 触发
 *   （once('exit') → finish → app.exit，幂等 settled 守卫）。
 * - 设计假设（GREEN 必须匹配）：托盘菜单经 Menu.buildFromTemplate(template) 构建——
 *   mock 捕获模板数组，测试直接触发菜单项 click 回调；「退出」菜单项 click = 退出流程
 *   入口。Tray 构造经 nativeImage.createFromPath(图标路径)（spec §5.6）。
 * - 模块级状态（closeBehavior/trayHintDismissed/quitInProgress/mainWindow）跨用例共享：
 *   状态变更用例（单实例锁失败 / quit 模式 / 退出路径 / 窗口销毁重建）用
 *   vi.resetModules() + 动态 import 换新模块实例（fakeChild emitter 必须先
 *   removeAllListeners 清旧回调，否则跨实例回调累积，window-controls 先例实测）。
 * - ⚠️ resetModules 会清空 vi.mock 的调用记录（实测）——默认实例的启动期断言
 *   （lock 调用 / IPC 注册通道）必须排在首个 freshInstance 之前；fresh 实例的
 *   ipcMain.handle 记录在其 import 后重新提取。
 * - 用例顺序依赖声明顺序（vitest 默认串行）：默认实例组内
 *   「首次提示 → dismiss → 退出」顺序不可调换（dismiss 会置 trayHintDismissed）。
 */
import { describe, it, expect, beforeAll, beforeEach, afterEach, vi, type Mock } from 'vitest';
import path from 'node:path';
import { app, ipcMain, Tray, nativeImage, Menu, BrowserWindow } from 'electron';
import './main';

type AnyHandler = (...args: unknown[]) => void;
type IpcHandleHandler = (event: unknown, ...args: unknown[]) => unknown;

/** 托盘菜单模板项（Electron MenuItemConstructorOptions 最小面，spec §5.6） */
interface MenuItemTemplate {
  label?: string;
  type?: string;
  click?: () => void;
  submenu?: unknown;
}

const electronMock = vi.hoisted(() => {
  // 迷你事件发射器：win.on / child.on 等存 handler，测试里手动触发
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
  let trayMenuTemplate: unknown = null;

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
    __getTrayMenuTemplate: () => trayMenuTemplate,
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
    },
    BrowserWindow: Object.assign(vi.fn(() => win), {
      getFocusedWindow: vi.fn(() => null),
    }),
    ipcMain: { on: vi.fn(), handle: vi.fn() },
    Menu: {
      setApplicationMenu: vi.fn(),
      buildFromTemplate: vi.fn((template: unknown) => {
        trayMenuTemplate = template;
        return { popup: vi.fn() };
      }),
    },
    globalShortcut: { register: vi.fn(() => true), unregisterAll: vi.fn() },
    dialog: { showMessageBox: vi.fn(() => Promise.resolve({ response: 0 })) },
    Tray: vi.fn(() => trayInstance),
    nativeImage: { createFromPath: vi.fn(() => ({ isEmpty: () => false })) },
  };
});

vi.mock('electron', () => electronMock);
vi.mock('node:child_process', () => ({ spawn: electronMock.__spawn }));

const win = electronMock.__win as unknown as {
  minimize: Mock;
  unmaximize: Mock;
  maximize: Mock;
  close: Mock;
  hide: Mock;
  show: Mock;
  focus: Mock;
  restore: Mock;
  isMinimized: Mock;
  setTitle: Mock;
  webContents: { send: Mock; on: Mock };
};
const windowEventHandlers = electronMock.__windowEventHandlers;
const webContentsEventHandlers = electronMock.__webContentsEventHandlers;
const appEventHandlers = electronMock.__appEventHandlers;
const spawnMock = electronMock.__spawn as unknown as Mock;
const fakeChild = electronMock.__fakeChild as unknown as {
  pid: number | undefined;
  exitCode: number | null;
  stdout: { emit: (evt: string, ...args: unknown[]) => boolean; removeAllListeners: (evt?: string) => unknown };
  emit: (evt: string, ...args: unknown[]) => boolean;
  removeAllListeners: (evt?: string) => unknown;
  kill: Mock;
};
const trayInstance = electronMock.__trayInstance as unknown as {
  setContextMenu: Mock;
  on: Mock;
  destroy: Mock;
};
const appMock = electronMock.app as {
  isPackaged: boolean;
  requestSingleInstanceLock: Mock;
  quit: Mock;
  exit: Mock;
};

const getTrayMenuTemplate = (): MenuItemTemplate[] | null =>
  electronMock.__getTrayMenuTemplate() as MenuItemTemplate[] | null;

let getCloseBehaviorHandler: IpcHandleHandler;
let setCloseBehaviorHandler: IpcHandleHandler;

/** 冲刷微任务（stopKernel 的 once('exit') 注册 / shutdown 续体） */
const flushMicrotasks = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

/** 新模块实例（状态归零：closeBehavior/quitInProgress/mainWindow/trayHintDismissed）。
 *  ⚠️ fakeChild 的 emitter 是 hoisted 单例：必须先 removeAllListeners 清旧实例回调。 */
const freshInstance = async (): Promise<void> => {
  fakeChild.removeAllListeners();
  fakeChild.stdout.removeAllListeners();
  fakeChild.stderr.removeAllListeners();
  vi.resetModules();
  await import('./main');
};

beforeAll(() => {
  vi.spyOn(console, 'log').mockImplementation(() => {});
  vi.spyOn(console, 'error').mockImplementation(() => {});
  // 启动回调已在 import 时执行（whenReady 立即 resolve）→ 从 ipcMain.handle 注册记录取 handler
  const handleMock = vi.mocked(ipcMain.handle);
  getCloseBehaviorHandler = handleMock.mock.calls.find(
    (c) => c[0] === 'settings:get-close-behavior'
  )?.[1] as unknown as IpcHandleHandler;
  setCloseBehaviorHandler = handleMock.mock.calls.find(
    (c) => c[0] === 'settings:set-close-behavior'
  )?.[1] as unknown as IpcHandleHandler;
});

beforeEach(() => {
  win.minimize.mockClear();
  win.unmaximize.mockClear();
  win.maximize.mockClear();
  win.close.mockClear();
  win.hide.mockClear();
  win.show.mockClear();
  win.focus.mockClear();
  win.restore.mockClear();
  win.setTitle.mockClear();
  win.webContents.send.mockClear();
  // mockReset 不重置实现：显式复位 isMinimized 默认 false
  win.isMinimized.mockReset();
  win.isMinimized.mockReturnValue(false);
  appMock.exit.mockClear();
  appMock.quit.mockClear();
  // ⚠️ 不清 trayInstance.setContextMenu / trayInstance.on / Tray / createFromPath：
  // 启动期创建断言依赖 import 时的注册记录（freshInstance 会累积计数，按「至少一次」断言）
  trayInstance.destroy.mockClear();
  fakeChild.kill.mockClear();
  fakeChild.pid = 4242;
  fakeChild.exitCode = null;
  appMock.isPackaged = false;
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe('单实例锁与 second-instance（spec §5.5 / 边界#7-9）', () => {
  it('启动时调用单实例锁恰一次（§5.5；冒烟）', () => {
    // ⚠️ 冒烟（#524）：whenReady 立即 resolve 的 mock 下，「锁调用在回调内」的时序约束
    // 不可验证（挪到模块顶层仍绿）——本用例仅锚定「启动链路上调用了锁」且恰一次。
    // 本用例是文件首个用例（beforeEach 不清锁 mock）→ import 时启动回调的 1 次调用即全部记录。
    expect(appMock.requestSingleInstanceLock).toHaveBeenCalledTimes(1);
  });

  it('second-instance（窗口存在）→ show() + focus()；非最小化不 restore()', () => {
    appEventHandlers['second-instance']?.();
    expect(win.show).toHaveBeenCalledTimes(1);
    expect(win.focus).toHaveBeenCalledTimes(1);
    expect(win.restore).not.toHaveBeenCalled();
  });

  it('second-instance 且窗口最小化（托盘隐藏态）→ restore() + show() + focus()（边界#8）', () => {
    win.isMinimized.mockReturnValue(true);
    appEventHandlers['second-instance']?.();
    expect(win.restore).toHaveBeenCalledTimes(1);
    expect(win.show).toHaveBeenCalledTimes(1);
    expect(win.focus).toHaveBeenCalledTimes(1);
  });

  it('单实例锁获取失败 → app.quit()，不创建窗口、不 spawn（边界#7）', async () => {
    vi.mocked(BrowserWindow).mockClear();
    spawnMock.mockClear();
    appMock.quit.mockClear();
    appMock.requestSingleInstanceLock.mockReturnValueOnce(false);
    await freshInstance();
    expect(appMock.quit).toHaveBeenCalledTimes(1);
    expect(BrowserWindow).not.toHaveBeenCalled();
    expect(spawnMock).not.toHaveBeenCalled();
  });

  it('second-instance 且窗口已销毁（托盘残留）→ createMainWindow 重建（边界#9）', async () => {
    await freshInstance();
    windowEventHandlers['closed']?.(); // 窗口销毁 → mainWindow = null
    const windowCallsBefore = vi.mocked(BrowserWindow).mock.calls.length;
    appEventHandlers['second-instance']?.();
    expect(vi.mocked(BrowserWindow).mock.calls.length).toBe(windowCallsBefore + 1);
  });
});

describe('settings:* IPC handler（spec §2.3 / M6 / M7）', () => {
  it('启动时注册 settings:get-close-behavior / settings:set-close-behavior / settings:dismiss-tray-hint', () => {
    const channels = vi.mocked(ipcMain.handle).mock.calls.map((c) => c[0]);
    expect(channels).toEqual(
      expect.arrayContaining([
        'settings:get-close-behavior',
        'settings:set-close-behavior',
        'settings:dismiss-tray-hint',
      ])
    );
    // ⚠️ 不断言 toHaveLength(3)：freshInstance（vi.resetModules 重 import）会重复注册
    // （每次实例 3 通道），mock 记录为跨实例累积——「恰好 3」无法在累积记录上成立；
    // 通道去重后恰为 3 即契约成立（同一实例不重复注册）
    expect(new Set(channels.filter((c) => c.startsWith('settings:'))).size).toBe(3);
  });

  it('get-close-behavior 默认返回 "tray"（§2.2 / M6）', async () => {
    expect(getCloseBehaviorHandler).toBeDefined();
    expect(await getCloseBehaviorHandler(null)).toBe('tray');
  });

  it('set-close-behavior 即改即生效：set "quit" → get "quit"；set 回 "tray" 恢复', async () => {
    expect(setCloseBehaviorHandler).toBeDefined();
    await setCloseBehaviorHandler(null, 'quit');
    expect(await getCloseBehaviorHandler(null)).toBe('quit');
    await setCloseBehaviorHandler(null, 'tray');
    expect(await getCloseBehaviorHandler(null)).toBe('tray');
  });

  it('dismiss-tray-hint 置 trayHintDismissed（后续 close 不再发 inkflow:tray-hint，§2.3/§5.2）', async () => {
    // ⚠️ 补强（#524）：副作用断言——dismiss 后 close 拦截不再推送 tray 提示（handler 变空实现此处变红）。
    // 用独立新实例隔离 dismiss 状态（末尾再 freshInstance 还原），避免污染后续
    // 「首次 close 应发 tray-hint」用例；filter + pop 取「最新注册」的 handler，
    // 与 close 拦截同一模块实例，状态才一致。
    await freshInstance();
    const handleMock = vi.mocked(ipcMain.handle);
    const dismissHandler = handleMock.mock.calls
      .filter((c) => c[0] === 'settings:dismiss-tray-hint')
      .pop()?.[1] as unknown as IpcHandleHandler;
    expect(dismissHandler).toBeDefined();
    await dismissHandler(null);
    const event = { preventDefault: vi.fn() };
    windowEventHandlers['close']?.(event);
    expect(event.preventDefault).toHaveBeenCalledTimes(1);
    expect(win.hide).toHaveBeenCalledTimes(1);
    expect(win.webContents.send).not.toHaveBeenCalledWith('inkflow:tray-hint');
    await freshInstance(); // 还原：后续「首次提示」用例需要 trayHintDismissed=false 的新实例
  });
});

describe('Tray 创建与菜单（spec §5.6）', () => {
  it('启动时创建 Tray：nativeImage.createFromPath(非空图标路径) + setContextMenu', () => {
    // 至少一次：freshInstance 用例会累积计数，启动创建（首次调用）即满足契约
    expect(Tray).toHaveBeenCalled();
    const iconPath = vi.mocked(nativeImage.createFromPath).mock.calls[0]?.[0];
    expect(iconPath).toBeDefined();
    expect(typeof iconPath).toBe('string');
    expect(String(iconPath)).toContain('inkflow-icon-256.png');
    expect(trayInstance.setContextMenu).toHaveBeenCalled();
  });

  it('托盘菜单模板：「打开主窗口」/「内核状态」/ 分隔 /「退出」（含 click 回调）', () => {
    const template = getTrayMenuTemplate();
    expect(template).toBeDefined();
    const entries = template?.map((i) => i.label ?? i.type) ?? [];
    expect(entries).toEqual(expect.arrayContaining(['打开主窗口', '退出', 'separator']));
    expect(template?.some((i) => String(i.label ?? '').startsWith('内核状态'))).toBe(true);
    expect(template?.find((i) => i.label === '退出')?.click).toBeTypeOf('function');
  });

  it('托盘菜单「打开主窗口」→ win.show() + win.focus()（§5.2）', () => {
    const openItem = getTrayMenuTemplate()?.find((i) => i.label === '打开主窗口');
    expect(openItem).toBeDefined();
    openItem?.click?.();
    expect(win.show).toHaveBeenCalledTimes(1);
    expect(win.focus).toHaveBeenCalledTimes(1);
  });

  it('托盘图标 click 事件 → 打开主窗口（show + focus，§5.6）', () => {
    const clickCallback = trayInstance.on.mock.calls.find((c) => c[0] === 'click')?.[1] as
      | (() => void)
      | undefined;
    expect(clickCallback).toBeDefined();
    clickCallback?.();
    expect(win.show).toHaveBeenCalledTimes(1);
    expect(win.focus).toHaveBeenCalledTimes(1);
  });
});

describe('关闭拦截状态机与首次托盘提示（spec §5.2 / M1 / M7）', () => {
  it('tray 模式（默认）close 拦截：preventDefault + hide + 首次 inkflow:tray-hint；内核保持', () => {
    const event = { preventDefault: vi.fn() };
    windowEventHandlers['close']?.(event);
    expect(event.preventDefault).toHaveBeenCalledTimes(1);
    expect(win.hide).toHaveBeenCalledTimes(1);
    expect(win.webContents.send).toHaveBeenCalledWith('inkflow:tray-hint');
    // 内核保持运行：不触发 shutdown（无 kill / 无 app.exit）
    expect(fakeChild.kill).not.toHaveBeenCalled();
    expect(appMock.exit).not.toHaveBeenCalled();
  });

  it('dismiss-tray-hint 后再 close → 不再发送 inkflow:tray-hint（§2.2 / Q1）', async () => {
    // ⚠️ 不依赖 beforeAll 提取的 handler：前面用例已 freshInstance（重 import），
    // windowEventHandlers['close'] 被新实例覆盖——handler 必须取「最新注册」的实例
    // （filter + pop = 最后一次注册），与 close 拦截同一模块实例，状态才一致。
    const handleMock = vi.mocked(ipcMain.handle);
    const dismissHandler = handleMock.mock.calls
      .filter((c) => c[0] === 'settings:dismiss-tray-hint')
      .pop()?.[1] as unknown as IpcHandleHandler;
    expect(dismissHandler).toBeDefined();
    await dismissHandler(null);
    const event = { preventDefault: vi.fn() };
    windowEventHandlers['close']?.(event);
    expect(event.preventDefault).toHaveBeenCalledTimes(1);
    expect(win.hide).toHaveBeenCalledTimes(1);
    expect(win.webContents.send).not.toHaveBeenCalledWith('inkflow:tray-hint');
  });

  it('托盘菜单「退出」→ tray.destroy() + shutdown（stopKernel + app.exit，§5.2/§5.6）', async () => {
    const quitItem = getTrayMenuTemplate()?.find((i) => i.label === '退出');
    expect(quitItem).toBeDefined();
    quitItem?.click?.();
    await flushMicrotasks(); // stopKernel 的 once('exit') 注册完成
    fakeChild.emit('exit', 0, null); // 模拟内核进程退出 → stopKernel 完成
    await flushMicrotasks(); // shutdown 续体：app.exit
    expect(trayInstance.destroy).toHaveBeenCalledTimes(1);
    expect(fakeChild.kill).toHaveBeenCalledTimes(1);
    expect(appMock.exit).toHaveBeenCalledTimes(1);
  });
});

describe('window-all-closed 条件退出（spec §5.2 / §5.6 / D5）', () => {
  it('quit 模式：close 不拦截（无 preventDefault / 无 hide）→ window-all-closed → shutdown', async () => {
    await freshInstance();
    const handleMock = vi.mocked(ipcMain.handle);
    // ⚠️ 同上：freshInstance 后取「最新注册」的 set handler（与 close 拦截同一实例）
    const setHandler = handleMock.mock.calls
      .filter((c) => c[0] === 'settings:set-close-behavior')
      .pop()?.[1] as unknown as IpcHandleHandler;
    expect(setHandler).toBeDefined();
    await setHandler(null, 'quit');
    const closeEvent = { preventDefault: vi.fn() };
    windowEventHandlers['close']?.(closeEvent);
    expect(closeEvent.preventDefault).not.toHaveBeenCalled();
    expect(win.hide).not.toHaveBeenCalled();
    appEventHandlers['window-all-closed']?.({ preventDefault: vi.fn() });
    await flushMicrotasks();
    fakeChild.emit('exit', 0, null); // stopKernel 完成
    await flushMicrotasks();
    expect(appMock.exit).toHaveBeenCalled();
  });

  it('tray 模式：window-all-closed 不退出（显式 preventDefault；不 shutdown，内核保持）', async () => {
    await freshInstance();
    vi.useFakeTimers();
    const event = { preventDefault: vi.fn() };
    appEventHandlers['window-all-closed']?.(event);
    expect(event.preventDefault).toHaveBeenCalledTimes(1);
    expect(appMock.exit).not.toHaveBeenCalled();
    expect(fakeChild.kill).not.toHaveBeenCalled();
    // 冲刷 RED 旧实现（无条件 shutdown）可能挂起的 stopKernel 定时器，避免悬挂句柄
    await vi.advanceTimersByTimeAsync(5_000);
  });
});

// ══ 回归防护：0.5.0 发布缺陷补测（#192，2026-08-08）═══════════════════════
//  #192 F1 packagedKernelPath 曾用 app.getAppPath()（打包版返回 asar 路径 → ENOENT
//  内核全灭）——本测试锁定修复后行为：process.resourcesPath 存在时 spawn 命令必须是
//  resources/kernel 绝对路径 + cwd 兜底。
//  #188 F2（ready → 菜单 label 刷新）的集成断言经实测无法在此文件（hoisted-mock ×
//  resetModules 隔离）下稳定触发 readline 链——其防护由 kernel.state.test.ts 的
//  formatKernelMenuLabel 契约 + window-controls.test.ts 的 ready 链 + rc 装机复验 M1' 组成。
describe('回归防护：内核路径来源（#187/#192 F1）', () => {
  it('#192 F1 packagedKernelPath 来源：process.resourcesPath 存在 → spawn command 为 resources/kernel 绝对路径', async () => {
    fakeChild.removeAllListeners();
    fakeChild.stdout.removeAllListeners();
    fakeChild.stderr.removeAllListeners();
    const prev = (process as { resourcesPath?: string }).resourcesPath;
    Object.defineProperty(process, 'resourcesPath', {
      value: 'C:/app/resources',
      configurable: true,
    });
    try {
      vi.resetModules();
      spawnMock.mockClear(); // import 前清旧实例累计——之后 calls[0] 即本实例生产 spawn
      appMock.isPackaged = true; // 先设再 import → boot 即走生产分支
      await import('./main');
      // boot 完成标志：spawn 已调用（生产模式 kernelStatePath=null → 无 fs/http 挂起）
      await vi.waitFor(() => {
        expect(spawnMock.mock.calls.length).toBeGreaterThan(0);
      });
      const command = spawnMock.mock.calls[0]?.[0] as string | undefined;
      expect(command).toBe(path.join('C:/app/resources', 'kernel', 'inkflow.exe'));
      // cwd 兜底：打包版 spawn cwd = exe 所在目录（#187 双保险）
      const opts = spawnMock.mock.calls[0]?.[2] as { cwd?: string } | undefined;
      expect(opts?.cwd).toBe(path.dirname(process.execPath));
    } finally {
      appMock.isPackaged = false;
      if (prev === undefined) {
        delete (process as { resourcesPath?: string }).resourcesPath;
      } else {
        Object.defineProperty(process, 'resourcesPath', { value: prev, configurable: true });
      }
    }
  });
});

// ══ F51 debug-mode：dev 测试钩子门控（打包版 + INKFLOW_DEBUG=1 时仍暴露）═══════════
// 契约（GREEN 由 Codex 实现）：
//   - updateKernelInfoHook / updateTrayInfoHook 门控改 `if (app.isPackaged && !isDebugMode()) return;`
//   - whenReady 内 `if (!app.isPackaged || isDebugMode()) { exposeTrayDevHooks(); }`
//   - isDebugMode() 读 process.env.INKFLOW_DEBUG（truthy 如 '1' 视为 debug，env 最高优先）
// RED 阶段：门控仍是 `app.isPackaged` → 打包版钩子不暴露 → 正向用例断言失败 = 有效 RED；
// 负向用例（打包版无 debug）当前实现天然满足 = 守卫（防 GREEN 过度暴露）。
// ⚠️ globalThis 钩子是模块内函数写入：文件顶部 dev 实例（isPackaged=false）启动期已写入
//   __trayInfo/__trayActions——用例前必须 delete 清理，否则负向断言受残留污染。
describe('dev 钩子门控（F51 debug-mode：打包版 + INKFLOW_DEBUG 也暴露测试钩子）', () => {
  beforeEach(() => {
    // READY 触发后 startHealthCheck 会打真实 /health —— stub fetch 杜绝真实网络（window-controls 先例）
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true })));
  });

  /** 清理跨 freshInstance 残留的 globalThis 测试钩子（默认 dev 实例启动期已写入） */
  const deleteHookGlobals = (): void => {
    delete (globalThis as { __kernelInfo?: unknown }).__kernelInfo;
    delete (globalThis as { __trayInfo?: unknown }).__trayInfo;
    delete (globalThis as { __trayActions?: unknown }).__trayActions;
  };

  it('正向：打包版 + INKFLOW_DEBUG=1 → 暴露 __trayInfo/__trayActions；READY 后暴露 __kernelInfo', async () => {
    deleteHookGlobals();
    vi.stubEnv('INKFLOW_DEBUG', '1');
    appMock.isPackaged = true;
    await freshInstance();
    await flushMicrotasks(); // whenReady 续体（createTray / exposeTrayDevHooks）跑完
    // RED：exposeTrayDevHooks 被 `if (!app.isPackaged)` 挡掉 + updateTrayInfoHook 被
    // `if (app.isPackaged)` 挡掉 → 均为 undefined → 失败 = 有效 RED（门控未改）
    expect((globalThis as { __trayInfo?: unknown }).__trayInfo).toBeDefined();
    expect((globalThis as { __trayActions?: unknown }).__trayActions).toBeDefined();
    // 内核就绪 → __kernelInfo 钩子（readline 'line' 回调同步执行，window-controls 先例）
    fakeChild.stdout.emit(
      'data',
      Buffer.from('INKFLOW_READY {"port":1,"token":"t","pid":4242,"version":"0.1.0"}\n')
    );
    await flushMicrotasks();
    const kernelHook = (globalThis as {
      __kernelInfo?: { pid: number; port: number; token: string };
    }).__kernelInfo;
    expect(kernelHook).toBeDefined();
    expect(kernelHook?.port).toBe(1);
  });

  it('负向：打包版 + 无 INKFLOW_DEBUG → 不暴露任何测试钩子（F51 门控守卫）', async () => {
    deleteHookGlobals();
    appMock.isPackaged = true;
    await freshInstance();
    await flushMicrotasks();
    expect((globalThis as { __kernelInfo?: unknown }).__kernelInfo).toBeUndefined();
    expect((globalThis as { __trayInfo?: unknown }).__trayInfo).toBeUndefined();
    expect((globalThis as { __trayActions?: unknown }).__trayActions).toBeUndefined();
  });
});

// ══ S3f-T1 F4 可观测性：INKFLOW_DEBUG 显式值门控（contract-s3f-t1 §2.6，G3 env=0）═══════
// 契约（GREEN 由 Codex 实现，contract §1.3 G3）：
//   isDebugMode env 判定改：env 显式设置（非 undefined 且非空串）时按
//   ['1','true','on']（trim+lowercase）判 true，其余（'0'/'false'/其他）判 false，
//   且【不再读 instance.env / config.json】（显式关 > instance.env=1，D8）；
//   INKFLOW_DEBUG=''（空串）→ 按未设置，继续走 instance.env / config.json 链。
// RED 基线（main.ts:128 `if (process.env.INKFLOW_DEBUG) return true`）：'0'/'false' 均 truthy
//   → 判 debug → 打包版钩子暴露 → 下方负向断言失败 = 有效 RED（G3 主语义）。
// instance.env 文件驱动：main.ts isDebugMode 经 app.getPath('appData')/InkFlow/instance.env +
//   node:fs existsSync/readFileSync（本文件未 mock node:fs）→ 测试注入 app.getPath 指向
//   mkdtemp 临时目录 + 真实写入 instance.env（纯 ASCII），免 vi.mock('node:fs') 接线。
describe('INKFLOW_DEBUG 显式值门控（S3f-T1 §2.6：env=0 > instance.env=1；空串=未设置）', () => {
  beforeEach(() => {
    // READY 触发后 startHealthCheck 会打真实 /health —— stub fetch 杜绝真实网络（window-controls 先例）
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true })));
  });

  /** 清理跨 freshInstance 残留的 globalThis 测试钩子（默认 dev 实例启动期已写入） */
  const clearHookGlobals = (): void => {
    delete (globalThis as { __kernelInfo?: unknown }).__kernelInfo;
    delete (globalThis as { __trayInfo?: unknown }).__trayInfo;
    delete (globalThis as { __trayActions?: unknown }).__trayActions;
  };

  /** 注入 app.getPath('appData') → tmp 目录（main.ts isDebugMode 读 instance.env 的锚点） */
  const stubAppDataPath = (dir: string): void => {
    (appMock as unknown as { getPath?: (name: string) => string }).getPath = vi.fn(
      () => dir
    );
  };

  /** 移除 getPath 注入（electronMock.app 是模块级单例，避免污染后续用例） */
  const unstubAppDataPath = (): void => {
    delete (appMock as unknown as { getPath?: (name: string) => string }).getPath;
  };

  /**
   * 建临时 appData 目录；instanceEnvBody 提供时写入 InkFlow/instance.env（真实 node:fs——
   * main.ts 未 mock node:fs，existsSync/readFileSync 直读真实文件；内容纯 ASCII）。
   */
  const makeAppDataDir = async (
    instanceEnvBody?: string
  ): Promise<{ dir: string; cleanup: () => void }> => {
    const nodeOs = await import('node:os');
    const nodeFs = await import('node:fs');
    const dir = nodeFs.mkdtempSync(path.join(nodeOs.tmpdir(), 'inkflow-tray-debug-'));
    if (instanceEnvBody !== undefined) {
      nodeFs.mkdirSync(path.join(dir, 'InkFlow'), { recursive: true });
      nodeFs.writeFileSync(path.join(dir, 'InkFlow', 'instance.env'), instanceEnvBody, 'utf8');
    }
    return {
      dir,
      cleanup: () => {
        try {
          nodeFs.rmSync(dir, { recursive: true, force: true });
        } catch {
          // Windows 偶发句柄占用：临时目录清理失败不阻塞断言
        }
      },
    };
  };

  /** 打包版 boot 到内核 READY（发射 INKFLOW_READY → updateKernelInfoHook 路径执行） */
  const bootPackagedToReady = async (): Promise<void> => {
    await freshInstance();
    await flushMicrotasks(); // whenReady 续体（createTray / exposeTrayDevHooks）跑完
    fakeChild.stdout.emit(
      'data',
      Buffer.from('INKFLOW_READY {"port":1,"token":"t","pid":4242,"version":"0.1.0"}\n')
    );
    await flushMicrotasks(); // updateKernelInfoHook 执行（debug 时会写 __kernelInfo）
  };

  it('【R】打包版 + INKFLOW_DEBUG=0（显式关）→ 不暴露任何测试钩子（G3：现实现把 0 当 true → FAIL）', async () => {
    // 纯 env 语义：无 instance.env / config.json 参与（GREEN 后在 env 分支即终止）
    clearHookGlobals();
    vi.stubEnv('INKFLOW_DEBUG', '0');
    appMock.isPackaged = true;
    try {
      await bootPackagedToReady();
      expect((globalThis as { __trayInfo?: unknown }).__trayInfo).toBeUndefined();
      expect((globalThis as { __trayActions?: unknown }).__trayActions).toBeUndefined();
      expect((globalThis as { __kernelInfo?: unknown }).__kernelInfo).toBeUndefined();
    } finally {
      appMock.isPackaged = false;
    }
  });

  it('【R】打包版 + INKFLOW_DEBUG=false（显式关，1.3 显式值表）→ 不暴露任何测试钩子（现实现 truthy → FAIL）', async () => {
    clearHookGlobals();
    vi.stubEnv('INKFLOW_DEBUG', 'false');
    appMock.isPackaged = true;
    try {
      await bootPackagedToReady();
      expect((globalThis as { __trayInfo?: unknown }).__trayInfo).toBeUndefined();
      expect((globalThis as { __trayActions?: unknown }).__trayActions).toBeUndefined();
      expect((globalThis as { __kernelInfo?: unknown }).__kernelInfo).toBeUndefined();
    } finally {
      appMock.isPackaged = false;
    }
  });

  it('【G】打包版 + INKFLOW_DEBUG=""（空串 = 按未设置）+ instance.env 不存在 → 不暴露（守卫）', async () => {
    const appData = await makeAppDataDir(); // instance.env 不存在 → 链回退 false
    try {
      clearHookGlobals();
      stubAppDataPath(appData.dir);
      vi.stubEnv('INKFLOW_DEBUG', '');
      appMock.isPackaged = true;
      await bootPackagedToReady();
      expect((globalThis as { __trayInfo?: unknown }).__trayInfo).toBeUndefined();
      expect((globalThis as { __trayActions?: unknown }).__trayActions).toBeUndefined();
      expect((globalThis as { __kernelInfo?: unknown }).__kernelInfo).toBeUndefined();
    } finally {
      appMock.isPackaged = false;
      unstubAppDataPath();
      appData.cleanup();
    }
  });

  it('【R】打包版 + INKFLOW_DEBUG=0 + instance.env INKFLOW_DEBUG=1 → 不暴露（env 显式关 > instance.env，D8）', async () => {
    // 契约主场景：instance.env=1 存在也不得翻盘——GREEN 后 env 分支终止不再读 instance.env；
    // RED 现实现 '0' truthy 判 debug → 暴露 → FAIL
    const appData = await makeAppDataDir('INKFLOW_DEBUG=1\n');
    try {
      clearHookGlobals();
      stubAppDataPath(appData.dir);
      vi.stubEnv('INKFLOW_DEBUG', '0');
      appMock.isPackaged = true;
      await bootPackagedToReady();
      expect((globalThis as { __trayInfo?: unknown }).__trayInfo).toBeUndefined();
      expect((globalThis as { __trayActions?: unknown }).__trayActions).toBeUndefined();
      expect((globalThis as { __kernelInfo?: unknown }).__kernelInfo).toBeUndefined();
    } finally {
      appMock.isPackaged = false;
      unstubAppDataPath();
      appData.cleanup();
    }
  });
});
