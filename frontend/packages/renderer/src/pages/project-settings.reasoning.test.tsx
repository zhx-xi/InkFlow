/**
 * ⚠️ 契约文件（#965 F59-M4 推理档位 → 项目设定页「Agent思考强度设定」，2026-09-09）。
 *
 * RED 预期：src/pages/project-settings.tsx 尚无「Agent思考强度设定」区块 → 本文件各用例
 * 均 FAIL 于 `getByTestId('ps-thinking-effort')` element-missing（控件/组件不存在 = 缺功能 RED）。
 * 仅当 GREEN 实现 §B F1（控件 + F4 i18n 键）后本文件全量转绿。
 *
 * 契约（GREEN 必须匹配，镜像 pages/project-settings.test.tsx 的 mock 基建）：
 * - 新 <section>（AI 配置区「模型绑定」之后、Agent 模板之前），样式同既有 section。
 * - 控件：Radix Select，data-testid="ps-thinking-effort"，aria-label=t('agent.thinking.label')，
 *   className="w-56"。
 * - 七档（值 = 英文枚举）none/minimal/low/medium/high/xhigh/default → t('agent.thinking.<值>')。
 * - 显示值：config.reasoning_effort ?? 'default'（None=跟随全局，UI 以「跟随模型默认」呈现）。
 * - 变更：setConfig({ reasoning_effort: v }) + persist()（既有 PATCH 全量 config 通道）。
 * - Q3 拍板：不加任何说明文案（控件标签直写「Agent思考强度设定」）。
 *
 * i18n（F4 唯一口径，GREEN 补 zh.ts / en.ts，前缀 agent.thinking.*）：
 *   agent.thinking.label=Agent思考强度设定 / low=低 / high=高 / medium=中 / default=跟随模型默认
 *   （RED 阶段这些键未定义 → useI18n 回显原键；控件不存在故本文件先 FAIL 于 getByTestId，不依赖兜底）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ProjectSettingsPage } from './project-settings';
import { apiFetch } from '../api/client';
import { useAgentStore } from '../stores/agent';
import { useAgentsStore } from '../stores/agents';
import { useModelsStore, type ProviderConfig } from '../stores/models';
import { useProjectStore, type ProjectConfig } from '../stores/project';
import { useTemplatesStore } from '../stores/templates';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

/** 与 project-settings.test.tsx 同源：6 内置镜像 + 3 provider（mock 对象含实体全字段） */
const BUILTIN_AGENTS = [
  { id: 101, name: '架构师', description: '章节结构/大纲规划', icon: '🏗️', system_prompt: '你是架构师。', tool_ids: [], skill_ids: [], model_override: null, temperature_override: null, builtin: true, role_key: 'architect', created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
  { id: 102, name: '写手', description: '正文生成', icon: '✍️', system_prompt: '你是写手。', tool_ids: [], skill_ids: [], model_override: null, temperature_override: null, builtin: true, role_key: 'writer', created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
  { id: 103, name: '审校员', description: '一致性审计', icon: '🔍', system_prompt: '你是审校员。', tool_ids: [], skill_ids: [], model_override: null, temperature_override: null, builtin: true, role_key: 'auditor', created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
  { id: 104, name: '修订师', description: '修订打磨', icon: '🛠️', system_prompt: '你是修订师。', tool_ids: [], skill_ids: [], model_override: null, temperature_override: null, builtin: true, role_key: 'reviser', created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
  { id: 105, name: '世界观顾问', description: '世界观一致', icon: '🌍', system_prompt: '你是世界观顾问。', tool_ids: [], skill_ids: [], model_override: null, temperature_override: null, builtin: true, role_key: 'worldview', created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
  { id: 106, name: '润色师', description: '文笔润色', icon: '✨', system_prompt: '你是润色师。', tool_ids: [], skill_ids: [], model_override: null, temperature_override: null, builtin: true, role_key: 'polisher', created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
] as const;

const PROVIDERS: ProviderConfig[] = [
  {
    id: 1, name: 'openai', base_url: 'https://api.openai.com/v1', default_model: 'gpt-4o',
    models: [
      { id: 'gpt-4o', type: 'chat', roles: ['main'] },
      { id: 'text-embedding-3-small', type: 'embedding', roles: ['rag'] },
    ],
    key_saved: true, max_retries: 3, timeout: 60,
    created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  },
  {
    id: 2, name: 'zhipu', base_url: 'https://open.bigmodel.cn/api/paas/v4', default_model: 'glm-4.5',
    models: [{ id: 'glm-4.5', type: 'chat', roles: [] }],
    key_saved: false, max_retries: 3, timeout: 60,
    created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  },
  {
    id: 3, name: 'ollama', base_url: 'http://127.0.0.1:11434', default_model: 'qwen3',
    models: [{ id: 'qwen3', type: 'chat', roles: [] }],
    key_saved: false, max_retries: 3, timeout: 60,
    created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
  },
];

/** F59 新键 reasoning_effort（ProjectConfig 将扩展；测试经子类型透传，免 `as` 强转） */
type ProjectWithReasoning = ProjectConfig & { reasoning_effort?: string | null };

/** 播种当前项目 p1 的 config（GREEN 页面按此契约渲染与播种；reasoning_effort 为 F59 新键） */
function seedProjectConfig(config: ProjectWithReasoning) {
  useProjectStore.setState({
    projects: [{
      id: 'p1', name: '青云志', tags: ['玄幻'], language: 'zh-CN', target_words: 800000,
      config,
      created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
    }],
    currentProjectId: 'p1', loading: false, error: null,
  });
}

beforeEach(() => {
  apiFetchMock.mockReset();
  useProjectStore.setState({
    projects: [{
      id: 'p1', name: '青云志', tags: ['玄幻'], language: 'zh-CN', target_words: 800000,
      config: {},
      created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
    }],
    currentProjectId: 'p1', loading: false, error: null,
  });
  useAgentStore.setState({ config: {}, apiKeyDraft: '', testStatus: 'idle', testMessage: null });
  useAgentsStore.setState({ agents: [], tools: [], skills: [], loading: false, error: null });
  useTemplatesStore.setState({ templates: [], loading: false, error: null, defaultTemplateId: null });
  useModelsStore.setState({
    providers: PROVIDERS,
    loading: false, error: null, selectedModelId: null,
    roleBinding: { main: '', architect: '', writer: '', auditor: '', reviser: '', embedding: '' },
  });
  useToastStore.setState({ toasts: [] });
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === '/api/v1/provider-configs') {
      return { items: PROVIDERS, total: 3, offset: 0, limit: 50 };
    }
    if (path === '/api/v1/agent-templates') {
      return { items: [], total: 0, offset: 0, limit: 50 };
    }
    if (path === '/api/v1/agents') {
      return { items: BUILTIN_AGENTS, total: 6, offset: 0, limit: 50 };
    }
    if (path === '/api/v1/projects' && !init?.method) {
      return { items: [], total: 0, offset: 0, limit: 50 };
    }
    return { ok: true };
  });
});

describe('#965 F59-M4 — 项目设定页「Agent思考强度设定」', () => {
  it('渲染契约：ps-thinking-effort 控件存在 + aria-label=t(agent.thinking.label)；无额外说明文案（Q3 拍板）', async () => {
    seedProjectConfig({ reasoning_effort: 'low' });
    render(<ProjectSettingsPage />);

    // #793 纪律：UI 必须出现断言（控件不存在 → element-missing FAIL）
    const select = await screen.findByTestId('ps-thinking-effort');
    expect(select).toHaveAttribute('aria-label', 'Agent思考强度设定');

    // Q3（spec §3.4 / §12 D9）：控件标签直写「Agent思考强度设定」，不加任何说明文案
    const section = select.closest('section')!;
    expect(within(section).getByText('Agent思考强度设定')).toBeInTheDocument();
    expect(within(section).queryByRole('paragraph')).not.toBeInTheDocument();
    expect(within(section).queryByText(/说明|用于|作用|控制/)).not.toBeInTheDocument();
  });

  it('回显：config.reasoning_effort="low" → 控件显示「低」（t(agent.thinking.low)）', async () => {
    seedProjectConfig({ reasoning_effort: 'low' });
    render(<ProjectSettingsPage />);

    const select = await screen.findByTestId('ps-thinking-effort');
    expect(select).toHaveTextContent('低');
  });

  it('回显：config.reasoning_effort 缺失（跟随全局）→ 控件显示「跟随模型默认」（t(agent.thinking.default)）', async () => {
    seedProjectConfig({});
    render(<ProjectSettingsPage />);

    const select = await screen.findByTestId('ps-thinking-effort');
    expect(select).toHaveTextContent('跟随模型默认');
  });

  it('变更：选择「高」→ setConfig({reasoning_effort:"high"}) + PATCH body.config.reasoning_effort="high"', async () => {
    const user = userEvent.setup();
    seedProjectConfig({ reasoning_effort: 'low' });
    render(<ProjectSettingsPage />);

    await user.click(await screen.findByTestId('ps-thinking-effort'));
    await user.click(await screen.findByRole('option', { name: '高' }));

    expect((useAgentStore.getState().config as ProjectWithReasoning).reasoning_effort).toBe('high');
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/projects/p1',
        expect.objectContaining({
          method: 'PATCH',
          body: expect.objectContaining({
            config: expect.objectContaining({ reasoning_effort: 'high' }),
          }),
        }),
      );
    });
  });
});
