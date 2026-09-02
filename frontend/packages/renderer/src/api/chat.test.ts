/**
 * SSE 流式聊天客户端契约（#541，GREEN 建 src/api/chat.ts）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 streamChat 必须匹配（行为镜像 src/api/sse.ts streamWriting）：
 * - POST {baseURL}/api/v1/chat/agent/stream + JSON body + X-InkFlow-Token 头（token 空时不带）
 * - 帧 {type, delta, done, error}：#597 起 SSE 帧带 type 字段——
 *   type='delta' 帧 → onDelta(delta)；type='error' 帧 → onError(error) + return；
 *   type='done' 帧 → onDone(frame) + return（后续帧忽略）
 * - 非 ok 响应 / 无 body → onError(`HTTP <status>`)
 * - 流结束无 done 帧 → onError('Stream ended unexpectedly')
 * - abort：返回的 abort 函数 → signal.aborted；catch 内 aborted → 静默 return（不报错）
 * - fetch reject → catch → onError(err.message)
 *
 * #597 agent 端点升级（streamChat 保留函数名，仅升级端点 + 帧协议）：
 * - POST URL 由 /api/v1/chat/stream 改为 /api/v1/chat/agent/stream（deepagents 系统级 Agent 流式端点）
 * - ChatStreamFrame 增 type 字段（'delta'/'tool_call'/'tool_result'/'done'/'error'）+ id/name/args/result
 * - ChatStreamCallbacks 增可选 onToolCall/onToolResult：
 *   type='tool_call' 帧 → onToolCall({id, name, args})；
 *   type='tool_result' 帧 → onToolResult({id, name, result})
 *
 * mock 方式：全局 fetch 返回可控 body reader（手动 push/end/fail 驱动，
 * frontend-testing 约定：手动触发替代 fake timers；参考 src/api/sse.test.ts 模式）
 *
 * #547 消息 CRUD 客户端（「chat 消息 CRUD 客户端」describe 锁定，GREEN 追加实现）：
 * - fetchChatMessages(conversationId, offset?, limit?) → GET /api/v1/chat/messages?conversation_id=&offset=&limit=
 * - saveChatMessage({project_id, conversation_id, role, content, intent?}) → POST /api/v1/chat/messages（body 逐字含 conversation_id；intent 缺省不携带）
 * - fetchChatConversations({includeDeleted?}) → GET /api/v1/chat/conversations（仅 include_deleted query）
 * #744 契约翻转：fetchChatMessages 收 conversationId；saveChatMessage body 含 conversation_id；
 * #S3c 契约对齐：fetchChatConversations 不再发 project_id（后端 GET /chat/conversations 未声明该
 * query，传了被静默忽略 → 项目过滤由调用方本地完成 #825）；新增 createChatConversation(projectId) → POST /api/v1/chat/conversations。
 * 均走 apiFetch（token 头 / 错误映射复用）；新用例用动态 import 引用，避免 RED 期缺导出
 * 把既有 streamChat 用例一起拖挂。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { streamChat, type ChatStreamBody } from './chat';

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

/** 全局 fetch mock：每次调用返回 ok:true + 可控流（参考 sse.test.ts stubStreamFetch） */
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

/** SSE 帧编码（#541 帧格式：data: JSON 行 + \n\n 空行，镜像 F23 §6.3） */
function frame(payload: Record<string, unknown>): Uint8Array {
  return new TextEncoder().encode(`data: ${JSON.stringify(payload)}\n\n`);
}

function makeCallbacks() {
  return {
    onDelta: vi.fn(),
    onDone: vi.fn(),
    onError: vi.fn(),
    // #597：agent 工具流回调（可选——GREEN 实现 type='tool_call'/'tool_result' 帧时分发）
    onToolCall: vi.fn(),
    onToolResult: vi.fn(),
  };
}

/** 等待微任务链跑完（reader 续体全部在 microtask 内） */
const flush = () => new Promise((r) => setTimeout(r, 0));

const body: ChatStreamBody = {
  project_id: 'p1',
  prompt: '帮我写一段打斗场景',
  chapter_id: 'c1',
  chapter_context: '已有正文第一段。',
};

beforeEach(() => {
  vi.unstubAllGlobals();
  window.INKFLOW_API = { baseURL: BASE, token: 'tok-1' };
});

afterEach(() => {
  delete window.INKFLOW_API;
});

