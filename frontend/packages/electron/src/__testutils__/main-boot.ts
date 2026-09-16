/**
 * 主进程 boot 测试共享助手（#1219）
 *
 * 背景：main.window-controls / main.tray / main.kernel-path 三个测试文件都靠
 * `vi.resetModules()` + 动态 `import('./main')` 换新模块实例，以归零模块级状态
 * （kernelInfo / stopping / consecutiveFailures / kernelProcess）。
 * 本文件把三处各自内联的换实例逻辑收敛成唯一实现（拒绝同族路径分叉）。
 *
 * ⚠️ 实测（#1219 根因）：`vi.resetModules()` **只换模块注册表，不回收旧实例的副作用**，
 * 于是上个用例的残留会串进下个用例：
 *   1. 旧实例 `startHealthCheck()` 留下的 `setInterval` 仍挂在 fake timer 队列上，
 *      其闭包捕获旧 `kernelInfo` → advanceTimers 时按**旧端口**打 `/health`，
 *      落进新用例的 fetchMock → `toHaveBeenCalledTimes` / 数组 length 断言串扰。
 *   2. 旧实例 `updateKernelInfoHook()` 写的 `globalThis.__kernelInfo` 残留，
 *      新实例 boot 续体写回前会被断言读到（实测读到上个用例的 port=59999）。
 *   3. `logger.ts` 的模块级 `currentEndpoint` 随旧实例的 `mainLogger` 闭包存活，
 *      READY 后上报 `/api/v1/logs` 打向**旧端点**（实测断言收到旧 port 的 URL）。
 *   4. `fakeChild` emitter 是 hoisted 单例，跨实例累积 error/exit/data 回调。
 *
 * 因此换实例前必须显式清理以上四项——固定时序兜底不可靠（CI 上表现为间歇性 flaky）。
 */

/** 主进程在 READY 后写入的 globalThis 测试钩子（#167 F31 / F51） */
const MAIN_HOOK_GLOBALS = ['__kernelInfo', '__trayInfo', '__trayActions'] as const;

/** 清理主进程 boot 在 globalThis 上留下的测试钩子 */
export function clearMainHookGlobals(): void {
  for (const key of MAIN_HOOK_GLOBALS) {
    delete (globalThis as Record<string, unknown>)[key];
  }
}

/** 假 child 的最小清理面（emitter 单例：跨实例累积回调，必须清） */
export interface ChildLike {
  removeAllListeners(): unknown;
  stdout: { removeAllListeners(): unknown };
  stderr: { removeAllListeners(): unknown };
}

export interface ResetMainInstanceDeps {
  /** vitest 的 `vi`（显式传入，避免本文件耦合 vitest 运行时，保持纯函数可测） */
  vi: {
    resetModules(): void;
    clearAllTimers(): void;
  };
  /** 当前用例的假 child（旧实例的 error/exit/data 回调注册在它上面） */
  fakeChild: ChildLike;
  /** 动态 import 入口（固定基准，各文件均为 './main'） */
  importMain: () => Promise<unknown>;
  /**
   * 旧 logger 模块的端点复位。传入 `./logger` 的 `setMainLogEndpoint` 即可——
   * 必须在 `resetModules()` **之前**取到旧模块引用，否则清的不是旧实例持有的那份。
   */
  resetLogEndpoint?: (baseURL: string, token: string) => void;
}

/**
 * 换新 main 模块实例：**先清旧实例全部残留，再 resetModules + import**。
 *
 * 顺序不可颠倒——先 import 会让旧实例的 in-flight 续体有机会在新实例之后写入共享状态。
 */
export async function resetMainInstance(deps: ResetMainInstanceDeps): Promise<void> {
  const { vi, fakeChild, importMain, resetLogEndpoint } = deps;

  // 1) 旧实例定时器：不清理则 interval 闭包持旧 kernelInfo → 按旧端口打 fetch
  vi.clearAllTimers();
  // 2) 旧实例写入的 globalThis 钩子（断言直接读它，残留即串扰）
  clearMainHookGlobals();
  // 3) 旧实例的日志上报端点（logger.ts 模块级 currentEndpoint）
  resetLogEndpoint?.('', '');
  // 4) fakeChild emitter 单例：旧实例 spawnKernel 注册的 error/exit/data 回调
  fakeChild.removeAllListeners();
  fakeChild.stdout.removeAllListeners();
  fakeChild.stderr.removeAllListeners();

  // 5) 换模块注册表 + 载入新实例（此刻旧实例已无活跃副作用）
  vi.resetModules();
  await importMain();
}
