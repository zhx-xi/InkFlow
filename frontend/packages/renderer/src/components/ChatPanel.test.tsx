/**
 * 聊天框契约（spec §4.1）：底部 AI 聊天框 ChatPanel（#541 流式重写版）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 ChatPanel 必须匹配（行为断言，不测样式）。
 *
 * #541 机制变更（相对 #477 轮询版）：
 * - 发送 = streamChat({project_id, prompt, chapter_id?, chapter_context?}, callbacks)
 *   （POST /api/v1/chat/stream，SSE 帧 {delta, done, error}，src/api/chat.ts GREEN 建）
 * - 流式渐进追加：delta 帧逐字追加到当前 ai 消息（不是 done 一次性出现）
 * - done 帧 → 最终文本用 parseChatReply 解析意图（#477 保留）
 * - error 帧 → 错误文案（write.chat.failed 含「对话失败」），不插入正文
 * - 并发保护：流式 in-flight 时再次发送不触发第二次 streamChat；done/error 后可继续对话
 *
 * hermes 风格 UI 契约（#541 新增）：
 * - 消息容器分列：user 消息 data-side="user"（靠右），ai 消息 data-side="ai"（靠左）
 * - 每条消息含角色标签 data-testid="chat-msg-role"
 *   （user → t('write.chat.user')='你'，ai → t('write.chat.ai')='AI'）
 * - chat-messages 容器 className 含 space-y-3（消息间空行；只锁工具类，不锁完整 class 串）
 *
 * 结构 testid：chat-panel / chat-input / chat-send / chat-msg-user-<n> / chat-msg-ai-<n>
 * / chat-select-<n>（content 意图选择控件，data-selected 选中态）/ chat-insert-selected
 *
 * 保留契约（#474/#476/#477，GREEN 必须保持）：
 * - 空输入发送禁用；折叠态发送自动展开；展开/收缩/拖动（data-height）
 * - 模型未配置前置校验：ensureModelReady 失败 → toast（common.modelNotConfigured）+ 不发请求
 * - 意图分离：content → 只显示 body + chat-select-<n> 自动选中；conversation → 完整原文无控件
 * - chat-insert-selected 只插入选中条 body（不自动保存，F27 save 流）
 *
 * i18n key（GREEN 补）：write.chat.user='你' / write.chat.ai='AI'
 * （write.chat.placeholder/send/insert/inserted/failed/select/expand/collapse 已存在）
 *
 * mock 方式：vi.mock('../api/chat') → streamChat 捕获 body+callbacks（模块级 capturedStreams），
 * 用例手动驱动 onDelta/onDone/onError（镜像 useExecutionPoll mock 套路；SSE 手动驱动约定）
 *
 * #547 持久化契约（「历史加载与消息持久化」describe 锁定，GREEN 追加实现）：
 * - 挂载 / projectId 变化 → fetchChatMessages(projectId) 加载历史（beforeEach 默认空列表）；
 *   历史 AI 消息 intent 保留（content → chat-select 最新自动选中；conversation → 无控件）
 * - 历史加载失败静默：不发 toast，后续发送仍可用
 * - 发送用户消息 → saveChatMessage({project_id, role:'user', content: prompt})（fire-and-forget）
 * - AI 回复 done → saveChatMessage({project_id, role:'ai', content: 最终文本, intent: 解析后意图})
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatPanel } from './ChatPanel';
import { apiFetch } from '../api/client';
import { executePipeline, getExecutionStatus } from '../api/pipeline';
import { useChapterStore } from '../stores/chapter';
import { useThemeStore } from '../stores/theme';
import { useModelsStore, type ProviderConfig } from '../stores/models';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});
// #541：轮询已替换为 SSE 流式。pipeline mock 保留仅为让旧实现惰性（GREEN 删除轮询后由流式契约接管）
vi.mock('../api/pipeline', () => ({
  executePipeline: vi.fn(),
  getExecutionStatus: vi.fn(),
  confirmExecution: vi.fn(),
}));

/** #547：chat api 模块 mock 聚合（streamChat + 消息 CRUD），vi.hoisted 供 vi.mock 工厂引用 */
const chatApiMocks = vi.hoisted(() => ({
  streamChat: vi.fn(),
  fetchChatMessages: vi.fn(),
  saveChatMessage: vi.fn(),
  fetchChatConversations: vi.fn(),
}));
vi.mock('../api/chat', () => chatApiMocks);

