/**
 * S3f-T3 R1：kernel.json 路径解析感知 INKFLOW_DATA_DIR（main.ts resolveKernelStatePath G4）
 *
 * 契约：.hermes/plans/contract-s3f-t3.md §1.1 G4 + §2 R1（RED 清单 R1）
 *   - dev + INKFLOW_DATA_DIR=dir → kernel.json 落 <dir>/kernel.json（与 Python config.data_dir
 *     对齐，per-test E2E 隔离的关键 src 行为变更）
 *   - dev 无 INKFLOW_DATA_DIR → 保持旧路径 <repo>/backend/data/kernel.json（F30 CLI 复用零破坏）
 *   - 打包（app.isPackaged=true）→ app.getPath('appData')/InkFlow/kernel.json（与 env 无关，分支不动）
 *
 * RED 基线（实测 main.ts L200-209）：resolveKernelStatePath 未感知 INKFLOW_DATA_DIR——
 * dev 分支写死 REPO_ROOT/backend/data/kernel.json。boot 后 kernelStatePath 在 whenReady 内赋值
 * （L854）→ spawn 成功收到 INKFLOW_READY 行写文件（L446-450）/ 复用判定读文件（L561）。
 * kernel.json 读写走 kernel.ts node:fs 同步 API → 测试用真实 fs 写 tmp 可行（main.export.test.ts
 * L22-24 同款注释）；不 mock node:fs / node:fs/promises。
 *
 * mock 设计（镜像 main.tray.test.ts S3f-T1 boot+文件驱动先例，L590+ describe 形态）：
 *   - vi.hoisted electron mock + vi.mock('node:child_process') 惰性假 child（迷你 EventEmitter，
 *     永不自动 emit）；whenReady 立即 resolve → import './main' 即完整 boot。
 *   - ⚠️ 本文件【不】在顶层 import './main'：resolveKernelStatePath 在 boot 时执行，env/appData
 *     stub 必须先于 freshInstance 生效；每用例 vi.stubEnv + resetModules 动态 import。
 *   - READY 触发用 fakeChild.stdout.emit('data', Buffer)（readline 'line' 回调同步执行，
 *     window-controls/tray 先例）；健康检查 /health 走【真实 fetch + 真实 node:http server】
 *     （kernel.state.test.ts tryReuseKernel describe L238+ 形态）——不 stub fetch，health 真 200
 *     永不累计失败触发崩溃拉起。
 *   - 写盘位置断言用每用例唯一 token：boot 后 READY 行带唯一 token → 读目标 kernel.json 断言
 *     token 相等 = 「本次 boot 写入该路径」的硬证据（R1/R3/R4 目标均为用例私有 tmp 目录，无竞争）。
 *   - ⚠️ R2 例外（限制如实注明）：dev 无 env 的旧路径 = <repo>/backend/data/kernel.json，是
 *     gitignored 共享运行时文件——CI 全量并行（vitest forks 每文件一进程）时 main.window-controls
 *     .test.ts 的 dev READY 用例会并发写同一文件（实测 R2 唯一 token 被覆写为 'b'）→ R2 不做内容
 *     token 读回，改断言：① 私有 tmp（stray/appData 注入）零落盘 ② repo 文件字节变化（boot 写盘
 *     确实发生）。afterAll 快照恢复原状。
 */
import { describe, it, expect, beforeAll, afterAll, beforeEach, afterEach, vi, type Mock } from 'vitest';
import * as fs from 'node:fs';
import * as os from 'node:os';
import path from 'node:path';
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';

type AnyHandler = (...args: unknown[]) => void;

/** kernel.json 五字段（F30 §2.1 契约；本地类型——与 kernel.state.test.ts 同款） */
interface KernelState {
  port: number;
  token: string;
  pid: number;
  version: string;
  started_at: string;
}

/** 假 child 固定 pid（spawn 后 effectivePid = child.pid ?? 解析值 → 写盘 pid 恒为 4242） */
const FAKE_CHILD_PID = 4242;

