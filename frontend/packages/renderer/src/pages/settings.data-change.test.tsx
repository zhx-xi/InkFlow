/**
 * 设置页数据面变更订阅接线（F23 §15.6.2 / #1088 批 A3）
 *
 * 契约：SettingsPage 登记四个**全局域**（agent_template / settings / provider_config / agent，
 * project_id 缺省 → 对所有项目页面生效，spec §15.6.3）；事件到达按 domain 分派到既有加载方法
 * 全量重拉（模板 / 设置 / 模型注册表 + modelReadiness / Agent 池），重连兜底（event=null）全刷。
 *
 * mock：src/api/event-stream（捕获回调手动驱动）+ src/api/client（apiFetch / fetchSettings 等）
 * + 有副作用的 api 模块（vector / config）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, render, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { SettingsPage } from './settings';
import { apiFetch, fetchSettings, type AppSettings } from '../api/client';
import { subscribeDataChanges, type DataChangeFrame } from '../api/event-stream';
import { useKernelStore } from '../stores/kernel';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';

const {
  patchSettingsMock,
  fetchDataDirMock,
  updateDataDirMock,
  fetchMcpInfoMock,
  fetchConfigMock,
  patchConfigMock,
  fetchVectorStatusMock,
  postVectorReindexMock,
  putEmbeddingModelMock,
} = vi.hoisted(() => ({
  patchSettingsMock: vi.fn(),
  fetchDataDirMock: vi.fn(),
  updateDataDirMock: vi.fn(),
  fetchMcpInfoMock: vi.fn(),
  fetchConfigMock: vi.fn(),
  patchConfigMock: vi.fn(),
  fetchVectorStatusMock: vi.fn(),
  postVectorReindexMock: vi.fn(),
  putEmbeddingModelMock: vi.fn(),
}));

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return {
    ...actual,
    apiFetch: vi.fn(),
    fetchSettings: vi.fn(),
    patchSettings: patchSettingsMock,
    fetchDataDir: fetchDataDirMock,
    updateDataDir: updateDataDirMock,
    fetchMcpInfo: fetchMcpInfoMock,
  };
});

vi.mock('../api/vector', () => ({
  fetchVectorStatus: fetchVectorStatusMock,
  postVectorReindex: postVectorReindexMock,
  putEmbeddingModel: putEmbeddingModelMock,
}));

vi.mock('../api/config', () => ({
  fetchConfig: fetchConfigMock,
  patchConfig: patchConfigMock,
}));

vi.mock('../api/event-stream', () => ({ subscribeDataChanges: vi.fn() }));

const apiFetchMock = vi.mocked(apiFetch);
const fetchSettingsMock = vi.mocked(fetchSettings);
const subscribeMock = vi.mocked(subscribeDataChanges);

const projectP1 = {
  id: 'p1', name: '青云志', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, config: {},
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};

const APP_SETTINGS: AppSettings = {
  theme: 'paper', bg: 'default', lang: 'zh', font: 'sans',
  close_behavior: 'tray', tray_hint_dismissed: false, default_words: 800000,
  kg_extract_enabled: false, kg_extract_interval_hours: 24, kg_extract_method: 'rule',
};

let emit: (ev: DataChangeFrame) => void;
let resync: () => void;

function ev(patch: Partial<DataChangeFrame> = {}): DataChangeFrame {
  return { domain: 'agent_template', op: 'update', resource_id: '1', source: 'cli', ...patch };
}

function fetchCount(path: string): number {
  return apiFetchMock.mock.calls.filter((c) => String(c[0]).split('?')[0] === path).length;
}

async function emitAndSettle(frame: DataChangeFrame): Promise<void> {
  await act(async () => {
    emit(frame);
    await new Promise((resolve) => setTimeout(resolve, 400));
  });
}

async function triggerResync(): Promise<void> {
  await act(async () => {
    resync();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function renderAndSubscribe(): Promise<void> {
  render(
    <MemoryRouter initialEntries={['/settings']}>
      <SettingsPage />
    </MemoryRouter>,
  );
  await waitFor(() => expect(subscribeMock).toHaveBeenCalled());
  // 冲刷挂载期在途请求（GeneralPanel fetchSettings / 主题初始化）→ 避免测试收尾 act 警告
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

/** 四个数据面端点的当前拉取快照（用于断言「恰好某一路被重拉」） */
function snapshot(): Record<string, number> {
  return {
    templates: fetchCount('/api/v1/agent-templates'),
    providers: fetchCount('/api/v1/provider-configs'),
    readiness: fetchCount('/api/v1/settings/model-readiness'),
    agents: fetchCount('/api/v1/agents'),
    settings: fetchSettingsMock.mock.calls.length,
  };
}

