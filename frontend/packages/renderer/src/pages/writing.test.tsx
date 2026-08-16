/**
 * 写作页测试契约（#298 语义反转批：GUI 写作入口管线化，spec §5.6 + §13 M8）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 WritingPage 必须匹配（行为断言，不测样式）。
 *
 * 结构 testid（既有保留）：
 * - 三栏: project-tree / editor / context-panel
 * - 项目树: tree-volume / tree-chapter（当前章 data-current="true"）
 * - 项目印章: project-seal（文本 = 书名关键字）
 * - 工具栏: editor-toolbar；撤销/重做/保存（toolbar-save）/续写/生成（i18n 文案）
 * - 编辑器: chapter-editor（textarea，段落化纯文本）
 * - 上下文: context-collapse / context-panel-content / context-expand-bar
 *
 * 管线执行状态区（替换原 SSE 流式区，spec §5.6）：
 * - data-testid="pipeline-status"
 * - running → 文案「执行中」（write.pipeline.running）
 * - success → 文案「生成完成」（write.pipeline.success）
 * - failed  → 文案「生成失败: ...」（write.pipeline.failed）
 *
 * 管线接线契约（#298 核心）：
 * - 「续写」按钮 / Ctrl+Enter → executePipeline({pipeline:'builtin:write_continue', ...})
 * - 「生成」按钮 / Ctrl+Shift+Enter → executePipeline({pipeline:'builtin:write_auto', ...})
 * - 轮询 getExecutionStatus(execution_id) → status==='completed' 时 chapterStore.setContent(final_output)
 *   （成品落章：编辑器内容 = reviser 输出 final_output）
 * - status==='failed' → 展示错误（不崩溃、不落章）
 *
 * 快捷键（Q2 拍板 C，监听在编辑器容器）：
 * - Ctrl+Z → execCommand('undo')；Ctrl+Y → execCommand('redo')
 * - Ctrl+S → chapterStore.saveContent()（PATCH /api/v1/chapters/{id}）
 * - Ctrl+Enter → 续写（executePipeline builtin:write_continue）
 * - Ctrl+Shift+Enter → 生成（executePipeline builtin:write_auto）
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { WritingPage } from './writing';
import { apiFetch } from '../api/client';
import { executePipeline, getExecutionStatus, confirmExecution } from '../api/pipeline';
import { useChapterStore } from '../stores/chapter';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});
vi.mock('../api/pipeline', () => ({
  executePipeline: vi.fn(),
  getExecutionStatus: vi.fn(),
  confirmExecution: vi.fn(),
}));

const apiFetchMock = vi.mocked(apiFetch);
const executeMock = vi.mocked(executePipeline);
const statusMock = vi.mocked(getExecutionStatus);
const confirmMock = vi.mocked(confirmExecution);

/** 与后端对齐的种子数据（mock 与 store 播种共用，防 GREEN 自动加载覆盖种子） */
const seedVolumes = [
  { id: 'v1', title: '第一卷 风起', order_index: 0 },
];
const seedChapters = [
  { id: 'c1', title: '第1章 初见', volume_id: 'v1', order_index: 0, word_count: 2347 },
  { id: 'c2', title: '第2章 夜谈', volume_id: 'v1', order_index: 1, word_count: 0 },
];

