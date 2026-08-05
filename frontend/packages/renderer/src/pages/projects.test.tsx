/**
 * 项目页测试契约（Issue #79 RED 阶段，spec §4.2.2）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 ProjectsPage 必须匹配（行为断言，不测样式）：
 *
 * - 挂载 → projectStore.loadProjects()（GET /api/v1/projects）→ 卡片网格
 * - 卡片（data-testid="project-card"）：
 *   书名 / 题材 / 目标字数 / 章节进度「第 n 章 / m 章」（n = word_count>0 章节数，m = 总数）
 *   / 更新时间相对时间 / 进度条（role="progressbar"，aria-valuenow = round(n/m*100)）
 *   / 写作中标记（data-testid="writing-badge"，文案「写作中」；依据 currentProjectId === project.id）
 * - 双入口：主按钮 data-testid="new-project-btn" + 网格末位虚线卡片 data-testid="new-project-card"（均打开新建对话框）
 * - 新建对话框（role="dialog"）：书名必填 1-100（空 → 「书名不能为空」，不发 POST）
 *   / 题材 11 枚举（Genre） / 语言（含 zh-CN） / 目标字数默认 800000
 * - 「创建」→ POST /api/v1/projects → 201 → navigate('/writing')（渲染于 MemoryRouter 下断言）
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ProjectsPage } from './projects';
import { apiFetch } from '../api/client';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import type { Project } from '../stores/project';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const GENRES = ['玄幻', '科幻', '言情', '仙侠', '武侠', '都市', '历史', '游戏', '悬疑', '奇幻', '其他'];

function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: 'p1',
    name: '青云志',
    genre: '玄幻',
    language: 'zh-CN',
    target_words: 800000,
    config: {},
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-08-05T10:00:00Z',
    ...overrides,
  };
}

/** 12 章中 3 章有正文（word_count>0）→ written=3, total=12 */
function chapterPage(total: number, written: number) {
  return {
    items: Array.from({ length: total }, (_, i) => ({
      id: `c${i}`, project_id: 'p1', volume_id: null, title: `第${i + 1}章`, content: '',
      word_count: i < written ? 500 : 0, order_index: i,
    })),
    total,
    offset: 0,
    limit: 50,
  };
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === '/api/v1/projects' && (!init?.method || init.method === 'GET')) {
      return {
        items: [makeProject({ id: 'p1', name: '青云志', updated_at: new Date(Date.now() - 30_000).toISOString() }),
          makeProject({ id: 'p2', name: '山海经', genre: '神话', updated_at: new Date(Date.now() - 5 * 86_400_000).toISOString() })],
        total: 2, offset: 0, limit: 50,
      };
    }
    if (path === '/api/v1/projects/p1/chapters') return chapterPage(12, 3);
    if (path === '/api/v1/projects/p2/chapters') return chapterPage(0, 0);
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

function renderProjectsPage(initialEntry = '/projects') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/writing" element={<div data-testid="writing-probe">写作页探针</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('项目页 — 卡片网格（spec §4.2.2）', () => {
  it('挂载加载项目列表并渲染卡片：书名/题材/目标字数/进度/更新时间/进度条', async () => {
    useProjectStore.setState({ currentProjectId: 'p1' }); // 写作中标记依据
    renderProjectsPage();

    // 卡片出现（loadProjects 异步完成；mock 2 个项目 → 用 findAll 取第一张）
    const card1 = (await screen.findAllByTestId('project-card'))[0];
    expect(card1).toHaveTextContent('青云志');
    expect(card1).toHaveTextContent('玄幻');
    expect(card1).toHaveTextContent(/800,?000/); // 目标字数
    // 章节进度：第 3 章 / 12 章（written=3, total=12）
    expect(card1).toHaveTextContent('第 3 章 / 12 章');
    // 更新时间相对时间：p1 刚刚更新
    expect(card1).toHaveTextContent('刚刚');
    // 进度条：3/12 → 25
    const bar = within(card1).getByRole('progressbar');
    expect(bar).toHaveAttribute('aria-valuenow', '25');

    const cards = screen.getAllByTestId('project-card');
    expect(cards).toHaveLength(2);
    expect(cards[1]).toHaveTextContent('山海经');
    expect(cards[1]).toHaveTextContent('5 天前');
  });

  it('写作中标记：仅 currentProjectId 对应卡片显示', async () => {
    useProjectStore.setState({ currentProjectId: 'p1' });
    renderProjectsPage();
    const card1 = (await screen.findAllByTestId('project-card'))[0];
    expect(within(card1).getByTestId('writing-badge')).toHaveTextContent('写作中');
    const cards = screen.getAllByTestId('project-card');
    expect(within(cards[1]).queryByTestId('writing-badge')).not.toBeInTheDocument();
  });

  it('加载失败：错误态展示（不渲染卡片）', async () => {
    apiFetchMock.mockRejectedValue(new Error('内核未就绪'));
    renderProjectsPage();
    await screen.findByText(/内核未就绪/);
    expect(screen.queryByTestId('project-card')).not.toBeInTheDocument();
  });
});

