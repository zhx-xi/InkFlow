/**
 * #1440 book 任务看板：「N 章已备份，可恢复」提示契约测试（RED）。
 *
 * 背景：#1430 A2 起，`POST /api/v1/agent/books/runs` 在 `force=true` 覆盖成功时，
 *   响应体追加 `overwrite = { forced, backup_target, chapters_to_backup }`
 *   （见 backend/src/inkflow/api/routers/books.py:560 start_run + book_run_mixin.py prepare_run）。
 *   前端 `BookRunResponse` 此前只有 { run_id, status } → GUI 无法把「哪些章被覆盖过」透出。
 *
 * ⚠️ 本文件 = 契约。GREEN 必须实现（三处）：
 *
 * ① src/api/books.ts：
 *    - 新增 `export interface BookRunOverwrite { forced: boolean; backup_target: string | null; chapters_to_backup: number }`
 *    - `BookRunResponse` 增加可选字段 `overwrite?: BookRunOverwrite`（非 force 请求响应无该键）
 *
 * ② src/stores/book.ts：
 *    - 新增字段 `runOverwrite: BookRunOverwrite | null`（初始 null）
 *    - `startRun` 成功 → `set({ runOverwrite: res.overwrite ?? null })`
 *    - `resetRun` / `reset` → `runOverwrite` 归零（null）
 *
 * ③ src/components/BookRunPanel.tsx：
 *    - `runOverwrite !== null && runOverwrite.chapters_to_backup > 0` →
 *      渲染 data-testid=`run-overwrite-notice`，文案 `t('book.run.overwrite.notice', { count })`
 *      （zh 含「{count} 章已备份」与「可恢复」；en 对应用词）
 *    - 计数为 0 / runOverwrite 为 null → **不渲染**
 *
 * i18n（i18n/book.ts 成对新增，zh/en 键集合对称）：
 *    book.run.overwrite.notice
 *
 * ⚠️ 现状说明（范围如实记录）：GUI 当前**没有 force 开关**（`startBookRun` 不传 force），
 *   故本提示在真实 GUI 交互中暂不可达 —— 它是「响应带 overwrite 即展示」的忠实实现，
 *   为后续 GUI 加 force 入口预留。契约仍按此锁定。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BookRunPanel } from './BookRunPanel';
import { useBookStore } from '../stores/book';
import { useThemeStore } from '../stores/theme';
import { apiFetch } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const RUN_PATH = '/api/v1/agent/books/runs/wp-1';
const RUNS_PATH = '/api/v1/agent/books/runs';

const runStatusFixture = {
  run_id: 'wp-1',
  status: 'completed',
  progress: { 'o-c1': 'done' },
  counters: { max_chapters: 3, max_agent_calls: 3, agent_calls: 3, chapters_written: 3 },
};

beforeEach(() => {
  apiFetchMock.mockReset();
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === RUN_PATH) return runStatusFixture;
    throw new Error(`unexpected: ${path}`);
  });
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useBookStore.getState().reset();
});

describe('BookRunPanel #1440 — 「N 章已备份，可恢复」提示', () => {
  it('overwrite.chapters_to_backup = 3 → 渲染 run-overwrite-notice 且含计数', async () => {
    useBookStore.setState({
      runId: 'wp-1',
      runStatus: 'completed',
      progress: { 'o-c1': 'done' },
      runOverwrite: { forced: true, backup_target: 'chapters.previous_content', chapters_to_backup: 3 },
    });
    render(<BookRunPanel />);
    const notice = await screen.findByTestId('run-overwrite-notice');
    expect(notice).toHaveTextContent('3');
    expect(notice).toHaveTextContent('可恢复');
  });

  it('【反例】chapters_to_backup = 0 → 不渲染提示', async () => {
    useBookStore.setState({
      runId: 'wp-1',
      runStatus: 'completed',
      progress: { 'o-c1': 'done' },
      runOverwrite: { forced: true, backup_target: 'chapters.previous_content', chapters_to_backup: 0 },
    });
    render(<BookRunPanel />);
    await screen.findByTestId('book-run-panel');
    expect(screen.queryByTestId('run-overwrite-notice')).not.toBeInTheDocument();
  });

  it('【反例】runOverwrite 为 null（非 force 请求）→ 不渲染提示', async () => {
    useBookStore.setState({ runId: 'wp-1', runStatus: 'completed', progress: { 'o-c1': 'done' } });
    render(<BookRunPanel />);
    await screen.findByTestId('book-run-panel');
    expect(screen.queryByTestId('run-overwrite-notice')).not.toBeInTheDocument();
  });
});

describe('book store #1440 — startRun 接线 overwrite', () => {
  it('启动响应带 overwrite → store.runOverwrite 被记录', async () => {
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === RUNS_PATH && init?.method === 'POST') {
        return {
          run_id: 'wp-1',
          status: 'running',
          overwrite: { forced: true, backup_target: 'chapters.previous_content', chapters_to_backup: 2 },
        };
      }
      if (path === RUN_PATH) return runStatusFixture;
      throw new Error(`unexpected: ${path}`);
    });

    await useBookStore.getState().startRun('wp-1');

    expect(useBookStore.getState().runOverwrite).toEqual({
      forced: true,
      backup_target: 'chapters.previous_content',
      chapters_to_backup: 2,
    });
  });

  it('【反例】启动响应无 overwrite（非 force）→ runOverwrite 保持 null', async () => {
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === RUNS_PATH && init?.method === 'POST') return { run_id: 'wp-1', status: 'running' };
      if (path === RUN_PATH) return runStatusFixture;
      throw new Error(`unexpected: ${path}`);
    });

    await useBookStore.getState().startRun('wp-1');

    expect(useBookStore.getState().runOverwrite).toBeNull();
  });
});