describe('streamChat — 请求形态', () => {
  it('POST {baseURL}/api/v1/chat/agent/stream：Content-Type + token 头 + body 序列化，返回 abort 函数', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const cbs = makeCallbacks();

    const abort = await streamChat(body, cbs);
    await flush();

    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(`${BASE}/api/v1/chat/agent/stream`);
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
    await streamChat(body, makeCallbacks());
    await flush();

    const headers = calls[0].init.headers as Record<string, string>;
    expect(headers['X-InkFlow-Token']).toBeUndefined();
    expect(headers['Content-Type']).toBe('application/json');
  });
});

describe('streamChat — 帧状态机', () => {
  it('delta 帧 → onDelta；done 帧 → onDone（携带帧字段），流不再消费', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const cbs = makeCallbacks();

    await streamChat(body, cbs);
    await flush();

    calls[0].api.push(frame({ type: 'delta', delta: '第一段', done: false }));
    await flush();
    expect(cbs.onDelta).toHaveBeenCalledWith('第一段');

    calls[0].api.push(frame({ type: 'done', done: true }));
    await flush();
    expect(cbs.onDone).toHaveBeenCalledTimes(1);
    expect(cbs.onDone.mock.calls[0][0]).toEqual({ type: 'done', done: true });
    expect(cbs.onError).not.toHaveBeenCalled();

    // done 后已 return：后续帧不再处理
    calls[0].api.push(frame({ type: 'delta', delta: '多余', done: false }));
    await flush();
    expect(cbs.onDelta).toHaveBeenCalledTimes(1);
  });

  it('error 帧 → onError + return（后续帧忽略，onDone 不触发）', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const cbs = makeCallbacks();

    await streamChat(body, cbs);
    await flush();

    calls[0].api.push(frame({ type: 'delta', delta: '前文', done: false }));
    await flush();
    calls[0].api.push(frame({ type: 'error', error: '模型超时', done: true }));
    await flush();

    expect(cbs.onError).toHaveBeenCalledWith('模型超时');
    expect(cbs.onDone).not.toHaveBeenCalled();

    calls[0].api.push(frame({ type: 'delta', delta: '忽略我', done: false }));
    await flush();
    expect(cbs.onDelta).toHaveBeenCalledTimes(1);
  });

  it('多帧一包：\\n\\n 切分逐帧处理', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const cbs = makeCallbacks();

    await streamChat(body, cbs);
    await flush();

    const twoFrames = new TextEncoder().encode(
      `data: ${JSON.stringify({ type: 'delta', delta: '甲', done: false })}\n\ndata: ${JSON.stringify({ type: 'delta', delta: '乙', done: false })}\n\n`,
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

    await streamChat(body, cbs);
    await flush();

    // 第一个 chunk 只有半个 data 行（无 \n\n 分隔，且字符串值引号未闭合）
    calls[0].api.push(new TextEncoder().encode('data: {"type":"delta","delta":"第'));
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

    await streamChat(body, cbs);
    await flush();

    calls[0].api.push(frame({ type: 'delta', delta: '部分内容', done: false }));
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

    await streamChat(body, cbs);
    await flush();

    calls[0].api.push(new TextEncoder().encode('data: {not-json}\n\n'));
    await flush();

    expect(cbs.onError).toHaveBeenCalledTimes(1);
    // V8 的 JSON.parse 报错文案（Node 20: "Expected property name or '}' in JSON at position 1"）
    expect(cbs.onError.mock.calls[0][0]).toContain('position');
    expect(cbs.onDone).not.toHaveBeenCalled();
  });
});

/**
 * #597 agent 工具帧：streamChat 升级为 agent 端点后，SSE 帧协议扩展 type 字段——
 * type='tool_call' 帧 → onToolCall({id, name, args})；
 * type='tool_result' 帧 → onToolResult({id, name, result})；
 * 混合序列（tool_call → tool_result → delta → done）依次触发对应回调。
 */
