/**
 * 底部 AI 聊天框（spec §4.1，#541 流式版）：streamChat SSE 驱动；delta 逐字追加 /
 * done 解析意图落库 / error 不插正文；卸载 abort；user 右 / ai 左。
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
  restoreChatConversation,
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
import {
  DEFAULT_REASONING_EFFORT,
  readReasoningEffort,
  writeReasoningEffort,
} from '../lib/reasoningEffort';
import { useChapterStore } from '../stores/chapter';
import { ensureModelReady, modelSupportsReasoning, useModelsStore } from '../stores/models';
import { useToastStore } from '../stores/toast';
import { ChatArchivedBanner } from './ChatArchivedBanner';
import { ChatDeleteAuthControl } from './ChatDeleteAuthControl';
import { ChatStreamBlocks } from './ChatStreamBlocks';
import { ThinkingLevelSelect } from './ThinkingLevelSelect';

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
  /** #964：当前模型（'provider/model' 形态；空 = 未知，不禁用选择器——软降级 A5） */
  model?: string | null;
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
  model,
}: ChatPanelProps) {
  const { t } = useI18n();
  const isFull = variant === 'full';
  // #964：思考档位能力数据源（provider-configs 回显 supports_reasoning，M2 已提供）
  const providers = useModelsStore((s) => s.providers);
  const modelsLoading = useModelsStore((s) => s.loading);
  const loadProviders = useModelsStore((s) => s.loadProviders);
  const capability = modelSupportsReasoning(providers, model);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  const [toolEntries, setToolEntries] = useState<ToolEntry[]>([]);
  // #477：当前选中 content 消息 seq（单选互斥）
  const [selectedSeq, setSelectedSeq] = useState<number | null>(null);
  const [expanded, setExpanded] = useState(false);
  /** #681：管线输出区（独立渲染、不落库） */
  const [pipelineOutputEntries, setPipelineOutputEntries] = useState<{ seq: number; text: string }[]>([]);
  const [height, setHeight] = useState(CHAT_DEFAULT_HEIGHT);
  // #719：流式运行中渲染中断按钮
  const [streaming, setStreaming] = useState(false);
  // #727：思考/工具折叠块展开状态
  const [expandedBlocks, setExpandedBlocks] = useState<Record<string, boolean>>({});
  const [reasoningEntries, setReasoningEntries] = useState<{ seq: number; text: string }[]>([]);
  const dragRef = useRef<{ startY: number; startHeight: number } | null>(null);
  const userSeqRef = useRef(0);
  const aiSeqRef = useRef(0);
  /** #681：管线输出条目 seq */
  const pipelineSeqRef = useRef<number | null>(null);
  // #541 流式状态：并发保护 + ai 消息累计
  const streamingRef = useRef(false);
  const streamSeqRef = useRef<number | null>(null);
  const streamTextRef = useRef('');
  const abortRef = useRef<(() => void) | null>(null);
  // #547：projectId 快照（流式回调落库仍落原项目）
  const projectIdRef = useRef(projectId);
  // #770：章节 id 快照（挂载建会话时读最新章节名；不纳入 effect 依赖）
  const chapterIdRef = useRef(chapterId);
  chapterIdRef.current = chapterId;
  const conversationIdRef = useRef<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  // #766 阶段②：删除授权三态 + HITL interrupt payload
  const [deletePermission, setDeletePermission] = useState<'manual' | 'ask_once' | 'auto'>('manual');
  const [interruptPayload, setInterruptPayload] = useState<{
    tool: string;
    entity_id: string;
    entity_name: string;
  } | null>(null);
  // #1015：URL 指定归档会话 → 横幅只读模式（meta 查不到/失败保守按活动处理）
  const [archived, setArchived] = useState(false);
  // #719：run_id 捕获（中断时调后端 abort）
  const runIdRef = useRef<string | null>(null);
  const reasoningSeqRef = useRef(0);
  // #964：思考级别档位（localStorage per-project 记忆，跨刷新保持）
  const [reasoningEffort, setReasoningEffort] = useState<string>(() =>
    readReasoningEffort(projectId),
  );
  useEffect(() => {
    setReasoningEffort(readReasoningEffort(projectId));
  }, [projectId]);
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  // #745：提交/加载历史后强制滚底标记（effect 消费后复位）
  const pendingScrollRef = useRef(false);

  // #964：model 已知但注册表未加载 → 静默拉取能力数据（失败不 toast，capability 保持 null）
  useEffect(() => {
    if (model && providers.length === 0 && !modelsLoading) {
      void loadProviders();
    }
  }, [model, providers.length, modelsLoading, loadProviders]);

  /** #547/#840/#1015：挂载 / projectId / conversationId 变化 → 加载历史（失败静默；URL 指定归档会话只读） */
  useEffect(() => {
    let cancelled = false;
    projectIdRef.current = projectId;
    setArchived(false);
    const load = async () => {
      try {
        // #840/#1015：URL 指定会话 → 直接加载（先 meta 判归档）
        let cid =
          requestedConversationId && requestedConversationId.trim() !== '' ? requestedConversationId : null;
        let isArchived = false;
        if (cid) {
          try {
            const convs = await fetchChatConversations({ projectId, includeDeleted: true });
            if (cancelled) return;
            isArchived =
              convs.items.find((c) => c.conversation_id === cid)?.is_deleted ?? false;
            if (isArchived) setArchived(true);
          } catch {
            // meta 查询失败：保守按活动会话处理（不阻塞消息加载）
          }
        }
        if (!cid) {
          const convs = await fetchChatConversations({ projectId, includeDeleted: false });
          if (cancelled) return;
          // #744：GET /conversations 忽略 project_id → 本地按 project_id 过滤活动线程
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
        const res = isArchived
          ? await fetchChatMessages(cid, 0, 50, { includeDeleted: true })
          : await fetchChatMessages(cid);
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
        let latestContentSeq: number | null = null;
        for (const m of history) {
          if (m.kind === 'ai' && m.intent === 'content') latestContentSeq = m.seq;
        }
        userSeqRef.current = userSeq;
        aiSeqRef.current = aiSeq;
        pendingScrollRef.current = true;
        setMessages(history);
        setToolEntries([]);
        setSelectedSeq(latestContentSeq);
        if (streamSink && history.length > 0) setExpanded(true);
      } catch {
        // 契约：历史加载失败静默（不弹 toast，后续发送仍可用）
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [projectId, streamSink, requestedConversationId]);

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
        setSelectedSeq(seq);
      }
      // #547：AI 回复落库（fire-and-forget）
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
    runIdRef.current = null;
    setStreaming(false);
  }, []);

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
      runIdRef.current = null;
      setStreaming(false);
    },
    [t],
  );

  const onToolCall = useCallback((call: { id: string; name: string; args: Record<string, unknown> }) => {
    setToolEntries((prev) => [...prev, { ...call, result: null }]);
  }, []);

  const onToolResult = useCallback((res: { id: string; name: string; result: string }) => {
    setToolEntries((prev) => prev.map((e) => (e.id === res.id ? { ...e, result: res.result } : e)));
  }, []);

  const onRunStart = useCallback((runId: string) => {
    runIdRef.current = runId;
  }, []);

  const onReasoning = useCallback((text: string) => {
    const seq = reasoningSeqRef.current++;
    setReasoningEntries((prev) => [...prev, { seq, text }]);
  }, []);

  const onInterrupt = useCallback((payload: { tool: string; entity_id: string; entity_name: string }) => {
    setInterruptPayload(payload);
  }, []);

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
        // PATCH 失败静默
      }
    }
  }, []);

  const handleResumeApprove = useCallback(() => {
    void resumeChatRun({ conversation_id: conversationIdRef.current ?? '', approved: true }).catch(() => {});
    setInterruptPayload(null);
  }, []);

  const handleResumeCancel = useCallback(() => {
    void resumeChatRun({ conversation_id: conversationIdRef.current ?? '', approved: false }).catch(() => {});
    setInterruptPayload(null);
  }, []);

  /** #964：改选档位 → setState + localStorage 落库（仅作用于下一轮发送） */
  const handleReasoningEffortChange = useCallback((v: string) => {
    setReasoningEffort(v);
    writeReasoningEffort(projectIdRef.current, v);
  }, []);

  const toggleBlock = useCallback((key: string) => {
    setExpandedBlocks((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  // #681：管线 delta/done 走独立输出区，不进 chat 消息、不调 saveChatMessage
  useEffect(() => {
    const sink = streamSink?.current;
    if (!sink) return;
    sink.onDelta = (d) => {
      setExpanded(true);
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
    setExpanded(true);
    // #474 P0 / #487：模型未配置/加载失败前置校验
    try {
      if (!(await ensureModelReady())) {
        useToastStore.getState().pushToast('warn', t('common.modelNotConfigured'));
        return;
      }
    } catch (err) { useToastStore.getState().pushToast('err', errorMessage(err)); return; }
    streamingRef.current = true;
    setStreaming(true);
    setMessages((prev) => [...prev, { kind: 'user', seq: userSeqRef.current++, text: prompt }]);
    pendingScrollRef.current = true;
    // #547/#744：用户消息落库（fire-and-forget；线程缺失先新建）
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
        // 新建线程失败不阻塞发送；下一轮发送重试
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
      // #964：条件转发——default 不发 reasoning_effort 键（镜像后端「default 不发参数」；
      // 既有 streamChat exact-body 断言零破坏）
      ...(reasoningEffort !== DEFAULT_REASONING_EFFORT
        ? { reasoning_effort: reasoningEffort }
        : {}),
    };
    void streamChat(body, { onDelta, onDone, onError, onToolCall, onToolResult, onRunStart, onReasoning, onInterrupt }).then(
      (abort) => {
        abortRef.current = abort;
      },
    );
  }, [input, projectId, chapterId, chapterContent, reasoningEffort, onDelta, onDone, onError, onToolCall, onToolResult, onRunStart, onReasoning, onInterrupt, t]);

  /** #719：中断当前流式运行 */
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

  useEffect(() => {
    return () => {
      if (runIdRef.current) void abortChatRun(runIdRef.current);
      abortRef.current?.();
    };
  }, []);

  useEffect(() => {
    return () => {
      dragRef.current = null;
      window.removeEventListener('mousemove', handleWindowMouseMove);
      window.removeEventListener('mouseup', handleWindowMouseUp);
    };
  }, [handleWindowMouseMove, handleWindowMouseUp]);

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

  /** #642-2：per-message 插入 */
  const handleInsertMessage = useCallback(
    (entry: ChatEntry) => {
      useChapterStore.getState().setContent(entry.text);
      useToastStore.getState().pushToast('ok', t('write.chat.inserted'));
    },
    [t],
  );

  /** #642-2：per-message 复制对话 */
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

  /** #581：删除消息（有 id 真删；无 id 仅本地移除） */
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

  /** #581：整轮归档（DELETE conversations/{id} 软删） */
  const handleArchiveRound = useCallback(async (): Promise<void> => {
    try {
      // #744：归档当前线程 → 建新线程 → 清空本轮消息
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
      // 新线程历史加载（fire-and-forget，失败静默）
      void fetchChatMessages(newConv.conversation_id).catch(() => {});
      useToastStore.getState().pushToast('ok', t('sessions.archivedToast'));
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  }, [t, chapterId]);

  /** #581：整轮删除（force=true 物理删除） */
  const handleDeleteRound = useCallback(async (): Promise<void> => {
    try {
      // #744：真删当前线程 → 建新线程 → 清空本轮消息
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

  /** #1015：归档横幅恢复 → restoreChatConversation(cid) 成功解除只读 + ok toast */
  const restoreFromBanner = useCallback(async (): Promise<void> => {
    const cid = conversationIdRef.current;
    if (!cid) return;
    try {
      await restoreChatConversation(cid);
      setArchived(false);
      useToastStore.getState().pushToast('ok', t('sessions.restoredToast'));
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  }, [t]);

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
        {/* #642-2：resize-handle 置顶行（拖动逻辑不变） */}
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
      {/* #1015：归档只读横幅 */}
      {archived && (expanded || isFull) && (
        <ChatArchivedBanner onRestore={() => void restoreFromBanner()} />
      )}
      {(expanded || isFull) && messages.length > 0 && (
        <div
          data-testid="chat-messages"
          data-height={String(height)}
          aria-live="polite"
          ref={messagesRef}
          className={
            isFull
              ? 'min-h-0 flex-1 space-y-3 overflow-y-auto text-[13px]'
              : 'max-h-[480px] space-y-3 overflow-y-auto text-[13px]'
          }
          style={isFull ? undefined : { height }}
        >
          <ChatStreamBlocks
            reasoningEntries={reasoningEntries}
            toolEntries={toolEntries}
            expandedBlocks={expandedBlocks}
            onToggle={toggleBlock}
          />
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
                  {/* #642-2：每条 AI 回复后跟复制按钮 */}
                  <button
                    type="button"
                    data-testid={`chat-copy-${m.seq}`}
                    aria-label={t('write.chat.copy')}
                    className="ml-2 rounded px-1 text-[11px] text-ink-3 hover:text-ink"
                    onClick={() => void handleCopyMessage(m)}
                  >
                    {t('write.chat.copy')}
                  </button>
                  {/* #642-2：content 意图渲染 per-message 插入按钮 */}
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
                  {/* #477：content 意图渲染选择控件 */}
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
          {/* #726：滚动到底部锚点 */}
          <div data-testid="chat-scroll-anchor" ref={messagesEndRef} />
        </div>
      )}
      {/* #681：管线输出区（独立渲染、不落 chat） */}
      {(expanded || isFull) && pipelineOutputEntries.length > 0 && (
        <div
          data-testid="pipeline-output-area"
          aria-live="polite"
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
      {archived ? null : (
        <div data-testid="chat-compose" className={`flex flex-col gap-2${isFull ? ' mt-auto' : ''}`}>
          {/* #766 阶段②：删除授权控件 + HITL 弹窗 */}
          <ChatDeleteAuthControl
            deletePermission={deletePermission}
            onModeChange={handleDeleteModeChange}
            interruptPayload={interruptPayload}
            onApprove={handleResumeApprove}
            onCancel={handleResumeCancel}
          />
          <div className="flex items-center gap-2">
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
          {/* #964：思考级别选择器（textarea 行下方；capability=false 置灰 + tooltip，
              未知/null 不禁用——软降级 A5） */}
          <ThinkingLevelSelect
            value={reasoningEffort}
            onChange={handleReasoningEffortChange}
            disabled={capability === false}
            disabledTooltip={t('reasoning.chat.disabledTooltip')}
          />
        </div>
      )}
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
