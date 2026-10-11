/**
 * #1532 / #1546「AI 提取」结果视图 + 最小化 RED 契约；#1582 补生命周期契约。
 *
 * 【契约（父侧定稿）】
 * - 提交一律带 `stage: true`（两段式：产物只进暂存区，确认前正式表零变更）
 * - 成功后对话框切**结果视图**：
 *   `ai-extract-result` 容器 + `ai-extract-created`（`ai-extract-created-item` × N）
 *   + `ai-extract-updated`（`ai-extract-updated-item` × M）
 * - 「确认落库」(`ai-extract-confirm`) → `POST /api/v1/projects/{pid}/extractions/staging/{batch}/confirm`
 *   → ok toast + 关框
 * - 「取消」(`ai-extract-cancel`) → `POST .../staging/{batch}/cancel` → 关框
 * - 「最小化」(`ai-extract-min`) → 对话框收起 + `ai-extract-float` 浮窗；点浮窗 → 恢复对话框
 *
 * 【#1582 生命周期契约（本文件新增；缺陷：浮窗随宿主重挂载消失）】
 * - 组件**无 props**：会话状态（open / minimized / staged / projectId / initialKind）读 `stores/extract.ts`
 *   → 宿主页重挂载 / 路由切换 / 组件整体重挂载后，浮窗与结果视图仍存活（跨重挂载契约7）
 * - 关闭对话框（×）且有未确认结果 → warn toast `extract.unconfirmedKept`（契约8）——
 *   关框只清结果视图，暂存批次仍在服务端，由「待确认提取（N）」入口列出
 *
 * 【RED 预期失败形态】#1582 契约：无 store 驱动的跨重挂载存活（element-missing）+ 无关框提示。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AIExtractDialog } from './AIExtractDialog';
import { apiFetch } from '../../api/client';
import { useExtractStore } from '../../stores/extract';
import { useToastStore } from '../../stores/toast';
import { extractEn, extractZh } from '../../i18n/extract-keys';

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const CHAPTERS_RESP = {
  items: [{ id: 'ch1', title: '第一章', volume_id: 'v1', order_index: 0, word_count: 10 }],
  total: 1,
  offset: 0,
  limit: 50,
};
const VOLUMES_RESP = { items: [{ id: 'v1', project_id: 'p1', title: '第一卷', order_index: 0 }] };
const RUNS_RESP = { items: [], total: 0, offset: 0, limit: 50 };
/** 待确认批次列表（#1581 冻结形状）：confirm 后 mock 递减，用于断言 N 同步 */
let batches: Array<{ batch_id: string; type: string; created_at: string; item_count: number }> = [];

/** stage 提取信封：detail 携带 would-be 条目清单 */
const STAGE_ENVELOPE = {
  type: 'character',
  status: 'success',
  skipped_reason: null,
  processed_sources: 1,
  skipped_sources: 0,
  created: 2,
  updated: 1,
  warnings: [],
  model: 'deepseek-chat',
  indexed: false,
  batch_id: 'ext-1',
  detail: {
    created: [{ id: 'c1', name: '角色甲' }, { id: 'c2', name: '角色壬' }],
    updated: [{ id: 'c3', name: '角色乙' }],
  },
};

function bodyOf(path: string): Record<string, unknown> | undefined {
  const call = apiFetchMock.mock.calls.find(
    (c) => c[0] === path && (c[1] as { method?: string })?.method === 'POST',
  );
  return (call?.[1] as { body?: Record<string, unknown> })?.body;
}

function resetExtractStore() {
  useExtractStore.setState({
    open: false,
    minimized: false,
    projectId: null,
    initialKind: undefined,
    staged: null,
    pending: [],
    pendingLoaded: false,
    pendingFor: null,
  });
}

beforeEach(() => {
  apiFetchMock.mockReset();
  useToastStore.setState({ toasts: [] });
  resetExtractStore();
  batches = [];
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path.startsWith('/api/v1/projects/p1/chapters')) return { ...CHAPTERS_RESP };
    if (path === '/api/v1/projects/p1/volumes') return { ...VOLUMES_RESP };
    if (path.startsWith('/api/v1/projects/p1/extractions/runs')) return { ...RUNS_RESP };
    if (path === '/api/v1/projects/p1/extractions/staging') return { batches };
    if (path.endsWith('/confirm') || path.endsWith('/cancel')) {
      const id = path.split('/').slice(-2)[0];
      batches = batches.filter((x) => x.batch_id !== id);
      return { batch_id: id, created: 1, updated: 0, deleted: 1 };
    }
    if (path === '/api/v1/extract' && init?.method === 'POST') return { ...STAGE_ENVELOPE };
    return { ok: true };
  });
});

async function runExtract(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('radio', { name: '角色' }));
  await user.click(await screen.findByRole('radio', { name: '全文' }));
  await user.click(await screen.findByTestId('ai-extract-run'));
}

/** 开框（生产环境由入口 / 写作页调 `openDialog`）+ 渲染 App 层对话框 */
function renderDialog(initialKind?: 'timeline') {
  useExtractStore.getState().openDialog('p1', initialKind);
  return render(<AIExtractDialog />);
}

const closed = () => useExtractStore.getState().open === false;

