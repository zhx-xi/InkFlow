/**
 * 设置页 F31/F32/#199/#266/#276 持久化 测试（拆分自 settings.test.tsx，#281 测试文件规模治理）。
 *
 * 共享 mock/beforeEach 定义见各拆分文件自含副本。
 */


import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { SettingsPage } from './settings';
import { apiFetch } from '../api/client';
import { useAgentStore } from '../stores/agent';
import { useProjectStore } from '../stores/project';
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
    // #399：visualTouched 守卫重置（模块单例跨用例污染防护；GREEN 后真实字段）
    visualTouched: false,
  } as unknown as Partial<ThemeStoreF32>);
  useProjectStore.setState({
    projects: [{ id: 'p1', name: '青云志', genre: '玄幻', language: 'zh-CN', target_words: 800000, config: {}, created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z' }],
    currentProjectId: 'p1', loading: false, error: null,
  });
  useAgentStore.setState({ config: {}, apiKeyDraft: '', testStatus: 'idle', testMessage: null });
  useToastStore.setState({ toasts: [] });
  // F42 #268：默认 mock 按 URL 分发——AgentChainCard 挂载会 loadProviders()
  // （GET /api/v1/provider-configs，spec §5.2 数据源）；其余请求保持 {ok:true}
  // F41 #260：AgentList 挂载会 loadAgents/loadToolCatalog/loadSkills（3 GET）——同样分发空列表
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/provider-configs') {
      return { items: [], total: 0, offset: 0, limit: 50 };
    }
    if (path === '/api/v1/agents') return { items: [], total: 0 };
    if (path === '/api/v1/agents/tools') return { items: [] };
    if (path === '/api/v1/skills') return { items: [], total: 0 };
    return { ok: true };
  });
});

describe('设置页 — 关闭窗口时设置（#167 F31 RED 契约）', () => {
  /** window.INKFLOW_API.settings mock（spec §2.3：getCloseBehavior / setCloseBehavior / dismissTrayHint 三通道） */
  function createSettingsApiMock() {
    return {
      getCloseBehavior: vi.fn().mockResolvedValue('tray'),
      setCloseBehavior: vi.fn().mockResolvedValue(undefined),
      dismissTrayHint: vi.fn().mockResolvedValue(undefined),
    };
  }

  /**
   * 注入 mock（settings 命名空间尚不在 ApiConfig 类型内 → unknown 透传 +
   * Object.defineProperty，#106 WindowControls.test.tsx setInjected 先例；GREEN 扩展类型后此写法仍成立）
   */
  function setInjected(api: unknown): void {
    Object.defineProperty(window, 'INKFLOW_API', {
      configurable: true,
      value: api,
    });
  }

  let settingsApi: ReturnType<typeof createSettingsApiMock>;

  beforeEach(() => {
    settingsApi = createSettingsApiMock();
    setInjected({ settings: settingsApi });
  });

  afterEach(() => {
    setInjected(undefined);
  });

  it('渲染「关闭窗口时」标签 + Select（combobox aria-label），默认值「最小化到系统托盘」（set.closeBehavior.tray）', async () => {
    renderSettings();
    const panel = screen.getByTestId('settings-panel');
    // GREEN 前设置项不存在 → getByText/getByRole 抛 = RED（element-missing）
    expect(within(panel).getByText('关闭窗口时')).toBeInTheDocument();
    const select = within(panel).getByRole('combobox', { name: '关闭窗口时' });
    // 初值 'tray' 经异步 getCloseBehavior 落地 → waitFor
    await waitFor(() => {
      expect(select).toHaveTextContent('最小化到系统托盘');
    });
  });

  it('挂载时调用 getCloseBehavior() 取初值（mock 返回 tray → Select 显示「最小化到系统托盘」）', async () => {
    renderSettings();
    // GREEN 前设置项未实现、零 IPC 调用 → toHaveBeenCalledTimes(1) FAIL = RED
    expect(settingsApi.getCloseBehavior).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: '关闭窗口时' })).toHaveTextContent('最小化到系统托盘');
    });
  });

  it('切换 Select 到「直接退出」→ settings.setCloseBehavior(quit) 被调用（选择即生效）', async () => {
    const user = userEvent.setup();
    renderSettings();
    const select = screen.getByRole('combobox', { name: '关闭窗口时' });
    await user.click(select);
    await user.click(await screen.findByRole('option', { name: '直接退出' }));
    // GREEN 前无设置项 → 上方 getByRole 已抛 = RED；GREEN 后断言 IPC 调用 + UI 回显
    // F32 契约升级（2026-08-08 父侧裁定）：closeBehavior 走 store 链路——PATCH 成功后
    // 才异步 IPC 推送（spec §5.3），故断言须 waitFor 等待 async 链完成
    await waitFor(() => {
      expect(settingsApi.setCloseBehavior).toHaveBeenCalledWith('quit');
    });
    expect(select).toHaveTextContent('直接退出');
  });

  it('无 window.INKFLOW_API（浏览器 dev）→ 渲染不崩，Select 仍显示默认值「最小化到系统托盘」', async () => {
    setInjected(undefined);
    renderSettings();
    // GREEN 前设置项不存在 → getByRole 抛 = RED；GREEN 后可选链吞掉调用、默认 tray 显示
    const select = screen.getByRole('combobox', { name: '关闭窗口时' });
    await waitFor(() => {
      expect(select).toHaveTextContent('最小化到系统托盘');
    });
  });
});