beforeEach(() => {
  vi.useRealTimers();
  apiFetchMock.mockReset();
  executeMock.mockReset();
  statusMock.mockReset();
  confirmMock.mockReset();
  executeMock.mockResolvedValue({
    execution_id: 'e1',
    pipeline: 'builtin:write_auto',
    project_id: 'p1',
    status: 'pending',
    created_at: '',
  });
  statusMock.mockResolvedValue({
    execution_id: 'e1',
    pipeline: 'builtin:write_auto',
    project_id: 'p1',
    status: 'completed',
    stages: [],
    final_output: '管线成品章节内容',
    total_duration_ms: 1200,
    error: '',
  });
  window.INKFLOW_API = { baseURL: 'http://test.local', token: 'tok-1' };
  localStorage.clear();

  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useChapterStore.setState({
    volumes: seedVolumes, chapters: seedChapters, treeProjectId: 'p1', currentChapterId: 'c1', content: '已有正文第一段。', loading: false, error: null,
  });
  useProjectStore.setState({
    projects: [{ id: 'p1', name: '青云志', genre: '玄幻', language: 'zh-CN', target_words: 800000, config: {}, created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z' }],
    currentProjectId: 'p1', loading: false, error: null,
  });

  // REST mock：自动加载/保存路径返回种子或空（防 GREEN 挂载自动加载覆盖）
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === '/api/v1/projects/p1/volumes') return { items: seedVolumes };
    if (path === '/api/v1/projects/p1/chapters') return { items: seedChapters, total: 2, offset: 0, limit: 50 };
    if (path.startsWith('/api/v1/chapters/') && init?.method === 'PATCH') return { ok: true };
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

afterEach(() => {
  vi.useRealTimers();
  delete window.INKFLOW_API;
});

describe('写作页 — 三栏与项目树', () => {
  it('三栏渲染：project-tree / editor / context-panel 存在', () => {
    render(<WritingPage />);
    expect(screen.getByTestId('project-tree')).toBeInTheDocument();
    expect(screen.getByTestId('editor')).toBeInTheDocument();
    expect(screen.getByTestId('context-panel')).toBeInTheDocument();
  });

  it('项目树：卷/章节点 + 各章字数 + 当前章 data-current 标记', () => {
    render(<WritingPage />);
    const tree = screen.getByTestId('project-tree');
    expect(within(tree).getByTestId('tree-volume')).toHaveTextContent('第一卷 风起');
    const ch1 = within(tree).getByTestId('tree-chapter');
    expect(ch1).toHaveTextContent('第1章 初见');
    expect(ch1).toHaveTextContent(/2,?347/);
    expect(ch1).toHaveAttribute('data-current', 'true');
    expect(within(tree).getByText('第2章 夜谈')).toBeInTheDocument();
  });

  it('编辑器渲染当前章正文（段落化纯文本）', () => {
    render(<WritingPage />);
    const editor = screen.getByTestId('chapter-editor') as HTMLTextAreaElement;
    expect(editor.value).toContain('已有正文第一段。');
  });
});

describe('写作页 — 项目印章常驻（三主题）', () => {
  it.each(['paper', 'night', 'ink'] as const)('主题 %s 下印章均显示，文字取书名关键字', (theme) => {
    render(<WritingPage />);
    const seal = screen.getByTestId('project-seal');
    expect(seal).toHaveTextContent('青');
    act(() => {
      useThemeStore.getState().setTheme(theme);
    });
    expect(screen.getByTestId('project-seal')).toBeInTheDocument();
  });
});

describe('写作页 — 上下文面板折叠/展开闭环', () => {
  it('折叠 → 展开条出现、内容区消失；点击展开条 → 内容区恢复', async () => {
    const user = userEvent.setup();
    render(<WritingPage />);
    expect(screen.getByTestId('context-panel-content')).toBeInTheDocument();

    await user.click(screen.getByTestId('context-collapse'));
    expect(screen.queryByTestId('context-panel-content')).not.toBeInTheDocument();
    expect(screen.getByTestId('context-expand-bar')).toBeInTheDocument();

    await user.click(screen.getByTestId('context-expand-bar'));
    expect(screen.getByTestId('context-panel-content')).toBeInTheDocument();
    expect(screen.queryByTestId('context-expand-bar')).not.toBeInTheDocument();
  });
});

describe('写作页 — 工具栏与快捷键（Q2 拍板 C）', () => {
  it('工具栏渲染：撤销/重做/保存/续写/生成', () => {
    render(<WritingPage />);
    const toolbar = screen.getByTestId('editor-toolbar');
    expect(within(toolbar).getByRole('button', { name: '撤销' })).toBeInTheDocument();
    expect(within(toolbar).getByRole('button', { name: '重做' })).toBeInTheDocument();
    expect(within(toolbar).getByTestId('toolbar-save')).toBeInTheDocument();
    expect(within(toolbar).getByRole('button', { name: '续写' })).toBeInTheDocument();
    expect(within(toolbar).getByRole('button', { name: '生成' })).toBeInTheDocument();
  });

  it('Ctrl+Z 撤销 / Ctrl+Y 重做：调用 document.execCommand', () => {
    const execMock = vi.fn(() => true);
    Object.defineProperty(document, 'execCommand', { value: execMock, configurable: true, writable: true });
    render(<WritingPage />);
    const editor = screen.getByTestId('chapter-editor');
    fireEvent.keyDown(editor, { key: 'z', ctrlKey: true });
    expect(execMock).toHaveBeenCalledWith('undo');
    fireEvent.keyDown(editor, { key: 'y', ctrlKey: true });
    expect(execMock).toHaveBeenCalledWith('redo');
    delete (document as { execCommand?: unknown }).execCommand;
  });

  it('Ctrl+S 保存：PATCH /api/v1/chapters/{currentChapterId}，body 携带正文', async () => {
    render(<WritingPage />);
    const editor = screen.getByTestId('chapter-editor') as HTMLTextAreaElement;
    fireEvent.change(editor, { target: { value: '修改后的正文内容' } });
    fireEvent.keyDown(editor, { key: 's', ctrlKey: true });
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/chapters/c1', {
        method: 'PATCH',
        body: { content: '修改后的正文内容' },
      });
    });
  });

  it('Ctrl+Enter 续写：触发管线 execute（builtin:write_continue）', async () => {
    render(<WritingPage />);
    fireEvent.keyDown(screen.getByTestId('chapter-editor'), { key: 'Enter', ctrlKey: true });
    await waitFor(() => {
      expect(executeMock).toHaveBeenCalledWith(expect.objectContaining({ pipeline: 'builtin:write_continue' }));
    });
  });

  it('Ctrl+Shift+Enter 生成：触发管线 execute（builtin:write_auto）', async () => {
    render(<WritingPage />);
    fireEvent.keyDown(screen.getByTestId('chapter-editor'), { key: 'Enter', ctrlKey: true, shiftKey: true });
    await waitFor(() => {
      expect(executeMock).toHaveBeenCalledWith(expect.objectContaining({ pipeline: 'builtin:write_auto' }));
    });
  });
});