// #541 既有引用别名（既有 26 用例的 streamChatMock 行为不变）
const streamChatMock = chatApiMocks.streamChat;

const executeMock = vi.mocked(executePipeline);
const statusMock = vi.mocked(getExecutionStatus);
const apiFetchMock = vi.mocked(apiFetch);

/** 与 src/api/chat.ts 契约一致（GREEN 建）：本地镜像类型，避免依赖未建模块 */
interface ChatStreamBody {
  project_id: string;
  prompt: string;
  chapter_id?: string;
  chapter_context?: string;
}
interface ChatStreamFrame {
  done: boolean;
  delta?: string;
  error?: string;
}
interface ChatStreamCallbacks {
  onDelta: (delta: string) => void;
  onDone: (frame: ChatStreamFrame) => void;
  onError: (message: string) => void;
}
interface CapturedChatStream {
  body: ChatStreamBody;
  callbacks: ChatStreamCallbacks;
}

/** #547：ChatMessageDto 本地镜像（GREEN 建 src/api/chat.ts 导出；形状对齐后端 GET/POST /api/v1/chat/messages 契约） */
interface ChatMessageDto {
  id: string;
  project_id: string;
  role: 'user' | 'ai';
  content: string;
  intent: 'content' | 'conversation' | null;
  created_at: string;
}

const OPTS = { projectId: 'p1', chapterId: 'c1', chapterContent: '已有正文第一段。' };

/** #474：已配置模型（key_saved=true + chat 模型）种子 provider——模拟用户在模型管理页保存过 Key */
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

/** 每次 streamChat 调用的捕获（body + callbacks），用例手动驱动 SSE 帧 */
let capturedStreams: CapturedChatStream[] = [];

/** 输入 + 点发送；等待第 index+1 次 streamChat 被调用（index 默认 0 = 最近一次） */
async function sendAndAwaitStream(
  user: ReturnType<typeof userEvent.setup>,
  text: string,
  index = 0,
) {
  await user.type(screen.getByTestId('chat-input'), text);
  await user.click(screen.getByTestId('chat-send'));
  await waitFor(() => {
    expect(streamChatMock).toHaveBeenCalledTimes(index + 1);
  });
}

/** 手动驱动第 index 次流的 delta 帧（渐进追加契约核心） */
function emitDelta(index: number, delta: string) {
  act(() => {
    capturedStreams[index].callbacks.onDelta(delta);
  });
}

/** 手动驱动第 index 次流的 done 帧 */
function emitDone(index: number, frame?: Partial<ChatStreamFrame>) {
  act(() => {
    capturedStreams[index].callbacks.onDone({ done: true, ...frame });
  });
}

/** 手动驱动第 index 次流的 error 帧 */
function emitError(index: number, message: string) {
  act(() => {
    capturedStreams[index].callbacks.onError(message);
  });
}

/** content 意图回复：delta 分两帧累积（含标记）+ done */
function driveContentReply(index: number, body: string) {
  emitDelta(index, '好的，以下是续写内容：');
  emitDelta(index, `\n<<<CONTENT>>>\n${body}\n<<<END>>>`);
  emitDone(index);
}

/** conversation 意图回复：单帧 delta + done */
function driveConversationReply(index: number, text: string) {
  emitDelta(index, text);
  emitDone(index);
}