const themeStateF32 = () => useThemeStore.getState() as ThemeStoreF32;

/**
 * F32 设置持久化（#152，spec §6.2/§6.3 对照表）：font / closeBehavior 从 theme store 读取。
 * RED 预期：现状为组件本地 state（font 写死 'sans'、closeBehavior 本地 'tray'）→
 * 断言 FAIL（font：期望「衬线」实得「无衬线」；closeBehavior：期望「直接退出」实得
 * 「最小化到系统托盘」）。
 */
describe('设置页 — F32 font / closeBehavior 读 store（spec §6.2）', () => {
  it('编辑器字体 Select 渲染初值 = store.font（非本地 state 写死）', () => {
    useThemeStore.setState({ font: 'serif' } as unknown as Partial<ThemeStoreF32>);
    renderSettings();
    // ⚠️ 锚定正则（2026-08-08 实测）：'无衬线' 含子串 '衬线' → toHaveTextContent('衬线')
    // 在 RED 阶段误 PASS；/^衬线$/ 钉死精确文本。GREEN 前本地 state 恒 'sans'（无衬线）→ FAIL = RED
    expect(screen.getByRole('combobox', { name: '编辑器字体' })).toHaveTextContent(/^衬线$/);
  });

  it('关闭窗口时 Select 渲染初值 = store.closeBehavior（非本地 state）', () => {
    // 不注入 INKFLOW_API：挂载 IPC 读被可选链吞掉，展示值应完全来自 store
    useThemeStore.setState({ closeBehavior: 'quit' } as unknown as Partial<ThemeStoreF32>);
    renderSettings();
    // GREEN 前本地 state 恒 'tray' → 期望「直接退出」FAIL = RED
    expect(screen.getByRole('combobox', { name: '关闭窗口时' })).toHaveTextContent('直接退出');
  });
});

/**
 * F32 设置持久化（#152，spec §6.2 + §5.3 开关链路）：首次托盘提示开关。
 * 开关 data-testid 自定：settings-tray-hint-switch（本文件 docstring 注明，GREEN 必须匹配）；
 * i18n set.trayHint 由 GREEN 补 zh.ts/en.ts。语义：checked = 提示开（!trayHintDismissed，
 * 默认开）；切换 → store.setTrayHintDismissed(v)（PATCH + IPC dismiss 链路由
 * stores/theme.test.ts 契约覆盖，本用例只钉 action 调用）。
 * RED 预期：开关不存在 → getByTestId 抛（element-missing）。
 */
