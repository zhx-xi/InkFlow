/**
 * e2e-isolation.ts 模块契约（S3f-T3 R3，contract-s3f-t3 §1.3）。
 *
 * createIsolatedEnv(tag, extra?) → IsolatedEnv { dataDir, userDataDir, env, cleanup }：
 * - dataDir     = mkdtempSync(join(tmpdir(), `inkflow-e2e-${tag}-`))   （内核数据隔离）
 * - userDataDir = 同上、`-ud` 后缀                                      （渲染层 --user-data-dir）
 * - env         = { ...process.env, INKFLOW_DATA_DIR: dataDir } + extra 覆盖（extra 优先）
 * - cleanup     = rmSync recursive force（幂等，目录已删/不存在不抛）
 *
 * 纯 Node 模块（禁 import @playwright/test，#415 vitest 加载约束）；spec（e2e-isolation.spec.ts
 * / e2e-rag-fake.spec.ts）与 vitest 双加载。
 *
 * RED 形态：e2e-isolation.ts 不存在 → vitest Cannot find module（本文件 collection FAIL）。
 */
import { afterEach, describe, expect, it } from 'vitest';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createIsolatedEnv, type IsolatedEnv } from './e2e-isolation';

/** 本文件创建的 env 清单——afterEach 兜底清理，防断言中途失败遗留临时目录 */
const created: IsolatedEnv[] = [];

afterEach(() => {
  for (const env of created.splice(0)) {
    try {
      env.cleanup();
    } catch {
      // cleanup 幂等：清理失败不掩盖用例结论
    }
  }
});

describe('createIsolatedEnv（S3f-T3 §1.3 四断言）', () => {
  it('① 目录真实存在且 env 回写 INKFLOW_DATA_DIR', () => {
    const env = createIsolatedEnv('t1');
    created.push(env);
    // mkdtemp 前缀约定：dataDir 带 tag、userDataDir 带 -ud- 后缀（供 spec 双隔离）
    expect(env.dataDir.startsWith(path.join(tmpdir(), 'inkflow-e2e-t1-'))).toBe(true);
    expect(env.userDataDir.startsWith(path.join(tmpdir(), 'inkflow-e2e-t1-ud-'))).toBe(true);
    expect(existsSync(env.dataDir)).toBe(true);
    expect(existsSync(env.userDataDir)).toBe(true);
    // env 回写：INKFLOW_DATA_DIR 指向 dataDir；其余键继承 process.env
    expect(env.env.INKFLOW_DATA_DIR).toBe(env.dataDir);
    expect(env.env.PATH).toBe(process.env.PATH);
  });

  it('② extra 覆盖优先（含 INKFLOW_DATA_DIR 键 + 自定义键）', () => {
    const env = createIsolatedEnv('t2', { INKFLOW_DATA_DIR: 'extra-override-value', CUSTOM_EXTRA: 'v' });
    created.push(env);
    // extra 在 base（process.env + INKFLOW_DATA_DIR=dataDir）之后展开 → 同键覆盖
    expect(env.env.INKFLOW_DATA_DIR).toBe('extra-override-value');
    expect(env.env.CUSTOM_EXTRA).toBe('v');
    // 目录仍独立创建（env 键可被 extra 改写，目录生命周期不受影响）
    expect(env.dataDir).not.toBe('extra-override-value');
    expect(existsSync(env.dataDir)).toBe(true);
  });

  it('③ cleanup 幂等：目录消失 + 重复调用不抛', () => {
    const env = createIsolatedEnv('t3');
    expect(existsSync(env.dataDir)).toBe(true);
    expect(existsSync(env.userDataDir)).toBe(true);
    env.cleanup();
    expect(existsSync(env.dataDir)).toBe(false);
    expect(existsSync(env.userDataDir)).toBe(false);
    // rmSync recursive force：缺目录不抛（重复 cleanup / 外部已删均安全）
    expect(() => env.cleanup()).not.toThrow();
  });

  it('④ 两次调用目录不同（per-test 隔离前提）', () => {
    const a = createIsolatedEnv('t4');
    const b = createIsolatedEnv('t4');
    created.push(a, b);
    expect(a.dataDir).not.toBe(b.dataDir);
    expect(a.userDataDir).not.toBe(b.userDataDir);
    expect(a.env.INKFLOW_DATA_DIR).not.toBe(b.env.INKFLOW_DATA_DIR);
  });
});