beforeEach(() => {
  streamChatMock.mockReset();
  capturedStreams = [];
  // #547：历史加载/持久化 mock 默认值——历史空列表（既有用例行为不变）；save 默认成功返回（fire-and-forget 不消费返回值）
  chatApiMocks.fetchChatMessages.mockReset();
  chatApiMocks.saveChatMessage.mockReset();
  chatApiMocks.fetchChatConversations.mockReset();
  chatApiMocks.fetchChatMessages.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
  chatApiMocks.saveChatMessage.mockResolvedValue({
    id: 'm-new',
    project_id: 'p1',
    role: 'user',
    content: '',
    intent: null,
    created_at: '2026-08-21T10:00:00Z',
  });
  chatApiMocks.fetchChatConversations.mockResolvedValue({ items: [], total: 0 });
  // 默认 mock：返回 abort 函数 + 捕获 callbacks 供用例手动驱动（镜像 useExecutionPoll mock 套路）
  streamChatMock.mockImplementation(
    (body: ChatStreamBody, callbacks: ChatStreamCallbacks) => {
      capturedStreams.push({ body, callbacks });
      return Promise.resolve(() => {});
    },
  );
  executeMock.mockReset();
  statusMock.mockReset();
  apiFetchMock.mockReset();
  // #474 前置校验依赖 models store：默认播种「已配置」让既有用例行为不变；未配置用例自行 setState 覆盖为空
  useModelsStore.setState({ providers: [READY_PROVIDER], loading: false, error: null });
  useToastStore.setState({ toasts: [] });
  // URL 分发：provider-configs 返回已配置（防 GREEN 挂载/发送时 loadProviders 覆盖播种）；其余端点返回通用成功
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/provider-configs') {
      return { items: [READY_PROVIDER], total: 1, offset: 0, limit: 50 };
    }
    return { ok: true };
  });
  // 旧轮询 mock 惰性化（GREEN 前的当前实现走 useExecutionPoll）：execute 正常、轮询永不完成
  executeMock.mockResolvedValue({
    execution_id: 'e-chat-1',
    pipeline: 'builtin:chat',
    project_id: 'p1',
    status: 'pending',
    created_at: '',
  });
  statusMock.mockResolvedValue({
    execution_id: 'e-chat-1',
    pipeline: 'builtin:chat',
    project_id: 'p1',
    status: 'pending',
    stages: [],
    trace: [],
    final_output: '',
    total_duration_ms: 0,
    error: '',
  });
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useChapterStore.setState({
    volumes: [],
    chapters: [],
    treeProjectId: 'p1',
    currentChapterId: 'c1',
    content: '已有正文第一段。',
    loading: false,
    error: null,
  });
});

describe('ChatPanel — 聊天输入与发送', () => {
  it('渲染 chat-panel / chat-input / chat-send；空输入发送禁用', () => {
    render(<ChatPanel {...OPTS} />);
    expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
    expect(screen.getByTestId('chat-input')).toBeInTheDocument();
    expect(screen.getByTestId('chat-send')).toBeDisabled();
  });

  it('输入 + 发送 → streamChat 调用（body: project_id/prompt/chapter_id/chapter_context + callbacks）', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '帮我写一段打斗场景');

    expect(capturedStreams[0].body).toEqual({
      project_id: 'p1',
      prompt: '帮我写一段打斗场景',
      chapter_id: 'c1',
      chapter_context: '已有正文第一段。',
    });
    // callbacks 三回调齐备（GREEN 由 streamChat 驱动）
    expect(typeof capturedStreams[0].callbacks.onDelta).toBe('function');
    expect(typeof capturedStreams[0].callbacks.onDone).toBe('function');
    expect(typeof capturedStreams[0].callbacks.onError).toBe('function');
  });

  it('chapterContent 为空 → body 无 chapter_context 字段', async () => {
    const user = userEvent.setup();
    render(<ChatPanel projectId="p1" chapterId="c1" chapterContent="" />);
    await sendAndAwaitStream(user, '你好');

    expect(capturedStreams[0].body.prompt).toBe('你好');
    expect(capturedStreams[0].body.chapter_context).toBeUndefined();
  });
});

