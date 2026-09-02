import '@testing-library/jest-dom/vitest';
import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

// RTL 自动清理（globals 模式下 afterEach 自动注册）
afterEach(() => {
  cleanup();
});

// userEvent 在 fake timers 下每次 API 调用收尾会 await setTimeout(0)（wait()），
// vitest 默认 fake timers 不自动推进 → user.type / user.click 挂起（ChatPanel 契约 4-6）。
// 兜底：无参 useFakeTimers() 默认 shouldAdvanceTime=true（按真实时间自动推进 @sinonjs clock），
// 显式传参的调用保持原样（既有轮询/防抖测试仍用 advanceTimersByTimeAsync 精确控制）。
const originalUseFakeTimers = vi.useFakeTimers.bind(vi);
vi.useFakeTimers = ((options?: Parameters<typeof vi.useFakeTimers>[0]) =>
  originalUseFakeTimers(options === undefined ? { shouldAdvanceTime: true } : options)) as typeof vi.useFakeTimers;

// jsdom 缺失的浏览器 API mock 位（SSE 走 fetch ReadableStream，mock 点在 api 层，见 frontend-testing 技能）

// Radix Select/Slider 内部 useSize 依赖 ResizeObserver（jsdom 未实现），提供最小 mock 防挂载崩溃
if (typeof globalThis.ResizeObserver === 'undefined') {
  class ResizeObserverMock {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  globalThis.ResizeObserver = ResizeObserverMock as unknown as typeof ResizeObserver;
}

// Radix Select trigger 的 pointerdown 依赖 Pointer Capture API（jsdom 未实现），最小 mock 防面板无法打开
// 仅 jsdom 环境有 Element；node env 集成测试（F1 SSE 黑盒）跳过
if (typeof Element !== 'undefined') {
  if (typeof Element.prototype.hasPointerCapture !== 'function') {
    Element.prototype.hasPointerCapture = () => false;
  }
  if (typeof Element.prototype.setPointerCapture !== 'function') {
    Element.prototype.setPointerCapture = () => {};
  }
  if (typeof Element.prototype.releasePointerCapture !== 'function') {
    Element.prototype.releasePointerCapture = () => {};
  }
  if (typeof Element.prototype.scrollIntoView !== 'function') {
    Element.prototype.scrollIntoView = () => {};
  }
}
