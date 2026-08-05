/**
 * SSE streamWriting 薄弱分支补测（Issue #104 覆盖率：分支 68.18% → 目标 ≥90%）
 *
 * 覆盖点（对应 src/api/sse.ts）：
 * - delta 帧 → onDelta；done 帧 → onDone；error 帧 → onError + return（后续帧忽略）
 * - 非 ok 响应 / 无 body → onError(`HTTP <status>`)
 * - 流结束无 done 帧 → onError('Stream ended unexpectedly')
 * - 分块到达（data 行跨 chunk）、多帧一包（\n\n 切分）
 * - abort：返回的 abort 函数 → signal.aborted；catch 内 aborted → 静默 return（不报错）
 * - JSON.parse 异常帧 → catch → onError
 * - 请求形态：POST {baseURL}/api/v1/writing/stream + Content-Type + token 头 + body 序列化
 *
 * mock 方式：全局 fetch 返回可控 body reader（手动 push/end/fail 驱动，frontend-testing 约定：
 * 手动触发替代 fake timers；参考 src/hooks/useStream.test.ts 模式）
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { streamWriting, type StreamRequestBody } from './sse';

const BASE = 'http://api.test';

interface ReadResult {
  done: boolean;
  value?: Uint8Array;
}

interface PendingRead {
  resolve: (r: ReadResult) => void;
  reject: (e: unknown) => void;
}

/** 手动驱动的 reader：每次 read() 挂起一个 promise，由测试 push/end/fail 释放 */
function makeReader() {
  const pending: PendingRead[] = [];
  const reader = {
    read: () =>
      new Promise<ReadResult>((resolve, reject) => {
        pending.push({ resolve, reject });
      }),
  };
  const api = {
    push(chunk: Uint8Array) {
      pending.shift()?.resolve({ done: false, value: chunk });
    },
    end() {
      pending.shift()?.resolve({ done: true });
    },
    fail(err: unknown) {
      pending.shift()?.reject(err);
    },
    pendingCount: () => pending.length,
  };
  return { reader, api };
}

interface FetchCall {
  url: string;
  init: RequestInit;
  api: ReturnType<typeof makeReader>['api'];
}

/** 全局 fetch mock：每次调用返回 ok:true + 可控流（参考 useStream.test.ts stubStreamFetch） */
function stubStreamFetch(calls: FetchCall[]) {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    const { reader, api } = makeReader();
    calls.push({ url, init: init ?? {}, api });
    return Promise.resolve({
      ok: true,
      status: 200,
      body: { getReader: () => reader },
    } as unknown as Response);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

/** SSE 帧编码（F23 §6.3: data: JSON 行 + \n\n 空行） */
function frame(payload: Record<string, unknown>): Uint8Array {
  return new TextEncoder().encode(`data: ${JSON.stringify(payload)}\n\n`);
}

function makeCallbacks() {
  return { onDelta: vi.fn(), onDone: vi.fn(), onError: vi.fn() };
}

/** 等待微任务链跑完（reader 续体全部在 microtask 内） */
const flush = () => new Promise((r) => setTimeout(r, 0));

const body: StreamRequestBody = {
  mode: 'generate',
  project_id: 'p1',
  chapter_id: 'c1',
  outline: '第一卷大纲',
};

beforeEach(() => {
  vi.unstubAllGlobals();
  window.INKFLOW_API = { baseURL: BASE, token: 'tok-1' };
});

afterEach(() => {
  delete window.INKFLOW_API;
});

describe('streamWriting — 请求形态', () => {
  it('POST {baseURL}/api/v1/writing/stream：Content-Type + token 头 + body 序列化，返回 abort 函数', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const cbs = makeCallbacks();

    const abort = await streamWriting(body, cbs);
    await flush();

    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(`${BASE}/api/v1/writing/stream`);
    expect(calls[0].init.method).toBe('POST');
    const headers = calls[0].init.headers as Record<string, string>;
    expect(headers['Content-Type']).toBe('application/json');
    expect(headers['X-InkFlow-Token']).toBe('tok-1');
    expect(JSON.parse(String(calls[0].init.body))).toEqual(body);
    expect(typeof abort).toBe('function');
  });

  it('无 token 时不带 X-InkFlow-Token 头', async () => {
    window.INKFLOW_API = { baseURL: BASE, token: '' };
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    await streamWriting(body, makeCallbacks());
    await flush();

    const headers = calls[0].init.headers as Record<string, string>;
    expect(headers['X-InkFlow-Token']).toBeUndefined();
    expect(headers['Content-Type']).toBe('application/json');
  });
});

