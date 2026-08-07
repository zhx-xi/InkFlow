/**
 * 主进程菜单移除测试契约（#98 Electron 菜单栏移除，RED 阶段）
 *
 * 契约来源：specs/f19-gui/spec.md §5.2.9 / §5.3 / §5.5 M9
 *   - Menu.setApplicationMenu(null) 彻底移除默认菜单栏（含 Alt 唤出通道），生产/开发模式一致；
 *   - 开发模式（app.isPackaged === false）显式注册 F12 / Ctrl+Shift+I 调
 *     webContents.openDevTools()（无菜单后默认加速键失效，需显式注册）；生产模式不注册。
 *
 * 被测模块 src/main.ts 新增模块级函数 setupAppMenu(isPackaged: boolean): void
 * （RED 阶段不存在 → 预期 import 失败），GREEN 由 Codex 按本契约实现并接入
 * app.whenReady().then(() => { setupAppMenu(app.isPackaged); ... })。§5.3 锁定
 * 实现落点 = main.ts（MODIFY），不新增文件。
 *
 * 设计假设（GREEN 必须匹配）：
 * 1. 签名：setupAppMenu(isPackaged: boolean): void —— isPackaged 注入式传入，
 *    不读 app.isPackaged（避免测试 mock app 全局；与 kernel.ts 注入式风格一致）；
 * 2. 两个模式都调用 Menu.setApplicationMenu(null)（§5.2.9「彻底移除」无模式差异）；
 * 3. 开发模式（isPackaged=false）：globalShortcut.register('F12', cb) 与
 *    globalShortcut.register('Ctrl+Shift+I', cb) 各恰好一次，且仅此两个 accelerator；
 *    cb = () => BrowserWindow.getFocusedWindow()?.webContents.openDevTools()
 *    （?. 短路：无聚焦窗口时静默不抛）；
 * 4. 幂等：模块级已注册 accelerator 集合去重——重复调用 setupAppMenu 不重复注册
 *    （register 总调用次数不增长），且不抛错；
 * 5. 容错：globalShortcut.register 返回 false（注册失败）时静默忽略，不抛异常；
 * 6. 返回值 void。
 *
 * mock 说明：vi.mock('electron') 提供 app/BrowserWindow/Menu/globalShortcut/dialog
 * 最小面；app.whenReady mock 为永不 resolve 的 Promise——import './main' 时顶层
 * whenReady().then(createMainWindow/spawnKernel) 不会执行，杜绝真实 spawn/定时器副作用。
 */
import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest';
import { Menu, globalShortcut, BrowserWindow } from 'electron';
import { setupAppMenu } from './main';

const electronMock = vi.hoisted(() => {
  const openDevTools = vi.fn();
  const focusedWindow = { webContents: { openDevTools } };
  return {
    __focusedWindow: focusedWindow,
    app: {
      isPackaged: false,
      whenReady: vi.fn(() => new Promise<void>(() => {})),
      on: vi.fn(),
      exit: vi.fn(),
    },
    BrowserWindow: Object.assign(
      vi.fn(() => ({
        on: vi.fn(),
        setTitle: vi.fn(),
        isDestroyed: () => false,
        webContents: { on: vi.fn(), send: vi.fn() },
        loadFile: vi.fn(() => Promise.resolve()),
      })),
      { getFocusedWindow: vi.fn(() => focusedWindow) }
    ),
    Menu: { setApplicationMenu: vi.fn(), buildFromTemplate: vi.fn(() => ({ popup: vi.fn() })) },
    globalShortcut: { register: vi.fn(() => true), unregisterAll: vi.fn() },
    dialog: { showMessageBox: vi.fn(() => Promise.resolve({ response: 0 })) },
    // #167 F31：main.ts 顶层 import Tray/nativeImage/requestSingleInstanceLock——
    // mock 必须提供导出，否则 vitest 报 "No Tray export"（本文件不触发启动回调，仅满足 import）
    Tray: vi.fn(() => ({ setContextMenu: vi.fn(), on: vi.fn(), destroy: vi.fn() })),
    nativeImage: { createFromPath: vi.fn(() => ({ isEmpty: () => false })) },
    ipcMain: { on: vi.fn(), handle: vi.fn() },
  };
});

vi.mock('electron', () => electronMock);

const focusedWindow = electronMock.__focusedWindow as unknown as {
  webContents: { openDevTools: Mock };
};

describe('setupAppMenu（菜单移除 + DevTools 快捷键，spec §5.2.9 / M9）', () => {
  beforeEach(() => {
    vi.mocked(Menu.setApplicationMenu).mockClear();
    vi.mocked(globalShortcut.register).mockClear();
    vi.mocked(BrowserWindow.getFocusedWindow).mockClear();
    focusedWindow.webContents.openDevTools.mockClear();
  });

  it('生产模式（isPackaged=true）：Menu.setApplicationMenu(null) 被调用，且零快捷键注册', () => {
    expect(setupAppMenu(true)).toBeUndefined();
    expect(Menu.setApplicationMenu).toHaveBeenCalledTimes(1);
    expect(Menu.setApplicationMenu).toHaveBeenCalledWith(null);
    expect(globalShortcut.register).not.toHaveBeenCalled();
  });

  it('开发模式（isPackaged=false）：菜单同样移除，且恰好注册 F12 与 Ctrl+Shift+I', () => {
    setupAppMenu(false);
    expect(Menu.setApplicationMenu).toHaveBeenCalledWith(null);
    const accelerators = vi
      .mocked(globalShortcut.register)
      .mock.calls.map((call) => call[0]);
    expect(accelerators).toHaveLength(2);
    expect(accelerators).toEqual(expect.arrayContaining(['F12', 'Ctrl+Shift+I']));
  });

  it('dev 快捷键 callback：调 BrowserWindow.getFocusedWindow()?.webContents.openDevTools()', () => {
    setupAppMenu(false);
    const callbacks = vi
      .mocked(globalShortcut.register)
      .mock.calls.map((call) => call[1] as () => void);
    expect(callbacks).toHaveLength(2);
    for (const cb of callbacks) {
      cb();
    }
    expect(BrowserWindow.getFocusedWindow).toHaveBeenCalledTimes(2);
    expect(focusedWindow.webContents.openDevTools).toHaveBeenCalledTimes(2);
  });

  it('无聚焦窗口（getFocusedWindow 返回 null）：callback 不抛异常（?. 容错）', () => {
    vi.mocked(BrowserWindow.getFocusedWindow).mockReturnValueOnce(null);
    setupAppMenu(false);
    const cb = vi.mocked(globalShortcut.register).mock.calls[0][1] as () => void;
    expect(() => cb()).not.toThrow();
  });

  it('幂等：重复调用 setupAppMenu 不重复注册快捷键、不抛错', () => {
    expect(() => {
      setupAppMenu(false);
      setupAppMenu(false);
    }).not.toThrow();
    expect(globalShortcut.register).toHaveBeenCalledTimes(2);
  });

  it('容错：globalShortcut.register 返回 false（注册失败）不抛异常', () => {
    vi.mocked(globalShortcut.register).mockReturnValue(false);
    expect(() => setupAppMenu(false)).not.toThrow();
    expect(globalShortcut.register).toHaveBeenCalledTimes(2);
  });
});
