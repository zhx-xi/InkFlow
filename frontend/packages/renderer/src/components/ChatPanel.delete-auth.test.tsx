/**
 * #766 阶段② 删除 HITL 授权 —— 前端三态分段控件 + HITL 确认弹窗 RED 契约（spec §6.4，M8）。
 * 本文件 = 契约，GREEN ChatPanel 实现必须匹配。当前实现无分段控件/弹窗 → 全部用例 FAIL（RED）。
 *
 * 契约锚点（GREEN 实现依据）：
 * - 分段控件：ChatPanel 工具调用区域新增三按钮分段组（SegmentedControl 风格），testid：
 *   `delete-mode-manual` / `delete-mode-ask-once` / `delete-mode-auto`；
 *   选中态高亮沿用 #477 chat-select-<n> 约定：`data-selected="true|false"` + aria-pressed。
 * - 默认态 = manual（spec §6.1：manual 时删除工具不注册，AI 无法删除）。
 * - 控件变更 → PATCH /api/v1/chat/conversations/{conversationId} body {delete_permission: "<mode>"}
 *   （api/chat.ts GREEN 新增 `updateChatDeletePermission(conversationId, deletePermission)`，URL/body 由 api/chat.test.ts 钉死）。
 * - HITL 中断：streamChat callbacks 增可选 `onInterrupt`（镜像 #597 onToolCall 模式）——interrupt SSE 帧
 *   {tool, entity_id, entity_name} 到达 → 渲染确认弹窗 `delete-confirm-dialog`（实体名 + 确认删除/取消）。
 * - 弹窗按钮：`delete-confirm-approve`（确认删除）/ `delete-confirm-cancel`（取消）→
 *   POST /api/v1/chat/resume body {conversation_id, approved: true|false}
 *   （api/chat.ts GREEN 新增 `resumeChatRun({conversation_id, approved})`）。
 * - 弹窗打开期间分段控件禁用（防中断中改权限）。
 * - i18n（zh.ts GREEN 补）：write.chat.deleteMode.manual='手动' / .askOnce='一次确认' / .auto='全自动'
 *   / .confirmTitle（弹窗标题）/ .confirmDelete='确认删除' / .cancel='取消'。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatPanel } from './ChatPanel';
import { useModelsStore, type ProviderConfig } from '../stores/models';
import { useToastStore } from '../stores/toast';
import { useThemeStore } from '../stores/theme';
import { useChapterStore } from '../stores/chapter';

// #766：chat api mock 聚合（vi.hoisted 供 vi.mock 工厂引用，镜像 ChatPanel.test.tsx / conversation 模式）。
// GREEN 时 api/chat.ts 新增 updateChatDeletePermission + resumeChatRun 两函数（本文件 mock 预置同名 vi.fn）。
const chatApiMocks = vi.hoisted(() => ({
  streamChat: vi.fn(),
  fetchChatMessages: vi.fn(),
  saveChatMessage: vi.fn(),
  fetchChatConversations: vi.fn(),
  archiveChatMessage: vi.fn(),
  deleteChatMessage: vi.fn(),
  restoreChatMessage: vi.fn(),
  archiveChatConversation: vi.fn(),
  deleteChatConversation: vi.fn(),
  createChatConversation: vi.fn(),
  // #766 阶段②：删除权限 PATCH + HITL resume（GREEN api/chat.ts 新增）
  updateChatDeletePermission: vi.fn(),
  resumeChatRun: vi.fn(),
}));
vi.mock('../api/chat', () => chatApiMocks);
vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});
vi.mock('../api/pipeline', () => ({
  executePipeline: vi.fn(),
  getExecutionStatus: vi.fn(),
  confirmExecution: vi.fn(),
}));
const streamChatMock = chatApiMocks.streamChat;

/** 与 src/api/chat.ts 契约一致（本地镜像，避免依赖未建模块）；#766 增可选 onInterrupt */
interface ChatStreamCallbacks {
  onDelta: (delta: string) => void;
  onDone: (frame: { done: boolean; delta?: string; error?: string }) => void;
  onError: (message: string) => void;
  /** #766 阶段②：interrupt SSE 帧（spec §6.3 payload {tool, entity_id, entity_name}）→ 前端确认弹窗 */
  onInterrupt?: (payload: { tool: string; entity_id: string; entity_name: string }) => void;
}
interface CapturedChatStream {
  body: { project_id: string; prompt: string };
  callbacks: ChatStreamCallbacks;
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

/** 每次 streamChat 调用的捕获（body + callbacks），用例手动驱动 SSE 帧（含 onInterrupt） */
let capturedStreams: CapturedChatStream[] = [];

/** 输入 + 点发送；等待第 index+1 次 streamChat 被调用（index 默认 0 = 最近一次） */
async function sendAndAwaitStream(user: ReturnType<typeof userEvent.setup>, text: string, index = 0) {
  await user.type(screen.getByTestId('chat-input'), text);
  await user.click(screen.getByTestId('chat-send'));
  await waitFor(() => {
    expect(streamChatMock).toHaveBeenCalledTimes(index + 1);
  });
}

/** 手动驱动第 index 次流的 interrupt 帧（#766：弹窗触发核心） */
function emitInterrupt(index: number, payload: { tool: string; entity_id: string; entity_name: string }) {
  act(() => {
    capturedStreams[index].callbacks.onInterrupt?.(payload);
  });
}

/** 挂载即解析活动线程（#744：无活动线程 → createChatConversation 建新 conv-p1）→ 等 conversation 就绪 */
async function waitConversationReady() {
  await waitFor(() => {
    expect(chatApiMocks.createChatConversation).toHaveBeenCalled();
  });
}

beforeEach(() => {
  streamChatMock.mockReset();
  capturedStreams = [];
  chatApiMocks.fetchChatMessages.mockReset();
  chatApiMocks.saveChatMessage.mockReset();
  chatApiMocks.fetchChatConversations.mockReset();
  chatApiMocks.archiveChatConversation.mockReset();
  chatApiMocks.deleteChatConversation.mockReset();
  chatApiMocks.createChatConversation.mockReset();
  // #766：新 API mock 默认成功返回
  chatApiMocks.updateChatDeletePermission.mockReset();
  chatApiMocks.resumeChatRun.mockReset();
  chatApiMocks.fetchChatMessages.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
  chatApiMocks.archiveChatConversation.mockResolvedValue(undefined);
  chatApiMocks.deleteChatConversation.mockResolvedValue(undefined);
  chatApiMocks.updateChatDeletePermission.mockResolvedValue(undefined);
  chatApiMocks.resumeChatRun.mockResolvedValue({ ok: true });
  chatApiMocks.saveChatMessage.mockResolvedValue({
    id: 'm-new',
    conversation_id: 'conv-p1',
    project_id: 'p1',
    role: 'user',
    content: '',
    intent: null,
    created_at: '2026-08-21T10:00:00Z',
  });
  chatApiMocks.fetchChatConversations.mockResolvedValue({ items: [], total: 0 });
  // #744：无活动线程时 createChatConversation 建新（mock 返回 conv-<projectId> 线程）
  chatApiMocks.createChatConversation.mockImplementation(async (projectId: string) => ({
    conversation_id: `conv-${projectId}`,
    project_id: projectId,
    project_name: null,
    last_message: '',
    message_count: 0,
    is_deleted: false,
    updated_at: '2026-08-21T10:00:00Z',
  }));
  streamChatMock.mockImplementation((body: { project_id: string; prompt: string }, callbacks: ChatStreamCallbacks) => {
    capturedStreams.push({ body, callbacks });
    return Promise.resolve(() => {});
  });
  useModelsStore.setState({ providers: [READY_PROVIDER], loading: false, error: null });
  useToastStore.setState({ toasts: [] });
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

describe('ChatPanel — 三态分段控件（#766 阶段② spec §6.4）', () => {
  it('渲染三态分段控件：delete-mode-manual / delete-mode-ask-once / delete-mode-auto（i18n 手动/一次确认/全自动）', async () => {
    render(<ChatPanel {...OPTS} />);
    // RED：当前实现无分段控件 → 三个 testid 均不存在 → getByTestId FAIL
    expect(screen.getByTestId('delete-mode-manual')).toHaveTextContent('手动');
    expect(screen.getByTestId('delete-mode-ask-once')).toHaveTextContent('一次确认');
    expect(screen.getByTestId('delete-mode-auto')).toHaveTextContent('全自动');
  });

  it('默认态 = manual（spec §6.1：删除工具不注册）：delete-mode-manual 选中（data-selected=true / aria-pressed），其余未选中', async () => {
    render(<ChatPanel {...OPTS} />);
    // RED：无分段控件 → getByTestId FAIL
    expect(screen.getByTestId('delete-mode-manual')).toHaveAttribute('data-selected', 'true');
    expect(screen.getByTestId('delete-mode-ask-once')).toHaveAttribute('data-selected', 'false');
    expect(screen.getByTestId('delete-mode-auto')).toHaveAttribute('data-selected', 'false');
  });

  it('点击「一次确认」→ PATCH /chat/conversations/{id}：updateChatDeletePermission(conversationId, "ask_once")', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await waitConversationReady();
    await user.click(screen.getByTestId('delete-mode-ask-once'));
    // RED：无控件可点 → user.click 抛错；GREEN 断言 PATCH 权限更新调用（body {delete_permission:"ask_once"}）
    await waitFor(() => {
      expect(chatApiMocks.updateChatDeletePermission).toHaveBeenCalledWith('conv-p1', 'ask_once');
    });
  });

  it('点击「全自动」→ PATCH /chat/conversations/{id}：updateChatDeletePermission(conversationId, "auto")', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await waitConversationReady();
    await user.click(screen.getByTestId('delete-mode-auto'));
    // RED：无控件可点 → user.click 抛错；GREEN 断言 PATCH 权限更新调用（body {delete_permission:"auto"}）
    await waitFor(() => {
      expect(chatApiMocks.updateChatDeletePermission).toHaveBeenCalledWith('conv-p1', 'auto');
    });
  });
});

describe('ChatPanel — HITL 确认弹窗（#766 阶段② spec §6.3/§6.4）', () => {
  /** #766：interrupt 帧标准 payload（delete_character 工具删除实体） */
  const INTERRUPT_PAYLOAD = { tool: 'delete_character', entity_id: 'char-1', entity_name: '李四' };

  it('interrupt 帧到达 → 渲染确认弹窗 delete-confirm-dialog（实体名 + 确认删除/取消按钮）', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '删除角色李四');
    // RED：ChatPanel 未订阅 onInterrupt → 无弹窗 → getByTestId FAIL
    emitInterrupt(0, INTERRUPT_PAYLOAD);
    const dialog = screen.getByTestId('delete-confirm-dialog');
    expect(within(dialog).getByText('李四')).toBeInTheDocument();
    expect(within(dialog).getByTestId('delete-confirm-approve')).toHaveTextContent('确认删除');
    expect(within(dialog).getByTestId('delete-confirm-cancel')).toHaveTextContent('取消');
  });

