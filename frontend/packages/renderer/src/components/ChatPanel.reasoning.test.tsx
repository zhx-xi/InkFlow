/**
 * ChatPanel 思考级别选择器集成契约（F59-M3 #964，spec §3.4 / §13 M3）。
 * RED 批 B：ThinkingLevelSelect / lib/reasoningEffort / store.modelSupportsReasoning / ChatPanel.model prop
 * + 思考级别条件转发均未实现 → 本文件（除 reasoning 帧渲染回归守卫 12-14 与既有 exact-body 守护 10）逐用例 FAIL。
 * 只写测试，禁写实现；不 import 未建模块（只用 data-testid + streamChatMock 行为断言 → 逐用例 FAIL 而非收集期报错）。
 *
 * 契约（plan §四 共享契约，逐字为准）：
 * - testid：chat-reasoning-effort（select）/ chat-reasoning-effort-tooltip（disabled 时）
 * - 档位记忆 key：inkflow.reasoning_effort.<projectId>
 * - 发送 body：...(effort !== 'default' ? { reasoning_effort: effort } : {})（条件转发，default 不发）
 * - 置灰：capability === false → disabled + tooltip；capability === null（未知/未加载）→ 不禁用（软降级 A5）
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatPanel } from './ChatPanel';
import { apiFetch } from '../api/client';
import { executePipeline, getExecutionStatus } from '../api/pipeline';
import { useChapterStore } from '../stores/chapter';
import { useThemeStore } from '../stores/theme';
import { useModelsStore } from '../stores/models';
import { useToastStore } from '../stores/toast';

// ---- 既有 mock 形态（逐字镜像 ChatPanel.test.tsx）----------------------------------
vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});
// #541 轮询已替换为 SSE 流式；pipeline mock 保留仅为让旧实现惰性
vi.mock('../api/pipeline', () => ({
  executePipeline: vi.fn(),
  getExecutionStatus: vi.fn(),
  confirmExecution: vi.fn(),
}));

/** chat api 模块 mock 聚合（vi.hoisted 供 vi.mock 工厂引用） */
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
}));
vi.mock('../api/chat', () => chatApiMocks);

const streamChatMock = chatApiMocks.streamChat;
const apiFetchMock = vi.mocked(apiFetch);

// ---- 本地镜像类型（避免依赖未建模块；GREEN 由 api/chat.ts 导出）----------------------
interface ChatStreamBody {
  project_id: string;
  prompt: string;
  chapter_id?: string;
  chapter_context?: string;
  reasoning_effort?: string;
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
  onToolCall?: (call: { id: string; name: string; args: unknown }) => void;
  onToolResult?: (result: { id: string; name: string; result: string }) => void;
  /** #727：reasoning 帧 → 思考过程块 */
  onReasoning?: (text: string) => void;
}
interface CapturedChatStream {
  body: ChatStreamBody;
  callbacks: ChatStreamCallbacks;
}

// ---- 播种/helper 形态 -----------------------------------------------------------
const OPTS = { projectId: 'p1', chapterId: 'c1', chapterContent: '已有正文第一段。' };
const MODEL = 'f59-fake/o3-mini';
const EFFORT_KEY_PREFIX = 'inkflow.reasoning_effort.';
const effortKey = (projectId: string) => `${EFFORT_KEY_PREFIX}${projectId}`;

/** 本地镜像 ProviderConfig（含契约新字段 supports_reasoning —— GREEN 由 stores/models.ts 补） */
interface SeededProviderModel {
  id: string;
  type: 'chat' | 'embedding';
  roles: string[];
  supports_reasoning?: boolean | null;
}
interface SeededProvider {
  id: number;
  name: string;
  base_url: string;
  default_model: string;
  models: SeededProviderModel[];
  key_saved: boolean;
  max_retries: number;
  timeout: number;
  created_at: string;
  updated_at: string;
}

function seededProvider(modelId: string, supportsReasoning: boolean | null | undefined): SeededProvider {
  return {
    id: 1,
    name: 'f59-fake',
    base_url: 'http://fake/v1',
    default_model: modelId,
    models: [{ id: modelId, type: 'chat', roles: ['main'], supports_reasoning: supportsReasoning }],
    key_saved: true,
    max_retries: 3,
    timeout: 60,
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-08-05T10:00:00Z',
  };
}

