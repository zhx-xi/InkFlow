/**
 * ProjectTree 薄弱分支补测（Issue #104 覆盖率：行 62.75% → 目标 ≥99%）
 *
 * 覆盖点（对应 src/components/ProjectTree.tsx）：
 * - 创建章节流程：+ 按钮 → 输入 → Enter / 勾按钮 → createChapter 调用 + 清空 + 关闭
 * - Escape 取消 / 取消按钮（不调用 createChapter）
 * - 空标题回退 '新章节'
 * - 无 currentProjectId → handleCreate 直接 return（createChapter 不调用）
 * - 卷分组渲染（volume 组 + ungrouped 组）
 * - 当前章高亮（data-current / data-testid=tree-chapter）
 * - 点击章节 → selectChapter
 *
 * mock 方式：vi.mock 替换 useChapterStore/useProjectStore 为纯函数 hook
 * （state 由 vi.hoisted 持有，测试内直接改写；zustand 组件测试约定见 frontend-testing 技能）
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { ProjectTree } from './ProjectTree';
import { useThemeStore } from '../stores/theme';
import type { ChapterMeta, Volume } from '../stores/chapter';
import type { Project } from '../stores/project';

const mocks = vi.hoisted(() => ({
  chapterState: {
    volumes: [] as Volume[],
    chapters: [] as ChapterMeta[],
    currentChapterId: null as string | null,
    selectChapter: vi.fn(),
    createChapter: vi.fn(),
    // #648 卷管理 GUI CRUD：卷入口依赖的 store 方法（mock 声明防组件引用 undefined 崩溃）
    createVolume: vi.fn(),
    patchVolume: vi.fn(),
    deleteVolume: vi.fn(),
  },
  projectState: {
    projects: [] as Project[],
    currentProjectId: null as string | null,
  },
}));

vi.mock('../stores/chapter', () => ({
  useChapterStore: (sel: (s: typeof mocks.chapterState) => unknown) => sel(mocks.chapterState),
}));

vi.mock('../stores/project', () => ({
  useProjectStore: (sel: (s: typeof mocks.projectState) => unknown) => sel(mocks.projectState),
}));

const volumes: Volume[] = [{ id: 'v1', title: '第一卷 风起', order_index: 0 }];

const chapters: ChapterMeta[] = [
  { id: 'c1', title: '第1章 初见', volume_id: 'v1', order_index: 0, word_count: 2347 },
  { id: 'c2', title: '第2章 夜谈', volume_id: 'v1', order_index: 1, word_count: 0 },
  { id: 'c3', title: '第3章 独行', volume_id: null, order_index: 2, word_count: 120 },
];

const project: Project = {
  id: 'p1',
  name: '长安十二时辰',
  tags: ['历史'],
  language: 'zh',
  target_words: 100000,
  config: {},
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

beforeEach(() => {
  mocks.chapterState.selectChapter.mockReset();
  mocks.chapterState.createChapter.mockReset();
  mocks.chapterState.createVolume.mockReset();
  mocks.chapterState.patchVolume.mockReset();
  mocks.chapterState.deleteVolume.mockReset();
  mocks.chapterState.createChapter.mockResolvedValue({ id: 'c4', title: '新章节', volume_id: null, order_index: 3, word_count: 0 });
  mocks.chapterState.volumes = [];
  mocks.chapterState.chapters = [];
  mocks.chapterState.currentChapterId = null;
  mocks.projectState.projects = [];
  mocks.projectState.currentProjectId = null;
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

function renderTree() {
  render(<ProjectTree />);
}

/** 进入创建态（点 + 按钮） */
function openCreator() {
  fireEvent.click(screen.getByRole('button', { name: '+ 新建章节' }));
}

const inputEl = () => screen.getByPlaceholderText('新建章节') as HTMLInputElement;

describe('ProjectTree — 卷章树渲染', () => {
  it('卷分组渲染：volume 组内章节 + ungrouped 章节（volume_id null）', () => {
    mocks.chapterState.volumes = volumes;
    mocks.chapterState.chapters = chapters;
    mocks.projectState.projects = [project];
    mocks.projectState.currentProjectId = 'p1';
    renderTree();

    // 项目印章 + 卷标题
    expect(screen.getByText('长安十二时辰')).toBeInTheDocument();
    expect(screen.getByTestId('project-seal')).toBeInTheDocument();
    expect(screen.getByText('第一卷 风起')).toBeInTheDocument();
    expect(screen.getAllByTestId('tree-volume')).toHaveLength(1);

    // 卷内章节（含字数）+ ungrouped 章节
    expect(screen.getByText('第1章 初见')).toBeInTheDocument();
    expect(screen.getByText('2,347')).toBeInTheDocument();
    expect(screen.getByText('第2章 夜谈')).toBeInTheDocument();
    expect(screen.getByText('第3章 独行')).toBeInTheDocument();
  });

  it('当前章高亮：仅当前章有 data-current=true 与 data-testid=tree-chapter', () => {
    mocks.chapterState.volumes = volumes;
    mocks.chapterState.chapters = chapters;
    mocks.chapterState.currentChapterId = 'c2';
    renderTree();

    const current = screen.getByTestId('tree-chapter');
    expect(current).toHaveTextContent('第2章 夜谈');
    expect(current).toHaveAttribute('data-current', 'true');

    // 非当前章不带 data-current
    expect(screen.getByText('第1章 初见').closest('button')).not.toHaveAttribute('data-current');
  });

  it('点击章节 → selectChapter(id)', () => {
    mocks.chapterState.volumes = volumes;
    mocks.chapterState.chapters = chapters;
    renderTree();

    fireEvent.click(screen.getByText('第3章 独行'));
    expect(mocks.chapterState.selectChapter).toHaveBeenCalledWith('c3');
  });
});

