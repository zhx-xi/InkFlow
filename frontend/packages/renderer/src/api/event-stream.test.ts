/**
 * 数据面变更订阅客户端契约（F23 spec §15.5.1 / §15.5.4；§15.12.1 M6）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须新建 src/api/event-stream.ts 并匹配：
 *
 * export interface DataChangeFrame {
 *   domain: string; op: string; resource_id: string;
 *   entity_id?: string; project_id?: string | null; source?: string;
 *   traceparent?: string; occurred_at?: string;
 * }
 * export function subscribeDataChanges(
 *   onEvent: (ev: DataChangeFrame) => void,
 *   onError?: (message: string) => void,
 *   onReconnect?: () => void,        // 重连成功（非首次连接）→ 调用方兜底全量 refetch
 * ): Promise<() => void>;
 *
 * 覆盖点（对应 src/api/event-stream.ts）：
 * - 请求形态：GET {baseURL}/api/v1/events/stream + X-InkFlow-Token（不用 EventSource）；返回 abort 函数
 * - 帧切分：`data:` 行 + `\n\n` 空行；分块到达（data 行跨 chunk）缓冲拼接；多帧一包逐帧处理
 * - 与写作帧解码器隔离：写作帧（无 domain/op）不被当事件帧；事件帧无 done 字段不被误判
 * - 非法帧（JSON 解析失败 / 非事件帧）→ 跳过该帧 + 不断开订阅（§15.5.3 E6）
 * - 断连 → 指数退避重连（1s → 2s → 4s → 上限 30s，§15.5.4）
 * - 重连成功 → onReconnect（兜底全量 refetch 信号）；首次连接成功不触发
 * - abort → 静默停止（不报错、不再重连）
 *
 * mock 方式：全局 fetch 返回可控 body reader（手动 push/end/fail 驱动；退避用 fake timers，
 * 参考 src/api/sse.test.ts / src/lib/polling.test.ts 模式）
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { subscribeDataChanges, type DataChangeFrame } from './event-stream';

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
  };
  return { reader, api };
}

interface FetchCall {
  url: string;
  init: RequestInit;
  api: ReturnType<typeof makeReader>['api'];
}

/** 全局 fetch mock：每次调用返回 ok:true + 可控流（同 sse.test.ts stubStreamFetch 模式） */
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

/** SSE 帧编码（§15.5.1：data: <json> + \n\n 空行，同 §6.3 传输形态） */
function frame(payload: Record<string, unknown>): Uint8Array {
  return new TextEncoder().encode(`data: ${JSON.stringify(payload)}\n\n`);
}

/** 完整事件帧（字段齐备形态，§15.5.1） */
const MAP_FRAME = {
  domain: 'map',
  op: 'create',
  resource_id: '7',
  entity_id: '7',
  project_id: '3f2b',
  source: 'cli',
  traceparent: '00-4bf9-a1c2-01',
  occurred_at: '2026-09-10T12:00:01Z',
};

/** 等待微任务链跑完（reader 续体全部在 microtask 内） */
const flush = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => {
  vi.unstubAllGlobals();
  window.INKFLOW_API = { baseURL: BASE, token: 'tok-1' };
});

afterEach(() => {
  delete window.INKFLOW_API;
});

