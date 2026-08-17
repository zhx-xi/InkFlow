/**
 * useKernelStore 状态机契约（Issue #384 层 1，2026-08-16）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 `src/stores/kernel.ts` 必须匹配：
 *
 * 状态机（三态 status + booted 门控开关 + healthFailures 连续失败计数，#419 方案 A）：
 * - 初始态：status='booting' + booted=false + healthFailures=0
 * - checkHealth() 成功 → status='ready' + booted=true + healthFailures=0（成功清零）
 * - checkHealth() 失败（阈值语义：#419，方案 A 已拍板）：
 *   - 启动期（booted=false）：连续失败达阈值才置 status='failed'；第 1、2 次连续失败保持
 *     status='booting'（BootGate 不闪「连接失败」），healthFailures 递增
 *   - 运行期（booted=true）：单次失败立即 status='failed'，booted 保持 true（门控不回退，既有语义）
 * - 阈值换算：POLL_INTERVAL_MS=5000 + 启动即探测一次（t=0）→ 连续 3 次失败（t=0/5/10）≈ 10s 时间窗；
 *   契约锁行为不锁常量名（FAILURE_THRESHOLD=3 或等价实现），第 3 次连续失败必置 failed
 * - retry()：置 status='booting' + healthFailures=0（失败计数清零），再 checkHealth()
 * - startPolling()：立即 checkHealth 一次 + setInterval 轮询；幂等（重复调用不叠加 timer）
 * - stopPolling()：清 timer（可安全重复调用）
 *
 * 导出面（GREEN 必实现）：
 * - export type KernelStatus = 'booting' | 'ready' | 'failed'
 * - export const useKernelStore = create<KernelState>(...)（zustand）
 * - KernelState 字段：status / booted / healthFailures / checkHealth / startPolling / stopPolling / retry
 * - healthFailures = 连续失败计数（启动期递增；成功 / retry 清零）
 * - checkHealth 内部调 apiFetch('/health')（成功不抛 = ready；抛错 = 失败计数递增 + 阈值判定）
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
  useKernelStore.setState({ status: 'booting', booted: false, healthFailures: 0 });
});

afterEach(() => {
  // 清理残留轮询 timer，避免跨测试泄漏
  useKernelStore.getState().stopPolling();
});

describe('useKernelStore — 内核状态单一真相源（#384）', () => {
  it('初始态：status=booting + booted=false + healthFailures=0', () => {
    expect(useKernelStore.getState().status).toBe('booting');
    expect(useKernelStore.getState().booted).toBe(false);
    expect(useKernelStore.getState().healthFailures).toBe(0);
  });

  it('checkHealth 成功 → status=ready + booted=true（调 /health）', async () => {
    apiFetchMock.mockResolvedValue({ ok: true });
    await useKernelStore.getState().checkHealth();
    expect(apiFetchMock).toHaveBeenCalledWith('/health');
    expect(useKernelStore.getState().status).toBe('ready');
    expect(useKernelStore.getState().booted).toBe(true);
    expect(useKernelStore.getState().healthFailures).toBe(0);
  });

  it('checkHealth 失败（启动期 booted=false，首次）→ 保持 booting + booted=false + healthFailures=1（阈值未达不置 failed）', async () => {
    apiFetchMock.mockRejectedValue(new Error('kernel unreachable'));
    await useKernelStore.getState().checkHealth();
    expect(useKernelStore.getState().status).toBe('booting');
    expect(useKernelStore.getState().booted).toBe(false);
    expect(useKernelStore.getState().healthFailures).toBe(1);
  });

  it('checkHealth 失败（运行期 booted=true）→ status=failed + booted 保持 true（门控不回退）', async () => {
    useKernelStore.setState({ status: 'ready', booted: true });
    apiFetchMock.mockRejectedValue(new Error('kernel unreachable'));
    await useKernelStore.getState().checkHealth();
    expect(useKernelStore.getState().status).toBe('failed');
    expect(useKernelStore.getState().booted).toBe(true);
  });

  it('连续失败达阈值（3 次 ≈ 10s）：第 1/2 次保持 booting，第 3 次置 failed', async () => {
    apiFetchMock.mockRejectedValue(new Error('kernel unreachable'));
    await useKernelStore.getState().checkHealth();
    expect(useKernelStore.getState().status).toBe('booting');
    expect(useKernelStore.getState().healthFailures).toBe(1);
    await useKernelStore.getState().checkHealth();
    expect(useKernelStore.getState().status).toBe('booting');
    expect(useKernelStore.getState().healthFailures).toBe(2);
    await useKernelStore.getState().checkHealth();
    expect(useKernelStore.getState().status).toBe('failed');
    expect(useKernelStore.getState().booted).toBe(false);
    expect(useKernelStore.getState().healthFailures).toBe(3);
  });

  it('10s 窗内成功无 failed 闪烁：首败保持 booting（不闪「连接失败」），次查成功直接 ready', async () => {
    apiFetchMock.mockRejectedValueOnce(new Error('kernel unreachable'));
    apiFetchMock.mockResolvedValueOnce({ ok: true });
    await useKernelStore.getState().checkHealth(); // 第 1 次：失败
    expect(useKernelStore.getState().status).toBe('booting');
    await useKernelStore.getState().checkHealth(); // 第 2 次：成功
    expect(useKernelStore.getState().status).toBe('ready');
    expect(useKernelStore.getState().booted).toBe(true);
    expect(useKernelStore.getState().healthFailures).toBe(0);
  });

  it('成功清零失败计数（防抖动）：fail → success 后 healthFailures 归 0', async () => {
    apiFetchMock.mockRejectedValueOnce(new Error('kernel unreachable'));
    apiFetchMock.mockResolvedValueOnce({ ok: true });
    await useKernelStore.getState().checkHealth(); // 失败：计数递增
    expect(useKernelStore.getState().healthFailures).toBe(1);
    await useKernelStore.getState().checkHealth(); // 成功：计数清零
    expect(useKernelStore.getState().healthFailures).toBe(0);
  });

  it('retry：failed → booting（同步置位 + 失败计数清零）→ checkHealth 成功 → ready+booted=true', async () => {
    useKernelStore.setState({ status: 'failed', booted: false, healthFailures: 2 });
    apiFetchMock.mockResolvedValue({ ok: true });
    useKernelStore.getState().retry();
    expect(useKernelStore.getState().status).toBe('booting');
    expect(useKernelStore.getState().healthFailures).toBe(0);
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
