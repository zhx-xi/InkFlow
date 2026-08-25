/**
 * 写作页测试契约（#298 语义反转批：GUI 写作入口管线化，spec §5.6 + §13 M8）
 *
 * ⚠️ 本文件 = 契约。#642-1（缺陷 A）后「AI 生成」由 executePipeline+轮询 改为 streamPipeline SSE 流式。
 *
 * 结构 testid（既有保留）：
 * - 三栏: project-tree / editor / context-panel
 * - 项目树: tree-volume / tree-chapter（当前章 data-current="true"）
 * - 项目印章: project-seal（文本 = 书名关键字）
 * - 工具栏: editor-toolbar；撤销/重做/保存（toolbar-save）/续写/生成（i18n 文案）
 * - 编辑器: chapter-editor（textarea，段落化纯文本）
 * - 上下文: context-collapse / context-panel-content / context-expand-bar
 *
 * 管线执行状态区（spec §5.6 + #642-1 流式）：
 * - data-testid="pipeline-status"
 * - running → 文案「执行中」（write.pipeline.running）
 * - success → 文案「生成完成」（write.pipeline.success）
 * - failed  → 文案「生成失败: ...」（write.pipeline.failed）
 *
 * 管线接线契约（#298 + #642-1 核心）：
 * - 「续写」按钮 / Ctrl+Enter → streamPipeline({pipeline:'builtin:write_continue', ...})
 * - 「生成」按钮 / Ctrl+Shift+Enter → streamPipeline({pipeline:'builtin:write_auto', ...})
 * - onDone(final_output) → status='success' → chapterStore.setContent(final_output)
 *   （成品落章：编辑器内容 = final_output）；onError → 展示错误（不崩溃、不落章）
 * - #642-1：start 走 SSE 流式（onDelta 渐进 / onDone 落定 / onError 失败）；
 *   流式帧无 hitl 类型 → 生成过程不出现 HITL 确认卡片（HITL 机器保留在 useExecutionPoll poll 路径）
 *
 * 快捷键（Q2 拍板 C，监听在编辑器容器）：
 * - Ctrl+Z → execCommand('undo')；Ctrl+Y → execCommand('redo')
 * - Ctrl+S → chapterStore.saveContent()（PATCH /api/v1/chapters/{id}）
 * - Ctrl+Enter → 续写（streamPipeline builtin:write_continue）
 * - Ctrl+Shift+Enter → 生成（streamPipeline builtin:write_auto）
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { WritingPage } from './writing';
import { apiFetch } from '../api/client';
import { streamPipeline, executePipeline, confirmExecution } from '../api/pipeline';
import { useChapterStore } from '../stores/chapter';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import { useModelsStore, type ProviderConfig } from '../stores/models';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});
vi.mock('../api/pipeline', () => ({
  streamPipeline: vi.fn(),
  executePipeline: vi.fn(),
  getExecutionStatus: vi.fn(),
  confirmExecution: vi.fn(),
}));

const apiFetchMock = vi.mocked(apiFetch);
const streamPipelineMock = vi.mocked(streamPipeline);
const executeMock = vi.mocked(executePipeline);
const confirmMock = vi.mocked(confirmExecution);

/** #642-1：每次 streamPipeline 调用的 body/callbacks 捕获（用例手动驱动 SSE 帧） */
interface CapturedPipelineStream {
  body: {
    project_id: string;
    pipeline: string;
    chapter_id?: string;
    variables?: Record<string, string>;
    mode?: string;
    supervisor?: { hitl_roles: string[] };
  };
  callbacks: {
    onDelta: (delta: string) => void;
    onDone: (frame: { done: boolean; final_output?: string }) => void;
    onError: (message: string) => void;
    onToolCall?: (call: { id: string; name: string; args: Record<string, unknown> }) => void;
    onToolResult?: (res: { id: string; name: string; result: string }) => void;
  };
}
let capturedStream: CapturedPipelineStream | null = null;

/** 与后端对齐的种子数据（mock 与 store 播种共用，防 GREEN 自动加载覆盖种子） */
const seedVolumes = [
  { id: 'v1', title: '第一卷 风起', order_index: 0 },
];
const seedChapters = [
  { id: 'c1', title: '第1章 初见', volume_id: 'v1', order_index: 0, word_count: 2347 },
  { id: 'c2', title: '第2章 夜谈', volume_id: 'v1', order_index: 1, word_count: 0 },
];