describe('设置页 — 首次托盘提示开关（F32 §6.2 RED 契约）', () => {
  it('开关渲染（默认开=提示）+ 切换 → store.setTrayHintDismissed 调用断言', async () => {
    const original = themeStateF32().setTrayHintDismissed;
    // 2026-08-08 父侧裁定（测试自身缺陷）：spy 必须同步更新 store 状态——
    // 受控 Switch 的 checked={!trayHintDismissed} 依赖状态驱动，纯 vi.fn 不更新
    // 状态会让第二次点击语义错位（checked 恒 true → 两次都触发 onCheckedChange(false)）
    const setTrayHintMock = vi.fn(async (v: boolean) => {
      useThemeStore.setState({ trayHintDismissed: v } as unknown as Partial<ThemeStoreF32>);
    });
    // 渲染前替换 store action（组件经 selector 读 state 对象 → 必须渲染前替换才生效）
    useThemeStore.setState({ setTrayHintDismissed: setTrayHintMock } as unknown as Partial<ThemeStoreF32>);
    try {
      const user = userEvent.setup();
      renderSettings();
      const sw = screen.getByTestId('settings-tray-hint-switch');
      expect(sw).toBeChecked(); // 默认开（提示）
      await user.click(sw); // 关闭 → 不再提示
      expect(setTrayHintMock).toHaveBeenCalledWith(true);
      await user.click(sw); // 再切回 → 恢复提示
      expect(setTrayHintMock).toHaveBeenCalledWith(false);
    } finally {
      useThemeStore.setState({ setTrayHintDismissed: original } as unknown as Partial<ThemeStoreF32>);
    }
  });
});

/**
 * #199（2026-08-09，rc4 复验缺陷）：设置保存反馈统一化——设置页所有即改即存设置
 * （首次托盘提示开关 / 关闭窗口时 Select / 编辑器字体 Select）保存成功后统一显示
 * 顶部「已保存」（settings-save-indicator，与 default_words #189 同一指示器）；
 * 失败 → err toast（store 内既有）+ 指示器回到隐藏。GREEN 契约：
 * - GeneralPanel 三个控件调用处包「saving → await setter（Promise<boolean>）→ saved(2s)/idle」
 * - store setter 返回 Promise<boolean>（成功 true / 失败 false，见 stores/theme.test.ts #199 组）
 * RED 预期：现状切换无顶部提示（指示器恒空/隐藏）→ textContent 断言 FAIL = RED。
 */
describe('设置页 — #199 保存反馈统一化（顶部「已保存」）', () => {
  it('编辑器字体 Select 切换「等宽」→ 顶部「已保存」（font 即改即存反馈）', async () => {
    const user = userEvent.setup();
    renderSettings();
    await user.click(screen.getByRole('combobox', { name: '编辑器字体' }));
    await user.click(await screen.findByRole('option', { name: '等宽' }));
    // GREEN 前 font 切换零顶部提示 → 恒空 → FAIL = RED
    await waitFor(() => {
      expect(screen.getByTestId('settings-save-indicator').textContent).toBe('已保存');
    });
    // store 已持久化（wire 佐证）
    expect(useThemeStore.getState().font).toBe('mono');
  });

  it('关闭窗口时 Select 切换「直接退出」→ 顶部「已保存」（closeBehavior 即改即存反馈）', async () => {
    const user = userEvent.setup();
    renderSettings();
    await user.click(screen.getByRole('combobox', { name: '关闭窗口时' }));
    await user.click(await screen.findByRole('option', { name: '直接退出' }));
    await waitFor(() => {
      expect(screen.getByTestId('settings-save-indicator').textContent).toBe('已保存');
    });
    expect(useThemeStore.getState().closeBehavior).toBe('quit');
  });

  it('首次托盘提示开关切换 → 顶部「已保存」（trayHint 即改即存反馈）', async () => {
    const user = userEvent.setup();
    renderSettings();
    const sw = screen.getByTestId('settings-tray-hint-switch');
    await user.click(sw); // 关闭提示 → setTrayHintDismissed(true)
    await waitFor(() => {
      expect(screen.getByTestId('settings-save-indicator').textContent).toBe('已保存');
    });
    expect(useThemeStore.getState().trayHintDismissed).toBe(true);
  });

  it('font 切换 PATCH 失败 → err toast + 顶部指示器不显示「已保存」（失败回隐藏，提示走 err toast）', async () => {
    patchSettingsMock.mockRejectedValue(new Error('network down'));
    const user = userEvent.setup();
    renderSettings();
    await user.click(screen.getByRole('combobox', { name: '编辑器字体' }));
    await user.click(await screen.findByRole('option', { name: '等宽' }));
    // err toast 出现（store 内 pushSaveFailed 既有行为）
    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts.some((t) => t.type === 'err')).toBe(true);
    });
    // 指示器不得显示「已保存」（失败信号 = false → idle）
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(screen.getByTestId('settings-save-indicator').textContent).not.toBe('已保存');
  });
});

