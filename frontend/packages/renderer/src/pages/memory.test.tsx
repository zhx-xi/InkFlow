/**
 * #486 会话/记忆 UI — 记忆页（语义总结展示 + 提取记忆 + 偏好管理）RED 阶段契约测试
 *
 * ⚠️ 本文件 = 契约。GREEN 新建 src/pages/memory.tsx（命名导出 MemoryPage），必须匹配：
 *
 * 接线（Mock 依赖）：
 * - MemoryPage 必须 import 自 '../api/memory'：fetchMemorySummaries /
 *   summarizeMemory / fetchProjectPreferences / removeProjectPreference /
 *   fetchUserPreferences / removeUserPreference（本文件 vi.mock 该模块）
 * - 项目上下文来自 useProjectStore（currentProjectId 缺省 = 空态引导去项目页）
 * - 挂载（有项目）并行加载：fetchMemorySummaries(pid) + fetchProjectPreferences(pid)
 *   + fetchUserPreferences()；currentProjectId 变化 → 重拉项目级数据
 * - 提取记忆：点击 → summarizeMemory(pid, true)（本轨拍板 force=true——用户显式
 *   点击「提取记忆」= 强制重新提取；锚点幂等语义由后端处理）
 *   → 完成后重拉/本地更新 summaries（测试用状态化共享对象，两种实现最终态一致）；
 *   失败（语义总结 502）→ memory-extract-error 展示 errorMessage
 * - 删除偏好：点删除 → removeProjectPreference(id) / removeUserPreference(id) → 行消失
 *
 * data-testid 即契约：
 * - memory-page 根容器
 * - memory-no-project 无项目空态 + memory-go-projects（跳 /projects）
 * - memory-project-select 项目选择（Radix Select：SelectTrigger 落点；选项来自
 *   useProjectStore.projects，可访问名 = 项目名）
 * - 语义总结区块：memory-summary-section；memory-summary-card（项目级总结卡片）：
 *   memory-summary-content（content 文本）、memory-summary-meta（updated_at/model 类）；
 *   memory-summary-expand 展开按钮（长文本时才渲染，测试不锁细节）；空态
 *   memory-summary-empty（project 与 user 均 null）；memory-summary-user（用户级总结
 *   存在时渲染，含 memory-summary-user-content）
 * - 提取入口：memory-extract-btn（文案 t('memory.extract')='提取记忆'）；
 *   提取中 memory-extract-loading（禁用态）；错误 memory-extract-error
 * - 项目偏好区块：memory-prefs-section；行 memory-pref-<id>：行内
 *   memory-pref-cat-<id>（category 文案）、memory-pref-pattern-<id>、
 *   memory-pref-value-<id>、memory-pref-count-<id>（count）、
 *   memory-pref-conf-<id>（confidence）、删除按钮 memory-pref-del-<id>；
 *   空态 memory-prefs-empty
 * - 用户级偏好区块：memory-userprefs-section；行 memory-userpref-<id>：行内
 *   memory-userpref-cat-<id> / memory-userpref-pattern-<id> /
 *   memory-userpref-value-<id> / 删除按钮 memory-userpref-del-<id>；空态
 *   memory-userprefs-empty
 *
 * i18n key（GREEN 补 zh.ts/en.ts）：
 * memory.title='记忆' memory.noProject='请先创建或选择项目'
 * memory.goProjects='前往项目页' memory.project.label='项目'
 * memory.summary.title='语义总结' memory.summary.empty='尚未提取记忆'
 * memory.summary.userLabel='用户级总结' memory.extract='提取记忆'
 * memory.extract.loading='提取中…' memory.extract.error='提取失败，请检查模型配置'
 * memory.prefs.title='项目偏好' memory.prefs.empty='暂无已学偏好'
 * memory.userPrefs.title='用户级偏好' memory.userPrefs.empty='暂无用户级偏好'
 * memory.prefs.delete='删除' memory.cat.addressing='称呼' memory.cat.style_word='用词'
 * memory.cat.structure='结构' memory.cat.other='其他'
 * memory.cat.user.addressing='称呼' memory.cat.user.style_word='用词'
 * memory.cat.user.structure='结构' memory.cat.user.other='其他'
 *
 * #521 手动添加/编辑记忆契约（2026-08-20 拍板，GREEN 必须实现）：
 * - 「添加记忆」按钮 memory-add-btn（文案 t('memory.add.title')='添加记忆'），
 *   点击展开表单容器 memory-add-form
 * - 表单字段（testid 即契约，label/placeholder GREEN 自定）：
 *   memory-add-scope（作用域 Select：项目级/全局级，默认项目级）
 *   memory-add-category（分类 Select：addressing | style_word | structure | other）
 *   memory-add-pattern（模式输入）、memory-add-value（偏好值输入）
 *   memory-add-submit（提交）、memory-add-cancel（取消）
 * - scope=全局级 → 渲染 memory-add-user-hint（t('memory.add.user.hint')，用户级偏好影响所有项目——spec §5.3 注入语义）
 * - 提交：项目级 → createProjectPreference(pid, { category, pattern, value }) →
 *   项目偏好列表出现新行；全局级 → createUserPreference(input) → 用户级列表新行
 * - 编辑入口：行内 memory-pref-edit-<id> / memory-userpref-edit-<id>（删除按钮旁），
 *   点击 → 表单出现且预填该行 pattern/value/category（编辑态作用域固定）→ 提交 →
 *   updateProjectPreference(id, {...}) / updateUserPreference(id, {...}) → 行更新
 * - 取消：关闭表单且不调任何 create/update API
 * - i18n key（GREEN 补 zh/en）：memory.add.title / memory.add.scope.label /
 *   memory.add.scope.project / memory.add.scope.user / memory.add.category.label /
 *   memory.add.pattern.label / memory.add.value.label / memory.add.submit /
 *   memory.add.cancel / memory.add.user.hint / memory.prefs.edit（='编辑'）
 *
 * #F49 记忆衰减 ③GUI（2026-08-24）：
 * - 删除语义总结：summaries.project 存在时渲染删除按钮 memory-summary-delete；
 *   点击 → removeMemorySummary(pid)（本文件 vi.mock 工厂已加）→ 成功后卡片消失
 *   （memory-summary-card 不再渲染；project/user 均 null → memory-summary-empty）
 *   + 成功 toast（type='ok'；失败 → type='err' 且卡片仍在）
 * - 被覆盖/降权状态（Q3=A：list 展示全部含 superseded）：项目偏好行 superseded_by
 *   非空 → 渲染 memory-pref-superseded-<id> 标记 + memory-pref-superseded-by-<id>
 *   显示被取代的偏好 id；superseded_by='' → 不渲染标记；用户级同理
 *   memory-userpref-superseded-<id> / memory-userpref-superseded-by-<id>
 * - 类型扩展（GREEN src/api/memory.ts）：ProjectPreferenceDto / UserPreferenceDto
 *   追加必填 superseded_by: string（后端 list 已含，'' = 未被取代）
 * - i18n key（GREEN 补 zh/en）：memory.summary.delete='删除'
 *   memory.summary.deleteSuccess='已删除语义总结' memory.prefs.superseded='被覆盖'
 *
 * #658 记忆统计概览（2026-08-25）：
 * - MemoryPage 必须 import fetchMemoryStats 自 '../api/memory'（vi.mock 工厂已加）；
 *   有项目挂载时调用 fetchMemoryStats(pid)（GET /api/v1/agent/memory/stats）
 * - 页面顶部「统计概览」区块 memory-stats-section：数字卡 memory-stats-total
 *   （= learned_preferences + user_preferences.count + 语义总结数）、
 *   memory-stats-project-prefs、memory-stats-user-prefs、memory-stats-summaries
 *   + agentic 明细卡 memory-stats-chapters / memory-stats-direct-confirms /
 *   memory-stats-modify-rate（百分比）/ memory-stats-regenerate-rate（百分比）/
 *   memory-stats-avg-diff-chars
 * - 统计加载失败不阻断页面（总结/偏好照常渲染）：memory-stats-unavailable 弱提示
 * - 用户级偏好行内详情升级：memory-userpref-count-<id>（count）/
 *   memory-userpref-conf-<id>（confidence）/ memory-userpref-projects-<id>（project_count）
 *
 * RED 预期：./memory 模块不存在 → 收集期 module-not-found（类 1 契约缺口）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { MemoryPage } from './memory';
import {
  createProjectPreference,
  createUserPreference,
  fetchMemoryStats,
  fetchMemorySummaries,
  fetchProjectPreferences,
  fetchUserPreferences,
  removeMemorySummary,
  removeProjectPreference,
  removeUserPreference,
  summarizeMemory,
  updateProjectPreference,
  updateUserPreference,
} from '../api/memory';
import { useProjectStore, type Project } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import { useToastStore } from '../stores/toast';

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
const summarizeMemoryMock = vi.mocked(summarizeMemory);
const fetchProjectPreferencesMock = vi.mocked(fetchProjectPreferences);
const removeProjectPreferenceMock = vi.mocked(removeProjectPreference);
const fetchUserPreferencesMock = vi.mocked(fetchUserPreferences);
const removeUserPreferenceMock = vi.mocked(removeUserPreference);
const createProjectPreferenceMock = vi.mocked(createProjectPreference);
const createUserPreferenceMock = vi.mocked(createUserPreference);
const updateProjectPreferenceMock = vi.mocked(updateProjectPreference);
const updateUserPreferenceMock = vi.mocked(updateUserPreference);
const removeMemorySummaryMock = vi.mocked(removeMemorySummary);

/** 契约结构镜像（GREEN 类型从 api/memory.ts 导出） */
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

