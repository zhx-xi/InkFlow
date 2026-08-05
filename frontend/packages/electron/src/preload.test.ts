/**
 * preload 就绪事件契约（#98 修复：Electron 生产 401 时序竞态，2026-08-05）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 preload.ts 必须匹配：
 *
 * 背景：Electron 生产模式下 React 挂载早于内核就绪 → window.INKFLOW_API 未注入时
 * 首请求无 token → 401「Unauthorized」且不自动重试（用户实测）。
 *
 * 契约（新增行为，既有 expose 幂等保持）：
 * - 收到 'inkflow:ready' payload（{baseURL, token}）后：
 *   1. contextBridge.exposeInMainWorld('INKFLOW_API', {baseURL, token})（既有）
 *   2. **新增**：window.dispatchEvent(new Event('inkflow:api-ready'))——renderer
 *      侧通过该事件知道 API 配置已注入，再发起首请求（client.ts ensureApiReady 消费）
 * - 幂等：重复 'inkflow:ready'（main 兜底重发）不重复 expose、不重复 dispatchEvent
 * - 就绪前：不 dispatch 任何事件（window.INKFLOW_API 保持 undefined）
 *
 * 环境假设：preload 运行在 renderer 的 sandbox 上下文（有 window/DOM）；
 * vitest node 环境无 window —— 测试 mock globalThis.window = { dispatchEvent }。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const contextBridge = { exposeInMainWorld: vi.fn() };
const ipcRenderer = { on: vi.fn() };

vi.mock('electron', () => ({
  contextBridge,
  ipcRenderer,
}));

// 测试用 window mock（preload 的 dispatchEvent 目标）
const dispatchMock = vi.fn();
const windowMock = { dispatchEvent: dispatchMock };

beforeEach(() => {
  vi.clearAllMocks();
  globalThis.window = windowMock as unknown as Window & typeof globalThis;
});

describe('preload — inkflow:api-ready 就绪事件（#98 修复）', () => {
  it('收到 inkflow:ready → exposeInMainWorld + dispatchEvent(inkflow:api-ready)', () => {
    // 重新 import 触发 ipcRenderer.on 注册
    vi.resetModules();
    vi.doMock('electron', () => ({ contextBridge, ipcRenderer }));
    import('./preload').then(() => {
      const handler = ipcRenderer.on.mock.calls.find((c) => c[0] === 'inkflow:ready')?.[1];
      expect(handler).toBeTypeOf('function');
      handler(null, { baseURL: 'http://127.0.0.1:54321', token: 'tok-abc' });

      expect(contextBridge.exposeInMainWorld).toHaveBeenCalledWith('INKFLOW_API', {
        baseURL: 'http://127.0.0.1:54321',
        token: 'tok-abc',
      });
      expect(dispatchMock).toHaveBeenCalledTimes(1);
      expect(dispatchMock.mock.calls[0][0].type).toBe('inkflow:api-ready');
    });
  });

  it('幂等：重复 inkflow:ready 不重复 expose、不重复 dispatchEvent', async () => {
    vi.resetModules();
    vi.doMock('electron', () => ({ contextBridge, ipcRenderer }));
    await import('./preload');
    const handler = ipcRenderer.on.mock.calls.find((c) => c[0] === 'inkflow:ready')?.[1] as (
      e: unknown,
      p: { baseURL: string; token: string }
    ) => void;

    handler(null, { baseURL: 'http://127.0.0.1:54321', token: 'tok-abc' });
    handler(null, { baseURL: 'http://127.0.0.1:54321', token: 'tok-abc' });

    expect(contextBridge.exposeInMainWorld).toHaveBeenCalledTimes(1);
    expect(dispatchMock).toHaveBeenCalledTimes(1);
  });

  it('就绪前不 dispatch 事件（仅注册监听，无副作用）', async () => {
    vi.resetModules();
    vi.doMock('electron', () => ({ contextBridge, ipcRenderer }));
    await import('./preload');
    expect(dispatchMock).not.toHaveBeenCalled();
    expect(contextBridge.exposeInMainWorld).not.toHaveBeenCalled();
  });
});
