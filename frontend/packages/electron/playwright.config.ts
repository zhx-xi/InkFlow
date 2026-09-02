import { defineConfig } from '@playwright/test';

/**
 * InkFlow Electron 壳 E2E 配置（#78，spec §3.6）。
 * 测试文件位于仓库根 tests/e2e/（AGENTS.md §3 预留目录），本包为执行入口。
 * 不进常规 CI（frontend-ci 技能约定）：本地 pnpm --filter inkflow-electron test:e2e 手动跑。
 */
export default defineConfig({
  testDir: '../../../tests/e2e',
  // #869 S3f-T3：tests/e2e 下混放 vitest 契约文件（e2e-isolation.test.ts / e2e-seed.test.ts，
  // 双目录共用先例 #415）——Playwright 默认 testMatch 含 *.test.ts 会误收它们以错误 loader
  // 执行（CI isolation step 红）。显式限定只收集 Playwright spec。
  testMatch: '**/*.spec.ts',
  timeout: 120_000,
  workers: 1,
  reporter: [['list']],
});