interface ProjectPreferenceDto {
  id: string;
  project_id: string;
  category: string;
  pattern: string;
  value: string;
  confidence: number;
  count: number;
  source_events: string[];
  created_at: string;
  updated_at: string;
  /** #F49：被取代的偏好 id（'' = 未被取代；GUI 渲染「被覆盖」标记） */
  superseded_by: string;
}

interface UserPreferenceDto {
  id: string;
  category: string;
  pattern: string;
  value: string;
  confidence: number;
  count: number;
  project_count: number;
  source_projects: string[];
  source_events: string[];
  created_at: string;
  updated_at: string;
  /** #F49：被取代的偏好 id（'' = 未被取代；GUI 渲染「被覆盖」标记） */
  superseded_by: string;
}

/** #521 契约：手动添加/编辑偏好输入（GREEN 从 api/memory.ts 导出 PreferenceInput） */
interface PreferenceInput {
  category: string;
  pattern: string;
  value: string;
}

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

let summaries: MemorySummariesResponse;
let prefs: ProjectPreferenceDto[];
let userPrefs: UserPreferenceDto[];
let memoryStats: MemoryStatsResponse;

const summaryContent = '用户偏好使用「低声道」替代「说」，主角称呼为林晚。';
const extractedContent = '提取后：用户偏好「林晚」「低声道」，段落结构三段式。';

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
  prefs = [
    {
      id: 'pref-1',
      project_id: 'p1',
      category: 'style_word',
      pattern: '说',
      value: '低声道',
      confidence: 0.75,
      count: 3,
      source_events: ['ev1'],
      created_at: '2026-08-10T08:00:00Z',
      updated_at: '2026-08-10T08:00:00Z',
      superseded_by: '',
    },
  ];
  userPrefs = [
    {
      id: 'upref-1',
      category: 'addressing',
      pattern: '她',
      value: '林晚',
      confidence: 0.8,
      count: 4,
      project_count: 2,
      source_projects: ['p1', 'p2'],
      source_events: ['ev1'],
      created_at: '2026-08-10T08:00:00Z',
      updated_at: '2026-08-10T08:00:00Z',
      superseded_by: '',
    },
  ];
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
    baseline_ref: 'docs/agent-baseline-2026-08-10.md',
    user_preferences: { count: 5, projects: 2 },
  };

  fetchMemoryStatsMock.mockReset();
  fetchMemorySummariesMock.mockReset();
  summarizeMemoryMock.mockReset();
  fetchProjectPreferencesMock.mockReset();
  removeProjectPreferenceMock.mockReset();
  fetchUserPreferencesMock.mockReset();
  removeUserPreferenceMock.mockReset();
  createProjectPreferenceMock.mockReset();
  createUserPreferenceMock.mockReset();
  updateProjectPreferenceMock.mockReset();
  updateUserPreferenceMock.mockReset();
  removeMemorySummaryMock.mockReset();

  // 状态化 mock：fetch* 读共享数组/对象；操作 mock 同步改写共享数据（两种实现最终态一致）
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
  summarizeMemoryMock.mockImplementation(async (pid: string) => {
    const s = {
      project_id: pid,
      summarized: true,
      project: {
        content: extractedContent,
        anchor_hash: 'def456',
        anchor_count: 5,
        model: 'deepseek-v4-flash',
        updated_at: '2026-08-11T08:00:00Z',
      },
      user: null,
    };
    summaries = { project_id: pid, project: s.project, user: null };
    return s;
  });
  fetchProjectPreferencesMock.mockImplementation(async () => ({
    items: prefs.map((p) => ({ ...p })),
    total: prefs.length,
  }));
  removeProjectPreferenceMock.mockImplementation(async (id: string) => {
    prefs = prefs.filter((p) => p.id !== id);
  });
  fetchUserPreferencesMock.mockImplementation(async () => ({
    items: userPrefs.map((p) => ({ ...p })),
    total: userPrefs.length,
  }));
  removeUserPreferenceMock.mockImplementation(async (id: string) => {
    userPrefs = userPrefs.filter((p) => p.id !== id);
  });
  // #521 状态化 mock：create* 往 prefs/userPrefs 追加带新 id 的项；update* 替换并返回新对象（本地更新/重拉两种实现最终态一致）
  createProjectPreferenceMock.mockImplementation(async (projectId: string, input: PreferenceInput) => {
    const created: ProjectPreferenceDto = {
      id: 'pref-new',
      project_id: projectId,
      category: input.category,
      pattern: input.pattern,
      value: input.value,
      confidence: 0.9,
      count: 1,
      source_events: [],
      created_at: '2026-08-20T08:00:00Z',
      updated_at: '2026-08-20T08:00:00Z',
      superseded_by: '',
    };
    prefs = [...prefs, created];
    return created;
  });
  createUserPreferenceMock.mockImplementation(async (input: PreferenceInput) => {
    const created: UserPreferenceDto = {
      id: 'upref-new',
      category: input.category,
      pattern: input.pattern,
      value: input.value,
      confidence: 0.9,
      count: 1,
      project_count: 1,
      source_projects: ['p1'],
      source_events: [],
      created_at: '2026-08-20T08:00:00Z',
      updated_at: '2026-08-20T08:00:00Z',
      superseded_by: '',
    };
    userPrefs = [...userPrefs, created];
    return created;
  });
  updateProjectPreferenceMock.mockImplementation(async (preferenceId: string, input: PreferenceInput) => {
    const existing = prefs.find((p) => p.id === preferenceId);
    const updated: ProjectPreferenceDto = {
      ...(existing ?? {
        id: preferenceId,
        project_id: 'p1',
        category: input.category,
        pattern: input.pattern,
        value: input.value,
        confidence: 0.5,
        count: 1,
        source_events: [],
        created_at: '2026-08-20T08:00:00Z',
        superseded_by: '',
      }),
      category: input.category,
      pattern: input.pattern,
      value: input.value,
      updated_at: '2026-08-20T09:00:00Z',
    };
    prefs = prefs.map((p) => (p.id === preferenceId ? updated : p));
    return updated;
  });
  updateUserPreferenceMock.mockImplementation(async (preferenceId: string, input: PreferenceInput) => {
    const existing = userPrefs.find((p) => p.id === preferenceId);
    const updated: UserPreferenceDto = {
      ...(existing ?? {
        id: preferenceId,
        category: input.category,
        pattern: input.pattern,
        value: input.value,
        confidence: 0.5,
        count: 1,
        project_count: 1,
        source_projects: [],
        source_events: [],
        created_at: '2026-08-20T08:00:00Z',
        superseded_by: '',
      }),
      category: input.category,
      pattern: input.pattern,
      value: input.value,
      updated_at: '2026-08-20T09:00:00Z',
    };
    userPrefs = userPrefs.map((p) => (p.id === preferenceId ? updated : p));
    return updated;
  });
  // #F49 状态化 mock：删除语义总结 → summaries.project 置 null（删除后走空态/无卡片两种实现最终态一致）
  removeMemorySummaryMock.mockImplementation(async () => {
    summaries = { project_id: summaries.project_id, project: null, user: null };
    return { project_id: summaries.project_id, deleted: true };
  });
});

