/**
 * 聊天框契约（spec §4.1）：底部 AI 聊天框 ChatPanel
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 ChatPanel 必须匹配（行为断言，不测样式）。
 *
 * 导出契约：
 * - export function ChatPanel(props: { projectId: string; chapterId?: string; chapterContent?: string })
 *
 * 结构 testid：
 * - chat-panel（容器）/ chat-input（textarea）/ chat-send（发送按钮）
 * - chat-msg-user-<n>（用户消息）/ chat-msg-ai-<n>（AI 回复消息）
 * - chat-insert-<n>（该条 AI 消息的「插入正文」按钮）
 *
 * 行为契约：
 * - 空输入（trim 后空）→ chat-send disabled
 * - 输入 + 发送 → executePipeline({pipeline:'builtin:chat', project_id, variables:{prompt, chapter_context?}})
 *   chapter_context 仅在 chapterContent 非空时注入
 * - 轮询 getExecutionStatus(execution_id)（1s 间隔）→ status==='completed'
 *   → assistant 消息展示 final_output + 「插入正文」按钮
 * - 点「插入正文」→ chapterStore.setContent(final_output)（不自动保存，F27 save 流）
 * - status==='failed' → 消息区显示错误文案（含「对话失败」），不插入正文
 * - 发送中并发保护：execute 未 resolve 时再次发送不触发第二次 execute
 *
 * i18n key（GREEN 补）：write.chat.placeholder / write.chat.send / write.chat.insert /
 * write.chat.inserted / write.chat.failed
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatPanel } from './ChatPanel';
import { executePipeline, getExecutionStatus, type PipelineExecuteResponse } from '../api/pipeline';
import { useChapterStore } from '../stores/chapter';
import { useThemeStore } from '../stores/theme';

vi.mock('../api/pipeline', () => ({
  executePipeline: vi.fn(),
  getExecutionStatus: vi.fn(),
  confirmExecution: vi.fn(),
}));

const executeMock = vi.mocked(executePipeline);
const statusMock = vi.mocked(getExecutionStatus);

const OPTS = { projectId: 'p1', chapterId: 'c1', chapterContent: '已有正文第一段。' };

beforeEach(() => {
  vi.useRealTimers();
  executeMock.mockReset();
  statusMock.mockReset();
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
    status: 'completed',
    stages: [],
    trace: [],
    final_output: '对话回复内容',
    total_duration_ms: 900,
    error: '',
  });
});

describe('ChatPanel — 聊天输入与发送', () => {
  it('渲染 chat-panel / chat-input / chat-send；空输入发送禁用', () => {
    render(<ChatPanel {...OPTS} />);
    expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
    expect(screen.getByTestId('chat-input')).toBeInTheDocument();
    expect(screen.getByTestId('chat-send')).toBeDisabled();
  });

  it('输入文本后发送按钮可用；点发送 → executePipeline(builtin:chat + prompt + chapter_context)', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    const input = screen.getByTestId('chat-input') as HTMLTextAreaElement;
    await user.type(input, '帮我写一段打斗场景');
    expect(screen.getByTestId('chat-send')).not.toBeDisabled();
    await user.click(screen.getByTestId('chat-send'));
    await waitFor(() => {
      expect(executeMock).toHaveBeenCalledWith(
        expect.objectContaining({
          pipeline: 'builtin:chat',
          project_id: 'p1',
          variables: expect.objectContaining({
            prompt: '帮我写一段打斗场景',
            chapter_context: '已有正文第一段。',
          }),
        }),
      );
    });
  });

  it('chapterContent 为空 → 不注入 chapter_context 变量', async () => {
    const user = userEvent.setup();
    render(<ChatPanel projectId="p1" chapterId="c1" chapterContent="" />);
    await user.type(screen.getByTestId('chat-input'), '你好');
    await user.click(screen.getByTestId('chat-send'));
    await waitFor(() => {
      const call = executeMock.mock.calls[0][0] as { variables?: Record<string, string> };
      expect(call.variables?.prompt).toBe('你好');
      expect(call.variables?.chapter_context).toBeUndefined();
    });
  });
});

describe('ChatPanel — 回复与插入正文', () => {
  it('轮询 completed → assistant 消息 + 插入正文按钮', async () => {
    vi.useFakeTimers();
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await user.type(screen.getByTestId('chat-input'), '解释这个角色的动机');
    await user.click(screen.getByTestId('chat-send'));
    // 用户消息立即展示
    expect(screen.getByTestId('chat-msg-user-0')).toHaveTextContent('解释这个角色的动机');
    // 轮询 1s → completed
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(screen.getByTestId('chat-msg-ai-0')).toHaveTextContent('对话回复内容');
    expect(screen.getByTestId('chat-insert-0')).toBeInTheDocument();
  });

  it('点「插入正文」→ chapterStore.setContent(final_output)', async () => {
    vi.useFakeTimers();
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await user.type(screen.getByTestId('chat-input'), '帮我写一段打斗场景');
    await user.click(screen.getByTestId('chat-send'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    await user.click(screen.getByTestId('chat-insert-0'));
    expect(useChapterStore.getState().content).toBe('对话回复内容');
  });
});

describe('ChatPanel — 失败与并发保护', () => {
  it('轮询 failed → 显示错误（含「对话失败」），不插入正文', async () => {
    statusMock.mockResolvedValue({
      execution_id: 'e-chat-1',
      pipeline: 'builtin:chat',
      project_id: 'p1',
      status: 'failed',
      stages: [],
      trace: [],
      final_output: '',
      total_duration_ms: 500,
      error: 'LLM 调用失败',
    });
    vi.useFakeTimers();
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await user.type(screen.getByTestId('chat-input'), '你好');
    await user.click(screen.getByTestId('chat-send'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(screen.getByTestId('chat-panel')).toHaveTextContent(/对话失败/);
    expect(useChapterStore.getState().content).toBe('已有正文第一段。');
  });

  it('发送中并发保护：execute 挂起时再次发送不触发第二次 execute', async () => {
    let resolveExec!: (v: PipelineExecuteResponse) => void;
    executeMock.mockReturnValue(new Promise((r) => { resolveExec = r; }));
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await user.type(screen.getByTestId('chat-input'), '第一条');
    await user.click(screen.getByTestId('chat-send'));
    await waitFor(() => expect(executeMock).toHaveBeenCalledTimes(1));
    // 发送中：输入第二条并再次发送 → 无第二次 execute
    await user.type(screen.getByTestId('chat-input'), '第二条');
    await user.click(screen.getByTestId('chat-send'));
    expect(executeMock).toHaveBeenCalledTimes(1);
    await act(async () => {
      resolveExec({
        execution_id: 'e-chat-1',
        pipeline: 'builtin:chat',
        project_id: 'p1',
        status: 'pending',
        created_at: '',
      });
    });
  });
});
