/** #526：全局配置 HTTP 面（对齐 CLI config show/set；PATCH 只支持 llm_default_model） */
import { apiFetch } from './client';

export interface GlobalConfigDto {
  default_model: string;
  default_temperature: number;
  context_max_ratio: number;
  context_default_window: number;
  server_host: string;
  server_port: number;
  data_dir: string;
}

/** 读取全局配置：GET /api/v1/config */
export async function fetchConfig(): Promise<Partial<GlobalConfigDto>> {
  return apiFetch<Partial<GlobalConfigDto>>('/api/v1/config', { method: 'GET' });
}

/** 保存全局默认模型：PATCH /api/v1/config body { llm_default_model } */
export async function patchConfig(
  llmDefaultModel: string,
): Promise<Partial<GlobalConfigDto> & { ok?: boolean }> {
  return apiFetch<Partial<GlobalConfigDto> & { ok?: boolean }>('/api/v1/config', {
    method: 'PATCH',
    body: { llm_default_model: llmDefaultModel },
  });
}
