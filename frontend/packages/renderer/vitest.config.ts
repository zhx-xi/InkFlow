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
  },
});
