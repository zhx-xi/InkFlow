/**
 * 设置页 #105 即改即存系列 测试（拆分自 settings.test.tsx，#281 测试文件规模治理）。
 *
 * 共享 mock/beforeEach 定义见各拆分文件自含副本。
 */


import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { SettingsPage } from './settings';
import { apiFetch } from '../api/client';
import { useAgentStore } from '../stores/agent';
import { useProjectStore, type ProjectConfig } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import { useToastStore } from '../stores/toast';

// 2026-08-08 父侧裁定（测试自身缺陷修复）：client.ts 模块内函数（patchSettings/fetchSettings）
// 经 importOriginal 展开后函数体仍引用真实 apiFetch（模块作用域闭包）→ 只 mock apiFetch 时
// 真实 patchSettings 会打网络 → KernelOfflineError → store 走 catch（F32 切换用例 IPC 零调用）。
// 修法 = 与 theme.test.ts 同款：vi.hoisted 直接替换 patchSettings/fetchSettings 为 mock。
const { fetchSettingsMock, patchSettingsMock } = vi.hoisted(() => ({
  fetchSettingsMock: vi.fn(),
  patchSettingsMock: vi.fn(),
}));

// #266（2026-08-12）：数据目录持久化契约 mock（GREEN 实现于 src/api/client.ts，镜像 F32 模式）
const { fetchDataDirMock, updateDataDirMock } = vi.hoisted(() => ({
  fetchDataDirMock: vi.fn(),
  updateDataDirMock: vi.fn(),
}));

// #276（2026-08-12）：RAG 向量检索区块契约 mock（GREEN 实现于 src/api/vector.ts）
const { vectorStatusMock, vectorReindexMock } = vi.hoisted(() => ({
  vectorStatusMock: vi.fn(),
  vectorReindexMock: vi.fn(),
}));

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return {
    ...actual,
    apiFetch: vi.fn(),
    fetchSettings: fetchSettingsMock,
    patchSettings: patchSettingsMock,
    fetchDataDir: fetchDataDirMock,
    updateDataDir: updateDataDirMock,
  };
});

// #276（2026-08-12）：RAG 向量检索区块 —— GREEN 才创建 src/api/vector.ts，
// 假实现保证既有用例可运行（#107 Mock-屏蔽型 RED 同款）；GREEN 落地后可删。
vi.mock('../api/vector', () => ({
  fetchVectorStatus: vectorStatusMock,
  postVectorReindex: vectorReindexMock,
}));

