/**
 * S3f-T3 E2E 数据隔离基建（contract-s3f-t3 §1.3 R3）。
 *
 * createIsolatedEnv(tag, extra?) → IsolatedEnv { dataDir, userDataDir, env, cleanup }：
 * - dataDir     = mkdtempSync(join(tmpdir(), `inkflow-e2e-${tag}-`))   （内核数据隔离）
 * - userDataDir = 同上、`-ud` 后缀                                      （渲染层 --user-data-dir）
 * - env         = { ...process.env, INKFLOW_DATA_DIR: dataDir } + extra 覆盖（extra 优先）
 * - cleanup     = rmSync recursive force（幂等，目录已删/不存在不抛）
 *
 * 纯 Node 模块（禁 import @playwright/test，#415 vitest 加载约束）；spec 与 vitest 双加载。
 */
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';

export interface IsolatedEnv {
  dataDir: string;
  userDataDir: string;
  env: Record<string, string | undefined>;
  cleanup(): void;
}

export function createIsolatedEnv(tag: string, extra?: Record<string, string>): IsolatedEnv {
  const dataDir = mkdtempSync(path.join(tmpdir(), `inkflow-e2e-${tag}-`));
  const userDataDir = mkdtempSync(path.join(tmpdir(), `inkflow-e2e-${tag}-ud-`));
  return {
    dataDir,
    userDataDir,
    env: { ...process.env, INKFLOW_DATA_DIR: dataDir, ...extra },
    cleanup: () => {
      rmSync(dataDir, { recursive: true, force: true });
      rmSync(userDataDir, { recursive: true, force: true });
    },
  };
}