describe('subscribeDataChanges — 请求形态与帧解码', () => {
  it('GET {baseURL}/api/v1/events/stream + token 头，返回 abort 函数', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);

    const abort = await subscribeDataChanges(vi.fn());
    await flush();

    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(`${BASE}/api/v1/events/stream`);
    expect(calls[0].init.method ?? 'GET').toBe('GET');
    const headers = calls[0].init.headers as Record<string, string>;
    expect(headers['X-InkFlow-Token']).toBe('tok-1');
    expect(typeof abort).toBe('function');
    abort();
  });

  it('无 token 时不带 X-InkFlow-Token 头', async () => {
    window.INKFLOW_API = { baseURL: BASE, token: '' };
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);

    const abort = await subscribeDataChanges(vi.fn());
    await flush();

    const headers = calls[0].init.headers as Record<string, string>;
    expect(headers['X-InkFlow-Token']).toBeUndefined();
    abort();
  });

  it('事件帧全字段解析 → onEvent 收到 DataChangeFrame', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const onEvent = vi.fn<(ev: DataChangeFrame) => void>();

    const abort = await subscribeDataChanges(onEvent);
    await flush();
    calls[0].api.push(frame(MAP_FRAME));
    await flush();

    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onEvent).toHaveBeenCalledWith(MAP_FRAME);
    abort();
  });

  it('分块到达：data 行跨 chunk 缓冲拼接后解析', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const onEvent = vi.fn();

    const abort = await subscribeDataChanges(onEvent);
    await flush();

    // 第一个 chunk 只有半个 data 行（无 \n\n 分隔，JSON 未闭合）
    calls[0].api.push(new TextEncoder().encode('data: {"domain":"map","op":"up'));
    await flush();
    expect(onEvent).not.toHaveBeenCalled();

    // 第二个 chunk 补全 + 帧尾
    calls[0].api.push(
      new TextEncoder().encode('date","resource_id":"9","project_id":"p1"}\n\n'),
    );
    await flush();
    expect(onEvent).toHaveBeenCalledWith({
      domain: 'map',
      op: 'update',
      resource_id: '9',
      project_id: 'p1',
    });
    abort();
  });

  it('多帧一包：\\n\\n 切分逐帧处理（长驻流无终止帧）', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const onEvent = vi.fn();

    const abort = await subscribeDataChanges(onEvent);
    await flush();

    const twoFrames = new TextEncoder().encode(
      `data: ${JSON.stringify({ domain: 'map', op: 'create', resource_id: '1' })}\n\n` +
        `data: ${JSON.stringify({ domain: 'agent_template', op: 'update', resource_id: '2', project_id: null })}\n\n`,
    );
    calls[0].api.push(twoFrames);
    await flush();

    expect(onEvent).toHaveBeenCalledTimes(2);
    expect(onEvent).toHaveBeenNthCalledWith(1, {
      domain: 'map',
      op: 'create',
      resource_id: '1',
    });
    // 全局域帧带显式 project_id: null 也应解析（§15.6.3 全局域语义）
    expect(onEvent).toHaveBeenNthCalledWith(2, {
      domain: 'agent_template',
      op: 'update',
      resource_id: '2',
      project_id: null,
    });
    abort();
  });
});

describe('subscribeDataChanges — 与写作帧解码器隔离（D15-5）', () => {
  it('写作帧（delta/done，无 domain/op）不被当事件帧，且不断开订阅', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const onEvent = vi.fn();
    const onError = vi.fn();

    const abort = await subscribeDataChanges(onEvent, onError);
    await flush();

    calls[0].api.push(frame({ delta: '正文片段', done: false }));
    calls[0].api.push(frame({ done: true, format_valid: true, word_count: 12 }));
    await flush();
    expect(onEvent).not.toHaveBeenCalled();

    // 隔离不等于断开：后续真正的事件帧照常送达
    calls[0].api.push(frame({ domain: 'character', op: 'create', resource_id: '5' }));
    await flush();
    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onError).not.toHaveBeenCalled();
    abort();
  });

  it('事件帧无 done 字段 → 正常触发 onEvent（长驻流不结束，不误判）', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const onEvent = vi.fn();

    const abort = await subscribeDataChanges(onEvent);
    await flush();

    calls[0].api.push(frame({ domain: 'settings', op: 'update', resource_id: 'app' }));
    await flush();

    expect(onEvent).toHaveBeenCalledWith({
      domain: 'settings',
      op: 'update',
      resource_id: 'app',
    });
    abort();
  });
});

describe('subscribeDataChanges — 非法帧跳过（§15.5.3 E6）', () => {
  it('JSON 解析失败 → 跳过该帧 + 不断开订阅（后续帧仍送达）', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const onEvent = vi.fn();
    const onError = vi.fn();
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});

    const abort = await subscribeDataChanges(onEvent, onError);
    await flush();

    calls[0].api.push(new TextEncoder().encode('data: {not-json}\n\n'));
    await flush();
    expect(onEvent).not.toHaveBeenCalled();

    calls[0].api.push(frame({ domain: 'map', op: 'delete', resource_id: '3' }));
    await flush();
    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onError).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalled();

    warn.mockRestore();
    abort();
  });

  it('合法 JSON 但非事件帧（缺 domain/op）→ 跳过，不打断订阅', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const onEvent = vi.fn();

    const abort = await subscribeDataChanges(onEvent);
    await flush();

    calls[0].api.push(frame({}));
    calls[0].api.push(frame({ domain: 'map' })); // 缺 op
    await flush();
    expect(onEvent).not.toHaveBeenCalled();
    abort();
  });
});

