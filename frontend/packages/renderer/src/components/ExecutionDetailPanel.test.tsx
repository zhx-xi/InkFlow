/**
 * AI 执行详情页契约（spec §4.3）：ExecutionDetailPanel
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 ExecutionDetailPanel 必须匹配（行为断言，不测样式）。
 *
 * 导出契约：
 * - export function ExecutionDetailPanel(props: { executionId?: string | null; projectId?: string })
 *
 * 数据源：
 * - 详情：GET /api/v1/agent/pipelines/executions/{executionId}（apiFetch，单次详情）
 * - 历史列表（#586）：GET /api/v1/agent/pipelines/executions?project_id=<projectId>（apiFetch）
 *   列表响应形状（后端 list_executions）：{ items: [{ execution_id, pipeline, status,
 *   created_at, total_duration_ms }], total }
 *   详情响应形状（PipelineExecutionStatus + trace）：
 *   { execution_id, pipeline, project_id, status, stages: StageSnapshot[],
 *     trace: TraceEntry[], relations: RelationEntry[], final_output, total_duration_ms, error }
 *
 * 结构 testid：
 * - exec-detail（容器）/ exec-detail-empty（无上下文空态：无 executionId 且无 projectId）
 * - exec-history-list（历史列表容器，#586）/ exec-history-item-<execution_id>（单条历史记录，#586）
 * - exec-detail-stages（各阶段区块）/ exec-detail-stage-<stage_id>（单阶段卡）
 * - exec-detail-trace（思维链/工具调用区块）/ exec-detail-trace-<n>（单条 trace）
 * - exec-detail-relations（Agent 关系区块）
 * - exec-detail-final（最终回复区块）
 *
 * 行为契约：
 * - 无 executionId + 有 projectId → 请求列表端点 GET /pipelines/executions?project_id=<id>
 *   → 渲染历史列表 exec-history-list + exec-history-item-<id>（#586：历史列表永不显示的 bug 修复）
 * - 无 executionId 且无 projectId → exec-detail-empty 空态（不发起请求，无上下文兜底）
 * - 有 executionId → 请求 GET /pipelines/executions/{id} → 渲染 stages/trace/relations/final
 * - stages：每阶段显示 stage_id + status + output（有 output 时）+ error（有 error 时）
 * - trace：每条显示 node + type + reasoning（有 reasoning 时）
 * - relations：显示 from → to + gate_result
 * - final：显示 final_output + total_duration_ms
 * - 请求失败 → 显示错误（不崩溃）
 *
 * i18n key（GREEN 补）：write.detail.empty / write.detail.stages / write.detail.trace /
 * write.detail.relations / write.detail.final / write.detail.unknown
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { ExecutionDetailPanel } from './ExecutionDetailPanel';
import { apiFetch } from '../api/client';
import { useThemeStore } from '../stores/theme';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const MOCK_STATUS = {
  execution_id: 'e1',
  pipeline: 'builtin:write_auto',
  project_id: 'p1',
  status: 'completed',
  stages: [
    { stage_id: 'architect', status: 'completed', output: '本章核心冲突：主角面临抉择', error: '', retry_count: 0, duration_ms: 100 },
    { stage_id: 'writer', status: 'completed', output: '正文内容...', error: '', retry_count: 0, duration_ms: 500 },
  ],
  trace: [
    { node: 'supervisor', type: 'decision', reasoning: '{"action":"execute","role":"architect"}', tool_calls: [], output: '', duration_ms: 30, ts: '2026-08-16T10:00:00Z' },
    { node: 'architect', type: 'stage', reasoning: '规划章节结构', tool_calls: [], output: '大纲', duration_ms: 100, ts: '2026-08-16T10:00:01Z' },
  ],
  relations: [
    { from: 'architect', to: 'writer', type: 'chain', gate_result: 'passed' },
  ],
  final_output: '修订后的成品章节内容',
  total_duration_ms: 1800,
  error: '',
};

/** #586：GET /pipelines/executions?project_id= 列表项（后端 list_executions item 形状） */
const MOCK_LIST_ITEM = {
  execution_id: 'e1',
  pipeline: 'builtin:write_auto',
  status: 'completed',
  created_at: '2026-08-22T10:00:00Z',
  total_duration_ms: 1800,
};

