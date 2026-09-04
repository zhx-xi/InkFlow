/**
 * #658 记忆统计概览 — 独立测试文件（B6 #803：从 memory.test.tsx 拆分）。
 *
 * 覆盖「记忆页 — 统计概览（#658）」describe：有项目挂载调用 fetchMemoryStats、
 * 渲染数字卡（total/project-prefs/user-prefs/summaries + agentic 明细）、
 * 统计加载失败降级不阻断页面、空态 total=0。
 *
 * 自带全套 mock 基建：vi.mock('../api/memory') 提供记忆页全部 API 函数 + 真 store
 * （useProjectStore / useThemeStore）+ seedProjects / renderMemoryPage helper
 * （与 memory.test.tsx 契约实现一致，拆分后本文件独立可跑）。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { MemoryPage } from './memory';
import {
  fetchMemoryStats,
  fetchMemorySummaries,
  fetchProjectPreferences,
  fetchUserPreferences,
} from '../api/memory';
import { useProjectStore, type Project } from '../stores/project';
import { useThemeStore } from '../stores/theme';

vi.mock('../api/memory', () => ({
  fetchMemoryStats: vi.fn(),
  fetchMemorySummaries: vi.fn(),
  summarizeMemory: vi.fn(),
  fetchProjectPreferences: vi.fn(),
  removeProjectPreference: vi.fn(),
  fetchUserPreferences: vi.fn(),
  removeUserPreference: vi.fn(),
  createProjectPreference: vi.fn(),
  createUserPreference: vi.fn(),
  updateProjectPreference: vi.fn(),
  updateUserPreference: vi.fn(),
  removeMemorySummary: vi.fn(),
}));

const fetchMemoryStatsMock = vi.mocked(fetchMemoryStats);
const fetchMemorySummariesMock = vi.mocked(fetchMemorySummaries);
const fetchProjectPreferencesMock = vi.mocked(fetchProjectPreferences);
const fetchUserPreferencesMock = vi.mocked(fetchUserPreferences);

/** #658 契约：记忆统计响应镜像（GREEN 从 api/memory.ts 导出 MemoryStatsResponse） */
interface MemoryStatsResponse {
  project_id: string;
  agentic: {
    chapters: number;
    direct_confirms: number;
    avg_diff_chars: number;
    modify_rate: number;
    regenerate_rate: number;
  };
  learned_preferences: number;
  baseline_ref: string;
  user_preferences?: { count: number; projects: number } | null;
}

/** #658 统计 total 依赖 summaries.project/user 是否存在；镜像 memory.test.tsx 契约结构 */
interface MemorySummaryDto {
  content: string;
  anchor_hash: string;
  anchor_count: number;
  model: string;
  updated_at: string;
}

interface MemorySummariesResponse {
  project_id: string;
  project: MemorySummaryDto | null;
  user: MemorySummaryDto | null;
}

let summaries: MemorySummariesResponse;
let memoryStats: MemoryStatsResponse;

const summaryContent = '用户偏好使用「低声道」替代「说」，主角称呼为林晚。';

function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: 'p1',
    name: '青云志',
    tags: ['玄幻'],
    language: 'zh-CN',
    target_words: 800000,
    config: {},
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-08-05T10:00:00Z',
    ...overrides,
  };
}

function seedProjects(currentProjectId: string | null = 'p1') {
  useProjectStore.setState({
    projects: [makeProject(), makeProject({ id: 'p2', name: '山海经' })],
    currentProjectId,
    loading: false,
    error: null,
  });
}

