/**
 * 设置页 五分类导航/常规/Agent/模型账户 测试（拆分自 settings.test.tsx，#281 测试文件规模治理）。
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

/** #473 R1：后端 BUILTIN_AGENT_SPECS 6 内置镜像（内置角色行派生真源；空列表用例局部覆盖） */
const BUILTIN_AGENTS = [
  { id: 101, name: '架构师', description: '章节结构/大纲规划', icon: '🏗️', system_prompt: '你是架构师。', tool_ids: [], skill_ids: [], model_override: null, temperature_override: null, builtin: true, role_key: 'architect', created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
  { id: 102, name: '写手', description: '正文生成', icon: '✍️', system_prompt: '你是写手。', tool_ids: [], skill_ids: [], model_override: null, temperature_override: null, builtin: true, role_key: 'writer', created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
  { id: 103, name: '审校员', description: '一致性审计', icon: '🔍', system_prompt: '你是审校员。', tool_ids: [], skill_ids: [], model_override: null, temperature_override: null, builtin: true, role_key: 'auditor', created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
  { id: 104, name: '修订师', description: '修订打磨', icon: '🛠️', system_prompt: '你是修订师。', tool_ids: [], skill_ids: [], model_override: null, temperature_override: null, builtin: true, role_key: 'reviser', created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
  { id: 105, name: '世界观顾问', description: '世界观一致', icon: '🌍', system_prompt: '你是世界观顾问。', tool_ids: [], skill_ids: [], model_override: null, temperature_override: null, builtin: true, role_key: null, created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
  { id: 106, name: '润色师', description: '文笔润色', icon: '✨', system_prompt: '你是润色师。', tool_ids: [], skill_ids: [], model_override: null, temperature_override: null, builtin: true, role_key: null, created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
] as const;

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
  // F41 #260：AgentList 挂载会 loadAgents/loadToolCatalog/loadSkills（3 GET）——同样分发
  // #473 R1：agents 默认返回 6 内置（内置角色行派生数据源）；空列表用例局部覆盖
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/provider-configs') {
      return { items: [], total: 0, offset: 0, limit: 50 };
    }
    if (path === '/api/v1/agents') return { items: BUILTIN_AGENTS, total: 6, offset: 0, limit: 50 };
    if (path === '/api/v1/agents/tools') return { items: [] };
    if (path === '/api/v1/skills') return { items: [], total: 0 };
    return { ok: true };
  });
});

describe('设置页 — 五分类导航（spec §7.4）', () => {
  it('settings-nav 五分类按钮 + 默认常规面板（仅激活面板渲染）', () => {
    renderSettings();
    expect(screen.getByTestId('settings-page')).toBeInTheDocument();
    const nav = screen.getByTestId('settings-nav');
    for (const name of ['常规', '模型', 'Agent', '模板', '账户']) {
      expect(within(nav).getByRole('button', { name })).toBeInTheDocument();
    }
    // 默认常规：主题 radio 可见，Agent 面板未挂载
    expect(screen.getByTestId('settings-panel')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /素笺/ })).toBeInTheDocument();
    expect(screen.queryByTestId('agent-chain-card')).not.toBeInTheDocument();
  });

  it('分类切换：点击 Agent → Agent 面板挂载（agent-chain-card 保留迁移），常规面板卸载', async () => {
    const user = userEvent.setup();
    renderSettings();
    await user.click(within(screen.getByTestId('settings-nav')).getByRole('button', { name: 'Agent' }));
    expect(screen.getByTestId('settings-panel')).toBeInTheDocument();
    expect(screen.getByTestId('agent-chain-card')).toBeInTheDocument();
    expect(screen.queryByRole('radio')).not.toBeInTheDocument();
  });

  it('深链直达：/settings?cat=agent → 初始 Agent 面板（导航 Agent 快捷入口联动）', () => {
    renderSettings('/settings?cat=agent');
    expect(screen.getByTestId('agent-chain-card')).toBeInTheDocument();
    expect(screen.queryByRole('radio')).not.toBeInTheDocument();
  });
});