// ⚠️ #107 RED 阶段 mock：stores/templates 与 components/TemplateDialog 由 GREEN 创建，
// 本文件以测试内假实现提供（保证既有用例可运行）。假 store 行为与 stores/templates.test.ts
// 契约一致；假 dialog 为受控表单壳（open/editing 回显 + 保存走 onCreate/onUpdate 回调）。
// GREEN 落地后此两 mock 可删，改真实 import。
vi.mock('../stores/templates', async () => {
  const { create } = await import('zustand');
  const { apiFetch } = await import('../api/client');
  interface FakeRole {
    model: string | null;
    temperature: number | null;
    enabled: boolean;
  }
  interface FakeTemplate {
    id: number;
    name: string;
    description: string;
    main_model: string;
    default_temperature: number;
    roles: {
      architect: FakeRole;
      writer: FakeRole;
      auditor: FakeRole;
      reviser: FakeRole;
    };
    default_words: number;
    is_default: boolean;
    used_by?: Array<{ id: string; name: string }>;
    created_at: string;
    updated_at: string;
  }
  const useTemplatesStore = create<{
    templates: FakeTemplate[];
    loading: boolean;
    error: string | null;
    defaultTemplateId: number | null;
    loadTemplates: () => Promise<void>;
    createTemplate: (input: unknown) => Promise<FakeTemplate>;
    updateTemplate: (id: number, patch: unknown) => Promise<FakeTemplate>;
    deleteTemplate: (id: number) => Promise<void>;
    duplicateTemplate: (id: number) => Promise<FakeTemplate>;
    setDefault: (id: number) => Promise<void>;
    loadDefault: () => Promise<void>;
  }>((set) => ({
    templates: [],
    loading: false,
    error: null,
    defaultTemplateId: null,
    loadTemplates: async () => {
      set({ loading: true, error: null });
      try {
        const data = await apiFetch<{ items: FakeTemplate[] }>('/api/v1/agent-templates');
        set({ templates: data.items, loading: false, error: null });
      } catch (err) {
        set({ error: err instanceof Error ? err.message : String(err), loading: false });
      }
    },
    // Coverage-Gap 补测（#107 失败路径）：三个写操作包 vi.fn —— 默认实现不变
    // （与 stores/templates.test.ts 契约一致），失败用例以 mockRejectedValueOnce 注入 reject
    createTemplate: vi.fn(async (input: unknown) => {
      const created = { ...(input as object), id: 999, is_default: false, used_by: [] } as unknown as FakeTemplate;
      set((s) => ({ templates: [...s.templates, created], error: null }));
      return created;
    }),
    updateTemplate: vi.fn(async (id: number, patch: unknown) => {
      const updated = await apiFetch<FakeTemplate>(`/api/v1/agent-templates/${id}`, {
        method: 'PATCH',
        body: patch,
      });
      set((s) => ({
        templates: s.templates.map((t) => (t.id === id ? updated : t)),
        error: null,
      }));
      return updated;
    }),
    deleteTemplate: vi.fn(async (id: number) => {
      await apiFetch(`/api/v1/agent-templates/${id}`, { method: 'DELETE' });
      set((s) => ({ templates: s.templates.filter((t) => t.id !== id), error: null }));
    }),
    duplicateTemplate: async (id) => {
      const dup = await apiFetch<FakeTemplate>(`/api/v1/agent-templates/${id}/duplicate`, {
        method: 'POST',
      });
      set((s) => ({ templates: [...s.templates, dup], error: null }));
      return dup;
    },
    setDefault: async (id) => {
      // 后端 SetDefaultRequest.id 契约为 str（与 stores/templates.test.ts 断言一致）
      await apiFetch('/api/v1/agent-templates/default', { method: 'PATCH', body: { id: String(id) } });
      set((s) => ({
        defaultTemplateId: id,
        templates: s.templates.map((t) => ({ ...t, is_default: t.id === id })),
        error: null,
      }));
    },
    loadDefault: async () => {
      try {
        const data = await apiFetch<FakeTemplate>('/api/v1/agent-templates/default');
        set({ defaultTemplateId: data.id, error: null });
      } catch (err) {
        set({ error: err instanceof Error ? err.message : String(err) });
      }
    },
  }));
  return { useTemplatesStore };
});

vi.mock('../components/TemplateDialog', async () => {
  const React = await import('react');
  function TemplateDialog(props: {
    open?: boolean;
    editing?: { name?: string } | null;
    onCreate?: (input: unknown) => void;
    onUpdate?: (input: unknown) => void;
    onOpenChange?: (open: boolean) => void;
  }) {
    const [name, setName] = React.useState(props.editing?.name ?? '');
    if (!props.open) return null;
    const save = () => {
      const input = props.editing ? { ...props.editing, name } : { name };
      if (props.editing) props.onUpdate?.(input);
      else props.onCreate?.(input);
    };
    return React.createElement(
      'div',
      { 'data-testid': 'template-dialog', role: 'dialog' },
      React.createElement('input', {
        'data-testid': 'template-name-input',
        value: name,
        onChange: (e: React.ChangeEvent<HTMLInputElement>) => setName(e.target.value),
      }),
      React.createElement('button', { 'data-testid': 'template-save', onClick: save }, '保存'),
      React.createElement(
        'button',
        { 'data-testid': 'template-cancel', onClick: () => props.onOpenChange?.(false) },
        '取消',
      ),
    );
  }
  return { TemplateDialog };
});

const apiFetchMock = vi.mocked(apiFetch);
// F32（#152）：theme store 扩展契约的测试侧类型（拆分自 settings.test.tsx F32 段；beforeEach 引用）
type FontKeyF32 = 'serif' | 'sans' | 'mono';
type CloseBehaviorF32 = 'tray' | 'quit';
type ThemeStoreF32 = ReturnType<typeof useThemeStore.getState> & {
  font: FontKeyF32;
  closeBehavior: CloseBehaviorF32;
  trayHintDismissed: boolean;
  setFont: (f: FontKeyF32) => Promise<boolean>;
  setCloseBehavior: (b: CloseBehaviorF32) => Promise<boolean>;
  setTrayHintDismissed: (v: boolean) => Promise<boolean>;
  initFromBackend: () => Promise<void>;
};


