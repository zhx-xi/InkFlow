/**
 * 主进程窗口控制 IPC 测试契约（#106 自绘窗口控制按钮，RED 阶段）
 *
 * 契约来源：specs/f19-gui/spec.md §3.4（renderer 契约）；#106 用户拍板自绘窗口控制按钮。
 * 被测模块 src/main.ts 的 registerWindowControlsHandlers()（L399-407）：
 *   - ipcMain.on('window:minimize')        → mainWindow?.minimize()
 *   - ipcMain.on('window:toggle-maximize') → !mainWindow 短路；isMaximized() ? unmaximize() : maximize()
 *   - ipcMain.on('window:close')           → mainWindow?.close()
 *
 * 与 main.menu.test.ts 的关键差异（必须理解的 mock 设计）：
 * - registerWindowControlsHandlers / createMainWindow 均未 export，mainWindow 是模块级
 *   变量——三个 handler 只在 app.whenReady().then() 启动回调内注册。因此本文件让
 *   whenReady **立即 resolve**：import './main' 时完整执行启动回调（注册 IPC +
 *   createMainWindow 给 mainWindow 赋值 + spawnKernel）。
 * - main.menu.test.ts 用「永不 resolve」规避的真实 spawn 副作用，本文件用
 *   vi.mock('node:child_process') 杜绝：spawn 返回惰性假 child（迷你 EventEmitter，
 *   永不自动 emit）——无真实进程、无网络、无 stdout 输出。
 * - 模块级单向状态（stopping/quitInProgress/kernelProcess/consecutiveFailures）——
 *   失败/退出路径用例组用 vi.resetModules() + 动态 import 换新模块实例（状态归零、
 *   ipcMain.on 调用记录清空、consecutiveFailures 从 0 起，退避延迟 1000/2000/4000/
 *   8000/16000ms 精确可控）。⚠️ resetModules 会清空 vi.mock 的调用记录（实测）。
 * - 「mainWindow 为 null 容错」用例放在文件最后（依赖声明顺序，vitest 默认串行）。
 */