describe('设置页 — 常规分类', () => {
  it('控件齐全：语言 / 主题 radio×3 / 背景变体 / 编辑器字体 / 新章节默认字数 / 快捷键一览表', () => {
    renderSettings();
    const panel = screen.getByTestId('settings-panel');

    expect(within(panel).getByRole('combobox', { name: '语言' })).toBeInTheDocument();
    expect(within(panel).getAllByRole('radio')).toHaveLength(3);
    expect(within(panel).getByRole('combobox', { name: '背景' })).toBeInTheDocument();
    expect(within(panel).getByRole('combobox', { name: '编辑器字体' })).toBeInTheDocument();
    expect(within(panel).getByLabelText('新章节默认字数')).toBeInTheDocument();

    // 快捷键一览表：五组快捷键组合（#105 修复批：生成 = Ctrl+Shift+Enter，非裸 Shift+Enter）
    // 注意 'Shift+Enter' 是 'Ctrl+Shift+Enter' 的子串 → 禁 toHaveTextContent 子串断言；
    // 收集 kbd 文本精确匹配（kbd 无 role，DOM 查询）。GREEN 前为 Shift+Enter → toEqual FAIL = RED
    const shortcuts = screen.getByTestId('settings-shortcuts');
    const combos = Array.from(shortcuts.querySelectorAll('kbd')).map((k) => k.textContent ?? '');
    expect(combos).toEqual(['Ctrl+Z', 'Ctrl+Y', 'Ctrl+S', 'Ctrl+Enter', 'Ctrl+Shift+Enter']);
  });

  it('主题预览卡存在于常规面板：theme-preview-paper/night/ink（#105 🔴-3 修复契约：GeneralPanel 挂载 AppearanceCard）', () => {
    renderSettings();
    const panel = screen.getByTestId('settings-panel');
    // GREEN 前 GeneralPanel 是裸 RadioGroup 重复实现、AppearanceCard 全仓 0 引用 → 预览卡不存在 → RED
    expect(within(panel).getByTestId('theme-preview-paper')).toBeInTheDocument();
    expect(within(panel).getByTestId('theme-preview-night')).toBeInTheDocument();
    expect(within(panel).getByTestId('theme-preview-ink')).toBeInTheDocument();
  });

  it('主题 radio 切换 → themeStore.theme（迁移自 AppearanceCard 行为）', async () => {
    const user = userEvent.setup();
    renderSettings();

    expect(useThemeStore.getState().theme).toBe('paper');
    await user.click(screen.getByRole('radio', { name: /夜航/ }));
    expect(useThemeStore.getState().theme).toBe('night');
    await user.click(screen.getByRole('radio', { name: /墨韵/ }));
    expect(useThemeStore.getState().theme).toBe('ink');
  });

  it('即改即存：新章节默认字数输入 1000 失焦 → 真实 PATCH config.default_words + toast「已保存」（#105 修复批：假 toast → 真实持久化）', async () => {
    const user = userEvent.setup();
    renderSettings();

    const input = screen.getByLabelText('新章节默认字数');
    await user.clear(input);
    await user.type(input, '1000');
    await user.tab(); // 失焦 → 即存

    // 修复契约：失焦必须真实 PATCH /api/v1/projects/p1 body config 含 default_words: 1000
    // （GREEN 前 onBlur 只 pushToast、值仅存本地 state → 零 PATCH 调用 → RED）
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/projects/p1',
        expect.objectContaining({
          method: 'PATCH',
          body: expect.objectContaining({ config: expect.objectContaining({ default_words: 1000 }) }),
        }),
      );
    });

    // toast 仍弹（既有行为不回归）
    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts.length).toBeGreaterThan(0);
      expect(toasts[toasts.length - 1].type).toBe('ok');
      expect(toasts[toasts.length - 1].message).toBe('已保存');
    });
  });

  // ⚠️ #189 rc1 发布缺陷（2026-08-08）：default_words 卸载 flush 在 Electron 托盘退出路径失效——
  // 「改完不失去焦点直接关窗口」→ 窗口 hide（组件不卸载、无失焦）→ flush 不触发 → 重启丢失。
  // RED 契约（GREEN 前 FAIL = 实现缺陷证据）：
  // 1. 输入停止后 debounce 自动保存（不依赖失焦/卸载/visibility）
  // 2. document visibilitychange(hidden) → flush（Electron 窗口隐藏到托盘触发 renderer 事件）
  it('#189 输入停止自动保存：输入 1500 不失去焦点 → 自动 PATCH（不依赖失焦/卸载）', async () => {
    const user = userEvent.setup();
    renderSettings();

    const input = screen.getByLabelText('新章节默认字数');
    await user.clear(input);
    await user.type(input, '1500');
    // 不 tab/blur——模拟「改完直接关窗口」的失焦缺失场景；输入停止后防抖到期应自动保存
    await waitFor(
      () => {
        expect(apiFetchMock).toHaveBeenCalledWith(
          '/api/v1/projects/p1',
          expect.objectContaining({
            method: 'PATCH',
            body: expect.objectContaining({ config: expect.objectContaining({ default_words: 1500 }) }),
          }),
        );
      },
      { timeout: 3000 },
    );
  });

  it('#189 窗口隐藏 flush：输入 2000 → visibilitychange(hidden) → PATCH（Electron 托盘 hide 路径）', async () => {
    const user = userEvent.setup();
    renderSettings();

    const input = screen.getByLabelText('新章节默认字数');
    await user.clear(input);
    await user.type(input, '2000');
    // 模拟 Electron 关闭按钮 → 窗口隐藏到托盘（renderer 收到 visibilitychange hidden，组件不卸载）
    Object.defineProperty(document, 'hidden', { value: true, configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/projects/p1',
        expect.objectContaining({
          method: 'PATCH',
          body: expect.objectContaining({ config: expect.objectContaining({ default_words: 2000 }) }),
        }),
      );
    });
    Object.defineProperty(document, 'hidden', { value: false, configurable: true });
  });

  // ⚠️ #189 全局默认（2026-08-08 用户拍板方案 A）：无当前项目时 default_words 不再静默丢弃——
  // 防抖到期 PATCH /api/v1/settings {default_words}（全局默认语义）；有项目时仍 PATCH 项目 config。
  it('#189 全局默认：无当前项目时改 default_words → 防抖到期 patchSettings({default_words})（不再静默丢弃）', async () => {
    useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
    const user = userEvent.setup();
    renderSettings();
    const input = screen.getByLabelText('新章节默认字数');
    await user.clear(input);
    await user.type(input, '300000');
    // 不失去焦点（防抖自动保存路径）——无项目时目标为全局 settings（patchSettingsMock：
    // vi.hoisted 替换，不走 apiFetch——2026-08-08 父侧裁定）
    await waitFor(
      () => {
        expect(patchSettingsMock).toHaveBeenCalledWith({ default_words: 300000 });
      },
      { timeout: 3000 },
    );
  });

  // ⚠️ #189 用户追加拍板（2026-08-08）：保存成功后页面正上方提示「已保存」
  // （参考 Notion / Google Docs 顶部保存指示：顶部小字、成功显示约 2s 淡出）
  // data-testid 契约：settings-save-indicator（页面正上方容器，文本 = 当前保存状态）
  it('#189 保存成功 → 页面正上方提示「已保存」（settings-save-indicator）', async () => {
    const user = userEvent.setup();
    renderSettings();

    const input = screen.getByLabelText('新章节默认字数');
    await user.clear(input);
    await user.type(input, '3000');
    await user.tab(); // 失焦触发保存
    await waitFor(() => {
      const indicator = screen.getByTestId('settings-save-indicator');
      expect(indicator.textContent).toBe('已保存');
    });
  });

  // ⚠️ #198（2026-08-09，rc4 复验缺陷）：default_words 全局值重启加载失败——
  // 设置页初始值只从项目 config 读（无项目兜底 800000），不从 fetchSettings().default_words 读。
  // 修复契约：初始值 = 项目 config.default_words 存在时优先，否则读全局 fetchSettings()；
  // 保存路径维持 #189（有项目 → 项目 config；无项目 → 全局 settings）。GREEN 需在
  // settings.tsx GeneralPanel 引入 fetchSettings 读取（经 fetchSettingsMock 断言 wire）。
  it('#198 无项目 + 后端全局 default_words → 初始值显示全局值（重启回显，非 800000 兜底）', async () => {
    useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
    fetchSettingsMock.mockResolvedValueOnce({
      theme: 'paper', bg: 'default', lang: 'zh', font: 'sans',
      close_behavior: 'tray', tray_hint_dismissed: false, default_words: 123456,
    });
    renderSettings();
    const input = screen.getByLabelText('新章节默认字数');
    // GREEN 前初始值恒 800000 → toHaveValue(123456) FAIL = RED
    await waitFor(() => {
      expect(input).toHaveValue(123456);
    });
  });

  it('#198 有项目 config.default_words=60000 → 项目级优先（fetchSettings 全局值不覆盖）', async () => {
    useProjectStore.setState({
      projects: [{
        id: 'p1', name: '青云志', genre: '玄幻', language: 'zh-CN', target_words: 800000,
        config: { default_words: 60000 },
        created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
      }],
      currentProjectId: 'p1', loading: false, error: null,
    });
    fetchSettingsMock.mockResolvedValueOnce({
      theme: 'paper', bg: 'default', lang: 'zh', font: 'sans',
      close_behavior: 'tray', tray_hint_dismissed: false, default_words: 123456,
    });
    renderSettings();
    const input = screen.getByLabelText('新章节默认字数');
    await waitFor(() => {
      expect(input).toHaveValue(60000);
    });
    // 异步全局值到达后也不得覆盖项目级值（给 fetch promise 足够时间 settle 再复核；
    // 确认型：GREEN 若短路不 fetch（项目有级值）也绿，若 fetch 则不得覆盖）
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(input).toHaveValue(60000);
  });

  it('#198 有项目但 config 无 default_words → 读全局 fetchSettings 值（项目未设 → 全局兜底链）', async () => {
    // beforeEach 项目 p1 config: {}（无 default_words）
    fetchSettingsMock.mockResolvedValueOnce({
      theme: 'paper', bg: 'default', lang: 'zh', font: 'sans',
      close_behavior: 'tray', tray_hint_dismissed: false, default_words: 234567,
    });
    renderSettings();
    const input = screen.getByLabelText('新章节默认字数');
    // GREEN 前恒 800000 → toHaveValue(234567) FAIL = RED
    await waitFor(() => {
      expect(input).toHaveValue(234567);
    });
  });

  it('#198 fetchSettings 失败 → 保持 800000 兜底（静默，无 toast 无错误态）', async () => {
    useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
    fetchSettingsMock.mockRejectedValueOnce(new Error('network down'));
    renderSettings();
    const input = screen.getByLabelText('新章节默认字数');
    // 确认型守卫：RED 阶段现状即 800000（无 fetch 调用）——GREEN 后 fetch 失败也不得污染
    await waitFor(() => {
      expect(input).toHaveValue(800000);
    });
    const toasts = useToastStore.getState().toasts;
    expect(toasts.length).toBe(0);
  });
});

