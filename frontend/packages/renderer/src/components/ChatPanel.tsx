/**
 * 底部 AI 聊天框（spec §4.1，#541 流式版）：streamChat SSE 驱动
 * - 发送 → streamChat({project_id, prompt, chapter_id?, chapter_context?}, callbacks)
 * - 流式渐进：onDelta 逐字追加当前 ai 消息；onDone → parseChatReply 解析意图（#477 保留）
 * - onError → 错误文案（write.chat.failed），不插入正文
 * - 并发保护：流式 in-flight 时再次发送不触发第二次 streamChat；done/error 后可继续
 * - abort 清理：卸载时调用 streamChat 返回的 abort
 * - hermes 风格：user 靠右 / ai 靠左 + 角色标签 + space-y-3 空行
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MutableRefObject,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
} from 'react';
import {
  abortChatRun,
  archiveChatConversation,
  createChatConversation,
  deleteChatConversation,
  deleteChatMessage,
  fetchChatConversations,
  fetchChatMessages,
  resumeChatRun,
  saveChatMessage,
  streamChat,
  updateChatDeletePermission,
  type ChatMessageDto,
  type ChatStreamBody,
} from '../api/chat';
import { errorMessage } from '../api/client';
import type { PipelineStreamSink } from '../hooks/useExecutionPoll';
import { useI18n } from '../i18n/useI18n';
import { parseChatReply, type ChatIntent } from '../lib/chatIntent';
import { useChapterStore } from '../stores/chapter';
import { ensureModelReady } from '../stores/models';
import { useToastStore } from '../stores/toast';
import { ChatDeleteAuthControl } from './ChatDeleteAuthControl';

export interface ChatPanelProps {
  projectId: string;
  chapterId?: string;
  chapterContent?: string;
  /** #642-1：管线流式回调 sink（streamPipeline 的 delta/done 复用 ChatPanel 流式渲染管线） */
  streamSink?: MutableRefObject<PipelineStreamSink> | null;
  /** #770：full=全局 chat 页（占满、无 resize handle）；inline=章节内底部横栏（默认，可调 80~480px） */
  variant?: 'inline' | 'full';
  /** #840：URL 指定会话 id——提供时直接加载该会话（跳过“最新活跃线程/新建”解析） */
  conversationId?: string;
}

interface ChatEntry {
  kind: 'user' | 'ai';
  seq: number;
  text: string;
  /** #566/#581：历史消息 id（来自 ChatMessageDto；无 id = 流式新消息，删除按钮用 kind-seq testid 并仅本地移除） */
  id?: string;
  /** #477：AI 回复意图（content=可插入正文 / conversation=纯对话） */
  intent?: ChatIntent;
}

/** #597：agent 工具流条目（onToolCall 追加，onToolResult 按 id 填充 result） */
interface ToolEntry {
  id: string;
  name: string;
  args: Record<string, unknown>;
  result: string | null;
}

/** #476：对话区展开默认高度 + 拖动高度上下限（px） */
const CHAT_DEFAULT_HEIGHT = 160;
const CHAT_MIN_HEIGHT = 80;
const CHAT_MAX_HEIGHT = 480;