describe('ChatPanel — 流式回复（#541 SSE 渐进追加）', () => {
  it('渐进追加：onDelta("你") → ai 消息显示 "你"；再 onDelta("好") → "你好"（不是 done 一次性出现）', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '写一个开头');
    // 用户消息立即展示
    expect(screen.getByTestId('chat-msg-user-0')).toHaveTextContent('写一个开头');
    // 第一个 delta 到达 → ai 消息出现且只含 '你'
    emitDelta(0, '你');
    expect(screen.getByTestId('chat-msg-ai-0')).toHaveTextContent('你');
    // 第二个 delta → 追加为 '你好'
    emitDelta(0, '好');
    expect(screen.getByTestId('chat-msg-ai-0')).toHaveTextContent('你好');
    // done 收尾 → 文本保持完整
    emitDone(0);
    expect(screen.getByTestId('chat-msg-ai-0')).toHaveTextContent('你好');
  });

  it('done 帧 → 最终文本用 parseChatReply 解析意图：content 只显示 body + 自动选中 + 共享插入按钮', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '解释这个角色的动机');
    // 流式原文渐进累积（done 前展示原文，含标记）
    emitDelta(0, '好的，以下是续写内容：');
    emitDelta(0, '\n<<<CONTENT>>>\n他握紧了剑。\n<<<END>>>');
    emitDone(0);
    // done 后意图分离：只显示提取 body，不显示标记与前言
    expect(screen.getByTestId('chat-msg-ai-0')).toHaveTextContent('他握紧了剑。');
    expect(screen.getByTestId('chat-msg-ai-0')).not.toHaveTextContent('好的，以下是续写内容');
    expect(screen.getByTestId('chat-msg-ai-0')).not.toHaveTextContent('<<<CONTENT>>>');
    expect(screen.getByTestId('chat-msg-ai-0')).not.toHaveTextContent('<<<END>>>');
    // content 消息：选择控件存在且自动选中
    expect(screen.getByTestId('chat-select-0')).toHaveAttribute('data-selected', 'true');
    // 共享插入按钮存在；旧 per-message 按钮不存在（#477 已删除）
    expect(screen.getByTestId('chat-insert-selected')).toBeInTheDocument();
    expect(screen.queryByTestId('chat-insert-0')).toBeNull();
  });

  it('conversation 回复（无标记）→ 显示完整原文，无选择控件、无插入按钮', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '聊聊角色设定');
    emitDelta(0, '对话回复内容');
    emitDone(0);
    expect(screen.getByTestId('chat-msg-ai-0')).toHaveTextContent('对话回复内容');
    expect(screen.queryByTestId('chat-select-0')).not.toBeInTheDocument();
    expect(screen.queryByTestId('chat-insert-selected')).not.toBeInTheDocument();
  });

  it('onError → 错误文案（write.chat.failed 含「对话失败」），不插入正文', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '你好');
    emitError(0, '模型超时');
    expect(screen.getByTestId('chat-panel')).toHaveTextContent(/对话失败/);
    expect(screen.getByTestId('chat-panel')).toHaveTextContent('模型超时');
    expect(useChapterStore.getState().content).toBe('已有正文第一段。');
  });
});

describe('ChatPanel — hermes 风格 UI（#541）', () => {
  it('消息分列：user 消息 data-side="user"（靠右），ai 消息 data-side="ai"（靠左）', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '分列测试');
    emitDelta(0, 'AI 回复');
    expect(screen.getByTestId('chat-msg-user-0')).toHaveAttribute('data-side', 'user');
    expect(screen.getByTestId('chat-msg-ai-0')).toHaveAttribute('data-side', 'ai');
  });

  it('角色标签 chat-msg-role：user 显示 t("write.chat.user")="你"，ai 显示 t("write.chat.ai")="AI"', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '角色标签');
    emitDelta(0, 'AI 回复');
    expect(within(screen.getByTestId('chat-msg-user-0')).getByTestId('chat-msg-role')).toHaveTextContent(
      '你',
    );
    expect(within(screen.getByTestId('chat-msg-ai-0')).getByTestId('chat-msg-role')).toHaveTextContent(
      'AI',
    );
  });

  it('消息间空行：chat-messages 容器 className 含 space-y-3', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '空行测试');
    expect(screen.getByTestId('chat-messages').className).toContain('space-y-3');
  });
});

