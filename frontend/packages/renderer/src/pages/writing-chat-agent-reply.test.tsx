/**
 * #642-1 契约（前端组件测试，TDD RED→GREEN）：写作页「AI 写作/生成」后，chat 页应显示 Agent 回复，
 * 与详情页 AgentRun 结果（final_output）一致。
 * 现状（BUG）：写作管线 executePipeline → getExecutionStatus.final_output 只落到详情页/编辑器，
 * 未接线到 ChatPanel（chat 读 /chat/messages）→ chat 页无回复。本契约锁 GREEN 注入行为。
 *
 * ⚠️ 本文件 = #642-1 契约。当前实现 FAIL，GREEN 实现必须匹配。
 * 回归：成品落章（编辑器内容 = final_output）不回归；chat 用户消息/展开不回归。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { WritingPage } from './writing';
import { apiFetch } from '../api/client';
import { executePipeline, getExecutionStatus, confirmExecution } from '../api/pipeline';
import { useChapterStore } from '../stores/chapter';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import { useModelsStore, type ProviderConfig } from '../stores/models';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});
vi.mock('../api/pipeline', () => ({
  executePipeline: vi.fn(),
  getExecutionStatus: vi.fn(),
  confirmExecution: vi.fn(),
}));

const apiFetchMock = vi.mocked(apiFetch);
const executeMock = vi.mocked(executePipeline);
const statusMock = vi.mocked(getExecutionStatus);
const confirmMock = vi.mocked(confirmExecution);

const seedVolumes = [{ id: 'v1', title: '第一卷 风起', order_index: 0 }];
const seedChapters = [
  { id: 'c1', title: '第1章 初见', volume_id: 'v1', order_index: 0, word_count: 2347 },
];

const READY_PROVIDER: ProviderConfig = {
  id: 1, name: 'openai', base_url: 'https://api.openai.com/v1', default_model: 'gpt-4o',
  models: [{ id: 'gpt-4o', type: 'chat', roles: ['main'] }], key_saved: true,
  max_retries: 3, timeout: 60, created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};

beforeEach(() => {
  vi.useRealTimers();
  apiFetchMock.mockReset();
  executeMock.mockReset();
  statusMock.mockReset();
  confirmMock.mockReset();
  useModelsStore.setState({ providers: [READY_PROVIDER], loading: false, error: null });
  useToastStore.setState({ toasts: [] });
  executeMock.mockResolvedValue({ execution_id: 'e1', pipeline: 'builtin:write_auto', project_id: 'p1', status: 'pending', created_at: '' });
  statusMock.mockResolvedValue({
    execution_id: 'e1', pipeline: 'builtin:write_auto', project_id: 'p1', status: 'completed',
    stages: [], final_output: '管线成品章节内容', total_duration_ms: 1200, error: '',
  });
  window.INKFLOW_API = { baseURL: 'http://test.local', token: 'tok-1' };
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useChapterStore.setState({
    volumes: seedVolumes, chapters: seedChapters, treeProjectId: 'p1', currentChapterId: 'c1', content: '已有正文第一段。', loading: false, error: null,
  });
  useProjectStore.setState({
    projects: [{ id: 'p1', name: '青云志', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, config: {}, created_at: '', updated_at: '' }],
    currentProjectId: 'p1', loading: false, error: null,
  });
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === '/api/v1/provider-configs') return { items: [READY_PROVIDER], total: 1, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/volumes') return { items: seedVolumes, total: 1, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/chapters') return { items: seedChapters, total: 1, offset: 0, limit: 50 };
    if (path.startsWith('/api/v1/chapters/') && init?.method === 'PATCH') return { ok: true };
    // chat 消息历史默认空（ChatPanel 挂载拉取）
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
});

afterEach(() => {
  vi.useRealTimers();
  delete window.INKFLOW_API;
});

describe('写作页 — AI 生成后 chat 页显示 Agent 回复（#642-1）', () => {
  it('「生成」管线 completed → chat 页显示 Agent 回复（与详情页 final_output 一致）', async () => {
    vi.useFakeTimers();
    render(<WritingPage />);
    fireEvent.click(screen.getByRole('button', { name: '生成' }));
    // 轮询（1s）到 completed
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    // RED：当前实现 chat 未接线管线 Agent 回复 → chat-messages 不渲染该回复 → 下面断言 FAIL
    const aiMsg = await screen.findByTestId('chat-msg-ai-0');
    expect(aiMsg).toHaveTextContent('管线成品章节内容');
    // 回归：成品落章（编辑器内容 = final_output）不回归
    const editor = screen.getByTestId('chapter-editor') as HTMLTextAreaElement;
    expect(editor.value).toBe('管线成品章节内容');
  });
});
