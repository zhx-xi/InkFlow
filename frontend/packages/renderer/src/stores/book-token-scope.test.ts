/**
 * book store — #1431 token「本轮 vs 累计」基线（`tokenBaseline`）契约测试。
 *
 * 从 `stores/book.test.ts` 拆出的兄弟文件：原文件追加 #1431 用例后 951 行，
 * 超出 `ci_cd/check_file_length.py` 的 900 行门禁（同族先例 = `stores/book-reason.test.ts`，护栏拆分）。
 *
 * 语义（#1288 拍板 (a) 不变）：累计 = `counters.tokens_used`（plan.limits 账单，
 * 持久化、reset **不清零**）；本轮 = 累计 − 基线，基线 = 最近一次 reset 成功时
 * 观测到的累计值（纯前端呈现态）。该设计使「重置 → 重跑」后本轮从 0 起算，
 * 而累计账单原样保留。
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
  // 整店归零 → 每个用例从干净的 store 起步（含 tokenBaseline）
  useBookStore.getState().reset();
});

describe('book store — #1431 token 本轮基线（reset 时捕获 / 整店归零）', () => {
  it('resetRun 成功 → 捕获 reset 前的累计账单为基线 + 运行态归零', async () => {
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/agent/books/runs/wp-1/reset' && init?.method === 'POST') {
        return { run_id: 'wp-1', status: 'ready' };
      }
      throw new Error(`unexpected: ${path} ${init?.method ?? 'GET'}`);
    });
    useBookStore.setState({
      runId: 'wp-1',
      runStatus: 'completed',
      counters: {
        max_chapters: 3,
        max_agent_calls: 5,
        agent_calls: 1,
        chapters_written: 1,
        max_tokens: 300000,
        tokens_used: 250000,
        tokens_warning: true,
      },
      tokenBaseline: 0,
    });

    let ok = false;
    await act(async () => {
      ok = await useBookStore.getState().resetRun();
    });

    expect(ok).toBe(true);
    const s = useBookStore.getState();
    expect(s.tokenBaseline).toBe(250000); // 基线 = reset 时的累计账单（本轮自此刻起算）
    expect(s.counters).toBeNull(); // 运行态归零（#1288 既有语义不变）
    expect(s.runId).toBeNull();
  });

  it('reset（整店归零）→ 基线归 0（新一轮不继承上一计划的累计）', () => {
    useBookStore.setState({ tokenBaseline: 12345 });

    useBookStore.getState().reset();

    expect(useBookStore.getState().tokenBaseline).toBe(0);
  });
});