const electronMock = vi.hoisted(() => {
  // 迷你事件发射器：child.on 等存 handler，测试里手动触发（tray 先例原样）
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

  // createMainWindow / app 的事件 handler 存储（boot 挂载，测试不触发但 mock 面必须完整）
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
  // ⚠️ vi.hoisted 工厂先于模块顶层 const 初始化执行 → pid 用字面量（tray 先例同款），
  //    测试侧断言用 FAKE_CHILD_PID 常量（beforeEach 会复位）
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

const spawnMock = electronMock.__spawn as unknown as Mock;
const fakeChild = electronMock.__fakeChild as unknown as {
  pid: number;
  exitCode: number | null;
  stdout: {
    emit: (evt: string, ...args: unknown[]) => boolean;
    removeAllListeners: (evt?: string) => unknown;
  };
  stderr: { removeAllListeners: (evt?: string) => unknown };
  removeAllListeners: (evt?: string) => unknown;
};
const appMock = electronMock.app as {
  isPackaged: boolean;
  exit: Mock;
  quit: Mock;
};

/** 旧路径 kernel.json（main.ts REPO_ROOT 同式：src/ 上溯 4 级 = 仓库根；gitignored 运行时文件） */
const REPO_STATE_FILE = path.resolve(__dirname, '..', '..', '..', '..', 'backend', 'data', 'kernel.json');

let repoSnapshot: { existed: boolean; content?: string } = { existed: false };

/** 每个用例独立临时目录（用后即焚） */
function makeTempDir(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'inkflow-kernel-path-'));
}

function cleanupTempDir(dir: string): void {
  try {
    fs.rmSync(dir, { recursive: true, force: true });
  } catch {
    // Windows 偶发句柄占用：临时目录清理失败不阻塞断言
  }
}

/** 注入 app.getPath('appData') → tmp 目录（打包版 kernelStatePath 的锚点，tray S3f-T1 同款） */
function stubAppDataPath(dir: string): void {
  (appMock as unknown as { getPath?: (name: string) => string }).getPath = vi.fn(() => dir);
}

function unstubAppDataPath(): void {
  delete (appMock as unknown as { getPath?: (name: string) => string }).getPath;
}

/** 真实 /health server：X-InkFlow-Token 匹配才返回 200（kernel.state.test.ts L243 形态） */
async function startHealthServer(token: string): Promise<{ port: number; close: () => void }> {
  const server: Server = createServer((req: IncomingMessage, res: ServerResponse) => {
    if (req.headers['x-inkflow-token'] === token) {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ status: 'ok' }));
    } else {
      res.writeHead(401);
      res.end();
    }
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (address === null || typeof address === 'string') {
    throw new Error('unexpected server address');
  }
  return { port: address.port, close: () => server.close() };
}

/** INKFLOW_READY 行（pid 会被 effectivePid=child.pid 覆盖 → 写盘 pid 恒为 FAKE_CHILD_PID） */
function readyLine(port: number, token: string, version: string): string {
  return `INKFLOW_READY ${JSON.stringify({ port, token, pid: 7, version })}\n`;
}

/** 冲刷微任务（whenReady 续体 / readline 回调链） */
const flushMicrotasks = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

/** 新模块实例 boot（env/appData stub 必须先于调用生效；boot 内 resolveKernelStatePath 读它们） */
async function bootFresh(options: { env?: Record<string, string>; packagedAppDataDir?: string } = {}): Promise<void> {
  fakeChild.removeAllListeners();
  fakeChild.stdout.removeAllListeners();
  fakeChild.stderr.removeAllListeners();
  appMock.isPackaged = options.packagedAppDataDir !== undefined;
  if (options.packagedAppDataDir) {
    stubAppDataPath(options.packagedAppDataDir);
  } else {
    unstubAppDataPath();
  }
  for (const [key, value] of Object.entries(options.env ?? {})) {
    vi.stubEnv(key, value);
  }
  spawnMock.mockClear();
  delete (globalThis as { __kernelInfo?: unknown }).__kernelInfo;
  vi.resetModules();
  await import('./main');
}

/** boot → spawn → 内核 READY（fake child 发 INKFLOW_READY 行 → kernelStatePath 写盘链执行） */
async function bootToReady(
  options: { env?: Record<string, string>; packagedAppDataDir?: string },
  fields: { token: string; version: string }
): Promise<{ port: number; close: () => void }> {
  const health = await startHealthServer(fields.token);
  await bootFresh(options);
  await vi.waitFor(() => {
    expect(spawnMock.mock.calls.length).toBeGreaterThan(0);
  });
  fakeChild.stdout.emit('data', Buffer.from(readyLine(health.port, fields.token, fields.version)));
  await flushMicrotasks();
  return health;
}

