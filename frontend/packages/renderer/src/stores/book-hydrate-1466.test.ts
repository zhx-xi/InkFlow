/**
 * #1466 成书页水合契约：`useBookStore.hydrate(projectId)`。
 *
 * 缺陷背景：成书页对「已有 plan / 跑过 book run 的书」只显示起点表单——
 * ① 后端无「列项目 plan」端点；② store 从不水合（纯内存态，只有本会话内
 * 跑完访谈才看得到计划卡/运行面板）。
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须在 src/stores/book.ts 追加：
 *
 *   hydrate(projectId: string | null): Promise<void>
 *
 * 行为契约（GREEN 必须满足）：
 * - projectId 为 null / '' → **不发请求**，store 保持原状（边界）
 * - 本会话已开始（sessionId !== null）→ **不发请求**，store 保持原状
 *  （反例守护：当前会话内新建 plan/run 的原有三态路径不受影响）
 * - 否则 GET /api/v1/agent/books/plans?project_id=<id>&offset=0&limit=50
 *   （listBookPlans，api/books.ts）
 * - 取 items[0]（后端按 updated_at DESC，最新在前）作为「该项目当前计划」：
 *   · 无 items → sessionStatus='idle' + writingPlan=null + runId=null
 *     （渲染态 = 起点表单）
 *   · plan.status ∈ {'ready','auto'}（planner 落库的两种未启动态）→
 *     sessionStatus='completed' + writingPlan=plan + runId=null
 *     （渲染态 = 计划卡；reset 后退回 ready 同属此态）
 *   · 其余 status（running / paused / waiting_hitl / completed / failed /
 *     degraded / blocked / aborted）→ sessionStatus='completed' +
 *     writingPlan=plan + runId=plan.id + runStatus=plan.status + progress 同步
 *     （渲染态 = 运行面板；BookRunPanel 据此轮询 getBookRunStatus 补 counters）
 * - 请求失败 → error = errorMessage(err)，三态不被伪造（sessionStatus 不变）
 *
 * 🔴 判据来源：run 载体 = WritingPlan.id（book_service.get_status：「run_id:
 * 书级运行 id（= WritingPlan.id 字符串）」）→ plan 与 run 一一对应，「plans +
 * 各自最近 run」退化为「plans 列表」，不新增第二套状态判断。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useBookStore } from './book';
import { apiFetch, ApiError } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const PLANS_URL = '/api/v1/agent/books/plans?project_id=p1&offset=0&limit=50';

/** 后端 WritingPlanDto 形态（run 状态摘要内嵌于 plan 自身） */
function plan(overrides: Record<string, unknown> = {}) {
  return {
    id: 'wp-1',
    project_id: 'p1',
    title: '既有写作计划',
    status: 'running',
    root_outline_id: null,
    character_ids: [],
    limits: { max_chapters: 3, max_agent_calls: 6 },
    progress: { 'o-c1': 'done', 'o-c2': 'in_progress' },
    execution_refs: { 'o-c1': 'exec-1' },
    thread_id: null,
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-02T00:00:00Z',
    ...overrides,
  };
}

function listResponse(items: unknown[]) {
  return { items, total: items.length, offset: 0, limit: 50 };
}

beforeEach(() => {
  apiFetchMock.mockReset();
  // 每个用例从干净 store 起步（reset() 是既有 action，清三态 + 会话态）
  useBookStore.getState().reset();
});

describe('#1466 hydrate — 有运行中 run → 运行面板态', () => {
  it('status=running：runId=plan.id + runStatus=running + writingPlan + completed', async () => {
    apiFetchMock.mockResolvedValue(listResponse([plan({ status: 'running' })]));
    await useBookStore.getState().hydrate('p1');

    const s = useBookStore.getState();
    expect(apiFetchMock).toHaveBeenCalledWith(PLANS_URL);
    expect(s.sessionStatus).toBe('completed');
    expect(s.writingPlan?.id).toBe('wp-1');
    expect(s.runId).toBe('wp-1');
    expect(s.runStatus).toBe('running');
  });

  it('status=completed（跑完 10 章的历史书）：runId 非空 → 看板可见（报告缺陷主场景）', async () => {
    apiFetchMock.mockResolvedValue(
      listResponse([
        plan({ status: 'completed', progress: { 'o-c1': 'done', 'o-c2': 'done' } }),
      ]),
    );
    await useBookStore.getState().hydrate('p1');

    const s = useBookStore.getState();
    expect(s.runId).toBe('wp-1');
    expect(s.runStatus).toBe('completed');
    expect(s.progress).toEqual({ 'o-c1': 'done', 'o-c2': 'done' });
    expect(s.progressStats.done).toBe(2);
    expect(s.progressStats.total).toBe(2);
  });

  it('status=waiting_hitl：runId 非空（HITL 暂停亦属「已启动」）', async () => {
    apiFetchMock.mockResolvedValue(listResponse([plan({ status: 'waiting_hitl' })]));
    await useBookStore.getState().hydrate('p1');

    const s = useBookStore.getState();
    expect(s.runId).toBe('wp-1');
    expect(s.runStatus).toBe('waiting_hitl');
  });
});

