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
        // #106 main.window-controls.test.ts 全量覆盖后 branches 96.5% 为真实上限：
        // 5 个数学死分支（kernel.ts L20 value===null 被 READY_LINE_PATTERN 正则排除、
        // main.ts L77/L168/L208/L257 调用点恒非 null 或无可达路径），非测试缺口
        branches: 96.5,
        functions: 38.09,
        statements: 26.73,
      },
    },
  },
});