describe('ProjectTree — 创建章节流程', () => {
  it('+ 按钮 → 输入 → Enter → createChapter(projectId, title) + 清空 + 关闭创建态', async () => {
    mocks.projectState.currentProjectId = 'p1';
    renderTree();

    openCreator();
    fireEvent.change(inputEl(), { target: { value: '第四章 归途' } });
    fireEvent.keyDown(inputEl(), { key: 'Enter' });

    await waitFor(() => expect(mocks.chapterState.createChapter).toHaveBeenCalledWith('p1', '第四章 归途'));
    // 创建后清空并关闭 → 回到 + 按钮
    await waitFor(() => expect(screen.getByRole('button', { name: '+ 新建章节' })).toBeInTheDocument());
    expect(screen.queryByPlaceholderText('新建章节')).not.toBeInTheDocument();
  });

  it('勾按钮提交：点 + → 输入 → 点 Check → createChapter 调用', async () => {
    mocks.projectState.currentProjectId = 'p1';
    renderTree();

    openCreator();
    fireEvent.change(inputEl(), { target: { value: '第四章 归途' } });
    fireEvent.click(screen.getByRole('button', { name: '新建章节' })); // Check 按钮 aria-label

    await waitFor(() => expect(mocks.chapterState.createChapter).toHaveBeenCalledWith('p1', '第四章 归途'));
    await waitFor(() => expect(screen.getByRole('button', { name: '+ 新建章节' })).toBeInTheDocument());
  });

  it('空标题 → 回退默认名「新章节」', async () => {
    mocks.projectState.currentProjectId = 'p1';
    renderTree();

    openCreator();
    fireEvent.keyDown(inputEl(), { key: 'Enter' });

    await waitFor(() => expect(mocks.chapterState.createChapter).toHaveBeenCalledWith('p1', '新章节'));
  });

  it('Escape 取消：关闭创建态 + 清空输入，不调用 createChapter', () => {
    mocks.projectState.currentProjectId = 'p1';
    renderTree();

    openCreator();
    fireEvent.change(inputEl(), { target: { value: '待取消' } });
    fireEvent.keyDown(inputEl(), { key: 'Escape' });

    expect(screen.getByRole('button', { name: '+ 新建章节' })).toBeInTheDocument();
    expect(mocks.chapterState.createChapter).not.toHaveBeenCalled();

    // 重新打开：输入已清空
    openCreator();
    expect(inputEl().value).toBe('');
  });

  it('取消按钮：关闭创建态，不调用 createChapter', () => {
    mocks.projectState.currentProjectId = 'p1';
    renderTree();

    openCreator();
    fireEvent.change(inputEl(), { target: { value: '待取消' } });
    fireEvent.click(screen.getByRole('button', { name: '取消' }));

    expect(screen.getByRole('button', { name: '+ 新建章节' })).toBeInTheDocument();
    expect(mocks.chapterState.createChapter).not.toHaveBeenCalled();
  });

  it('无 currentProjectId → handleCreate 直接 return（不调用 createChapter，创建态保持）', () => {
    mocks.projectState.currentProjectId = null;
    renderTree();

    openCreator();
    fireEvent.change(inputEl(), { target: { value: '孤儿章节' } });
    fireEvent.keyDown(inputEl(), { key: 'Enter' });

    expect(mocks.chapterState.createChapter).not.toHaveBeenCalled();
    // 输入保留、创建态未关闭
    expect(inputEl().value).toBe('孤儿章节');
  });
});

describe('ProjectTree — 卷节点入口（#648 卷管理 GUI CRUD，RED 契约）', () => {
  it('每卷节点（tree-volume）提供「编辑卷标题」与「删除卷」按钮（按卷节点内查找）', () => {
    mocks.chapterState.volumes = [
      { id: 'v1', title: '第一卷 风起', order_index: 0 },
      { id: 'v2', title: '第二卷 云涌', order_index: 1 },
    ];
    mocks.chapterState.chapters = [];
    renderTree();

    const volumeNodes = screen.getAllByTestId('tree-volume');
    expect(volumeNodes).toHaveLength(2);
    for (const node of volumeNodes) {
      expect(within(node).getByRole('button', { name: '编辑卷标题' })).toBeInTheDocument();
      expect(within(node).getByRole('button', { name: '删除卷' })).toBeInTheDocument();
    }
  });

  it('底部栏提供「＋ 新建卷」按钮（与「＋ 新建章节」并列）', () => {
    renderTree();
    expect(screen.getByRole('button', { name: /\+ 新建卷/ })).toBeInTheDocument();
  });
});
