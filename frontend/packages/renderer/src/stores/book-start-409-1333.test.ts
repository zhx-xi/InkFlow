/**
 * #1333 段 2 · §3.5-7（拍板）—— 重复启动同计划：前端只透错，不静默新建 run（N25）。
 *
 * 后端契约（见 backend/tests/unit/api/routers/test_book_run_409_1333.py）：
 * 同一计划重复启动 → 409。
 *
 * 前端守护契约：`startRun` 失败（409）→ `error` 记录服务端 detail，
 * `runId` **保持原值/为 null**（绝不静默新建 run 覆盖当前运行）。
 *
 * 说明：本用例是**守护型**（GREEN 前后均应 PASS）——锁定「失败不假装成功」不变量，
 * 防止后续重构把 error 吞掉或误置 runId。
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act } from '@testing-library/react';
import { useBookStore } from './book';
import { apiFetch, ApiError } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

beforeEach(() => {
  apiFetchMock.mockReset();
  useBookStore.setState({
    runId: null,
    runStatus: null,
    error: null,
    loading: false,
    progressReason: null,
    progress: {},
    counters: null,
    progressStats: { total: 0, done: 0, inProgress: 0, failed: 0, skipped: 0, pending: 0 },
  });
});

describe('book store — 重复启动 409 透错（#1333 · N25）', () => {
  it('startRun 遇 409 → error 记录服务端 detail 且 runId 保持 null（不静默新建 run）', async () => {
    apiFetchMock.mockRejectedValue(new ApiError(409, '运行已在进行中'));

    await act(async () => {
      await useBookStore.getState().startRun('wp-1');
    });

    const s = useBookStore.getState();
    expect(s.runId).toBeNull();
    expect(s.error).toContain('运行已在进行中');
    expect(s.loading).toBe(false);
  });
});