function renderSettings(initialPath = '/settings') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <SettingsPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  // F32（#152）：patchSettings/fetchSettings mock 默认成功（全默认设置对象，§3.2）；
  // 各用例可按需 mockResolvedValueOnce 覆盖
  patchSettingsMock.mockReset();
  patchSettingsMock.mockResolvedValue({
    theme: 'paper',
    bg: 'default',
    lang: 'zh',
    font: 'sans',
    close_behavior: 'tray',
    tray_hint_dismissed: false,
  });
  fetchSettingsMock.mockReset();
  fetchSettingsMock.mockResolvedValue({
    theme: 'paper',
    bg: 'default',
    lang: 'zh',
    font: 'sans',
    close_behavior: 'tray',
    tray_hint_dismissed: false,
    // #198：默认补齐 default_words（后端 AppSettings 恒返回；无项目回显兜底源）
    default_words: 800000,
  });
  // F32（#152）：扩展重置 font/closeBehavior/trayHintDismissed——测试间隔离，
  // 防「上一用例改 store 值 → 下一用例 Select 初值漂移」污染既有用例（GREEN 后 cast 可删）
  useThemeStore.setState({
    theme: 'paper', bg: 'default', lang: 'zh',
    font: 'sans', closeBehavior: 'tray', trayHintDismissed: false,
  } as unknown as Partial<ThemeStoreF32>);
  useProjectStore.setState({
    projects: [{ id: 'p1', name: '青云志', genre: '玄幻', language: 'zh-CN', target_words: 800000, config: {}, created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z' }],
    currentProjectId: 'p1', loading: false, error: null,
  });
  useAgentStore.setState({ config: {}, apiKeyDraft: '', testStatus: 'idle', testMessage: null });
  useToastStore.setState({ toasts: [] });
  // F42 #268：默认 mock 按 URL 分发——AgentChainCard 挂载会 loadProviders()
  // （GET /api/v1/provider-configs，spec §5.2 数据源）；其余请求保持 {ok:true}
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/provider-configs') {
      return { items: [], total: 0, offset: 0, limit: 50 };
    }
    return { ok: true };
  });
});

describe('设置页 — 下拉即改即存分支（#105 补测）', () => {
  it('语言下拉：切换 → themeStore.lang 更新', async () => {
    const user = userEvent.setup();
    renderSettings();
    await user.click(screen.getByRole('combobox', { name: '语言' }));
    await user.click(await screen.findByRole('option', { name: 'EN' }));
    expect(useThemeStore.getState().lang).toBe('en');
  });

  it('背景变体下拉：切换 → themeStore.bg 更新（paper 主题第二变体 parchment）', async () => {
    const user = userEvent.setup();
    renderSettings();
    await user.click(screen.getByRole('combobox', { name: '背景' }));
    await user.click(await screen.findByRole('option', { name: /parchment|羊皮/i }));
    expect(useThemeStore.getState().bg).toBe('parchment');
  });

  it('编辑器字体下拉：切换 → 触发回读选中值（本地状态）', async () => {
    const user = userEvent.setup();
    renderSettings();
    await user.click(screen.getByRole('combobox', { name: '编辑器字体' }));
    await user.click(await screen.findByRole('option', { name: '等宽' }));
    expect(screen.getByRole('combobox', { name: '编辑器字体' })).toHaveTextContent('等宽');
  });
});