import { describe, it, expect, beforeAll, beforeEach, afterEach, afterAll, vi, type Mock } from 'vitest';
import { app, dialog, ipcMain } from 'electron';
import { parseReadyLine } from './kernel';
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

  // createMainWindow 的事件 handler 存储（按事件名，测试手动触发）
  const windowEventHandlers: Record<string, AnyHandler> = {};
  const webContentsEventHandlers: Record<string, AnyHandler> = {};
  const appEventHandlers: Record<string, AnyHandler> = {};

  const win = {
    minimize: vi.fn(),
    unmaximize: vi.fn(),
    maximize: vi.fn(),
    close: vi.fn(),
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

  // #167 F31：main.ts 新增 Tray/nativeImage import（托盘常驻）——mock 必须提供对应导出，
  // 否则 vitest 报 "No Tray export is defined on the electron mock"（B2 后 19 errors 实测）。
  // 本文件不测托盘行为（main.tray.test.ts 专责），最小 stub 满足 import 即可。
  const trayStub = { setContextMenu: vi.fn(), on: vi.fn(), destroy: vi.fn() };

  return {
    __win: win,
    __windowEventHandlers: windowEventHandlers,
    __webContentsEventHandlers: webContentsEventHandlers,
    __appEventHandlers: appEventHandlers,
    __fakeChild: fakeChild,
    __spawn: vi.fn(() => fakeChild),
    app: {
      isPackaged: false,
      whenReady: vi.fn(() => Promise.resolve()),
      on: vi.fn((evt: string, cb: AnyHandler) => {
        appEventHandlers[evt] = cb;
      }),
      exit: vi.fn(),
      quit: vi.fn(),
      // #167 F31：单实例锁（main.ts 启动回调最先调用；默认 true 走正常路径）
      requestSingleInstanceLock: vi.fn(() => true),
      setAppUserModelId: vi.fn(),
    },
    BrowserWindow: Object.assign(vi.fn(() => win), {
      getFocusedWindow: vi.fn(() => null),
    }),
    ipcMain: { on: vi.fn(), handle: vi.fn() },
    Menu: { setApplicationMenu: vi.fn(), buildFromTemplate: vi.fn(() => ({ popup: vi.fn() })) },
    globalShortcut: { register: vi.fn(() => true), unregisterAll: vi.fn() },
    dialog: { showMessageBox: vi.fn(() => Promise.resolve({ response: 0 })) },
    Tray: vi.fn(() => trayStub),
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
  isMaximized: Mock;
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
const appMock = electronMock.app as { isPackaged: boolean };

const READY_LINE = (port: number, token: string): string =>
  `INKFLOW_READY {"port":${port},"token":"${token}","pid":7,"version":"0.1.0"}\n`;

/** 触发一次 INKFLOW_READY（line 回调同步执行；kernelProcess 必须 === child 才生效） */
const emitReady = (port = 51234, token = 'a'): void => {
  fakeChild.stdout.emit('data', Buffer.from(READY_LINE(port, token)));
};

/** 内核 spawn 调用次数（排除 killProcessTree 的 taskkill 干扰） */
const kernelSpawnCount = (): number =>
  spawnMock.mock.calls.filter((c: unknown[]) => c[0] !== 'taskkill').length;

/** 新模块实例（状态归零：consecutiveFailures/kernelProcess/stopping/quitInProgress）。
 *  ⚠️ fakeChild 的 emitter 是 hoisted 单例：旧实例 spawnKernel 注册的事件回调会跨实例
 *  累积（emit 触发多组回调 → kill/spawn 计数爆炸，实测）——必须先 removeAllListeners
 *  清掉旧回调，再 resetModules + import（新实例注册自己的回调）。 */
const freshInstance = async (): Promise<void> => {
  fakeChild.removeAllListeners();
  fakeChild.stdout.removeAllListeners();
  fakeChild.stderr.removeAllListeners();
  vi.resetModules();
  await import('./main');
};

type IpcHandler = (event: unknown, ...args: unknown[]) => void;
let minimizeHandler: IpcHandler;
let toggleMaximizeHandler: IpcHandler;
let closeHandler: IpcHandler;

beforeAll(() => {
  // 启动回调已在 import 时执行（whenReady 立即 resolve）→ 从 ipcMain.on 注册记录取 handler
  const onMock = vi.mocked(ipcMain.on);
  minimizeHandler = onMock.mock.calls.find((c) => c[0] === 'window:minimize')?.[1] as unknown as IpcHandler;
  toggleMaximizeHandler = onMock.mock.calls.find(
    (c) => c[0] === 'window:toggle-maximize'
  )?.[1] as unknown as IpcHandler;
  closeHandler = onMock.mock.calls.find((c) => c[0] === 'window:close')?.[1] as unknown as IpcHandler;
  expect(minimizeHandler).toBeDefined();
  expect(toggleMaximizeHandler).toBeDefined();
  expect(closeHandler).toBeDefined();
});

beforeEach(() => {
  win.minimize.mockClear();
  win.unmaximize.mockClear();
  win.maximize.mockClear();
  win.close.mockClear();
  win.setTitle.mockClear();
  win.webContents.send.mockClear();
  vi.mocked(app.exit).mockClear();
  // mockClear 不重置实现：显式复位 isMaximized 默认 false（mockReset 会清掉默认实现）
  win.isMaximized.mockReset();
  win.isMaximized.mockReturnValue(false);
  // 假 child / app 属性复位（分支用例会改）
  fakeChild.pid = 4242;
  fakeChild.exitCode = null;
  appMock.isPackaged = false;
});

describe('registerWindowControlsHandlers（#106 自绘窗口控制按钮 IPC 注册）', () => {
  it('启动时注册 window:minimize / window:toggle-maximize / window:close 三个 IPC 通道', () => {
    const channels = vi.mocked(ipcMain.on).mock.calls.map((c) => c[0]);
    expect(channels).toEqual(['window:minimize', 'window:toggle-maximize', 'window:close']);
  });

  it('window:minimize handler：mainWindow.minimize() 被调用（mainWindow 已设置）', () => {
    minimizeHandler(null);
    expect(win.minimize).toHaveBeenCalledTimes(1);
  });

  it('window:toggle-maximize handler：isMaximized()=true → unmaximize()（还原分支）', () => {
    win.isMaximized.mockReturnValue(true);
    toggleMaximizeHandler(null);
    expect(win.isMaximized).toHaveBeenCalledTimes(1);
    expect(win.unmaximize).toHaveBeenCalledTimes(1);
    expect(win.maximize).not.toHaveBeenCalled();
  });

  it('window:toggle-maximize handler：isMaximized()=false → maximize()（最大化分支）', () => {
    toggleMaximizeHandler(null);
    expect(win.isMaximized).toHaveBeenCalledTimes(1);
    expect(win.maximize).toHaveBeenCalledTimes(1);
    expect(win.unmaximize).not.toHaveBeenCalled();
  });

  it('window:close handler：mainWindow.close() 被调用', () => {
    closeHandler(null);
    expect(win.close).toHaveBeenCalledTimes(1);
  });
});

describe('createMainWindow 窗口事件联动（#106 状态推送 / 标题固定 / 导航拦截）', () => {
  it('maximize/unmaximize/ready-to-show → webContents.send("window:maximized-changed", isMaximized())', () => {
    win.isMaximized.mockReturnValue(true);
    windowEventHandlers['maximize']?.(null);
    windowEventHandlers['unmaximize']?.(null);
    windowEventHandlers['ready-to-show']?.(null);
    expect(win.webContents.send).toHaveBeenCalledTimes(3);
    expect(win.webContents.send).toHaveBeenCalledWith('window:maximized-changed', true);
  });

  it('page-title-updated → event.preventDefault() + setTitle("InkFlow")（固定窗口标题）', () => {
    const event = { preventDefault: vi.fn() };
    windowEventHandlers['page-title-updated']?.(event, 'Hacker Title');
    expect(event.preventDefault).toHaveBeenCalledTimes(1);
    expect(win.setTitle).toHaveBeenCalledWith('InkFlow');
  });

  it('will-navigate 非 file:// URL → event.preventDefault()（§3.3 防钓鱼）', () => {
    const event = { preventDefault: vi.fn() };
    webContentsEventHandlers['will-navigate']?.(event, 'https://evil.example.com');
    expect(event.preventDefault).toHaveBeenCalledTimes(1);
  });

  it('will-navigate file:// URL → 不拦截（本地页面正常导航）', () => {
    const event = { preventDefault: vi.fn() };
    webContentsEventHandlers['will-navigate']?.(
      event,
      'file:///C:/InkFlow/renderer/dist/index.html'
    );
    expect(event.preventDefault).not.toHaveBeenCalled();
  });

  it('did-finish-load → 补发最大化状态；pendingReadyPayload 为空时不发 inkflow:ready', () => {
    webContentsEventHandlers['did-finish-load']?.(null);
    expect(win.webContents.send).toHaveBeenCalledTimes(1);
    expect(win.webContents.send).toHaveBeenCalledWith('window:maximized-changed', false);
    expect(win.webContents.send).not.toHaveBeenCalledWith('inkflow:ready', expect.anything());
  });
});

/**
 * 内核启动/失败/退出路径（boot 副作用隔离下的覆盖率补全）。
 * 关键约束（全部实测）：
 * - line 回调有 `if (kernelProcess !== child) return` 守卫：README 前 kernelProcess
 *   必须 === child；失败用例（onKernelFailure 清 kernelProcess）后必须 advance 到
 *   restartTimer 触发（spawnKernel 恢复 kernelProcess）。
 * - 退避延迟递增（1000/2000/4000/8000/16000ms），advance 必须精确匹配当前失败序号；
 *   ≥6 次失败走错误对话框（response=0 → 重置计数并直接重启）。
 * - 失败/退出路径用例组用 freshInstance()（resetModules + 动态 import）换新模块实例，
 *   组内 consecutiveFailures 从 0 起、kernelProcess 恒 === child，精确可控。
 * - multiple readline 并发会重建 kernelInfo（新对象）→ checkHealthOnce 的换代守卫
 *   （kernelInfo !== info）会误判 return——READY 后的首次健康检查可能不计入失败计数，
 *   健康失败用例按「tick 计失败」设计。
 * - resetModules 会清空 vi.mock 的调用记录（ipcMain.on.mock.calls 归零，实测）。
 */
describe('内核启动/失败/退出路径（boot 全量执行）', () => {
  let fetchMock: Mock;

  beforeAll(() => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  beforeEach(() => {
    fetchMock = vi.fn(() => Promise.resolve({ ok: true }));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    delete process.env.INKFLOW_KERNEL_CMD;
    vi.mocked(dialog.showMessageBox).mockResolvedValue({ response: 0 });
    appMock.isPackaged = false;
  });

  afterAll(() => {
    vi.restoreAllMocks();
  });

  // #892 kernel_ready 上报：READY 路径的 fetch 分两类——/health 健康检查 与 /api/v1/logs
  // 日志上报。计数断言统一按 URL 过滤：新增上报 fetch 不翻红既有健康检查计数（保语义不绑实现）。
  const fetchCallsTo = (mock: Mock, urlPart: string): unknown[][] =>
    mock.mock.calls.filter((c) => String(c[0]).includes(urlPart));
  /** /health 健康检查 fetch 次数（不含 /api/v1/logs 日志上报） */
  const healthFetchCount = (mock: Mock): number => fetchCallsTo(mock, '/health').length;
  /** /api/v1/logs 日志上报调用（kernel_ready 等主进程事件上报，body 为 MainLogRecord JSON） */
  const logReportCalls = (mock: Mock): unknown[][] => fetchCallsTo(mock, '/api/v1/logs');

  // ── 组 A：READY 路径（第一个实例，无重启 → 单一 readline）──

  it('INKFLOW_READY 行 → kernelInfo/__kernelInfo 钩子/inkflow:ready 推送/健康检查启动', async () => {
    emitReady(51234, 't0k3n');
    await Promise.resolve();
    expect((globalThis as { __kernelInfo?: unknown }).__kernelInfo).toEqual({
      pid: 4242,
      port: 51234,
      token: 't0k3n',
    });
    expect(win.webContents.send).toHaveBeenCalledWith('inkflow:ready', {
      baseURL: 'http://127.0.0.1:51234',
      token: 't0k3n',
    });
    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:51234/health',
      expect.objectContaining({ headers: { 'X-InkFlow-Token': 't0k3n' } })
    );
  });

  it('did-finish-load → pendingReadyPayload 非空时重发 inkflow:ready', async () => {
    emitReady(51234, 't0k3n');
    await Promise.resolve();
    win.webContents.send.mockClear();
    webContentsEventHandlers['did-finish-load']?.(null);
    expect(win.webContents.send).toHaveBeenCalledWith('inkflow:ready', {
      baseURL: 'http://127.0.0.1:51234',
      token: 't0k3n',
    });
    expect(win.webContents.send).toHaveBeenCalledWith('window:maximized-changed', false);
  });

  it('畸形行（非 INKFLOW_READY）→ parseReadyLine 返回 null 静默跳过', async () => {
    fakeChild.stdout.emit('data', Buffer.from('some garbage line\n'));
    await Promise.resolve();
    expect(win.webContents.send).not.toHaveBeenCalled();
  });

  it('第二次 INKFLOW_READY → startHealthCheck 重入（重建 interval）', async () => {
    // #892：READY 路径新增 /api/v1/logs 上报 fetch 后全局计数会翻红 → 按 /health 过滤。
    // 语义不变：两次 READY 各触发 1 次健康检查（不统计健康检查之外的 fetch）。
    const before = healthFetchCount(fetchMock);
    emitReady(51234, 'a');
    await Promise.resolve();
    emitReady(59999, 'b');
    await Promise.resolve();
    expect(healthFetchCount(fetchMock)).toBe(before + 2);
    expect((globalThis as { __kernelInfo?: unknown }).__kernelInfo).toEqual({
      pid: 4242,
      port: 59999,
      token: 'b',
    });
  });

  // ── 组 A2：kernel_ready 成功态上报（#892，新实例）──
  //
  // 契约（用户批准方案 B）：READY 成功 → sendReadyToRenderer 设置上报端点后经 mainLogger 上报
  // info 级 record（event=kernel_ready / message_key=log.event.kernel_ready / params={port,pid}）；
  // pending/failed/spawn 前不上报成功态。断言锚定 fetch 调用（/api/v1/logs），不绑 console 文本。
  // RED 现状：main.ts 成功态仅 console.log → 正向/重复用例 FAIL；负向为守护用例（防 GREEN 过度上报）。

  it('INKFLOW_READY 成功态 → 上报 kernel_ready（POST /api/v1/logs，端点随本次 READY 设置后即上报）', async () => {
    vi.useFakeTimers();
    await freshInstance();
    emitReady(51234, 't0k3n');
    await vi.advanceTimersByTimeAsync(0);
    const logCalls = logReportCalls(fetchMock);
    expect(logCalls).toHaveLength(1); // RED 锚点：现实现成功态不上报 → 0 条
    const [url, init] = logCalls[0] as unknown as [string, RequestInit];
    expect(url).toBe('http://127.0.0.1:51234/api/v1/logs');
    expect(init.method).toBe('POST');
    const headers = init.headers as Headers;
    expect(headers.get('X-InkFlow-Token')).toBe('t0k3n'); // 端点 token 透传
    const body = JSON.parse(String(init.body)) as {
      level: string;
      caller_type: string;
      caller_name: string;
      event: string;
      message_key: string;
      params: { port: number; pid: number };
      correlation_id: string;
      timestamp: string;
    };
    expect(body).toMatchObject({
      level: 'info',
      caller_type: 'frontend',
      caller_name: 'electron.main',
      event: 'kernel_ready',
      message_key: 'log.event.kernel_ready',
      // pid 取 kernelInfo.pid（mock child.pid=4242，优先于 READY 行内 pid:7）
      params: { port: 51234, pid: 4242 },
    });
    expect(body.correlation_id.length).toBeGreaterThan(0);
    expect(headers.get('X-Correlation-Id')).toBe(body.correlation_id); // 请求头与记录关联 id 一致
    expect(Number.isNaN(Date.parse(body.timestamp))).toBe(false);
  });

  it('READY 之前（boot 仅 spawn）→ 不上报成功态（/api/v1/logs 零调用；守护用例）', async () => {
    vi.useFakeTimers();
    await freshInstance();
    await vi.advanceTimersByTimeAsync(0);
    // 健康检查在 READY 后才启动 → 无 READY 即无任何上报 fetch（pending 不触发成功态）
    expect(logReportCalls(fetchMock)).toHaveLength(0);
  });

  it('重复 INKFLOW_READY（换端口）→ 每次成功态各上报一条，port 跟随新值', async () => {
    vi.useFakeTimers();
    await freshInstance();
    emitReady(51234, 'a');
    await vi.advanceTimersByTimeAsync(0);
    emitReady(59999, 'b');
    await vi.advanceTimersByTimeAsync(0);
    const logCalls = logReportCalls(fetchMock);
    expect(logCalls).toHaveLength(2); // RED 锚点：现实现 0 条
    expect(logCalls.map((c) => String(c[0]))).toEqual([
      'http://127.0.0.1:51234/api/v1/logs',
      'http://127.0.0.1:59999/api/v1/logs',
    ]);
    for (const [i, call] of logCalls.entries()) {
      const body = JSON.parse(String((call[1] as RequestInit).body)) as {
        level: string;
        params: { port: number };
      };
      expect(body.level).toBe('info');
      expect(body.params.port).toBe(i === 0 ? 51234 : 59999);
    }
  });

  // ── 组 B：spawn error（新实例，fail 1→2 精确）──

  it('spawn error 事件 → onKernelFailure（!stopping 分支）→ 退避重启', async () => {
    vi.useFakeTimers();
    await freshInstance();
    const killBefore = fakeChild.kill.mock.calls.length;
    const spawnBefore = kernelSpawnCount();
    fakeChild.emit('error', new Error('ENOENT')); // 失败 #1 → restartTimer@1000
    await vi.advanceTimersByTimeAsync(1_000);
    expect(fakeChild.kill.mock.calls.length).toBe(killBefore + 1);
    expect(kernelSpawnCount()).toBe(spawnBefore + 1);
  });

  it('exit 事件 → onKernelFailure（失败 #2，退避 2000ms）→ 重启', async () => {
    vi.useFakeTimers();
    // 延续组 B 实例：失败计数已到 1 → 本次为失败 #2（退避 2000ms）
    const killBefore = fakeChild.kill.mock.calls.length;
    const spawnBefore = kernelSpawnCount();
    fakeChild.emit('exit', 1, null);
    await vi.advanceTimersByTimeAsync(2_000);
    expect(fakeChild.kill.mock.calls.length).toBe(killBefore + 1);
    expect(kernelSpawnCount()).toBe(spawnBefore + 1);
  });

  // ── 组 C：INKFLOW_KERNEL_CMD 分支（新实例，fail 1→2 精确）──

  it('INKFLOW_KERNEL_CMD 绝对路径 → 直接 spawn（isAbsolute 分支）', async () => {
    vi.useFakeTimers();
    await freshInstance();
    process.env.INKFLOW_KERNEL_CMD = 'C:\\Windows\\System32\\notepad.exe --help';
    const killBefore = fakeChild.kill.mock.calls.length;
    const spawnBefore = kernelSpawnCount();
    fakeChild.emit('exit', 1, null); // 失败 #1 → restartTimer@1000
    await vi.advanceTimersByTimeAsync(1_000);
    expect(fakeChild.kill.mock.calls.length).toBe(killBefore + 1);
    expect(kernelSpawnCount()).toBe(spawnBefore + 1);
    expect(spawnMock.mock.calls[spawnMock.mock.calls.length - 1][0]).toBe(
      'C:\\Windows\\System32\\notepad.exe'
    );
    expect(spawnMock.mock.calls[spawnMock.mock.calls.length - 1][1]).toEqual(['--help']);
  });

  it('INKFLOW_KERNEL_CMD 相对路径且文件存在 → 解析为绝对路径（existsSync 分支）', async () => {
    vi.useFakeTimers();
    // 相对路径在 REPO_ROOT（f19-gui-models）下存在 → 第一次迭代 existsSync true
    process.env.INKFLOW_KERNEL_CMD = 'frontend/packages/electron/package.json';
    const killBefore = fakeChild.kill.mock.calls.length;
    const spawnBefore = kernelSpawnCount();
    fakeChild.emit('exit', 1, null); // 失败 #2 → restartTimer@2000
    await vi.advanceTimersByTimeAsync(2_000);
    expect(fakeChild.kill.mock.calls.length).toBe(killBefore + 1);
    expect(kernelSpawnCount()).toBe(spawnBefore + 1);
    expect(String(spawnMock.mock.calls[spawnMock.mock.calls.length - 1][0])).toMatch(
      /package\.json$/
    );
  });

  it('INKFLOW_KERNEL_CMD 相对路径不存在 → 循环穷尽后原样返回（existsSync 全 false）', async () => {
    vi.useFakeTimers();
    process.env.INKFLOW_KERNEL_CMD = 'nonexistent-dir/fake-kernel.exe';
    const spawnBefore = kernelSpawnCount();
    fakeChild.emit('exit', 1, null); // 失败 #3 → restartTimer@4000
    await vi.advanceTimersByTimeAsync(4_000);
    expect(kernelSpawnCount()).toBe(spawnBefore + 1);
    expect(String(spawnMock.mock.calls[spawnMock.mock.calls.length - 1][0])).toBe(
      'nonexistent-dir/fake-kernel.exe'
    );
  });

  // ── 组 D：健康检查（新实例）──

  it('连续 3 次健康检查失败 → onKernelFailure（阈值分支）→ 退避重启', async () => {
    vi.useFakeTimers();
    await freshInstance();
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: false })));
    const killBefore = fakeChild.kill.mock.calls.length;
    const spawnBefore = kernelSpawnCount();
    emitReady(51234, 'a');
    await vi.advanceTimersByTimeAsync(0); // 立即检查 → 失败 1（单 readline，无并发误判）
    await vi.advanceTimersByTimeAsync(2_000); // tick 1 → 失败 2
    await vi.advanceTimersByTimeAsync(2_000); // tick 2 → 失败 3 → 达阈值 → onKernelFailure
    expect(fakeChild.kill.mock.calls.length).toBe(killBefore + 1);
    await vi.advanceTimersByTimeAsync(1_000); // 失败 #1 退避 → spawn
    expect(kernelSpawnCount()).toBe(spawnBefore + 1);
  });

  it('健康检查挂起（in-flight）→ interval tick 不重叠；内核换代 → 旧结果作废', async () => {
    vi.useFakeTimers();
    await freshInstance();
    let resolveFetch!: (v: { ok: boolean }) => void;
    const holdingFetch = vi.fn(
      () => new Promise<{ ok: boolean }>((resolve) => (resolveFetch = resolve))
    );
    vi.stubGlobal('fetch', holdingFetch);
    emitReady(51234, 'a');
    await vi.advanceTimersByTimeAsync(0); // 立即检查挂起（healthInFlight=true）
    emitReady(59999, 'b'); // 内核换代 → 新 checkHealthOnce 被 in-flight 挡掉（不发起 fetch）
    await vi.advanceTimersByTimeAsync(2_000); // tick 同样被挡
    expect(healthFetchCount(holdingFetch)).toBe(1); // #892：/health 过滤，容忍 kernel_ready 上报 fetch
    resolveFetch({ ok: true }); // 旧请求返回 → kernelInfo !== info → 结果作废
    await vi.advanceTimersByTimeAsync(0);
    expect(healthFetchCount(holdingFetch)).toBe(1);
  });

  it('健康检查 fetch 抛异常 → catch 分支累计失败计数，3 次后触发失败处理（不崩溃）', async () => {
    vi.useFakeTimers();
    await freshInstance();
    const failingFetch = vi.fn(() => Promise.reject(new Error('ECONNREFUSED')));
    vi.stubGlobal('fetch', failingFetch);
    const killBefore = fakeChild.kill.mock.calls.length;
    const spawnBefore = kernelSpawnCount();
    emitReady(51234, 'a');
    await vi.advanceTimersByTimeAsync(0); // 立即检查 → 失败 1（reject → catch → ok=false）
    expect(healthFetchCount(failingFetch)).toBe(1); // #892：/health 过滤，容忍 kernel_ready 上报 fetch
    // ⚠️ 补强（#524）：reject 路径与组 D 的 ok:false 路径共享同一 onKernelFailure——
    // 连续 3 次失败 → kill + 退避重启（删 catch / catch 静默吞掉此处变红）
    await vi.advanceTimersByTimeAsync(2_000); // tick 1 → 失败 2
    await vi.advanceTimersByTimeAsync(2_000); // tick 2 → 失败 3 → 达阈值 → onKernelFailure
    expect(fakeChild.kill.mock.calls.length).toBe(killBefore + 1);
    await vi.advanceTimersByTimeAsync(1_000); // 失败 #1 退避 → spawn
    expect(kernelSpawnCount()).toBe(spawnBefore + 1);
  });

  // ── 组 E：连续 6 次失败 → dialog（新实例，fail 1→6 精确）──

  it('连续失败达 6 次 → 错误对话框 → 重试分支（重置计数并直接重启）', async () => {
    vi.useFakeTimers();
    await freshInstance();
    const killBefore = fakeChild.kill.mock.calls.length;
    const spawnBefore = kernelSpawnCount();
    fakeChild.emit('exit', 1, null);
    await vi.advanceTimersByTimeAsync(1_000); // 失败 #1 → spawn
    fakeChild.emit('exit', 1, null);
    await vi.advanceTimersByTimeAsync(2_000); // 失败 #2 → spawn
    fakeChild.emit('exit', 1, null);
    await vi.advanceTimersByTimeAsync(4_000); // 失败 #3 → spawn
    fakeChild.emit('exit', 1, null);
    await vi.advanceTimersByTimeAsync(8_000); // 失败 #4 → spawn
    fakeChild.emit('exit', 1, null);
    await vi.advanceTimersByTimeAsync(16_000); // 失败 #5 → spawn
    fakeChild.emit('exit', 1, null); // 失败 #6 → dialog（response=0 → 重置并 spawnKernel）
    await vi.advanceTimersByTimeAsync(0);
    expect(fakeChild.kill.mock.calls.length).toBe(killBefore + 6);
    expect(kernelSpawnCount()).toBe(spawnBefore + 6);
    expect(app.exit).not.toHaveBeenCalled();
  });

  it('错误对话框选择「退出」→ shutdown（response=1 分支）', async () => {
    vi.useFakeTimers();
    await freshInstance();
    vi.mocked(dialog.showMessageBox).mockResolvedValue({ response: 1 });
    fakeChild.emit('exit', 1, null);
    await vi.advanceTimersByTimeAsync(1_000); // 失败 #1 → spawn
    fakeChild.emit('exit', 1, null);
    await vi.advanceTimersByTimeAsync(2_000); // 失败 #2 → spawn
    fakeChild.emit('exit', 1, null);
    await vi.advanceTimersByTimeAsync(4_000); // 失败 #3 → spawn
    fakeChild.emit('exit', 1, null);
    await vi.advanceTimersByTimeAsync(8_000); // 失败 #4 → spawn
    fakeChild.emit('exit', 1, null);
    await vi.advanceTimersByTimeAsync(16_000); // 失败 #5 → spawn
    fakeChild.emit('exit', 1, null); // 失败 #6 → dialog response=1 → shutdown（kernelProcess 已清 → !child 早退）
    await vi.advanceTimersByTimeAsync(0);
    expect(app.exit).toHaveBeenCalledWith(0);
  });

  // ── 组 F：shutdown 完整回收 + 幂等（新实例）──

  it('before-quit → shutdown → stopKernel 完整回收（含超时兜底）→ 幂等 + 残留事件静默', async () => {
    vi.useFakeTimers();
    await freshInstance();
    emitReady(51234, 'a'); // healthCheckTimer 非 null → stopKernel 的 interval 清理分支
    await vi.advanceTimersByTimeAsync(0);
    const event = { preventDefault: vi.fn() };
    appEventHandlers['before-quit']?.(event);
    expect(event.preventDefault).toHaveBeenCalledTimes(1);
    fakeChild.emit('exit', 0, null); // finish → shutdown 继续 → app.exit(0)
    await vi.advanceTimersByTimeAsync(0);
    expect(app.exit).toHaveBeenCalledWith(0);
    await vi.advanceTimersByTimeAsync(3_000); // 3s 兜底回调（已 finish → settled 短路）
    await vi.advanceTimersByTimeAsync(2_000); // 5s 硬上限（finish 幂等）
    expect(app.exit).toHaveBeenCalledTimes(1);
    // 二次 shutdown（window-all-closed）→ quitInProgress 短路
    appEventHandlers['window-all-closed']?.(null);
    await vi.advanceTimersByTimeAsync(0);
    expect(app.exit).toHaveBeenCalledTimes(1);
    // kernelProcess 已清 → exit/error/line 事件全部静默跳过
    expect(() => {
      fakeChild.emit('exit', 1, null);
      fakeChild.emit('error', new Error('late'));
      fakeChild.stdout.emit('data', Buffer.from(READY_LINE(1, 'x')));
    }).not.toThrow();
    expect(app.exit).toHaveBeenCalledTimes(1);
    // 二次 before-quit → quitInProgress 短路（preventDefault 不再执行）
    const event2 = { preventDefault: vi.fn() };
    appEventHandlers['before-quit']?.(event2);
    await vi.advanceTimersByTimeAsync(0);
    expect(event2.preventDefault).not.toHaveBeenCalled();
    expect(app.exit).toHaveBeenCalledTimes(1);
  });

  it('stopKernel：kill 抛异常 + 3s 超时 taskkill 兜底分支 → 硬上限收尾', async () => {
    vi.useFakeTimers();
    await freshInstance();
    fakeChild.kill.mockImplementationOnce(() => {
      throw new Error('kill failed');
    });
    appEventHandlers['before-quit']?.({ preventDefault: vi.fn() });
    await vi.advanceTimersByTimeAsync(0); // kill 抛 → catch（L358）→ once('exit', finish) 挂起
    // 3s 兜底里 taskkill spawn 抛 → catch（L373）→ finish 直接收尾
    spawnMock.mockImplementationOnce(() => {
      throw new Error('taskkill ENOENT');
    });
    await vi.advanceTimersByTimeAsync(3_000);
    await vi.advanceTimersByTimeAsync(2_000); // 硬上限 finish 幂等
    expect(app.exit).toHaveBeenCalledWith(0);
  });

  it('killProcessTree：taskkill spawn 抛 + child.kill 抛 → 双 catch 兜底不崩溃', async () => {
    vi.useFakeTimers();
    await freshInstance();
    const spawnBefore = kernelSpawnCount();
    spawnMock.mockImplementationOnce(() => {
      throw new Error('taskkill ENOENT');
    });
    fakeChild.kill.mockImplementationOnce(() => {
      throw new Error('kill failed');
    });
    expect(() => fakeChild.emit('exit', 1, null)).not.toThrow();
    await vi.advanceTimersByTimeAsync(1_000); // 失败 #1 退避 → spawn（mock 已恢复）
    expect(kernelSpawnCount()).toBe(spawnBefore + 1);
  });

  // ── 组 G：stopKernel 早退（新实例）──

  it('stopKernel 早退：kernelProcess 已清空（!child 分支）→ 不挂起直接退出', async () => {
    vi.useFakeTimers();
    await freshInstance();
    fakeChild.emit('exit', 1, null); // onKernelFailure → kernelProcess = null（restartTimer 随后被 stopKernel 清理）
    await vi.advanceTimersByTimeAsync(0);
    const event = { preventDefault: vi.fn() };
    appEventHandlers['before-quit']?.(event);
    await vi.advanceTimersByTimeAsync(0);
    expect(event.preventDefault).toHaveBeenCalledTimes(1);
    expect(app.exit).toHaveBeenCalledWith(0);
  });

  it('stopKernel 早退：child.pid 缺失（pid === undefined 分支）→ 不挂起直接退出', async () => {
    vi.useFakeTimers();
    await freshInstance();
    fakeChild.pid = undefined;
    appEventHandlers['before-quit']?.({ preventDefault: vi.fn() });
    await vi.advanceTimersByTimeAsync(0);
    expect(app.exit).toHaveBeenCalledWith(0);
  });

  it('stopKernel 早退：child 已退出（exitCode !== null 分支）→ 不挂起直接退出', async () => {
    vi.useFakeTimers();
    await freshInstance();
    fakeChild.exitCode = 0;
    appEventHandlers['before-quit']?.({ preventDefault: vi.fn() });
    await vi.advanceTimersByTimeAsync(0);
    expect(app.exit).toHaveBeenCalledWith(0);
  });

  it('killProcessTree 早退：child.pid 缺失 → 跳过 taskkill/kill（不抛）', async () => {
    vi.useFakeTimers();
    await freshInstance();
    fakeChild.pid = undefined;
    const killBefore = fakeChild.kill.mock.calls.length;
    fakeChild.emit('exit', 1, null); // onKernelFailure → killProcessTree → pid undefined → 早退
    await vi.advanceTimersByTimeAsync(1_000); // 失败 #1 退避 → spawn
    expect(fakeChild.kill.mock.calls.length).toBe(killBefore); // 未调用 child.kill
  });

  it('INKFLOW_READY 行 child.pid 缺失 → effectivePid 回退解析值（?? 分支）', async () => {
    vi.useFakeTimers();
    await freshInstance();
    fakeChild.pid = undefined;
    emitReady(51234, 'pidfallback');
    await vi.advanceTimersByTimeAsync(0);
    expect((globalThis as { __kernelInfo?: unknown }).__kernelInfo).toEqual({
      pid: 7, // child.pid undefined → 用 READY 行里的 pid
      port: 51234,
      token: 'pidfallback',
    });
  });

  // ── 组 H：错误对话框挂起期间退出（新实例）──

  it('错误对话框挂起期间触发退出 → stopping 短路（showStartupErrorDialog 幂等）', async () => {
    vi.useFakeTimers();
    await freshInstance();
    let resolveDialog!: (v: { response: number }) => void;
    vi.mocked(dialog.showMessageBox).mockImplementation(
      () => new Promise<{ response: number }>((resolve) => (resolveDialog = resolve))
    );
    fakeChild.emit('exit', 1, null);
    await vi.advanceTimersByTimeAsync(1_000); // 失败 #1 → spawn
    fakeChild.emit('exit', 1, null);
    await vi.advanceTimersByTimeAsync(2_000); // 失败 #2 → spawn
    fakeChild.emit('exit', 1, null);
    await vi.advanceTimersByTimeAsync(4_000); // 失败 #3 → spawn
    fakeChild.emit('exit', 1, null);
    await vi.advanceTimersByTimeAsync(8_000); // 失败 #4 → spawn
    fakeChild.emit('exit', 1, null);
    await vi.advanceTimersByTimeAsync(16_000); // 失败 #5 → spawn
    fakeChild.emit('exit', 1, null); // 失败 #6 → dialog 挂起（不 resolve）
    await vi.advanceTimersByTimeAsync(0);
    // 对话框未决期间用户触发退出 → shutdown（kernelProcess 已清 → stopKernel !child 早退）
    appEventHandlers['before-quit']?.({ preventDefault: vi.fn() });
    await vi.advanceTimersByTimeAsync(0);
    expect(app.exit).toHaveBeenCalledWith(0);
    // dialog 此时才 resolve → stopping 短路，不重复 shutdown
    resolveDialog({ response: 1 });
    await vi.advanceTimersByTimeAsync(0);
    expect(app.exit).toHaveBeenCalledTimes(1);
  });

  // ── 组 I：生产模式（新实例，boot 即 isPackaged=true）──

  it('生产模式（isPackaged=true）：__kernelInfo 钩子短路 + 内核命令走 resources 分支', async () => {
    vi.useFakeTimers();
    delete (globalThis as { __kernelInfo?: unknown }).__kernelInfo; // 清旧实例残留
    fakeChild.removeAllListeners();
    fakeChild.stdout.removeAllListeners();
    fakeChild.stderr.removeAllListeners();
    vi.resetModules();
    appMock.isPackaged = true; // 先设再 import → 新实例 boot 即走生产分支
    await import('./main');
    emitReady(51234, 'a');
    await vi.advanceTimersByTimeAsync(0);
    expect((globalThis as { __kernelInfo?: unknown }).__kernelInfo).toBeUndefined();
    // boot 的 spawn（最后一条）在 isPackaged=true 时走 resources 分支；README 不触发新 spawn
    expect(String(spawnMock.mock.calls[spawnMock.mock.calls.length - 1][0])).toMatch(
      /inkflow\.exe$/
    );
  });

  it('parseReadyLine 畸形 JSON → null（kernel 契约兜底，与既有 kernel.test 互补）', () => {
    expect(parseReadyLine('INKFLOW_READY {not-json}')).toBeNull();
    expect(parseReadyLine('not a ready line')).toBeNull();
  });
});

