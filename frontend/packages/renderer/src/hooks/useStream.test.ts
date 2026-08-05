/**
 * useStream hook 测试契约（Issue #79 RED 阶段，spec §4.5 SSE 流式渲染）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须新建 src/hooks/useStream.ts 并匹配：
 *
 * export type StreamMode = 'generate' | 'continue' | 'revise';
 * export interface StreamParams {
 *   outline?: string;          // generate: 大纲/提示（缺省 ''）
 *   minWords?: number;         // generate
 *   existingContent?: string;  // continue: 缺省 = chapterStore.getState().content
 *   targetWords?: number;      // continue
 *   feedback?: string;         // revise: 缺省 ''
 * }
 * export interface StreamSummary { wordCount?: number; model?: string; formatValid?: boolean; warnings?: string[] }
 * export function useStream(options: { projectId: string; chapterId: string }): {
 *   status: StreamStatus;              // 'idle' | 'generating' | 'done' | 'error' | 'stopped'
 *   text: string;                      // delta 累积渲染文本
 *   wordCount: number;                 // 实时字数（客户端累积估算 = 非空白字符数）；done 帧回填精确值
 *   summary: StreamSummary | null;
 *   error: string | null;
 *   start: (mode: StreamMode, params?: StreamParams) => void;   // 生成中再次调用 = 无操作（防并发流）
 *   stop: () => void;                  // abort() + status 'stopped'
 *   retry: () => void;                 // 以最近一次 mode/params 重发（format_valid=false 手动重试，从头重拉）
 * }
 *
 * 传输契约（复用 src/api/sse.ts streamWriting，真实模块）：
 * - POST {baseURL}/api/v1/writing/stream，body 按 mode 对齐 StreamGenerateBody/ContinueBody/ReviseBody
 * - 帧: {delta, done:false} × N → {done:true, format_valid?, word_count?, model?, warnings?}；流中错误 {done:true, error}
 * - 停止: AbortController.abort()
 * - done 帧 → 一次性 chapterStore.setContent(累积文本)（store 边界，§4.5）
 * - error 帧 → error 状态 + 前文保留（不提交 store）
 * - 生命周期不入 store（AbortController/reader 由 hook 持有）
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { useStream } from './useStream';
import { useChapterStore } from '../stores/chapter';

/** 可控 SSE 流：测试手动逐帧 enqueue（frontend-testing 模式：手动触发替代 fake timers） */
function createControllableStream() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({
    start(c) { controller = c; },
  });
  return { stream, controller };
}

/** SSE 帧编码（F23 §6.3: data: JSON 行 + \n\n 空行） */
function frame(payload: Record<string, unknown>): Uint8Array {
  return new TextEncoder().encode(`data: ${JSON.stringify(payload)}\n\n`);
}

const BASE = 'http://test.local';

interface FetchCall {
  url: string;
  init: RequestInit;
  controller: ReadableStreamDefaultController<Uint8Array>;
}