describe('设置页 — 默认模型下拉回读与选择（#105 补测；F42 #268 R1 ② 改 provider/model）', () => {
  async function openAgentPanel() {
    const user = userEvent.setup();
    renderSettings();
    await user.click(within(screen.getByTestId('settings-nav')).getByRole('button', { name: 'Agent' }));
    return user;
  }

  /** R1 ②：默认模型下拉数据源 = provider-configs chat 模型（spec §5.2 Q3）——mock 注入 deepseek/ollama 两 provider */
  function mockChatProviders() {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/provider-configs') {
        return {
          items: [
            {
              id: 2, name: 'deepseek', base_url: 'https://api.deepseek.com', default_model: 'deepseek-chat',
              models: [{ id: 'deepseek-chat', type: 'chat', roles: [] }],
              key_saved: false, max_retries: 3, timeout: 60,
              created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
            },
            {
              id: 3, name: 'ollama', base_url: 'http://127.0.0.1:11434', default_model: 'qwen3',
              models: [{ id: 'qwen3', type: 'chat', roles: [] }],
              key_saved: false, max_retries: 3, timeout: 60,
              created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
            },
          ],
          total: 2, offset: 0, limit: 50,
        };
      }
      return { ok: true };
    });
  }

  it('config.model 已配置 → 下拉回读当前模型值（truthy 分支，完整 provider/model）', async () => {
    mockChatProviders();
    act(() => {
      useAgentStore.getState().setConfig({ model: 'deepseek/deepseek-chat' });
    });
    await openAgentPanel();
    expect(screen.getByRole('combobox', { name: '默认模型' })).toHaveTextContent('deepseek/deepseek-chat');
  });

  it('选择模型 → setConfig({ model }) 即改即存（完整 provider/model）', async () => {
    mockChatProviders();
    const user = await openAgentPanel();
    await user.click(screen.getByRole('combobox', { name: '默认模型' }));
    await user.click(await screen.findByRole('option', { name: 'ollama/qwen3' }));
    expect(useAgentStore.getState().config.model).toBe('ollama/qwen3');
    // 修复契约（#105 🔴-2）：下拉变更 → 即改即存 PATCH /api/v1/projects/p1 body config.model
    // （GREEN 前零 PATCH 调用 → RED）
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/projects/p1',
        expect.objectContaining({
          method: 'PATCH',
          body: expect.objectContaining({ config: expect.objectContaining({ model: 'ollama/qwen3' }) }),
        }),
      );
    });
  });
});

/**
 * #105 修复批二次迭代 RED 契约（2026-08-06 评审复查 🔴-A/🔴-B，交叉路径）：
 * 评审确认「播种守卫过松 + 两个 PATCH body 合并源不一致」→ general↔agent 交叉操作静默丢字段。
 * 基线 19/19 绿 → 追加后 3 FAIL = RED 证据（失败分类：守卫不播种 → toBeChecked FAIL；
 * 合并源旧快照 → 最新 PATCH body 断言 FAIL；失败 toast → waitFor 超时 FAIL）：
 * - 🔴-A 播种守卫收紧：general 先改 default_words（store 仅 {default_words}）→ 切 agent 仍按
 *   项目 config 重新播种，四开关初始状态与项目 config 一致（守卫 = config 不含 model 且不含
 *   任何 agent_* 系字段才播种；default_words 等非结构性字段不拦截）
 * - 🔴-B 交叉操作不丢字段：agent toggle 落库后回 general 改 default_words → 最新 PATCH body
 *   config 含全部已配置字段（合并源 = agent store 当前 config，非 project store 旧快照）
 * - 失败 PATCH 弹 err toast（现状 catch 吞掉后无条件 pushToast('ok')）
 */
