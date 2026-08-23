/**
 * Agent Run API 契约测试（#599 统一执行视图）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须匹配 api/runs.ts（已建）：
 *
 * export interface AgentToolCallDto { step_index; tool_name; arguments; result; is_error; }
 * export interface AgentStepDto { index; message_content; tool_calls; tokens; }
 * export interface AgentRunDto { id; project_id; chapter_id; mode; status; steps;
 *   final_content; draft_id; model; token_usage_total; terminated_by; created_at; updated_at; }
 * export function getRun(runId: string): Promise<AgentRunDto>          → GET /api/v1/agent/runs/{id}
 * export function listRuns(projectId: string, limit=20): Promise<{items,total}>
 *   → GET /api/v1/agent/runs?project_id=<id>&limit=<n>
 *
 * 端点契约（backend api/routers/agent_runs.py 实证）：
 * - GET /api/v1/agent/runs/{run_id} → run dict（model_dump(mode='json')，steps JSON 快照）
 * - GET /api/v1/agent/runs?project_id=<id>&limit=<n> → { items: [...], total }
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { getRun, listRuns } from './runs';
import { apiFetch } from './client';

vi.mock('./client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

beforeEach(() => {
  apiFetchMock.mockReset();
});

describe('runs API — getRun（单次决策轨迹）', () => {
  it('按 run_id 查询 → GET /api/v1/agent/runs/{id}', async () => {
    apiFetchMock.mockResolvedValue({ id: 'r1', steps: [] } as never);
    await getRun('r1');
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/runs/r1');
  });

  it('返回完整 run（含 steps 决策轨迹）', async () => {
    const run = {
      id: 'r1',
      project_id: 'p1',
      chapter_id: 'c1',
      mode: 'agentic',
      status: 'completed',
      steps: [
        {
          index: 0,
          message_content: '查询角色',
          tool_calls: [
            { step_index: 0, tool_name: 'search_characters', arguments: { query: '主角' }, result: '{"ok":true}', is_error: false },
          ],
          tokens: 120,
        },
      ],
      final_content: '最终正文',
      draft_id: null,
      model: 'deepseek',
      token_usage_total: 120,
      terminated_by: 'llm',
      created_at: '2026-08-23T10:00:00Z',
      updated_at: '2026-08-23T10:00:05Z',
    };
    apiFetchMock.mockResolvedValue(run);
    await expect(getRun('r1')).resolves.toEqual(run);
  });
});

describe('runs API — listRuns（项目 run 列表）', () => {
  it('按 project_id 分页查询 → GET /api/v1/agent/runs?project_id=<id>&limit=<n>', async () => {
    apiFetchMock.mockResolvedValue({ items: [], total: 0 } as never);
    await listRuns('p1');
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/runs?project_id=p1&limit=20');
  });

  it('limit 可自定义（默认 20）', async () => {
    apiFetchMock.mockResolvedValue({ items: [], total: 0 } as never);
    await listRuns('p1', 50);
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/runs?project_id=p1&limit=50');
  });

  it('返回 {items, total}', async () => {
    const resp = { items: [{ id: 'r1' }], total: 1 };
    apiFetchMock.mockResolvedValue(resp as never);
    const result = await listRuns('p1');
    expect(result.items).toHaveLength(1);
    expect(result.total).toBe(1);
  });
});
