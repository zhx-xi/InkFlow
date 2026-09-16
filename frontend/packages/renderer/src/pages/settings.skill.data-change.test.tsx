/**
 * 设置页 — Skill 域数据面变更订阅接线（F23 §15.6.2 / #1090 批次 B）
 *
 * 契约（父侧设计裁定表 §3）：SETTINGS_DATA_CHANGE_DOMAINS 追加 'skill'（全局域，
 * project_id 缺省 = 对所有项目页面生效，§15.6.3）；订阅回调新增分支
 * `if (domain === null || domain === 'skill') { useSkillsStore.loadSkills();
 * useAgentsStore.loadSkills(); }` —— 两个 store 都刷（SkillList 读 useSkillsStore、
 * AgentList 读 useAgentsStore 的技能池），二者的 loadSkills 均打 GET /api/v1/skills
 * （stores/skills.ts:57 / stores/agents.ts:154）→ 以该端点 fetch 计数作为失效动作观测面。
 * 因此本契约不依赖 SkillList 重挂载（若 GREEN 走 remount 而非 store 重拉，本用例仍应 FAIL）。
 *
 * mock：src/api/event-stream（捕获 emit/resync 手动驱动）+ src/api/client 的 apiFetch（端点
 * 计数）+ 有副作用的 api 模块（vector / config）——镜像 settings.data-change.test.tsx 形态；
 * stores/skills + stores/agents 用**真 store**（loadSkills 即真实重拉路径）。
 * 订阅调度层自带 300ms 防抖 → 真实计时器等待（emitAndSettle 400ms）。
 *
 * ⚠️ RED 阶段 'skill' 未注册 → 事件被调度层丢弃 → /api/v1/skills 计数不增 → FAIL。
 * renderAndSubscribe 限时轮询后静默放行（不 assert 订阅建立），保证失败落在断言上。
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

const { patchSettingsMock, fetchDataDirMock, updateDataDirMock, fetchMcpInfoMock,
  fetchConfigMock, patchConfigMock, fetchVectorStatusMock, postVectorReindexMock,
  putEmbeddingModelMock } = vi.hoisted(() => ({
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

/** 技能池端点（skills store 与 agents store 的 loadSkills 共用） */
const SKILLS_PATH = '/api/v1/skills';

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
  // skill 为全局域：project_id 缺省
  return { domain: 'skill', op: 'create', resource_id: 'my-skill', source: 'cli', ...patch };
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

/** 驱动重连兜底（event=null，无防抖，立即投递） */
async function triggerResync(): Promise<void> {
  await act(async () => {
    resync();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function renderAndSubscribe(): Promise<void> {
  render(
    <MemoryRouter initialEntries={['/settings?cat=skills']}>
      <SettingsPage />
    </MemoryRouter>,
  );
  for (let i = 0; i < 50 && subscribeMock.mock.calls.length === 0; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
  }
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
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
    if (path === '/api/v1/agents') return { items: [], total: 0 };
    if (path === '/api/v1/skills') return { items: [], total: 0 };
    if (path === '/api/v1/settings/model-readiness') {
      return { ready: false, has_chat_model: false, has_embedding_model: false, reason: 'no_provider' };
    }
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

afterEach(() => {
  useKernelStore.setState({ status: 'booting', booted: false, healthFailures: 0 });
});

describe('设置页 — Skill 域订阅接线（F23 §15.6.2 / #1090 B）', () => {
  it('skill 事件（全局域）→ GET /api/v1/skills 全量重拉（SkillList / AgentList 两个 store 同刷）', async () => {
    await renderAndSubscribe();
    await waitFor(() => expect(fetchCount(SKILLS_PATH)).toBeGreaterThan(0));
    const before = fetchCount(SKILLS_PATH);

    await emitAndSettle(ev({ domain: 'skill', op: 'create', resource_id: 'my-skill' }));

    expect(fetchCount(SKILLS_PATH)).toBeGreaterThan(before);
  });

  it('反例：未登记的域（map，项目域）不触发技能池重拉', async () => {
    await renderAndSubscribe();
    await waitFor(() => expect(fetchCount(SKILLS_PATH)).toBeGreaterThan(0));
    const before = fetchCount(SKILLS_PATH);

    await emitAndSettle(ev({ domain: 'map', op: 'create', resource_id: 'm1', project_id: 'p1' }));

    expect(fetchCount(SKILLS_PATH)).toBe(before);
  });

  it('反例：self-originated（source=gui）不触发重拉', async () => {
    await renderAndSubscribe();
    await waitFor(() => expect(fetchCount(SKILLS_PATH)).toBeGreaterThan(0));
    const before = fetchCount(SKILLS_PATH);

    await emitAndSettle(ev({ domain: 'skill', source: 'gui' }));

    expect(fetchCount(SKILLS_PATH)).toBe(before);
  });

  it('重连兜底（event=null）→ 技能池全量重拉（回调 null 分支含 skill 重拉）', async () => {
    await renderAndSubscribe();
    await waitFor(() => expect(fetchCount(SKILLS_PATH)).toBeGreaterThan(0));
    const before = fetchCount(SKILLS_PATH);

    await triggerResync();

    expect(fetchCount(SKILLS_PATH)).toBeGreaterThan(before);
  });
});