describe('记忆页 — 无项目态', () => {
  it('projects 为空 → memory-no-project 引导 + 前往项目页按钮跳 /projects', async () => {
    const user = userEvent.setup();
    renderMemoryPage();
    expect(screen.getByTestId('memory-no-project')).toBeInTheDocument();
    expect(fetchMemorySummariesMock).not.toHaveBeenCalled();
    await user.click(screen.getByTestId('memory-go-projects'));
    expect(screen.getByTestId('projects-probe')).toBeInTheDocument();
  });
});

describe('记忆页 — 挂载加载与语义总结展示', () => {
  it('有项目挂载：三组加载 + 总结卡片渲染 content/meta', async () => {
    seedProjects();
    renderMemoryPage();
    expect(await screen.findByTestId('memory-summary-card')).toBeInTheDocument();
    expect(fetchMemorySummariesMock).toHaveBeenCalledWith('p1');
    expect(fetchProjectPreferencesMock).toHaveBeenCalledWith('p1');
    expect(fetchUserPreferencesMock).toHaveBeenCalled();

    expect(screen.getByTestId('memory-summary-content')).toHaveTextContent(summaryContent);
    expect(screen.getByTestId('memory-summary-meta')).toHaveTextContent('deepseek-v4-flash');
  });

  it('用户级总结存在 → memory-summary-user 渲染', async () => {
    summaries.user = {
      content: '全局：用户偏好短句与对话式表达',
      anchor_hash: 'u1',
      anchor_count: 2,
      model: 'deepseek-v4-flash',
      updated_at: '2026-08-10T08:00:00Z',
    };
    seedProjects();
    renderMemoryPage();
    expect(await screen.findByTestId('memory-summary-user')).toBeInTheDocument();
    expect(screen.getByTestId('memory-summary-user-content')).toHaveTextContent('短句与对话式表达');
  });

  it('project 与 user 均 null → memory-summary-empty', async () => {
    summaries.project = null;
    summaries.user = null;
    seedProjects();
    renderMemoryPage();
    expect(await screen.findByTestId('memory-summary-empty')).toBeInTheDocument();
  });
});

