/**
 * ⚠️ 契约文件（Issue #482 项目聚合设置页，2026-08-19）
 *
 * GREEN 新建 src/pages/project-settings.tsx（路由 /settings/project），必须匹配：
 *
 * 导出与根结构：
 * - export function ProjectSettingsPage()（React 19：省略显式返回类型注解）
 * - 根容器 data-testid="project-settings-page"
 * - currentProjectId 为 null → 空态 data-testid="ps-empty"，文案 t('ps.empty')
 *   （新 i18n key，GREEN 补 zh.ts / en.ts；其余 key 复用既有 ag.* / set.*）
 * - 有当前项目 → 标题为项目名（heading，含 project.name）
 *
 * 四聚合区块（data-testid 即契约）：
 * ① 模型绑定：Radix Select，data-testid="ps-model-select"（SelectTrigger 落点），
 *    aria-label=t('ag.defaultModel')，value=config.model，onValueChange →
 *    setConfig({ model: v }) + persist；选项 = selectChatModelOptions(providers)
 * ② Agent 链：复用 AgentChainCard（根 data-testid="agent-chain-card" 既有），
 *    传 onConfigChange=persist
 * ③ 字数：input type=number，data-testid="ps-words-input"，
 *    aria-label=t('set.defaultWords')，value=config.default_words ?? 800000，blur 保存
 * ④ 世界观：Switch data-testid="ps-worldview-switch"（checked =
 *    typeof config.agent_worldview === 'string'；关闭→null / 开启→'__default__' sentinel）
 *    + 开启时 Select data-testid="ps-worldview-model"（选项 = 跟随默认 + chat 模型扁平）
 *
 * 保存统一走 useAgentStore（镜像 pages/settings.tsx AgentPanel 播种守卫与 persist）：
 * - persist = saveConfig(projectId) → PATCH /api/v1/projects/{id} body { config: 全量 }
 * - 挂载播种守卫：useEffect 依赖 currentProjectId，agent store config 不含
 *   agent_* / model 键时 loadFromProject(project.config)；已有则不覆盖
 *
 * RED 预期：src/pages/project-settings.tsx 不存在 → 文件级 module-not-found
 * （0 用例收集，不逐用例失败；GREEN 后本文件全量转绿）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ProjectSettingsPage } from './project-settings';
import { apiFetch } from '../api/client';
import { useAgentStore } from '../stores/agent';
import { useAgentsStore } from '../stores/agents';
import { useModelsStore, type ProviderConfig } from '../stores/models';
import { useProjectStore, AGENT_DEFAULT_SENTINEL, type ProjectConfig } from '../stores/project';
import { useTemplatesStore } from '../stores/templates';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

/** #473 R1：后端 BUILTIN_AGENT_SPECS 6 内置镜像（role_key 派生真源；mock 对象须含实体全字段） */
const BUILTIN_AGENTS = [
  { id: 101, name: '架构师', description: '章节结构/大纲规划', icon: '🏗️', system_prompt: '你是架构师。', tool_ids: [], skill_ids: [], model_override: null, temperature_override: null, builtin: true, role_key: 'architect', created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
  { id: 102, name: '写手', description: '正文生成', icon: '✍️', system_prompt: '你是写手。', tool_ids: [], skill_ids: [], model_override: null, temperature_override: null, builtin: true, role_key: 'writer', created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
  { id: 103, name: '审校员', description: '一致性审计', icon: '🔍', system_prompt: '你是审校员。', tool_ids: [], skill_ids: [], model_override: null, temperature_override: null, builtin: true, role_key: 'auditor', created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
  { id: 104, name: '修订师', description: '修订打磨', icon: '🛠️', system_prompt: '你是修订师。', tool_ids: [], skill_ids: [], model_override: null, temperature_override: null, builtin: true, role_key: 'reviser', created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
  { id: 105, name: '世界观顾问', description: '世界观一致', icon: '🌍', system_prompt: '你是世界观顾问。', tool_ids: [], skill_ids: [], model_override: null, temperature_override: null, builtin: true, role_key: 'worldview', created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
  { id: 106, name: '润色师', description: '文笔润色', icon: '✨', system_prompt: '你是润色师。', tool_ids: [], skill_ids: [], model_override: null, temperature_override: null, builtin: true, role_key: 'polisher', created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
] as const;

/** provider-configs mock（与 AgentChainCard.test.tsx 同源）：openai(gpt-4o chat) / zhipu(glm-4.5 chat) / ollama(qwen3 chat) */
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

/** 覆盖播种当前项目 p1 的 config（GREEN 页面按此契约渲染与播种） */
function seedProjectConfig(config: ProjectConfig) {
  useProjectStore.setState({
    projects: [{
      id: 'p1', name: '青云志', genre: '玄幻', language: 'zh-CN', target_words: 800000,
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
      id: 'p1', name: '青云志', genre: '玄幻', language: 'zh-CN', target_words: 800000,
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
  // AgentChainCard 挂载 3 GET（provider-configs / agent-templates / agents）必须分发，否则真实 fetch 污染断言；
  // PATCH 落库 = saveConfig → /api/v1/projects/p1。播种与 mock 同源（providers 双份一致）
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

describe('ProjectSettingsPage — #482 项目聚合设置页', () => {
  it('渲染契约：根容器 + 项目名标题 + 四聚合区块 testid + AgentChainCard 复用', async () => {
    seedProjectConfig({
      model: 'openai/gpt-4o',
      agent_worldview: 'openai/gpt-4o',
      default_words: 800000,
    });
    render(<ProjectSettingsPage />);

    expect(screen.getByTestId('project-settings-page')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /青云志/ })).toBeInTheDocument();
    // 四区块
    expect(screen.getByTestId('ps-model-select')).toBeInTheDocument();
    expect(screen.getByTestId('agent-chain-card')).toBeInTheDocument();
    expect(screen.getByTestId('ps-words-input')).toHaveValue(800000);
    expect(screen.getByTestId('ps-worldview-switch')).toBeChecked();
    // 世界观开启（字符串）→ 模型 Select 渲染
    expect(screen.getByTestId('ps-worldview-model')).toBeInTheDocument();
  });

  it('空态：currentProjectId=null → ps-empty，聚合区块不渲染', () => {
    useProjectStore.setState({ currentProjectId: null });
    render(<ProjectSettingsPage />);

    expect(screen.getByTestId('project-settings-page')).toBeInTheDocument();
    expect(screen.getByTestId('ps-empty')).toBeInTheDocument();
    expect(screen.queryByTestId('ps-model-select')).not.toBeInTheDocument();
    expect(screen.queryByTestId('ps-worldview-switch')).not.toBeInTheDocument();
  });

  it('模型绑定：默认模型 Select 切换 → setConfig({model}) + PATCH body.config.model', async () => {
    const user = userEvent.setup();
    seedProjectConfig({ model: 'openai/gpt-4o' });
    render(<ProjectSettingsPage />);

    // 挂载播种：agent store config.model = 项目 config.model
    expect(useAgentStore.getState().config.model).toBe('openai/gpt-4o');

    await user.click(screen.getByTestId('ps-model-select'));
    await user.click(await screen.findByRole('option', { name: 'zhipu/glm-4.5' }));

    expect(useAgentStore.getState().config.model).toBe('zhipu/glm-4.5');
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/projects/p1',
        expect.objectContaining({
          method: 'PATCH',
          body: expect.objectContaining({
            config: expect.objectContaining({ model: 'zhipu/glm-4.5' }),
          }),
        }),
      );
    });
  });

  it('世界观开关 关→开：agent_worldview=sentinel + PATCH（跟随默认）', async () => {
    const user = userEvent.setup();
    seedProjectConfig({ agent_worldview: null });
    render(<ProjectSettingsPage />);

    const sw = screen.getByTestId('ps-worldview-switch');
    expect(sw).not.toBeChecked();

    await user.click(sw);

    expect(useAgentStore.getState().config.agent_worldview).toBe(AGENT_DEFAULT_SENTINEL);
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/projects/p1',
        expect.objectContaining({
          method: 'PATCH',
          body: expect.objectContaining({
            config: expect.objectContaining({ agent_worldview: AGENT_DEFAULT_SENTINEL }),
          }),
        }),
      );
    });
  });

  it('世界观开关 开→关：agent_worldview=null（显式）+ PATCH', async () => {
    const user = userEvent.setup();
    seedProjectConfig({ agent_worldview: AGENT_DEFAULT_SENTINEL });
    render(<ProjectSettingsPage />);

    const sw = screen.getByTestId('ps-worldview-switch');
    expect(sw).toBeChecked();

    await user.click(sw);

    expect(useAgentStore.getState().config.agent_worldview).toBeNull();
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/projects/p1',
        expect.objectContaining({
          method: 'PATCH',
          body: expect.objectContaining({
            config: expect.objectContaining({ agent_worldview: null }),
          }),
        }),
      );
    });
  });

  it('世界观选模型：开启后 Select 选 chat 模型 → PATCH body.config.agent_worldview=模型值', async () => {
    const user = userEvent.setup();
    seedProjectConfig({ agent_worldview: AGENT_DEFAULT_SENTINEL });
    render(<ProjectSettingsPage />);

    const select = screen.getByTestId('ps-worldview-model');
    await user.click(select);
    // 选项契约：跟随默认置顶 + chat 模型扁平（embedding 过滤由 selectChatModelOptions 保证）
    expect(await screen.findByRole('option', { name: '跟随默认' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'openai/gpt-4o' })).toBeInTheDocument();

    await user.click(screen.getByRole('option', { name: 'ollama/qwen3' }));

    expect(useAgentStore.getState().config.agent_worldview).toBe('ollama/qwen3');
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/projects/p1',
        expect.objectContaining({
          method: 'PATCH',
          body: expect.objectContaining({
            config: expect.objectContaining({ agent_worldview: 'ollama/qwen3' }),
          }),
        }),
      );
    });
  });

  it('字数 blur 保存：改值 + 失焦 → PATCH body.config.default_words 变化', async () => {
    const user = userEvent.setup();
    seedProjectConfig({ default_words: 800000 });
    render(<ProjectSettingsPage />);

    const input = screen.getByTestId('ps-words-input');
    expect(input).toHaveValue(800000);

    await user.clear(input);
    await user.type(input, '1200000');
    await user.tab(); // blur → 保存

    expect(useAgentStore.getState().config.default_words).toBe(1200000);
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/projects/p1',
        expect.objectContaining({
          method: 'PATCH',
          body: expect.objectContaining({
            config: expect.objectContaining({ default_words: 1200000 }),
          }),
        }),
      );
    });
  });

  it('挂载播种：agent store 无 agent 字段 → loadFromProject(project.config)，输入框回显项目值', () => {
    seedProjectConfig({ default_words: 500000, writing_style: '明快' });
    render(<ProjectSettingsPage />);

    // 播种守卫放行（config 无 agent_* / model 键）→ 全量 loadFromProject
    expect(useAgentStore.getState().config).toEqual({ default_words: 500000, writing_style: '明快' });
    expect(screen.getByTestId('ps-words-input')).toHaveValue(500000);
  });
});