/** kernel.json 存在 + 五字段与期望一致（与 READY 行一致：pid=FAKE_CHILD_PID、started_at ISO） */
function expectStateFile(
  filePath: string,
  expected: { port: number; token: string; pid: number; version: string }
): void {
  expect(fs.existsSync(filePath)).toBe(true);
  const parsed = JSON.parse(fs.readFileSync(filePath, 'utf-8')) as KernelState;
  expect(parsed.port).toBe(expected.port);
  expect(parsed.token).toBe(expected.token);
  expect(parsed.pid).toBe(expected.pid);
  expect(parsed.version).toBe(expected.version);
  expect(typeof parsed.started_at).toBe('string');
  expect(Number.isNaN(Date.parse(parsed.started_at))).toBe(false);
}

function readKernelInfoHook(): { pid: number; port: number; token: string } | undefined {
  return (globalThis as { __kernelInfo?: { pid: number; port: number; token: string } }).__kernelInfo;
}

beforeAll(() => {
  vi.spyOn(console, 'log').mockImplementation(() => {});
  vi.spyOn(console, 'error').mockImplementation(() => {});
  // 快照旧路径 kernel.json（dev 无 env 用例会真实写它；gitignored 运行时文件，跑完恢复原状）
  repoSnapshot = { existed: fs.existsSync(REPO_STATE_FILE) };
  if (repoSnapshot.existed) {
    repoSnapshot.content = fs.readFileSync(REPO_STATE_FILE, 'utf-8');
  }
});

afterAll(() => {
  try {
    if (repoSnapshot.existed && repoSnapshot.content !== undefined) {
      fs.writeFileSync(REPO_STATE_FILE, repoSnapshot.content, 'utf-8');
    } else if (!repoSnapshot.existed) {
      fs.rmSync(REPO_STATE_FILE, { force: true });
    }
  } catch {
    // 恢复失败不阻塞（gitignored 运行时文件）
  }
});

beforeEach(() => {
  appMock.isPackaged = false;
  fakeChild.pid = FAKE_CHILD_PID;
  fakeChild.exitCode = null;
  spawnMock.mockClear();
  unstubAppDataPath();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs(); // ⚠️ unstubAllGlobals 不恢复 env stub（vitest 3.2.7 实测）——两行都要
});

