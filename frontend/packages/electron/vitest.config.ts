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
        // #167 F31 新代码计入后基线提升（2026-08-08 实测 90.43/93.98/82.97/90.43）：
        // kernel.state.test.ts 21 用例 + main.tray.test.ts 18 用例 + preload settings 通道。
        // 留 2-3 点余量防 CI/本地 v8 覆盖率微差（#104 惯例：thresholds 随实现上调）
        lines: 88,
        // branches 96.5 → 93：main.ts 扩容后分支基数增大，实测 93.98（kernel.ts 96.49 / main.ts 92.9）
        branches: 90,
        functions: 80,
        statements: 88,
      },
    },
  },
});