describe('streamChat — agent 工具帧（#597）', () => {
  it('tool_call 帧 → onToolCall({id, name, args})', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const cbs = makeCallbacks();

    await streamChat(body, cbs);
    await flush();

    calls[0].api.push(
      frame({ type: 'tool_call', id: 'call_1', name: 'search_characters', args: { project_id: 'p1' }, done: false }),
    );
    await flush();

    expect(cbs.onToolCall).toHaveBeenCalledWith({
      id: 'call_1',
      name: 'search_characters',
      args: { project_id: 'p1' },
    });
    expect(cbs.onDone).not.toHaveBeenCalled();
    expect(cbs.onError).not.toHaveBeenCalled();
  });

  it('tool_result 帧 → onToolResult({id, name, result})', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const cbs = makeCallbacks();

    await streamChat(body, cbs);
    await flush();

    calls[0].api.push(
      frame({ type: 'tool_result', id: 'call_1', name: 'search_characters', result: '{"ok":true}', done: false }),
    );
    await flush();

    expect(cbs.onToolResult).toHaveBeenCalledWith({
      id: 'call_1',
      name: 'search_characters',
      result: '{"ok":true}',
    });
    expect(cbs.onDelta).not.toHaveBeenCalled();
  });

  it('混合帧序列：tool_call → tool_result → delta → done 依次触发对应回调', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const cbs = makeCallbacks();

    await streamChat(body, cbs);
    await flush();

    calls[0].api.push(
      frame({ type: 'tool_call', id: 'call_1', name: 'search_characters', args: { project_id: 'p1' }, done: false }),
    );
    await flush();
    expect(cbs.onToolCall).toHaveBeenCalledTimes(1);

    calls[0].api.push(
      frame({ type: 'tool_result', id: 'call_1', name: 'search_characters', result: '{"ok":true}', done: false }),
    );
    await flush();
    expect(cbs.onToolResult).toHaveBeenCalledTimes(1);

    calls[0].api.push(frame({ type: 'delta', delta: '最终回复文本', done: false }));
    await flush();
    expect(cbs.onDelta).toHaveBeenCalledWith('最终回复文本');

    calls[0].api.push(frame({ type: 'done', done: true }));
    await flush();
    expect(cbs.onDone).toHaveBeenCalledTimes(1);
    expect(cbs.onDone.mock.calls[0][0]).toEqual({ type: 'done', done: true });
    expect(cbs.onError).not.toHaveBeenCalled();
  });
});

describe('streamChat — HTTP 错误 / 网络错误', () => {
  it('非 ok 响应（500）→ onError("HTTP 500")，不读 body', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      body: { getReader: () => ({ read: vi.fn() }) },
    } as unknown as Response);
    vi.stubGlobal('fetch', fetchMock);
    const cbs = makeCallbacks();

    await streamChat(body, cbs);
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

    await streamChat(body, cbs);
    await flush();

    expect(cbs.onError).toHaveBeenCalledWith('HTTP 200');
  });

  it('fetch reject（网络层失败）→ catch → onError(err.message)', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('Kernel unreachable'));
    vi.stubGlobal('fetch', fetchMock);
    const cbs = makeCallbacks();

    await streamChat(body, cbs);
    await flush();

    expect(cbs.onError).toHaveBeenCalledWith('Kernel unreachable');
  });
});

