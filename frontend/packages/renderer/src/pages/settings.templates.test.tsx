/**
 * 设置页 模板分类（#107 契约） 测试（拆分自 settings.test.tsx，#281 测试文件规模治理）。
 *
 * 共享 mock/beforeEach 定义见各拆分文件自含副本。
 */


import { describe, it, expect, beforeEach, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { SettingsPage } from './settings';
import { apiFetch } from '../api/client';
import { useAgentStore } from '../stores/agent';
import { useProjectStore } from '../stores/project';
import { useTemplatesStore } from '../stores/templates';
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

describe('设置页 — 模板分类（#107 RED 契约）', () => {
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
  const ROLE = (model: string | null, temperature: number | null, enabled: boolean): FakeRole => ({
    model,
    temperature,
    enabled,
  });
  /** 列表 fixture：t1 被 2 个项目引用 + 默认；t2 无引用 + 非默认 */
  const TEMPLATES: FakeTemplate[] = [
    {
      id: 1,
      name: '经典玄幻',
      description: '标准玄幻创作模板',
      main_model: 'gpt-4o',
      default_temperature: 0.7,
      roles: {
        architect: ROLE('deepseek-chat', 0.4, true),
        writer: ROLE('gpt-4o', 0.8, true),
        auditor: ROLE('gpt-4o', 0.5, true),
        reviser: ROLE('deepseek-chat', 0.6, true),
      },
      default_words: 800000,
      is_default: true,
      used_by: [
        { id: 'p1', name: '青云志' },
        { id: 'p2', name: '归墟记' },
      ],
      created_at: '2026-08-01T10:00:00Z',
      updated_at: '2026-08-05T10:00:00Z',
    },
    {
      id: 2,
      name: '悬疑推理',
      description: '悬疑推理创作模板',
      main_model: 'deepseek-chat',
      default_temperature: 0.6,
      roles: {
        architect: ROLE(null, null, true),
        writer: ROLE('deepseek-chat', 0.9, true),
        auditor: ROLE(null, null, true),
        reviser: ROLE(null, null, true),
      },
      default_words: 600000,
      is_default: false,
      used_by: [],
      created_at: '2026-08-01T10:00:00Z',
      updated_at: '2026-08-05T10:00:00Z',
    },
  ];

  /** 面板挂载 → loadTemplates（GET /api/v1/agent-templates）的数据源 mock；PATCH 回显供保存流程 */
  function mockTemplateList() {
    apiFetchMock.mockImplementation(
      async (path: string, init?: { method?: string; body?: unknown }) => {
        void init?.body;
        if (path === '/api/v1/agent-templates' && !init?.method) {
          return { items: TEMPLATES, total: 2, offset: 0, limit: 50 };
        }
        if (path === '/api/v1/agent-templates/1' && init?.method === 'PATCH') {
          return { ...TEMPLATES[0], name: '经典玄幻改' };
        }
        return { ok: true };
      },
    );
  }

  beforeEach(() => {
    mockTemplateList();
  });

  async function openTemplatesPanel() {
    const user = userEvent.setup();
    renderSettings();
    await user.click(within(screen.getByTestId('settings-nav')).getByRole('button', { name: '模板' }));
    return user;
  }

  it('点击「模板」分类 → 模板列表：名称/描述/应用项目数徽标/设为默认标记', async () => {
    await openTemplatesPanel();
    const list = await screen.findByTestId('template-list');
    const card1 = within(list).getByTestId('template-card-1');
    expect(within(card1).getByText('经典玄幻')).toBeInTheDocument();
    expect(within(card1).getByText('标准玄幻创作模板')).toBeInTheDocument();
    expect(within(card1).getByTestId('template-usedby-1')).toHaveTextContent('2 个项目使用');
    expect(within(card1).getByTestId('template-default-badge-1')).toHaveTextContent('默认');
    const card2 = within(list).getByTestId('template-card-2');
    expect(within(card2).getByText('悬疑推理')).toBeInTheDocument();
    expect(within(card2).queryByTestId('template-usedby-2')).not.toBeInTheDocument();
    expect(within(card2).queryByTestId('template-default-badge-2')).not.toBeInTheDocument();
  });

  it('新建按钮 → TemplateDialog 打开（新建模式：名称空）', async () => {
    const user = await openTemplatesPanel();
    await user.click(screen.getByTestId('template-add-btn'));
    const dlg = await screen.findByTestId('template-dialog');
    expect(within(dlg).getByTestId('template-name-input')).toHaveValue('');
  });

  it('编辑按钮 → TemplateDialog 打开且回显模板名称', async () => {
    const user = await openTemplatesPanel();
    await user.click(within(await screen.findByTestId('template-card-1')).getByTestId('template-edit-1'));
    const dlg = await screen.findByTestId('template-dialog');
    expect(within(dlg).getByTestId('template-name-input')).toHaveValue('经典玄幻');
  });

  it('删除被引用模板 → 风险确认框（列出项目名）→ 确认 → DELETE + 列表移除', async () => {
    const user = await openTemplatesPanel();
    await user.click(within(await screen.findByTestId('template-card-1')).getByTestId('template-delete-1'));
    const confirm = screen.getByTestId('template-confirm-dialog');
    expect(confirm).toHaveTextContent('该模板正在被 2 个项目使用（青云志、归墟记）');
    await user.click(within(confirm).getByTestId('template-confirm-ok'));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/agent-templates/1',
        expect.objectContaining({ method: 'DELETE' }),
      );
    });
    await waitFor(() => {
      expect(screen.queryByTestId('template-card-1')).not.toBeInTheDocument();
    });
    expect(screen.getByTestId('template-card-2')).toBeInTheDocument();
  });

  it('删除被引用模板 → 取消 → 不发 DELETE、列表不变', async () => {
    const user = await openTemplatesPanel();
    await user.click(within(await screen.findByTestId('template-card-1')).getByTestId('template-delete-1'));
    const confirm = screen.getByTestId('template-confirm-dialog');
    await user.click(within(confirm).getByTestId('template-confirm-cancel'));
    await waitFor(() => {
      expect(screen.queryByTestId('template-confirm-dialog')).not.toBeInTheDocument();
    });
    expect(
      apiFetchMock.mock.calls.some(
        (c) => c[0] === '/api/v1/agent-templates/1' && c[1]?.method === 'DELETE',
      ),
    ).toBe(false);
    expect(screen.getByTestId('template-card-1')).toBeInTheDocument();
  });

  it('删除无引用模板 → 通用确认文案「确定删除「悬疑推理」？此操作不可撤销」→ 确认 → DELETE', async () => {
    const user = await openTemplatesPanel();
    await user.click(within(await screen.findByTestId('template-card-2')).getByTestId('template-delete-2'));
    const confirm = screen.getByTestId('template-confirm-dialog');
    expect(confirm).toHaveTextContent('确定删除「悬疑推理」？此操作不可撤销');
    await user.click(within(confirm).getByTestId('template-confirm-ok'));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/agent-templates/2',
        expect.objectContaining({ method: 'DELETE' }),
      );
    });
  });

  it('设为默认 → PATCH /api/v1/agent-templates/default body {id} → 默认徽标迁移', async () => {
    const user = await openTemplatesPanel();
    await user.click(within(await screen.findByTestId('template-card-2')).getByTestId('template-set-default-2'));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/agent-templates/default',
        expect.objectContaining({ method: 'PATCH', body: expect.objectContaining({ id: '2' }) }),
      );
    });
    // 徽标迁移：card2 出现「默认」，card1 移除（store is_default 翻转 → 重渲染）
    await waitFor(() => {
      expect(within(screen.getByTestId('template-card-2')).getByTestId('template-default-badge-2')).toBeInTheDocument();
    });
    expect(
      within(screen.getByTestId('template-card-1')).queryByTestId('template-default-badge-1'),
    ).not.toBeInTheDocument();
  });

  it('编辑被引用模板保存 → 风险确认（列出影响项目）→ 确认 → PATCH /api/v1/agent-templates/1（spec §9.5 保存分支）', async () => {
    const user = await openTemplatesPanel();
    await user.click(within(await screen.findByTestId('template-card-1')).getByTestId('template-edit-1'));
    const dlg = await screen.findByTestId('template-dialog');
    await user.clear(within(dlg).getByTestId('template-name-input'));
    await user.type(within(dlg).getByTestId('template-name-input'), '经典玄幻改');
    await user.click(within(dlg).getByTestId('template-save'));
    const confirm = await screen.findByTestId('template-confirm-dialog');
    expect(confirm).toHaveTextContent('保存将同步影响这些项目的 Agent 配置');
    await user.click(within(confirm).getByTestId('template-confirm-ok'));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/agent-templates/1',
        expect.objectContaining({ method: 'PATCH' }),
      );
    });
  });

  it('编辑被引用模板保存 → 取消 → 不发 PATCH', async () => {
    const user = await openTemplatesPanel();
    await user.click(within(await screen.findByTestId('template-card-1')).getByTestId('template-edit-1'));
    const dlg = await screen.findByTestId('template-dialog');
    await user.clear(within(dlg).getByTestId('template-name-input'));
    await user.type(within(dlg).getByTestId('template-name-input'), '经典玄幻改');
    await user.click(within(dlg).getByTestId('template-save'));
    const confirm = await screen.findByTestId('template-confirm-dialog');
    await user.click(within(confirm).getByTestId('template-confirm-cancel'));
    await waitFor(() => {
      expect(screen.queryByTestId('template-confirm-dialog')).not.toBeInTheDocument();
    });
    expect(
      apiFetchMock.mock.calls.some(
        (c) => c[0] === '/api/v1/agent-templates/1' && c[1]?.method === 'PATCH',
      ),
    ).toBe(false);
  });

  /**
   * #107 Coverage-Gap 补测（非 RED，测试预期直接全绿）：模板分类失败路径 + 风险确认背景点击。
   * 覆盖 settings.tsx TemplatesPanel 未覆盖语句（F31 合入前即存在的 #107 分支）：
   * - handleCreate catch（createTemplate reject → err toast；成功 → 对话框关闭）
   * - handleUpdate try/catch（无引用模板 updateTemplate 成功/失败两路径）
   * - confirmSave catch（被引用模板确认保存 updateTemplate reject → err toast）
   * - handleDelete error 分支（deleteTemplate 失败置位 store.error → err toast，不 rethrow）
   * - 风险确认框背景点击（backdrop onClick 清空 pendingDelete/pendingSave）
   */
  describe('模板分类失败路径 + 风险确认背景点击（#107 Coverage-Gap 补测）', () => {
    it('新建保存失败：createTemplate reject → err toast「create failed」+ 对话框不关闭（handleCreate catch）', async () => {
      vi.mocked(useTemplatesStore.getState().createTemplate).mockRejectedValueOnce(
        new Error('create failed'),
      );
      const user = await openTemplatesPanel();
      await user.click(screen.getByTestId('template-add-btn'));
      const dlg = await screen.findByTestId('template-dialog');
      await user.type(within(dlg).getByTestId('template-name-input'), '新模板');
      await user.click(within(dlg).getByTestId('template-save'));

      await waitFor(() => {
        const toasts = useToastStore.getState().toasts;
        expect(toasts).toHaveLength(1);
        expect(toasts[0]).toEqual(
          expect.objectContaining({ type: 'err', message: 'create failed' }),
        );
      });
      // catch 分支不执行 setDialogOpen(false) → 对话框保持打开
      expect(screen.getByTestId('template-dialog')).toBeInTheDocument();
    });

    it('新建保存成功 → 对话框关闭（handleCreate 成功路径 setDialogOpen(false)）', async () => {
      const user = await openTemplatesPanel();
      await user.click(screen.getByTestId('template-add-btn'));
      const dlg = await screen.findByTestId('template-dialog');
      await user.type(within(dlg).getByTestId('template-name-input'), '新模板');
      await user.click(within(dlg).getByTestId('template-save'));

      await waitFor(() => {
        expect(screen.queryByTestId('template-dialog')).not.toBeInTheDocument();
      });
    });

    it('编辑无引用模板保存失败：updateTemplate reject → err toast + 对话框不关闭（handleUpdate catch）', async () => {
      vi.mocked(useTemplatesStore.getState().updateTemplate).mockRejectedValueOnce(
        new Error('update failed'),
      );
      const user = await openTemplatesPanel();
      await user.click(
        within(await screen.findByTestId('template-card-2')).getByTestId('template-edit-2'),
      );
      const dlg = await screen.findByTestId('template-dialog');
      await user.clear(within(dlg).getByTestId('template-name-input'));
      await user.type(within(dlg).getByTestId('template-name-input'), '悬疑推理改');
      await user.click(within(dlg).getByTestId('template-save'));

      await waitFor(() => {
        const toasts = useToastStore.getState().toasts;
        expect(toasts).toHaveLength(1);
        expect(toasts[0]).toEqual(
          expect.objectContaining({ type: 'err', message: 'update failed' }),
        );
      });
      // 无引用 → 不经风险确认；catch 不关对话框
      expect(screen.queryByTestId('template-confirm-dialog')).not.toBeInTheDocument();
      expect(screen.getByTestId('template-dialog')).toBeInTheDocument();
    });

    it('编辑无引用模板保存成功 → 对话框关闭 + 列表名称更新（handleUpdate 成功路径）', async () => {
      const user = await openTemplatesPanel();
      await user.click(
        within(await screen.findByTestId('template-card-2')).getByTestId('template-edit-2'),
      );
      const dlg = await screen.findByTestId('template-dialog');
      await user.clear(within(dlg).getByTestId('template-name-input'));
      await user.type(within(dlg).getByTestId('template-name-input'), '悬疑推理改');
      // PATCH /api/v1/agent-templates/2 返回更新后实体（mockTemplateList 仅处理 /1 的 PATCH）
      apiFetchMock.mockResolvedValueOnce({ ...TEMPLATES[1], name: '悬疑推理改' });
      await user.click(within(dlg).getByTestId('template-save'));

      await waitFor(() => {
        expect(screen.queryByTestId('template-dialog')).not.toBeInTheDocument();
      });
      await waitFor(() => {
        expect(
          within(screen.getByTestId('template-card-2')).getByText('悬疑推理改'),
        ).toBeInTheDocument();
      });
    });

    it('被引用模板确认保存失败：updateTemplate reject → err toast + 确认框关闭 + 编辑对话框仍开（confirmSave catch）', async () => {
      vi.mocked(useTemplatesStore.getState().updateTemplate).mockRejectedValueOnce(
        new Error('update failed'),
      );
      const user = await openTemplatesPanel();
      await user.click(
        within(await screen.findByTestId('template-card-1')).getByTestId('template-edit-1'),
      );
      const dlg = await screen.findByTestId('template-dialog');
      await user.clear(within(dlg).getByTestId('template-name-input'));
      await user.type(within(dlg).getByTestId('template-name-input'), '经典玄幻改');
      await user.click(within(dlg).getByTestId('template-save'));
      const confirm = await screen.findByTestId('template-confirm-dialog');
      await user.click(within(confirm).getByTestId('template-confirm-ok'));

      await waitFor(() => {
        const toasts = useToastStore.getState().toasts;
        expect(toasts).toHaveLength(1);
        expect(toasts[0]).toEqual(
          expect.objectContaining({ type: 'err', message: 'update failed' }),
        );
      });
      // confirmSave 先清 pendingSave（确认框关闭），catch 不执行 setDialogOpen(false) → 编辑框仍开
      expect(screen.queryByTestId('template-confirm-dialog')).not.toBeInTheDocument();
      expect(screen.getByTestId('template-dialog')).toBeInTheDocument();
    });

    it('删除失败（store error 置位，不 rethrow）→ err toast（handleDelete error 分支）', async () => {
      // 镜像真实 store 语义：deleteTemplate 失败 catch 内置位 error，不向上抛
      vi.mocked(useTemplatesStore.getState().deleteTemplate).mockImplementationOnce(async () => {
        useTemplatesStore.setState({ error: 'delete failed' });
      });
      const user = await openTemplatesPanel();
      await user.click(
        within(await screen.findByTestId('template-card-2')).getByTestId('template-delete-2'),
      );
      const confirm = screen.getByTestId('template-confirm-dialog');
      await user.click(within(confirm).getByTestId('template-confirm-ok'));

      await waitFor(() => {
        const toasts = useToastStore.getState().toasts;
        expect(toasts).toHaveLength(1);
        expect(toasts[0]).toEqual(
          expect.objectContaining({ type: 'err', message: 'delete failed' }),
        );
      });
    });

    it('风险确认框背景点击 → 关闭 + 不发 DELETE（backdrop onClick 清空 pendingDelete/pendingSave）', async () => {
      const user = await openTemplatesPanel();
      await user.click(
        within(await screen.findByTestId('template-card-1')).getByTestId('template-delete-1'),
      );
      const confirm = screen.getByTestId('template-confirm-dialog');
      // 背景 = 对话框外层 fixed 遮罩（role=presentation）。fireEvent 直接派发到遮罩元素：
      // userEvent 按元素中心坐标点击会命中内层对话框 → stopPropagation 吞掉 backdrop onClick
      const backdrop = confirm.parentElement as HTMLElement;
      fireEvent.click(backdrop);

      await waitFor(() => {
        expect(screen.queryByTestId('template-confirm-dialog')).not.toBeInTheDocument();
      });
      expect(
        apiFetchMock.mock.calls.some(
          (c) => c[0] === '/api/v1/agent-templates/1' && c[1]?.method === 'DELETE',
        ),
      ).toBe(false);
    });
  });
});

/**
 * #105 Coverage-Gap 补测（非 RED）：常规分类三个下拉 onValueChange 分支
 * （语言 L79 / 背景变体 L111 / 编辑器字体 L127）+ Agent 默认模型下拉
 * 回读 truthy 分支（L193）与 onValueChange 分支（L194）。
 */