describe('resolveKernelStatePath 三态（S3f-T3 §1.1 G4：kernel.json 路径感知 INKFLOW_DATA_DIR）', () => {
  it('【R】dev + INKFLOW_DATA_DIR=tmp → READY 后 kernel.json 落 data dir 且五字段与 READY 一致（现写死 backend/data → FAIL）', async () => {
    const dir = makeTempDir();
    let health: { port: number; close: () => void } | null = null;
    try {
      const token = 'r1-data-dir-token';
      health = await bootToReady({ env: { INKFLOW_DATA_DIR: dir } }, { token, version: '0.1.0' });
      const stateFile = path.join(dir, 'kernel.json');
      // RED：resolveKernelStatePath dev 分支未感知 env → 写盘 <repo>/backend/data/kernel.json
      expect(fs.existsSync(stateFile), 'dev + INKFLOW_DATA_DIR 应写 <dataDir>/kernel.json（G4）').toBe(true);
      expectStateFile(stateFile, { port: health.port, token, pid: FAKE_CHILD_PID, version: '0.1.0' });
    } finally {
      health?.close();
      cleanupTempDir(dir);
    }
  });

  it('【G】dev 无 INKFLOW_DATA_DIR → 旧行为写 backend/data/kernel.json（守卫：F30 CLI 复用契约零破坏）', async () => {
    const strayDir = makeTempDir();
    const appDataDir = makeTempDir();
    let health: { port: number; close: () => void } | null = null;
    const prevEnv = process.env.INKFLOW_DATA_DIR;
    try {
      delete process.env.INKFLOW_DATA_DIR; // 显式清除环境残留，锁定「无 env」语义
      const token = 'r2-legacy-repo-token';
      // 注入 appData → tmp：防实现回归误入打包路径（dev 正常不调 getPath，isDebugMode 走 catch）
      stubAppDataPath(appDataDir);
      const beforeBytes = fs.existsSync(REPO_STATE_FILE)
        ? fs.readFileSync(REPO_STATE_FILE, 'utf-8')
        : null;
      health = await bootToReady({}, { token, version: '0.2.0' });
      // data dir 概念不存在 → 任何 tmp 目录都不该出现 kernel.json（无 env 不得启用 data dir 语义）
      expect(fs.existsSync(path.join(strayDir, 'kernel.json'))).toBe(false);
      // 打包路径同样不得落盘（dev 无 env 时只可能走 repo 旧分支）
      expect(fs.existsSync(path.join(appDataDir, 'InkFlow', 'kernel.json'))).toBe(false);
      // ⚠️ 限制（如实注明）：REPO_STATE_FILE 是 gitignored 共享运行时文件，CI 全量并行时
      // main.window-controls.test.ts 的 dev READY 用例会并发写同一文件（实测 token 被覆写为 'b'）
      // → 不做「内容 token 匹配」读回（竞态必挂），改用字节变化判定「本次 boot 写盘确实发生在
      // repo 旧路径」；GREEN 后 dev 无 env 分支行为不变（§1.1），本守卫两阶段均应通过。
      const afterBytes = fs.existsSync(REPO_STATE_FILE)
        ? fs.readFileSync(REPO_STATE_FILE, 'utf-8')
        : null;
      expect(afterBytes).not.toBeNull();
      expect(afterBytes).not.toBe(beforeBytes);
    } finally {
      if (prevEnv === undefined) {
        delete process.env.INKFLOW_DATA_DIR;
      } else {
        process.env.INKFLOW_DATA_DIR = prevEnv;
      }
      unstubAppDataPath();
      health?.close();
      cleanupTempDir(strayDir);
      cleanupTempDir(appDataDir);
    }
  });

  it('【R】dev + INKFLOW_DATA_DIR + kernel.json 指向活内核（真 pid + /health 200）→ 复用不 spawn（现读 backend/data → 死 pid → spawn FAIL）', async () => {
    const dir = makeTempDir();
    let health: { port: number; close: () => void } | null = null;
    try {
      const token = 'r3-reuse-token';
      health = await startHealthServer(token);
      // 预写合法五字段状态文件：pid = 真存活进程（process.pid）+ 真 http server 应答 /health 200
      const stateFile = path.join(dir, 'kernel.json');
      fs.writeFileSync(
        stateFile,
        JSON.stringify({
          port: health.port,
          token,
          pid: process.pid,
          version: '9.9.9',
          started_at: '2026-09-03T00:00:00.000Z',
        }),
        'utf-8'
      );
      await bootFresh({ env: { INKFLOW_DATA_DIR: dir } });
      // 等待复用判定落定：spawn 已发生（复用失败回落）或 __kernelInfo 钩子已写（复用成功）
      await vi.waitFor(() => {
        const spawned = spawnMock.mock.calls.length > 0;
        const kernelHook = readKernelInfoHook();
        expect(spawned || kernelHook !== undefined).toBe(true);
      });
      // RED：当前实现读 backend/data/kernel.json（死 pid）→ tryReuse null → spawnKernel → 断言失败
      expect(spawnMock, '活内核状态文件存在时应走复用路径，不再 spawn（G4）').not.toHaveBeenCalled();
      // 复用内容 = 状态文件四字段（pid 原样透传 process.pid）
      expect(readKernelInfoHook()).toEqual({ pid: process.pid, port: health.port, token });
    } finally {
      health?.close();
      cleanupTempDir(dir);
    }
  });

  it('【G】打包版 + appData=tmp + INKFLOW_DATA_DIR 也设 → kernel.json 仍落 appData/InkFlow（appData 优先，打包分支不动）', async () => {
    const appDataDir = makeTempDir();
    const envDir = makeTempDir();
    // 真实 Electron 启动即建 %APPDATA%\InkFlow（userData 目录）；writeKernelStateFile 不建目录
    // （writeFileSync 直写）→ 测试须先建好，否则 ENOENT 走 main.ts 降级 catch
    fs.mkdirSync(path.join(appDataDir, 'InkFlow'), { recursive: true });
    let health: { port: number; close: () => void } | null = null;
    try {
      const token = 'r4-packaged-appdata-token';
      health = await bootToReady(
        { packagedAppDataDir: appDataDir, env: { INKFLOW_DATA_DIR: envDir } },
        { token, version: '0.4.0' }
      );
      expectStateFile(path.join(appDataDir, 'InkFlow', 'kernel.json'), {
        port: health.port,
        token,
        pid: FAKE_CHILD_PID,
        version: '0.4.0',
      });
      // INKFLOW_DATA_DIR 已设也不得改道（§1.1 打包分支与 env 无关——现状即正确）
      expect(fs.existsSync(path.join(envDir, 'kernel.json'))).toBe(false);
    } finally {
      health?.close();
      cleanupTempDir(appDataDir);
      cleanupTempDir(envDir);
    }
  });
});