describe('设置页 — #105 修复批二次迭代（交叉路径 RED 契约）', () => {
  /** 播种当前项目 p1 的 config（同 Agent 分类 describe 的 helper；beforeEach 已置 currentProjectId='p1'） */
  function seedProjectConfig(config: ProjectConfig) {
    useProjectStore.setState({
      projects: [
        {
          id: 'p1', name: '青云志', genre: '玄幻', language: 'zh-CN', target_words: 800000,
          config,
          created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
        },
      ],
    });
  }

  it('🔴-A 播种守卫收紧：general 先改 default_words → 切 agent 仍按项目 config 播种（四开关状态与项目 config 一致）', async () => {
    // 项目 config：model='gpt-4o'、agent_writer='deepseek'（开）、architect/auditor/reviser 未配置（关）
    seedProjectConfig({ model: 'gpt-4o', agent_writer: 'deepseek', default_words: 50000 });
    const user = userEvent.setup();
    renderSettings();

    // General 分类改 default_words → setConfig 使 store 只有 {default_words}（1 个非结构性 key）
    const input = screen.getByLabelText('新章节默认字数');
    await user.clear(input);
    await user.type(input, '80000');
    await user.tab();
    expect(Object.keys(useAgentStore.getState().config)).toEqual(['default_words']);

    // 切到 Agent 分类：现状守卫「keys > 0 跳过播种」→ 四开关全 off → toBeChecked FAIL = RED
    await user.click(within(screen.getByTestId('settings-nav')).getByRole('button', { name: 'Agent' }));
    const card = screen.getByTestId('agent-chain-card');
    const switches = within(card).getAllByRole('switch');
    expect(switches[1]).toBeChecked(); // Writer（agent_writer='deepseek'）
    expect(switches[0]).not.toBeChecked(); // Architect 未配置
    expect(switches[2]).not.toBeChecked(); // Auditor 未配置
    expect(switches[3]).not.toBeChecked(); // Reviser 未配置
    expect(useAgentStore.getState().config.model).toBe('gpt-4o');
    expect(useAgentStore.getState().config.agent_writer).toBe('deepseek');
  });

  it('🔴-B 交叉操作不丢字段：agent toggle 后回 general 改 default_words → 最新 PATCH body 含全部已配置字段', async () => {
    seedProjectConfig({ model: 'gpt-4o', agent_architect: 'deepseek', default_words: 30000 });
    const user = userEvent.setup();
    renderSettings();

    // Agent 分类：store 空 → 挂载播种；architect 关→开（#225：关=null / 开="__default__" sentinel）
    await user.click(within(screen.getByTestId('settings-nav')).getByRole('button', { name: 'Agent' }));
    const card = screen.getByTestId('agent-chain-card');
    const switches = within(card).getAllByRole('switch');
    await user.click(switches[0]);
    await user.click(switches[0]);
    await waitFor(() => {
      expect(useAgentStore.getState().config.agent_architect).toBe('__default__');
    });

    // 回 General 分类：改 default_words → 失焦 PATCH
    await user.click(within(screen.getByTestId('settings-nav')).getByRole('button', { name: '常规' }));
    const input = screen.getByLabelText('新章节默认字数');
    await user.clear(input);
    await user.type(input, '60000');
    await user.tab();

    // 契约：最新 PATCH body config = 全部已配置字段（现状合并源 = project store 旧快照 →
    // agent_architect 回 'deepseek' 而非 '__default__' → FAIL = RED；#225：终态开 = sentinel）
    await waitFor(() => {
      const patchCalls = apiFetchMock.mock.calls.filter((c) => c[1]?.method === 'PATCH');
      expect(patchCalls.length).toBeGreaterThanOrEqual(3); // toggle 关 + toggle 开 + general 失焦
      const lastBody = patchCalls[patchCalls.length - 1][1]?.body as { config: ProjectConfig };
      expect(lastBody.config).toEqual(
        expect.objectContaining({ model: 'gpt-4o', agent_architect: '__default__', default_words: 60000 }),
      );
    });
  });

  it('PATCH 失败 → err toast（现状 catch 吞掉后无条件 ok → 断言 err 型 toast 出现）', async () => {
    apiFetchMock.mockRejectedValueOnce(new Error('network down'));
    const user = userEvent.setup();
    renderSettings();

    const input = screen.getByLabelText('新章节默认字数');
    await user.clear(input);
    await user.type(input, '5000');
    await user.tab();

    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts.length).toBeGreaterThan(0);
      expect(toasts[toasts.length - 1].type).toBe('err');
    });
  });
});

/**
 * #105 修复批二次迭代 Coverage-Gap 补测（非 RED，测试预期直接全绿）：
 * defaultWords blur 失败/非法分支 —— <1000 不发 PATCH + err toast「保存失败」；
 * 空值失焦不弹任何 toast（「PATCH reject → err toast」已由上方「PATCH 失败 → err toast」用例覆盖）。
 */