describe('ChatPanel — 展开/收缩/拖动（#476 保留契约）', () => {
  it('默认折叠：chat-messages 不渲染；chat-expand 可见', () => {
    render(<ChatPanel {...OPTS} />);
    expect(screen.getByTestId('chat-expand')).toBeInTheDocument();
    expect(screen.queryByTestId('chat-messages')).not.toBeInTheDocument();
  });

  it('折叠态发送消息 → 自动展开：chat-messages 出现 + 用户消息可见 + chat-collapse 可见', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    expect(screen.queryByTestId('chat-messages')).not.toBeInTheDocument();
    await user.type(screen.getByTestId('chat-input'), '自动展开测试');
    await user.click(screen.getByTestId('chat-send'));
    expect(screen.getByTestId('chat-messages')).toBeInTheDocument();
    expect(screen.getByTestId('chat-msg-user-0')).toHaveTextContent('自动展开测试');
    expect(screen.getByTestId('chat-collapse')).toBeInTheDocument();
  });

  it('收缩 → chat-messages 隐藏；再展开 → 历史消息保留', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await user.type(screen.getByTestId('chat-input'), '保留测试');
    await user.click(screen.getByTestId('chat-send'));
    expect(screen.getByTestId('chat-messages')).toBeInTheDocument();
    await user.click(screen.getByTestId('chat-collapse'));
    expect(screen.queryByTestId('chat-messages')).not.toBeInTheDocument();
    expect(screen.getByTestId('chat-expand')).toBeInTheDocument();
    await user.click(screen.getByTestId('chat-expand'));
    expect(screen.getByTestId('chat-messages')).toBeInTheDocument();
    expect(screen.getByTestId('chat-msg-user-0')).toHaveTextContent('保留测试');
  });

  it('展开/收缩按钮在消息区之前（#542：按钮应在对话区顶部）', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await user.type(screen.getByTestId('chat-input'), '按钮位置');
    await user.click(screen.getByTestId('chat-send'));
    const btn = screen.getByTestId('chat-collapse');
    const msgs = screen.getByTestId('chat-messages');
    expect(btn.compareDocumentPosition(msgs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await user.click(screen.getByTestId('chat-collapse'));
    const btn2 = screen.getByTestId('chat-expand');
    const input = screen.getByTestId('chat-input');
    expect(btn2.compareDocumentPosition(input) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('鼠标拖动调整对话区高度（handle mousedown → window mousemove 向上拖 → data-height 增大）', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await user.type(screen.getByTestId('chat-input'), '拖拽高度');
    await user.click(screen.getByTestId('chat-send'));
    const messages = screen.getByTestId('chat-messages');
    const before = messages.getAttribute('data-height');
    expect(before).toBeTruthy();
    const handle = screen.getByTestId('chat-resize-handle');
    fireEvent.mouseDown(handle, { clientX: 100, clientY: 120 });
    fireEvent.mouseMove(window, { clientX: 100, clientY: 80 }); // 向上拖 40px → 高度增大
    fireEvent.mouseUp(window);
    const after = messages.getAttribute('data-height');
    expect(after).toBeTruthy();
    expect(Number(after)).toBeGreaterThan(Number(before));
  });
});

describe('ChatPanel — 模型未配置前置校验（#474 保留契约）', () => {
  it('未配置模型（providers 空）→ 点发送 → toast 提示 + 不调 streamChat', async () => {
    useModelsStore.setState({ providers: [], loading: false, error: null });
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/provider-configs') {
        return { items: [], total: 0, offset: 0, limit: 50 };
      }
      return { ok: true };
    });
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await user.type(screen.getByTestId('chat-input'), '帮我写一段打斗场景');
    await user.click(screen.getByTestId('chat-send'));
    expect(useToastStore.getState().toasts.some((t) => t.type === 'warn')).toBe(true);
    expect(useToastStore.getState().toasts.some((t) => t.message.includes('配置'))).toBe(true);
    expect(streamChatMock).not.toHaveBeenCalled();
  });

  it('未配置模型（provider 存在但 key_saved=false）→ 点发送 → toast + 不调 streamChat', async () => {
    useModelsStore.setState({
      providers: [
        {
          id: 1,
          name: 'openai',
          base_url: 'https://api.openai.com/v1',
          default_model: 'gpt-4o',
          models: [{ id: 'gpt-4o', type: 'chat', roles: ['main'] }],
          key_saved: false,
          max_retries: 3,
          timeout: 60,
          created_at: '2026-08-01T10:00:00Z',
          updated_at: '2026-08-05T10:00:00Z',
        },
      ],
      loading: false,
      error: null,
    });
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/provider-configs') {
        return { items: [], total: 0, offset: 0, limit: 50 };
      }
      return { ok: true };
    });
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await user.type(screen.getByTestId('chat-input'), '你好');
    await user.click(screen.getByTestId('chat-send'));
    expect(useToastStore.getState().toasts.some((t) => t.type === 'warn')).toBe(true);
    expect(streamChatMock).not.toHaveBeenCalled();
  });

  it('Enter 键发送同样走前置校验（未配置 → toast + 不调 streamChat）', async () => {
    useModelsStore.setState({ providers: [], loading: false, error: null });
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/provider-configs') {
        return { items: [], total: 0, offset: 0, limit: 50 };
      }
      return { ok: true };
    });
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await user.type(screen.getByTestId('chat-input'), '回车发送');
    await user.keyboard('{Enter}');
    expect(useToastStore.getState().toasts.some((t) => t.type === 'warn')).toBe(true);
    expect(streamChatMock).not.toHaveBeenCalled();
  });

  it('已配置模型（默认播种）→ 发送 → streamChat 调用（body 含 project_id + prompt）', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '已配置模型对话');
    expect(capturedStreams[0].body).toEqual(
      expect.objectContaining({ project_id: 'p1', prompt: '已配置模型对话' }),
    );
  });
});

