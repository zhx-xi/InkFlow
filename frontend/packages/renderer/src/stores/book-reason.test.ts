/**
 * book store #903 增量契约测试（degraded 终态
 * progress_reason 透传 + reset 清空）。
 *
 * 从 stores/book.test.ts 拆出（900 行护栏 check_file_length.py
 * 覆盖 .ts/.tsx，超限优先拆分不贴线）：用例逻辑与
 * 断言逐字节不变，import/beforeEach 镜像主契约文件
 * （#903 契约说明见 book.test.ts 头部 docblock Â§84-91）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act } from '@testing-library/react';
import { useBookStore } from './book';
import { apiFetch } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

beforeEach(() => {
  apiFetchMock.mockReset();
  useBookStore.getState().reset();
});

describe('book store — #903 progress_reason 透传 + reset 清空（degraded 终态理由字段）', () => {
  it('loadRunStatus：GET payload status=degraded + progress_reason → progressReason 透传', async () => {
    apiFetchMock.mockResolvedValue({
      run_id: 'wp-1',
      status: 'degraded',
      progress: { 'o-c1': 'done', 'o-c2': 'failed' },
      counters: { max_chapters: 2, max_agent_calls: 2, agent_calls: 1, chapters_written: 1 },
      progress_reason: '部分章节失败：o-c2 RuntimeError',
    });
    await act(async () => {
      await useBookStore.getState().loadRunStatus('wp-1');
    });
    const s = useBookStore.getState();
    expect(s.runStatus).toBe('degraded');
    // RED 期断言合法：BookState 尚无 progressReason 字段 → undefined ≠ 字符串即 FAIL
    expect(s.progressReason).toBe('部分章节失败：o-c2 RuntimeError');
  });

  it('loadRunStatus：completed + progress_reason null → progressReason 覆写为 null（非默认残留播种 → 清零断言非假绿）', async () => {
    apiFetchMock.mockResolvedValue({
      run_id: 'wp-1',
      status: 'completed',
      progress: { 'o-c1': 'done' },
      counters: { max_chapters: 1, max_agent_calls: 1, agent_calls: 1, chapters_written: 1 },
      progress_reason: null,
    });
    useBookStore.setState({ progressReason: '上轮残留理由' }); // RED 期播种合法：Zustand 合并未知键
    await act(async () => {
      await useBookStore.getState().loadRunStatus('wp-1');
    });
    expect(useBookStore.getState().progressReason).toBeNull();
  });

  it('reset 清空 progressReason（非默认态播种 → 清零断言非假绿）', () => {
    useBookStore.setState({ progressReason: '部分章节失败：o-c2 RuntimeError' });
    useBookStore.getState().reset();
    expect(useBookStore.getState().progressReason).toBeNull();
  });
});
