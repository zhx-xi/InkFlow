/**
 * `e2e-app-ready.ts` 就绪握手契约（#1125 cold-start readiness RED）。
 *
 * 契约面（= 全仓 37+ 处 `app-nav` + 60s 先例）：
 * 1. 锚点 = `app-nav`（主 UI 挂载判据，非 BootGate 的任何元素）
 * 2. 预算 = 60_000ms（冷启动 chromadb + 内核 + 首启门控全链路）
 * 3. 调用形态 = `expect(locator).toBeVisible({ timeout })`
 *    —— 两处已踩过的错形态，本测试**显式反证**：
 *      a) `expect(locator, { timeout })`：第二参数是 message，不轮询不 await
 *      b) `locator.toBeVisible({ timeout })`：Locator 上没有该方法（ExpectLike 才提供）
 * 4. 可注入覆盖预算（默认常量单点收口）
 *
 * RED 形态：e2e-app-ready.ts 不存在 → vitest Cannot find module（全用例 FAIL）。
 */
import { describe, expect, it, vi } from 'vitest';
import {
  APP_READY_TESTID,
  APP_READY_TIMEOUT_MS,
  awaitAppReady,
  type ExpectLike,
} from './e2e-app-ready';

/**
 * expect 替身：忠实模拟 `expect(locator, message?) → { toBeVisible({timeout}) }`。
 * 记录 (locator, timeout)，并可模拟「断言失败」。
 */
function makeExpect() {
  const calls: Array<{ locator: unknown; timeout?: number }> = [];
  const double = ((locator: unknown) => ({
    async toBeVisible(options?: { timeout?: number }) {
      calls.push({ locator, timeout: options?.timeout });
    },
  })) as unknown as ExpectLike;
  return { double, calls };
}

/** Page 替身：getByTestId 返回一个**纯 locator 标记**（刻意不带 toBeVisible）。 */
function makePage() {
  const lookups: string[] = [];
  const page = {
    getByTestId(testId: string) {
      lookups.push(testId);
      // 真实 Playwright Locator 没有 toBeVisible —— 复刻该事实
      return { __testId: testId } as unknown;
    },
  };
  return { page, lookups };
}

describe('e2e 冷启动就绪握手（#1125）', () => {
  it('锚点 = app-nav（主 UI 挂载判据）', () => {
    expect(APP_READY_TESTID).toBe('app-nav');
  });

  it('预算 = 60s（对齐全仓既有 app-nav 先例）', () => {
    expect(APP_READY_TIMEOUT_MS).toBe(60_000);
  });

  it('以 app-nav + 60s 调用 expect(locator).toBeVisible（正确原语）', async () => {
    const { double, calls } = makeExpect();
    const { page, lookups } = makePage();

    await awaitAppReady(page, double);

    expect(lookups).toEqual(['app-nav']);
    expect(calls).toHaveLength(1), '恰好一次可见性断言';
    expect(calls[0]?.timeout).toBe(60_000), '默认预算须为 60s';
  });

  it('locator 保持原样透传给 expect（不在 helper 内自行断言）', async () => {
    const { double, calls } = makeExpect();
    const { page } = makePage();

    await awaitAppReady(page, double);

    // 传入 expect 的应是 page.getByTestId('app-nav') 的返回值
    expect(calls[0]?.locator).toEqual({ __testId: 'app-nav' });
  });

  it('toBeVisible 被真正 await（非 fire-and-forget）', async () => {
    let resolved = false;
    const double = ((_locator: unknown) => ({
      async toBeVisible() {
        await new Promise((r) => setTimeout(r, 5));
        resolved = true;
      },
    })) as unknown as ExpectLike;
    const { page } = makePage();

    await awaitAppReady(page, double);

    expect(resolved).toBe(true), 'helper 必须 await 可见性断言';
  });

  it('可注入覆盖预算（单点收口，禁散写字面量）', async () => {
    const { double, calls } = makeExpect();
    const { page } = makePage();

    await awaitAppReady(page, double, 12_345);

    expect(calls[0]?.timeout).toBe(12_345), '覆盖值须透传';
  });

  it('断言原语被调用（非静默空实现）', async () => {
    const spy = vi.fn(async () => {});
    const double = ((_locator: unknown) => ({
      toBeVisible: spy,
    })) as unknown as ExpectLike;
    const { page } = makePage();

    await awaitAppReady(page, double);

    expect(spy).toHaveBeenCalledTimes(1);
  });

  it('反证：helper 不得依赖 locator 上的 toBeVisible（Locator 无此方法）', async () => {
    // 真实 Locator 形状（只有 getByTestId 产物，无 toBeVisible）下必须仍能工作，
    // 因为断言由 expect(locator).toBeVisible 承担。
    const { double } = makeExpect();
    const { page } = makePage();

    await expect(awaitAppReady(page, double)).resolves.toBeUndefined();
  });
});
