import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

// RTL 自动清理（globals 模式下 afterEach 自动注册）
afterEach(() => {
  cleanup();
});

// jsdom 缺失的浏览器 API mock 位（SSE 走 fetch ReadableStream，mock 点在 api 层，见 frontend-testing 技能）