/** #474：已配置模型种子 provider（key_saved=true + chat 模型），默认播种让既有用例行为不变 */
const READY_PROVIDER: ProviderConfig = {
  id: 1,
  name: 'openai',
  base_url: 'https://api.openai.com/v1',
  default_model: 'gpt-4o',
  models: [{ id: 'gpt-4o', type: 'chat', roles: ['main'] }],
  key_saved: true,
  max_retries: 3,
  timeout: 60,
  created_at: '2026-08-01T10:00:00Z',
  updated_at: '2026-08-05T10:00:00Z',
};

beforeEach(() => {
  vi.useRealTimers();
  apiFetchMock.mockReset();
  streamPipelineMock.mockReset();
  executeMock.mockReset();
  confirmMock.mockReset();
  capturedStream = null;
  // #474 前置校验依赖 models store：默认播种「已配置」+ provider-configs GET 返回同款，
  // 防 GREEN 挂载/发送时 loadProviders 覆盖为未配置
  useModelsStore.setState({ providers: [READY_PROVIDER], loading: false, error: null });
  useToastStore.setState({ toasts: [] });
  // #642-1：默认 streamPipeline 捕获 callbacks，不自动 emit（用例手动驱动帧）
  streamPipelineMock.mockImplementation((_body, callbacks) => {
    capturedStream = {
      body: _body as CapturedPipelineStream['body'],
      callbacks: callbacks as CapturedPipelineStream['callbacks'],
    };
    return Promise.resolve(() => {});
  });
  window.INKFLOW_API = { baseURL: 'http://test.local', token: 'tok-1' };
  localStorage.clear();

  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useChapterStore.setState({
    volumes: seedVolumes, chapters: seedChapters, treeProjectId: 'p1', currentChapterId: 'c1', content: '已有正文第一段。', loading: false, error: null,
  });
  useProjectStore.setState({
    projects: [{ id: 'p1', name: '青云志', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, config: {}, created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z' }],
    currentProjectId: 'p1', loading: false, error: null,
  });

  // REST mock：自动加载/保存路径返回种子或空（防 GREEN 挂载自动加载覆盖）
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === '/api/v1/provider-configs') {
      return { items: [READY_PROVIDER], total: 1, offset: 0, limit: 50 };
    }
    if (path === '/api/v1/projects/p1/volumes') return { items: seedVolumes };
    if (path === '/api/v1/projects/p1/chapters') return { items: seedChapters, total: 2, offset: 0, limit: 50 };
    if (path.startsWith('/api/v1/chapters/') && init?.method === 'PATCH') return { ok: true };
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

afterEach(() => {
  vi.useRealTimers();
  delete window.INKFLOW_API;
  capturedStream = null;
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

  it('Ctrl+Enter 续写：触发 streamPipeline（builtin:write_continue）', async () => {
    render(<WritingPage />);
    fireEvent.keyDown(screen.getByTestId('chapter-editor'), { key: 'Enter', ctrlKey: true });
    await waitFor(() => {
      expect(streamPipelineMock).toHaveBeenCalledWith(
        expect.objectContaining({ pipeline: 'builtin:write_continue' }),
        expect.any(Object),
      );
    });
  });

  it('Ctrl+Shift+Enter 生成：触发 streamPipeline（builtin:write_auto）', async () => {
    render(<WritingPage />);
    fireEvent.keyDown(screen.getByTestId('chapter-editor'), { key: 'Enter', ctrlKey: true, shiftKey: true });
    await waitFor(() => {
      expect(streamPipelineMock).toHaveBeenCalledWith(
        expect.objectContaining({ pipeline: 'builtin:write_auto' }),
        expect.any(Object),
      );
    });
  });
});

describe('写作页 — 管线执行状态与成品落章（#298 §5.6 + #642-1 流式）', () => {
  it('「续写」按钮 → streamPipeline（builtin:write_continue）', async () => {
    render(<WritingPage />);
    fireEvent.click(screen.getByRole('button', { name: '续写' }));
    await waitFor(() => {
      expect(streamPipelineMock).toHaveBeenCalledWith(
        expect.objectContaining({ pipeline: 'builtin:write_continue' }),
        expect.any(Object),
      );
    });
  });

  it('「生成」按钮 → streamPipeline（builtin:write_auto）', async () => {
    render(<WritingPage />);
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    await waitFor(() => {
      expect(streamPipelineMock).toHaveBeenCalledWith(
        expect.objectContaining({ pipeline: 'builtin:write_auto' }),
        expect.any(Object),
      );
    });
  });

  it('执行中：running 状态展示「执行中」', async () => {
    render(<WritingPage />);
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    await waitFor(() => {
      expect(screen.getByTestId('pipeline-status')).toHaveTextContent('执行中');
    });
  });

  it('成品落章：onDone(final_output) → 编辑器内容 = final_output + 展示「生成完成」', async () => {
    render(<WritingPage />);
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    await waitFor(() => expect(streamPipelineMock).toHaveBeenCalled());
    // 驱动 SSE done 帧（#642-1：final_output 落定）
    act(() => {
      capturedStream?.callbacks.onDone({ done: true, final_output: '管线成品章节内容' });
    });
    const editor = screen.getByTestId('chapter-editor') as HTMLTextAreaElement;
    await waitFor(() => expect(editor.value).toBe('管线成品章节内容'));
    expect(screen.getByTestId('pipeline-status')).toHaveTextContent('生成完成');
  });

  it('失败：onError → 展示错误（不崩溃、不落章）', async () => {
    render(<WritingPage />);
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    await waitFor(() => expect(streamPipelineMock).toHaveBeenCalled());
    act(() => {
      capturedStream?.callbacks.onError('管线执行失败: 阶段 writer 重试耗尽');
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

  it('回归：有章节时编辑器 placeholder 不含 idle 空态文案（#580 删除「AI 已就绪，开始创作」）', () => {
    render(<WritingPage />);
    const editor = screen.getByTestId('chapter-editor') as HTMLTextAreaElement;
    // #540：AI 对话栏替代续写栏后，编辑器不再提示「点击续写或 Ctrl+Enter 开始 AI 续写」
    // #564：空态文案中性化——不再提示「在下方对话框与 AI 对话」（与底部 AI 对话栏并存易混淆）
    // #580：idle 空态栏整栏删除——有章节时 placeholder 不得再是「AI 已就绪，开始创作」（当前实现仍渲染 → RED）
    expect(editor.placeholder).not.toBe('AI 已就绪，开始创作');
    expect(editor.placeholder).not.toContain('AI 已就绪');
    expect(editor.placeholder).not.toContain('在下方对话框');
    expect(editor.placeholder).not.toContain('Ctrl+Enter');
  });
});

/**
 * #565 执行详情页隐藏 ChatPanel：view=detail 不渲染底部 AI 对话栏（仅 editor 视图有）。
 */
describe('写作页 — 执行详情页隐藏 ChatPanel（#565）', () => {
  it('view=detail 不渲染 ChatPanel（仅 editor 视图有）', () => {
    render(<WritingPage />);
    // editor 视图渲染 ChatPanel
    expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
    // 切到 detail 视图
    fireEvent.click(screen.getByTestId('view-toggle'));
    // RED：当前两种 view 都渲染 ChatPanel → 这里 FAIL（queryByTestId 仍找到 chat-panel）
    expect(screen.queryByTestId('chat-panel')).not.toBeInTheDocument();
    // 执行详情面板渲染（无 executionId → 空态），布局不混杂 chat
    expect(screen.getByTestId('exec-detail-empty')).toBeInTheDocument();
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
    expect(streamPipelineMock).not.toHaveBeenCalled();
    delete (document as { execCommand?: unknown }).execCommand;
  });
});

/**
 * #343 HITL 确认流（#642-1 迁移）：
 * - start 走 SSE 流式（帧类型 delta/tool_call/tool_result/done/error，无 hitl 帧）
 *   → 生成过程不出现 awaiting_human / HITL 确认卡片，confirmExecution 不被调用
 * - HITL 中断 + confirm 续跑机器保留在 useExecutionPoll 的 poll/confirm 路径
 *   （getExecutionStatus/confirmExecution 契约见 useExecutionPoll.test.ts）
 */
describe('写作页 — HITL 确认流（#343 + #642-1：流式 start 无 HITL 帧）', () => {
  it('#642-1 流式执行不出现 HITL 确认卡片（流式帧无 hitl 类型）', async () => {
    render(<WritingPage />);
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    await waitFor(() => expect(streamPipelineMock).toHaveBeenCalled());
    // running 态：无确认卡片
    expect(screen.queryByTestId('hitl-confirm-card')).not.toBeInTheDocument();
    expect(screen.getByTestId('pipeline-status')).toHaveTextContent('执行中');
    // done 帧直达 success：依然无确认卡片
    act(() => {
      capturedStream?.callbacks.onDone({ done: true, final_output: '成品' });
    });
    expect(screen.queryByTestId('hitl-confirm-card')).not.toBeInTheDocument();
    expect(screen.getByTestId('pipeline-status')).toHaveTextContent('生成完成');
  });

  it('done 帧直达 success：不触发 confirmExecution（流式路径无 executionId）', async () => {
    render(<WritingPage />);
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    await waitFor(() => expect(streamPipelineMock).toHaveBeenCalled());
    act(() => {
      capturedStream?.callbacks.onDone({ done: true, final_output: '确认后成品' });
    });
    expect(screen.getByTestId('pipeline-status')).toHaveTextContent('生成完成');
    expect(useChapterStore.getState().content).toBe('确认后成品');
    expect(confirmMock).not.toHaveBeenCalled();
  });

  it('onError 帧 → 生成失败展示；confirmExecution 不被调用', async () => {
    render(<WritingPage />);
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    await waitFor(() => expect(streamPipelineMock).toHaveBeenCalled());
    act(() => {
      capturedStream?.callbacks.onError('管线执行失败: 阶段 writer 重试耗尽');
    });
    expect(screen.getByTestId('pipeline-status')).toHaveTextContent(/生成失败/);
    expect(screen.queryByTestId('hitl-confirm-card')).not.toBeInTheDocument();
    expect(confirmMock).not.toHaveBeenCalled();
  });

  it('项目 config 含 supervisor.hitl_roles → 生成时 streamPipeline body 带 mode=supervisor', async () => {
    // 项目 config 携带 supervisor 配置（#343 拍板 2A：ProjectConfig.supervisor）
    useProjectStore.setState({
      projects: [
        {
          id: 'p1',
          name: '青云志',
          tags: ['玄幻'],
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
    await waitFor(() => expect(streamPipelineMock).toHaveBeenCalled());
    expect(streamPipelineMock).toHaveBeenCalledWith(
      expect.objectContaining({
        pipeline: 'builtin:write_auto',
        mode: 'supervisor',
        supervisor: { hitl_roles: ['reviser'] },
      }),
      expect.any(Object),
    );
  });
});

describe('写作页 — 底部续写栏 AI 聊天框（#519 S6a：chat 移到 ChapterEditor 之后）', () => {
  it('渲染 chat-panel（聊天输入框 + 发送按钮；空输入发送禁用）', () => {
    render(<WritingPage />);
    expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
    expect(screen.getByTestId('chat-input')).toBeInTheDocument();
    expect(screen.getByTestId('chat-send')).toBeDisabled();
  });

  it('chat 位于编辑器底部续写栏：ChapterEditor 之后、PipelineStatus 之前', () => {
    render(<WritingPage />);
    const editor = screen.getByTestId('editor');
    const toolbar = screen.getByTestId('editor-toolbar');
    // #476 契约：chat-panel 必须渲染在 editor main 内（旧实现是 main 外的底部兄弟节点）
    const chat = within(editor).getByTestId('chat-panel');
    // #476 契约：文档顺序上位于 editor-toolbar 之后
    expect(toolbar.compareDocumentPosition(chat) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // #519 契约（RED 主失败点）：chat 必须位于 ChapterEditor 之后（当前实现渲染在编辑器上方）
    const chapterEditor = screen.getByTestId('chapter-editor');
    expect(chapterEditor.compareDocumentPosition(chat) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // #585：idle 态不再渲染 PipelineStatus（空框）——此处不再断言「chat 在 PipelineStatus 之前」
    // （该顺序仅在 PipelineStatus 有状态时才有意义；本用例聚焦 chat 在编辑器内的位置）
  });
});

describe('写作页 — 视图切换（#379 F47 §4.2：正文编辑 ↔ AI 执行详情）', () => {
  it('默认 editor 视图：ChapterEditor 渲染、无 exec-detail', () => {
    render(<WritingPage />);
    expect(screen.getByTestId('chapter-editor')).toBeInTheDocument();
    expect(screen.queryByTestId('exec-detail')).not.toBeInTheDocument();
  });

  it('点 view-toggle → detail 视图：ExecutionDetailPanel 渲染（mock 轨迹数据）', async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/agent/pipelines/executions/e1') {
        return {
          execution_id: 'e1',
          pipeline: 'builtin:write_auto',
          project_id: 'p1',
          status: 'completed',
          stages: [
            { stage_id: 'architect', status: 'completed', output: '规划', error: '', retry_count: 0, duration_ms: 100 },
          ],
          trace: [
            { node: 'supervisor', type: 'decision', reasoning: '{"action":"execute","role":"architect"}', tool_calls: [], output: '', duration_ms: 30, ts: '2026-08-16T10:00:00Z' },
          ],
          relations: [],
          final_output: '成品',
          total_duration_ms: 800,
          error: '',
        };
      }
      if (path === '/api/v1/projects/p1/volumes') return { items: seedVolumes };
      if (path === '/api/v1/projects/p1/chapters') return { items: seedChapters, total: 2, offset: 0, limit: 50 };
      if (path.startsWith('/api/v1/chapters/')) return { ok: true };
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
    const user = userEvent.setup();
    render(<WritingPage />);
    // 未执行过管线 → detail 视图空态（exec-detail-empty）
    await user.click(screen.getByTestId('view-toggle'));
    expect(await screen.findByTestId('exec-detail-empty')).toBeInTheDocument();
    // 切回 editor 视图 → ChapterEditor 恢复
    await user.click(screen.getByTestId('view-toggle'));
    expect(screen.getByTestId('chapter-editor')).toBeInTheDocument();
  });
});

describe('写作页 — 模型未配置前置校验（#474 P0）', () => {
  /**
   * 契约：用户未配置模型（无 key_saved=true 的 chat provider）时，续写/生成入口：
   * - 不发 streamPipeline 请求（不发 AI 请求）
   * - toast 提示（type='warn'，文案引导去配置）
   * 已配置模型（beforeEach 默认播种 READY_PROVIDER）行为不变：正常 streamPipeline。
   *
   * i18n key（GREEN 补 zh.ts/en.ts）：common.modelNotConfigured
   */
  const unreadyMock = () => {
    useModelsStore.setState({ providers: [], loading: false, error: null });
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/provider-configs') {
        return { items: [], total: 0, offset: 0, limit: 50 };
      }
      if (path === '/api/v1/projects/p1/volumes') return { items: seedVolumes };
      if (path === '/api/v1/projects/p1/chapters') return { items: seedChapters, total: 2, offset: 0, limit: 50 };
      if (path.startsWith('/api/v1/chapters/') && init?.method === 'PATCH') return { ok: true };
      return { items: [], total: 0, offset: 0, limit: 50 };
    });
  };

  it('未配置模型 → 点「续写」按钮 → toast + 不发 streamPipeline', async () => {
    unreadyMock();
    render(<WritingPage />);
    fireEvent.click(screen.getByRole('button', { name: '续写' }));
    // async 守卫（ensureModelReady → loadProviders）在微任务后写 toast → waitFor 消化
    await waitFor(() => {
      expect(useToastStore.getState().toasts.some((t) => t.type === 'warn')).toBe(true);
      expect(useToastStore.getState().toasts.some((t) => t.message.includes('配置'))).toBe(true);
    });
    expect(streamPipelineMock).not.toHaveBeenCalled();
  });

  it('未配置模型 → 点「生成」按钮 → toast + 不发 streamPipeline', async () => {
    unreadyMock();
    render(<WritingPage />);
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    await waitFor(() => {
      expect(useToastStore.getState().toasts.some((t) => t.type === 'warn')).toBe(true);
    });
    expect(streamPipelineMock).not.toHaveBeenCalled();
  });

  it('未配置模型 → Ctrl+Enter 续写快捷键 → toast + 不发 streamPipeline', async () => {
    unreadyMock();
    render(<WritingPage />);
    fireEvent.keyDown(screen.getByTestId('chapter-editor'), { key: 'Enter', ctrlKey: true });
    await waitFor(() => {
      expect(useToastStore.getState().toasts.some((t) => t.type === 'warn')).toBe(true);
    });
    expect(streamPipelineMock).not.toHaveBeenCalled();
  });

  it('未配置模型 → Ctrl+Shift+Enter 生成快捷键 → toast + 不发 streamPipeline', async () => {
    unreadyMock();
    render(<WritingPage />);
    fireEvent.keyDown(screen.getByTestId('chapter-editor'), { key: 'Enter', ctrlKey: true, shiftKey: true });
    await waitFor(() => {
      expect(useToastStore.getState().toasts.some((t) => t.type === 'warn')).toBe(true);
    });
    expect(streamPipelineMock).not.toHaveBeenCalled();
  });

  it('已配置模型（默认播种）→ 点「生成」→ streamPipeline 正常（#642-1）', async () => {
    render(<WritingPage />);
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    await waitFor(() => {
      expect(streamPipelineMock).toHaveBeenCalledWith(
        expect.objectContaining({ pipeline: 'builtin:write_auto' }),
        expect.any(Object),
      );
    });
    // 旧 executePipeline 入口不再被调用（#642-1 替换断言）
    expect(executeMock).not.toHaveBeenCalled();
  });
});