/** 播种能力数据（必须播种，否则 ChatPanel 挂载/发送会走 loadProviders 的 apiFetch） */
function seedProviders(providers: SeededProvider[]) {
  // 契约新增字段 supports_reasoning 当前不在 ProviderConfig.model 上，类型断言规避 excess-property 检查
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  useModelsStore.setState({ providers: providers as any, loading: false, error: null, selectedModelId: null });
}

/** 渲染（ChatPanel.model prop 为 GREEN 新增；当前为多余 prop，React 忽略 → 不报错） */
function renderPanel(overrides?: Record<string, unknown>) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return render(<ChatPanel {...({ ...OPTS, ...overrides } as any)} />);
}

let capturedStreams: CapturedChatStream[] = [];

/** 输入 + 点发送；等待第 index+1 次 streamChat 被调用（index 默认 0） */
async function sendAndAwaitStream(user: ReturnType<typeof userEvent.setup>, text: string, index = 0) {
  await user.type(screen.getByTestId('chat-input'), text);
  await user.click(screen.getByTestId('chat-send'));
  await waitFor(() => {
    expect(streamChatMock).toHaveBeenCalledTimes(index + 1);
  });
}

/** 驱动第 index 次流的 reasoning 帧（#727 -> chat-reasoning-<n>） */
function emitReasoning(index: number, text: string) {
  act(() => {
    capturedStreams[index].callbacks.onReasoning?.(text);
  });
}

/** 驱动第 index 次流的 done 帧（复位 streaming → chat-send 重新可点；镜像 ChatPanel.test.tsx emitDone） */
function emitDone(index: number) {
  act(() => {
    capturedStreams[index].callbacks.onDone({ done: true });
  });
}

/** 通过 UI 改选思考档位（fireEvent.change；RED 下 selector 缺失 → seedMemory 用例在前，本 helper 仅在 GREEN 命中） */
function selectEffort(value: string) {
  fireEvent.change(screen.getByTestId('chat-reasoning-effort'), { target: { value } });
}

beforeEach(() => {
  // 铁律：localStorage 清零（档位记忆隔离）+ useModelsStore 重置
  localStorage.clear();
  useModelsStore.setState({ providers: [], loading: false, error: null, selectedModelId: null });

  streamChatMock.mockReset();
  capturedStreams = [];
  chatApiMocks.fetchChatMessages.mockReset();
  chatApiMocks.saveChatMessage.mockReset();
  chatApiMocks.fetchChatConversations.mockReset();
  chatApiMocks.archiveChatMessage.mockReset();
  chatApiMocks.deleteChatMessage.mockReset();
  chatApiMocks.restoreChatMessage.mockReset();
  chatApiMocks.archiveChatConversation.mockReset();
  chatApiMocks.deleteChatConversation.mockReset();
  chatApiMocks.createChatConversation.mockReset();

  // 历史加载/持久化 mock 默认值（镜像既有用例行为；历史空列表）
  chatApiMocks.fetchChatMessages.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
  chatApiMocks.deleteChatMessage.mockResolvedValue(undefined);
  chatApiMocks.archiveChatConversation.mockResolvedValue(undefined);
  chatApiMocks.deleteChatConversation.mockResolvedValue(undefined);
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
  chatApiMocks.createChatConversation.mockImplementation(async (projectId: string) => ({
    conversation_id: `conv-${projectId}`,
    project_id: projectId,
    project_name: null,
    last_message: '',
    message_count: 0,
    is_deleted: false,
    updated_at: '2026-08-21T10:00:00Z',
  }));
  // 默认 mock：返回 abort 函数 + 捕获 callbacks 供用例手动驱动
  streamChatMock.mockImplementation((body: ChatStreamBody, callbacks: ChatStreamCallbacks) => {
    capturedStreams.push({ body, callbacks });
    return Promise.resolve(() => {});
  });

  executeMock.mockReset();
  statusMock.mockReset();
  apiFetchMock.mockReset();
  // URL 分发：provider-configs 返回已配置 chat 模型（防 GREEN 挂载/发送时 loadProviders 覆盖播种失败 → 发送中断）
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/provider-configs') {
      return {
        items: [seededProvider('o3-mini', true)],
        total: 1,
        offset: 0,
        limit: 50,
      };
    }
    return { ok: true };
  });
  // 旧轮询 mock 惰性化（执行中永不完成）
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
  useToastStore.setState({ toasts: [] });
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