describe('记忆页 — 提取记忆', () => {
  it('点击提取 → summarizeMemory(pid, true) → 成功后 summary 内容更新', async () => {
    const user = userEvent.setup();
    seedProjects();
    renderMemoryPage();
    await screen.findByTestId('memory-summary-card');

    await user.click(screen.getByTestId('memory-extract-btn'));
    expect(summarizeMemoryMock).toHaveBeenCalledWith('p1', true);
    await waitFor(() => {
      expect(screen.getByTestId('memory-summary-content')).toHaveTextContent(extractedContent);
    });
  });

  it('提取失败（后端 502 语义）→ memory-extract-error 展示错误', async () => {
    const user = userEvent.setup();
    summarizeMemoryMock.mockRejectedValue(new Error('模型未配置'));
    seedProjects();
    renderMemoryPage();
    await screen.findByTestId('memory-summary-card');

    await user.click(screen.getByTestId('memory-extract-btn'));
    expect(await screen.findByTestId('memory-extract-error')).toHaveTextContent('模型未配置');
  });
});

describe('记忆页 — 偏好列表与删除', () => {
  it('项目偏好行渲染 pattern/value/category/count/confidence', async () => {
    seedProjects();
    renderMemoryPage();
    await screen.findByTestId('memory-prefs-section');

    const row = screen.getByTestId('memory-pref-pref-1');
    expect(within(row).getByTestId('memory-pref-cat-pref-1')).toHaveTextContent('用词');
    expect(within(row).getByTestId('memory-pref-pattern-pref-1')).toHaveTextContent('说');
    expect(within(row).getByTestId('memory-pref-value-pref-1')).toHaveTextContent('低声道');
    expect(within(row).getByTestId('memory-pref-count-pref-1')).toHaveTextContent('3');
    expect(within(row).getByTestId('memory-pref-conf-pref-1')).toHaveTextContent('0.75');
  });

  it('删除项目偏好 → removeProjectPreference(id) → 行消失', async () => {
    const user = userEvent.setup();
    seedProjects();
    renderMemoryPage();
    await screen.findByTestId('memory-prefs-section');

    await user.click(screen.getByTestId('memory-pref-del-pref-1'));
    expect(removeProjectPreferenceMock).toHaveBeenCalledWith('pref-1');
    await waitFor(() => {
      expect(screen.queryByTestId('memory-pref-pref-1')).not.toBeInTheDocument();
    });
  });

  it('用户级偏好渲染 + 删除', async () => {
    const user = userEvent.setup();
    seedProjects();
    renderMemoryPage();
    await screen.findByTestId('memory-userprefs-section');

    expect(screen.getByTestId('memory-userpref-value-upref-1')).toHaveTextContent('林晚');
    // #658：用户级偏好行内详情升级（count/confidence/project_count）
    expect(screen.getByTestId('memory-userpref-count-upref-1')).toHaveTextContent('4');
    expect(screen.getByTestId('memory-userpref-conf-upref-1')).toHaveTextContent('0.8');
    expect(screen.getByTestId('memory-userpref-projects-upref-1')).toHaveTextContent('2');
    await user.click(screen.getByTestId('memory-userpref-del-upref-1'));
    expect(removeUserPreferenceMock).toHaveBeenCalledWith('upref-1');
    await waitFor(() => {
      expect(screen.queryByTestId('memory-userpref-upref-1')).not.toBeInTheDocument();
    });
  });

  it('无偏好 → memory-prefs-empty / memory-userprefs-empty', async () => {
    prefs.length = 0;
    userPrefs.length = 0;
    seedProjects();
    renderMemoryPage();
    expect(await screen.findByTestId('memory-prefs-empty')).toBeInTheDocument();
    expect(await screen.findByTestId('memory-userprefs-empty')).toBeInTheDocument();
  });
});