describe('设置页 — Agent 分类（迁移自 AgentChainCard，spec §7.4/§7.6）', () => {
  async function openAgentPanel() {
    const user = userEvent.setup();
    renderSettings();
    await user.click(within(screen.getByTestId('settings-nav')).getByRole('button', { name: 'Agent' }));
    return user;
  }

  /** 播种当前项目 p1 的 config（#105 🔴-2 走 loadFromProject 初始化路径；beforeEach 已置 currentProjectId='p1'） */
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

  it('四行渲染：后端真源派生名（架构师/写手/审校员/修订师）+ 描述 + 4 开关（#473 R1）', async () => {
    await openAgentPanel();
    const card = screen.getByTestId('agent-chain-card');
    // #473 R1：行名从 GET /api/v1/agents 按 role_key 派生（异步加载 → findByText）
    expect(await within(card).findByText('架构师')).toBeInTheDocument();
    expect(await within(card).findByText('写手')).toBeInTheDocument();
    expect(await within(card).findByText('审校员')).toBeInTheDocument();
    expect(await within(card).findByText('修订师')).toBeInTheDocument();
    expect(within(card).getAllByRole('switch')).toHaveLength(4);
  });

  it('开关 ↔ config.agent_*：#225 关闭 → null（禁用角色），重开 → "__default__"（跟随默认）', async () => {
    act(() => {
      useAgentStore.getState().setConfig({
        // F42 #268 R1 ③（spec §8 O2）：fixture 裸名 agent_* 改 provider/model（Q3 格式统一）
        agent_architect: 'openai/gpt-4o',
        agent_writer: '__default__',
        agent_auditor: 'openai/gpt-4o',
        agent_reviser: 'openai/gpt-4o',
      });
    });
    const user = await openAgentPanel();
    const card = screen.getByTestId('agent-chain-card');
    const switches = within(card).getAllByRole('switch');

    // checked 判定 = 字符串值（null=关闭 → 不勾选；"__default__" 是字符串 → 勾选）
    expect(switches[0]).toBeChecked();
    expect(switches[1]).toBeChecked();

    await user.click(switches[0]);
    expect(useAgentStore.getState().config.agent_architect).toBeNull();

    await user.click(switches[0]);
    expect(useAgentStore.getState().config.agent_architect).toBe('__default__');

    // 修复契约（#225）：开关变更 → 即改即存 PATCH /api/v1/projects/p1 body config 含
    // agent_architect（末次 = 重开态 sentinel；关闭态显式 null 由独立用例锁定）。
    // GREEN 前 AgentPanel 零持久化 → 无 PATCH 调用 → RED
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/projects/p1',
        expect.objectContaining({
          method: 'PATCH',
          body: expect.objectContaining({ config: expect.objectContaining({ agent_architect: '__default__' }) }),
        }),
      );
    });
  });

  it('#225 关闭即改即存：点击开关关闭 → PATCH body config 含 agent_architect: null（显式 null 非缺键）', async () => {
    seedProjectConfig({ agent_architect: 'gpt-4o' });
    const user = await openAgentPanel();
    const card = screen.getByTestId('agent-chain-card');
    const sw = within(card).getAllByRole('switch')[0];
    expect(sw).toBeChecked();

    await user.click(sw); // 关闭 → setConfig({agent_architect: null})（#225：不再发 undefined）

    // RED 证据（当前实现发 undefined → PATCH body 对象含 agent_architect: undefined，
    // objectContaining(null) 不匹配 → FAIL）；GREEN 后 body 含显式 null
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/projects/p1',
        expect.objectContaining({
          method: 'PATCH',
          body: expect.objectContaining({ config: expect.objectContaining({ agent_architect: null }) }),
        }),
      );
    });
  });

  it('loadFromProject 初始化：项目 config 播种 agent_architect=gpt-4o → 开关初始 checked（#105 🔴-2 修复契约）', async () => {
    // 不直设 agent store —— 初始化必须来自 AgentPanel 挂载时 loadFromProject(当前项目 config)
    seedProjectConfig({ agent_architect: 'gpt-4o' });
    await openAgentPanel();
    const card = screen.getByTestId('agent-chain-card');
    // GREEN 前 loadFromProject 无 UI 调用方 → agent store config 恒 {} → 开关未勾选 → RED
    expect(within(card).getAllByRole('switch')[0]).toBeChecked();
    expect(useAgentStore.getState().config.agent_architect).toBe('gpt-4o');
  });

  it('开关变更即改即存：点击开关 → PATCH /api/v1/projects/p1 body 含 config.agent_architect（#225 语义）', async () => {
    seedProjectConfig({
      agent_architect: 'gpt-4o',
      agent_writer: 'gpt-4o',
      agent_auditor: 'gpt-4o',
      agent_reviser: 'gpt-4o',
    });
    const user = await openAgentPanel();
    const card = screen.getByTestId('agent-chain-card');
    const switches = within(card).getAllByRole('switch');

    // 关 → 开（关 = null 禁用角色；开 = "__default__" 跟随默认 sentinel，#225）
    await user.click(switches[0]);
    await user.click(switches[0]);

    // GREEN 前无 PATCH 调用 → RED
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/projects/p1',
        expect.objectContaining({
          method: 'PATCH',
          body: expect.objectContaining({ config: expect.objectContaining({ agent_architect: '__default__' }) }),
        }),
      );
    });
  });

  it('#225 M2 重启持久化：项目 config.agent_writer=null（关闭）→ loadFromProject 后开关保持关闭', async () => {
    // 旧实现 checked = value !== undefined → null 误显示开启（#225 根因：重启读回 null → 开关恢复 on）
    seedProjectConfig({ agent_writer: null });
    await openAgentPanel();
    const card = screen.getByTestId('agent-chain-card');
    // RED 证据：当前实现 null !== undefined → 开关 checked → not.toBeChecked FAIL
    expect(within(card).getAllByRole('switch')[1]).not.toBeChecked();
    expect(useAgentStore.getState().config.agent_writer).toBeNull();
  });

  it('#225 M3 sentinel 读回：项目 config.agent_writer="__default__"（跟随默认）→ 开关开启', async () => {
    // 确认型：字符串（含 sentinel）→ 开关 checked（GREEN 判定 value !== null）
    seedProjectConfig({ agent_writer: '__default__' });
    await openAgentPanel();
    expect(within(screen.getByTestId('agent-chain-card')).getAllByRole('switch')[1]).toBeChecked();
  });

  it('默认模型下拉：combobox「默认模型」选项 = provider-configs chat 模型列表（F42 #268 R1 ①：openai/deepseek/ollama 硬编码 → chat 扁平）', async () => {
    // R1 ①：数据源改为 provider-configs chat 模型（spec §5.2 Q3）——mock 注入两 provider 的 chat 模型
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/provider-configs') {
        return {
          items: [
            {
              id: 1, name: 'openai', base_url: 'https://api.openai.com/v1', default_model: 'gpt-4o',
              models: [{ id: 'gpt-4o', type: 'chat', roles: [] }],
              key_saved: true, max_retries: 3, timeout: 60,
              created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
            },
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
          total: 3, offset: 0, limit: 50,
        };
      }
      // F41 #260：AgentList 挂载 3 GET 分发（行内覆盖 variant 同 beforeEach）
      if (path === '/api/v1/agents') return { items: [], total: 0 };
      if (path === '/api/v1/agents/tools') return { items: [] };
      if (path === '/api/v1/skills') return { items: [], total: 0 };
      return { ok: true };
    });
    const user = await openAgentPanel();
    await user.click(screen.getByRole('combobox', { name: '默认模型' }));
    expect(await screen.findByRole('option', { name: 'openai/gpt-4o' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'deepseek/deepseek-chat' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'ollama/qwen3' })).toBeInTheDocument();
  });

  it('F41 #260：Agent 管理列表挂载（agent-list 容器）+ 空列表 → 空态提示「暂无自定义 Agent」', async () => {
    // 默认 mock 已改为 6 内置（#473 R1 派生数据源）→ 本用例局部覆盖回空列表（AgentList 空态语义）
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/provider-configs') return { items: [], total: 0, offset: 0, limit: 50 };
      if (path === '/api/v1/agents') return { items: [], total: 0 };
      if (path === '/api/v1/agents/tools') return { items: [] };
      if (path === '/api/v1/skills') return { items: [], total: 0 };
      return { ok: true };
    });
    await openAgentPanel();
    expect(await screen.findByTestId('agent-list')).toBeInTheDocument();
    expect(screen.getByText('暂无自定义 Agent')).toBeInTheDocument();
  });

  it('F41 #260：深链 /settings?cat=agent → AgentList 挂载（Agent 快捷入口联动）', async () => {
    renderSettings('/settings?cat=agent');
    expect(await screen.findByTestId('agent-list')).toBeInTheDocument();
  });

  it('F41 #260：内置+自定义 Agent 渲染（内置只读徽标 / 自定义可编辑按钮）', async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/agents') {
        return {
          items: [
            { id: 1, name: '架构师', description: '章节结构/大纲规划', icon: '🏗️', system_prompt: '你是架构师。', tool_ids: ['search_characters'], skill_ids: ['1'], model_override: null, temperature_override: null, builtin: true, created_at: '2026-08-16T00:00:00Z', updated_at: '2026-08-16T00:00:00Z' },
            { id: 2, name: '我的润色师', description: '专注文笔润色', icon: '✨', system_prompt: '你是润色师。', tool_ids: ['count_words'], skill_ids: ['3'], model_override: 'zhipu/glm-4.5', temperature_override: 0.6, builtin: false, created_at: '2026-08-16T01:00:00Z', updated_at: '2026-08-16T01:00:00Z' },
          ],
          total: 2,
        };
      }
      if (path === '/api/v1/agents/tools') {
        return { items: [{ name: 'search_characters', description: '搜索项目内角色档案', group: 'retrieval', input_schema: {} }, { name: 'count_words', description: '中英文混合字数统计', group: 'audit', input_schema: {} }] };
      }
      if (path === '/api/v1/skills') {
        return { items: [{ id: 1, name: 'outline-planning', description: '大纲规划方法论', source: 'builtin', agent_ids: [] }, { id: 3, name: 'web-research', description: '网络调研方法论', source: 'user_upload', agent_ids: [] }], total: 2 };
      }
      if (path === '/api/v1/provider-configs') return { items: [], total: 0, offset: 0, limit: 50 };
      return { ok: true };
    });
    await openAgentPanel();
    const list = await screen.findByTestId('agent-list');
    const builtinCard = within(list).getByTestId('agent-card-1');
    expect(within(builtinCard).getByTestId('agent-builtin-badge-1')).toBeInTheDocument();
    expect(within(builtinCard).queryByTestId('agent-edit-1')).not.toBeInTheDocument();
    expect(within(builtinCard).getByTestId('agent-tool-chip-search_characters')).toBeInTheDocument();
    const customCard = within(list).getByTestId('agent-card-2');
    expect(within(customCard).getByTestId('agent-edit-2')).toBeInTheDocument();
    expect(within(customCard).getByTestId('agent-del-2')).toBeInTheDocument();
  });
});