/** 必须在最后执行：把模块级 mainWindow 置回 null 会影响后续用例 */
describe('mainWindow 为 null 容错（?. 短路，依赖声明顺序）', () => {
  it('容错：mainWindow 为 null 时三个 handler 均不抛异常且无副作用', async () => {
    vi.useFakeTimers();
    // 干净实例：清旧回调 + resetModules 清空 ipcMain.on 调用记录 → import 后恰好 3 条
    fakeChild.removeAllListeners();
    fakeChild.stdout.removeAllListeners();
    fakeChild.stderr.removeAllListeners();
    vi.resetModules();
    await import('./main');
    const calls = vi.mocked(ipcMain.on).mock.calls;
    expect(calls).toHaveLength(3);
    const lastMinimize = calls[0][1] as unknown as IpcHandler;
    const lastToggle = calls[1][1] as unknown as IpcHandler;
    const lastClose = calls[2][1] as unknown as IpcHandler;
    // 触发本实例 createMainWindow 注册的 win.on('closed') → 本实例 mainWindow = null
    windowEventHandlers['closed']?.(null);
    expect(() => lastMinimize(null)).not.toThrow();
    expect(() => lastToggle(null)).not.toThrow();
    expect(() => lastClose(null)).not.toThrow();
    expect(win.minimize).not.toHaveBeenCalled();
    expect(win.maximize).not.toHaveBeenCalled();
    expect(win.unmaximize).not.toHaveBeenCalled();
    expect(win.close).not.toHaveBeenCalled();
    // toggle 在 mainWindow 为 null 时提前 return，不读取 isMaximized
    expect(win.isMaximized).not.toHaveBeenCalled();
  });
});