describe('记忆页 — 手动添加/编辑记忆（#521）', () => {
  it('添加项目级偏好：展开表单（默认项目级）→ 填 addressing/她/林晚 → 提交 → 项目列表出现新行', async () => {
    const user = userEvent.setup();
    seedProjects();
    renderMemoryPage();
    await screen.findByTestId('memory-prefs-section');

    await user.click(screen.getByTestId('memory-add-btn'));
    expect(screen.getByTestId('memory-add-form')).toBeInTheDocument();
    // 默认作用域 = 项目级：作用域 Select 显示「项目级」且无用户级提示
    expect(screen.getByTestId('memory-add-scope')).toHaveTextContent('项目级');
    expect(screen.queryByTestId('memory-add-user-hint')).not.toBeInTheDocument();
    await user.click(screen.getByTestId('memory-add-category'));
    await user.click(await screen.findByRole('option', { name: '称呼' }));
    await user.type(screen.getByTestId('memory-add-pattern'), '她');
    await user.type(screen.getByTestId('memory-add-value'), '林晚');
    await user.click(screen.getByTestId('memory-add-submit'));

    expect(createProjectPreferenceMock).toHaveBeenCalledWith('p1', {
      category: 'addressing',
      pattern: '她',
      value: '林晚',
    });
    // 状态化 mock：create 同步追加 → 列表出现新行（本地更新/重拉两种实现最终态一致）
    await waitFor(() => {
      expect(screen.getByTestId('memory-pref-value-pref-new')).toHaveTextContent('林晚');
    });
  });

  it('添加全局级偏好：切作用域为全局级 → 出现用户级提示 → 提交 → 用户级列表出现新行', async () => {
    const user = userEvent.setup();
    seedProjects();
    renderMemoryPage();
    await screen.findByTestId('memory-userprefs-section');

    await user.click(screen.getByTestId('memory-add-btn'));
    await user.click(screen.getByTestId('memory-add-scope'));
    await user.click(await screen.findByRole('option', { name: '全局级' }));
    expect(screen.getByTestId('memory-add-user-hint')).toBeInTheDocument();

    await user.click(screen.getByTestId('memory-add-category'));
    await user.click(await screen.findByRole('option', { name: '用词' }));
    await user.type(screen.getByTestId('memory-add-pattern'), '说');
    await user.type(screen.getByTestId('memory-add-value'), '低声道');
    await user.click(screen.getByTestId('memory-add-submit'));

    expect(createUserPreferenceMock).toHaveBeenCalledWith({
      category: 'style_word',
      pattern: '说',
      value: '低声道',
    });
    await waitFor(() => {
      expect(screen.getByTestId('memory-userpref-value-upref-new')).toHaveTextContent('低声道');
    });
  });

  it('编辑项目偏好：点行内编辑 → 表单预填 pattern/value/category → 改 value 提交 → 行更新', async () => {
    const user = userEvent.setup();
    seedProjects();
    renderMemoryPage();
    await screen.findByTestId('memory-prefs-section');

    await user.click(screen.getByTestId('memory-pref-edit-pref-1'));
    expect(screen.getByTestId('memory-add-form')).toBeInTheDocument();
    // 编辑态预填当前行值（category 经 Select 文案回显）
    expect(screen.getByTestId('memory-add-category')).toHaveTextContent('用词');
    expect(screen.getByTestId('memory-add-pattern')).toHaveValue('说');
    expect(screen.getByTestId('memory-add-value')).toHaveValue('低声道');
    // 编辑态作用域固定为项目级（无用户级提示）
    expect(screen.queryByTestId('memory-add-user-hint')).not.toBeInTheDocument();

    await user.clear(screen.getByTestId('memory-add-value'));
    await user.type(screen.getByTestId('memory-add-value'), '轻声道');
    await user.click(screen.getByTestId('memory-add-submit'));

    expect(updateProjectPreferenceMock).toHaveBeenCalledWith('pref-1', {
      category: 'style_word',
      pattern: '说',
      value: '轻声道',
    });
    await waitFor(() => {
      expect(screen.getByTestId('memory-pref-value-pref-1')).toHaveTextContent('轻声道');
    });
  });

  it('编辑用户级偏好：点行内编辑 → 改 value 提交 → 行更新', async () => {
    const user = userEvent.setup();
    seedProjects();
    renderMemoryPage();
    await screen.findByTestId('memory-userprefs-section');

    await user.click(screen.getByTestId('memory-userpref-edit-upref-1'));
    expect(screen.getByTestId('memory-add-form')).toBeInTheDocument();
    expect(screen.getByTestId('memory-add-value')).toHaveValue('林晚');

    await user.clear(screen.getByTestId('memory-add-value'));
    await user.type(screen.getByTestId('memory-add-value'), '晚晚');
    await user.click(screen.getByTestId('memory-add-submit'));

    expect(updateUserPreferenceMock).toHaveBeenCalledWith('upref-1', {
      category: 'addressing',
      pattern: '她',
      value: '晚晚',
    });
    await waitFor(() => {
      expect(screen.getByTestId('memory-userpref-value-upref-1')).toHaveTextContent('晚晚');
    });
  });

  it('取消：点添加 → 点取消 → 表单关闭且不调任何 create/update API', async () => {
    const user = userEvent.setup();
    seedProjects();
    renderMemoryPage();
    await screen.findByTestId('memory-prefs-section');

    await user.click(screen.getByTestId('memory-add-btn'));
    expect(screen.getByTestId('memory-add-form')).toBeInTheDocument();
    await user.click(screen.getByTestId('memory-add-cancel'));
    expect(screen.queryByTestId('memory-add-form')).not.toBeInTheDocument();

    expect(createProjectPreferenceMock).not.toHaveBeenCalled();
    expect(createUserPreferenceMock).not.toHaveBeenCalled();
    expect(updateProjectPreferenceMock).not.toHaveBeenCalled();
    expect(updateUserPreferenceMock).not.toHaveBeenCalled();
  });

  it('添加记忆表单为弹框（role=dialog，#546：内联表单改 Dialog）', async () => {
    const user = userEvent.setup();
    seedProjects();
    renderMemoryPage();
    await screen.findByTestId('memory-prefs-section');

    await user.click(screen.getByTestId('memory-add-btn'));
    const form = screen.getByTestId('memory-add-form');
    expect(form).toBeInTheDocument();
    // #546：添加记忆必须是弹框（role=dialog）而非内联展开
    expect(form).toHaveAttribute('role', 'dialog');
  });
});

