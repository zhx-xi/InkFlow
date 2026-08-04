import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// renderer 开发服务器（#79 开发期：浏览器调试 + 本地内核 serve，不启动 Electron）
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // file:// 加载兼容（spec §3.4）：生产模式 BrowserWindow 以 file:// 加载 dist/，
  // base 必须为相对路径 './'，否则 /assets/... 绝对路径 404
  base: './',
  server: {
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: 'dist',
  },
});