/**
 * F32 设置持久化（#152，spec §5.4，Q3=C）：default_words 卸载 flush + dirty 跟踪。
 * GREEN 契约（settings.tsx GeneralPanel）：
 * - onChange → 本地 state + dirty 标记（ref 镜像 valueRef/dirtyRef，评审 🟡-7）
 * - 卸载（切分类/跳页）cleanup → dirty 时 flushDefaultWords()（fire-and-forget）
 * - flush 经 useProjectStore.updateConfig（PATCH /api/v1/projects/{id} body {config}，
 *   单请求 + 双 store 同步闭环，评审 🔴-2）；成功 → agent setConfig + 清 dirty + ok toast；
 *   失败 → err toast + agent store 不被污染（缺陷 #4）+ dirty 保持
 * - currentProjectId 变化 → 重读新项目 config.default_words + 清 dirty（缺陷 #2）
 * - 无当前项目 → 不保存（评审 🟢）
 * RED 预期：GREEN 前无卸载 flush / 无 project store 同步 / 失败路径先 setConfig 污染 →
 * waitFor 超时 + 断言 FAIL。
 */
describe('设置页 — default_words 卸载 flush（F32 §5.4 RED 契约）', () => {
  /** 切到「模型」分类（静态占位面板，无额外 apiFetch）→ GeneralPanel 卸载 */
  async function switchToModels(user: ReturnType<typeof userEvent.setup>) {
    await user.click(within(screen.getByTestId('settings-nav')).getByRole('button', { name: '模型' }));
  }

  it('输入 5000 → 切分类（GeneralPanel 卸载）→ PATCH 已发出 + 返回后输入框值保留（issue 验收 1 跳页不丢）', async () => {
    const user = userEvent.setup();
    renderSettings();
    const input = screen.getByLabelText('新章节默认字数');
    await user.clear(input);
    await user.type(input, '5000');
    await switchToModels(user);
    // RED：blur 路径的 PATCH 由现状实现发出（可过），但 project store 不合并 →
    // 下方两个断言 FAIL = RED 证据
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/projects/p1',
        expect.objectContaining({
          method: 'PATCH',
          body: expect.objectContaining({ config: expect.objectContaining({ default_words: 5000 }) }),
        }),
      );
    });
    // flush 成功 → project store 本地合并（remount 懒初始化读新值前提，评审 🔴-2）
    await waitFor(() => {
      expect(useProjectStore.getState().projects[0].config.default_words).toBe(5000);
    });
    // 返回常规 → 输入框值保留（懒初始化读 project store）
    await user.click(within(screen.getByTestId('settings-nav')).getByRole('button', { name: '常规' }));
    expect(screen.getByLabelText('新章节默认字数')).toHaveValue(5000);
  });

  it('输入 5000 → 再改 6000 → 立即卸载 → flush PATCH 携带 6000（ref 镜像契约，评审 🟡-7）', async () => {
    const user = userEvent.setup();
    const { unmount } = renderSettings();
    const input = screen.getByLabelText('新章节默认字数');
    await user.clear(input);
    await user.type(input, '5000');
    await user.clear(input);
    await user.type(input, '6000');
    // ⚠️ 与任务书「切分类」表述的偏差：切分类会先触发 blur（既存 onBlur 保存路径同样携带
    // 最新 state 6000）→ 该用例在 RED 阶段可能即绿（确认型），钉不住「卸载路径」。
    // 改用 unmount()（React 卸载不派发 blur/focusout → 卸载 cleanup 是唯一 PATCH 来源）：
    // cleanup 闭包若捕获陈旧 state（5000）→ 末次 PATCH 为 5000 → FAIL（ref 镜像契约精确命中）。
    unmount();
    await waitFor(() => {
      const patchCalls = apiFetchMock.mock.calls.filter((c) => c[1]?.method === 'PATCH');
      expect(patchCalls.length).toBeGreaterThanOrEqual(1);
      const lastBody = patchCalls[patchCalls.length - 1][1]?.body as { config: { default_words?: number } };
      expect(lastBody.config.default_words).toBe(6000);
    });
  });

  it('flush PATCH 成功 → project store 本地 config.default_words 已更新（评审 🔴-2：remount 懒初始化读新值前提）', async () => {
    const user = userEvent.setup();
    renderSettings();
    const input = screen.getByLabelText('新章节默认字数');
    await user.clear(input);
    await user.type(input, '7000');
    await switchToModels(user);
    // GREEN 前 updateConfig 无 flush 调用方 → project store 恒不合并 → waitFor 超时 = RED
    await waitFor(() => {
      expect(useProjectStore.getState().projects[0].config.default_words).toBe(7000);
    });
  });

  it('卸载 flush PATCH reject → err toast + agent store.config.default_words 未被污染（缺陷 #4 修复）', async () => {
    apiFetchMock.mockRejectedValue(new Error('network down'));
    const user = userEvent.setup();
    renderSettings();
    const input = screen.getByLabelText('新章节默认字数');
    await user.clear(input);
    await user.type(input, '5000');
    await switchToModels(user);
    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts.some((t) => t.type === 'err')).toBe(true);
    });
    // 现状 blur 路径 PATCH 前先 setConfig → 污染（default_words=5000）→ toBeUndefined FAIL = RED
    expect(useAgentStore.getState().config.default_words).toBeUndefined();
  });

  it('currentProjectId 变化 → 输入框重读新项目 config.default_words + 清 dirty（缺陷 #2 修复）', async () => {
    useProjectStore.setState({
      projects: [
        { id: 'p1', name: '青云志', genre: '玄幻', language: 'zh-CN', target_words: 800000, config: { default_words: 30000 }, created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z' },
        { id: 'p2', name: '归墟记', genre: '仙侠', language: 'zh-CN', target_words: 600000, config: { default_words: 60000 }, created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z' },
      ],
      currentProjectId: 'p1',
    });
    renderSettings();
    const input = screen.getByLabelText('新章节默认字数');
    expect(input).toHaveValue(30000);
    act(() => {
      useProjectStore.getState().selectProject('p2');
    });
    // GREEN 前 useState 惰性初始化只跑一次 → 输入框仍 30000 → waitFor 超时 = RED
    await waitFor(() => expect(input).toHaveValue(60000));
  });

  it('无当前项目：输入 → 卸载 → PATCH 未发出（评审 🟢；确认型——现状 blur 路径已有无项目守卫，预期 RED 阶段即绿）', async () => {
    useProjectStore.setState({ projects: [], currentProjectId: null });
    const user = userEvent.setup();
    renderSettings();
    const input = screen.getByLabelText('新章节默认字数');
    await user.clear(input);
    await user.type(input, '5000');
    await switchToModels(user);
    const patchCalls = apiFetchMock.mock.calls.filter(
      (c) => c[0] === '/api/v1/projects/p1' && c[1]?.method === 'PATCH',
    );
    expect(patchCalls).toHaveLength(0);
  });

  it('#399：PATCH 异步在途 → 切回常规 remount → store 合并后输入框自动同步 5000（订阅式重读）', async () => {
    // 模拟 E2E F32 M1（e2e-settings.spec.ts:227）真实时序：输入 5000 → 切分类（blur flush PATCH
    // 发出，异步在途）→ 立即切回常规 → remount 懒初始化读 store 旧值 800000 → PATCH 完成后
    // updateConfig 合并 store config.default_words=5000 → 输入框必须自动刷新。
    // GREEN 前 GeneralPanel 只一次性初始化 + useEffect[currentProjectId]（未变不触发）
    // → 恒 800000 → waitFor toHaveValue(5000) 超时 = RED。
    const patchResolvers: Array<(v: unknown) => void> = [];
    apiFetchMock.mockImplementation((path, init) => {
      if (path === '/api/v1/projects/p1' && init?.method === 'PATCH') {
        return new Promise((res) => {
          patchResolvers.push(res);
        });
      }
      if (path === '/api/v1/provider-configs') {
        return Promise.resolve({ items: [], total: 0, offset: 0, limit: 50 });
      }
      return Promise.resolve({ ok: true });
    });
    const user = userEvent.setup();
    renderSettings();
    const input = screen.getByLabelText('新章节默认字数');
    await user.clear(input);
    await user.type(input, '5000');
    await switchToModels(user); // blur → flush PATCH（挂起）；卸载 cleanup 二次 flush（同挂起）
    // 立即切回常规 → remount 懒初始化读 store（PATCH 未完成 → 800000）
    await user.click(within(screen.getByTestId('settings-nav')).getByRole('button', { name: '常规' }));
    // PATCH 完成 → updateConfig 合并 store config.default_words=5000
    await act(async () => {
      patchResolvers.forEach((r) => r({ ok: true }));
    });
    await waitFor(() => expect(screen.getByLabelText('新章节默认字数')).toHaveValue(5000));
  });
});

