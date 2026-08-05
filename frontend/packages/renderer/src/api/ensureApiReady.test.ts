/**
 * ensureApiReady 契约（#98 修复：Electron 生产 401 时序竞态，2026-08-05）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 client.ts 新增导出必须匹配：
 *
 * 背景：Electron 生产模式下 React 挂载（projects.tsx loadProjects）早于
 * preload 注入 window.INKFLOW_API → 首请求无 token → 401（用户实测）。
 * 修复：渲染层在 Electron 环境下等待 'inkflow:api-ready' 事件（preload 注入后 dispatch）
 * 再发起首请求；非 Electron（浏览器 dev）不等待（无注入源，错误态由页面处理）。
 *
 * 契约（新增导出，不改既有 getApiConfig 签名）：
 * - isElectronEnv(): boolean —— navigator.userAgent 含 'Electron'（大小写不敏感）
 * - ensureApiReady(timeoutMs = 15000): Promise<void>
 *   - window.INKFLOW_API 已就绪 → 立即 resolve
 *   - 非 Electron 环境 → 立即 resolve（浏览器模式无注入源）
 *   - Electron + 未就绪 → 监听 'inkflow:api-ready'（window.addEventListener）→ resolve；
 *     timeoutMs 后兜底 resolve（不挂起；若事件在超时后到达，不应抛错）
 *   - 幂等：已就绪后再次调用立即 resolve；多次调用各自监听（互不干扰）
 *
 * 消费方：pages/projects.tsx useEffect 在 loadProjects 前 await ensureApiReady()。
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { isElectronEnv, ensureApiReady } from './client';

const originalUA = navigator.userAgent;

function setUA(ua: string): void {
  Object.defineProperty(navigator, 'userAgent', {
    configurable: true,
    get: () => ua,
  });
}

function setInjected(api: unknown): void {
  Object.defineProperty(window, 'INKFLOW_API', {
    configurable: true,
    value: api,
  });
}

beforeEach(() => {
  // 清掉可能残留的 INKFLOW_API
  Object.defineProperty(window, 'INKFLOW_API', {
    configurable: true,
    value: undefined,
  });
});

afterEach(() => {
  setUA(originalUA);
});

describe('isElectronEnv', () => {
  it('Electron UA → true（Electron/34.5.8 含大小写变体）', () => {
    setUA('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) InkFlow/0.3.0 Chrome/130.0.0.0 Electron/34.5.8 Safari/537.36');
    expect(isElectronEnv()).toBe(true);
    setUA('...electron/34...');
    expect(isElectronEnv()).toBe(true);
  });

  it('非 Electron UA → false', () => {
    setUA('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36');
    expect(isElectronEnv()).toBe(false);
  });
});

describe('ensureApiReady', () => {
  it('INKFLOW_API 已就绪 → 立即 resolve', async () => {
    setInjected({ baseURL: 'http://127.0.0.1:54321', token: 'tok' });
    await expect(ensureApiReady(5000)).resolves.toBeUndefined();
  });

  it('非 Electron 环境 → 立即 resolve（浏览器 dev 不等待）', async () => {
    setUA('Mozilla/5.0 Chrome/130.0.0.0');
    await expect(ensureApiReady(5000)).resolves.toBeUndefined();
  });

  it('Electron + 未就绪 → 等待 inkflow:api-ready 事件后 resolve', async () => {
    setUA('Mozilla/5.0 ... Electron/34.5.8 ...');
    const p = ensureApiReady(5000);
    let resolved = false;
    void p.then(() => {
      resolved = true;
    });
    await new Promise((r) => setTimeout(r, 20));
    expect(resolved).toBe(false);
    window.dispatchEvent(new Event('inkflow:api-ready'));
    await p;
    expect(resolved).toBe(true);
  });

  it('Electron + 未就绪 + 超时 → 兜底 resolve（不挂起）', async () => {
    setUA('Mozilla/5.0 ... Electron/34.5.8 ...');
    await expect(ensureApiReady(50)).resolves.toBeUndefined();
  });

  it('幂等：已就绪后再次调用立即 resolve', async () => {
    setInjected({ baseURL: 'http://127.0.0.1:54321', token: 'tok' });
    await ensureApiReady(1000);
    await expect(ensureApiReady(1000)).resolves.toBeUndefined();
  });
});