describe('写作页 — 管线执行状态与成品落章（#298 §5.6）', () => {
  it('「续写」按钮 → executePipeline（builtin:write_continue）', async () => {
    render(<WritingPage />);
    fireEvent.click(screen.getByRole('button', { name: '续写' }));
    await waitFor(() => {
      expect(executeMock).toHaveBeenCalledWith(expect.objectContaining({ pipeline: 'builtin:write_continue' }));
    });
  });

  it('「生成」按钮 → executePipeline（builtin:write_auto）', async () => {
    render(<WritingPage />);
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    await waitFor(() => {
      expect(executeMock).toHaveBeenCalledWith(expect.objectContaining({ pipeline: 'builtin:write_auto' }));
    });
  });

  it('执行中：running 状态展示「执行中」', async () => {
    statusMock.mockResolvedValue({
      execution_id: 'e1',
      pipeline: 'builtin:write_auto',
      project_id: 'p1',
      status: 'pending',
      stages: [],
      final_output: '',
      total_duration_ms: 0,
      error: '',
    });
    render(<WritingPage />);
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    await waitFor(() => {
      expect(screen.getByTestId('pipeline-status')).toHaveTextContent('执行中');
    });
  });

  it('成品落章：completed → 编辑器内容 = final_output + 展示「生成完成」', async () => {
    vi.useFakeTimers();
    render(<WritingPage />);
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    // 轮询（1s 间隔）到 completed
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    const editor = screen.getByTestId('chapter-editor') as HTMLTextAreaElement;
    expect(editor.value).toBe('管线成品章节内容');
    expect(screen.getByTestId('pipeline-status')).toHaveTextContent('生成完成');
  });

  it('失败：failed → 展示错误（不崩溃、不落章）', async () => {
    statusMock.mockResolvedValue({
      execution_id: 'e1',
      pipeline: 'builtin:write_auto',
      project_id: 'p1',
      status: 'failed',
      stages: [],
      final_output: '',
      total_duration_ms: 800,
      error: '管线执行失败: 阶段 writer 重试耗尽',
    });
    vi.useFakeTimers();
    render(<WritingPage />);
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(screen.getByTestId('pipeline-status')).toHaveTextContent(/生成失败/);
    expect(screen.getByTestId('pipeline-status')).toHaveTextContent('管线执行失败');
    // 失败不落章（编辑器保持原值）
    const editor = screen.getByTestId('chapter-editor') as HTMLTextAreaElement;
    expect(editor.value).toBe('已有正文第一段。');
  });
});

/**
 * 空态设计（#98 §5.2.6）：无项目 / 无章节空态（本 describe 为增量契约，未改动既有断言）
 */
