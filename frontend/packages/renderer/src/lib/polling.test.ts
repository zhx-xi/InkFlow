/**
 * startPolling 通用轮询工具契约（#472 R0 前置重构）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须新建 src/lib/polling.ts 并匹配：
 *
 * export interface PollHandle { cancel: () => void }
 * export interface StartPollingOptions {
 *   intervalMs?: number;                          // 默认 1000
 *   onValue?: (value: T) => void;                 // 每轮 pollFn resolve 后回调（含终态轮）
 * }
 * export function startPolling<T>(
 *   pollFn: () => Promise<T>,
 *   isTerminal: (value: T) => boolean,
 *   options?: StartPollingOptions,
 * ): PollHandle;
 *
 * 行为契约（BookRunPanel / useExecutionPoll 复用；setTimeout 递归 + 终态停止 + cancelled 清理）：
 * - 调用后立即执行一次 pollFn
 * - 非终态 → intervalMs 后再次执行（setTimeout 递归）
 * - 终态 → 停止（不再调度）
 * - pollFn reject → 停止（不无限重试、错误不抛出到调用方）
 * - handle.cancel() → 停止后续调度（清除已排程 timer）
 * - onValue 每轮结果触发（GREEN 供 useExecutionPoll 消费，轮询 UI 态更新）
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { startPolling } from './polling';

describe('startPolling — 立即执行 + 间隔递归', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('调用后立即执行一次 pollFn', async () => {
    const pollFn = vi.fn(async () => 'pending');
    startPolling(pollFn, () => false);
    await vi.advanceTimersByTimeAsync(0);
    expect(pollFn).toHaveBeenCalledTimes(1);
  });

  it('非终态 → 默认 1000ms 间隔重复执行', async () => {
    const pollFn = vi.fn(async () => 'pending');
    startPolling(pollFn, () => false);
    await vi.advanceTimersByTimeAsync(0);
    expect(pollFn).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(pollFn).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1000);
    expect(pollFn).toHaveBeenCalledTimes(3);
  });

  it('终态 → 停止轮询（不再调度）', async () => {
    const pollFn = vi.fn(async () => 'done');
    startPolling(pollFn, (v) => v === 'done');
    await vi.advanceTimersByTimeAsync(0);
    expect(pollFn).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5000);
    expect(pollFn).toHaveBeenCalledTimes(1);
  });

  it('intervalMs 自定义生效', async () => {
    const pollFn = vi.fn(async () => 'pending');
    startPolling(pollFn, () => false, { intervalMs: 300 });
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(300);
    expect(pollFn).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(299);
    expect(pollFn).toHaveBeenCalledTimes(2);
  });

  it('cancel() → 停止后续调度（清除已排程 timer）', async () => {
    const pollFn = vi.fn(async () => 'pending');
    const handle = startPolling(pollFn, () => false);
    await vi.advanceTimersByTimeAsync(0);
    expect(pollFn).toHaveBeenCalledTimes(1);
    handle.cancel();
    await vi.advanceTimersByTimeAsync(5000);
    expect(pollFn).toHaveBeenCalledTimes(1);
  });

  it('pollFn reject → 停止（不无限重试、错误不外抛）', async () => {
    const pollFn = vi.fn(async () => {
      throw new Error('boom');
    });
    startPolling(pollFn, () => false);
    await vi.advanceTimersByTimeAsync(0);
    expect(pollFn).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5000);
    expect(pollFn).toHaveBeenCalledTimes(1);
  });

  it('onValue 回调每轮结果触发（含终态轮）', async () => {
    const values: string[] = [];
    const pollFn = vi.fn(async () => 'done');
    startPolling(pollFn, (v) => v === 'done', { onValue: (v) => values.push(v) });
    await vi.advanceTimersByTimeAsync(0);
    expect(values).toEqual(['done']);
  });
});