/** 全局 fetch mock：每次调用返回一个新的可控流 */
function stubStreamFetch(calls: FetchCall[]) {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    const { stream, controller } = createControllableStream();
    calls.push({ url, init: init ?? {}, controller });
    return Promise.resolve({ ok: true, body: stream } as unknown as Response);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

beforeEach(() => {
  vi.unstubAllGlobals();
  window.INKFLOW_API = { baseURL: BASE, token: 'tok-1' };
  useChapterStore.setState({ volumes: [], chapters: [], currentChapterId: 'c1', content: '已有正文', loading: false, error: null });
});

afterEach(() => {
  delete window.INKFLOW_API;
});

describe('useStream — 状态机（idle → generating → done | error | stopped）', () => {
  it('初始状态：idle / 空文本 / 零字数 / 无摘要 / 无错误', () => {
    const { result } = renderHook(() => useStream({ projectId: 'p1', chapterId: 'c1' }));
    expect(result.current.status).toBe('idle');
    expect(result.current.text).toBe('');
    expect(result.current.wordCount).toBe(0);
    expect(result.current.summary).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('start(continue)：POST /writing/stream，body 对齐 StreamContinueBody，状态进入 generating', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const { result } = renderHook(() => useStream({ projectId: 'p1', chapterId: 'c1' }));

    act(() => {
      result.current.start('continue', { targetWords: 1000 });
    });

    await waitFor(() => expect(result.current.status).toBe('generating'));
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(`${BASE}/api/v1/writing/stream`);
    const parsed = JSON.parse(String(calls[0].init.body)) as Record<string, unknown>;
    expect(parsed).toEqual({
      mode: 'continue',
      project_id: 'p1',
      chapter_id: 'c1',
      existing_content: '已有正文',
      target_words: 1000,
    });
    const headers = calls[0].init.headers as Record<string, string>;
    expect(headers['Content-Type']).toContain('application/json');
    expect(headers['X-InkFlow-Token']).toBe('tok-1');
  });

  it('start(generate)：body 对齐 StreamGenerateBody（outline/min_words）', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const { result } = renderHook(() => useStream({ projectId: 'p1', chapterId: 'c1' }));
    act(() => {
      result.current.start('generate', { outline: '第一卷大纲', minWords: 800 });
    });
    await waitFor(() => expect(calls).toHaveLength(1));
    const parsed = JSON.parse(String(calls[0].init.body)) as Record<string, unknown>;
    expect(parsed).toEqual({
      mode: 'generate',
      project_id: 'p1',
      chapter_id: 'c1',
      outline: '第一卷大纲',
      min_words: 800,
    });
  });

  it('start(revise)：body 对齐 StreamReviseBody（content 取 store 正文 + feedback）', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const { result } = renderHook(() => useStream({ projectId: 'p1', chapterId: 'c1' }));
    act(() => {
      result.current.start('revise', { feedback: '对话更生动' });
    });
    await waitFor(() => expect(calls).toHaveLength(1));
    const parsed = JSON.parse(String(calls[0].init.body)) as Record<string, unknown>;
    expect(parsed).toEqual({
      mode: 'revise',
      project_id: 'p1',
      chapter_id: 'c1',
      content: '已有正文',
      feedback: '对话更生动',
    });
  });
});

describe('useStream — delta 帧逐段累积 + 实时字数', () => {
  it('delta 帧逐段累积渲染文本，实时字数 = 客户端累积估算（非空白字符数）', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const { result } = renderHook(() => useStream({ projectId: 'p1', chapterId: 'c1' }));
    act(() => {
      result.current.start('continue');
    });
    await waitFor(() => expect(calls).toHaveLength(1));

    act(() => {
      calls[0].controller.enqueue(frame({ delta: '第一段', done: false }));
    });
    await waitFor(() => expect(result.current.text).toBe('第一段'));
    expect(result.current.wordCount).toBe(3);

    act(() => {
      calls[0].controller.enqueue(frame({ delta: '，第二段。', done: false }));
    });
    await waitFor(() => expect(result.current.text).toBe('第一段，第二段。'));
    expect(result.current.wordCount).toBe(8);
    // 流式期间不提交 store（store 边界：done 帧一次性提交）
    expect(useChapterStore.getState().content).toBe('已有正文');
  });

  it('done 帧：状态 done + 摘要（word_count/model/format_valid/warnings）+ store 一次性提交 + 字数回填精确值', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const { result } = renderHook(() => useStream({ projectId: 'p1', chapterId: 'c1' }));
    act(() => {
      result.current.start('continue');
    });
    await waitFor(() => expect(calls).toHaveLength(1));

    act(() => {
      calls[0].controller.enqueue(frame({ delta: '流式正文。', done: false }));
    });
    await waitFor(() => expect(result.current.text).toBe('流式正文。'));

    act(() => {
      calls[0].controller.enqueue(frame({
        done: true,
        format_valid: true,
        word_count: 1234,
        model: 'gpt-4o',
        token_usage: { total_tokens: 1560 },
        warnings: [],
      }));
    });

    await waitFor(() => expect(result.current.status).toBe('done'));
    expect(result.current.summary).toEqual({
      wordCount: 1234,
      model: 'gpt-4o',
      formatValid: true,
      warnings: [],
    });
    // 字数回填 done 帧精确值
    expect(result.current.wordCount).toBe(1234);
    // 一次性提交 chapterStore
    expect(useChapterStore.getState().content).toBe('流式正文。');
  });
});

