/**
 * useKernelStore 状态机契约（Issue #384 层 1，2026-08-16）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 `src/stores/kernel.ts` 必须匹配：
 *
 * 状态机（三态 status + booted 门控开关，plan D1）：
 * - 初始态：status='booting' + booted=false
 * - checkHealth() 成功 → status='ready' + booted=true
 * - checkHealth() 失败：
 *   - booted=false（启动期）→ status='failed'，booted 保持 false
 *   - booted=true（运行期）→ status='failed'，booted 保持 true（门控不回退）
 * - retry()：置 status='booting'，再 checkHealth()
 * - startPolling()：立即 checkHealth 一次 + setInterval 轮询；幂等（重复调用不叠加 timer）
 * - stopPolling()：清 timer（可安全重复调用）
 *
 * 导出面（GREEN 必实现）：
 * - export type KernelStatus = 'booting' | 'ready' | 'failed'
 * - export const useKernelStore = create<KernelState>(...)（zustand）
 * - KernelState 字段：status / booted / checkHealth / startPolling / stopPolling / retry
 * - checkHealth 内部调 apiFetch('/health')（成功不抛 = ready；抛错 = failed）
 *
 * 设计假设：轮询生命周期归 store 管（AppLayout 挂载 startPolling / 卸载 stopPolling）；
 * 模块级 timer 句柄（同 toast.ts timers Map 模式），跨测试需 stopPolling 清理。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { waitFor } from '@testing-library/react';
import { apiFetch } from '../api/client';
import { useKernelStore } from './kernel';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

beforeEach(() => {
  apiFetchMock.mockReset();
  useKernelStore.setState({ status: 'booting', booted: false });
});

afterEach(() => {
  // 清理残留轮询 timer，避免跨测试泄漏
  useKernelStore.getState().stopPolling();
});

describe('useKernelStore — 内核状态单一真相源（#384）', () => {
  it('初始态：status=booting + booted=false', () => {
    expect(useKernelStore.getState().status).toBe('booting');
    expect(useKernelStore.getState().booted).toBe(false);
  });

  it('checkHealth 成功 → status=ready + booted=true（调 /health）', async () => {
    apiFetchMock.mockResolvedValue({ ok: true });
    await useKernelStore.getState().checkHealth();
    expect(apiFetchMock).toHaveBeenCalledWith('/health');
    expect(useKernelStore.getState().status).toBe('ready');
    expect(useKernelStore.getState().booted).toBe(true);
  });

  it('checkHealth 失败（启动期 booted=false）→ status=failed + booted 保持 false', async () => {
    apiFetchMock.mockRejectedValue(new Error('kernel unreachable'));
    await useKernelStore.getState().checkHealth();
    expect(useKernelStore.getState().status).toBe('failed');
    expect(useKernelStore.getState().booted).toBe(false);
  });

  it('checkHealth 失败（运行期 booted=true）→ status=failed + booted 保持 true（门控不回退）', async () => {
    useKernelStore.setState({ status: 'ready', booted: true });
    apiFetchMock.mockRejectedValue(new Error('kernel unreachable'));
    await useKernelStore.getState().checkHealth();
    expect(useKernelStore.getState().status).toBe('failed');
    expect(useKernelStore.getState().booted).toBe(true);
  });

  it('retry：failed → booting（同步置位）→ checkHealth 成功 → ready+booted=true', async () => {
    useKernelStore.setState({ status: 'failed', booted: false });
    apiFetchMock.mockResolvedValue({ ok: true });
    useKernelStore.getState().retry();
    expect(useKernelStore.getState().status).toBe('booting');
    await waitFor(() => expect(useKernelStore.getState().status).toBe('ready'));
    expect(useKernelStore.getState().booted).toBe(true);
  });

  it('startPolling：立即探测 /health 一次 + 幂等（重复调用不叠加）', async () => {
    apiFetchMock.mockResolvedValue({ ok: true });
    useKernelStore.getState().startPolling();
    useKernelStore.getState().startPolling();
    await waitFor(() => expect(useKernelStore.getState().status).toBe('ready'));
    // 仅立即探测一次（5s setInterval 未到；幂等第二次 startPolling 不重复发起）
    expect(apiFetchMock).toHaveBeenCalledTimes(1);
  });

  it('stopPolling：清理 timer（可安全重复调用）', () => {
    apiFetchMock.mockResolvedValue({ ok: true });
    useKernelStore.getState().startPolling();
    useKernelStore.getState().stopPolling();
    useKernelStore.getState().stopPolling();
    // 不抛错即通过（timer 清理幂等）；状态仍保持 booting（stop 不改变状态）
    expect(useKernelStore.getState().status).toBe('booting');
  });
});
