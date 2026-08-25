/**
 * #657 RED 契约：检索页「索引维护」重建索引入口（C+P2：全文+向量、异步进度轮询）
 *
 * 契约（GREEN 实现，本文件只写测试不改 src/）：
 * - 挂载（projects 非空）→ search-page 内出现「索引维护」卡片，含：
 *   rebuild-project-scope（项目范围 Select：当前项目 / 全部项目，默认当前项目）
 *   rebuild-index-scope（索引类型 Select：两者（全文+向量）/ 仅全文 / 仅向量，默认两者）
 *   rebuild-btn（重建索引入口按钮）
 * - 点 rebuild-btn → 确认弹窗 rebuild-confirm-dialog（含「API 费用」提示）……
 *   点 rebuild-confirm-ok → 调 api/index.ts 新导出 postIndexRebuild
 *   （body：project_ids / scope 由范围与类型选择决定）→ 开始轮询 fetchIndexRebuildStatus
 * - 反馈三态：进行中 rebuild-loading（spinner + 步骤 + 进度条 + N/M 项目）；
 *   完成 rebuild-ok-toast（含 rebuilt_at + 项目数）；失败 rebuild-err-toast（区分全文已建/向量失败）
 * - 后端缺席（#659 未合入）时，rebuild 端点 404 → 失败 err toast（不炸 UI）
 *
 * Mock 形态：vi.mock('../api/index')（postIndexRebuild/fetchIndexRebuildStatus）；
 * 真 store（useProjectStore.setState 注入 projects/currentProjectId；useToastStore 清空）；
 * i18n 真实 useI18n（testid 断言为主）。
 *
 * RED 预期：SearchPage 未实现索引维护卡 → 用例 1（元素缺失）FAIL；
 * 依赖 api/index.ts 模块缺失 → 用例 2-6 FAIL（postIndexRebuild.mock 未定义）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { SearchPage } from './search';
import { fetchSearch } from '../api/search';
import { postIndexRebuild, fetchIndexRebuildStatus, type IndexRebuildStatusDto } from '../api/index';
import { useProjectStore, type Project } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import { useToastStore } from '../stores/toast';

vi.mock('../api/search', () => ({ fetchSearch: vi.fn() }));
vi.mock('../api/index', () => ({
  postIndexRebuild: vi.fn(),
  fetchIndexRebuildStatus: vi.fn(),
}));

const fetchSearchMock = vi.mocked(fetchSearch);
const postIndexRebuildMock = vi.mocked(postIndexRebuild);
const fetchIndexRebuildStatusMock = vi.mocked(fetchIndexRebuildStatus);

/** 契约结构镜像（GREEN 类型从 api/index.ts 导出；本文件内联镜像供 mock 播种） */
const DONE: IndexRebuildStatusDto = {
  status: 'done',
  step: 'vector',
  progress_done: 7,
  progress_total: 7,
  rebuilt_at: '2026-08-25T12:30:00Z',
  error: null,
};

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

function renderSearchPage() {
  return render(
    <MemoryRouter>
      <SearchPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  useToastStore.setState({ toasts: [] });
  fetchSearchMock.mockReset();
  postIndexRebuildMock.mockReset();
  postIndexRebuildMock.mockResolvedValue({ task_id: 'task-1', status: 'running' });
  fetchIndexRebuildStatusMock.mockReset();
});