describe('「AI 提取」结果视图 + 最小化（#1532 / #1546）', () => {
  it('契约1（stage）：提交带 stage:true', async () => {
    const user = userEvent.setup();
    renderDialog();
    await runExtract(user);
    await waitFor(() => {
      expect(bodyOf('/api/v1/extract')?.stage).toBe(true);
    });
  });

  it('契约2（结果视图）：成功后展示新增/更新清单', async () => {
    const user = userEvent.setup();
    renderDialog();
    await runExtract(user);

    const result = await screen.findByTestId('ai-extract-result');
    const created = within(result).getByTestId('ai-extract-created');
    expect(within(created).getAllByTestId('ai-extract-created-item')).toHaveLength(2);
    expect(within(created).getByText(/角色甲/)).toBeInTheDocument();
    const updated = within(result).getByTestId('ai-extract-updated');
    expect(within(updated).getAllByTestId('ai-extract-updated-item')).toHaveLength(1);
    expect(within(updated).getByText(/角色乙/)).toBeInTheDocument();
  });

  it('契约3（确认落库）：调 confirm 端点 + 关框', async () => {
    const user = userEvent.setup();
    renderDialog();
    await runExtract(user);
    await user.click(await screen.findByTestId('ai-extract-confirm'));

    await waitFor(() => {
      const call = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/projects/p1/extractions/staging/ext-1/confirm',
      );
      expect(call).toBeDefined();
    });
    await waitFor(() => expect(closed()).toBe(true));
  });

  it('契约4（取消）：调 cancel 端点 + 关框（零确认调用）', async () => {
    const user = userEvent.setup();
    renderDialog();
    await runExtract(user);
    await user.click(await screen.findByTestId('ai-extract-cancel'));

    await waitFor(() => {
      const call = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/projects/p1/extractions/staging/ext-1/cancel',
      );
      expect(call).toBeDefined();
    });
    expect(apiFetchMock.mock.calls.some((c) => String(c[0]).endsWith('/confirm'))).toBe(false);
    await waitFor(() => expect(closed()).toBe(true));
  });

  it('契约5（最小化）：收起对话框 + 浮窗；点浮窗还原', async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(await screen.findByTestId('ai-extract-min'));

    const float = await screen.findByTestId('ai-extract-float');
    expect(screen.queryByTestId('ai-extract-dialog')).not.toBeInTheDocument();

    await user.click(float);
    expect(await screen.findByTestId('ai-extract-dialog')).toBeInTheDocument();
  });

  it('契约6（i18n）：结果视图/最小化新键 zh/en 对齐', async () => {
    for (const k of [
      'resultTitle',
      'createdTitle',
      'updatedTitle',
      'confirm',
      'cancel',
      'willOverwrite',
      'floatRestore',
      // #1582
      'floatPending',
      'unconfirmedKept',
      'pending',
      'pendingNote',
      'pendingFoot',
      'pendingView',
      'pendingCount',
    ] as const) {
      const key = `extract.${k}`;
      expect(extractZh[key], `${key} zh`).toBeTruthy();
      expect(extractEn[key], `${key} en`).toBeTruthy();
    }
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// #1582：生命周期（浮窗 / 结果跨重挂载存活 + 关框提示）
// ═══════════════════════════════════════════════════════════════════════════
describe('「AI 提取」浮窗生命周期（#1582）', () => {
  it('契约7（跨重挂载存活）：最小化 + 已出结果 → 整体卸载/重挂载 → 浮窗仍在；还原可见结果视图', async () => {
    const user = userEvent.setup();
    const first = renderDialog();
    await runExtract(user);
    await screen.findByTestId('ai-extract-result');
    await user.click(await screen.findByTestId('ai-extract-min'));
    await screen.findByTestId('ai-extract-float');
    expect(useExtractStore.getState().minimized).toBe(true);

    // 宿主页重挂载 / 路由切换 / 进程内组件树重建：DOM 与组件实例全丢
    first.unmount();
    expect(screen.queryByTestId('ai-extract-float')).not.toBeInTheDocument();

    // 重新挂载（生产 = App 层常驻；此处按最坏情形整体重建）
    render(<AIExtractDialog />);
    const float = await screen.findByTestId('ai-extract-float');
    expect(float).toHaveTextContent('待确认');

    await user.click(float);
    const result = await screen.findByTestId('ai-extract-result');
    expect(within(result).getAllByTestId('ai-extract-created-item')).toHaveLength(2);
    expect(within(result).getAllByTestId('ai-extract-updated-item')).toHaveLength(1);
  });

  it('契约7b（进行中最小化）：浮窗文案为「提取中」，不谎报待确认', async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(await screen.findByTestId('ai-extract-min'));
    const float = await screen.findByTestId('ai-extract-float');
    expect(float).toHaveTextContent('提取中');
    expect(float).not.toHaveTextContent('待确认');
  });

  it('契约8（关框提示）：有未确认结果时关闭 → warn toast 指向「待确认提取」入口', async () => {
    const user = userEvent.setup();
    renderDialog();
    await runExtract(user);
    await screen.findByTestId('ai-extract-result');

    await user.click(screen.getByRole('button', { name: '关闭' }));

    await waitFor(() => {
      const toast = useToastStore.getState().toasts.find((x) => x.type === 'warn');
      expect(toast?.message).toBe(extractZh['extract.unconfirmedKept']);
    });
    expect(closed()).toBe(true);
    expect(useExtractStore.getState().staged).toBeNull();
  });

  it('契约8b（无结果时关框）：不打扰——不弹提示', async () => {
    const user = userEvent.setup();
    renderDialog();
    await screen.findByTestId('ai-extract-dialog');
    await user.click(screen.getByRole('button', { name: '关闭' }));
    await waitFor(() => expect(closed()).toBe(true));
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it('契约9（initialKind 来源页）：store 里按来源页开框 → 默认类型随来源页', async () => {
    renderDialog('timeline');
    const group = await screen.findByTestId('ai-extract-type');
    expect(within(group).getByRole('radio', { name: '时间线' })).toBeChecked();
  });
});