describe('记忆页 — F49 记忆衰减（删除语义总结 / 被覆盖状态）', () => {
  it('有项目总结 → 渲染删除按钮；点击 → removeMemorySummary(p1) → 卡片消失 + 空态 + 成功 toast', async () => {
    const user = userEvent.setup();
    seedProjects();
    renderMemoryPage();
    await screen.findByTestId('memory-summary-card');

    expect(screen.getByTestId('memory-summary-delete')).toBeInTheDocument();
    await user.click(screen.getByTestId('memory-summary-delete'));

    expect(removeMemorySummaryMock).toHaveBeenCalledWith('p1');
    await waitFor(() => {
      expect(screen.queryByTestId('memory-summary-card')).not.toBeInTheDocument();
    });
    // project/user 均 null → 空态（删除后最终态一致）
    expect(await screen.findByTestId('memory-summary-empty')).toBeInTheDocument();
    // 成功反馈 toast（type='ok'）
    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts[toasts.length - 1].type).toBe('ok');
    });
  });

  it('无项目总结（project=null）→ 不渲染删除按钮', async () => {
    summaries.project = null;
    seedProjects();
    renderMemoryPage();
    await screen.findByTestId('memory-summary-empty');
    expect(screen.queryByTestId('memory-summary-delete')).not.toBeInTheDocument();
  });

  it('删除失败 → 错误 toast（type=err）且卡片仍在', async () => {
    const user = userEvent.setup();
    removeMemorySummaryMock.mockRejectedValue(new Error('删除失败'));
    seedProjects();
    renderMemoryPage();
    await screen.findByTestId('memory-summary-card');

    await user.click(screen.getByTestId('memory-summary-delete'));
    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts[toasts.length - 1].type).toBe('err');
    });
    expect(screen.getByTestId('memory-summary-card')).toBeInTheDocument();
  });

  it('项目偏好 superseded_by 非空 → 渲染「被覆盖」标记 + 显示被取代偏好 id', async () => {
    prefs[0] = { ...prefs[0], superseded_by: 'pref-2' };
    seedProjects();
    renderMemoryPage();
    await screen.findByTestId('memory-prefs-section');

    expect(screen.getByTestId('memory-pref-superseded-pref-1')).toBeInTheDocument();
    expect(screen.getByTestId('memory-pref-superseded-by-pref-1')).toHaveTextContent('pref-2');
  });

  it('项目偏好 superseded_by 为空 \'\' → 不渲染「被覆盖」标记', async () => {
    seedProjects();
    renderMemoryPage();
    await screen.findByTestId('memory-prefs-section');

    expect(screen.queryByTestId('memory-pref-superseded-pref-1')).not.toBeInTheDocument();
  });

  it('用户级偏好 superseded_by 非空 → 渲染「被覆盖」标记 + 显示被取代偏好 id', async () => {
    userPrefs[0] = { ...userPrefs[0], superseded_by: 'upref-2' };
    seedProjects();
    renderMemoryPage();
    await screen.findByTestId('memory-userprefs-section');

    expect(screen.getByTestId('memory-userpref-superseded-upref-1')).toBeInTheDocument();
    expect(screen.getByTestId('memory-userpref-superseded-by-upref-1')).toHaveTextContent('upref-2');
  });
});

/**
 * #658 记忆统计概览（2026-08-25）：
 * - 页面顶部「统计概览」区块 memory-stats-section（有项目时渲染）；数字卡
 *   memory-stats-total（= learned_preferences + user_preferences.count +
 *   语义总结数）、memory-stats-project-prefs（learned_preferences）、
 *   memory-stats-user-prefs（user_preferences.count）、memory-stats-summaries
 *   （语义总结数）与 agentic 明细卡 memory-stats-chapters /
 *   memory-stats-direct-confirms / memory-stats-modify-rate（百分比） /
 *   memory-stats-regenerate-rate（百分比）/ memory-stats-avg-diff-chars
 * - 统计加载失败不阻断页面（总结/偏好照常渲染）：memory-stats-unavailable 弱提示
 * - MemoryPage 必须 import fetchMemoryStats 自 '../api/memory'
 *   （本文件 vi.mock 工厂已加）→ 有项目挂载时调用 fetchMemoryStats(pid)
 *
 * RED 预期：当前实现无统计区块 → memory-stats-* 元素不存在（元素级 FAIL）；
 * 用户级偏好行内详情 testid 同理。
 */
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
      baseline_ref: 'docs/agent-baseline-2026-08-10.md',
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