describe('检索页 — 索引维护重建入口（#657）', () => {
  it('test_renders_maintenance_card：有项目 → 项目范围/索引类型/重建按钮齐全，默认当前项目+两者', () => {
    seedProjects();
    renderSearchPage();

    expect(screen.getByTestId('search-page')).toBeInTheDocument();
    // 入口卡片
    expect(screen.getByTestId('rebuild-project-scope')).toBeInTheDocument();
    expect(screen.getByTestId('rebuild-index-scope')).toBeInTheDocument();
    expect(screen.getByTestId('rebuild-btn')).toBeInTheDocument();
    // 默认值（Radix SelectValue 文本注入 trigger）
    expect(screen.getByTestId('rebuild-project-scope')).toHaveTextContent('当前项目');
    expect(screen.getByTestId('rebuild-index-scope')).toHaveTextContent('两者');
    // 初始无反馈
    expect(screen.queryByTestId('rebuild-loading')).not.toBeInTheDocument();
    expect(screen.queryByTestId('rebuild-ok-toast')).not.toBeInTheDocument();
    expect(screen.queryByTestId('rebuild-err-toast')).not.toBeInTheDocument();
  });

  it('test_confirm_dialog_before_rebuild：点重建 → 确认弹窗（含费用提示）→ 点确定 → postIndexRebuild scope=both', async () => {
    seedProjects();
    fetchIndexRebuildStatusMock.mockResolvedValue(DONE);
    const user = userEvent.setup();
    renderSearchPage();

    await user.click(screen.getByTestId('rebuild-btn'));
    // 确认弹窗出现（未点确定前不发请求）
    const dialog = await screen.findByTestId('rebuild-confirm-dialog');
    expect(dialog).toBeInTheDocument();
    expect(dialog.textContent).toMatch(/API 费用|费用|embedding 模型/i);
    expect(postIndexRebuildMock).not.toHaveBeenCalled();

    await user.click(screen.getByTestId('rebuild-confirm-ok'));
    await waitFor(() => {
      expect(postIndexRebuildMock).toHaveBeenCalledWith({
        project_ids: ['p1'],
        scope: 'both',
      });
    });
  });

  it('test_scope_all_projects：范围切「全部项目」→ project_ids=null（缺省=全部）', async () => {
    seedProjects();
    fetchIndexRebuildStatusMock.mockResolvedValue(DONE);
    const user = userEvent.setup();
    renderSearchPage();

    await user.click(screen.getByTestId('rebuild-project-scope'));
    await user.click(await screen.findByRole('option', { name: '全部项目' }));
    await user.click(screen.getByTestId('rebuild-btn'));
    await user.click(await screen.findByTestId('rebuild-confirm-ok'));
    await waitFor(() => {
      expect(postIndexRebuildMock).toHaveBeenCalledWith(
        expect.objectContaining({ project_ids: null, scope: 'both' }),
      );
    });
  });

  it('test_index_scope_vector：索引类型切「仅向量」→ scope=vector', async () => {
    seedProjects();
    fetchIndexRebuildStatusMock.mockResolvedValue(DONE);
    const user = userEvent.setup();
    renderSearchPage();

    await user.click(screen.getByTestId('rebuild-index-scope'));
    await user.click(await screen.findByRole('option', { name: '仅向量' }));
    await user.click(screen.getByTestId('rebuild-btn'));
    await user.click(await screen.findByTestId('rebuild-confirm-ok'));
    await waitFor(() => {
      expect(postIndexRebuildMock).toHaveBeenCalledWith(
        expect.objectContaining({ project_ids: ['p1'], scope: 'vector' }),
      );
    });
  });

  it('test_loading_state：调 postIndexRebuild 后 → rebuild-loading 出现（spinner+步骤+进度）', async () => {
    seedProjects();
    postIndexRebuildMock.mockResolvedValue({ task_id: 'task-1', status: 'running' });
    fetchIndexRebuildStatusMock.mockReturnValue(new Promise(() => {})); // 永不 resolve → 保持 running
    const user = userEvent.setup();
    renderSearchPage();

    await user.click(screen.getByTestId('rebuild-btn'));
    await user.click(await screen.findByTestId('rebuild-confirm-ok'));

    const loading = await screen.findByTestId('rebuild-loading');
    expect(loading).toBeInTheDocument();
    expect(loading.textContent).toMatch(/正在重建索引|进度|step|全文/i);
  });

  it('test_done_toast：轮询返回 done → rebuild-ok-toast（含 rebuilt_at + 项目数）', async () => {
    seedProjects();
    fetchIndexRebuildStatusMock.mockResolvedValue(DONE);
    const user = userEvent.setup();
    renderSearchPage();

    await user.click(screen.getByTestId('rebuild-btn'));
    await user.click(await screen.findByTestId('rebuild-confirm-ok'));

    const ok = await screen.findByTestId('rebuild-ok-toast');
    expect(ok).toBeInTheDocument();
    expect(ok.textContent).toMatch(/2026-08-25T12:30:00Z/);
    expect(ok.textContent).toMatch(/1|项目/);
    // 完成后 cleanup：loading/确认弹窗消失
    expect(screen.queryByTestId('rebuild-loading')).not.toBeInTheDocument();
  });

  it('test_err_toast：postIndexRebuild 失败（后端 #659 未合入 404）→ rebuild-err-toast 且不炸 UI', async () => {
    seedProjects();
    postIndexRebuildMock.mockRejectedValue(new Error('HTTP 404'));
    const user = userEvent.setup();
    renderSearchPage();

    await user.click(screen.getByTestId('rebuild-btn'));
    await user.click(await screen.findByTestId('rebuild-confirm-ok'));

    const err = await screen.findByTestId('rebuild-err-toast');
    expect(err).toBeInTheDocument();
    // 页面仍可交互（搜索区健在）
    expect(screen.getByTestId('search-page')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '检索' })).toBeInTheDocument();
  });
});
