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
import { MemoryRouter } from 'react-router-dom';
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
    // #674 拖拽归卷：章节 drop 到卷容器依赖的 store 方法
    moveChapter: vi.fn(),
    // #723 章节行操作：重命名（patchChapter）/ 删除（deleteChapter）
    patchChapter: vi.fn(),
    deleteChapter: vi.fn(),
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
  mocks.chapterState.moveChapter.mockReset();
  mocks.chapterState.deleteVolume.mockReset();
  mocks.chapterState.patchChapter.mockReset();
  mocks.chapterState.deleteChapter.mockReset();
  mocks.chapterState.createChapter.mockResolvedValue({ id: 'c4', title: '新章节', volume_id: null, order_index: 3, word_count: 0 });
  mocks.chapterState.volumes = [];
  mocks.chapterState.chapters = [];
  mocks.chapterState.currentChapterId = null;
  mocks.projectState.projects = [];
  mocks.projectState.currentProjectId = null;
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

function renderTree() {
  render(
    <MemoryRouter>
      <ProjectTree />
    </MemoryRouter>
  );
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

describe('ProjectTree — #674 卷章树按钮并排/拖拽归卷/新建选卷（RED 契约）', () => {
  it('底部容器两按钮「+ 新建卷」与「+ 新建章节」并排（同一 actions-row flex 容器内，非块级堆叠）', () => {
    renderTree();
    // #702：按钮行 = footer 内独立的 actions-row（flex 容器），两按钮为其兄弟
    const footer = screen.getByTestId('tree-actions');
    expect(footer).toBeInTheDocument();
    expect(footer.className).toMatch(/(^|\s)flex(\s|$)/);
    const btnRow = screen.getByTestId('tree-action-row');
    expect(btnRow.className).toMatch(/(^|\s)flex(\s|$)/);
    const volBtn = screen.getByRole('button', { name: /\+ 新建卷/ });
    const chBtn = screen.getByRole('button', { name: /\+ 新建章节/ });
    // 两按钮是同一 actions-row 的兄弟（非块级上下堆叠）
    expect(volBtn.parentElement).toBe(btnRow);
    expect(chBtn.parentElement).toBe(btnRow);
  });

  it('章节行 draggable，onDragStart 设置 dataTransfer(text/plain=chapter id)', () => {
    mocks.chapterState.volumes = volumes;
    mocks.chapterState.chapters = chapters;
    renderTree();
    const ch = screen.getByText('第1章 初见').closest('button') as HTMLButtonElement;
    expect(ch).toHaveAttribute('draggable', 'true');
    const dt = { setData: vi.fn(), effectAllowed: '' };
    fireEvent.dragStart(ch, { dataTransfer: dt });
    expect(dt.setData).toHaveBeenCalledWith('text/plain', 'c1');
  });

  it('卷容器（tree-volume）onDragOver preventDefault，onDrop 调 moveChapter(chapterId, volumeId)', () => {
    mocks.chapterState.volumes = volumes;
    mocks.chapterState.chapters = chapters;
    mocks.chapterState.moveChapter.mockResolvedValue(undefined);
    renderTree();
    const vol = screen.getAllByTestId('tree-volume')[0];
    // onDragOver：jsdom DragEvent 的 defaultPrevented 不可靠，改断言 dragOver 后组件进入高亮态
    fireEvent.dragOver(vol, { dataTransfer: {}, cancelable: true });
    expect(vol.className).toContain('ring-1 ring-accent');
    // onDrop：jsdom DragEvent 从 init 读 dataTransfer，handler 经 getData('text/plain') 调 moveChapter
    fireEvent.drop(vol, { dataTransfer: { getData: () => 'c1' }, cancelable: true });
    expect(mocks.chapterState.moveChapter).toHaveBeenCalledWith('c1', 'v1');
  });

  it('新建章节输入行有卷 <Select> 下拉（默认「未分组」）', () => {
    mocks.chapterState.volumes = volumes;
    mocks.projectState.currentProjectId = 'p1';
    renderTree();
    openCreator();
    // GREEN 须给卷 Select trigger 加 data-testid="chapter-volume-select"
    const select = screen.getByTestId('chapter-volume-select');
    expect(select).toBeInTheDocument();
    expect(select).toHaveTextContent(/未分组/);
  });
});
describe('ProjectTree — #702 左栏创建输入整行 + 调宽手柄', () => {
  it('点「＋ 新建卷」→ 创建输入行整行弹出（含 ✓/✕），位于按钮行上方', () => {
    renderTree();
    fireEvent.click(screen.getByRole('button', { name: /\+ 新建卷/ }));
    const row = screen.getByTestId('tree-create-volume-row');
    expect(screen.getByPlaceholderText('新建卷标题')).toBeInTheDocument();
    expect(within(row).getByRole('button', { name: '创建卷' })).toBeInTheDocument();
    expect(within(row).getByRole('button', { name: '取消' })).toBeInTheDocument();
    // 输入行位于按钮行上方（DOM 文档序：row 先于 tree-action-row）
    const btnRow = screen.getByTestId('tree-action-row');
    expect(row.compareDocumentPosition(btnRow) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('点「＋ 新建卷」→ Enter 创建卷 / Esc 取消卷', async () => {
    mocks.projectState.currentProjectId = 'p1';
    mocks.chapterState.createVolume.mockResolvedValue(undefined);
    renderTree();
    fireEvent.click(screen.getByRole('button', { name: /\+ 新建卷/ }));
    fireEvent.change(screen.getByPlaceholderText('新建卷标题'), { target: { value: '第二卷' } });
    fireEvent.keyDown(screen.getByPlaceholderText('新建卷标题'), { key: 'Enter' });
    await waitFor(() => expect(mocks.chapterState.createVolume).toHaveBeenCalledWith('p1', '第二卷'));
    // Esc 取消：关闭输入行
    fireEvent.click(screen.getByRole('button', { name: /\+ 新建卷/ }));
    fireEvent.change(screen.getByPlaceholderText('新建卷标题'), { target: { value: '待取消' } });
    fireEvent.keyDown(screen.getByPlaceholderText('新建卷标题'), { key: 'Escape' });
    expect(screen.queryByTestId('tree-create-volume-row')).not.toBeInTheDocument();
    expect(mocks.chapterState.createVolume).toHaveBeenCalledTimes(1);
  });

  it('左栏提供 col-resize 拖拽手柄（拖动调宽，min 160 / max 360）', () => {
    const onResize = vi.fn();
    render(
      <MemoryRouter initialEntries={['/writing']}>
        <ProjectTree width={208} onResizeWidth={onResize} />
      </MemoryRouter>
    );
    const handle = screen.getByTestId('tree-resize-handle');
    expect(handle).toBeInTheDocument();
    expect(handle.className).toMatch(/col-resize/);
    // mousedown 记录起点 → mousemove 更新宽度（208 + (300-208) = 300，在 [160,360] 内）
    fireEvent.mouseDown(handle, { clientX: 208 });
    fireEvent.mouseMove(window, { clientX: 300 });
    expect(onResize).toHaveBeenCalledWith(300);
    // 超出上限 clamp 到 360
    fireEvent.mouseDown(handle, { clientX: 0 });
    fireEvent.mouseMove(window, { clientX: 500 });
    expect(onResize).toHaveBeenLastCalledWith(360);
  });
});
describe('ProjectTree — #723 章节行编辑/删除按钮（RED 契约）', () => {
  it('每章节行提供「编辑章节」与「删除章节」按钮（按章节 id 查找）', () => {
    mocks.chapterState.volumes = volumes;
    mocks.chapterState.chapters = chapters;
    renderTree();
    for (const ch of chapters) {
      expect(screen.getByTestId(`chapter-edit-${ch.id}`)).toBeInTheDocument();
      expect(screen.getByTestId(`chapter-delete-${ch.id}`)).toBeInTheDocument();
    }
  });

  it('点击「删除章节」→ 弹确认框（chapter-del-dialog，含章节名）；确认 → deleteChapter(id) 且关框', async () => {
    mocks.chapterState.volumes = volumes;
    mocks.chapterState.chapters = chapters;
    mocks.chapterState.deleteChapter.mockResolvedValue(undefined);
    renderTree();

    fireEvent.click(screen.getByTestId('chapter-delete-c1'));
    const dialog = screen.getByTestId('chapter-del-dialog');
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveTextContent('第1章 初见');

    fireEvent.click(screen.getByTestId('chapter-del-ok'));
    await waitFor(() => expect(mocks.chapterState.deleteChapter).toHaveBeenCalledWith('c1'));
    await waitFor(() => expect(screen.queryByTestId('chapter-del-dialog')).not.toBeInTheDocument());
  });

  it('确认框「取消」关闭且不调 deleteChapter', () => {
    mocks.chapterState.volumes = volumes;
    mocks.chapterState.chapters = chapters;
    renderTree();

    fireEvent.click(screen.getByTestId('chapter-delete-c1'));
    fireEvent.click(screen.getByTestId('chapter-del-cancel'));
    expect(screen.queryByTestId('chapter-del-dialog')).not.toBeInTheDocument();
    expect(mocks.chapterState.deleteChapter).not.toHaveBeenCalled();
  });

  it('点「编辑章节」→ 行内输入框（chapter-edit-input，预填标题）；Enter → patchChapter(id, 新标题)', async () => {
    mocks.chapterState.volumes = volumes;
    mocks.chapterState.chapters = chapters;
    mocks.chapterState.patchChapter.mockResolvedValue({
      id: 'c1', title: '改后标题', volume_id: 'v1', order_index: 0, word_count: 2347,
    });
    renderTree();

    fireEvent.click(screen.getByTestId('chapter-edit-c1'));
    const input = screen.getByTestId('chapter-edit-input') as HTMLInputElement;
    expect(input).toBeInTheDocument();
    expect(input.value).toBe('第1章 初见');

    fireEvent.change(input, { target: { value: '改后标题' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(mocks.chapterState.patchChapter).toHaveBeenCalledWith('c1', '改后标题'));
  });
});