/**
 * #266 数据目录持久化 RED 契约（2026-08-12，instance.env 持久化；GREEN 义务见文件头 docstring）：
 * AccountPanel「数据目录」区——挂载 fetchDataDir() 回显 → 修改 + 保存 → updateDataDir PUT
 * → 成功提示「重启后生效」+ ok toast；失败 → err toast 且提示行不显示；input aria-label =
 * t('set.account.dataDir')（'数据目录'，i18n 默认 zh）。
 * RED 预期：GREEN 前硬编码占位 ~/.inkflow/data、无输入框/保存按钮 → 新用例全部
 * element-missing FAIL（findByTestId 超时 / getByTestId 抛 TestingLibraryElementError），
 * 既有用例保持绿。
 */
describe('设置页 — 数据目录持久化（#266 RED 契约）', () => {
  /** 切到「账户」分类（fireEvent 同步派发，契约 testid = settings-cat-account） */
  function switchToAccount() {
    fireEvent.click(screen.getByTestId('settings-cat-account'));
  }

  beforeEach(() => {
    // ⚠️ mockReset 后必须 mockResolvedValue 默认——挂载异步 fetch 是 fire-and-forget，
    // 缺默认会 TypeError 未处理 rejection
    fetchDataDirMock.mockReset();
    fetchDataDirMock.mockResolvedValue({
      data_dir: 'C:/Users/test/InkFlow',
      instance_env_path: 'C:/Users/test/InkFlow/instance.env',
    });
    updateDataDirMock.mockReset();
    updateDataDirMock.mockResolvedValue({
      data_dir: 'C:/Users/test/InkFlow',
      instance_env_path: 'C:/Users/test/InkFlow/instance.env',
      restart_required: true,
    });
  });

  it('test_account_data_dir_input_shows_api_value：挂载账户面板 → fetchDataDir 回显 data_dir', async () => {
    renderSettings();
    switchToAccount();
    // RED：GREEN 前输入框不存在 → findByTestId 超时（TestingLibraryElementError）
    const input = await screen.findByTestId('settings-data-dir-input');
    await waitFor(() => {
      expect(input).toHaveValue('C:/Users/test/InkFlow');
    });
    expect(fetchDataDirMock).toHaveBeenCalled();
  });

  it('test_account_data_dir_save_calls_put_and_shows_hint：修改 + 保存 → PUT body 精确 + 重启提示 + ok toast', async () => {
    renderSettings();
    switchToAccount();
    const input = await screen.findByTestId('settings-data-dir-input');
    fireEvent.change(input, { target: { value: 'D:/novels/ink' } });
    fireEvent.click(screen.getByTestId('settings-data-dir-save'));
    // 契约：updateDataDir body 精确 = { data_dir: 'D:/novels/ink' }
    await waitFor(() => {
      expect(updateDataDirMock).toHaveBeenCalledWith({ data_dir: 'D:/novels/ink' });
    });
    // 成功 → 提示行「重启后生效」（t('set.account.dataDirRestart')，i18n 默认 zh）
    await waitFor(() => {
      expect(screen.getByTestId('settings-data-dir-hint').textContent).toContain('重启后生效');
    });
    // toast store 收到 ok（pushToast('ok', t('toast.saved'))）
    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts.some((t) => t.type === 'ok')).toBe(true);
    });
  });

  it('test_account_data_dir_save_failure_shows_err_toast：保存失败 → err toast + 提示行不显示', async () => {
    updateDataDirMock.mockRejectedValueOnce(new Error('boom'));
    renderSettings();
    switchToAccount();
    const input = await screen.findByTestId('settings-data-dir-input');
    fireEvent.change(input, { target: { value: 'D:/novels/ink' } });
    fireEvent.click(screen.getByTestId('settings-data-dir-save'));
    // 失败 → pushToast('err', t('toast.saveFailed'))
    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts.some((t) => t.type === 'err')).toBe(true);
    });
    // 提示行不显示
    expect(screen.queryByTestId('settings-data-dir-hint')).not.toBeInTheDocument();
  });

  it('test_account_data_dir_input_has_aria_label：input aria-label = 数据目录（set.account.dataDir）', async () => {
    renderSettings();
    switchToAccount();
    const input = await screen.findByTestId('settings-data-dir-input');
    expect(input).toHaveAttribute('aria-label', '数据目录');
  });
});

