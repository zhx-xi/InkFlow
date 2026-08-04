import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// 前端集成测试（spec §4.7 集成（真实内核）层）：
// - 环境 jsdom（apiFetch 依赖 window.INKFLOW_API / import.meta.env）
// - 只收集 src/api/__integration__/**（真实内核往返，启动 serve 子进程）
// - 单元测试（src/**/*.test.ts）由 vitest.config.ts 收集，此处排除
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/api/__integration__/**/*.test.ts'],
    testTimeout: 60_000, // 内核启动 + INKFLOW_READY 等待
    hookTimeout: 60_000,
  },
});
