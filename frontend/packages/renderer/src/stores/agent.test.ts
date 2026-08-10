/**
 * agent store 测试契约（Issue #79 RED 阶段，spec §4.2.3 / §4.4）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须匹配以下导出/签名：
 *
 * 新增 REST actions（当前骨架缺失 → RED）：
 * - submitApiKey(input: { provider: string; model: string; api_key: string }): Promise<void>
 *     POST /api/v1/settings/llm-keys（Q3 拍板工具端点，APIKeyManager 加密存储）
 *     → 成功清空 apiKeyDraft；失败保留 draft（不丢用户输入）并抛出（页面展示）
 * - testConnection(input: { provider: string; model: string; api_key: string }): Promise<void>
 *     POST /api/v1/settings/llm/test（LLMClient 最小探测）
 *     响应契约（后端端点随 #79 交付，设计假设）：成功 {ok: true} → testStatus 'ok' + '连接成功'；
 *     失败 {ok: false, message} → testStatus 'fail' + '连接失败: {message}'；网络/HTTP 错误同理置 fail
 * - saveConfig(projectId: string, provider?: string): Promise<void>
 *     保存流程（Q3 拍板：测试通过→保存主路径 + 直接保存并存）：
 *     PATCH /api/v1/projects/{projectId}，body { config: 当前 config }
 *     若 apiKeyDraft 非空 → 先 POST /api/v1/settings/llm-keys（落 key，provider 取参数）→ 清空 draft → 再 PATCH config
 *
 * 表单语义契约（spec §4.2.3 + #225 拍板 2026-08-10）：
 * - config.agent_*: string | null —— null = 关闭（禁用该角色）；字符串 = 开启且指定模型；
 *   字符串 "__default__"（AGENT_DEFAULT_SENTINEL）= 跟随默认（预留，前端本期不暴露中间态 UI）
 * - 关闭必须显式发送 null：undefined 会被 JSON.stringify 省略 → 后端视为「缺失」（不改字段）
 *   → 重启读回旧值 → 开关误显示开启（#225 根因链，E3-3 E2E 实证）
 * - temperature: 0.0-2.0（后端 ProjectConfig Field ge=0 le=2）
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act } from '@testing-library/react';
import { useAgentStore } from './agent';
import { apiFetch, KernelOfflineError } from '../api/client';
import type { ProjectConfig } from './project';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

beforeEach(() => {
  apiFetchMock.mockReset();
  useAgentStore.setState({ config: {}, apiKeyDraft: '', testStatus: 'idle', testMessage: null });
});

describe('agent store — 契约面（GREEN 必须提供）', () => {
  it('暴露 REST actions: submitApiKey / testConnection / saveConfig', () => {
    const s = useAgentStore.getState();
    expect(typeof s.submitApiKey).toBe('function');
    expect(typeof s.testConnection).toBe('function');
    expect(typeof s.saveConfig).toBe('function');
  });
});

describe('agent store — ProjectConfig 表单状态', () => {
  it('初始 config 为空表单（未加载项目）', () => {
    const s = useAgentStore.getState();
    expect(s.config).toEqual({});
    expect(s.apiKeyDraft).toBe('');
    expect(s.testStatus).toBe('idle');
    expect(s.testMessage).toBeNull();
  });

  it('setConfig 局部合并：不覆盖未涉及字段', () => {
    act(() => {
      useAgentStore.getState().setConfig({ temperature: 1.2, model: 'deepseek-chat' });
    });
    act(() => {
      useAgentStore.getState().setConfig({ writing_style: '文风细腻' });
    });
    const c = useAgentStore.getState().config;
    expect(c.temperature).toBe(1.2);
    expect(c.model).toBe('deepseek-chat');
    expect(c.writing_style).toBe('文风细腻');
  });

  it('null = 关闭语义（#225）：agent_architect 显式置 null（禁用角色），JSON 序列化保留', () => {
    act(() => {
      useAgentStore.getState().setConfig({ agent_architect: null });
    });
    expect(useAgentStore.getState().config.agent_architect).toBeNull();
    // 线缆语义（#225）：null 被 JSON.stringify 保留 → PATCH body 含 agent_architect: null
    // （与 undefined 省略键相反——后端可区分「关闭」vs「缺失」）
    expect(JSON.stringify(useAgentStore.getState().config)).toContain('"agent_architect":null');
  });

  it('undefined 不再用于关闭（#225 语义反转）：序列化省略是 JSON 事实，组件层禁止产生 undefined', () => {
    act(() => {
      useAgentStore.getState().setConfig({ agent_writer: 'gpt-4o' });
    });
    act(() => {
      useAgentStore.getState().setConfig({ agent_writer: undefined });
    });
    const cfg = useAgentStore.getState().config;
    expect(cfg.agent_writer).toBeUndefined();
    // JSON 事实：undefined 键被省略 → 后端视为「缺失」（不改字段）→ 重启读回旧值 →
    // 开关误显示开启——#225 根因，关闭必须显式 null（见 AgentChainCard 契约）
    expect(JSON.stringify(cfg)).not.toContain('agent_writer');
  });

  it('loadFromProject：填充 config 并复位测试状态', () => {
    const cfg: ProjectConfig = { model: 'gpt-4o', agent_architect: null, temperature: 0.9, writing_style: '凝练' };
    act(() => {
      useAgentStore.getState().setTestStatus('fail', '连接失败: 超时');
      useAgentStore.getState().loadFromProject(cfg);
    });
    const s = useAgentStore.getState();
    expect(s.config).toEqual(cfg);
    expect(s.testStatus).toBe('idle');
    expect(s.testMessage).toBeNull();
  });
});

describe('agent store — REST actions', () => {
  it('submitApiKey：POST /settings/llm-keys → 成功清空 apiKeyDraft', async () => {
    apiFetchMock.mockResolvedValue({ ok: true });
    act(() => {
      useAgentStore.getState().setApiKeyDraft('sk-abc123');
    });
    await act(async () => {
      await useAgentStore.getState().submitApiKey({ provider: 'openai', model: 'gpt-4o', api_key: 'sk-abc123' });
    });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/settings/llm-keys', {
      method: 'POST',
      body: { provider: 'openai', model: 'gpt-4o', api_key: 'sk-abc123' },
    });
    expect(useAgentStore.getState().apiKeyDraft).toBe('');
  });

  it('submitApiKey 失败：保留 apiKeyDraft（不丢用户输入）', async () => {
    apiFetchMock.mockRejectedValue(new Error('加密存储失败'));
    act(() => {
      useAgentStore.getState().setApiKeyDraft('sk-abc123');
    });
    await act(async () => {
      await expect(
        useAgentStore.getState().submitApiKey({ provider: 'openai', model: 'gpt-4o', api_key: 'sk-abc123' }),
      ).rejects.toThrow('加密存储失败');
    });
    expect(useAgentStore.getState().apiKeyDraft).toBe('sk-abc123');
  });

  it('testConnection 成功：testStatus ok + 连接成功', async () => {
    apiFetchMock.mockResolvedValue({ ok: true });
    await act(async () => {
      await useAgentStore.getState().testConnection({ provider: 'openai', model: 'gpt-4o', api_key: 'sk-abc123' });
    });
    const s = useAgentStore.getState();
    expect(s.testStatus).toBe('ok');
    expect(s.testMessage).toBe('连接成功');
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/settings/llm/test', {
      method: 'POST',
      body: { provider: 'openai', model: 'gpt-4o', api_key: 'sk-abc123' },
    });
  });

  it('testConnection 失败：testStatus fail + 原因展示', async () => {
    apiFetchMock.mockResolvedValue({ ok: false, message: '模型不可达' });
    await act(async () => {
      await useAgentStore.getState().testConnection({ provider: 'deepseek', model: 'deepseek-chat', api_key: '' });
    });
    const s = useAgentStore.getState();
    expect(s.testStatus).toBe('fail');
    expect(s.testMessage).toContain('模型不可达');
  });

  it('saveConfig：无 draft 时仅 PATCH config', async () => {
    apiFetchMock.mockResolvedValue({ ok: true });
    act(() => {
      useAgentStore.getState().setConfig({ temperature: 1.2 });
    });
    await act(async () => {
      await useAgentStore.getState().saveConfig('p1');
    });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/projects/p1', {
      method: 'PATCH',
      body: { config: { temperature: 1.2 } },
    });
  });

  it('saveConfig：有 draft 时先落 key 再 PATCH config（Q3 保存主路径）', async () => {
    apiFetchMock.mockResolvedValue({ ok: true });
    act(() => {
      useAgentStore.getState().setConfig({ model: 'gpt-4o' });
      useAgentStore.getState().setApiKeyDraft('sk-xyz');
    });
    await act(async () => {
      await useAgentStore.getState().saveConfig('p1', 'openai');
    });
    expect(apiFetchMock).toHaveBeenNthCalledWith(1, '/api/v1/settings/llm-keys', {
      method: 'POST',
      body: { provider: 'openai', model: 'gpt-4o', api_key: 'sk-xyz' },
    });
    expect(apiFetchMock).toHaveBeenNthCalledWith(2, '/api/v1/projects/p1', {
      method: 'PATCH',
      body: { config: { model: 'gpt-4o' } },
    });
    expect(useAgentStore.getState().apiKeyDraft).toBe('');
  });

  it('saveConfig：#225 关闭态（null）→ PATCH body config 含 agent_writer: null（显式 null 非缺键）', async () => {
    // 确认型：store 透传 config（含 null 键）——锁「关闭 = 显式 null」线缆不被过滤/省略
    apiFetchMock.mockResolvedValue({ ok: true });
    act(() => {
      useAgentStore.getState().setConfig({ model: 'gpt-4o', agent_writer: 'deepseek/deepseek-chat' });
    });
    act(() => {
      useAgentStore.getState().setConfig({ agent_writer: null });
    });
    await act(async () => {
      await useAgentStore.getState().saveConfig('p1');
    });
    const patchCall = apiFetchMock.mock.calls.find((c) => c[0] === '/api/v1/projects/p1');
    expect(patchCall).toBeTruthy();
    const body = (patchCall![1] as { body: { config: ProjectConfig } }).body;
    expect(body.config.agent_writer).toBeNull(); // null 键存在 → JSON.stringify 保留 → 后端落库 null
    expect(body.config.model).toBe('gpt-4o'); // 未涉及字段透传
  });
});

describe('agent store — 薄弱分支补测（Issue #104）', () => {
  it('testConnection：res.ok=false 且无 message → 回退 error 字段', async () => {
    apiFetchMock.mockResolvedValue({ ok: false, error: '密钥无效' });
    await act(async () => {
      await useAgentStore.getState().testConnection({ provider: 'openai', model: 'gpt-4o', api_key: 'k' });
    });
    const s = useAgentStore.getState();
    expect(s.testStatus).toBe('fail');
    expect(s.testMessage).toBe('连接失败: 密钥无效');
  });

  it('testConnection：message/error 均缺失 → 回退「未知错误」', async () => {
    apiFetchMock.mockResolvedValue({ ok: false });
    await act(async () => {
      await useAgentStore.getState().testConnection({ provider: 'openai', model: 'gpt-4o', api_key: 'k' });
    });
    const s = useAgentStore.getState();
    expect(s.testStatus).toBe('fail');
    expect(s.testMessage).toBe('连接失败: 未知错误');
  });

  it('testConnection：apiFetch reject → catch 分支 fail + errorMessage(err)', async () => {
    apiFetchMock.mockRejectedValue(new KernelOfflineError('Kernel unreachable'));
    await act(async () => {
      await useAgentStore.getState().testConnection({ provider: 'openai', model: 'gpt-4o', api_key: 'k' });
    });
    const s = useAgentStore.getState();
    expect(s.testStatus).toBe('fail');
    // KernelOfflineError instanceof ApiError → errorMessage 取 detail
    expect(s.testMessage).toBe('连接失败: Kernel unreachable');
  });

  it('testConnection：请求挂起期间 testStatus=testing，成功后复位 ok', async () => {
    let resolveFetch!: (v: unknown) => void;
    apiFetchMock.mockReturnValue(new Promise((resolve) => {
      resolveFetch = resolve;
    }));
    let p!: Promise<void>;
    act(() => {
      p = useAgentStore.getState().testConnection({ provider: 'openai', model: 'gpt-4o', api_key: 'k' });
    });
    expect(useAgentStore.getState().testStatus).toBe('testing');
    expect(useAgentStore.getState().testMessage).toBeNull();

    resolveFetch({ ok: true });
    await act(async () => {
      await p;
    });
    expect(useAgentStore.getState().testStatus).toBe('ok');
    expect(useAgentStore.getState().testMessage).toBe('连接成功');
  });

  it('saveConfig：有 draft 但未传 provider → provider 回退空串（先 POST 再 PATCH 并清空 draft）', async () => {
    apiFetchMock.mockResolvedValue({ ok: true });
    act(() => {
      useAgentStore.getState().setConfig({ model: 'deepseek-chat' });
      useAgentStore.getState().setApiKeyDraft('sk-xyz');
    });
    await act(async () => {
      await useAgentStore.getState().saveConfig('p1');
    });
    expect(apiFetchMock).toHaveBeenNthCalledWith(1, '/api/v1/settings/llm-keys', {
      method: 'POST',
      body: { provider: '', model: 'deepseek-chat', api_key: 'sk-xyz' },
    });
    expect(apiFetchMock).toHaveBeenNthCalledWith(2, '/api/v1/projects/p1', {
      method: 'PATCH',
      body: { config: { model: 'deepseek-chat' } },
    });
    expect(useAgentStore.getState().apiKeyDraft).toBe('');
  });

  it('submitApiKey 成功：无论 draft 原值如何，成功后清空', async () => {
    apiFetchMock.mockResolvedValue({ ok: true });
    act(() => {
      useAgentStore.getState().setApiKeyDraft('sk-old');
    });
    await act(async () => {
      await useAgentStore.getState().submitApiKey({ provider: 'openai', model: 'gpt-4o', api_key: 'sk-new' });
    });
    expect(useAgentStore.getState().apiKeyDraft).toBe('');
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/settings/llm-keys', {
      method: 'POST',
      body: { provider: 'openai', model: 'gpt-4o', api_key: 'sk-new' },
    });
  });
});
