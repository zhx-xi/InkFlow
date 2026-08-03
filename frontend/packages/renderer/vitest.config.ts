import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// 前端测试（frontend-testing 技能约定：jsdom + globals + setup）
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
});
