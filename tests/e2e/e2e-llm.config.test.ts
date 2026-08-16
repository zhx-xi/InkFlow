/**
 * e2e-llm.config.ts 配置模块契约（#415 G2，2026-08-16）。
 *
 * 用户拍板：E2E 管线模型选择 = 「测试配置文件 + env 并行」——配置是默认源，
 * INKFLOW_E2E_LLM_PROVIDER / INKFLOW_E2E_LLM_MODEL env 优先覆盖。
 * 生成管线用 deepseek（便宜），仅 embedding 用 zhipu。
 *
 * RED 形态：e2e-llm.config.ts 不存在 → vitest Cannot find module（3 用例全 FAIL）。
 */
import { afterEach, describe, expect, it } from 'vitest';
import {
  E2E_LLM_DEFAULT_CONFIG,
  resolveE2eLlmConfig,
} from './e2e-llm.config';

const ORIG_ENV = { ...process.env };

afterEach(() => {
  process.env = { ...ORIG_ENV };
});

describe('e2e-llm 配置解析（#415 G2）', () => {
  it('默认配置 = deepseek v4-flash 生成 + zhipu embedding', () => {
    delete process.env.INKFLOW_E2E_LLM_PROVIDER;
    delete process.env.INKFLOW_E2E_LLM_MODEL;
    expect(E2E_LLM_DEFAULT_CONFIG).toEqual({
      provider: 'deepseek',
      model: 'deepseek/deepseek-v4-flash',
      embedding: 'zhipu',
    });
    expect(resolveE2eLlmConfig()).toEqual(E2E_LLM_DEFAULT_CONFIG);
  });

  it('env 覆盖 provider/model（INKFLOW_E2E_LLM_PROVIDER/MODEL 优先于配置）', () => {
    process.env.INKFLOW_E2E_LLM_PROVIDER = 'zhipu';
    process.env.INKFLOW_E2E_LLM_MODEL = 'zhipu/glm-4.5';
    expect(resolveE2eLlmConfig()).toEqual({
      provider: 'zhipu',
      model: 'zhipu/glm-4.5',
      embedding: 'zhipu',
    });
  });

  it('env 缺省回退配置默认（不设 env 时保留 deepseek 配置）', () => {
    delete process.env.INKFLOW_E2E_LLM_PROVIDER;
    delete process.env.INKFLOW_E2E_LLM_MODEL;
    const cfg = resolveE2eLlmConfig();
    expect(cfg.provider).toBe('deepseek');
    expect(cfg.model).toBe('deepseek/deepseek-v4-flash');
    expect(cfg.embedding).toBe('zhipu');
  });
});
