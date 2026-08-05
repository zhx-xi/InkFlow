import { configDefaults, defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// 前端测试（frontend-testing 技能约定：jsdom + globals + setup）
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // 集成测试（真实内核往返）走独立 config（vitest.integration.config.ts），单元测试排除
    // ⚠️ 必须展开 configDefaults.exclude 追加（直接替换会收集 node_modules 测试，8 failed 实测）
    exclude: [...configDefaults.exclude, 'src/api/__integration__/**'],
    // 覆盖率（#104 Phase 1）：provider=v8（@vitest/coverage-v8，与 vitest 3.2.7 同版本）
    // include 界定 src/ 业务代码；exclude 排除入口/测试/集成目录（统计口径 = Issue #104 基线）
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'json-summary'],
      reportsDirectory: './coverage',
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        ...configDefaults.exclude,
        'src/main.tsx',
        'src/**/*.test.{ts,tsx}',
        'src/test/**',
        'src/api/__integration__/**',
      ],
      thresholds: {
        lines: 99.11,
        branches: 92.51,
        functions: 84.54,
        statements: 99.11,
      },
    },
  },
});