describe('写作页 — 空态（#98 §5.2.6）', () => {
  it('无项目 → 居中引导（「选择或新建项目开始写作」+ 返回项目页按钮跳转 /projects）', async () => {
    useProjectStore.setState({ projects: [], currentProjectId: null, loading: false, error: null });
    useChapterStore.setState({ volumes: [], chapters: [], currentChapterId: null, content: '', loading: false, error: null });
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={['/writing']}>
        <Routes>
          <Route path="/writing" element={<WritingPage />} />
          <Route path="/projects" element={<div data-testid="projects-probe">项目页探针</div>} />
        </Routes>
      </MemoryRouter>,
    );
    const empty = await screen.findByTestId('writing-empty');
    expect(empty).toHaveTextContent('选择或新建项目开始写作');
    await user.click(within(empty).getByRole('button', { name: '返回项目页' }));
    expect(await screen.findByTestId('projects-probe')).toBeInTheDocument();
  });

  it('有项目无章节 → 项目树「新建章节」引导 + 编辑器 placeholder 增强文案', async () => {
    useChapterStore.setState({ volumes: [], chapters: [], currentChapterId: null, content: '', loading: false, error: null });
    render(<WritingPage />);
    await waitFor(() => expect(useChapterStore.getState().loading).toBe(false));
    expect(screen.getByRole('button', { name: /新建章节/ })).toBeInTheDocument();
    const editor = screen.getByTestId('chapter-editor') as HTMLTextAreaElement;
    expect(editor.placeholder).toBe('还没有章节，点击左侧「新建章节」创建');
  });

  it('回归：有章节时编辑器 placeholder 保持 write.stream.idle 语义', () => {
    render(<WritingPage />);
    const editor = screen.getByTestId('chapter-editor') as HTMLTextAreaElement;
    expect(editor.placeholder).toBe('点击「续写」或 Ctrl+Enter 开始 AI 续写');
  });
});

/**
 * #105 Coverage-Gap 补测（非 RED）：自动保存防抖定时器分支 + 快捷键 switch default 兜底。
 */
describe('写作页 — 自动保存与工具栏/快捷键兜底分支（#105 补测）', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  function patchCalls() {
    return apiFetchMock.mock.calls.filter((c) => (c[1] as { method?: string } | undefined)?.method === 'PATCH');
  }

  it('自动保存：编辑后 2s 防抖落盘（PATCH 携带最新正文）', async () => {
    vi.useFakeTimers();
    render(<WritingPage />);
    const editor = screen.getByTestId('chapter-editor') as HTMLTextAreaElement;
    fireEvent.change(editor, { target: { value: '防抖自动保存的正文' } });

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(patchCalls()).toHaveLength(0);

    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(patchCalls()).toHaveLength(1);
    expect(patchCalls()[0][0]).toBe('/api/v1/chapters/c1');
    expect(patchCalls()[0][1]).toEqual({ method: 'PATCH', body: { content: '防抖自动保存的正文' } });
  });

  it('自动保存防抖重置：2s 内再次编辑重置计时器（仅最后一次变更落盘）', async () => {
    vi.useFakeTimers();
    render(<WritingPage />);
    const editor = screen.getByTestId('chapter-editor') as HTMLTextAreaElement;

    fireEvent.change(editor, { target: { value: '第一版' } });
    act(() => {
      vi.advanceTimersByTime(1500);
    });
    fireEvent.change(editor, { target: { value: '第二版' } });
    act(() => {
      vi.advanceTimersByTime(1500);
    });
    expect(patchCalls()).toHaveLength(0);

    await act(async () => {
      vi.advanceTimersByTime(600);
    });
    expect(patchCalls()).toHaveLength(1);
    expect(patchCalls()[0][1]).toEqual({ method: 'PATCH', body: { content: '第二版' } });
  });

  it('快捷键兜底：Ctrl+未注册键（Ctrl+A）无副作用（不撤销/不保存/不触发管线）', () => {
    const execMock = vi.fn(() => true);
    Object.defineProperty(document, 'execCommand', { value: execMock, configurable: true, writable: true });
    render(<WritingPage />);
    fireEvent.keyDown(screen.getByTestId('chapter-editor'), { key: 'a', ctrlKey: true });
    expect(execMock).not.toHaveBeenCalled();
    expect(patchCalls()).toHaveLength(0);
    expect(executeMock).not.toHaveBeenCalled();
    delete (document as { execCommand?: unknown }).execCommand;
  });
});

