/**
 * preload（#78 Electron 壳）：contextBridge 注入 window.INKFLOW_API = {baseURL, token}。
 * 契约来源：specs/f19-gui/spec.md §3.3（sandbox 下 contextBridge/ipcRenderer 可用）/ §3.4（Q1 拍板 B）。
 *
 * 可靠性说明（Electron 34 实测）：contextBridge 暴露对象是「值拷贝」——暴露后修改原对象不会
 * 同步到 renderer，getter 也在 expose 时求值一次后拷贝、不实时更新；且对同一 key 重复
 * exposeInMainWorld 会抛 "Cannot bind an API on top of an existing context bridge API"。
 * 因此**仅就绪后暴露一次**：main 在 INKFLOW_READY 后发送 'inkflow:ready'，此处收到真实
 * {baseURL, token} 时再注入（就绪前 window.INKFLOW_API 为 undefined，renderer 回退 Vite env、
 * 显示「正在启动内核…」，spec §3.2/§3.4 契约）；exposed 标志保证 main 的 did-finish-load
 * 兜底重发（同一 payload）不会触发第二次 expose。
 * renderer 读取：window.INKFLOW_API?.baseURL ?? import.meta.env.VITE_API_BASE（§4.4 消费契约）。
 *
 * #98 修复（Electron 生产 401 时序竞态，2026-08-05）：
 * - exposeInMainWorld 成功后（exposed 标志内置）追加 dispatch 'inkflow:api-ready'，
 *   renderer 侧 ensureApiReady 等待该事件后才发起首请求，消除
 *   「React 挂载早于 preload 注入 → 首请求无 token → 401」竞态。
 * - 幂等保持：重复 'inkflow:ready' 在 exposed 守卫处提前返回，不重复 expose / dispatch。
 * - 安全写法：preload 运行于 renderer sandbox（有 DOM window）；vitest node 环境由测试
 *   mock globalThis.window；node 类型限制下用 globalThis + 最小类型声明兜底。
 */
import { contextBridge, ipcRenderer } from 'electron';

// node 类型环境（无 DOM lib）下的最小 Event 构造类型声明；运行时由 sandbox DOM / Node 全局 Event 提供。
declare const Event: {
  new (type: string): unknown;
};

/** 注入完成后通知 renderer（dispatch 'inkflow:api-ready'），window 不存在时安全忽略。 */
function dispatchApiReady(): void {
  const holder = globalThis as typeof globalThis & {
    window?: { dispatchEvent: (event: unknown) => void };
  };
  holder.window?.dispatchEvent(new Event('inkflow:api-ready'));
}

// 幂等标志：'inkflow:ready' 可能被 main 发送两次（INKFLOW_READY 首达 + did-finish-load 兜底重发），
// 重复 exposeInMainWorld 同 key 会抛 "Cannot bind an API on top of an existing context bridge API"。
let exposed = false;

ipcRenderer.on(
  'inkflow:ready',
  (_event, payload: { baseURL: string; token: string }) => {
    if (exposed) {
      return;
    }
    exposed = true;
    contextBridge.exposeInMainWorld(
      'INKFLOW_API',
      Object.freeze({
        baseURL: payload.baseURL,
        token: payload.token,
        // #106 用户拍板：自绘窗口控制按钮（官方 titleBarOverlay 颜色联动不可靠）
        windowControls: Object.freeze({
          minimize: () => ipcRenderer.send('window:minimize'),
          toggleMaximize: () => ipcRenderer.send('window:toggle-maximize'),
          close: () => ipcRenderer.send('window:close'),
        }),
      })
    );
    dispatchApiReady();
  }
);
