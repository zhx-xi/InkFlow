/**
 * ⚠️ 契约文件（Issue #105 导航重构 RED 阶段 + #105 修复批契约升级，spec §7.4 设置页框架）
 *
 * GREEN 新建 src/pages/settings.tsx（命名导出 SettingsPage），必须匹配：
 *
 * 结构（data-testid 即契约）：
 * - settings-page：页面根容器
 * - settings-nav：左侧五分类导航；settings-cat-<key> 按钮，key ∈ general|models|agent|templates|account
 *   （常规/模型/Agent/模板/账户，spec §7.4 五分类）
 * - settings-panel：右侧当前分类面板——仅激活分类的面板渲染到 DOM（条件渲染，非激活不挂载）
 * - agent-chain-card：Agent 分类内（迁移自 AgentChainCard，testid 保留；行为契约同 agents.test.tsx）
 * - settings-shortcuts：快捷键一览表
 *
 * 分类内容：
 * - 常规：语言（combobox aria-label「语言」ap.lang 已有）· 主题 radio×3（素笺/夜航/墨韵 →
 *   themeStore.theme，theme.* 已有）· 背景变体（combobox「背景」ap.bg 已有）·
 *   编辑器字体（combobox「编辑器字体」）· 新章节默认字数（number input「新章节默认字数」）·
 *   快捷键一览表（含 Ctrl+Z/Ctrl+Y/Ctrl+S/Ctrl+Enter/Ctrl+Shift+Enter 五组，
 *   #105 修复批：生成快捷键 = Ctrl+Shift+Enter，非裸 Shift+Enter）
 * - 模型：Provider 摘要 + 占位（#106 前不实现管理）
 * - Agent：四角色开关（Architect/Writer/Auditor/Reviser，role=switch ↔ config.agent_*：
 *   关闭→undefined 从管线移除 / 重开→null 默认模型）+ 默认模型下拉
 *   （combobox aria-label「默认模型」ag.defaultModel 已有，选项 openai/deepseek/ollama）
 * - 模板：模板列表（名称/描述/应用项目数徽标/设为默认标记）+ 新建/编辑/删除/设为默认
 *   + TemplateDialog（#107 契约，见下方 RED 段）
 * - 账户：数据目录 + 关于（版本/logo）
 *
 * 行为：
 * - 默认激活常规；点击 settings-cat-<key> → 面板切换
 * - 读取 URL cat 查询参数作为初始分类（导航 Agent 快捷入口 /settings?cat=agent 直达）
 * - 即改即存：设置项变更即时生效；数字项（新章节默认字数）失焦 → pushToast('ok', t('toast.saved'))
 *   （toast 视觉挂载由 App 层 ToastHost 承接，本测试断言 useToastStore 状态）
 *
 * ⚠️ #105 修复批契约（2026-08-06，GREEN 前以下断言 FAIL = RED 证据）：
 * - 🔴-2 Agent 分类持久化：AgentPanel 挂载时 loadFromProject(当前项目 config) 初始化——播种项目
 *   config.agent_architect='gpt-4o' 后渲染 Agent 分类 → 开关初始 checked；开关/默认模型下拉变更 →
 *   即改即存 PATCH /api/v1/projects/{id} body {config}（GREEN 前零 PATCH 调用）。
 *   注意：挂载初始化不得覆盖用例预置的 agent store config（「开关 ↔ config.agent_*」「下拉回读」
 *   用例先 setConfig 后挂载；GREEN 需幂等/空态守卫，契约不约束实现方式）。
 * - 🔴-3 主题预览卡可达：GeneralPanel 渲染 <AppearanceCard /> —— theme-preview-paper/night/ink
 *   预览卡 testid 存在于常规面板内（AppearanceCard 全仓 0 引用 → 修复目标）；预览卡 role=radio +
 *   aria-checked，兼容既有 getByRole('radio', { name: /素笺/ }) 断言（GREEN 删裸 RadioGroup 重复实现）。
 * - 默认字数真实 PATCH：失焦 → PATCH body config 含 default_words: 1000（替代仅本地 state 的假 toast；
 *   值接 store config.default_words）+ toast 仍弹。
 * - 快捷键表：断言 kbd 文本精确等于五组（'Shift+Enter' 是 'Ctrl+Shift+Enter' 子串 → 禁 toHaveTextContent
 *   子串断言）。
 *
 * ⚠️ #105 修复批二次迭代 RED 契约（2026-08-06 评审复查 🔴-A/🔴-B，GREEN 前以下断言 FAIL = RED 证据）：
 * - 🔴-A 播种守卫收紧：AgentPanel 挂载守卫不得以「config 有任意 key」跳过播种——general 先改
 *   default_words（store 仅 {default_words} 非结构性字段）→ 切 agent 仍按项目 config 重新播种，
 *   四开关初始状态与项目 config 一致。守卫语义 = 仅当 config 不含 model 且不含任何 agent_* 系字段
 *   时播种（既有「先 setConfig 后挂载」用例预置含 model / agent_* 系字段 → 不播种保持绿）。
 * - 🔴-B 交叉操作不丢字段：general defaultWords 失焦 PATCH 的合并源 = agent store 当前 config
 *   （{...useAgentStore.getState().config, default_words: n}），不得用 project store 旧快照——
 *   agent toggle 落库后回 general 改字数，最新 PATCH body 必须含 toggle 结果与全部已配置字段。
 * - 失败 PATCH 弹 err toast：defaultWords 失焦 PATCH reject → pushToast('err', ...)（现状 catch
 *   吞掉后无条件 pushToast('ok') → RED）。
 *
 * ⚠️ #107 模板分类转正 RED 契约（2026-08-06，spec §9.2.5 / §9.5 / M4；占位 → 真实面板）：
 * - 占位用例（set.templates.placeholder 断言）删除；模板分类转正。data-testid 即契约：
 *   template-list（列表容器）/ template-card-<id> / template-usedby-<id>（应用项目数徽标
 *   「N 个项目使用」，无引用不渲染）/ template-default-badge-<id>（「默认」标记，is_default=true）/
 *   template-add-btn / template-edit-<id> / template-delete-<id> / template-set-default-<id> /
 *   template-confirm-dialog（风险确认框）/ template-confirm-ok / template-confirm-cancel
 * - 进入模板分类 → 面板挂载 → loadTemplates()（GET /api/v1/agent-templates → {items}）；
 *   列表项含 used_by（前端契约，见 stores/templates 契约）
 * - 删除：被引用 → 风险确认「该模板正在被 {n} 个项目使用（{names}）」（tpl.confirm.deleteReferenced）
 *   确认 → DELETE /api/v1/agent-templates/{id} + 列表移除；无引用 → 通用文案
 *   「确定删除「{name}」？此操作不可撤销」（tpl.confirm.delete）；取消分支 → 不发 DELETE
 * - 设为默认（template-set-default-<id>）→ PATCH /api/v1/agent-templates/default body {id}
 *   → 默认徽标迁移（目标卡片出现「默认」，原默认卡片移除）
 * - 编辑被引用模板保存 → 风险确认（tpl.confirm.saveReferenced「…保存将同步影响这些项目的
 *   Agent 配置」）→ 确认 → PATCH /api/v1/agent-templates/{id}；取消 → 不发 PATCH（spec §9.5）
 * - 新建/编辑按钮 → TemplateDialog 打开（编辑模式回显名称）
 * - RED 阶段 mock：vi.mock('../stores/templates') + vi.mock('../components/TemplateDialog')
 *   （两模块 GREEN 才创建；本文件以测试内假实现提供，保证既有用例可运行——
 *   假 store 行为与 stores/templates.test.ts 契约一致，假 dialog 为受控表单壳）。
 *   GREEN 落地后此两 mock 可删改真实 import。→ 本文件 RED 形态 = 新用例 element-missing
 *   （template-list / template-add-btn 等不存在），既有用例保持绿。
 *
 * 新增 i18n key（GREEN 补 zh.ts / en.ts）：
 * set.title='设置' set.cat.general='常规' set.cat.models='模型' set.cat.agent='Agent'
 * set.cat.templates='模板' set.cat.account='账户' set.font='编辑器字体'
 * set.font.serif='衬线' set.font.sans='无衬线' set.font.mono='等宽'
 * set.defaultWords='新章节默认字数' set.models.summary='已配置 Provider'
 * set.models.placeholder='模型管理将在后续版本提供' set.templates.placeholder='模板功能将在后续版本提供'
 * set.account.dataDir='数据目录' set.account.about='关于' set.shortcuts.title='快捷键一览'
 * toast.saved='已保存'
 * （#107 新增，GREEN 补 zh.ts / en.ts；set.templates.placeholder 不再使用，GREEN 可清理）：
 * tpl.usedBy='{n} 个项目使用' tpl.defaultBadge='默认'
 * tpl.confirm.delete='确定删除「{name}」？此操作不可撤销'
 * tpl.confirm.deleteReferenced='该模板正在被 {n} 个项目使用（{names}）'
 * tpl.confirm.saveReferenced='该模板正在被 {n} 个项目使用（{names}），保存将同步影响这些项目的 Agent 配置'
 *
 * ⚠️ #167 F31 GUI 托盘常驻 RED 契约（2026-08-08，spec §6.2 设置页 UI + §2.3 IPC 契约）：
 * GeneralPanel 新增「关闭窗口时」设置项——设置项未实现 → 本批新用例全部 element-missing /
 * 零 IPC 调用 FAIL（RED 证据），既有用例保持绿：
 * - 渲染「关闭窗口时」标签（set.closeBehavior）+ Select（combobox aria-label「关闭窗口时」，
 *   默认「最小化到系统托盘」set.closeBehavior.tray / 「直接退出」set.closeBehavior.quit）
 * - 挂载时 window.INKFLOW_API.settings.getCloseBehavior() 取初值（mock 返回 'tray'）
 * - 切换 quit → window.INKFLOW_API.settings.setCloseBehavior('quit')（选择即生效）
 * - 无 window.INKFLOW_API（浏览器 dev）→ 可选链吞掉调用，Select 仍默认显示 tray 文案
 * 新增 i18n key（GREEN 补 zh.ts / en.ts）：set.closeBehavior / set.closeBehavior.tray /
 * set.closeBehavior.quit
 *
 * ⚠️ F32 设置持久化（#152，spec §5.4/§6.2/§6.3/§9.4）RED 段（2026-08-08）——设计假设清单：
 * - settings.tsx GeneralPanel 改造：font / closeBehavior 从 theme store 读（组件本地 state
 *   移除，§6.3 对照表）；新增「首次托盘提示」开关（data-testid 自定 = settings-tray-hint-switch，
 *   docstring 注明，GREEN 必须匹配；i18n set.trayHint 由 GREEN 补 zh.ts/en.ts）；
 *   default_words 用 ref 镜像（valueRef/dirtyRef，评审 🟡-7）+ 卸载 cleanup flush
 *   （fire-and-forget，经 useProjectStore.updateConfig 单次 PATCH 完整 config，评审 🔴-2）+
 *   切项目重读（currentProjectId 变化 → 重读新项目值 + 清 dirty，缺陷 #2）
 * - flushDefaultWords 契约（§5.4）：空值/非法 → 静默不 PATCH；<1000 → err toast 不 PATCH；
 *   合法 → PATCH /api/v1/projects/{id} body {config:{...}} → 成功：project store 本地合并同步
 *   + agent store setConfig + 清 dirty；失败：err toast + agent store 不被污染（缺陷 #4）+
 *   dirty 保持；无当前项目 → 不保存（评审 🟢）
 * - 既有 F31 describe（#167）保持绿的前提：GREEN 保留挂载 getCloseBehavior 取初值
 *   （spec §5.3 允许与 store 两处并存，幂等）——若 GREEN 迁移为纯 store 读，该用例由父 agent
 *   裁定升级；F31「切换 → IPC setCloseBehavior」用例在 GREEN 下走 store 链路（PATCH 成功
 *   → IPC 推送）保持绿
 * - 文件级 beforeEach 已扩展重置 font/closeBehavior/trayHintDismissed（测试间隔离：防「上一
 *   用例改 store 值 → 下一用例 Select 初值漂移」污染既有用例）
 * - RED 预期：GREEN 前新用例 FAIL 于 element-missing（settings-tray-hint-switch 不存在）/
 *   断言型缺口（font/closeBehavior 初值 = 本地 state 写死）/ waitFor 超时（卸载 flush 不存在、
 *   project store 不合并）/ 污染断言（失败路径现状先 setConfig）；既有用例保持绿
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { SettingsPage } from './settings';
import { apiFetch } from '../api/client';
import { useAgentStore } from '../stores/agent';
import { useProjectStore, type ProjectConfig } from '../stores/project';
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

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return {
    ...actual,
    apiFetch: vi.fn(),
    fetchSettings: fetchSettingsMock,
    patchSettings: patchSettingsMock,
  };
});

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
      await apiFetch('/api/v1/agent-templates/default', { method: 'PATCH', body: { id } });
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
  apiFetchMock.mockResolvedValue({ ok: true });
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

  it('四行渲染：Architect/Writer/Auditor/Reviser + 描述 + 4 开关', async () => {
    await openAgentPanel();
    const card = screen.getByTestId('agent-chain-card');
    expect(within(card).getByText('Architect 大纲架构师')).toBeInTheDocument();
    expect(within(card).getByText('Writer 执笔')).toBeInTheDocument();
    expect(within(card).getByText('Auditor 审校')).toBeInTheDocument();
    expect(within(card).getByText('Reviser 修订')).toBeInTheDocument();
    expect(within(card).getAllByRole('switch')).toHaveLength(4);
  });

  it('开关 ↔ config.agent_*：关闭 → undefined（从管线移除），重开 → null（默认模型）', async () => {
    act(() => {
      useAgentStore.getState().setConfig({
        agent_architect: 'gpt-4o',
        agent_writer: null,
        agent_auditor: 'gpt-4o',
        agent_reviser: 'gpt-4o',
      });
    });
    const user = await openAgentPanel();
    const card = screen.getByTestId('agent-chain-card');
    const switches = within(card).getAllByRole('switch');

    expect(switches[0]).toBeChecked();
    expect(switches[1]).toBeChecked();

    await user.click(switches[0]);
    expect(useAgentStore.getState().config.agent_architect).toBeUndefined();

    await user.click(switches[0]);
    expect(useAgentStore.getState().config.agent_architect).toBeNull();

    // 修复契约（#105 🔴-2）：开关变更 → 即改即存 PATCH /api/v1/projects/p1 body config 含
    // agent_architect: null（重开 = null 默认模型；undefined 态 JSON 序列化被丢弃 → 断言 null 态）。
    // GREEN 前 AgentPanel 零持久化 → 无 PATCH 调用 → RED
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

  it('开关变更即改即存：点击开关 → PATCH /api/v1/projects/p1 body 含 config.agent_architect（#105 🔴-2 修复契约）', async () => {
    seedProjectConfig({
      agent_architect: 'gpt-4o',
      agent_writer: 'gpt-4o',
      agent_auditor: 'gpt-4o',
      agent_reviser: 'gpt-4o',
    });
    const user = await openAgentPanel();
    const card = screen.getByTestId('agent-chain-card');
    const switches = within(card).getAllByRole('switch');

    // 关 → 开（开 = null 默认模型；undefined 序列化被 JSON 丢弃 → 断言 null 态的 PATCH body）
    await user.click(switches[0]);
    await user.click(switches[0]);

    // GREEN 前无 PATCH 调用 → RED
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

  it('默认模型下拉：combobox「默认模型」选项 openai/deepseek/ollama', async () => {
    const user = await openAgentPanel();
    await user.click(screen.getByRole('combobox', { name: '默认模型' }));
    expect(await screen.findByRole('option', { name: 'openai' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'deepseek' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'ollama' })).toBeInTheDocument();
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
        expect.objectContaining({ method: 'PATCH', body: expect.objectContaining({ id: 2 }) }),
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

describe('设置页 — 默认模型下拉回读与选择（#105 补测）', () => {
  async function openAgentPanel() {
    const user = userEvent.setup();
    renderSettings();
    await user.click(within(screen.getByTestId('settings-nav')).getByRole('button', { name: 'Agent' }));
    return user;
  }

  it('config.model 已配置 → 下拉回读当前模型值（truthy 分支）', async () => {
    act(() => {
      useAgentStore.getState().setConfig({ model: 'deepseek' });
    });
    await openAgentPanel();
    expect(screen.getByRole('combobox', { name: '默认模型' })).toHaveTextContent('deepseek');
  });

  it('选择模型 → setConfig({ model }) 即改即存', async () => {
    const user = await openAgentPanel();
    await user.click(screen.getByRole('combobox', { name: '默认模型' }));
    await user.click(await screen.findByRole('option', { name: 'ollama' }));
    expect(useAgentStore.getState().config.model).toBe('ollama');
    // 修复契约（#105 🔴-2）：下拉变更 → 即改即存 PATCH /api/v1/projects/p1 body config.model
    // （GREEN 前零 PATCH 调用 → RED）
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/projects/p1',
        expect.objectContaining({
          method: 'PATCH',
          body: expect.objectContaining({ config: expect.objectContaining({ model: 'ollama' }) }),
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

    // Agent 分类：store 空 → 挂载播种；architect 关→开（null 态可序列化）
    await user.click(within(screen.getByTestId('settings-nav')).getByRole('button', { name: 'Agent' }));
    const card = screen.getByTestId('agent-chain-card');
    const switches = within(card).getAllByRole('switch');
    await user.click(switches[0]);
    await user.click(switches[0]);
    await waitFor(() => {
      expect(useAgentStore.getState().config.agent_architect).toBeNull();
    });

    // 回 General 分类：改 default_words → 失焦 PATCH
    await user.click(within(screen.getByTestId('settings-nav')).getByRole('button', { name: '常规' }));
    const input = screen.getByLabelText('新章节默认字数');
    await user.clear(input);
    await user.type(input, '60000');
    await user.tab();

    // 契约：最新 PATCH body config = 全部已配置字段（现状合并源 = project store 旧快照 →
    // agent_architect 回 'deepseek' 而非 null → FAIL = RED）
    await waitFor(() => {
      const patchCalls = apiFetchMock.mock.calls.filter((c) => c[1]?.method === 'PATCH');
      expect(patchCalls.length).toBeGreaterThanOrEqual(3); // toggle 关 + toggle 开 + general 失焦
      const lastBody = patchCalls[patchCalls.length - 1][1]?.body as { config: ProjectConfig };
      expect(lastBody.config).toEqual(
        expect.objectContaining({ model: 'gpt-4o', agent_architect: null, default_words: 60000 }),
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
    apiFetchMock.mockRejectedValueOnce(new Error('network down'));
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
    // 首个 PATCH 挂起（手动 resolve），后续 PATCH 立即成功
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      void path; // 参数契约保持（apiFetch 双参签名），仅使用 init
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

    // 第一次 toggle（off→on）：agent_architect=null → PATCH #1 in-flight（persistingRef=true）
    await user.click(switches[0]);
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledTimes(1));

    // 第二次 toggle（on→off）：agent_architect=undefined；并发守卫挂起 pending，不发新 PATCH
    await user.click(switches[0]);
    expect(apiFetchMock).toHaveBeenCalledTimes(1);

    // 完成 PATCH #1 → finally 检测 pending → 以最新 config 补存 PATCH #2
    await act(async () => {
      resolvePatch({ ok: true });
    });
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledTimes(2));

    const patchCalls = apiFetchMock.mock.calls.filter((c) => c[1]?.method === 'PATCH');
    const firstBody = patchCalls[0][1]?.body as { config: ProjectConfig };
    const lastBody = patchCalls[patchCalls.length - 1][1]?.body as { config: ProjectConfig };
    expect(firstBody.config).toEqual({ agent_architect: null }); // toggle1 的 config
    expect(lastBody.config).toEqual({ agent_architect: undefined }); // toggle2（最新）的 config
  });

  it('无当前项目：persist 早退（不发 PATCH、不弹 toast）', async () => {
    useProjectStore.setState({ currentProjectId: null, projects: [] });
    const user = await openAgentPanel();
    const card = screen.getByTestId('agent-chain-card');

    await user.click(within(card).getAllByRole('switch')[0]);

    expect(apiFetchMock).not.toHaveBeenCalled();
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

// ⚠️ F32（#152）：theme store 扩展契约的测试侧类型（GREEN 补全 stores/theme.ts 后此段可删；
// esbuild 不查类型但 RED 验证要求 tsc --noEmit 绿——运行时缺失方法 → TypeError = RED 证据）
type FontKeyF32 = 'serif' | 'sans' | 'mono';
type CloseBehaviorF32 = 'tray' | 'quit';
type ThemeStoreF32 = ReturnType<typeof useThemeStore.getState> & {
  font: FontKeyF32;
  closeBehavior: CloseBehaviorF32;
  trayHintDismissed: boolean;
  setFont: (f: FontKeyF32) => void;
  setCloseBehavior: (b: CloseBehaviorF32) => Promise<void>;
  setTrayHintDismissed: (v: boolean) => Promise<void>;
  initFromBackend: () => Promise<void>;
};
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
});