describe('#1466 hydrate — 有计划无 run → 计划卡态', () => {
  it('status=ready：runId=null（不渲染运行面板）+ writingPlan 就位', async () => {
    apiFetchMock.mockResolvedValue(listResponse([plan({ status: 'ready', progress: {} })]));
    await useBookStore.getState().hydrate('p1');

    const s = useBookStore.getState();
    expect(s.sessionStatus).toBe('completed');
    expect(s.writingPlan?.id).toBe('wp-1');
    expect(s.runId).toBeNull();
    expect(s.runStatus).toBeNull();
  });

  it('status=auto（「全部你决定」产出）：runId=null', async () => {
    apiFetchMock.mockResolvedValue(listResponse([plan({ status: 'auto', progress: {} })]));
    await useBookStore.getState().hydrate('p1');

    const s = useBookStore.getState();
    expect(s.writingPlan?.status).toBe('auto');
    expect(s.runId).toBeNull();
  });
});

describe('#1466 hydrate — 都无 → 起点表单态', () => {
  it('空项目（items=[]）→ idle + writingPlan/runId 归 null（200 空列表非 404）', async () => {
    apiFetchMock.mockResolvedValue(listResponse([]));
    await useBookStore.getState().hydrate('p1');

    const s = useBookStore.getState();
    expect(apiFetchMock).toHaveBeenCalledWith(PLANS_URL);
    expect(s.sessionStatus).toBe('idle');
    expect(s.writingPlan).toBeNull();
    expect(s.runId).toBeNull();
  });

  it('多项时取 items[0]（后端 updated_at DESC 最新在前）', async () => {
    apiFetchMock.mockResolvedValue(
      listResponse([
        plan({ id: 'wp-new', status: 'running', title: '最近一轮' }),
        plan({ id: 'wp-old', status: 'completed', title: '更早一轮' }),
      ]),
    );
    await useBookStore.getState().hydrate('p1');

    const s = useBookStore.getState();
    expect(s.writingPlan?.id).toBe('wp-new');
    expect(s.runId).toBe('wp-new');
  });
});

describe('#1466 hydrate — 边界：不发请求', () => {
  it('projectId=null → 不发请求、状态不动', async () => {
    useBookStore.setState({ sessionStatus: 'idle' });
    await useBookStore.getState().hydrate(null);

    expect(apiFetchMock).not.toHaveBeenCalled();
    expect(useBookStore.getState().sessionStatus).toBe('idle');
  });

  it('projectId="" → 不发请求', async () => {
    await useBookStore.getState().hydrate('');

    expect(apiFetchMock).not.toHaveBeenCalled();
  });
});

describe('#1466 hydrate — 反例守护：本会话内的原有三态路径不受影响', () => {
  it('sessionId 非空（本会话已开始访谈/运行）→ 不水合、不被后端旧数据覆盖', async () => {
    useBookStore.setState({
      sessionId: 'sess-1',
      sessionStatus: 'drafting',
      messages: [],
    });
    apiFetchMock.mockResolvedValue(listResponse([plan({ status: 'completed' })]));

    await useBookStore.getState().hydrate('p1');

    const s = useBookStore.getState();
    expect(apiFetchMock).not.toHaveBeenCalled();
    expect(s.sessionStatus).toBe('drafting');
    expect(s.sessionId).toBe('sess-1');
    expect(s.writingPlan).toBeNull();
    expect(s.runId).toBeNull();
  });

  it('空项目水合后仍可走起点表单 → startPlanner 路径（sessionStatus idle → drafting）', async () => {
    apiFetchMock
      .mockResolvedValueOnce(listResponse([]))
      .mockResolvedValueOnce({
        session_id: 'sess-2',
        round: 1,
        questions: [{ id: 'q1', text: '题材？', template: '___' }],
        max_rounds: 5,
      });

    await useBookStore.getState().hydrate('p1');
    expect(useBookStore.getState().sessionStatus).toBe('idle');

    await useBookStore.getState().startPlanner('p1', '写一本关于时间旅者的悬疑小说', 'new', null);
    // apiFetch 第二次调用 = POST /planner（原有访谈路径未被水合破坏）
    expect(apiFetchMock).toHaveBeenLastCalledWith(
      '/api/v1/agent/books/planner',
      expect.objectContaining({ method: 'POST' }),
    );
    expect(useBookStore.getState().sessionStatus).toBe('drafting');
  });
});

describe('#1466 hydrate — 失败不伪造三态', () => {
  it('请求失败 → error 记录、sessionStatus 保持 idle（不假装有计划）', async () => {
    apiFetchMock.mockRejectedValue(new ApiError(500, '服务不可用'));
    await useBookStore.getState().hydrate('p1');

    const s = useBookStore.getState();
    expect(s.error).toBeTruthy();
    expect(s.sessionStatus).toBe('idle');
    expect(s.writingPlan).toBeNull();
    expect(s.runId).toBeNull();
  });
});
