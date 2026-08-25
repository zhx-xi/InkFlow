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
  archiveChatConversation,
  deleteChatConversation,
  deleteChatMessage,
  fetchChatMessages,
  saveChatMessage,
  streamChat,
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

export interface ChatPanelProps {
  projectId: string;
  chapterId?: string;
  chapterContent?: string;
  /** #642-1：管线流式回调 sink（streamPipeline 的 delta/done 复用 ChatPanel 流式渲染管线） */
  streamSink?: MutableRefObject<PipelineStreamSink> | null;
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

export function ChatPanel({ projectId, chapterId, chapterContent, streamSink }: ChatPanelProps) {
  const { t } = useI18n();
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  // #597：本轮 agent 工具调用/结果卡片（下标 = 数组内 index，首个工具调用 = 0）
  const [toolEntries, setToolEntries] = useState<ToolEntry[]>([]);
  // #477：当前选中的 content 消息 seq（单选互斥，新 content 到达自动成为选中条）
  const [selectedSeq, setSelectedSeq] = useState<number | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [height, setHeight] = useState(CHAT_DEFAULT_HEIGHT);
  const dragRef = useRef<{ startY: number; startHeight: number } | null>(null);
  const userSeqRef = useRef(0);
  const aiSeqRef = useRef(0);
  // #541 流式状态：并发保护 + 当前 ai 消息渐进累计（ref 持有，避免回调闭包陈旧）
  const streamingRef = useRef(false);
  const streamSeqRef = useRef<number | null>(null);
  const streamTextRef = useRef('');
  const abortRef = useRef<(() => void) | null>(null);
  // #547：发送时的 projectId 快照（onDone/onError 保存 AI 消息仍落到原项目，避免闭包陈旧）
  const projectIdRef = useRef(projectId);

  /** #547：挂载 / projectId 变化 → 加载历史（失败静默，不打扰后续发送） */
  useEffect(() => {
    let cancelled = false;
    projectIdRef.current = projectId;
    void fetchChatMessages(projectId)
      .then((res) => {
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
        setMessages(history);
        // #597：切换项目/重载历史时清空上一轮工具卡片
        setToolEntries([]);
        setSelectedSeq(latestContentSeq);
        // #642-1：写作页（带 streamSink）挂载后历史非空 → 自动展开（管线回复重挂后仍可见）
        if (streamSink && history.length > 0) setExpanded(true);
      })
      .catch(() => {
        // 契约：历史加载失败静默，不弹 toast，后续发送仍可用
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, streamSink]);

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
        role: 'ai',
        content: parsed.body,
        intent: parsed.intent,
      }).catch(() => {});
    }
    streamingRef.current = false;
    streamSeqRef.current = null;
    streamTextRef.current = '';
    abortRef.current = null;
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

  // #642-1：把 ChatPanel 既有流式 handler 挂到管线 streamSink，供 streamPipeline 复用
  useEffect(() => {
    const sink = streamSink?.current;
    if (!sink) return;
    // 复用 ChatPanel 既有 onDelta/onDone/onToolCall/onToolResult（流式渲染 + parseChatReply + saveChatMessage）
    // #642-1：管线 delta 到达 → 自动展开（与旧 agentOutput 注入 setExpanded(true) 行为一致）
    sink.onDelta = (d) => {
      setExpanded(true);
      onDelta(d);
    };
    sink.onDone = onDone;
    sink.onToolCall = onToolCall;
    sink.onToolResult = onToolResult;
    return () => {
      sink.onDelta = undefined;
      sink.onDone = undefined;
      sink.onToolCall = undefined;
      sink.onToolResult = undefined;
    };
  }, [streamSink, onDelta, onDone, onToolCall, onToolResult]);

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
    setMessages((prev) => [...prev, { kind: 'user', seq: userSeqRef.current++, text: prompt }]);
    // #547：用户消息落库（fire-and-forget，不 await 不阻塞发送）
    void saveChatMessage({ project_id: projectId, role: 'user', content: prompt }).catch(() => {});
    setInput('');
    const body: ChatStreamBody = {
      project_id: projectId,
      prompt,
      ...(chapterId ? { chapter_id: chapterId } : {}),
      ...(chapterContent ? { chapter_context: chapterContent } : {}),
    };
    void streamChat(body, { onDelta, onDone, onError, onToolCall, onToolResult }).then((abort) => {
      abortRef.current = abort;
    });
  }, [input, projectId, chapterId, chapterContent, onDelta, onDone, onError, onToolCall, onToolResult, t]);

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
      await archiveChatConversation(projectIdRef.current);
      setMessages([]);
      setToolEntries([]);
      useToastStore.getState().pushToast('ok', t('sessions.archivedToast'));
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  }, [t]);

  /** #581：整轮删除（force=true 物理删除，api/chat.ts deleteChatConversation 内部带 force） */
  const handleDeleteRound = useCallback(async (): Promise<void> => {
    try {
      await deleteChatConversation(projectIdRef.current);
      setMessages([]);
      setToolEntries([]);
      useToastStore.getState().pushToast('ok', t('sessions.deletedToast'));
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  }, [t]);

  const canSend = input.trim() !== '';

  return (
    <div data-testid="chat-panel" className="flex flex-col gap-2 border-b border-line bg-surface-2 px-4 py-3">
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
          <div
            data-testid="chat-resize-handle"
            className="flex h-1.5 cursor-ns-resize items-center justify-center"
            onMouseDown={handleResizeMouseDown}
          >
            <span className="block h-0.5 w-8 rounded-full bg-line" />
          </div>
        </div>
      </div>
      {expanded && messages.length > 0 && (
        <div
          data-testid="chat-messages"
          data-height={String(height)}
          className="max-h-[480px] space-y-3 overflow-y-auto text-[13px]"
          style={{ height }}
        >
          {/* #597：agent 工具调用/结果卡片（在 ai 消息前展示） */}
          {toolEntries.map((entry, index) => (
            <div key={`tool-${entry.id}-${index}`} className="space-y-1">
              <div
                data-testid={`chat-tool-call-${index}`}
                data-name={entry.name}
                className="rounded-md border border-line bg-surface px-3 py-2 text-[12px] text-ink-2"
              >
                <span className="font-medium text-ink">{entry.name}</span>
                <span className="ml-2 truncate">{JSON.stringify(entry.args)}</span>
              </div>
              {entry.result !== null && (
                <div
                  data-testid={`chat-tool-result-${index}`}
                  className="rounded-md border border-line bg-surface px-3 py-2 text-[12px] text-ink-2"
                >
                  {entry.result}
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
        </div>
      )}
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
        <button
          type="button"
          data-testid="chat-send"
          disabled={!canSend}
          className="rounded-md bg-accent px-4 py-2 text-[13px] text-accent-ink hover:bg-accent-hover disabled:opacity-40"
          onClick={() => void handleSend()}
        >
          {t('write.chat.send')}
        </button>
      </div>
      {expanded && messages.length > 0 && (
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