  it('点击「确认删除」→ POST /chat/resume：resumeChatRun({conversation_id, approved: true})', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '删除角色李四');
    emitInterrupt(0, INTERRUPT_PAYLOAD);
    await user.click(screen.getByTestId('delete-confirm-approve'));
    // RED：无弹窗按钮可点 → user.click 抛错；GREEN 断言 resume 批准续跑
    await waitFor(() => {
      expect(chatApiMocks.resumeChatRun).toHaveBeenCalledWith({ conversation_id: 'conv-p1', approved: true });
    });
  });

  it('点击「取消」→ POST /chat/resume：resumeChatRun({conversation_id, approved: false})', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '删除角色李四');
    emitInterrupt(0, INTERRUPT_PAYLOAD);
    await user.click(screen.getByTestId('delete-confirm-cancel'));
    // RED：无弹窗按钮可点 → user.click 抛错；GREEN 断言 resume 拒绝续跑（不删除）
    await waitFor(() => {
      expect(chatApiMocks.resumeChatRun).toHaveBeenCalledWith({ conversation_id: 'conv-p1', approved: false });
    });
  });

  it('弹窗打开期间分段控件禁用（delete-mode-* 三按钮 disabled，防中断中改权限）', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await sendAndAwaitStream(user, '删除角色李四');
    emitInterrupt(0, INTERRUPT_PAYLOAD);
    // RED：无弹窗/无控件 → getByTestId FAIL；GREEN 断言三按钮 disabled
    expect(screen.getByTestId('delete-mode-manual')).toBeDisabled();
    expect(screen.getByTestId('delete-mode-ask-once')).toBeDisabled();
    expect(screen.getByTestId('delete-mode-auto')).toBeDisabled();
  });
});

