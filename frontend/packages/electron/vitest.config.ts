import { configDefaults, defineConfig } from 'vitest/config';

// 主进程纯函数单测（node 环境；kernel.test.ts 不 import electron，可直接运行）
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
    // 覆盖率（#104 Phase 1）：electron 壳 20 用例纳入统计
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'json-summary'],
      reportsDirectory: './coverage',
      include: ['src/**/*.ts'],
      exclude: [...configDefaults.exclude, 'src/**/*.test.ts'],
      thresholds: {
        lines: 26.73,
        branches: 97.5,
        functions: 38.09,
        statements: 26.73,
      },
    },
  },
});
