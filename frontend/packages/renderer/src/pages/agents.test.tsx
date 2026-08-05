/**
 * Agent 配置页测试契约（Issue #79 RED 阶段，spec §4.2.3）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 AgentsPage 必须匹配（行为断言，不测样式）：
 *
 * 结构（data-testid）：agent-llm-card（模型接入）/ agent-chain-card（写作 Agent 链）/ agent-appearance-card（外观）
 *
 * 模型接入卡片（原生表单控件契约：select/input/range —— 渲染层当前无 radix 依赖）：
 * - 服务商 combobox：openai / deepseek / ollama（provider_config.py 内建注册表核实）
 * - 模型输入（label「模型」）、API Key 输入（label「API Key」）、温度滑杆
 *   （input type=range min=0 max=2 step=0.1，值对齐 config.temperature）、默认字数输入
 * - 温度滑杆变更 → agentStore.config.temperature
 * - API Key 落点：保存时若 apiKeyDraft 非空 → POST /api/v1/settings/llm-keys（body {provider, model, api_key}）→ 清空输入
 * - 测试连接 = POST /api/v1/settings/llm/test：成功 → 「连接成功」+ 保存可用（主路径）；
 *   失败 → 「连接失败: {原因}」+ 直接保存始终可用（PATCH /api/v1/projects/{id} {config}）
 * - 保存 = PATCH /api/v1/projects/{currentProjectId}
 *
 * Agent 链卡片：Architect/Writer/Auditor/Reviser 四行（role="switch"，含描述文案），
 * 开关 ↔ config.agent_* 映射：关闭 → 字段置 undefined（从管线移除）；重开 → null（默认模型）
 *
 * 外观卡片：主题三选（role="radio"：素笺/夜航/墨韵）→ themeStore.theme；
 * 背景 combobox 随主题过滤（paper: 默认+羊皮纸 / night: 默认+墨蓝黑 / ink: 默认+深褐纸）；
 * 语言 combobox（中文/EN）→ themeStore.lang，UI 文案随语言切换
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AgentsPage } from './agents';
import { apiFetch } from '../api/client';
import { useAgentStore } from '../stores/agent';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({
    projects: [{ id: 'p1', name: '青云志', genre: '玄幻', language: 'zh-CN', target_words: 800000, config: {}, created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z' }],
    currentProjectId: 'p1', loading: false, error: null,
  });
  useAgentStore.setState({ config: {}, apiKeyDraft: '', testStatus: 'idle', testMessage: null });
  apiFetchMock.mockResolvedValue({ ok: true });
});

describe('Agent 页 — 结构', () => {
  it('渲染两卡片 + 外观卡片', () => {
    render(<AgentsPage />);
    expect(screen.getByTestId('agent-llm-card')).toBeInTheDocument();
    expect(screen.getByTestId('agent-chain-card')).toBeInTheDocument();
    expect(screen.getByTestId('agent-appearance-card')).toBeInTheDocument();
  });
});

describe('Agent 页 — 模型接入卡片', () => {
  it('字段渲染：服务商（openai/deepseek/ollama）/ 模型 / API Key / 温度滑杆 / 默认字数', () => {
    render(<AgentsPage />);
    const card = screen.getByTestId('agent-llm-card');

    const provider = within(card).getByLabelText('服务商');
    expect(provider.tagName).toBe('SELECT');
    expect(within(provider).getByRole('option', { name: 'openai' })).toBeInTheDocument();
    expect(within(provider).getByRole('option', { name: 'deepseek' })).toBeInTheDocument();
    expect(within(provider).getByRole('option', { name: 'ollama' })).toBeInTheDocument();

    expect(within(card).getByLabelText('模型')).toBeInTheDocument();
    expect(within(card).getByLabelText('API Key')).toBeInTheDocument();

    const slider = within(card).getByLabelText('温度') as HTMLInputElement;
    expect(slider.type).toBe('range');
    expect(slider.min).toBe('0');
    expect(slider.max).toBe('2');
    expect(slider.step).toBe('0.1');

    expect(within(card).getByLabelText('默认字数')).toBeInTheDocument();
  });

  it('温度滑杆变更 → config.temperature（对齐 ProjectConfig.temperature 0-2.0）', () => {
    act(() => {
      useAgentStore.getState().setConfig({ temperature: 0.7 });
    });
    render(<AgentsPage />);
    const slider = screen.getByLabelText('温度') as HTMLInputElement;
    expect(slider.value).toBe('0.7');

    // range 输入用 fireEvent.change（userEvent.type 对 range 无效）
    fireEvent.change(slider, { target: { value: '1.2' } });
    expect(useAgentStore.getState().config.temperature).toBe(1.2);
  });

  it('保存：API Key 落点 POST /settings/llm-keys → 清空 draft → PATCH /projects/{id} config', async () => {
    const user = userEvent.setup();
    render(<AgentsPage />);
    const card = screen.getByTestId('agent-llm-card');

    await user.type(within(card).getByLabelText('API Key'), 'sk-secret-123');
    await user.selectOptions(within(card).getByLabelText('服务商'), 'openai');
    await user.type(within(card).getByLabelText('模型'), 'gpt-4o');
    await user.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/settings/llm-keys', {
        method: 'POST',
        body: { provider: 'openai', model: 'gpt-4o', api_key: 'sk-secret-123' },
      });
    });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/projects/p1', {
      method: 'PATCH',
      body: { config: expect.objectContaining({ model: 'gpt-4o' }) },
    });
    expect(within(card).getByLabelText('API Key')).toHaveValue('');
  });

  it('测试连接成功：POST /settings/llm/test → 「连接成功」+ 保存可用（主路径）', async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/settings/llm/test') return { ok: true };
      return { ok: true };
    });
    const user = userEvent.setup();
    render(<AgentsPage />);

    await user.click(screen.getByRole('button', { name: '测试连接' }));
    expect(await screen.findByText('连接成功')).toBeInTheDocument();
    expect(useAgentStore.getState().testStatus).toBe('ok');
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/settings/llm/test', {
      method: 'POST',
      body: expect.objectContaining({ provider: expect.any(String), model: expect.any(String) }),
    });
    expect(screen.getByRole('button', { name: '保存' })).toBeEnabled();
  });

  it('测试连接失败：原因展示 + 直接保存始终可用（PATCH 仍可执行）', async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/settings/llm/test') return { ok: false, message: '模型不可达' };
      return { ok: true };
    });
    const user = userEvent.setup();
    render(<AgentsPage />);

    await user.click(screen.getByRole('button', { name: '测试连接' }));
    expect(await screen.findByText('连接失败: 模型不可达')).toBeInTheDocument();
    expect(useAgentStore.getState().testStatus).toBe('fail');

    // 直接保存（用户自信场景）
    await user.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/projects/p1', expect.objectContaining({ method: 'PATCH' }));
    });
  });
});

describe('Agent 页 — 写作 Agent 链', () => {
  it('四行渲染：Architect/Writer/Auditor/Reviser + 描述 + 开关', () => {
    render(<AgentsPage />);
    const card = screen.getByTestId('agent-chain-card');
    // 角色名用精确字典值断言（ag.chainDesc 副标题含英文角色名，/Architect/ 正则会匹配 2 处）
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
    const user = userEvent.setup();
    render(<AgentsPage />);
    const card = screen.getByTestId('agent-chain-card');
    const switches = within(card).getAllByRole('switch');

    // 初始：architect 开启（非空模型），writer 开启（null = 默认模型）
    expect(switches[0]).toBeChecked();
    expect(switches[1]).toBeChecked();

    // 关闭 Architect → 字段 undefined（从管线移除）
    await user.click(switches[0]);
    expect(useAgentStore.getState().config.agent_architect).toBeUndefined();

    // 重开 Architect → null（默认模型）
    await user.click(switches[0]);
    expect(useAgentStore.getState().config.agent_architect).toBeNull();
  });
});

describe('Agent 页 — 外观卡片', () => {
  it('主题三选：radio 切换 → themeStore.theme 更新', async () => {
    const user = userEvent.setup();
    render(<AgentsPage />);
    const card = screen.getByTestId('agent-appearance-card');
    const radios = within(card).getAllByRole('radio');
    expect(radios).toHaveLength(3);

    expect(useThemeStore.getState().theme).toBe('paper');
    await user.click(within(card).getByRole('radio', { name: /夜航/ }));
    expect(useThemeStore.getState().theme).toBe('night');
    await user.click(within(card).getByRole('radio', { name: /墨韵/ }));
    expect(useThemeStore.getState().theme).toBe('ink');
  });

  it('背景变体随主题过滤：paper → 默认+羊皮纸；night → 默认+墨蓝黑；ink → 默认+深褐纸', async () => {
    const user = userEvent.setup();
    render(<AgentsPage />);
    const card = screen.getByTestId('agent-appearance-card');

    // 背景下拉选项（仅取背景 select 自身，避免混入服务商等其它 select 的 option）
    const bgSelect = within(card).getByLabelText('背景') as HTMLSelectElement;
    const bgNames = (): string[] => Array.from(bgSelect.options).map((o) => o.textContent ?? '');

    // paper（默认主题）：默认 + 羊皮纸
    const paperOptions = bgNames();
    expect(paperOptions).toContain('默认');
    expect(paperOptions).toContain('羊皮纸');
    expect(paperOptions).not.toContain('墨蓝黑');

    await user.click(within(card).getByRole('radio', { name: /夜航/ }));
    const nightOptions = bgNames();
    expect(nightOptions).toContain('默认');
    expect(nightOptions).toContain('墨蓝黑');
    expect(nightOptions).not.toContain('羊皮纸');

    await user.click(within(card).getByRole('radio', { name: /墨韵/ }));
    const inkOptions = bgNames();
    expect(inkOptions).toContain('默认');
    expect(inkOptions).toContain('深褐纸');
    expect(inkOptions).not.toContain('墨蓝黑');
  });

  it('语言切换：zh → en，UI 文案随语言切换', async () => {
    const user = userEvent.setup();
    render(<AgentsPage />);
    const card = screen.getByTestId('agent-appearance-card');

    expect(screen.getByRole('heading', { name: 'Agent 与模型配置' })).toBeInTheDocument();
    await user.selectOptions(within(card).getByLabelText('语言'), 'en');
    expect(useThemeStore.getState().lang).toBe('en');
    expect(screen.getByRole('heading', { name: 'Agents & Model' })).toBeInTheDocument();
  });
});