describe('ChatPanel — 意图分离与多生成单选插入（#477 保留契约，流式版）', () => {
  it('混合：第 1 条 content + 第 2 条 conversation → 仅 content 条可选，选中仍在 seq 0', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '写一段打斗', 0);
    driveContentReply(0, '他握紧了剑。');
    expect(screen.getByTestId('chat-select-0')).toHaveAttribute('data-selected', 'true');
    await sendAndAwaitStream(user, '谢谢', 1);
    driveConversationReply(1, '不客气，随时再聊');
    expect(screen.queryByTestId('chat-select-1')).not.toBeInTheDocument();
    expect(screen.getByTestId('chat-insert-selected')).toBeInTheDocument();
    expect(screen.getByTestId('chat-select-0')).toHaveAttribute('data-selected', 'true');
  });

  it('两条 content → 均渲染选择控件；新到第 2 条自动选中（互斥）', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '写第一段', 0);
    driveContentReply(0, '第一段正文。');
    await sendAndAwaitStream(user, '写第二段', 1);
    driveContentReply(1, '第二段正文。');
    expect(screen.getByTestId('chat-select-0')).toBeInTheDocument();
    expect(screen.getByTestId('chat-select-1')).toBeInTheDocument();
    expect(screen.getByTestId('chat-select-1')).toHaveAttribute('data-selected', 'true');
    expect(screen.getByTestId('chat-select-0')).toHaveAttribute('data-selected', 'false');
    expect(screen.getByTestId('chat-insert-selected')).toBeInTheDocument();
    expect(screen.queryByTestId('chat-insert-0')).toBeNull();
  });

  it('点 chat-select-0 → 选中切换到第 1 条（互斥）', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '写第一段', 0);
    driveContentReply(0, '第一段正文。');
    await sendAndAwaitStream(user, '写第二段', 1);
    driveContentReply(1, '第二段正文。');
    await user.click(screen.getByTestId('chat-select-0'));
    expect(screen.getByTestId('chat-select-0')).toHaveAttribute('data-selected', 'true');
    expect(screen.getByTestId('chat-select-1')).toHaveAttribute('data-selected', 'false');
  });

  it('选中第 1 条后点插入 → 只插入选中条 body（+ toast 已插入正文）', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '写第一段', 0);
    driveContentReply(0, '第一段正文。');
    await sendAndAwaitStream(user, '写第二段', 1);
    driveContentReply(1, '第二段正文。');
    await user.click(screen.getByTestId('chat-select-0'));
    await user.click(screen.getByTestId('chat-insert-selected'));
    expect(useChapterStore.getState().content).toBe('第一段正文。');
    expect(useToastStore.getState().toasts.some((t) => t.message.includes('已插入正文'))).toBe(true);
  });

  it('不手动切换（默认最新选中）点插入 → 插入第 2 条 body', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '写第一段', 0);
    driveContentReply(0, '第一段正文。');
    await sendAndAwaitStream(user, '写第二段', 1);
    driveContentReply(1, '第二段正文。');
    await user.click(screen.getByTestId('chat-insert-selected'));
    expect(useChapterStore.getState().content).toBe('第二段正文。');
  });
});

