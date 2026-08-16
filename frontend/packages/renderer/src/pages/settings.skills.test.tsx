/**
 * 设置页 — Skill 管理分类 测试（F40 #259；拆分自 settings.test.tsx 的文件规模治理惯例）。
 *
 * 契约锚点（spec §8.3 settings.tsx MODIFY / §5.4）：
 * - 五分类导航新增「Skill 管理」分类（CatKey 'skills'，nav 按钮 settings-cat-skills）
 * - 点击 → SkillList 面板挂载（skill-list；GREEN 后挂载为 `{activeCat === 'skills' && <SkillList />}` 单行，无额外包装 div）
 * - 深链 /settings?cat=skills → 直接 Skill 面板
 *
 * 共享 mock 模式：本文件自含副本（#281 拆分惯例），SkillList/SkillUploadDialog 以假实现
 * 屏蔽（各自有独立契约测试文件）；stores/skills + stores/agents 假 store 保证 GREEN 后
 * settings.tsx 挂载 SkillsPanel 可运行。
 *
 * RED 预期：settings.tsx 尚无 'skills' 分类 → settings-cat-skills 不存在 → 断言失败（类 3
 * 行为缺口，suite 级失败形态：找不到元素）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { SettingsPage } from './settings';
import { apiFetch } from '../api/client';
import { useAgentStore } from '../stores/agent';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import { useToastStore } from '../stores/toast';

// 同 settings.test.tsx：vi.hoisted 替换 client.ts 模块内函数（patchSettings/fetchSettings）
const { fetchSettingsMock, patchSettingsMock } = vi.hoisted(() => ({
  fetchSettingsMock: vi.fn(),
  patchSettingsMock: vi.fn(),
}));
const { fetchDataDirMock, updateDataDirMock } = vi.hoisted(() => ({
  fetchDataDirMock: vi.fn(),
  updateDataDirMock: vi.fn(),
}));
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

vi.mock('../api/vector', () => ({
  fetchVectorStatus: vectorStatusMock,
  postVectorReindex: vectorReindexMock,
}));

// GREEN 创建的 stores/skills + stores/agents：假 store 保证 SettingsPage 挂载可运行
// （行为契约在各自测试文件断言；此处仅需面板渲染不炸）
vi.mock('../stores/skills', async () => {
  const { create } = await import('zustand');
  const { apiFetch } = await import('../api/client');
  const useSkillsStore = create(() => ({
    skills: [] as Array<{ id: number; name: string }>,
    loading: false,
    error: null,
    loadSkills: async () => {
      const data = await apiFetch<{ items: Array<{ id: number; name: string }>; total: number }>(
        '/api/v1/skills'
      );
      useSkillsStore.setState({ skills: data.items, loading: false, error: null });
    },
    uploadSkill: async () => ({ id: 0, name: '', description: '', content: '', source: 'user_upload', created_at: '', updated_at: '', agent_ids: [] }),
    deleteSkill: async () => {},
  }));
  return { useSkillsStore };
});

vi.mock('../stores/agents', async () => {
  const { create } = await import('zustand');
  const { apiFetch } = await import('../api/client');
  const useAgentsStore = create(() => ({
    agents: [] as Array<{ id: number; name: string; builtin: boolean }>,
    loading: false,
    error: null,
    loadAgents: async () => {
      const data = await apiFetch<{
        items: Array<{ id: number; name: string; builtin: boolean }>;
        total: number;
      }>('/api/v1/agents');
      useAgentsStore.setState({ agents: data.items, loading: false, error: null });
    },
    bindSkill: async () => {},
  }));
  return { useAgentsStore };
});

// 假 SkillList：面板挂载点（data-testid=skill-list + skill-add-btn 打开假 UploadDialog）
vi.mock('../components/SkillList', async () => {
  const React = await import('react');
  function SkillList() {
    return React.createElement(
      'div',
      { 'data-testid': 'skill-list' },
      React.createElement('button', { 'data-testid': 'skill-add-btn' }, '上传 Skill'),
    );
  }
  return { SkillList };
});

// 假 SkillUploadDialog：仅保证 settings.tsx import 不炸（契约测试在独立文件）
vi.mock('../components/SkillUploadDialog', async () => {
  const React = await import('react');
  function SkillUploadDialog(props: { open?: boolean; onOpenChange?: (open: boolean) => void }) {
    if (!props.open) return null;
    return React.createElement('div', { 'data-testid': 'skill-upload-dialog', role: 'dialog' });
  }
  return { SkillUploadDialog };
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
  patchSettingsMock.mockReset();
  patchSettingsMock.mockResolvedValue({
    theme: 'paper', bg: 'default', lang: 'zh', font: 'sans',
    close_behavior: 'tray', tray_hint_dismissed: false,
  });
  fetchSettingsMock.mockReset();
  fetchSettingsMock.mockResolvedValue({
    theme: 'paper', bg: 'default', lang: 'zh', font: 'sans',
    close_behavior: 'tray', tray_hint_dismissed: false, default_words: 800000,
  });
  useThemeStore.setState({
    theme: 'paper', bg: 'default', lang: 'zh',
  } as unknown as Partial<ReturnType<typeof useThemeStore.getState>>);
  useProjectStore.setState({
    projects: [{ id: 'p1', name: '青云志', genre: '玄幻', language: 'zh-CN', target_words: 800000, config: {}, created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z' }],
    currentProjectId: 'p1', loading: false, error: null,
  });
  useAgentStore.setState({ config: {}, apiKeyDraft: '', testStatus: 'idle', testMessage: null });
  useToastStore.setState({ toasts: [] });
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/provider-configs') {
      return { items: [], total: 0, offset: 0, limit: 50 };
    }
    if (path === '/api/v1/skills') return { items: [], total: 0 };
    if (path === '/api/v1/agents') return { items: [], total: 0 };
    return { ok: true };
  });
});

describe('设置页 — Skill 管理分类（F40 #259）', () => {
  it('五分类导航出现「Skill 管理」按钮', () => {
    renderSettings();
    const nav = screen.getByTestId('settings-nav');
    expect(within(nav).getByTestId('settings-cat-skills')).toBeInTheDocument();
    expect(within(nav).getByRole('button', { name: 'Skill 管理' })).toBeInTheDocument();
  });

  it('点击 Skill 管理 → SkillList 面板挂载 + 常规面板卸载', async () => {
    const user = userEvent.setup();
    renderSettings();
    await user.click(screen.getByTestId('settings-cat-skills'));
    expect(await screen.findByTestId('skill-list')).toBeInTheDocument();
    expect(screen.queryByRole('radio')).not.toBeInTheDocument();
  });

  it('深链直达：/settings?cat=skills → 初始 Skill 面板', () => {
    renderSettings('/settings?cat=skills');
    expect(screen.getByTestId('skill-list')).toBeInTheDocument();
  });
});