// execute/getExecutionStatus 别名（反映到 mock 惰性化设置）
const executeMock = vi.mocked(executePipeline);
const statusMock = vi.mocked(getExecutionStatus);

// ===================================================================================
// 组 1：选择器出现与默认值
// ===================================================================================
describe('ChatPanel — 思考级别选择器：出现与默认值（契约 §4.3 / plan §四）', () => {
  it('1. model=o3-mini(支持思考) + 无记忆 → chat-reasoning-effort 可见且值=default（跟随模型默认）', () => {
    seedProviders([seededProvider('o3-mini', true)]);
    renderPanel({ model: MODEL });
    const select = screen.getByTestId('chat-reasoning-effort') as HTMLSelectElement;
    expect(select).toBeInTheDocument();
    expect(select.value).toBe('default');
  });

  it('2. 未传 model prop（能力未知）→ 选择器仍渲染且不禁用（软降级 A5）', () => {
    renderPanel();
    const select = screen.getByTestId('chat-reasoning-effort') as HTMLSelectElement;
    expect(select).toBeInTheDocument();
    expect(select).not.toBeDisabled();
  });
});

// ===================================================================================
// 组 2：档位记忆（localStorage per-project）
// ===================================================================================
describe('ChatPanel — 思考档位记忆（inkflow.reasoning_effort.<projectId>）', () => {
  it('3. 预置 p1=high → 挂载后 select 值=high（readReasoningEffort 恢复）', () => {
    localStorage.setItem(effortKey('p1'), 'high');
    seedProviders([seededProvider('o3-mini', true)]);
    renderPanel({ model: MODEL });
    const select = screen.getByTestId('chat-reasoning-effort') as HTMLSelectElement;
    expect(select.value).toBe('high');
  });

  it('4. 改选 medium（fireEvent.change）→ localStorage p1=medium（writeReasoningEffort 落库）', () => {
    seedProviders([seededProvider('o3-mini', true)]);
    renderPanel({ model: MODEL });
    selectEffort('medium');
    expect(localStorage.getItem(effortKey('p1'))).toBe('medium');
  });

  it('5. 项目隔离：预置 p1=high，渲染 p2 → select 值=default（不串档）', () => {
    localStorage.setItem(effortKey('p1'), 'high');
    seedProviders([seededProvider('o3-mini', true)]);
    renderPanel({ projectId: 'p2', model: MODEL });
    const select = screen.getByTestId('chat-reasoning-effort') as HTMLSelectElement;
    expect(select.value).toBe('default');
  });
});

// ===================================================================================
// 组 3：置灰（能力数据源 = provider-configs 回显 / modelSupportsReasoning）
// ===================================================================================
describe('ChatPanel — 思考级别置灰（capability 驱动）', () => {
  it('6. supports_reasoning=false → select 禁用 + 出现 chat-reasoning-effort-tooltip 文案=当前模型不支持思考(zh)', () => {
    seedProviders([seededProvider('o3-mini', false)]);
    renderPanel({ model: MODEL });
    expect(screen.getByTestId('chat-reasoning-effort')).toBeDisabled();
    expect(screen.getByTestId('chat-reasoning-effort-tooltip')).toHaveTextContent('当前模型不支持思考');
  });

  it('7. supports_reasoning=true → 不 disabled、无 tooltip 元素', () => {
    seedProviders([seededProvider('o3-mini', true)]);
    renderPanel({ model: MODEL });
    const select = screen.getByTestId('chat-reasoning-effort') as HTMLSelectElement;
    expect(select).not.toBeDisabled();
    expect(screen.queryByTestId('chat-reasoning-effort-tooltip')).not.toBeInTheDocument();
  });

  it('8. providers 找不到该模型（supports_reasoning 未知）→ 不禁用（软降级，非阻断）', () => {
    // 播种一个不含 o3-mini 的 provider → modelSupportsReasoning('f59-fake/o3-mini') = null
    seedProviders([seededProvider('gpt-4o', true)]);
    renderPanel({ model: MODEL });
    const select = screen.getByTestId('chat-reasoning-effort') as HTMLSelectElement;
    expect(select).not.toBeDisabled();
    expect(screen.queryByTestId('chat-reasoning-effort-tooltip')).not.toBeInTheDocument();
  });
});

