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
 */
import { contextBridge, ipcRenderer } from 'electron';

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
      Object.freeze({ baseURL: payload.baseURL, token: payload.token })
    );
  }
);