function renderMemoryPage() {
  return render(
    <MemoryRouter>
      <MemoryPage />
      <Routes>
        <Route path="/projects" element={<div data-testid="projects-probe" />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });

  summaries = {
    project_id: 'p1',
    project: {
      content: summaryContent,
      anchor_hash: 'abc123',
      anchor_count: 3,
      model: 'deepseek-v4-flash',
      updated_at: '2026-08-10T08:00:00Z',
    },
    user: null,
  };
  memoryStats = {
    project_id: 'p1',
    agentic: {
      chapters: 10,
      direct_confirms: 3,
      avg_diff_chars: 48,
      modify_rate: 0.34,
      regenerate_rate: 0.2,
    },
    learned_preferences: 3,
    baseline_ref: 'design/agent-baseline-2026-08-10.md',
    user_preferences: { count: 5, projects: 2 },
  };

  fetchMemoryStatsMock.mockReset();
  fetchMemorySummariesMock.mockReset();
  fetchProjectPreferencesMock.mockReset();
  fetchUserPreferencesMock.mockReset();

  fetchMemoryStatsMock.mockImplementation(async () => ({
    ...memoryStats,
    agentic: { ...memoryStats.agentic },
    user_preferences: memoryStats.user_preferences
      ? { ...memoryStats.user_preferences }
      : null,
  }));
  fetchMemorySummariesMock.mockImplementation(async () => ({
    ...summaries,
    project: summaries.project ? { ...summaries.project } : null,
    user: summaries.user ? { ...summaries.user } : null,
  }));
  fetchProjectPreferencesMock.mockImplementation(async () => ({ items: [], total: 0 }));
  fetchUserPreferencesMock.mockImplementation(async () => ({ items: [], total: 0 }));
});

describe('记忆页 — 统计概览（#658）', () => {
  it('有项目挂载 → fetchMemoryStats(pid) 被调用', async () => {
    seedProjects();
    renderMemoryPage();
    await screen.findByTestId('memory-stats-section');
    expect(fetchMemoryStatsMock).toHaveBeenCalledWith('p1');
  });

  it('渲染概览数字卡（total=learned+user+总结 / 项目偏好 / 用户偏好 / agentic 明细）', async () => {
    seedProjects();
    renderMemoryPage();
    await screen.findByTestId('memory-stats-section');

    // total = learned_preferences 3 + user_preferences.count 5 + 语义总结 1（summaries.project 存在）= 9
    expect(screen.getByTestId('memory-stats-total')).toHaveTextContent('9');
    expect(screen.getByTestId('memory-stats-project-prefs')).toHaveTextContent('3');
    expect(screen.getByTestId('memory-stats-user-prefs')).toHaveTextContent('5');
    expect(screen.getByTestId('memory-stats-summaries')).toHaveTextContent('1');
    // agentic 明细（modify/regenerate 以百分比展示）
    expect(screen.getByTestId('memory-stats-chapters')).toHaveTextContent('10');
    expect(screen.getByTestId('memory-stats-direct-confirms')).toHaveTextContent('3');
    expect(screen.getByTestId('memory-stats-modify-rate')).toHaveTextContent('34%');
    expect(screen.getByTestId('memory-stats-regenerate-rate')).toHaveTextContent('20%');
    expect(screen.getByTestId('memory-stats-avg-diff-chars')).toHaveTextContent('48');
  });

  it('统计加载失败降级：页面不阻断（总结照常渲染）+ memory-stats-unavailable 弱提示', async () => {
    fetchMemoryStatsMock.mockRejectedValue(new Error('503'));
    seedProjects();
    renderMemoryPage();
    // 统计失败不影响总结/偏好区块（页面仍完整可用）
    expect(await screen.findByTestId('memory-summary-card')).toBeInTheDocument();
    expect(await screen.findByTestId('memory-stats-unavailable')).toBeInTheDocument();
  });

  it('空态：stats 全 0 且无总结 → memory-stats-total 显示 0', async () => {
    memoryStats = {
      project_id: 'p1',
      agentic: {
        chapters: 0,
        direct_confirms: 0,
        avg_diff_chars: 0,
        modify_rate: 0,
        regenerate_rate: 0,
      },
      learned_preferences: 0,
      baseline_ref: 'design/agent-baseline-2026-08-10.md',
      user_preferences: null,
    };
    // 无总结 → 总数 0（与 total=learned+user+总结数 的契约一致）
    summaries.project = null;
    summaries.user = null;
    seedProjects();
    renderMemoryPage();
    expect(await screen.findByTestId('memory-stats-total')).toHaveTextContent('0');
  });
});