// ══════════════════════════════════════════════════════════════════
// #276 S2c RAG 向量检索区块契约（2026-08-12，Issue #276 范围 5）
// ══════════════════════════════════════════════════════════════════
// ModelsPanel（模型分类）落地 RAG 区块。data-testid 即契约：
// - rag-status-card：状态卡片（常驻展示当前 embedding 模型 + 匹配状态）
// - rag-model-name：当前生效 embedding 模型 id（API provider/model 或本地 BGE）
// - rag-stale-banner：stale 警告横幅（含 reason 文案；fresh/未配置不渲染）
// - rag-reindex-btn：重新向量化按钮（仅 stale/unknown 时出现）
// - rag-confirm-dialog + rag-confirm-ok：确认对话框（维度不匹配 → 破坏性二次确认）
// - rag-no-embedding：未配置 embedding 提示态
// 行为：
// - 挂载 ModelsPanel → fetchVectorStatus(当前项目 id) → 展示模型名 + 状态行；
//   fresh → 绿色「索引与模型匹配」；stale → 横幅（reason 文案）+ 按钮
// - 点击按钮 → 确认对话框（文案说明将用当前模型重建）→ 确认 →
//   postVectorReindex(projectId) → 完成 → 重新 fetchVectorStatus → fresh → 横幅消失
// - dimension_mismatch=true → 二次确认文案（「清空当前向量库并重建」，破坏性）
// - reason 文案映射：unknown「无索引指纹」/ model_changed「模型已变更」/
//   chunking_changed「切片参数已变更」/ schema_old「数据版本过旧」/ no_embedding「未配置」
// 新增 i18n key（GREEN 补 zh.ts / en.ts）：
// set.rag.title='向量检索（RAG）' set.rag.model='当前模型' set.rag.fresh='索引与模型匹配'
// set.rag.stale='向量库与当前配置不一致，检索结果可能异常'
// set.rag.reindex='重新向量化' set.rag.confirm='将用当前模型全量重建向量索引'
// set.rag.confirmDestructive='此操作将清空当前向量库并重建（维度不兼容）'
// set.rag.noEmbedding='未配置 embedding 模型' set.rag.reason.unknown='无索引指纹'
// set.rag.reason.modelChanged='模型已变更' set.rag.reason.chunkingChanged='切片参数已变更'
// set.rag.reason.schemaOld='数据版本过旧'
// RED 预期：GREEN 前 ModelsPanel 为占位 → 新用例全部 element-missing FAIL，
// 既有用例保持绿。