beforeEach(() => {
  apiFetchMock.mockReset();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('ExecutionDetailPanel — 历史列表（#586）', () => {
  it('无 executionId + 有 projectId → 调用列表端点并渲染历史列表（#586 契约核心，RED）', async () => {
    apiFetchMock.mockResolvedValue({ items: [MOCK_LIST_ITEM], total: 1 } as never);
    render(<ExecutionDetailPanel executionId={null} projectId="p1" />);
    // 契约：请求列表端点 GET /api/v1/agent/pipelines/executions?project_id=p1
    // RED：当前实现 executionId 为空直接渲染 empty、从不调用 apiFetch → 本断言 FAIL
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/pipelines/executions?project_id=p1');
    });
    // 契约：渲染历史列表项（当前实现无列表 → 断言 FAIL）
    expect(await screen.findByTestId('exec-history-item-e1')).toBeInTheDocument();
    expect(screen.queryByTestId('exec-detail-empty')).not.toBeInTheDocument();
  });

  it('守护：无 executionId 且无 projectId → exec-detail-empty 空态，不发起请求', () => {
    render(<ExecutionDetailPanel executionId={null} />);
    expect(screen.getByTestId('exec-detail-empty')).toBeInTheDocument();
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it('有 executionId → 仍走单次详情 GET /executions/{id}，不调用列表端点（#586 锁定）', async () => {
    apiFetchMock.mockResolvedValue(MOCK_STATUS as never);
    render(<ExecutionDetailPanel executionId="e1" projectId="p1" />);
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent/pipelines/executions/e1');
    });
    expect(apiFetchMock).not.toHaveBeenCalledWith('/api/v1/agent/pipelines/executions?project_id=p1');
    expect(await screen.findByTestId('exec-detail')).toBeInTheDocument();
  });
});

describe('ExecutionDetailPanel — stages / trace / relations / final 渲染', () => {
  it('stages：每阶段显示 stage_id + status + output', async () => {
    apiFetchMock.mockResolvedValue(MOCK_STATUS as never);
    render(<ExecutionDetailPanel executionId="e1" />);
    const stage1 = await screen.findByTestId('exec-detail-stage-architect');
    expect(stage1).toHaveTextContent('architect');
    expect(stage1).toHaveTextContent('completed');
    expect(stage1).toHaveTextContent('本章核心冲突');
    expect(screen.getByTestId('exec-detail-stage-writer')).toHaveTextContent('正文内容');
  });

  it('trace：每条显示 node + type + reasoning', async () => {
    apiFetchMock.mockResolvedValue(MOCK_STATUS as never);
    render(<ExecutionDetailPanel executionId="e1" />);
    const t0 = await screen.findByTestId('exec-detail-trace-0');
    expect(t0).toHaveTextContent('supervisor');
    expect(t0).toHaveTextContent('execute');
    const t1 = screen.getByTestId('exec-detail-trace-1');
    expect(t1).toHaveTextContent('architect');
    expect(t1).toHaveTextContent('规划章节结构');
  });

  it('relations：显示 from → to + gate_result', async () => {
    apiFetchMock.mockResolvedValue(MOCK_STATUS as never);
    render(<ExecutionDetailPanel executionId="e1" />);
    const relations = await screen.findByTestId('exec-detail-relations');
    expect(relations).toHaveTextContent('architect');
    expect(relations).toHaveTextContent('writer');
    expect(relations).toHaveTextContent('passed');
  });

  it('final：显示 final_output + total_duration_ms', async () => {
    apiFetchMock.mockResolvedValue(MOCK_STATUS as never);
    render(<ExecutionDetailPanel executionId="e1" />);
    const final = await screen.findByTestId('exec-detail-final');
    expect(final).toHaveTextContent('修订后的成品章节内容');
    expect(final).toHaveTextContent('1800');
  });
});

describe('ExecutionDetailPanel — 失败', () => {
  it('请求失败 → 显示错误（不崩溃）', async () => {
    apiFetchMock.mockRejectedValue(new Error('内核离线'));
    render(<ExecutionDetailPanel executionId="e1" />);
    const panel = await screen.findByTestId('exec-detail');
    expect(panel).toHaveTextContent(/内核离线/);
  });
});
