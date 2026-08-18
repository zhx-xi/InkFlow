/**
 * 模型就绪选择器契约（Issue #474：P0 模型未配置前置校验）
 *
 * ⚠️ 本文件 = 契约。GREEN 必须新建 src/stores/models.ts 的导出（本文件 import 它）：
 *
 * export function hasChatModel(providers: ProviderConfig[]): boolean
 *
 * 判定口径（#474 源码实锤）：存在任一 provider 满足
 *   provider.key_saved === true 且 provider.models 含 type === 'chat' 的模型
 * ——「模型未配置」= 没有任何 key_saved=true 的 chat 类型 provider 模型，
 *   不是「没有模型名」（config.llm_default_model 恒有默认值 deepseek/deepseek-v4-flash，
 *   但无 API key 时 get_provider_config 抛 ValueError）。
 *
 * 行为契约：
 * - 空 providers → false
 * - provider key_saved=false 但含 chat 模型 → false（未保存 API Key 不算可用模型）
 * - provider key_saved=true 但仅 embedding 模型 → false（无 chat 类型）
 * - provider key_saved=true 且含 chat 模型 → true
 * - 多 provider 混合：任一满足即 true
 *
 * 消费方（三个入口，均须在发起 AI 前调用）：
 * - components/ChatPanel.tsx handleSend（builtin:chat 发送）
 * - pages/writing.tsx 续写/生成（start('write_continue'|'write_auto')）
 * - components/BookPlannerPanel.tsx handleStart（book-planner-start 访谈开始）
 */
import { describe, it, expect } from 'vitest';
import { hasChatModel, type ProviderConfig } from './models';

const base = (over: Partial<ProviderConfig>): ProviderConfig => ({
  id: 1,
  name: 'openai',
  base_url: 'https://api.openai.com/v1',
  default_model: 'gpt-4o',
  models: [{ id: 'gpt-4o', type: 'chat', roles: [] }],
  key_saved: true,
  max_retries: 3,
  timeout: 60,
  created_at: '2026-08-01T10:00:00Z',
  updated_at: '2026-08-05T10:00:00Z',
  ...over,
});

describe('models — hasChatModel 模型就绪选择器（#474）', () => {
  it('空 providers → false', () => {
    expect(hasChatModel([])).toBe(false);
  });

  it('provider key_saved=false 但含 chat 模型 → false（未保存 API Key 不算可用）', () => {
    const providers = [base({ key_saved: false })];
    expect(hasChatModel(providers)).toBe(false);
  });

  it('provider key_saved=true 但仅 embedding 模型 → false（无 chat 类型）', () => {
    const providers = [
      base({ models: [{ id: 'text-embedding-3-small', type: 'embedding', roles: ['rag'] }] }),
    ];
    expect(hasChatModel(providers)).toBe(false);
  });

  it('provider key_saved=true 且含 chat 模型 → true', () => {
    const providers = [base({})];
    expect(hasChatModel(providers)).toBe(true);
  });

  it('多 provider 混合：任一满足即 true（key_saved=false 的 provider 不拖后腿）', () => {
    const providers = [
      base({ id: 1, name: 'deepseek', key_saved: false }),
      base({ id: 2, name: 'openai', key_saved: true }),
    ];
    expect(hasChatModel(providers)).toBe(true);
  });
});
