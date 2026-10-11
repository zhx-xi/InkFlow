/**
 * #1582 提取会话 store RED 契约（`stores/extract.ts`，zustand；同目录惯例 = 同名 `.test.ts`）。
 *
 * 【为什么要有这个 store】#1582 缺陷：提取会话（浮窗 / 结果视图）原本绑在宿主页局部
 * state（`library.tsx` / `writing.tsx` 各一个 `useState`）→ 宿主重挂载或路由切换即复位，
 * 浮窗与结果视图一并消失（`AIExtractDialog` 内 `if (!open) return null` 语义）⇒ 两段式
 * 结果永久不可达。修复（拍板 B1-a）：会话里必须跨路由/重挂载存活的那一份状态上提到本 store。
 *
 * 【上提最小集】`open` / `minimized` / `staged` / `initialKind` / `projectId` + 待确认批次列表
 * `pending`。**不上提** `chapters` / `volumes` / `runs` / 范围面等一次性输入（留在组件内，
 * 避免上一次提取的输入泄漏到下一次）。
 *
 * 【契约】
 * - `openDialog(projectId, initialKind?)`：开框；`staged` 复位 null（新会话）；`minimized=false`
 * - `closeDialog()`：关框 —— **只清结果视图（staged=null）**，暂存批次仍在服务端，由
 *   「待确认提取（N）」入口列出（关框 ≠ 丢弃结果）
 * - `minimize()` / `restore()`：浮窗 ⇄ 对话框
 * - `viewBatch(projectId, staged)`：从入口「查看」某一批 → 直接进结果视图（open=true、不最小化）
 * - `refreshPending(projectId)`：`GET /api/v1/projects/{pid}/extractions/staging`
 *   → `{batches: [{batch_id, type, created_at, item_count}]}`（W11a 轨 1 / #1581 交付的形状，本轨只消费）
 *   → `pending`，`pendingFor = projectId`（**按 projectId 归属，切项目不串**）
 * - 迟到响应作废：切项目后再回来旧项目的响应不得覆盖（只认最后一次请求）
 * - 拉取失败 → `pending=[]`、不抛（入口静默不渲染，不炸页面）
 *
 * 【RED 预期失败形态】`stores/extract.ts` 不存在 → 模块缺失（module-missing）→ 全文件 FAIL。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useExtractStore, type PendingBatch } from './extract';
import { apiFetch } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);
const LIST_PATH = '/api/v1/projects/p1/extractions/staging';

function batch(id: string, type = 'timeline', itemCount = 3): PendingBatch {
  return { batch_id: id, type, created_at: '2026-10-11T06:02:00Z', item_count: itemCount };
}

const EMPTY = {
  open: false,
  minimized: false,
  projectId: null,
  initialKind: undefined,
  staged: null,
  pending: [] as PendingBatch[],
  pendingLoaded: false,
  pendingFor: null,
};

beforeEach(() => {
  apiFetchMock.mockReset();
  useExtractStore.setState({ ...EMPTY });
});

describe('提取会话 store（#1582）', () => {
  it('初始态：未开框 / 无结果 / 列表空；动作齐备', () => {
    const s = useExtractStore.getState();
    expect(s.open).toBe(false);
    expect(s.minimized).toBe(false);
    expect(s.staged).toBeNull();
    expect(s.pending).toEqual([]);
    for (const fn of [
      'openDialog',
      'closeDialog',
      'minimize',
      'restore',
      'viewBatch',
      'setStaged',
      'refreshPending',
    ] as const) {
      expect(typeof s[fn], fn).toBe('function');
    }
  });

  it('openDialog：开框 + 记 projectId/来源页类型 + 清上一次结果 + 取消最小化', () => {
    useExtractStore.setState({
      minimized: true,
      staged: { batchIds: ['old'], created: [{ name: '旧' }], updated: [] },
    });
    useExtractStore.getState().openDialog('p1', 'timeline');
    const s = useExtractStore.getState();
    expect(s.open).toBe(true);
    expect(s.minimized).toBe(false);
    expect(s.projectId).toBe('p1');
    expect(s.initialKind).toBe('timeline');
    expect(s.staged).toBeNull();
  });

  it('closeDialog：关框只清结果视图（staged=null），不最小化', () => {
    useExtractStore.getState().openDialog('p1');
    useExtractStore.getState().setStaged({
      batchIds: ['ext-1'],
      created: [{ id: 'c1', name: '角色甲' }],
      updated: [],
    });
    useExtractStore.getState().closeDialog();
    const s = useExtractStore.getState();
    expect(s.open).toBe(false);
    expect(s.minimized).toBe(false);
    expect(s.staged).toBeNull();
  });

  it('minimize / restore：只切 minimized（结果面与开关不动）', () => {
    useExtractStore.getState().openDialog('p1');
    useExtractStore.getState().minimize();
    expect(useExtractStore.getState().minimized).toBe(true);
    expect(useExtractStore.getState().open).toBe(true);
    useExtractStore.getState().restore();
    expect(useExtractStore.getState().minimized).toBe(false);
  });

  it('viewBatch：入口「查看」某一批 → 开框 + 非最小化 + 结果面即该批', () => {
    useExtractStore.getState().minimize();
    useExtractStore.getState().viewBatch('p1', {
      batchIds: ['ext-9'],
      created: [{ id: 'c9', name: '角色癸' }],
      updated: [],
    });
    const s = useExtractStore.getState();
    expect(s.open).toBe(true);
    expect(s.minimized).toBe(false);
    expect(s.projectId).toBe('p1');
    expect(s.staged?.batchIds).toEqual(['ext-9']);
    expect(s.staged?.created).toEqual([{ id: 'c9', name: '角色癸' }]);
  });

  it('refreshPending：拉列表端点 → pending 即批次（N = 批次数，非条目数）', async () => {
    apiFetchMock.mockResolvedValue({ batches: [batch('ext-2', 'timeline', 18), batch('ext-1', 'character', 3)] });
    await useExtractStore.getState().refreshPending('p1');

    expect(apiFetchMock).toHaveBeenCalledWith(LIST_PATH);
    const s = useExtractStore.getState();
    expect(s.pending).toHaveLength(2);
    expect(s.pendingFor).toBe('p1');
    expect(s.pendingLoaded).toBe(true);
    // 18 + 3 = 21 条目，但 N 必须是 2（批次数）
    expect(s.pending.map((x) => x.item_count).reduce((a, c) => a + c, 0)).toBe(21);
  });

  it('refreshPending 失败：pending 置空、不抛（入口静默不渲染，不炸页面）', async () => {
    apiFetchMock.mockRejectedValue(new Error('boom'));
    await expect(useExtractStore.getState().refreshPending('p1')).resolves.toBeUndefined();
    expect(useExtractStore.getState().pending).toEqual([]);
    expect(useExtractStore.getState().pendingLoaded).toBe(true);
  });

  it('切项目：旧项目的迟到响应不得覆盖新项目列表（不串项目）', async () => {
    let resolveP1: (v: { batches: PendingBatch[] }) => void = () => {};
    const p1Pending = new Promise<{ batches: PendingBatch[] }>((res) => {
      resolveP1 = res;
    });
    apiFetchMock.mockImplementation((path: string) =>
      path.includes('/projects/p1/') ? p1Pending : Promise.resolve({ batches: [batch('ext-p2')] }),
    );

    const first = useExtractStore.getState().refreshPending('p1');
    await useExtractStore.getState().refreshPending('p2');
    expect(useExtractStore.getState().pendingFor).toBe('p2');

    resolveP1({ batches: [batch('ext-p1')] });
    await first;
    const s = useExtractStore.getState();
    expect(s.pendingFor).toBe('p2');
    expect(s.pending.map((x) => x.batch_id)).toEqual(['ext-p2']);
  });
});