describe('subscribeDataChanges — 断连重连与指数退避（§15.5.4）', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('连接失败 → 指数退避重连 1s → 2s → 4s', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('kernel unreachable'));
    vi.stubGlobal('fetch', fetchMock);
    const onError = vi.fn();
    const onReconnect = vi.fn();

    const abort = await subscribeDataChanges(vi.fn(), onError, onReconnect);
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(1); // 立即发起首次连接

    await vi.advanceTimersByTimeAsync(999);
    expect(fetchMock).toHaveBeenCalledTimes(1); // 未到 1s
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchMock).toHaveBeenCalledTimes(2); // 1s → 第 2 次
    await vi.advanceTimersByTimeAsync(1999);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchMock).toHaveBeenCalledTimes(3); // 2s → 第 3 次
    await vi.advanceTimersByTimeAsync(4000);
    expect(fetchMock).toHaveBeenCalledTimes(4); // 4s → 第 4 次

    expect(onError).toHaveBeenCalledTimes(4); // 每次失败上报（非致命）
    expect(onReconnect).not.toHaveBeenCalled(); // 始终未连上 → 无「重连成功」
    abort();
  });

  it('退避上限 30s（8s → 16s → 30s，不再翻倍）', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('kernel unreachable'));
    vi.stubGlobal('fetch', fetchMock);

    const abort = await subscribeDataChanges(vi.fn());
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(1000); // 1s → 2 次
    await vi.advanceTimersByTimeAsync(2000); // 2s → 3 次
    await vi.advanceTimersByTimeAsync(4000); // 4s → 4 次
    await vi.advanceTimersByTimeAsync(8000); // 8s → 5 次
    await vi.advanceTimersByTimeAsync(16000); // 16s → 6 次
    expect(fetchMock).toHaveBeenCalledTimes(6);

    await vi.advanceTimersByTimeAsync(29000);
    expect(fetchMock).toHaveBeenCalledTimes(6); // 上限 30s：29s 未到
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetchMock).toHaveBeenCalledTimes(7); // 30s → 第 7 次
    abort();
  });

  it('流异常结束（长驻流不应结束）→ 报错并重连', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const onError = vi.fn();

    const abort = await subscribeDataChanges(vi.fn(), onError);
    await vi.advanceTimersByTimeAsync(0);
    expect(calls).toHaveLength(1);

    calls[0].api.end();
    await vi.advanceTimersByTimeAsync(0);
    expect(onError).toHaveBeenCalledWith('Stream ended unexpectedly');

    await vi.advanceTimersByTimeAsync(1000);
    expect(calls).toHaveLength(2); // 1s 后重连
    abort();
  });

  it('重连成功 → onReconnect（兜底全量 refetch 信号）；重连后事件照常送达', async () => {
    const calls: FetchCall[] = [];
    let attempt = 0;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      attempt += 1;
      if (attempt === 1) return Promise.reject(new Error('kernel unreachable'));
      const { reader, api } = makeReader();
      calls.push({ url, init: init ?? {}, api });
      return Promise.resolve({
        ok: true,
        status: 200,
        body: { getReader: () => reader },
      } as unknown as Response);
    });
    vi.stubGlobal('fetch', fetchMock);
    const onEvent = vi.fn();
    const onReconnect = vi.fn();

    const abort = await subscribeDataChanges(onEvent, vi.fn(), onReconnect);
    await vi.advanceTimersByTimeAsync(0);
    expect(onReconnect).not.toHaveBeenCalled(); // 首次连接失败不算重连

    await vi.advanceTimersByTimeAsync(1000);
    expect(calls).toHaveLength(1);
    expect(onReconnect).toHaveBeenCalledTimes(1); // 重连成功 → 触发兜底全量 refetch

    calls[0].api.push(frame({ domain: 'map', op: 'create', resource_id: '11' }));
    await vi.advanceTimersByTimeAsync(0);
    expect(onEvent).toHaveBeenCalledWith({
      domain: 'map',
      op: 'create',
      resource_id: '11',
    });
    abort();
  });

  it('首次连接成功 → 不触发 onReconnect（未错过事件）', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const onReconnect = vi.fn();

    const abort = await subscribeDataChanges(vi.fn(), vi.fn(), onReconnect);
    await vi.advanceTimersByTimeAsync(0);

    expect(calls).toHaveLength(1);
    expect(onReconnect).not.toHaveBeenCalled();
    abort();
  });

  it('abort 后不再重连（fetch 不再增加）', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('kernel unreachable'));
    vi.stubGlobal('fetch', fetchMock);

    const abort = await subscribeDataChanges(vi.fn());
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    abort();
    await vi.advanceTimersByTimeAsync(60000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe('subscribeDataChanges — abort', () => {
  it('abort() → 静默停止（不触发 onError，不再重连）', async () => {
    const calls: FetchCall[] = [];
    const fetchMock = stubStreamFetch(calls);
    const onError = vi.fn();

    const abort = await subscribeDataChanges(vi.fn(), onError);
    await flush();

    abort();
    // reader 以 AbortError 拒绝 → 静默 return（主动停止不算错误）
    calls[0].api.fail(new DOMException('The operation was aborted.', 'AbortError'));
    await flush();

    expect(onError).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