describe('设置页 — defaultWords 失败/非法值分支（#105 补测）', () => {
  it('输入 < 1000 失焦：不发 PATCH + err toast「保存失败」（与后端 ge=1000 对齐）', async () => {
    const user = userEvent.setup();
    renderSettings();

    const input = screen.getByLabelText('新章节默认字数');
    await user.clear(input);
    await user.type(input, '500');
    await user.tab();

    // 低于下限：不发 PATCH，直接 err toast
    expect(apiFetchMock).not.toHaveBeenCalled();
    const toasts = useToastStore.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0]).toEqual(expect.objectContaining({ type: 'err', message: '保存失败' }));
  });

  it('空值失焦：不发 PATCH、不弹任何 toast（无变更静默）', async () => {
    const user = userEvent.setup();
    renderSettings();

    const input = screen.getByLabelText('新章节默认字数');
    await user.clear(input); // value=''
    await user.tab();

    expect(apiFetchMock).not.toHaveBeenCalled();
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });
});

/**
 * #105 修复批二次迭代 Coverage-Gap 补测（非 RED）：AgentPanel persist 并发守卫
 * （🟡-E）——saveConfig reject → err toast；in-flight 期间再次变更挂起 pending，
 * 当前 PATCH 结束后以最新 config 补存（不丢最后一次 toggle）。
 */
describe('设置页 — AgentPanel persist 并发守卫（#105 补测）', () => {
  async function openAgentPanel() {
    const user = userEvent.setup();
    renderSettings();
    await user.click(within(screen.getByTestId('settings-nav')).getByRole('button', { name: 'Agent' }));
    return user;
  }

  it('saveConfig reject → err toast「保存失败」（persist catch 分支）', async () => {
    // F42 #268：AgentChainCard 挂载会 loadProviders()（GET provider-configs 成功）；
    // 仅 PATCH /projects/p1 reject（Once 语义从「首个请求」升级为「PATCH 请求」，防 GET 消费）
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/provider-configs') {
        return { items: [], total: 0, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/projects/p1' && init?.method === 'PATCH') {
        throw new Error('network down');
      }
      return { ok: true };
    });
    const user = await openAgentPanel();
    const card = screen.getByTestId('agent-chain-card');

    await user.click(within(card).getAllByRole('switch')[0]);

    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts).toHaveLength(1);
      expect(toasts[0]).toEqual(expect.objectContaining({ type: 'err', message: '保存失败' }));
    });
  });

  it('in-flight 期间再次 toggle → pending 补存：当前 PATCH 结束后以最新 config 重发', async () => {
    let resolvePatch!: (v: unknown) => void;
    let hold = true;
    // 首个 PATCH 挂起（手动 resolve），后续 PATCH 立即成功；
    // F42 #268：provider-configs GET 直接成功（AgentChainCard 挂载 loadProviders）
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/provider-configs') {
        return { items: [], total: 0, offset: 0, limit: 50 };
      }
      if (init?.method === 'PATCH' && hold) {
        hold = false;
        return new Promise((resolve) => {
          resolvePatch = resolve;
        });
      }
      return { ok: true };
    });

    const user = await openAgentPanel();
    const card = screen.getByTestId('agent-chain-card');
    const switches = within(card).getAllByRole('switch');

    // F42 #268 适配：挂载后 apiFetch 含 provider-configs GET → 计数断言改为「仅数 PATCH 调用」
    const patchCallCount = () =>
      apiFetchMock.mock.calls.filter((c) => c[1]?.method === 'PATCH').length;

    // 第一次 toggle（off→on）：agent_architect="__default__"（#225 打开=sentinel）→ PATCH #1 in-flight（persistingRef=true）
    await user.click(switches[0]);
    await waitFor(() => expect(patchCallCount()).toBe(1));

    // 第二次 toggle（on→off）：agent_architect=null（#225 关闭=显式 null）；并发守卫挂起 pending，不发新 PATCH
    await user.click(switches[0]);
    expect(patchCallCount()).toBe(1);

    // 完成 PATCH #1 → finally 检测 pending → 以最新 config 补存 PATCH #2
    await act(async () => {
      resolvePatch({ ok: true });
    });
    await waitFor(() => expect(patchCallCount()).toBe(2));

    const patchCalls = apiFetchMock.mock.calls.filter((c) => c[1]?.method === 'PATCH');
    const firstBody = patchCalls[0][1]?.body as { config: ProjectConfig };
    const lastBody = patchCalls[patchCalls.length - 1][1]?.body as { config: ProjectConfig };
    expect(firstBody.config).toEqual({ agent_architect: '__default__' }); // toggle1（开）的 config
    expect(lastBody.config).toEqual({ agent_architect: null }); // toggle2（关，最新）的 config——#225：显式 null 非 undefined
  });

  it('无当前项目：persist 早退（不发 PATCH、不弹 toast）', async () => {
    useProjectStore.setState({ currentProjectId: null, projects: [] });
    const user = await openAgentPanel();
    const card = screen.getByTestId('agent-chain-card');

    await user.click(within(card).getAllByRole('switch')[0]);

    // F42 #268 适配：AgentChainCard 挂载会 loadProviders()（provider-configs GET 允许）；
    // 契约 = 无 PATCH 调用（persist 早退）+ 无 toast
    expect(apiFetchMock.mock.calls.filter((c) => c[1]?.method === 'PATCH')).toHaveLength(0);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });
});

