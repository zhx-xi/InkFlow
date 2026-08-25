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
 * file 命名空间契约（F21 导出服务 GUI 消费；GREEN 实现补暴露，既有命名空间不动）：
 * - file.getDefaultLocation() → ipcRenderer.invoke('file:get-default-location')
 * - file.chooseDirectory() → ipcRenderer.invoke('dialog:choose-directory')
 * - file.saveExport(opts) → ipcRenderer.invoke('file:save-export', opts)
 *
 * 环境假设：preload 运行在 renderer 的 sandbox 上下文（有 window/DOM）；
 * vitest node 环境无 window —— 测试 mock globalThis.window = { dispatchEvent }。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const contextBridge = { exposeInMainWorld: vi.fn() };
const ipcRenderer = { on: vi.fn(), invoke: vi.fn() };

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
  it('收到 inkflow:ready → exposeInMainWorld + dispatchEvent(inkflow:api-ready)', async () => {
    // 重新 import 触发 ipcRenderer.on 注册
    vi.resetModules();
    vi.doMock('electron', () => ({ contextBridge, ipcRenderer }));
    await import('./preload');
    const handler = ipcRenderer.on.mock.calls.find((c) => c[0] === 'inkflow:ready')?.[1];
    expect(handler).toBeTypeOf('function');
    handler(null, { baseURL: 'http://127.0.0.1:54321', token: 'tok-abc' });

    expect(contextBridge.exposeInMainWorld).toHaveBeenCalledWith('INKFLOW_API', {
      baseURL: 'http://127.0.0.1:54321',
      token: 'tok-abc',
      // #106 用户拍板：自绘窗口控制按钮（官方 titleBarOverlay 颜色联动不可靠）
      windowControls: {
        minimize: expect.any(Function),
        toggleMaximize: expect.any(Function),
        close: expect.any(Function),
        onMaximizedChange: expect.any(Function), // #106：最大化状态订阅（图标切换）
      },
      // #167 F31：关闭行为设置 IPC 通道（托盘常驻，spec f31 §2.3）
      settings: {
        getCloseBehavior: expect.any(Function),
        setCloseBehavior: expect.any(Function),
        dismissTrayHint: expect.any(Function),
      },
      // F21 导出服务：导出保存/目录选择 file 命名空间（GREEN 实现补暴露）
      file: {
        getDefaultLocation: expect.any(Function),
        chooseDirectory: expect.any(Function),
        saveExport: expect.any(Function),
      },
    });
    expect(dispatchMock).toHaveBeenCalledTimes(1);
    expect(dispatchMock.mock.calls[0][0].type).toBe('inkflow:api-ready');
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

describe('preload — file 命名空间（F21 导出服务 GUI 消费：目录选择/导出保存 IPC 转发）', () => {
  const payload = { baseURL: 'http://127.0.0.1:54321', token: 'tok-abc' };

  // 触发 'inkflow:ready' → 捕获 exposeInMainWorld 暴露对象（与既有 #98 用例同套路）
  async function captureExposedApi(): Promise<{ file?: Record<string, unknown> }> {
    vi.resetModules();
    vi.doMock('electron', () => ({ contextBridge, ipcRenderer }));
    await import('./preload');
    const handler = ipcRenderer.on.mock.calls.find((c) => c[0] === 'inkflow:ready')?.[1] as (
      e: unknown,
      p: { baseURL: string; token: string }
    ) => void;
    handler(null, payload);
    return contextBridge.exposeInMainWorld.mock.calls.find((c) => c[0] === 'INKFLOW_API')?.[1] as {
      file?: Record<string, unknown>;
    };
  }

  it('暴露 file 命名空间：getDefaultLocation / chooseDirectory / saveExport 均为函数', async () => {
    const exposed = await captureExposedApi();

    // RED：GREEN 实现前 file 未暴露 → 此处断言失败（有效 RED）
    expect(exposed.file).toBeDefined();
    expect(exposed.file?.getDefaultLocation).toBeTypeOf('function');
    expect(exposed.file?.chooseDirectory).toBeTypeOf('function');
    expect(exposed.file?.saveExport).toBeTypeOf('function');
  });

  it('file.getDefaultLocation() → ipcRenderer.invoke("file:get-default-location")', async () => {
    const exposed = await captureExposedApi();

    // RED 守卫：file 未暴露时断言失败；GREEN 后走通转发断言
    expect(exposed.file).toBeDefined();
    (exposed.file?.getDefaultLocation as () => Promise<string>)();

    expect(ipcRenderer.invoke).toHaveBeenCalledWith('file:get-default-location');
  });

  it('file.chooseDirectory() → ipcRenderer.invoke("dialog:choose-directory")', async () => {
    const exposed = await captureExposedApi();

    // RED 守卫：file 未暴露时断言失败；GREEN 后走通转发断言
    expect(exposed.file).toBeDefined();
    (exposed.file?.chooseDirectory as () => Promise<string | null>)();

    expect(ipcRenderer.invoke).toHaveBeenCalledWith('dialog:choose-directory');
  });

  it('file.saveExport(opts) → ipcRenderer.invoke("file:save-export", opts)', async () => {
    const exposed = await captureExposedApi();
    const opts = { directory: 'D:\\inkflow-export', filename: '第一章.md', content: '# 第一章 序章' };

    // RED 守卫：file 未暴露时断言失败；GREEN 后走通转发断言
    expect(exposed.file).toBeDefined();
    (exposed.file?.saveExport as (o: typeof opts) => Promise<{ path: string }>)(opts);

    expect(ipcRenderer.invoke).toHaveBeenCalledWith('file:save-export', opts);
  });
});
