/**
 * #1015 归档 AI 对话只读加载 RED 契约（spec specs/f19-gui/sessions.md §6.2/§6.3 N14/N15）
 *
 * ⚠️ 本文件 = 契约。GREEN（ChatPanel.tsx + ChatArchivedBanner 子组件）必须匹配：
 * - 消费 URL conversationId（#840 指定会话）时，先以 fetchChatConversations(
 *   { projectId, includeDeleted: true }) 本地按 conversation_id 查 meta（既有端点，
 *   无新 GET）→ is_deleted=true 判定归档会话：
 *   ① 顶部渲染横幅 chat-archived-banner + 恢复按钮 chat-archived-restore；
 *   ② 历史加载 fetchChatMessages(cid, 0, 50, { includeDeleted: true })（wire 契约
 *      见 api/chat.test.ts；后端 GET /chat/messages 新增 include_deleted query）；
 *   ③ 只读：不渲染 chat-input / chat-send / chat-compose（可看不可续聊）。
 * - 恢复：点 chat-archived-restore → restoreChatConversation(cid)（api/chat.ts 既有）
 *   → 成功后横幅消失、解除只读（输入区恢复）。
 * - meta 查不到 / 查询失败 → 按活动会话处理（保守降级，不阻塞消息加载）。
 * - 守护（N15）：活动会话（meta.is_deleted=false）→ 无横幅、输入区渲染，且消息请求
 *   调用形态保持 fetchChatMessages(cid) 单参（不带 opts → 不发 include_deleted 参数，
 *   ChatPanel.conversation.test.tsx 既有单参断言不回归）。
 *
 * RED 预期：当前 ChatPanel 无归档感知（不查 meta、无横幅、始终渲染输入区）→
 * 归档用例在 findByTestId('chat-archived-banner') FAIL；守护用例 PASS。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatPanel } from './ChatPanel';
import {
  fetchChatConversations,
  fetchChatMessages,
  restoreChatConversation,
} from '../api/chat';
import { useModelsStore, type ProviderConfig } from '../stores/models';
import { useToastStore } from '../stores/toast';
import { useThemeStore } from '../stores/theme';
import { useChapterStore } from '../stores/chapter';

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
  // #1015：归档横幅恢复按钮消费（api/chat.ts 既有导出）
  restoreChatConversation: vi.fn(),
  renameChatConversation: vi.fn(),
  updateChatDeletePermission: vi.fn(),
  resumeChatRun: vi.fn(),
  abortChatRun: vi.fn(),
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

const fetchChatConversationsMock = vi.mocked(fetchChatConversations);
const fetchChatMessagesMock = vi.mocked(fetchChatMessages);
const restoreChatConversationMock = vi.mocked(restoreChatConversation);

const READY_PROVIDER: ProviderConfig = {
  id: 1,
  name: 'openai',
  base_url: 'https://api.openai.com/v1',
  default_model: 'gpt-4o',
  models: [{ id: 'gpt-4o', type: 'chat', roles: ['main'] }],
  key_saved: true,
  max_retries: 3,
  timeout: 60,
  created_at: '',
  updated_at: '',
};

const ARCHIVED_CONV = {
  conversation_id: 'conv-arch',
  project_id: 'p1',
  project_name: '青云志',
  title: '归档对话',
  last_message: '',
  message_count: 0,
  is_deleted: true,
  updated_at: '2026-08-20T09:00:00Z',
};
const ACTIVE_CONV = {
  conversation_id: 'conv-act',
  project_id: 'p1',
  project_name: '青云志',
  title: '活动对话',
  last_message: '在写第七章',
  message_count: 2,
  is_deleted: false,
  updated_at: '2026-08-21T10:00:00Z',
};

beforeEach(() => {
  chatApiMocks.streamChat.mockReset();
  fetchChatConversationsMock.mockReset();
  fetchChatMessagesMock.mockReset();
  restoreChatConversationMock.mockReset();
  chatApiMocks.saveChatMessage.mockReset();
  chatApiMocks.createChatConversation.mockReset();

  fetchChatConversationsMock.mockResolvedValue({ items: [ARCHIVED_CONV, ACTIVE_CONV], total: 2 });
  fetchChatMessagesMock.mockResolvedValue({
    items: [
      {
        id: 'm1',
        conversation_id: 'conv-arch',
        project_id: 'p1',
        role: 'user',
        content: '归档前的问题',
        intent: null,
        created_at: '2026-08-20T08:00:00Z',
      },
      {
        id: 'm2',
        conversation_id: 'conv-arch',
        project_id: 'p1',
        role: 'ai',
        content: '归档前的回答',
        intent: 'conversation',
        created_at: '2026-08-20T08:01:00Z',
      },
    ],
    total: 2,
    offset: 0,
    limit: 50,
  });
  restoreChatConversationMock.mockResolvedValue({ ...ARCHIVED_CONV, is_deleted: false });
  chatApiMocks.createChatConversation.mockResolvedValue({ ...ACTIVE_CONV, conversation_id: 'conv-new' });

  useModelsStore.setState({ providers: [READY_PROVIDER], loading: false, error: null });
  useToastStore.setState({ toasts: [] });
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useChapterStore.setState({
    volumes: [],
    chapters: [],
    treeProjectId: null,
    currentChapterId: null,
    content: '',
    loading: false,
    error: null,
  });
});

describe('#1015 归档会话（URL conversationId 指定）→ 横幅 + 只读 + include_deleted 加载', () => {
  it('归档 meta → chat-archived-banner 出现、历史请求带 {includeDeleted:true}、输入区不渲染（只读）', async () => {
    render(<ChatPanel projectId="p1" variant="full" conversationId="conv-arch" />);

    // meta 查询：includeDeleted=true（含归档线程的聚合列表）
    await waitFor(() => {
      expect(fetchChatConversationsMock).toHaveBeenCalledWith({
        projectId: 'p1',
        includeDeleted: true,
      });
    });
    // 横幅 + 恢复入口
    expect(await screen.findByTestId('chat-archived-banner')).toBeInTheDocument();
    expect(screen.getByTestId('chat-archived-restore')).toBeInTheDocument();
    // 归档消息加载（级联软删的消息经 include_deleted 返回）
    await waitFor(() => {
      expect(fetchChatMessagesMock).toHaveBeenCalledWith('conv-arch', 0, 50, {
        includeDeleted: true,
      });
    });
    // 只读：无输入区
    expect(screen.queryByTestId('chat-input')).not.toBeInTheDocument();
    expect(screen.queryByTestId('chat-send')).not.toBeInTheDocument();
    // 历史消息渲染
    expect(await screen.findByText('归档前的问题')).toBeInTheDocument();
  });

  it('点击 chat-archived-restore → restoreChatConversation(cid) 成功 → 横幅消失、输入区恢复', async () => {
    const user = userEvent.setup();
    render(<ChatPanel projectId="p1" variant="full" conversationId="conv-arch" />);
    await screen.findByTestId('chat-archived-banner');

    await user.click(screen.getByTestId('chat-archived-restore'));
    await waitFor(() => {
      expect(restoreChatConversationMock).toHaveBeenCalledWith('conv-arch');
    });
    await waitFor(() => {
      expect(screen.queryByTestId('chat-archived-banner')).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByTestId('chat-input')).toBeInTheDocument();
    });
  });

  it('meta 查不到该线程（异常数据）→ 按活动处理：无横幅、输入区渲染、单参加载（保守降级）', async () => {
    fetchChatConversationsMock.mockResolvedValue({ items: [], total: 0 });
    render(<ChatPanel projectId="p1" variant="full" conversationId="conv-unknown" />);
    await waitFor(() => {
      expect(
        fetchChatMessagesMock.mock.calls.some((c) => c[0] === 'conv-unknown'),
      ).toBe(true);
    });
    expect(screen.queryByTestId('chat-archived-banner')).not.toBeInTheDocument();
    expect(screen.getByTestId('chat-input')).toBeInTheDocument();
  });

  it('meta 查询失败（reject）→ 按活动处理不崩溃（静默降级）', async () => {
    fetchChatConversationsMock.mockRejectedValueOnce(new Error('offline'));
    render(<ChatPanel projectId="p1" variant="full" conversationId="conv-arch" />);
    await waitFor(() => {
      expect(
        fetchChatMessagesMock.mock.calls.some((c) => c[0] === 'conv-arch'),
      ).toBe(true);
    });
    expect(screen.queryByTestId('chat-archived-banner')).not.toBeInTheDocument();
    expect(screen.getByTestId('chat-input')).toBeInTheDocument();
  });
});

describe('#1015 守护（N15）：活动会话行为不回归', () => {
  it('活动会话（meta.is_deleted=false）→ 无横幅、输入区渲染、消息加载不带 includeDeleted opts', async () => {
    render(<ChatPanel projectId="p1" variant="full" conversationId="conv-act" />);

    // 消息加载发生（first-arg 锚定；活动路径的精确单参形态由
    // ChatPanel.conversation.test.tsx 既有断言守护，此处不重复钉死参数位）
    await waitFor(() => {
      expect(
        fetchChatMessagesMock.mock.calls.some((c) => c[0] === 'conv-act'),
      ).toBe(true);
    });
    // 横幅永不出现 + 输入区在
    await waitFor(() => {
      expect(screen.getByTestId('chat-input')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('chat-archived-banner')).not.toBeInTheDocument();
    // 任何调用都未带 includeDeleted:true opts
    const withArchivedOpts = fetchChatMessagesMock.mock.calls.some(
      (call) => (call[3] as { includeDeleted?: boolean } | undefined)?.includeDeleted === true,
    );
    expect(withArchivedOpts).toBe(false);
  });

  it('无 URL conversationId（#744 解析路径）→ 行为不变：includeDeleted:false 解析 + 单参加载', async () => {
    fetchChatConversationsMock.mockResolvedValue({ items: [ACTIVE_CONV], total: 1 });
    render(<ChatPanel projectId="p1" />);
    await waitFor(() => {
      expect(fetchChatConversationsMock).toHaveBeenCalledWith({
        projectId: 'p1',
        includeDeleted: false,
      });
    });
    await waitFor(() => {
      expect(fetchChatMessagesMock).toHaveBeenCalledWith('conv-act');
    });
    expect(screen.queryByTestId('chat-archived-banner')).not.toBeInTheDocument();
  });
});
