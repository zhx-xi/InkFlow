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
 * - chat-select-<n>（content 意图消息的选择控件，data-selected="true"|"false" 选中态）
 * - chat-insert-selected（共享「插入选中正文」按钮，仅存在 content 消息时渲染）
 *
 * 行为契约：
 * - 空输入（trim 后空）→ chat-send disabled
 * - 输入 + 发送 → executePipeline({pipeline:'builtin:chat', project_id, variables:{prompt, chapter_context?}})
 *   chapter_context 仅在 chapterContent 非空时注入
 * - 轮询 getExecutionStatus(execution_id)（1s 间隔）→ status==='completed'
 *   → 用 parseChatReply(final_output) 解析意图（#477，src/lib/chatIntent.ts GREEN 建）：
 *     content（含成对标记）→ 消息只显示提取 body（标记与前言隐藏）+ chat-select-<n> 控件
 *     conversation（无标记）→ 消息显示完整原文，无选择/插入控件
 * - 单选互斥：点 chat-select-<n> 切换选中；新 content 消息到达自动成为选中条（最新优先）
 * - 点 chat-insert-selected → chapterStore.setContent(选中条 body)（不自动保存，F27 save 流）
 *   + toast（write.chat.inserted）
 * - 旧 per-message chat-insert-<n> 按钮已删除（#477：新契约下任何场景都不应出现）
 * - status==='failed' → 消息区显示错误文案（含「对话失败」），不插入正文
 * - 发送中并发保护：execute 未 resolve 时再次发送不触发第二次 execute
 *
 * i18n key（GREEN 补）：write.chat.placeholder / write.chat.send / write.chat.insert /
 * write.chat.inserted / write.chat.failed / write.chat.select（选中此回复，选择控件 aria-label）
 *
 * 展开/收缩/拖动契约（#476 D2，2026-08-19 追加）：
 * - chat-expand（展开对话按钮，aria-label = write.chat.expand「展开对话」）
 * - chat-collapse（收起对话按钮，aria-label = write.chat.collapse「收起对话」）
 * - chat-messages（消息区容器，条件渲染：有消息且展开时才存在）
 * - chat-resize-handle（拖动把手，展开态渲染）
 * - 默认折叠（chat-messages 不渲染）；点 chat-expand 展开；点 chat-collapse 收起
 * - 折叠态发送消息 → 自动展开（chat-messages 出现，消息可见）
 * - 收缩再展开 → 历史消息保留
 * - 鼠标拖动调整高度：mousedown(handle) → mousemove(window) → chat-messages 的
 *   data-height 属性变化（px 字符串，向上拖 = 增大）；mouseup(window) 结束
 * i18n key（GREEN 补）：write.chat.expand / write.chat.collapse
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatPanel } from './ChatPanel';
import { executePipeline, getExecutionStatus, type PipelineExecuteResponse } from '../api/pipeline';
import { apiFetch } from '../api/client';
import { useChapterStore } from '../stores/chapter';
import { useThemeStore } from '../stores/theme';
import { useModelsStore, type ProviderConfig } from '../stores/models';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});
vi.mock('../api/pipeline', () => ({
  executePipeline: vi.fn(),
  getExecutionStatus: vi.fn(),
  confirmExecution: vi.fn(),
}));

const executeMock = vi.mocked(executePipeline);
const statusMock = vi.mocked(getExecutionStatus);
const apiFetchMock = vi.mocked(apiFetch);

const OPTS = { projectId: 'p1', chapterId: 'c1', chapterContent: '已有正文第一段。' };

/** #477：构造一条 completed 轮询响应（final_output 可变），形状与 beforeEach 默认 mock 一致。 */
type ChatStatusReply = Awaited<ReturnType<typeof getExecutionStatus>>;
function completedReply(finalOutput: string): ChatStatusReply {
  return {
    execution_id: 'e-chat-1',
    pipeline: 'builtin:chat',
    project_id: 'p1',
    status: 'completed',
    stages: [],
    trace: [],
    final_output: finalOutput,
    total_duration_ms: 900,
    error: '',
  };
}

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

