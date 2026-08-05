/**
 * ⚠️ 契约文件（Issue #105 导航重构 RED 阶段，spec §7.4 设置页框架）
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
 *   快捷键一览表（含 Ctrl+Z/Ctrl+Y/Ctrl+S/Ctrl+Enter/Shift+Enter 五组）
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
import { useProjectStore } from '../stores/project';
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

    // 快捷键一览表：五组快捷键组合
    const shortcuts = screen.getByTestId('settings-shortcuts');
    for (const combo of ['Ctrl+Z', 'Ctrl+Y', 'Ctrl+S', 'Ctrl+Enter', 'Shift+Enter']) {
      expect(shortcuts).toHaveTextContent(combo);
    }
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

  it('即改即存：新章节默认字数失焦 → pushToast ok「已保存」（spec §7.4 数字项失焦即存）', async () => {
    const user = userEvent.setup();
    renderSettings();

    const input = screen.getByLabelText('新章节默认字数');
    await user.clear(input);
    await user.type(input, '1000');
    await user.tab(); // 失焦 → 即存

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
  });
});
