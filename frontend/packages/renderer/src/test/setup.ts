import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

// RTL 自动清理（globals 模式下 afterEach 自动注册）
afterEach(() => {
  cleanup();
});

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