describe('项目页 — 双入口（主按钮 + 末位虚线卡片）', () => {
  it('主按钮与虚线卡片均可打开新建对话框', async () => {
    const user = userEvent.setup();
    renderProjectsPage();

    await user.click(screen.getByTestId('new-project-btn'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '取消' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await user.click(screen.getByTestId('new-project-card'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });
});

describe('项目页 — 新建对话框', () => {
  it('字段：书名必填 / 题材 11 枚举 / 语言含 zh-CN / 目标字数默认 800000', async () => {
    const user = userEvent.setup();
    renderProjectsPage();
    await user.click(screen.getByTestId('new-project-btn'));

    const dlg = screen.getByRole('dialog');
    expect(within(dlg).getByLabelText('书名')).toBeInTheDocument();
    const genre = within(dlg).getByLabelText('题材');
    expect(genre.tagName).toBe('SELECT');
    const options = within(dlg).getAllByRole('option');
    // 11 种 Genre 枚举（+ 占位默认选项 0 或 11 全量 —— 契约：11 个题材枚举全量存在）
    for (const g of GENRES) {
      expect(within(dlg).getByRole('option', { name: g })).toBeInTheDocument();
    }
    expect(options.length).toBeGreaterThanOrEqual(11);
    expect(within(dlg).getByLabelText('语言')).toBeInTheDocument();
    expect(within(dlg).getByRole('option', { name: 'zh-CN' })).toBeInTheDocument();
    expect(within(dlg).getByLabelText('目标字数')).toHaveValue(800000);
  });

  it('书名空校验：显示「书名不能为空」，不发 POST', async () => {
    const user = userEvent.setup();
    renderProjectsPage();
    await user.click(screen.getByTestId('new-project-btn'));
    await user.click(screen.getByRole('button', { name: '创建' }));

    expect(screen.getByText('书名不能为空')).toBeInTheDocument();
    expect(apiFetchMock).not.toHaveBeenCalledWith('/api/v1/projects', expect.objectContaining({ method: 'POST' }));
  });

  it('创建成功：POST /api/v1/projects → 201 → 跳转写作页', async () => {
    const user = userEvent.setup();
    const created = makeProject({ id: 'p9', name: '青山入我怀', genre: '言情' });
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/projects' && init?.method === 'POST') return created;
      if (path === '/api/v1/projects' && (!init?.method || init.method === 'GET')) {
        return { items: [created], total: 1, offset: 0, limit: 50 };
      }
      if (path.startsWith('/api/v1/projects/p9/chapters')) return chapterPage(0, 0);
      return { items: [], total: 0, offset: 0, limit: 50 };
    });

    renderProjectsPage();
    await user.click(screen.getByTestId('new-project-btn'));
    await user.type(within(screen.getByRole('dialog')).getByLabelText('书名'), '青山入我怀');
    await user.selectOptions(within(screen.getByRole('dialog')).getByLabelText('题材'), '言情');
    await user.click(screen.getByRole('button', { name: '创建' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/projects', {
        method: 'POST',
        body: { name: '青山入我怀', genre: '言情', language: 'zh-CN', target_words: 800000 },
      });
    });
    // 201 后跳转写作页
    expect(await screen.findByTestId('writing-probe')).toBeInTheDocument();
    expect(useProjectStore.getState().currentProjectId).toBe('p9');
  });
});