describe('ChatPanel — 失败与并发保护（#541 流式版）', () => {
  it('流式 in-flight 时再次发送 → 不触发第二次 streamChat', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '第一条', 0);
    // 流式进行中（未 onDone）：再次输入并发送 → 无第二次 streamChat
    await user.type(screen.getByTestId('chat-input'), '第二条');
    await user.click(screen.getByTestId('chat-send'));
    expect(streamChatMock).toHaveBeenCalledTimes(1);
    // 收尾：done 结束流
    emitDone(0);
  });

  it('onDone 结束后再次发送 → 触发第二次 streamChat（对话可继续）', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '第一条', 0);
    driveConversationReply(0, '回复一');
    await sendAndAwaitStream(user, '第二条', 1);
    driveConversationReply(1, '回复二');
    expect(screen.getByTestId('chat-msg-ai-0')).toHaveTextContent('回复一');
    expect(screen.getByTestId('chat-msg-ai-1')).toHaveTextContent('回复二');
  });
});

describe('ChatPanel — 历史加载与消息持久化（#547）', () => {
  /** 历史消息 fixture（后端 GET /api/v1/chat/messages 时间升序；seq 按 role 独立从 0 起） */
  const HISTORY: ChatMessageDto[] = [
    { id: 'm1', project_id: 'p1', role: 'user', content: '之前的提问', intent: null, created_at: '2026-08-20T08:00:00Z' },
    { id: 'm2', project_id: 'p1', role: 'ai', content: '之前的对话回答', intent: 'conversation', created_at: '2026-08-20T08:01:00Z' },
    { id: 'm3', project_id: 'p1', role: 'ai', content: '可插入正文', intent: 'content', created_at: '2026-08-20T08:02:00Z' },
  ];

  it('挂载即加载历史：fetchChatMessages(projectId)；已存 user/ai 消息按 role 独立 seq 渲染', async () => {
    chatApiMocks.fetchChatMessages.mockResolvedValue({ items: HISTORY, total: 3, offset: 0, limit: 50 });
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    // 挂载（projectId 变化同理）→ 以 projectId 拉取历史
    await waitFor(() => {
      expect(chatApiMocks.fetchChatMessages).toHaveBeenCalledWith('p1');
    });
    // 历史消息落入消息区（seq 从 0 起：user/ai 各自独立计数）
    await user.click(screen.getByTestId('chat-expand'));
    expect(screen.getByTestId('chat-msg-user-0')).toHaveTextContent('之前的提问');
    expect(screen.getByTestId('chat-msg-ai-0')).toHaveTextContent('之前的对话回答');
    expect(screen.getByTestId('chat-msg-ai-1')).toHaveTextContent('可插入正文');
  });

  it('历史 AI 消息 intent 保留：content → chat-select 渲染且最新自动选中；conversation → 无选择控件', async () => {
    chatApiMocks.fetchChatMessages.mockResolvedValue({ items: HISTORY, total: 3, offset: 0, limit: 50 });
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await waitFor(() => {
      expect(chatApiMocks.fetchChatMessages).toHaveBeenCalled();
    });
    await user.click(screen.getByTestId('chat-expand'));
    // conversation 条（ai seq 0）无选择控件
    expect(screen.queryByTestId('chat-select-0')).not.toBeInTheDocument();
    // content 条（ai seq 1）有选择控件且为最新 content 自动选中；共享插入按钮出现
    expect(screen.getByTestId('chat-select-1')).toHaveAttribute('data-selected', 'true');
    expect(screen.getByTestId('chat-insert-selected')).toBeInTheDocument();
  });

  it('历史加载失败静默：无 toast；发送仍可用（streamChat 正常触发）', async () => {
    chatApiMocks.fetchChatMessages.mockRejectedValue(new Error('network down'));
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await waitFor(() => {
      expect(chatApiMocks.fetchChatMessages).toHaveBeenCalled();
    });
    // 契约：失败不打扰——不发 toast
    expect(useToastStore.getState().toasts).toHaveLength(0);
    // 后续发送仍可用
    await sendAndAwaitStream(user, '故障后仍可对话');
    expect(capturedStreams[0].body.prompt).toBe('故障后仍可对话');
  });

  it('发送用户消息 → saveChatMessage({project_id, role:"user", content})（fire-and-forget，intent 缺省）', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '帮我写一段打斗场景');
    expect(chatApiMocks.saveChatMessage).toHaveBeenCalledWith({
      project_id: 'p1',
      role: 'user',
      content: '帮我写一段打斗场景',
    });
  });

  it('AI conversation 回复完成（onDone）→ saveChatMessage({project_id, role:"ai", content: 完整文本, intent:"conversation"})', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '聊聊角色设定');
    driveConversationReply(0, '对话回复内容');
    expect(chatApiMocks.saveChatMessage).toHaveBeenCalledWith({
      project_id: 'p1',
      role: 'ai',
      content: '对话回复内容',
      intent: 'conversation',
    });
  });

  it('AI content 回复完成（onDone）→ saveChatMessage({project_id, role:"ai", content: 解析后 body, intent:"content"})', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '写一段打斗');
    driveContentReply(0, '他握紧了剑。');
    expect(chatApiMocks.saveChatMessage).toHaveBeenCalledWith({
      project_id: 'p1',
      role: 'ai',
      content: '他握紧了剑。',
      intent: 'content',
    });
  });

  it('projectId 变化 → 以新 projectId 重新加载历史（fetchChatMessages 再次调用）', async () => {
    const { rerender } = render(<ChatPanel projectId="p1" />);
    await waitFor(() => {
      expect(chatApiMocks.fetchChatMessages).toHaveBeenCalledWith('p1');
    });
    rerender(<ChatPanel projectId="p2" />);
    await waitFor(() => {
      expect(chatApiMocks.fetchChatMessages).toHaveBeenCalledWith('p2');
    });
    expect(chatApiMocks.fetchChatMessages).toHaveBeenCalledTimes(2);
  });
});