const ragFingerprint = {
  schema_version: 1,
  embedding: {
    provider: 'openai',
    model_id: 'text-embedding-3-small',
    base_url: 'http://api.test/v1',
    dimension: 384,
  },
  chunking: { mode: 'fixed', chunk_size: 500, overlap_ratio: 0, chunker_version: 1 },
  indexed_at: '2026-08-12T08:00:00Z',
  status: 'fresh',
};

const ragStatusFresh = {
  configured_fp: ragFingerprint,
  indexed_fp: ragFingerprint,
  stale: false,
  reason: null,
  dimension_mismatch: false,
};

const ragStatusStaleModelChanged = {
  ...ragStatusFresh,
  configured_fp: { ...ragFingerprint, embedding: { ...ragFingerprint.embedding, model_id: 'text-embedding-3-large' } },
  stale: true,
  reason: 'model_changed',
};

const ragStatusUnknown = {
  ...ragStatusFresh,
  indexed_fp: null,
  stale: true,
  reason: 'unknown',
};

const ragStatusNoEmbedding = {
  configured_fp: null,
  indexed_fp: null,
  stale: false,
  reason: 'no_embedding',
  dimension_mismatch: false,
};

const ragReindexResult = {
  project_id: '1',
  entity_types: ['character', 'setting', 'foreshadowing', 'timeline_event', 'chapter_chunk'],
  indexed: 87,
  warnings: [],
  collections_recreated: false,
};