beforeEach(() => {
  vi.useRealTimers();
  executeMock.mockReset();
  statusMock.mockReset();
  apiFetchMock.mockReset();
  // #474 前置校验依赖 models store：默认播种「已配置」让既有用例行为不变；
  // 未配置用例自行 setState 覆盖为空
  useModelsStore.setState({ providers: [READY_PROVIDER], loading: false, error: null });
  useToastStore.setState({ toasts: [] });
  // URL 分发：provider-configs 返回已配置（防 GREEN 挂载/发送时 loadProviders 覆盖播种）；
  // 其余端点返回通用成功
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/provider-configs') {
      return { items: [READY_PROVIDER], total: 1, offset: 0, limit: 50 };
    }
    return { ok: true };
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
  it('轮询 completed → content 意图：assistant 消息只显示 body + 自动选中 + 共享插入按钮', async () => {
    // #477：带标记的产出正文（LLM 按 prompt 约定用标记包裹正文）
    statusMock.mockResolvedValue(completedReply('好的，以下是续写内容：\n<<<CONTENT>>>\n他握紧了剑。\n<<<END>>>'));
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
    // 只显示提取的 body，不显示标记与前言
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

  it('点共享「插入选中」→ chapterStore.setContent(选中条 body，纯 body 无标记无前言)', async () => {
    // #477：带标记的产出正文；默认最新选中 → 插入提取后的纯 body
    statusMock.mockResolvedValue(completedReply('好的，以下是续写内容：\n<<<CONTENT>>>\n他握紧了剑。\n<<<END>>>'));
    vi.useFakeTimers();
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await user.type(screen.getByTestId('chat-input'), '帮我写一段打斗场景');
    await user.click(screen.getByTestId('chat-send'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    await user.click(screen.getByTestId('chat-insert-selected'));
    expect(useChapterStore.getState().content).toBe('他握紧了剑。');
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

describe('ChatPanel — 模型未配置前置校验（#474 P0）', () => {
  /**
   * 契约：用户未配置模型（providers 空 / 无 key_saved=true 的 chat provider）时点发送：
   * - 不发 executePipeline 请求（不发 AI 请求）
   * - toast 提示（type='warn'，文案引导去配置）
   * 已配置模型（beforeEach 默认播种 READY_PROVIDER）行为不变：正常 execute。
   *
   * i18n key（GREEN 补 zh.ts/en.ts）：common.modelNotConfigured
   */
  it('未配置模型（providers 空）→ 点发送 → toast 提示 + 不发 execute 请求', async () => {
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
    // toast 提示（引导去配置）
    expect(useToastStore.getState().toasts.some((t) => t.type === 'warn')).toBe(true);
    expect(useToastStore.getState().toasts.some((t) => t.message.includes('配置'))).toBe(true);
    // 不发 AI 请求
    expect(executeMock).not.toHaveBeenCalled();
  });

  it('未配置模型（provider 存在但 key_saved=false）→ 点发送 → toast + 不发 execute', async () => {
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
    expect(executeMock).not.toHaveBeenCalled();
  });

  it('Enter 键发送同样走前置校验（未配置 → toast + 不发 execute）', async () => {
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
    expect(executeMock).not.toHaveBeenCalled();
  });

  it('已配置模型（默认播种）→ 发送正常 execute（行为不变）', async () => {
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await user.type(screen.getByTestId('chat-input'), '已配置模型对话');
    await user.click(screen.getByTestId('chat-send'));
    await waitFor(() => {
      expect(executeMock).toHaveBeenCalledWith(
        expect.objectContaining({ pipeline: 'builtin:chat' }),
      );
    });
  });
});

describe('ChatPanel — 展开/收缩/拖动（#476 D2：对话区高度交互）', () => {
  /**
   * 契约：#476 底部 chat 搬入工具栏栏后，对话区支持展开/收缩/鼠标拖动调整高度。
   * 布局与交互语义见文件头 docstring（chat-expand / chat-collapse / chat-messages /
   * chat-resize-handle / 默认折叠 / 发送自动展开 / 拖动改 data-height）。
   *
   * 拖动模拟（#388 窗口级拖拽模式）：mousedown 打 handle 元素、mousemove/mouseup 打 window。
   * 高度断言只锁「变化 + 变大」（clamp 上下限由 GREEN 定，默认展开高度须低于上限）。
   */
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
    // 收缩
    await user.click(screen.getByTestId('chat-collapse'));
    expect(screen.queryByTestId('chat-messages')).not.toBeInTheDocument();
    expect(screen.getByTestId('chat-expand')).toBeInTheDocument();
    // 再展开 → 消息保留
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
    // 按钮必须位于消息区之前（DOM 顺序：顶部）
    expect(btn.compareDocumentPosition(msgs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // 折叠态：chat-expand 也在输入区之前（顶部行）
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

describe('ChatPanel — 意图分离（#477 D8）', () => {
  /**
   * 契约：#477 聊天回复意图分离——success 到达时用 parseChatReply(final_output)
   * 判定意图（src/lib/chatIntent.ts，GREEN 建）：
   * - content 意图（含成对 <<<CONTENT>>> / <<<END>>> 标记）：消息只显示提取 body，
   *   渲染选择控件 chat-select-<n>（data-selected 选中态），可插入
   * - conversation 意图（无标记）：消息显示完整原文，无选择/插入控件
   * - chat-insert-selected 仅当存在至少一条 content 消息时渲染
   *
   * i18n key（GREEN 补 zh.ts/en.ts）：write.chat.select（选中此回复，选择控件 aria-label）
   */
  it('无标记回复（默认 final_output）→ conversation：显示原文，无选择控件、无插入按钮', async () => {
    vi.useFakeTimers();
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await user.type(screen.getByTestId('chat-input'), '聊聊角色设定');
    await user.click(screen.getByTestId('chat-send'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    // conversation：完整原文展示
    expect(screen.getByTestId('chat-msg-ai-0')).toHaveTextContent('对话回复内容');
    // 无选择控件 / 无共享插入按钮
    expect(screen.queryByTestId('chat-select-0')).not.toBeInTheDocument();
    expect(screen.queryByTestId('chat-insert-selected')).not.toBeInTheDocument();
  });

  it('混合：第 1 条 content + 第 2 条 conversation → 仅 content 条可选，选中仍在 seq 0', async () => {
    vi.useFakeTimers();
    statusMock.mockResolvedValueOnce(completedReply('好的，以下是续写内容：\n<<<CONTENT>>>\n他握紧了剑。\n<<<END>>>'));
    statusMock.mockResolvedValueOnce(completedReply('对话回复内容'));
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    // 第一次发送 → content 回复
    await user.type(screen.getByTestId('chat-input'), '写一段打斗');
    await user.click(screen.getByTestId('chat-send'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(screen.getByTestId('chat-select-0')).toHaveAttribute('data-selected', 'true');
    // 第二次发送 → conversation 回复（无标记）
    await user.type(screen.getByTestId('chat-input'), '谢谢');
    await user.click(screen.getByTestId('chat-send'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    // 第 2 条为 conversation：无选择控件
    expect(screen.queryByTestId('chat-select-1')).not.toBeInTheDocument();
    // 共享插入按钮仍渲染（存在 content 消息）；选中保持在 seq 0
    expect(screen.getByTestId('chat-insert-selected')).toBeInTheDocument();
    expect(screen.getByTestId('chat-select-0')).toHaveAttribute('data-selected', 'true');
  });
});

describe('ChatPanel — 多生成单选插入（#477）', () => {
  /**
   * 契约：多条 content 回复时单选互斥——每条渲染 chat-select-<n>（data-selected
   * 选中态），新到达的 content 消息自动成为选中条（最新优先）；共享
   * chat-insert-selected 只插入选中条的 body；旧 per-message chat-insert-<n>
   * 按钮已删除（任何场景都不应出现）。
   */
  it('两条 content → 均渲染选择控件；新到第 2 条自动选中（互斥）', async () => {
    vi.useFakeTimers();
    statusMock.mockResolvedValueOnce(completedReply('好的，以下是续写内容：\n<<<CONTENT>>>\n第一段正文。\n<<<END>>>'));
    statusMock.mockResolvedValueOnce(completedReply('好的，以下是续写内容：\n<<<CONTENT>>>\n第二段正文。\n<<<END>>>'));
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await user.type(screen.getByTestId('chat-input'), '写第一段');
    await user.click(screen.getByTestId('chat-send'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    await user.type(screen.getByTestId('chat-input'), '写第二段');
    await user.click(screen.getByTestId('chat-send'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    // 两条 content 均渲染选择控件
    expect(screen.getByTestId('chat-select-0')).toBeInTheDocument();
    expect(screen.getByTestId('chat-select-1')).toBeInTheDocument();
    // 最新到达的第 2 条自动选中（data-selected 互斥）
    expect(screen.getByTestId('chat-select-1')).toHaveAttribute('data-selected', 'true');
    expect(screen.getByTestId('chat-select-0')).toHaveAttribute('data-selected', 'false');
    // 共享插入按钮存在；旧 per-message 按钮不存在
    expect(screen.getByTestId('chat-insert-selected')).toBeInTheDocument();
    expect(screen.queryByTestId('chat-insert-0')).toBeNull();
  });

  it('点 chat-select-0 → 选中切换到第 1 条（互斥）', async () => {
    vi.useFakeTimers();
    statusMock.mockResolvedValueOnce(completedReply('好的，以下是续写内容：\n<<<CONTENT>>>\n第一段正文。\n<<<END>>>'));
    statusMock.mockResolvedValueOnce(completedReply('好的，以下是续写内容：\n<<<CONTENT>>>\n第二段正文。\n<<<END>>>'));
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await user.type(screen.getByTestId('chat-input'), '写第一段');
    await user.click(screen.getByTestId('chat-send'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    await user.type(screen.getByTestId('chat-input'), '写第二段');
    await user.click(screen.getByTestId('chat-send'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    await user.click(screen.getByTestId('chat-select-0'));
    expect(screen.getByTestId('chat-select-0')).toHaveAttribute('data-selected', 'true');
    expect(screen.getByTestId('chat-select-1')).toHaveAttribute('data-selected', 'false');
  });

  it('选中第 1 条后点插入 → 只插入选中条 body（+ toast 已插入正文）', async () => {
    vi.useFakeTimers();
    statusMock.mockResolvedValueOnce(completedReply('好的，以下是续写内容：\n<<<CONTENT>>>\n第一段正文。\n<<<END>>>'));
    statusMock.mockResolvedValueOnce(completedReply('好的，以下是续写内容：\n<<<CONTENT>>>\n第二段正文。\n<<<END>>>'));
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await user.type(screen.getByTestId('chat-input'), '写第一段');
    await user.click(screen.getByTestId('chat-send'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    await user.type(screen.getByTestId('chat-input'), '写第二段');
    await user.click(screen.getByTestId('chat-send'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    // 手动切到第 1 条 → 插入第 1 条 body
    await user.click(screen.getByTestId('chat-select-0'));
    await user.click(screen.getByTestId('chat-insert-selected'));
    expect(useChapterStore.getState().content).toBe('第一段正文。');
    expect(useToastStore.getState().toasts.some((t) => t.message.includes('已插入正文'))).toBe(true);
  });

  it('不手动切换（默认最新选中）点插入 → 插入第 2 条 body', async () => {
    vi.useFakeTimers();
    statusMock.mockResolvedValueOnce(completedReply('好的，以下是续写内容：\n<<<CONTENT>>>\n第一段正文。\n<<<END>>>'));
    statusMock.mockResolvedValueOnce(completedReply('好的，以下是续写内容：\n<<<CONTENT>>>\n第二段正文。\n<<<END>>>'));
    const user = userEvent.setup();
    render(<ChatPanel {...OPTS} />);
    await user.type(screen.getByTestId('chat-input'), '写第一段');
    await user.click(screen.getByTestId('chat-send'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    await user.type(screen.getByTestId('chat-input'), '写第二段');
    await user.click(screen.getByTestId('chat-send'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    // 默认最新选中（第 2 条）→ 插入第 2 条 body
    await user.click(screen.getByTestId('chat-insert-selected'));
    expect(useChapterStore.getState().content).toBe('第二段正文。');
  });
});
