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
import userEvent from '@testing-library/user-event';
import { ExecutionDetailPanel } from './ExecutionDetailPanel';
import { apiFetch } from '../api/client';
import { getRun, listRuns } from '../api/runs';
import { useThemeStore } from '../stores/theme';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

vi.mock('../api/runs', () => ({ getRun: vi.fn(), listRuns: vi.fn() }));

const apiFetchMock = vi.mocked(apiFetch);
const getRunMock = vi.mocked(getRun);
const listRunsMock = vi.mocked(listRuns);

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

/** #599：agentic run 决策轨迹 fixture（领域 AgentRun model_dump(mode='json') 形状） */
const MOCK_RUN = {
  id: 'r1',
  project_id: 'p1',
  chapter_id: 'c1',
  mode: 'agentic',
  status: 'completed',
  steps: [
    {
      index: 0,
      message_content: '我来查一下角色设定。',
      tool_calls: [
        { step_index: 0, tool_name: 'search_characters', arguments: { query: '主角' }, result: '{"ok":true,"items":[]}', is_error: false },
      ],
      tokens: 120,
    },
    {
      index: 1,
      message_content: '正文内容...',
      tool_calls: [
        { step_index: 1, tool_name: 'save_draft', arguments: { content: '正文' }, result: '{"ok":true,"draft_id":"d1"}', is_error: false },
      ],
      tokens: 200,
    },
  ],
  final_content: '最终正文内容',
  draft_id: 'd1',
  model: 'deepseek',
  token_usage_total: 320,
  terminated_by: 'llm',
  created_at: '2026-08-23T10:00:00Z',
  updated_at: '2026-08-23T10:00:05Z',
};

beforeEach(() => {
  apiFetchMock.mockReset();
  getRunMock.mockReset();
  listRunsMock.mockReset();
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

describe('ExecutionDetailPanel — agentic 动态工具调用流（#599 D10-A）', () => {
  it('runId → 渲染决策步骤流（steps + 工具卡），调用 getRun', async () => {
    getRunMock.mockResolvedValue(MOCK_RUN as never);
    render(<ExecutionDetailPanel runId="r1" />);
    expect(await screen.findByTestId('exec-detail-steps')).toBeInTheDocument();
    expect(getRunMock).toHaveBeenCalledWith('r1');
    // 步骤卡
    const step0 = screen.getByTestId('exec-detail-step-0');
    expect(step0).toHaveTextContent('我来查一下角色设定。');
    const step1 = screen.getByTestId('exec-detail-step-1');
    expect(step1).toHaveTextContent('正文内容');
    // 工具卡：tool_name + arguments + result
    const tool0 = screen.getByTestId('exec-detail-tool-call-0-0');
    expect(tool0).toHaveTextContent('search_characters');
    expect(tool0).toHaveTextContent('主角');
    expect(tool0).toHaveTextContent('items');
    const tool1 = screen.getByTestId('exec-detail-tool-call-1-0');
    expect(tool1).toHaveTextContent('save_draft');
    // final_content + token_usage_total
    expect(screen.getByTestId('exec-detail-final')).toHaveTextContent('最终正文内容');
    expect(screen.getByTestId('exec-detail-final')).toHaveTextContent('320');
  });

  it('run 无 steps → 渲染 exec-detail-steps-empty 空态', async () => {
    getRunMock.mockResolvedValue({ ...MOCK_RUN, steps: [] } as never);
    render(<ExecutionDetailPanel runId="r1" />);
    expect(await screen.findByTestId('exec-detail-steps-empty')).toBeInTheDocument();
  });

  it('getRun 失败 → 显示错误（不崩溃）', async () => {
    getRunMock.mockRejectedValue(new Error('run 不存在'));
    render(<ExecutionDetailPanel runId="r1" />);
    const panel = await screen.findByTestId('exec-detail');
    expect(panel).toHaveTextContent(/run 不存在/);
  });
});

describe('ExecutionDetailPanel — 工作流栏（#599 可置上/下方）', () => {
  it('workflowPlacement=top → exec-workflow-bar 位于区块上方，含步骤步进', async () => {
    getRunMock.mockResolvedValue(MOCK_RUN as never);
    render(<ExecutionDetailPanel runId="r1" workflowPlacement="top" />);
    const bar = await screen.findByTestId('exec-workflow-bar');
    const steps = screen.getByTestId('exec-detail-steps');
    // 工作流栏在详情区块之前（DOM 顺序）
    expect(bar.compareDocumentPosition(steps) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByTestId('exec-workflow-step-0')).toBeInTheDocument();
    expect(screen.getByTestId('exec-workflow-step-1')).toBeInTheDocument();
  });

  it('workflowPlacement=bottom → exec-workflow-bar 位于区块下方', async () => {
    getRunMock.mockResolvedValue(MOCK_RUN as never);
    render(<ExecutionDetailPanel runId="r1" workflowPlacement="bottom" />);
    const bar = await screen.findByTestId('exec-workflow-bar');
    const steps = screen.getByTestId('exec-detail-steps');
    expect(steps.compareDocumentPosition(bar) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe('ExecutionDetailPanel — 统一历史列表（#599 D12-A 双入口统一出口）', () => {
  it('无 executionId + projectId → 同屏渲染链式 execution + agentic run', async () => {
    apiFetchMock.mockResolvedValue({ items: [MOCK_LIST_ITEM], total: 1 } as never);
    listRunsMock.mockResolvedValue({ items: [MOCK_RUN], total: 1 } as never);
    render(<ExecutionDetailPanel executionId={null} projectId="p1" />);
    // 链式历史项（既有）
    expect(await screen.findByTestId('exec-history-item-e1')).toBeInTheDocument();
    // agentic 历史项（新）
    expect(await screen.findByTestId('exec-history-run-r1')).toBeInTheDocument();
    expect(screen.queryByTestId('exec-detail-empty')).not.toBeInTheDocument();
  });

  it('两者皆空 → exec-detail-empty（守卫：writing.test.tsx 既有契约不变）', async () => {
    apiFetchMock.mockResolvedValue({ items: [], total: 0 } as never);
    listRunsMock.mockResolvedValue({ items: [], total: 0 } as never);
    render(<ExecutionDetailPanel executionId={null} projectId="p1" />);
    expect(await screen.findByTestId('exec-detail-empty')).toBeInTheDocument();
  });

  it('点击 agentic run 历史项 → 进入 agentic 详情（getRun 被调）', async () => {
    apiFetchMock.mockResolvedValue({ items: [], total: 0 } as never);
    listRunsMock.mockResolvedValue({ items: [MOCK_RUN], total: 1 } as never);
    getRunMock.mockResolvedValue(MOCK_RUN as never);
    const user = userEvent.setup();
    render(<ExecutionDetailPanel executionId={null} projectId="p1" />);
    const runItem = await screen.findByTestId('exec-history-run-r1');
    await user.click(runItem);
    expect(await screen.findByTestId('exec-detail-steps')).toBeInTheDocument();
    expect(getRunMock).toHaveBeenCalledWith('r1');
  });
});
