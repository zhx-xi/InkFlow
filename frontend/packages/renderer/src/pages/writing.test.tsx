/**
 * 写作页测试契约（Issue #79 RED 阶段，spec §4.2.1）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 WritingPage 必须匹配（行为断言，不测样式）：
 *
 * 结构 testid：
 * - 三栏: project-tree / editor / context-panel（既有占位已含）
 * - 项目树: 卷节点 data-testid="tree-volume"、章节点 data-testid="tree-chapter"
 *   当前章节点 data-current="true"（高亮为视觉契约，行为契约 = data-current 标记）
 * - 项目印章: data-testid="project-seal"，文本 = 书名关键字
 *   （design 已知项 #3 规则待用户拍板；测试按「首字」假设，GREEN 若拍板其他规则可调整，常驻断言不变）
 * - 工具栏: data-testid="editor-toolbar"；按钮 撤销/重做/续写/生成（i18n 文案）、保存 data-testid="toolbar-save"
 * - 编辑器正文: data-testid="chapter-editor"（textarea，段落化纯文本）
 * - 上下文: 折叠按钮 data-testid="context-collapse"、内容区 data-testid="context-panel-content"、
 *   折叠后展开条 data-testid="context-expand-bar"（26px 宽度为视觉契约，行为契约 = 折叠/展开闭环）
 * - SSE 流式区: data-testid="stream-area"；生成中 live 标记文案「生成中」+ 停止按钮「停止」；
 *   done 摘要行（i18n write.stream.done 模板）；format_valid=false → warnings 逐条 + 「重试」按钮
 *
 * 快捷键（Q2 拍板 C，监听在编辑器容器）：
 * - Ctrl+Z → document.execCommand('undo')；Ctrl+Y → execCommand('redo')
 * - Ctrl+S → chapterStore.saveContent()（PATCH /api/v1/chapters/{id}）
 * - Ctrl+Enter → 续写（useStream start('continue')，POST /writing/stream）
 * - Ctrl+Shift+Enter → 生成（useStream start('generate')）
 *
 * 印章常驻：三主题（paper/night/ink）下均显示（颜色跟随 accent 为视觉契约）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { WritingPage } from './writing';
import { apiFetch } from '../api/client';
import { useChapterStore } from '../stores/chapter';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

/** 与后端对齐的种子数据（mock 与 store 播种共用，防 GREEN 自动加载覆盖种子） */
const seedVolumes = [
  { id: 'v1', title: '第一卷 风起', order_index: 0 },
];
const seedChapters = [
  { id: 'c1', title: '第1章 初见', volume_id: 'v1', order_index: 0, word_count: 2347 },
  { id: 'c2', title: '第2章 夜谈', volume_id: 'v1', order_index: 1, word_count: 0 },
];

function createControllableStream() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({ start(c) { controller = c; } });
  return { stream, controller };
}
function frame(payload: Record<string, unknown>): Uint8Array {
  return new TextEncoder().encode(`data: ${JSON.stringify(payload)}\n\n`);
}

let streamControllers: ReadableStreamDefaultController<Uint8Array>[] = [];