/**
 * #105 Coverage-Gap 补测（非 RED）：账户分类 /health 兜底分支
 * （version 三元 truthy 侧 / 非字符串 / 空字符串 / fetch reject → setVersion(null)）。
 */
describe('设置页 — 账户 /health 版本兜底分支（#105 补测）', () => {
  async function openAccountPanel() {
    const user = userEvent.setup();
    renderSettings();
    await user.click(within(screen.getByTestId('settings-nav')).getByRole('button', { name: '账户' }));
    return user;
  }

  it('/health reject → catch 兜底 setVersion(null)：不展示版本号', async () => {
    apiFetchMock.mockRejectedValueOnce(new Error('kernel down'));
    await openAccountPanel();
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledWith('/health'));
    expect(screen.queryByText(/v\d+\.\d+\.\d+/)).not.toBeInTheDocument();
  });

  it('/health 返回非字符串 version（如 12345）→ 不展示版本号', async () => {
    apiFetchMock.mockResolvedValueOnce({ version: 12345 });
    await openAccountPanel();
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledWith('/health'));
    expect(screen.queryByText(/v\d+\.\d+\.\d+/)).not.toBeInTheDocument();
  });

  it('/health 返回空字符串 version → 不展示版本号', async () => {
    apiFetchMock.mockResolvedValueOnce({ version: '' });
    await openAccountPanel();
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledWith('/health'));
    expect(screen.queryByText(/v\d+\.\d+\.\d+/)).not.toBeInTheDocument();
  });

  it('/health 返回合法 version → 展示「v版本号」', async () => {
    apiFetchMock.mockResolvedValueOnce({ version: '1.2.3' });
    await openAccountPanel();
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledWith('/health'));
    expect(await screen.findByText(/v1\.2\.3/)).toBeInTheDocument();
  });
});

/**
 * #167 F31 GUI 托盘常驻 RED 契约（2026-08-08，spec §6.2 设置页 UI + §2.3 IPC 契约）。
 * RED 预期：GREEN 前 GeneralPanel 无「关闭窗口时」设置项 → 本 describe 全部 FAIL
 * （Unable to find combobox/getByText「关闭窗口时」= element-missing；
 * getCloseBehavior 零调用 = expected number of calls: 1），既有用例保持绿。
 *
 * GREEN 契约（settings.tsx GeneralPanel + preload settings 命名空间 + i18n）：
 * - 渲染「关闭窗口时」标签（t('set.closeBehavior')）+ Select：combobox aria-label
 *   「关闭窗口时」，选项 = 最小化到系统托盘（t('set.closeBehavior.tray')，value 'tray'）/
 *   直接退出（t('set.closeBehavior.quit')，value 'quit'）；初值 'tray'
 * - 挂载 useEffect：window.INKFLOW_API?.settings?.getCloseBehavior() 取初值
 * - onValueChange：window.INKFLOW_API?.settings?.setCloseBehavior(v)（选择即生效，可选链吞掉）
 * - 无 window.INKFLOW_API（浏览器 dev）→ 渲染不崩，Select 仍默认显示 tray 文案
 */