export function ChatPanel({
  projectId,
  chapterId,
  chapterContent,
  streamSink,
  variant = 'inline',
  conversationId: requestedConversationId,
}: ChatPanelProps) {
  const { t } = useI18n();
  const isFull = variant === 'full';
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  // #597：本轮 agent 工具调用/结果卡片（下标 = 数组内 index，首个工具调用 = 0）
  const [toolEntries, setToolEntries] = useState<ToolEntry[]>([]);
  // #477：当前选中的 content 消息 seq（单选互斥，新 content 到达自动成为选中条）
  const [selectedSeq, setSelectedSeq] = useState<number | null>(null);
  const [expanded, setExpanded] = useState(false);
  /** #681：管线输出区（管线 delta 独立渲染，非 chat AI 消息、不落库） */
  const [pipelineOutputEntries, setPipelineOutputEntries] = useState<{ seq: number; text: string }[]>([]);
  const [height, setHeight] = useState(CHAT_DEFAULT_HEIGHT);
  // #719：流式运行中渲染中断按钮（state 驱动重渲染；ref 供回调/并发保护）
  const [streaming, setStreaming] = useState(false);
  // #727：思考过程/工具调用折叠块展开状态（key = tool-${index} / reasoning-${index}）
  const [expandedBlocks, setExpandedBlocks] = useState<Record<string, boolean>>({});
  // #727：reasoning 帧条目（seq 独立递增 → 每帧独立折叠块）
  const [reasoningEntries, setReasoningEntries] = useState<{ seq: number; text: string }[]>([]);
  const dragRef = useRef<{ startY: number; startHeight: number } | null>(null);
  const userSeqRef = useRef(0);
  const aiSeqRef = useRef(0);
  /** #681：管线输出条目 seq（onDone 清空 → 下一轮管线重新起 seq） */
  const pipelineSeqRef = useRef<number | null>(null);
  // #541 流式状态：并发保护 + 当前 ai 消息渐进累计（ref 持有，避免回调闭包陈旧）
  const streamingRef = useRef(false);
  const streamSeqRef = useRef<number | null>(null);
  const streamTextRef = useRef('');
  const abortRef = useRef<(() => void) | null>(null);
  // #547：发送时的 projectId 快照（onDone/onError 保存 AI 消息仍落到原项目，避免闭包陈旧）
  const projectIdRef = useRef(projectId);
  // #770：章节 id 快照（挂载 effect 建会话时读最新章节名；不把 chapterId 纳入 effect 依赖，
  // 保持既有「仅 projectId/streamSink 变化才重解析线程」的加载语义）
  const chapterIdRef = useRef(chapterId);
  chapterIdRef.current = chapterId;
  // #744：当前线程 id 快照（防闭包陈旧，镜像 projectIdRef；归档后新建线程更新）
  const conversationIdRef = useRef<string | null>(null);
  // #744：当前线程 id（state 驱动渲染；与 ref 同步）
  const [conversationId, setConversationId] = useState<string | null>(null);
  // #766 阶段②：删除授权三态（默认 manual）+ HITL interrupt 弹窗 payload
  const [deletePermission, setDeletePermission] = useState<'manual' | 'ask_once' | 'auto'>('manual');
  const [interruptPayload, setInterruptPayload] = useState<{
    tool: string;
    entity_id: string;
    entity_name: string;
  } | null>(null);
  // #719：run_id 捕获（run_started 帧 → 中断时调后端 abort 端点）
  const runIdRef = useRef<string | null>(null);
  // #727：reasoning 条目 seq 计数器（每帧独立块）
  const reasoningSeqRef = useRef(0);
  // #726：消息区滚动容器 + 底部锚点（发送后自动滚动到底部）
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  // #745：每次提交 / 页面跳转加载历史后强制滚底（一次性标记，effect 消费后复位）
  const pendingScrollRef = useRef(false);

  /** #547/#840：挂载 / projectId / conversationId 变化 → 加载历史（失败静默，不打扰后续发送） */
  useEffect(() => {
    let cancelled = false;
    projectIdRef.current = projectId;
    const load = async () => {
      try {
        // #840：URL 指定会话 id 非空 → 直接加载该会话（跳过“最新活跃线程/新建”解析）
        let cid =
          requestedConversationId && requestedConversationId.trim() !== '' ? requestedConversationId : null;
        if (!cid) {
          const convs = await fetchChatConversations({ projectId, includeDeleted: false });
          if (cancelled) return;
          // #744：后端 GET /conversations 忽略 project_id，返回全部线程 → 必须本地按 project_id 过滤，
          // 否则会选到其它项目的活动线程（e2e 写作页跨用例消息残留根因）
          const active =
            convs.items.find((c) => c.project_id === projectId && !c.is_deleted) ?? null;
          cid = active ? active.conversation_id : null;
          if (!cid) {
            // #770：章节内建会话 title=章节名（章节锚点）；全局 chat 页（无章节）不传 title
            const chapterTitle = chapterIdRef.current
              ? useChapterStore.getState().chapters.find((c) => c.id === chapterIdRef.current)?.title
              : undefined;
            const created = chapterTitle
              ? await createChatConversation(projectId, { title: chapterTitle })
              : await createChatConversation(projectId);
            if (cancelled) return;
            cid = created.conversation_id;
          }
        }
        conversationIdRef.current = cid;
        setConversationId(cid);
        const res = await fetchChatMessages(cid);
        if (cancelled) return;
        let userSeq = 0;
        let aiSeq = 0;
        const history: ChatEntry[] = res.items.map((msg: ChatMessageDto) =>
          msg.role === 'user'
            ? { kind: 'user', seq: userSeq++, text: msg.content, id: msg.id }
            : {
                kind: 'ai',
                seq: aiSeq++,
                text: msg.content,
                intent: msg.intent ?? undefined,
                id: msg.id,
              },
        );
        // 历史最新 content 消息自动选中（仅存在 content 消息时）
        let latestContentSeq: number | null = null;
        for (const m of history) {
          if (m.kind === 'ai' && m.intent === 'content') latestContentSeq = m.seq;
        }
        userSeqRef.current = userSeq;
        aiSeqRef.current = aiSeq;
        // #745：页面跳转/重载历史后强制滚底
        pendingScrollRef.current = true;
        setMessages(history);
        // #597：切换项目/重载历史时清空上一轮工具卡片
        setToolEntries([]);
        setSelectedSeq(latestContentSeq);
        // #642-1：写作页（带 streamSink）挂载后历史非空 → 自动展开（管线回复重挂后仍可见）
        if (streamSink && history.length > 0) setExpanded(true);
      } catch {
        // 契约：历史加载失败静默，不弹 toast，后续发送仍可用
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [projectId, streamSink, requestedConversationId]);

  /** 流式 delta：追加到当前 ai 消息（首个 delta 创建消息占位） */
  const onDelta = useCallback((delta: string) => {
    streamTextRef.current += delta;
    if (streamSeqRef.current === null) {
      streamSeqRef.current = aiSeqRef.current++;
    }
    const seq = streamSeqRef.current;
    setMessages((prev) => {
      const next: ChatEntry = { kind: 'ai', seq, text: streamTextRef.current };
      const exists = prev.some((m) => m.kind === 'ai' && m.seq === seq);
      if (!exists) return [...prev, next];
      return prev.map((m) => (m.kind === 'ai' && m.seq === seq ? next : m));
    });
  }, []);

  /** 流式 done：对完整文本 parseChatReply 解析意图并落定消息形态 */
  const onDone = useCallback(() => {
    const seq = streamSeqRef.current;
    if (seq !== null) {
      const parsed = parseChatReply(streamTextRef.current);
      setMessages((prev) =>
        prev.map((m) =>
          m.kind === 'ai' && m.seq === seq ? { ...m, text: parsed.body, intent: parsed.intent } : m,
        ),
      );
      if (parsed.intent === 'content') {
        // 新 content 消息到达自动成为选中条（最新优先）
        setSelectedSeq(seq);
      }
      // #547：AI 回复落库（fire-and-forget；契约 = ChatPanel.test.tsx #547 describe）
      void saveChatMessage({
        project_id: projectIdRef.current,
        conversation_id: conversationIdRef.current ?? '',
        role: 'ai',
        content: parsed.body,
        intent: parsed.intent,
      }).catch(() => {});
    }
    streamingRef.current = false;
    streamSeqRef.current = null;
    streamTextRef.current = '';
    abortRef.current = null;
    // #719：done 后复位中断态与 run_id
    runIdRef.current = null;
    setStreaming(false);
  }, []);

  /** 流式 error：AI 消息显示错误文案（write.chat.failed），不插入正文 */
  const onError = useCallback(
    (message: string) => {
      const seq = streamSeqRef.current ?? aiSeqRef.current++;
      const entry: ChatEntry = {
        kind: 'ai',
        seq,
        text: t('write.chat.failed', { message }),
      };
      setMessages((prev) => {
        const exists = prev.some((m) => m.kind === 'ai' && m.seq === seq);
        if (!exists) return [...prev, entry];
        return prev.map((m) => (m.kind === 'ai' && m.seq === seq ? entry : m));
      });
      streamingRef.current = false;
      streamSeqRef.current = null;
      streamTextRef.current = '';
      abortRef.current = null;
      // #719：error 后复位中断态与 run_id
      runIdRef.current = null;
      setStreaming(false);
    },
    [t],
  );

  /** #597：工具调用帧 → 追加工具条目（result 待 tool_result 填充） */
  const onToolCall = useCallback((call: { id: string; name: string; args: Record<string, unknown> }) => {
    setToolEntries((prev) => [...prev, { ...call, result: null }]);
  }, []);

  /** #597：工具结果帧 → 按 id 匹配填充 result */
  const onToolResult = useCallback((res: { id: string; name: string; result: string }) => {
    setToolEntries((prev) => prev.map((e) => (e.id === res.id ? { ...e, result: res.result } : e)));
  }, []);

  /** #719：run_started 帧 → 捕获 run_id（中断时调后端 abort 端点） */
  const onRunStart = useCallback((runId: string) => {
    runIdRef.current = runId;
  }, []);

  /** #727：reasoning 帧 → 追加独立思考过程条目（seq 递增） */
  const onReasoning = useCallback((text: string) => {
    const seq = reasoningSeqRef.current++;
    setReasoningEntries((prev) => [...prev, { seq, text }]);
  }, []);

  /** #766 阶段②：interrupt 帧（HITL 删除授权确认）→ 打开确认弹窗 */
  const onInterrupt = useCallback((payload: { tool: string; entity_id: string; entity_name: string }) => {
    setInterruptPayload(payload);
  }, []);

  /** #766 阶段②：删除授权三态切换 → PATCH 服务端（线程缺失时先新建再 PATCH） */
  const handleDeleteModeChange = useCallback(async (mode: 'manual' | 'ask_once' | 'auto') => {
    setDeletePermission(mode);
    let cid = conversationIdRef.current;
    if (!cid) {
      try {
        const created = await createChatConversation(projectIdRef.current);
        cid = created.conversation_id;
        conversationIdRef.current = cid;
        setConversationId(cid);
      } catch {
        // 新建线程失败则跳过 PATCH（本地选中态保留，服务端权限不变）
      }
    }
    if (cid) {
      try {
        await updateChatDeletePermission(cid, mode);
      } catch {
        // PATCH 失败静默（不阻塞 UI）
      }
    }
  }, []);

  /** #766 阶段②：HITL 确认删除 → resume approved:true */
  const handleResumeApprove = useCallback(() => {
    void resumeChatRun({ conversation_id: conversationIdRef.current ?? '', approved: true }).catch(() => {});
    setInterruptPayload(null);
  }, []);

  /** #766 阶段②：HITL 取消删除 → resume approved:false */
  const handleResumeCancel = useCallback(() => {
    void resumeChatRun({ conversation_id: conversationIdRef.current ?? '', approved: false }).catch(() => {});
    setInterruptPayload(null);
  }, []);

  /** #727：折叠块展开切换（tool-${index} / reasoning-${index}） */
  const toggleBlock = useCallback((key: string) => {
    setExpandedBlocks((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  // #681：管线帧与 chat 帧区分渲染——管线 delta/done 走独立「管线输出」区，
  // 不进入 chat messages、不调 saveChatMessage（chat 流 #547 落库契约不受影响）
  useEffect(() => {
    const sink = streamSink?.current;
    if (!sink) return;
    sink.onDelta = (d) => {
      setExpanded(true);
      // 管线产物累积到 pipelineOutputEntries（非 AI 消息，不落 chat 历史）
      // 每条管线 delta 独立一个条目（seq 递增；ref 在 updater 外推进，保持 updater 纯净）
      if (pipelineSeqRef.current === null) pipelineSeqRef.current = 0;
      const seq = pipelineSeqRef.current;
      pipelineSeqRef.current += 1;
      setPipelineOutputEntries((prev) => {
        const exists = prev.find((e) => e.seq === seq);
        if (!exists) return [...prev, { seq, text: d }];
        return prev.map((e) => (e.seq === seq ? { ...e, text: e.text + d } : e));
      });
    };
    sink.onDone = () => {
      // 管线完成：不调 saveChatMessage，仅清管线 seq（下次管线 delta 重新起 seq）
      pipelineSeqRef.current = null;
    };
    sink.onToolCall = onToolCall;
    sink.onToolResult = onToolResult;
    return () => {
      sink.onDelta = undefined;
      sink.onDone = undefined;
      sink.onToolCall = undefined;
      sink.onToolResult = undefined;
    };
  }, [streamSink, onToolCall, onToolResult]);

  const handleSend = useCallback(async () => {
    const prompt = input.trim();
    if (!prompt || streamingRef.current) return;
    // #476：折叠态发送 → 自动展开，保证消息可见
    setExpanded(true);
    // #474 P0：模型未配置前置校验（trim 非空后、streamChat 前）
    if (!(await ensureModelReady())) {
      useToastStore.getState().pushToast('warn', t('common.modelNotConfigured'));
      return;
    }
    streamingRef.current = true;
    setStreaming(true);
    setMessages((prev) => [...prev, { kind: 'user', seq: userSeqRef.current++, text: prompt }]);
    // #745：本轮提交消息渲染后强制滚底
    pendingScrollRef.current = true;
    // #547：用户消息落库（fire-and-forget，不 await 不阻塞发送）
    // #547/#744：用户消息落库（fire-and-forget，不 await 不阻塞发送；线程异常缺失时先新建）
    let cid = conversationIdRef.current;
    if (!cid) {
      try {
        const chapterTitle = chapterId
          ? useChapterStore.getState().chapters.find((c) => c.id === chapterId)?.title
          : undefined;
        const created = chapterTitle
          ? await createChatConversation(projectId, { title: chapterTitle })
          : await createChatConversation(projectId);
        cid = created.conversation_id;
        conversationIdRef.current = cid;
        setConversationId(cid);
      } catch {
        // 新建线程失败不阻塞发送；AI 落库/下一轮发送会重试
      }
    }
    if (cid) {
      void saveChatMessage({
        project_id: projectId,
        conversation_id: cid,
        role: 'user',
        content: prompt,
      }).catch(() => {});
    }
    setInput('');
    const body: ChatStreamBody = {
      project_id: projectId,
      prompt,
      ...(chapterId ? { chapter_id: chapterId } : {}),
      ...(chapterContent ? { chapter_context: chapterContent } : {}),
    };
    void streamChat(body, { onDelta, onDone, onError, onToolCall, onToolResult, onRunStart, onReasoning, onInterrupt }).then(
      (abort) => {
        abortRef.current = abort;
      },
    );
  }, [input, projectId, chapterId, chapterContent, onDelta, onDone, onError, onToolCall, onToolResult, onRunStart, onReasoning, onInterrupt, t]);

  /** #719：中断当前流式运行（先调后端 abort 端点，再本地 abort + 复位发送态） */
  const handleInterrupt = useCallback(() => {
    if (runIdRef.current) void abortChatRun(runIdRef.current);
    abortRef.current?.();
    runIdRef.current = null;
    setStreaming(false);
    streamingRef.current = false;
    streamSeqRef.current = null;
    streamTextRef.current = '';
    abortRef.current = null;
  }, []);

  // #476 窗口级拖拽：#388 模式 —— mousedown(handle) 记录起点，window mousemove 更新高度，window mouseup 收尾
  const handleWindowMouseMove = useCallback((e: MouseEvent) => {
    const drag = dragRef.current;
    if (!drag) return;
    const next = Math.min(
      CHAT_MAX_HEIGHT,
      Math.max(CHAT_MIN_HEIGHT, drag.startHeight + (drag.startY - e.clientY)),
    );
    setHeight(next);
  }, []);

  const handleWindowMouseUp = useCallback(() => {
    dragRef.current = null;
    window.removeEventListener('mousemove', handleWindowMouseMove);
    window.removeEventListener('mouseup', handleWindowMouseUp);
  }, [handleWindowMouseMove]);

  const handleResizeMouseDown = useCallback(
    (e: ReactMouseEvent<HTMLDivElement>) => {
      e.preventDefault();
      dragRef.current = { startY: e.clientY, startHeight: height };
      window.addEventListener('mousemove', handleWindowMouseMove);
      window.addEventListener('mouseup', handleWindowMouseUp);
    },
    [height, handleWindowMouseMove, handleWindowMouseUp],
  );

  // 卸载时中止在途流式请求（streamChat 返回的 abort）
  useEffect(() => {
    return () => {
      abortRef.current?.();
    };
  }, []);

  // 卸载时清理拖拽监听，避免组件销毁后窗口残留监听
  useEffect(() => {
    return () => {
      dragRef.current = null;
      window.removeEventListener('mousemove', handleWindowMouseMove);
      window.removeEventListener('mouseup', handleWindowMouseUp);
    };
  }, [handleWindowMouseMove, handleWindowMouseUp]);

  // #726：发送后自动滚动到底部——仅当容器处于底部附近（用户未上滑）时拉底
  // #745：pendingScrollRef 置位时无条件拉底（每次提交 + 页面跳转/历史加载）
  useEffect(() => {
    const el = messagesRef.current;
    if (!el) return;
    if (pendingScrollRef.current) {
      pendingScrollRef.current = false;
      messagesEndRef.current?.scrollIntoView({ block: 'end' });
      return;
    }
    const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 60;
    if (atBottom) messagesEndRef.current?.scrollIntoView({ block: 'end' });
  }, [messages, toolEntries, reasoningEntries]);

  /** #642-2：per-message 插入（点击该条 content 消息直接插入该条 body，不再依赖 selectedSeq） */
  const handleInsertMessage = useCallback(
    (entry: ChatEntry) => {
      useChapterStore.getState().setContent(entry.text);
      useToastStore.getState().pushToast('ok', t('write.chat.inserted'));
    },
    [t],
  );

  /** #642-2：per-message 复制对话（防御性：jsdom 无 navigator.clipboard，静默；toast 提示已复制） */
  const handleCopyMessage = useCallback((entry: ChatEntry) => {
    try {
      void navigator.clipboard?.writeText?.(entry.text);
    } catch {
      /* 测试环境无 clipboard，静默 */
    }
    useToastStore.getState().pushToast('ok', t('write.chat.copied'));
  }, [t]);

  const handleInputKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        void handleSend();
      }
    },
    [handleSend],
  );

  /** #581：删除消息（有 id 真删 force=true；流式新消息无 id 仅本地移除） */
  const handleDeleteMessage = useCallback(async (entry: ChatEntry): Promise<void> => {
    try {
      if (entry.id) {
        await deleteChatMessage(entry.id);
      }
      setMessages((prev) =>
        entry.id
          ? prev.filter((m) => m.id !== entry.id)
          : prev.filter((m) => !(m.kind === entry.kind && m.seq === entry.seq)),
      );
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  }, []);

  /** #581：整轮归档（复用会话页归档 API：DELETE conversations/{projectId} 软删全部消息） */
  const handleArchiveRound = useCallback(async (): Promise<void> => {
    try {
      // #744：归档当前线程 -> 新建新线程（开新对话不复用旧 conversation）-> 清空本轮消息
      await archiveChatConversation(conversationIdRef.current ?? '');
      const chapterTitle = chapterId
        ? useChapterStore.getState().chapters.find((c) => c.id === chapterId)?.title
        : undefined;
      const newConv = chapterTitle
        ? await createChatConversation(projectIdRef.current, { title: chapterTitle })
        : await createChatConversation(projectIdRef.current);
      conversationIdRef.current = newConv.conversation_id;
      setConversationId(newConv.conversation_id);
      setMessages([]);
      setToolEntries([]);
      userSeqRef.current = 0;
      aiSeqRef.current = 0;
      // 新线程历史加载（新建线程为空；fire-and-forget，失败静默）
      void fetchChatMessages(newConv.conversation_id).catch(() => {});
      useToastStore.getState().pushToast('ok', t('sessions.archivedToast'));
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  }, [t, chapterId]);

  /** #581：整轮删除（force=true 物理删除，api/chat.ts deleteChatConversation 内部带 force） */
  const handleDeleteRound = useCallback(async (): Promise<void> => {
    try {
      // #744：真删当前线程 -> 新建新线程 -> 清空本轮消息
      await deleteChatConversation(conversationIdRef.current ?? '');
      const chapterTitle = chapterId
        ? useChapterStore.getState().chapters.find((c) => c.id === chapterId)?.title
        : undefined;
      const newConv = chapterTitle
        ? await createChatConversation(projectIdRef.current, { title: chapterTitle })
        : await createChatConversation(projectIdRef.current);
      conversationIdRef.current = newConv.conversation_id;
      setConversationId(newConv.conversation_id);
      setMessages([]);
      setToolEntries([]);
      userSeqRef.current = 0;
      aiSeqRef.current = 0;
      void fetchChatMessages(newConv.conversation_id).catch(() => {});
      useToastStore.getState().pushToast('ok', t('sessions.deletedToast'));
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  }, [t, chapterId]);

  const canSend = input.trim() !== '';

  return (
    <div
      data-testid="chat-panel"
      data-conversation-id={conversationId ?? undefined}
      className={`flex flex-col gap-2 border-b border-line bg-surface-2 px-4 py-3${isFull ? ' min-h-0 flex-1' : ''}`}
    >
      <div className="flex items-center gap-2">
        <button
          type="button"
          data-testid={expanded ? 'chat-collapse' : 'chat-expand'}
          aria-label={expanded ? t('write.chat.collapse') : t('write.chat.expand')}
          className="shrink-0 rounded px-1.5 text-ink-3 hover:bg-surface-3 hover:text-ink"
          onClick={() => setExpanded((v) => !v)}
        >
          …
        </button>
        {/* #642-2：resize-handle 从底部移到顶部行（toggle 之后；拖动逻辑不变） */}
        <div className="flex-1 flex justify-center">
          {!isFull && (
            <div
              data-testid="chat-resize-handle"
              className="flex h-1.5 cursor-ns-resize items-center justify-center"
              onMouseDown={handleResizeMouseDown}
            >
              <span className="block h-0.5 w-8 rounded-full bg-line" />
            </div>
          )}
        </div>
      </div>
      {(expanded || isFull) && messages.length > 0 && (
        <div
          data-testid="chat-messages"
          data-height={String(height)}
          ref={messagesRef}
          className={
            isFull
              ? 'min-h-0 flex-1 space-y-3 overflow-y-auto text-[13px]'
              : 'max-h-[480px] space-y-3 overflow-y-auto text-[13px]'
          }
          style={isFull ? undefined : { height }}
        >
          {/* #727：思考过程折叠块（在工具块之前展示） */}
          {reasoningEntries.map((entry, index) => {
            const blockKey = `reasoning-${index}`;
            const open = !!expandedBlocks[blockKey];
            return (
              <div
                key={blockKey}
                data-testid={`chat-reasoning-${index}`}
                aria-expanded={open}
                className="rounded-md border border-line bg-surface px-3 py-2 text-[12px]"
                onClick={() => toggleBlock(blockKey)}
              >
                <button
                  type="button"
                  data-testid={`chat-reasoning-toggle-${index}`}
                  aria-expanded={open}
                  className="flex w-full items-center gap-1.5 text-left"
                  onClick={(e) => {
                    e.stopPropagation();
                    toggleBlock(blockKey);
                  }}
                >
                  <span className="inline-block w-3 shrink-0 text-ink-3">{open ? '▾' : '›'}</span>
                  <span className="text-ink">🧠</span>
                  <span className="font-medium text-ink">{t('write.chat.thinking')}</span>
                  <span className="ml-auto text-[11px] text-ink-3">{t('write.chat.thinking')}</span>
                </button>
                {open && (
                  <div className="mt-1 whitespace-pre-wrap border-t border-line pt-1 text-ink-2">
                    {entry.text}
                  </div>
                )}
              </div>
            );
          })}
          {/* #727：agent 工具调用/结果折叠块（保留 #597 旧 testid chat-tool-call 与 chat-tool-result） */}
          {toolEntries.map((entry, index) => (
            <div
              key={`tool-${entry.id}-${index}`}
              data-testid={`chat-tool-${index}`}
              aria-expanded={!!expandedBlocks[`tool-${index}`]}
              className="rounded-md border border-line bg-surface px-3 py-2 text-[12px]"
              onClick={() => toggleBlock(`tool-${index}`)}
            >
              <button
                type="button"
                data-testid={`chat-tool-toggle-${index}`}
                aria-expanded={!!expandedBlocks[`tool-${index}`]}
                className="flex w-full items-center gap-1.5 text-left"
                onClick={(e) => {
                  e.stopPropagation();
                  toggleBlock(`tool-${index}`);
                }}
              >
                <span className="inline-block w-3 shrink-0 text-ink-3">
                  {expandedBlocks[`tool-${index}`] ? '▾' : '›'}
                </span>
                <span className="text-ink">🔧</span>
                <span className="font-medium text-ink" data-testid={`chat-tool-call-${index}`} data-name={entry.name}>
                  {entry.name}
                </span>
                <span className="ml-auto text-[11px] text-ink-3">{t('write.chat.toolCall')}</span>
              </button>
              {expandedBlocks[`tool-${index}`] && (
                <div className="mt-1 space-y-1 border-t border-line pt-1">
                  <div className="text-ink-2">参数: {JSON.stringify(entry.args)}</div>
                </div>
              )}
              {/* #597 兼容：result 卡片 testid 常驻 DOM（内容按折叠态显示） */}
              {entry.result !== null && (
                <div data-testid={`chat-tool-result-${index}`} className="text-ink-2">
                  {expandedBlocks[`tool-${index}`] && (
                    <>
                      <span className={entry.result.includes('"ok": false') ? 'text-err' : 'text-ink'}>
                        {entry.result.includes('"ok": false') ? '❌ ' : '✅ '}
                      </span>
                      <span className="whitespace-pre-wrap">{entry.result}</span>
                    </>
                  )}
                </div>
              )}
            </div>
          ))}
          {messages.map((m) => {
            const id = m.id;
            return m.kind === 'user' ? (
              <div
                key={`user-${m.seq}`}
                data-testid={`chat-msg-user-${m.seq}`}
                data-side="user"
                className="flex justify-end"
              >
                <div className="max-w-[85%] rounded-lg bg-surface-3 px-3 py-2 text-ink">
                  <span data-testid="chat-msg-role" className="mr-2 text-[11px] text-ink-3">
                    {t('write.chat.user')}
                  </span>
                  <span className="whitespace-pre-wrap">{m.text}</span>
                  <button
                    type="button"
                    data-testid={id ? `chat-msg-delete-${id}` : `chat-msg-delete-user-${m.seq}`}
                    aria-label={t('write.chat.delete')}
                    className="ml-2 rounded px-1 text-[11px] text-ink-3 hover:text-err"
                    onClick={() => void handleDeleteMessage(m)}
                  >
                    {t('write.chat.delete')}
                  </button>
                </div>
              </div>
            ) : (
              <div
                key={`ai-${m.seq}`}
                data-testid={`chat-msg-ai-${m.seq}`}
                data-side="ai"
                className="flex justify-start"
              >
                <div className="max-w-[85%] rounded-lg border border-line bg-surface px-3 py-2 text-ink-2">
                  <span data-testid="chat-msg-role" className="mr-2 text-[11px] text-ink-3">
                    {t('write.chat.ai')}
                  </span>
                  <span className="whitespace-pre-wrap">{m.text}</span>
                  <button
                    type="button"
                    data-testid={id ? `chat-msg-delete-${id}` : `chat-msg-delete-ai-${m.seq}`}
                    aria-label={t('write.chat.delete')}
                    className="ml-2 rounded px-1 text-[11px] text-ink-3 hover:text-err"
                    onClick={() => void handleDeleteMessage(m)}
                  >
                    {t('write.chat.delete')}
                  </button>
                  {/* #642-2：每条 AI 回复后跟复制按钮（复制对话） */}
                  <button
                    type="button"
                    data-testid={`chat-copy-${m.seq}`}
                    aria-label={t('write.chat.copy')}
                    className="ml-2 rounded px-1 text-[11px] text-ink-3 hover:text-ink"
                    onClick={() => void handleCopyMessage(m)}
                  >
                    {t('write.chat.copy')}
                  </button>
                  {/* #642-2：仅 content 意图消息渲染 per-message 插入按钮（替代原全局 chat-insert-selected） */}
                  {m.intent === 'content' && (
                    <button
                      type="button"
                      data-testid={`chat-insert-${m.seq}`}
                      aria-label={t('write.chat.insert')}
                      className="ml-2 rounded px-1 text-[11px] text-ink-3 hover:text-ink"
                      onClick={() => void handleInsertMessage(m)}
                    >
                      {t('write.chat.insert')}
                    </button>
                  )}
                  {/* #477：仅 content 意图消息渲染选择控件（单选互斥） */}
                  {m.intent === 'content' && (
                    <button
                      type="button"
                      data-testid={`chat-select-${m.seq}`}
                      data-selected={selectedSeq === m.seq ? 'true' : 'false'}
                      aria-label={t('write.chat.select')}
                      aria-pressed={selectedSeq === m.seq}
                      className="mt-1 block rounded-md border border-line px-2 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3"
                      onClick={() => setSelectedSeq(m.seq)}
                    >
                      {t('write.chat.select')}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
          {/* #726：滚动到底部锚点（新消息/工具/思考块到达后 scrollIntoView） */}
          <div data-testid="chat-scroll-anchor" ref={messagesEndRef} />
        </div>
      )}
      {/* #681：管线输出区——管线 delta/done 独立渲染（与 chat messages 分离，不落 chat 历史） */}
      {(expanded || isFull) && pipelineOutputEntries.length > 0 && (
        <div
          data-testid="pipeline-output-area"
          className="max-h-[240px] space-y-2 overflow-y-auto text-[13px]"
        >
          {pipelineOutputEntries.map((entry) => (
            <div
              key={`pipeline-${entry.seq}`}
              data-testid={`pipeline-output-${entry.seq}`}
              className="rounded-md border border-accent/30 bg-accent/5 px-3 py-2 text-ink-2"
            >
              <span className="mr-2 text-[11px] text-ink-3">管线输出</span>
              <span className="whitespace-pre-wrap">{entry.text}</span>
            </div>
          ))}
        </div>
      )}
      {/* #766 阶段②：删除授权三态分段控件 + HITL 确认弹窗（独立组件，行为不变） */}
      <ChatDeleteAuthControl
        deletePermission={deletePermission}
        onModeChange={handleDeleteModeChange}
        interruptPayload={interruptPayload}
        onApprove={handleResumeApprove}
        onCancel={handleResumeCancel}
      />
      <div className={`flex items-center gap-2${isFull ? ' mt-auto' : ''}`}>
        <textarea
          data-testid="chat-input"
          className="min-h-[40px] flex-1 resize-none rounded-md border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-accent"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleInputKeyDown}
          placeholder={t('write.chat.placeholder')}
          rows={1}
        />
        {streaming ? (
          <button
            type="button"
            data-testid="chat-interrupt"
            aria-label={t('write.chat.stop')}
            className="rounded-md bg-accent px-4 py-2 text-[13px] text-accent-ink hover:bg-accent-hover"
            onClick={() => void handleInterrupt()}
          >
            <span className="mr-1 inline-block h-2 w-2 rounded-[2px] bg-current" aria-hidden="true" />
            {t('write.chat.stop')}
          </button>
        ) : (
          <button
            type="button"
            data-testid="chat-send"
            disabled={!canSend}
            className="rounded-md bg-accent px-4 py-2 text-[13px] text-accent-ink hover:bg-accent-hover disabled:opacity-40"
            onClick={() => void handleSend()}
          >
            {t('write.chat.send')}
          </button>
        )}
      </div>
      {(expanded || isFull) && messages.length > 0 && (
        <div className="flex gap-2">
          <button
            type="button"
            data-testid="chat-round-archive"
            aria-label={t('write.chat.archiveRound')}
            className="rounded-md border border-line px-2 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3"
            onClick={() => void handleArchiveRound()}
          >
            {t('write.chat.archiveRound')}
          </button>
          <button
            type="button"
            data-testid="chat-round-delete"
            aria-label={t('write.chat.deleteRound')}
            className="rounded-md border border-line px-2 py-0.5 text-[12px] text-ink-2 hover:border-err/50 hover:text-err"
            onClick={() => void handleDeleteRound()}
          >
            {t('write.chat.deleteRound')}
          </button>
        </div>
      )}
    </div>
  );
}