function stubStreamFetch() {
  const fetchMock = vi.fn(() => {
    const { stream, controller } = createControllableStream();
    streamControllers.push(controller);
    return Promise.resolve({ ok: true, body: stream } as unknown as Response);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

beforeEach(() => {
  apiFetchMock.mockReset();
  vi.unstubAllGlobals();
  streamControllers = [];
  window.INKFLOW_API = { baseURL: 'http://test.local', token: 'tok-1' };
  localStorage.clear();

  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useChapterStore.setState({
    volumes: seedVolumes, chapters: seedChapters, currentChapterId: 'c1', content: '已有正文第一段。', loading: false, error: null,
  });
  useProjectStore.setState({
    projects: [{ id: 'p1', name: '青云志', genre: '玄幻', language: 'zh-CN', target_words: 800000, config: {}, created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z' }],
    currentProjectId: 'p1', loading: false, error: null,
  });

  // REST mock：自动加载/保存路径返回种子或空（防 GREEN 挂载自动加载覆盖）
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === '/api/v1/projects/p1/volumes') return seedVolumes;
    if (path === '/api/v1/projects/p1/chapters') return { items: seedChapters, total: 2, offset: 0, limit: 50 };
    if (path.startsWith('/api/v1/chapters/') && init?.method === 'PATCH') return { ok: true };
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

afterEach(() => {
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
    expect(ch1).toHaveTextContent(/2,?347/); // 章节字数
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
    // 设计假设：印章文字 = 书名首字（design 已知项 #3 规则待拍板）
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
    // jsdom 无 document.execCommand（spyOn 会抛 "does not exist"）→ defineProperty 注入
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

  it('Ctrl+Enter 续写：发起 continue 流（POST /writing/stream）', async () => {
    stubStreamFetch();
    render(<WritingPage />);
    fireEvent.keyDown(screen.getByTestId('chapter-editor'), { key: 'Enter', ctrlKey: true });
    await waitFor(() => expect(screen.getByText('生成中')).toBeInTheDocument());
    const fetchMock = vi.mocked(globalThis.fetch);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/writing/stream');
    expect(JSON.parse(String(init.body))).toMatchObject({ mode: 'continue' });
  });

  it('Ctrl+Shift+Enter 生成：发起 generate 流', async () => {
    stubStreamFetch();
    render(<WritingPage />);
    fireEvent.keyDown(screen.getByTestId('chapter-editor'), { key: 'Enter', ctrlKey: true, shiftKey: true });
    await waitFor(() => expect(screen.getByText('生成中')).toBeInTheDocument());
    const fetchMock = vi.mocked(globalThis.fetch);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toMatchObject({ mode: 'generate' });
  });
});

describe('写作页 — SSE 流式区（§4.5）', () => {
  it('续写：live 标记 + 停止按钮 → delta 逐段渲染 → done 摘要行 + store 提交', async () => {
    const user = userEvent.setup();
    stubStreamFetch();
    render(<WritingPage />);

    await user.click(screen.getByRole('button', { name: '续写' }));
    expect(screen.getByText('生成中')).toBeInTheDocument(); // live 标记
    expect(screen.getByRole('button', { name: '停止' })).toBeInTheDocument();

    const ctl = streamControllers[0];
    act(() => {
      ctl.enqueue(frame({ delta: '流式第一段', done: false }));
    });
    await waitFor(() => {
      expect(screen.getByTestId('stream-area')).toHaveTextContent('流式第一段');
    });

    act(() => {
      ctl.enqueue(frame({ delta: '，流式第二段。', done: false }));
    });
    await waitFor(() => {
      expect(screen.getByTestId('stream-area')).toHaveTextContent('流式第一段，流式第二段。');
    });

    act(() => {
      ctl.enqueue(frame({ done: true, format_valid: true, word_count: 342, model: 'gpt-4o', warnings: [] }));
    });
    // done 摘要行：已生成 342 字 · 模型 gpt-4o · 格式校验通过
    await waitFor(() => {
      expect(screen.getByTestId('stream-area')).toHaveTextContent(/342/);
      expect(screen.getByTestId('stream-area')).toHaveTextContent('gpt-4o');
      expect(screen.getByTestId('stream-area')).toHaveTextContent('格式校验通过');
    });
    // 停止按钮消失 + store 一次性提交
    expect(screen.queryByRole('button', { name: '停止' })).not.toBeInTheDocument();
    expect(useChapterStore.getState().content).toBe('流式第一段，流式第二段。');
  });

  it('format_valid=false：warnings 逐条展示 + 重试按钮（不自动重试）', async () => {
    const user = userEvent.setup();
    stubStreamFetch();
    render(<WritingPage />);

    await user.click(screen.getByRole('button', { name: '续写' }));
    const ctl = streamControllers[0];
    act(() => {
      ctl.enqueue(frame({ delta: '草稿', done: false }));
    });
    await waitFor(() => expect(screen.getByTestId('stream-area')).toHaveTextContent('草稿'));
    act(() => {
      ctl.enqueue(frame({ done: true, format_valid: false, word_count: 4, model: 'gpt-4o', warnings: ['章节开头缺少主角名'] }));
    });

    await waitFor(() => {
      expect(screen.getByText('章节开头缺少主角名')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument();
      expect(screen.getByTestId('stream-area')).toHaveTextContent('格式校验未通过');
    });
    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledTimes(1); // 不自动重试
  });

  it('停止：点击停止 → 生成中断文案 + 已生成前文保留', async () => {
    const user = userEvent.setup();
    stubStreamFetch();
    render(<WritingPage />);

    await user.click(screen.getByRole('button', { name: '续写' }));
    const ctl = streamControllers[0];
    act(() => {
      ctl.enqueue(frame({ delta: '部分生成内容', done: false }));
    });
    await waitFor(() => expect(screen.getByTestId('stream-area')).toHaveTextContent('部分生成内容'));

    await user.click(screen.getByRole('button', { name: '停止' }));
    expect(screen.getByText('生成中断 · 已保留前文')).toBeInTheDocument();
    expect(screen.getByTestId('stream-area')).toHaveTextContent('部分生成内容');
  });
});
