/**
 * E2E 管线 LLM 配置（#415 G2，2026-08-16 用户拍板）。
 *
 * 模型选择 = 「测试配置文件 + env 并行」：配置是默认源，
 * INKFLOW_E2E_LLM_PROVIDER / INKFLOW_E2E_LLM_MODEL env 优先覆盖（缺省读配置）。
 * 生成管线用 deepseek（便宜），仅 embedding 用 zhipu（用户指定，勿改）。
 */
export interface E2eLlmConfig {
  provider: string;
  model: string;
  embedding: string;
}

export const E2E_LLM_DEFAULT_CONFIG: E2eLlmConfig = {
  provider: 'deepseek',
  model: 'deepseek/deepseek-v4-flash',
  embedding: 'zhipu',
};

export function resolveE2eLlmConfig(): E2eLlmConfig {
  return {
    provider: process.env.INKFLOW_E2E_LLM_PROVIDER ?? E2E_LLM_DEFAULT_CONFIG.provider,
    model: process.env.INKFLOW_E2E_LLM_MODEL ?? E2E_LLM_DEFAULT_CONFIG.model,
    embedding: E2E_LLM_DEFAULT_CONFIG.embedding,
  };
}