beforeEach(() => {
  apiFetchMock.mockReset();
  fetchSettingsMock.mockReset();
  fetchSettingsMock.mockResolvedValue(APP_SETTINGS);
  patchSettingsMock.mockReset();
  fetchDataDirMock.mockReset();
  updateDataDirMock.mockReset();
  fetchMcpInfoMock.mockReset();
  fetchConfigMock.mockReset();
  fetchConfigMock.mockResolvedValue({});
  patchConfigMock.mockReset();
  fetchVectorStatusMock.mockReset();
  postVectorReindexMock.mockReset();
  putEmbeddingModelMock.mockReset();
  subscribeMock.mockReset();
  emit = () => {};
  resync = () => {};
  subscribeMock.mockImplementation(async (onEvent, _onError, onReconnect) => {
    emit = onEvent;
    resync = onReconnect ?? (() => {});
    return () => {};
  });
  localStorage.clear();
  useKernelStore.setState({ status: 'ready', booted: true, healthFailures: 0 });
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({
    projects: [projectP1],
    currentProjectId: 'p1',
    loading: false,
    error: null,
  });
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/agent-templates') return { items: [], total: 0 };
    if (path === '/api/v1/provider-configs') return { items: [] };
    if (path === '/api/v1/agents') return { items: [] };
    if (path === '/api/v1/settings/model-readiness') {
      return { ready: false, has_chat_model: false, has_embedding_model: false, reason: 'no_provider' };
    }
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

afterEach(() => {
  useKernelStore.setState({ status: 'booting', booted: false, healthFailures: 0 });
});

describe('设置页 — 全局域数据面变更订阅（F23 §15.6.2/§15.6.3 / #1088 A3）', () => {
  it('agent_template 事件 → 仅重拉模板列表（#989 used_by 服务端权威重取）', async () => {
    await renderAndSubscribe();
    const before = snapshot();

    await emitAndSettle(ev({ domain: 'agent_template' }));

    const after = snapshot();
    expect(after.templates).toBeGreaterThan(before.templates);
    expect(after.providers).toBe(before.providers);
    expect(after.agents).toBe(before.agents);
  });

  it('provider_config 事件 → 重拉模型注册表 + modelReadiness', async () => {
    await renderAndSubscribe();
    const before = snapshot();

    await emitAndSettle(ev({ domain: 'provider_config' }));

    const after = snapshot();
    expect(after.providers).toBeGreaterThan(before.providers);
    expect(after.readiness).toBeGreaterThan(before.readiness);
    expect(after.templates).toBe(before.templates);
  });

  it('agent 事件 → 重拉 Agent 池（AgentList / AgentChainCard 共用 store）', async () => {
    await renderAndSubscribe();
    const before = snapshot();

    await emitAndSettle(ev({ domain: 'agent' }));

    expect(snapshot().agents).toBeGreaterThan(before.agents);
  });

  it('settings 事件 → 重拉全局设置（fetchSettings）', async () => {
    await renderAndSubscribe();
    const before = snapshot();

    await emitAndSettle(ev({ domain: 'settings' }));

    expect(snapshot().settings).toBeGreaterThan(before.settings);
  });

  it('重连兜底（event=null）→ 四路全量重拉', async () => {
    await renderAndSubscribe();
    const before = snapshot();

    await triggerResync();

    const after = snapshot();
    expect(after.templates).toBeGreaterThan(before.templates);
    expect(after.providers).toBeGreaterThan(before.providers);
    expect(after.agents).toBeGreaterThan(before.agents);
    expect(after.settings).toBeGreaterThan(before.settings);
  });

  it('反例：self-originated（source=gui）不触发任何重拉', async () => {
    await renderAndSubscribe();
    const before = snapshot();

    await emitAndSettle(ev({ domain: 'agent_template', source: 'gui' }));

    expect(snapshot()).toEqual(before);
  });

  it('反例：未登记的 domain（map，项目域）不触发本页重拉', async () => {
    await renderAndSubscribe();
    const before = snapshot();

    await emitAndSettle(ev({ domain: 'map', project_id: 'p1' }));

    expect(snapshot()).toEqual(before);
  });
});