describe('streamChat — abort', () => {
  it('abort() → signal.aborted=true；catch 内 aborted → 静默 return（不触发 onError）', async () => {
    const calls: FetchCall[] = [];
    stubStreamFetch(calls);
    const cbs = makeCallbacks();

    const abort = await streamChat(body, cbs);
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

/** #547/#744：消息 CRUD 客户端（GREEN 建 fetchChatMessages / saveChatMessage / fetchChatConversations / createChatConversation） */
describe('chat 消息 CRUD 客户端（#547）', () => {
  /** apiFetch 走全局 fetch（res.json 解析）：stub 一个返回固定 JSON 的 fetch */
  function stubJsonFetch(response: unknown, status = 200) {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      json: async () => response,
    } as unknown as Response);
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  }

  it('fetchChatMessages：GET {baseURL}/api/v1/chat/messages?conversation_id=&offset=&limit= + token 头，返回 {items,total,offset,limit}', async () => {
    const { fetchChatMessages } = await import('./chat');
    const payload = {
      items: [
        { id: 'm1', conversation_id: 'conv-1', project_id: 'p1', role: 'user', content: '之前的提问', intent: null, created_at: '2026-08-20T08:00:00Z' },
        { id: 'm2', conversation_id: 'conv-1', project_id: 'p1', role: 'ai', content: '之前的回答', intent: 'conversation', created_at: '2026-08-20T08:01:00Z' },
      ],
      total: 2,
      offset: 0,
      limit: 20,
    };
    const fetchMock = stubJsonFetch(payload);
    const res = await fetchChatMessages('conv-1', 0, 20);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/chat/messages?conversation_id=conv-1&offset=0&limit=20`);
    expect(init?.method).toBe('GET');
    const headers = init?.headers as Headers;
    expect(headers.get('X-InkFlow-Token')).toBe('tok-1');
    expect(res).toEqual(payload);
  });

  it('saveChatMessage：POST {baseURL}/api/v1/chat/messages + body 逐字含 conversation_id（intent 缺省不携带）→ 返回 ChatMessageDto', async () => {
    const { saveChatMessage } = await import('./chat');
    const saved = {
      id: 'm9',
      conversation_id: 'conv-1',
      project_id: 'p1',
      role: 'user',
      content: '帮我写一段打斗场景',
      intent: null,
      created_at: '2026-08-21T10:00:00Z',
    };
    const fetchMock = stubJsonFetch(saved, 201);
    const res = await saveChatMessage({ project_id: 'p1', conversation_id: 'conv-1', role: 'user', content: '帮我写一段打斗场景' });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/chat/messages`);
    expect(init?.method).toBe('POST');
    const headers = init?.headers as Headers;
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(headers.get('X-InkFlow-Token')).toBe('tok-1');
    // body 逐字：intent 缺省时请求体不含 intent 键；conversation_id 必携（#744）
    expect(JSON.parse(String(init?.body))).toEqual({ project_id: 'p1', conversation_id: 'conv-1', role: 'user', content: '帮我写一段打斗场景' });
    expect(res).toEqual(saved);
  });

  it('saveChatMessage 携带 intent：body 含 conversation_id + intent:"content"', async () => {
    const { saveChatMessage } = await import('./chat');
    const fetchMock = stubJsonFetch(
      { id: 'm10', conversation_id: 'conv-1', project_id: 'p1', role: 'ai', content: '正文', intent: 'content', created_at: '2026-08-21T10:01:00Z' },
      201,
    );
    await saveChatMessage({ project_id: 'p1', conversation_id: 'conv-1', role: 'ai', content: '正文', intent: 'content' });
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(String(init?.body))).toEqual({ project_id: 'p1', conversation_id: 'conv-1', role: 'ai', content: '正文', intent: 'content' });
  });

  it('fetchChatConversations：GET {baseURL}/api/v1/chat/conversations（#S3c 翻转：projectId 仅本地过滤，不再发 project_id query——后端未声明该参数）→ {items,total}', async () => {
    const { fetchChatConversations } = await import('./chat');
    const payload = {
      items: [
        { conversation_id: 'conv-1', project_id: 'p1', project_name: '仙侠长篇', last_message: '帮我写一段打斗场景', message_count: 3, is_deleted: false, updated_at: '2026-08-21T10:00:00Z' },
      ],
      total: 1,
    };
    const fetchMock = stubJsonFetch(payload);
    const res = await fetchChatConversations({ projectId: 'p1' });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    // #S3c（原 #744 契约）：后端 GET /chat/conversations 仅声明 include_deleted；
    // 传 projectId 不发 query（过滤由调用方本地完成），避免静默无效参数。
    expect(url).toBe(`${BASE}/api/v1/chat/conversations`);
    expect(init?.method ?? 'GET').toBe('GET');
    expect(res).toEqual(payload);
  });

  it('createChatConversation：POST {baseURL}/api/v1/chat/conversations + body {project_id} → 201 返回含 conversation_id 的 ChatConversationDto', async () => {
    const { createChatConversation } = await import('./chat');
    const created = {
      conversation_id: 'conv-new-1',
      project_id: 'p1',
      project_name: null,
      last_message: '',
      message_count: 0,
      is_deleted: false,
      updated_at: '2026-08-21T10:00:00Z',
    };
    const fetchMock = stubJsonFetch(created, 201);
    const res = await createChatConversation('p1');

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/chat/conversations`);
    expect(init?.method).toBe('POST');
    const headers = init?.headers as Headers;
    expect(headers.get('Content-Type')).toBe('application/json');
    // body 逐字：{project_id}（#744 新线程创建契约）
    expect(JSON.parse(String(init?.body))).toEqual({ project_id: 'p1' });
    expect(res).toEqual(created);
  });

  it('updateChatDeletePermission：PATCH {baseURL}/api/v1/chat/conversations/conv-p1 + body {delete_permission:"ask_once"}', async () => {
    const { updateChatDeletePermission } = await import('./chat');
    const fetchMock = stubJsonFetch(undefined, 204);
    await updateChatDeletePermission('conv-p1', 'ask_once');

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/chat/conversations/conv-p1`);
    expect(init?.method).toBe('PATCH');
    const headers = init?.headers as Headers;
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(JSON.parse(String(init?.body))).toEqual({ delete_permission: 'ask_once' });
  });

  it('resumeChatRun：POST {baseURL}/api/v1/chat/resume + body {conversation_id, approved} → {ok}', async () => {
    const { resumeChatRun } = await import('./chat');
    const fetchMock = stubJsonFetch({ ok: true });
    const res = await resumeChatRun({ conversation_id: 'conv-p1', approved: true });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/chat/resume`);
    expect(init?.method).toBe('POST');
    const headers = init?.headers as Headers;
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(JSON.parse(String(init?.body))).toEqual({ conversation_id: 'conv-p1', approved: true });
    expect(res).toEqual({ ok: true });
  });
});
