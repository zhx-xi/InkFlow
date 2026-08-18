/**
 * 底部 AI 聊天框（spec §4.1）：builtin:chat 单轮对话
 * - 发送 → useExecutionPoll.start({pipeline:'builtin:chat', project_id, variables:{prompt, chapter_context?}})
 * - 轮询/并发保护/错误态统一由 useExecutionPoll 承担（#472 R0，1s 间隔）
 * - completed → assistant 消息 + 「插入正文」→ chapterStore.setContent(final_output)
 * - failed → 错误文案（不插入正文）
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import type { PipelineExecuteRequest } from '../api/pipeline';
import { useExecutionPoll } from '../hooks/useExecutionPoll';
import { useI18n } from '../i18n/useI18n';
import { useChapterStore } from '../stores/chapter';
import { ensureModelReady } from '../stores/models';
import { useToastStore } from '../stores/toast';

export interface ChatPanelProps {
  projectId: string;
  chapterId?: string;
  chapterContent?: string;
}

interface ChatEntry {
  kind: 'user' | 'ai';
  seq: number;
  text: string;
  finalOutput?: string;
}

export function ChatPanel({ projectId, chapterId, chapterContent }: ChatPanelProps) {
  const { t } = useI18n();
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  const exec = useExecutionPoll();
  const userSeqRef = useRef(0);
  const aiSeqRef = useRef(0);

  const handleSend = useCallback(async () => {
    const prompt = input.trim();
    if (!prompt) return;
    // #474 P0：模型未配置前置校验（trim 非空后、exec.start 前）
    if (!(await ensureModelReady())) {
      useToastStore.getState().pushToast('warn', t('common.modelNotConfigured'));
      return;
    }
    setMessages((prev) => [...prev, { kind: 'user', seq: userSeqRef.current++, text: prompt }]);
    setInput('');
    const variables: Record<string, string> = { prompt };
    if (chapterContent) {
      variables.chapter_context = chapterContent;
    }
    const body: PipelineExecuteRequest = {
      project_id: projectId,
      pipeline: 'builtin:chat',
      ...(chapterId ? { chapter_id: chapterId } : {}),
      variables,
    };
    exec.start(body); // 并发保护在 hook 内（running 期间二次 start 无操作）
  }, [input, projectId, chapterId, chapterContent, exec.start, t]);

  // 轮询结果消费：status 只在 0→1 次变化（idle→running→success/failed），依赖 [status] 天然防重
  useEffect(() => {
    if (exec.status === 'success') {
      setMessages((prev) => [
        ...prev,
        {
          kind: 'ai',
          seq: aiSeqRef.current++,
          text: exec.finalOutput,
          finalOutput: exec.finalOutput,
        },
      ]);
    } else if (exec.status === 'failed') {
      setMessages((prev) => [
        ...prev,
        {
          kind: 'ai',
          seq: aiSeqRef.current++,
          text: t('write.chat.failed', { message: exec.error || '执行失败' }),
        },
      ]);
    }
  }, [exec.status]);

  const handleInsert = useCallback(
    (finalOutput: string) => {
      useChapterStore.getState().setContent(finalOutput);
      useToastStore.getState().pushToast('ok', t('write.chat.inserted'));
    },
    [t],
  );

  const handleInputKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  const canSend = input.trim() !== '';

  return (
    <div data-testid="chat-panel" className="flex flex-col gap-2 border-t border-line bg-surface-2 px-4 py-3">
      {messages.length > 0 && (
        <div className="max-h-40 space-y-1.5 overflow-y-auto text-[13px]">
          {messages.map((m) =>
            m.kind === 'user' ? (
              <div
                key={`user-${m.seq}`}
                data-testid={`chat-msg-user-${m.seq}`}
                className="text-ink"
              >
                {m.text}
              </div>
            ) : (
              <div
                key={`ai-${m.seq}`}
                data-testid={`chat-msg-ai-${m.seq}`}
                className="text-ink-2"
              >
                <div className="whitespace-pre-wrap">{m.text}</div>
                {m.finalOutput !== undefined && (
                  <button
                    type="button"
                    data-testid={`chat-insert-${m.seq}`}
                    aria-label={t('write.chat.insert')}
                    className="mt-1 rounded-md border border-line px-2 py-0.5 text-[12px] text-ink-2 hover:bg-surface-3"
                    onClick={() => handleInsert(m.finalOutput as string)}
                  >
                    {t('write.chat.insert')}
                  </button>
                )}
              </div>
            ),
          )}
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
          onClick={handleSend}
        >
          {t('write.chat.send')}
        </button>
      </div>
    </div>
  );
}
