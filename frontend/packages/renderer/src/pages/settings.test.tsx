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
 * - 模板：占位（#107 前不实现）
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
 * 新增 i18n key（GREEN 补 zh.ts/en.ts；theme 系 / ap 系 / ag 系 key 已有）：
 * set.title='设置' set.cat.general='常规' set.cat.models='模型' set.cat.agent='Agent'
 * set.cat.templates='模板' set.cat.account='账户' set.font='编辑器字体'
 * set.font.serif='衬线' set.font.sans='无衬线' set.font.mono='等宽'
 * set.defaultWords='新章节默认字数' set.models.summary='已配置 Provider'
 * set.models.placeholder='模型管理将在后续版本提供' set.templates.placeholder='模板功能将在后续版本提供'
 * set.account.dataDir='数据目录' set.account.about='关于' set.shortcuts.title='快捷键一览'
 * toast.saved='已保存'
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

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
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
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
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

describe('设置页 — 模型/模板/账户分类（占位，spec §7.4）', () => {
  it('模型分类：Provider 摘要 + 占位（#106 前不实现管理）', async () => {
    const user = userEvent.setup();
    renderSettings();
    await user.click(within(screen.getByTestId('settings-nav')).getByRole('button', { name: '模型' }));
    const panel = screen.getByTestId('settings-panel');
    expect(panel).toHaveTextContent('已配置 Provider');
    expect(panel).toHaveTextContent('模型管理将在后续版本提供');
  });

  it('模板分类：占位（#107 前不实现）；账户分类：数据目录 + 关于', async () => {
    const user = userEvent.setup();
    renderSettings();
    const nav = screen.getByTestId('settings-nav');

    await user.click(within(nav).getByRole('button', { name: '模板' }));
    expect(screen.getByTestId('settings-panel')).toHaveTextContent('模板功能将在后续版本提供');

    await user.click(within(nav).getByRole('button', { name: '账户' }));
    const panel = screen.getByTestId('settings-panel');
    expect(panel).toHaveTextContent('数据目录');
    expect(panel).toHaveTextContent('关于');
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