describe('写作页 — HITL 确认流（#343：waiting_hitl → 内联确认卡片 → 确认/拒绝续跑）', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('管线 waiting_hitl → 内联确认卡片出现（question + 继续/拒绝按钮）', async () => {
    vi.useFakeTimers();
    statusMock.mockResolvedValue({
      execution_id: 'e1',
      pipeline: 'builtin:write_auto',
      project_id: 'p1',
      status: 'waiting_hitl',
      stages: [],
      final_output: '',
      total_duration_ms: 0,
      error: '',
      hitl_pending: { question: '确认执行下一角色 reviser？', role: 'reviser' },
    });
    render(<WritingPage />);
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    const card = screen.getByTestId('hitl-confirm-card');
    expect(card).toHaveTextContent('确认执行下一角色 reviser？');
    expect(screen.getByTestId('hitl-confirm-approve')).toBeInTheDocument();
    expect(screen.getByTestId('hitl-confirm-reject')).toBeInTheDocument();
  });

  it('点「继续执行」→ confirmExecution(executionId, true) → 轮询续跑 → 生成完成落章', async () => {
    vi.useFakeTimers();
    statusMock
      .mockResolvedValueOnce({
        execution_id: 'e1',
        pipeline: 'builtin:write_auto',
        project_id: 'p1',
        status: 'waiting_hitl',
        stages: [],
        final_output: '',
        total_duration_ms: 0,
        error: '',
        hitl_pending: { question: '确认执行下一角色 reviser？', role: 'reviser' },
      })
      .mockResolvedValueOnce({
        execution_id: 'e1',
        pipeline: 'builtin:write_auto',
        project_id: 'p1',
        status: 'completed',
        stages: [],
        final_output: '确认后成品',
        total_duration_ms: 3000,
        error: '',
      });
    confirmMock.mockResolvedValue({ execution_id: 'e1', status: 'completed', final_output: '确认后成品' });
    render(<WritingPage />);
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByTestId('hitl-confirm-card')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('hitl-confirm-approve'));
    await act(async () => {
      vi.advanceTimersByTime(0);
    });
    expect(confirmMock).toHaveBeenCalledWith('e1', true);
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByTestId('pipeline-status')).toHaveTextContent('生成完成');
    expect(useChapterStore.getState().content).toBe('确认后成品');
  });

  it('点「拒绝并回退」→ confirmExecution(executionId, false) → 轮询续跑 → 生成完成', async () => {
    vi.useFakeTimers();
    statusMock
      .mockResolvedValueOnce({
        execution_id: 'e1',
        pipeline: 'builtin:write_auto',
        project_id: 'p1',
        status: 'waiting_hitl',
        stages: [],
        final_output: '',
        total_duration_ms: 0,
        error: '',
        hitl_pending: { question: '确认执行下一角色 reviser？', role: 'reviser' },
      })
      .mockResolvedValueOnce({
        execution_id: 'e1',
        pipeline: 'builtin:write_auto',
        project_id: 'p1',
        status: 'completed',
        stages: [],
        final_output: '拒绝后回退成品',
        total_duration_ms: 2000,
        error: '',
      });
    confirmMock.mockResolvedValue({ execution_id: 'e1', status: 'completed', final_output: '拒绝后回退成品' });
    render(<WritingPage />);
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByTestId('hitl-confirm-card')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('hitl-confirm-reject'));
    await act(async () => {
      vi.advanceTimersByTime(0);
    });
    expect(confirmMock).toHaveBeenCalledWith('e1', false);
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByTestId('pipeline-status')).toHaveTextContent('生成完成');
    expect(useChapterStore.getState().content).toBe('拒绝后回退成品');
  });

  it('项目 config 含 supervisor.hitl_roles → 生成时 execute body 带 mode=supervisor', async () => {
    vi.useFakeTimers();
    // 项目 config 携带 supervisor 配置（#343 拍板 2A：ProjectConfig.supervisor）
    useProjectStore.setState({
      projects: [
        {
          id: 'p1',
          name: '青云志',
          genre: '玄幻',
          language: 'zh-CN',
          target_words: 800000,
          config: { supervisor: { hitl_roles: ['reviser'] } },
          created_at: '2026-08-01T10:00:00Z',
          updated_at: '2026-08-05T10:00:00Z',
        },
      ],
      currentProjectId: 'p1',
      loading: false,
      error: null,
    });
    render(<WritingPage />);
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    await act(async () => {
      vi.advanceTimersByTime(0);
    });
    expect(executeMock).toHaveBeenCalledWith(
      expect.objectContaining({
        pipeline: 'builtin:write_auto',
        mode: 'supervisor',
        supervisor: { hitl_roles: ['reviser'] },
      }),
    );
  });
});

describe('写作页 — 底部 AI 聊天框（#379 F47 §4.1）', () => {
  it('渲染 chat-panel（聊天输入框 + 发送按钮；空输入发送禁用）', () => {
    render(<WritingPage />);
    expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
    expect(screen.getByTestId('chat-input')).toBeInTheDocument();
    expect(screen.getByTestId('chat-send')).toBeDisabled();
  });
});