describe('useStream — format_valid=false：warnings + 手动重试（不自动重试）', () => {
  it('done 帧 format_valid=false：展示 warnings，不自动重试（fetch 仅 1 次）', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const { result } = renderHook(() => useStream({ projectId: 'p1', chapterId: 'c1' }));
    act(() => {
      result.current.start('continue');
    });
    await waitFor(() => expect(calls).toHaveLength(1));
    act(() => {
      calls[0].controller.enqueue(frame({
        done: true,
        format_valid: false,
        word_count: 120,
        model: 'gpt-4o',
        warnings: ['章节开头缺少主角名', '存在重复段落'],
      }));
    });
    await waitFor(() => expect(result.current.status).toBe('done'));
    expect(result.current.summary?.formatValid).toBe(false);
    expect(result.current.summary?.warnings).toEqual(['章节开头缺少主角名', '存在重复段落']);
    // 不自动重试
    await new Promise((r) => setTimeout(r, 20));
    expect(calls).toHaveLength(1);
  });

  it('retry()：手动重试 = 从头重拉（text 重置，新流）', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const { result } = renderHook(() => useStream({ projectId: 'p1', chapterId: 'c1' }));
    act(() => {
      result.current.start('continue');
    });
    await waitFor(() => expect(calls).toHaveLength(1));
    act(() => {
      calls[0].controller.enqueue(frame({ delta: '草稿文字', done: false }));
    });
    await waitFor(() => expect(result.current.text).toBe('草稿文字'));
    act(() => {
      calls[0].controller.enqueue(frame({ done: true, format_valid: false, warnings: ['缺少主角'] }));
    });
    await waitFor(() => expect(result.current.status).toBe('done'));

    act(() => {
      result.current.retry();
    });
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(result.current.status).toBe('generating');
    // 从头重拉：旧文本清空
    expect(result.current.text).toBe('');
    act(() => {
      calls[1].controller.enqueue(frame({ delta: '重写内容', done: false }));
    });
    await waitFor(() => expect(result.current.text).toBe('重写内容'));
  });
});

describe('useStream — error 帧 / 停止 / 并发 / store 边界', () => {
  it('error 帧：状态 error + 错误消息 + 已生成前文保留 + store 不提交', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const { result } = renderHook(() => useStream({ projectId: 'p1', chapterId: 'c1' }));
    act(() => {
      result.current.start('continue');
    });
    await waitFor(() => expect(calls).toHaveLength(1));
    act(() => {
      calls[0].controller.enqueue(frame({ delta: '前文已生成', done: false }));
    });
    await waitFor(() => expect(result.current.text).toBe('前文已生成'));
    act(() => {
      calls[0].controller.enqueue(frame({ done: true, error: '模型超时' }));
    });
    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.error).toBe('模型超时');
    expect(result.current.text).toBe('前文已生成');
    expect(useChapterStore.getState().content).toBe('已有正文');
  });

  it('网络层失败：error 状态 + 错误消息', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('Kernel unreachable'));
    vi.stubGlobal('fetch', fetchMock);
    const { result } = renderHook(() => useStream({ projectId: 'p1', chapterId: 'c1' }));
    act(() => {
      result.current.start('continue');
    });
    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.error).toContain('Kernel unreachable');
  });

  it('stop()：状态 stopped + AbortController.abort() 被调用（signal.aborted）', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const { result } = renderHook(() => useStream({ projectId: 'p1', chapterId: 'c1' }));
    act(() => {
      result.current.start('continue');
    });
    await waitFor(() => expect(calls).toHaveLength(1));
    const signal = calls[0].init.signal as AbortSignal | undefined;
    expect(signal?.aborted).toBe(false);

    act(() => {
      result.current.stop();
    });
    expect(result.current.status).toBe('stopped');
    expect(signal?.aborted).toBe(true);
  });

  it('并发保护：生成中再次 start 不发起新流（fetch 仅 1 次）', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const { result } = renderHook(() => useStream({ projectId: 'p1', chapterId: 'c1' }));
    act(() => {
      result.current.start('continue');
    });
    act(() => {
      result.current.start('generate');
    });
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(result.current.status).toBe('generating');
  });

  it('生命周期不入 store：流式期间 store 可序列化且无流对象字段', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const { result } = renderHook(() => useStream({ projectId: 'p1', chapterId: 'c1' }));
    act(() => {
      result.current.start('continue');
    });
    await waitFor(() => expect(calls).toHaveLength(1));
    const state = useChapterStore.getState();
    expect(() => JSON.stringify(state)).not.toThrow();
    expect('abort' in state).toBe(false);
    expect('reader' in state).toBe(false);
    expect('stream' in state).toBe(false);
  });
});