describe('streamWriting — 帧状态机', () => {
  it('delta 帧 → onDelta；done 帧 → onDone（携带摘要字段），流不再消费', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const cbs = makeCallbacks();

    await streamWriting(body, cbs);
    await flush();

    calls[0].api.push(frame({ delta: '第一段', done: false }));
    await flush();
    expect(cbs.onDelta).toHaveBeenCalledWith('第一段');

    calls[0].api.push(
      frame({ done: true, format_valid: true, word_count: 1234, model: 'gpt-4o', warnings: [] }),
    );
    await flush();
    expect(cbs.onDone).toHaveBeenCalledTimes(1);
    expect(cbs.onDone.mock.calls[0][0]).toEqual({
      done: true,
      format_valid: true,
      word_count: 1234,
      model: 'gpt-4o',
      warnings: [],
    });
    expect(cbs.onError).not.toHaveBeenCalled();

    // done 后已 return：后续帧不再处理
    calls[0].api.push(frame({ delta: '多余', done: false }));
    await flush();
    expect(cbs.onDelta).toHaveBeenCalledTimes(1);
  });

  it('error 帧 → onError + return（后续帧忽略，onDone 不触发）', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const cbs = makeCallbacks();

    await streamWriting(body, cbs);
    await flush();

    calls[0].api.push(frame({ delta: '前文', done: false }));
    await flush();
    calls[0].api.push(frame({ done: true, error: '模型超时' }));
    await flush();

    expect(cbs.onError).toHaveBeenCalledWith('模型超时');
    expect(cbs.onDone).not.toHaveBeenCalled();

    calls[0].api.push(frame({ delta: '忽略我', done: false }));
    await flush();
    expect(cbs.onDelta).toHaveBeenCalledTimes(1);
  });

  it('多帧一包：\\n\\n 切分逐帧处理', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const cbs = makeCallbacks();

    await streamWriting(body, cbs);
    await flush();

    const twoFrames = new TextEncoder().encode(
      `data: ${JSON.stringify({ delta: '甲', done: false })}\n\ndata: ${JSON.stringify({ delta: '乙', done: false })}\n\n`,
    );
    calls[0].api.push(twoFrames);
    await flush();

    expect(cbs.onDelta).toHaveBeenCalledTimes(2);
    expect(cbs.onDelta).toHaveBeenNthCalledWith(1, '甲');
    expect(cbs.onDelta).toHaveBeenNthCalledWith(2, '乙');
  });

  it('分块到达：data 行跨 chunk 缓冲拼接后解析', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const cbs = makeCallbacks();

    await streamWriting(body, cbs);
    await flush();

    // 第一个 chunk 只有半个 data 行（无 \n\n 分隔，且字符串值引号未闭合）
    calls[0].api.push(new TextEncoder().encode('data: {"delta":"第'));
    await flush();
    expect(cbs.onDelta).not.toHaveBeenCalled();

    // 第二个 chunk 补全引号 + 帧尾（JSON 属性名必须带引号）
    calls[0].api.push(new TextEncoder().encode('一", "done": false}\n\n'));
    await flush();
    expect(cbs.onDelta).toHaveBeenCalledWith('第一');
    expect(cbs.onError).not.toHaveBeenCalled();
  });

  it('流结束但无 done 帧 → onError("Stream ended unexpectedly")', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const cbs = makeCallbacks();

    await streamWriting(body, cbs);
    await flush();

    calls[0].api.push(frame({ delta: '部分内容', done: false }));
    await flush();
    calls[0].api.end();
    await flush();

    expect(cbs.onError).toHaveBeenCalledWith('Stream ended unexpectedly');
    expect(cbs.onDone).not.toHaveBeenCalled();
  });

  it('JSON.parse 异常帧 → catch → onError（非 abort 原因）', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const cbs = makeCallbacks();

    await streamWriting(body, cbs);
    await flush();

    calls[0].api.push(new TextEncoder().encode('data: {not-json}\n\n'));
    await flush();

    expect(cbs.onError).toHaveBeenCalledTimes(1);
    // V8 的 JSON.parse 报错文案（Node 20: "Expected property name or '}' in JSON at position 1"）
    expect(cbs.onError.mock.calls[0][0]).toContain('position');
    expect(cbs.onDone).not.toHaveBeenCalled();
  });
});

describe('streamWriting — HTTP 错误 / 网络错误', () => {
  it('非 ok 响应（500）→ onError("HTTP 500")，不读 body', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      body: { getReader: () => ({ read: vi.fn() }) },
    } as unknown as Response);
    vi.stubGlobal('fetch', fetchMock);
    const cbs = makeCallbacks();

    await streamWriting(body, cbs);
    await flush();

    expect(cbs.onError).toHaveBeenCalledWith('HTTP 500');
    expect(cbs.onDone).not.toHaveBeenCalled();
  });

  it('ok 但无 body → onError("HTTP 200")', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: null,
    } as unknown as Response);
    vi.stubGlobal('fetch', fetchMock);
    const cbs = makeCallbacks();

    await streamWriting(body, cbs);
    await flush();

    expect(cbs.onError).toHaveBeenCalledWith('HTTP 200');
  });

  it('fetch reject（网络层失败）→ catch → onError(err.message)', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('Kernel unreachable'));
    vi.stubGlobal('fetch', fetchMock);
    const cbs = makeCallbacks();

    await streamWriting(body, cbs);
    await flush();

    expect(cbs.onError).toHaveBeenCalledWith('Kernel unreachable');
  });
});

describe('streamWriting — abort', () => {
  it('abort() → signal.aborted=true；catch 内 aborted → 静默 return（不触发 onError）', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const cbs = makeCallbacks();

    const abort = await streamWriting(body, cbs);
    await flush();

    const signal = calls[0].init.signal as AbortSignal | undefined;
    expect(signal?.aborted).toBe(false);

    abort();
    expect(signal?.aborted).toBe(true);

    // reader.read() 以 AbortError 拒绝 → catch 分支：signal.aborted → 静默
    calls[0].api.fail(new DOMException('The operation was aborted.', 'AbortError'));
    await flush();

    expect(cbs.onError).not.toHaveBeenCalled();
    expect(cbs.onDone).not.toHaveBeenCalled();
  });
});