// ===================================================================================
// 组 4：发送传参（条件转发 + 仅作用下一轮）
// ===================================================================================
describe('ChatPanel — 发送传参（条件转发 reasoning_effort）', () => {
  it('9. 记忆 high 发送 → first-arg body 条件转发 reasoning_effort=high（first-arg 宽松匹配）', async () => {
    localStorage.setItem(effortKey('p1'), 'high');
    seedProviders([seededProvider('o3-mini', true)]);
    const user = userEvent.setup();
    renderPanel({ model: MODEL });
    await sendAndAwaitStream(user, '写一段带推理的续写');
    expect(streamChatMock.mock.calls[0][0]).toMatchObject({ reasoning_effort: 'high' });
  });

  it('10. 默认档（未选择）发送 → first-arg body 不含 reasoning_effort 键（守护既有 exact-body 契约，禁双钉）', async () => {
    seedProviders([seededProvider('o3-mini', true)]);
    const user = userEvent.setup();
    renderPanel({ model: MODEL });
    await sendAndAwaitStream(user, '保持默认档');
    const sentBody = streamChatMock.mock.calls[0][0] as Record<string, unknown>;
    expect('reasoning_effort' in sentBody).toBe(false);
  });

  it('11. 仅作用下一轮：记忆 high 发送(calls[0]=high) → 改选 low → 再发送(calls[1]=low)，calls[0] 仍为 high', async () => {
    localStorage.setItem(effortKey('p1'), 'high');
    seedProviders([seededProvider('o3-mini', true)]);
    const user = userEvent.setup();
    renderPanel({ model: MODEL });
    await sendAndAwaitStream(user, '第一轮');
    expect(streamChatMock.mock.calls[0][0]).toMatchObject({ reasoning_effort: 'high' });
    // 完成第一轮流（streaming 复位 → chat-send 重新可点；镜像 ChatPanel.test.tsx emitDone 形态）
    emitDone(0);
    // 改选 low（仅影响下一轮；不回写第一轮已发送 body）
    selectEffort('low');
    await sendAndAwaitStream(user, '第二轮', 1);
    expect(streamChatMock.mock.calls[1][0]).toMatchObject({ reasoning_effort: 'low' });
    expect(streamChatMock.mock.calls[0][0]).toMatchObject({ reasoning_effort: 'high' });
  });
});

// ===================================================================================
// 组 5：reasoning 帧渲染回归（#727 链路，UI 必须出现断言）
// ===================================================================================
describe('ChatPanel — reasoning 帧渲染回归（#727 chat-reasoning-<n>）', () => {
  it('12. onReasoning(先分析用户意图) → chat-reasoning-0 必须出现', async () => {
    const user = userEvent.setup();
    renderPanel();
    await sendAndAwaitStream(user, '请先分析意图');
    emitReasoning(0, '先分析用户意图');
    expect(await screen.findByTestId('chat-reasoning-0')).toBeInTheDocument();
  });

  it('13. 点 chat-reasoning-toggle-0 展开 → chat-reasoning-0 内文本含 先分析用户意图', async () => {
    const user = userEvent.setup();
    renderPanel();
    await sendAndAwaitStream(user, '请先分析意图');
    emitReasoning(0, '先分析用户意图');
    await screen.findByTestId('chat-reasoning-0');
    fireEvent.click(screen.getByTestId('chat-reasoning-toggle-0'));
    await waitFor(() => {
      expect(within(screen.getByTestId('chat-reasoning-0')).getByText('先分析用户意图')).toBeInTheDocument();
    });
  });

  it('14. 两次 reasoning 帧 → chat-reasoning-0 与 chat-reasoning-1 各 1 个（多帧不合并/不丢失）', async () => {
    const user = userEvent.setup();
    renderPanel();
    await sendAndAwaitStream(user, '两个推理');
    emitReasoning(0, '第一步思考');
    emitReasoning(0, '第二步思考');
    await waitFor(() => {
      expect(screen.getByTestId('chat-reasoning-0')).toBeInTheDocument();
      expect(screen.getByTestId('chat-reasoning-1')).toBeInTheDocument();
    });
    expect(screen.getAllByTestId('chat-reasoning-0')).toHaveLength(1);
    expect(screen.getAllByTestId('chat-reasoning-1')).toHaveLength(1);
  });
});