describe('ChatPanel — #841 5b 写作模式控件锚定输入框上方', () => {
  it('full 变体无 chat 内容 → 分段控件与输入框同在底部 compose 组（控件在输入框上方）', async () => {
    chatApiMocks.fetchChatConversations.mockResolvedValue({ items: [], total: 0 });
    render(<ChatPanel projectId="p1" variant="full" />);
    await screen.findByTestId('chat-panel');
    const compose = screen.getByTestId('chat-compose');
    // #841 5b：compose 组 mt-auto 沉底（控件 + 输入框同组）
    expect(compose).toHaveClass('mt-auto');
    expect(within(compose).getByTestId('delete-mode-manual')).toBeInTheDocument();
    expect(within(compose).getByTestId('chat-input')).toBeInTheDocument();
  });

  it('章节内 inline 变体 → 分段控件仍在输入框上方（同 compose 组）', async () => {
    chatApiMocks.fetchChatConversations.mockResolvedValue({ items: [], total: 0 });
    render(<ChatPanel {...OPTS} />);
    await screen.findByTestId('chat-panel');
    const compose = screen.getByTestId('chat-compose');
    expect(within(compose).getByTestId('delete-mode-manual')).toBeInTheDocument();
    expect(within(compose).getByTestId('chat-input')).toBeInTheDocument();
  });
});
