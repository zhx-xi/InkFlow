import { defineConfig } from '@playwright/test';

/**
 * InkFlow Electron 壳 E2E 配置（#78，spec §3.6）。
 * 测试文件位于仓库根 tests/e2e/（AGENTS.md §3 预留目录），本包为执行入口。
 * 不进常规 CI（frontend-ci 技能约定）：本地 pnpm --filter inkflow-electron test:e2e 手动跑。
 */
export default defineConfig({
  testDir: '../../../tests/e2e',
  timeout: 120_000,
  workers: 1,
  reporter: [['list']],
});
