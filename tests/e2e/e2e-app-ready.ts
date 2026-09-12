/**
 * E2E 冷启动就绪握手契约（#1125）。
 *
 * 背景：`e2e-projects.spec.ts` 用例 1 是本 suite 首个 `launchApp()`（冷启动），
 * 启动后立即裸 `click()` `new-project-btn` → 撞 30s 隐式等待超时
 * （`element(s) not found`，run 34608978801 首跑红 / rerun 绿）。
 *
 * 根因：`launchApp()` 只等到「内核就绪 + 模型预置」（`waitKernelInfo` +
 * `ensureModelConfigured` 都是**主进程/后端**层信号），**不等于渲染层已出 boot gate**。
 * AppLayout 在 `!booted` 时渲染 `BootGate`，主 UI（含 `new-project-btn`）根本未挂载
 * （App.tsx:74）。
 *
 * 全仓既有解（37+ 处先例）：等 `app-nav` 可见（`{ timeout: 60_000 }`）——
 * 每个 spec 都用了，唯独 `e2e-projects.spec.ts` 未采纳。
 *
 * ⚠️ Playwright API 事实（两次踩坑后钉死，勿再想当然）：
 *   - `expect(locator, options)` 的第二参数是**消息**（`string | { message?: string }`，
 *     见 playwright/types/test.d.ts:8716）——**不轮询、不 await、不产生断言**。
 *   - `locator.toBeVisible()` **不存在**（toBeVisible 是 expect 的 matcher，不在 Locator 上）。
 *   - 唯一正确形态（= 全仓 37 处先例）：
 *         await expect(locator).toBeVisible({ timeout })
 * 本模块把该形态收口，避免各处散写字面量。
 *
 * 纯 Node 模块（禁 import @playwright/test，对齐 e2e-model-ready.ts 的 #415 约束）——
 * 因此 `expect` 由调用方注入（spec 内传全局 expect）。
 */

/** 就绪锚点 testid：主 UI（AppLayout）挂载完成的唯一判据。 */
export const APP_READY_TESTID = 'app-nav';

/** 就绪等待预算（ms）：冷启动 chromadb + 内核 + 首启门控全链路。 */
export const APP_READY_TIMEOUT_MS = 60_000;

/**
 * Playwright `expect` 的最小结构形状。
 *
 * 只收「接收 locator、返回带 toBeVisible 的 matcher 对象」这一条能力，
 * 使 helper 的调用形态与真实 API 一致而不必 import Playwright 类型。
 */
export interface ExpectLike {
  (locator: unknown): {
    toBeVisible(options?: { timeout?: number }): Promise<void>;
  };
}

/** Locator 最小形状（只要求 getByTestId 的返回值可被 expect 接收）。 */
export interface ReadyPageLike {
  getByTestId(testId: string): unknown;
}

/**
 * 断言渲染层已出 boot gate（主 UI 已挂载）。
 *
 * 等价于全仓先例 `await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 })`，
 * 但把「锚点 testid + 预算」单点收口。
 *
 * @param page       Electron 首窗（`app.firstWindow()` 的返回值）
 * @param expect     Playwright 的 `expect`（spec 内传全局 expect）
 * @param timeoutMs  覆盖预算（默认 {@link APP_READY_TIMEOUT_MS}）
 */
export async function awaitAppReady(
  page: ReadyPageLike,
  expect: ExpectLike,
  timeoutMs: number = APP_READY_TIMEOUT_MS,
): Promise<void> {
  await expect(page.getByTestId(APP_READY_TESTID)).toBeVisible({ timeout: timeoutMs });
}
