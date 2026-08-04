import { defineConfig } from 'vitest/config';

// 主进程纯函数单测（node 环境；kernel.test.ts 不 import electron，可直接运行）
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
});
