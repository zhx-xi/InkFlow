/**
 * AgentLlmCard 测试契约（Issue #105 §6.3① defaultWords 落字段 + #79 模型接入契约迁移）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 src/components/AgentLlmCard.tsx 必须匹配：
 *
 * §6.3① defaultWords 落字段（现状 L24 useState(800000) 本地 state，刷新丢失）：
 * - 默认字数输入（label「默认字数」，type=number）↔ store config 字段 `default_words`
 *   （ProjectConfig 新增字段，后端 config JSON 列存储）：
 *   * 回读：config.default_words 有值 → 输入框显示该值（本地 state 不再是唯一来源）
 *   * 保存：输入变更 → setConfig({ default_words }) → 保存 → PATCH /api/v1/projects/{id}
 *     body config 含 default_words
 *
 * 模型接入契约（迁移自 src/pages/agents.test.tsx，行为不变）：
 * - 服务商 combobox（role=combobox，aria-label「服务商」）：openai/deepseek/ollama
 *   （选项 portal 渲染，screen 级 findByRole('option')）
 * - 模型输入（label「模型」）、API Key 输入（label「API Key」，password）、
 *   温度滑杆（role=slider，aria-valuemin=0 / aria-valuemax=2，键盘步进 ±0.1）
 * - 测试连接 = POST /api/v1/settings/llm/test：成功 → 「连接成功」；失败 → 「连接失败: {原因}」
 * - 保存：apiKeyDraft 非空 → POST /api/v1/settings/llm-keys（body {provider, model, api_key}）
 *   → 清空 draft → PATCH /api/v1/projects/{currentProjectId}
 *
 * testid：`agent-llm-card`（沿用既有锚点）。
 * RED 预期：default_words 不落字段 → 回读/保存断言 FAIL；其余迁移断言保持 GREEN。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AgentLlmCard } from './AgentLlmCard';
import { apiFetch } from '../api/client';
import { useAgentStore } from '../stores/agent';
import { useProjectStore } from '../stores/project';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useProjectStore.setState({
    projects: [],
    currentProjectId: 'p1',
    loading: false,
    error: null,
    chapterProgress: {},
  });
  useAgentStore.setState({ config: {}, apiKeyDraft: '', testStatus: 'idle', testMessage: null });
  apiFetchMock.mockResolvedValue({ ok: true });
});

describe('AgentLlmCard — 默认字数落字段（Issue #105 §6.3①）', () => {
  it('回读：config.default_words 有值 → 输入框显示该值（刷新不丢）', () => {
    act(() => {
      useAgentStore.getState().setConfig({ model: 'gpt-4o', temperature: 0.7, default_words: 50000 });
    });
    render(<AgentLlmCard />);
    const card = screen.getByTestId('agent-llm-card');
    expect(within(card).getByLabelText('默认字数')).toHaveValue(50000);
  });

  it('保存：输入 30000 → PATCH /api/v1/projects/p1，body config 含 default_words', async () => {
    const user = userEvent.setup();
    render(<AgentLlmCard />);
    const card = screen.getByTestId('agent-llm-card');

    const words = within(card).getByLabelText('默认字数');
    await user.clear(words);
    await user.type(words, '30000');
    await user.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/projects/p1', {
        method: 'PATCH',
        body: { config: expect.objectContaining({ default_words: 30000 }) },
      });
    });
  });

  it('未改动的默认值保存：config.default_words 与输入一致（800000 基线）', async () => {
    const user = userEvent.setup();
    render(<AgentLlmCard />);
    const card = screen.getByTestId('agent-llm-card');

    expect(within(card).getByLabelText('默认字数')).toHaveValue(800000);
    await user.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/projects/p1', {
        method: 'PATCH',
        body: { config: expect.objectContaining({ default_words: 800000 }) },
      });
    });
  });
});

describe('AgentLlmCard — 模型接入（迁移自 agents.test.tsx）', () => {
  it('字段渲染：服务商（openai/deepseek/ollama）/ 模型 / API Key / 温度滑杆 / 默认字数', async () => {
    const user = userEvent.setup();
    render(<AgentLlmCard />);
    const card = screen.getByTestId('agent-llm-card');

    const provider = screen.getByRole('combobox', { name: '服务商' });
    expect(provider).toBeInTheDocument();
    await user.click(provider);
    expect(await screen.findByRole('option', { name: 'openai' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'deepseek' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'ollama' })).toBeInTheDocument();
    await user.keyboard('{Escape}');

    expect(within(card).getByLabelText('模型')).toBeInTheDocument();
    expect(within(card).getByLabelText('API Key')).toBeInTheDocument();

    const slider = screen.getByRole('slider', { name: '温度' });
    expect(slider).toHaveAttribute('aria-valuemin', '0');
    expect(slider).toHaveAttribute('aria-valuemax', '2');

    expect(within(card).getByLabelText('默认字数')).toBeInTheDocument();
  });

  it('温度滑杆变更 → config.temperature（对齐 ProjectConfig.temperature 0-2.0）', async () => {
    act(() => {
      useAgentStore.getState().setConfig({ temperature: 0.7 });
    });
    render(<AgentLlmCard />);
    const slider = screen.getByRole('slider', { name: '温度' });
    expect(slider).toHaveAttribute('aria-valuenow', '0.7');

    // Radix Slider 键盘步进：ArrowRight +0.1（实现端 step=0.1，0.7 → 0.8）
    slider.focus();
    fireEvent.keyDown(slider, { key: 'ArrowRight' });
    expect(useAgentStore.getState().config.temperature).toBeCloseTo(0.8);
  });

  it('保存：API Key 落点 POST /settings/llm-keys → 清空 draft → PATCH /projects/p1 config', async () => {
    const user = userEvent.setup();
    render(<AgentLlmCard />);
    const card = screen.getByTestId('agent-llm-card');

    await user.type(within(card).getByLabelText('API Key'), 'sk-secret-123');
    await user.click(screen.getByRole('combobox', { name: '服务商' }));
    await user.click(await screen.findByRole('option', { name: 'openai' }));
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

  it('测试连接成功：POST /settings/llm/test → 「连接成功」', async () => {
    const user = userEvent.setup();
    render(<AgentLlmCard />);

    await user.click(screen.getByRole('button', { name: '测试连接' }));
    expect(await screen.findByText('连接成功')).toBeInTheDocument();
    expect(useAgentStore.getState().testStatus).toBe('ok');
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/settings/llm/test', {
      method: 'POST',
      body: expect.objectContaining({ provider: expect.any(String), model: expect.any(String) }),
    });
  });

  it('测试连接失败：原因展示', async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/settings/llm/test') return { ok: false, message: '模型不可达' };
      return { ok: true };
    });
    const user = userEvent.setup();
    render(<AgentLlmCard />);

    await user.click(screen.getByRole('button', { name: '测试连接' }));
    expect(await screen.findByText('连接失败: 模型不可达')).toBeInTheDocument();
    expect(useAgentStore.getState().testStatus).toBe('fail');
  });
});