describe('设置页 — 模型/账户分类（占位，spec §7.4）', () => {
  it('模型分类：Provider 摘要 + 占位（#106 前不实现管理）', async () => {
    const user = userEvent.setup();
    renderSettings();
    await user.click(within(screen.getByTestId('settings-nav')).getByRole('button', { name: '模型' }));
    const panel = screen.getByTestId('settings-panel');
    expect(panel).toHaveTextContent('已配置 Provider');
    expect(panel).toHaveTextContent('模型管理将在后续版本提供');
  });

  it('账户分类：数据目录 + 关于', async () => {
    const user = userEvent.setup();
    renderSettings();
    await user.click(within(screen.getByTestId('settings-nav')).getByRole('button', { name: '账户' }));
    const panel = screen.getByTestId('settings-panel');
    expect(panel).toHaveTextContent('数据目录');
    expect(panel).toHaveTextContent('关于');
  });
});

/**
 * #107 模板分类转正（2026-08-06）：占位 → 真实面板契约（spec §9.2.5 / §9.5 / M4）。
 * RED 预期：GREEN 前 TemplatesPanel 仍为占位 → 本 describe 全部 element-missing
 * （template-list / template-add-btn 等 testid 不存在）；既有用例（其他分类）保持绿。
 * 数据流：面板挂载 → loadTemplates()（GET /api/v1/agent-templates mock）→ 测试内假 store。
 */