function renderModelsPanel(): void {
  useProjectStore.setState({ currentProjectId: '1' });
  render(
    <MemoryRouter>
      <SettingsPage />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByTestId('settings-cat-models'));
}

describe('RAG 向量检索区块（#276）', () => {
  beforeEach(() => {
    vectorStatusMock.mockReset();
    vectorReindexMock.mockReset();
    vectorStatusMock.mockResolvedValue(ragStatusFresh);
    vectorReindexMock.mockResolvedValue(ragReindexResult);
  });

  it('test_rag_fresh_shows_model_name_and_no_banner：fresh → 模型名 + 匹配态，无横幅', async () => {
    renderModelsPanel();
    expect(await screen.findByTestId('rag-model-name')).toHaveTextContent(
      'text-embedding-3-small',
    );
    expect(screen.getByTestId('rag-status-card')).toBeInTheDocument();
    expect(screen.queryByTestId('rag-stale-banner')).not.toBeInTheDocument();
    expect(screen.queryByTestId('rag-reindex-btn')).not.toBeInTheDocument();
  });

  it('test_rag_stale_shows_banner_and_reindex_button：stale → 横幅（reason 文案）+ 按钮', async () => {
    vectorStatusMock.mockResolvedValue(ragStatusStaleModelChanged);
    renderModelsPanel();
    const banner = await screen.findByTestId('rag-stale-banner');
    expect(banner.textContent).toContain('模型已变更');
    expect(screen.getByTestId('rag-reindex-btn')).toBeInTheDocument();
  });

  it('test_rag_unknown_shows_banner：unknown（存量升级）视同 stale → 横幅 + 按钮', async () => {
    vectorStatusMock.mockResolvedValue(ragStatusUnknown);
    renderModelsPanel();
    expect(await screen.findByTestId('rag-stale-banner')).toBeInTheDocument();
    expect(screen.getByTestId('rag-reindex-btn')).toBeInTheDocument();
  });

  it('test_rag_no_embedding_shows_hint：未配置 embedding → 提示态，无横幅无按钮', async () => {
    vectorStatusMock.mockResolvedValue(ragStatusNoEmbedding);
    renderModelsPanel();
    expect(await screen.findByTestId('rag-no-embedding')).toBeInTheDocument();
    expect(screen.queryByTestId('rag-stale-banner')).not.toBeInTheDocument();
    expect(screen.queryByTestId('rag-reindex-btn')).not.toBeInTheDocument();
  });

  it('test_rag_reindex_flow_confirm_then_fresh：点击按钮 → 确认 → reindex → 刷新 fresh 横幅消失', async () => {
    vectorStatusMock.mockResolvedValueOnce(ragStatusStaleModelChanged).mockResolvedValue(ragStatusFresh);
    renderModelsPanel();
    fireEvent.click(await screen.findByTestId('rag-reindex-btn'));
    // 确认对话框出现 → 确认
    expect(await screen.findByTestId('rag-confirm-dialog')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('rag-confirm-ok'));
    // reindex 调用 + 状态刷新（fresh → 横幅消失）
    await waitFor(() => {
      expect(vectorReindexMock).toHaveBeenCalledWith('1');
    });
    await waitFor(() => {
      expect(screen.queryByTestId('rag-stale-banner')).not.toBeInTheDocument();
    });
    expect(vectorStatusMock).toHaveBeenCalledTimes(2);
  });

  it('test_rag_dimension_mismatch_shows_destructive_confirm：维度不匹配 → 破坏性二次确认文案', async () => {
    vectorStatusMock.mockResolvedValue({ ...ragStatusStaleModelChanged, dimension_mismatch: true });
    renderModelsPanel();
    fireEvent.click(await screen.findByTestId('rag-reindex-btn'));
    const dialog = await screen.findByTestId('rag-confirm-dialog');
    expect(dialog.textContent).toContain('清空当前向量库并重建');
  });
});
