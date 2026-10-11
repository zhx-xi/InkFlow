/**
 * 「待确认提取（N）」入口 RED 契约（#1582；`components/extract/AIExtractEntry.tsx` 内）。
 *
 * 【为什么要有它】两段式暂存（#1545/#1546）把产物留在 `extract_staging` 等确认，但**全仓无任何
 * UI 入口可看**——浮窗一消失（见 AIExtractResultView.test.tsx 的生命周期契约）结果就永久不可达，
 * 未确认批次只能靠 #1551 的 30 天过期清理兜底。拍板 B2-a：资料库工具栏加「待确认提取（N）」入口。
 *
 * 【契约】
 * - 位置：资料库工具栏（`AIExtractEntry` 内，位于「AI 提取」左侧）；仅 currentProjectId 非 null 渲染
 * - `extract-pending-entry`：入口按钮；文案含 i18n `extract.pending` + 角标 N
 * - **N = 待确认批次数**（`pending.length`，非条目数）；`N === 0` → 入口不渲染（拍板 D1，不占位）
 * - 点击 → `extract-pending-panel` 面板：每批一行 `extract-pending-item`（类型 / 条目数 / 时间）
 *   + 行内 `extract-pending-view` / `extract-pending-cancel` / `extract-pending-confirm`（拍板 D2）
 * - 「确认落库」→ `POST .../staging/{batch_id}/confirm`；「取消」→ `POST .../staging/{batch_id}/cancel`；
 *   两者完成后**重拉列表** → 角标 N 同步下降
 * - 「查看」→ `GET .../staging/{batch_id}`（既有端点，不新增）→ 按 action 拆新增/更新 → 开结果视图
 * - 数据源 `GET /api/v1/projects/{pid}/extractions/staging`（#1581 交付的冻结形状，本轨只消费）
 * - **跨进程存活**：进程内的 store 一旦清空（= 关掉 App 重开），入口重新挂载仍能从服务端列出批次
 *
 * 【RED 预期失败形态】`extract-pending-entry` 不存在（无入口）→ element-missing。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AIExtractEntry } from './AIExtractEntry';
import { AIExtractDialog } from './AIExtractDialog';
import { apiFetch } from '../../api/client';
import { useExtractStore, type PendingBatch } from '../../stores/extract';
import { useProjectStore } from '../../stores/project';
import { useThemeStore } from '../../stores/theme';
import { useToastStore } from '../../stores/toast';

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const projectP1 = {
  id: 'p1',
  name: '项目甲',
  tags: ['玄幻'],
  language: 'zh-CN',
  target_words: 800000,
  config: {},
  created_at: '2026-08-01T10:00:00Z',
  updated_at: '2026-08-05T10:00:00Z',
};

function batch(id: string, type = 'timeline', itemCount = 18): PendingBatch {
  return { batch_id: id, type, created_at: '2026-10-11T06:02:00Z', item_count: itemCount };
}

/** 服务端「当前待确认批次」可变状态（confirm / cancel 后由 mock 递减，模拟真实列表端点） */
let batches: PendingBatch[] = [];

function installMock() {
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === '/api/v1/projects/p1/extractions/staging') return { batches };
    const single = /\/extractions\/staging\/([^/]+)$/.exec(path);
    if (single && (init?.method ?? 'GET') === 'GET') {
      const id = single[1];
      return {
        batch_id: id,
        items: [
          { entity_type: 'timeline_event', action: 'create', name: '事件甲', payload: {} },
          { entity_type: 'timeline_event', action: 'update', name: '事件乙', payload: {} },
        ],
      };
    }
    if (path.endsWith('/confirm') || path.endsWith('/cancel')) {
      const id = path.split('/').slice(-2)[0];
      batches = batches.filter((x) => x.batch_id !== id);
      return { batch_id: id, created: 1, updated: 0, deleted: 1 };
    }
    if (path.startsWith('/api/v1/projects/p1/chapters')) return { items: [], total: 0, offset: 0, limit: 50 };
    if (path === '/api/v1/projects/p1/volumes') return { items: [] };
    if (path.startsWith('/api/v1/projects/p1/extractions/runs')) return { items: [] };
    return { ok: true };
  });
}

/** 挂载入口（+ App 层的对话框，供「查看」断言结果视图） */
function renderEntry(withDialog = false) {
  return render(
    <>
      <AIExtractEntry cat="characters" />
      {withDialog ? <AIExtractDialog /> : null}
    </>,
  );
}

beforeEach(() => {
  cleanup();
  apiFetchMock.mockReset();
  installMock();
  batches = [];
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  useToastStore.setState({ toasts: [] });
  useProjectStore.setState({ projects: [projectP1], currentProjectId: 'p1', loading: false, error: null });
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
});

describe('「待确认提取（N）」入口（#1582）', () => {
  it('契约1：未选项目 → 入口与「AI 提取」都不渲染', async () => {
    useProjectStore.setState({ currentProjectId: null });
    renderEntry();
    await waitFor(() => expect(screen.queryByTestId('extract-entry-lib')).not.toBeInTheDocument());
    expect(screen.queryByTestId('extract-pending-entry')).not.toBeInTheDocument();
  });

  it('契约2：无待确认批次（N=0）→ 入口不渲染，但「AI 提取」照常', async () => {
    renderEntry();
    await waitFor(() => expect(screen.getByTestId('extract-entry-lib')).toBeInTheDocument());
    await waitFor(() =>
      expect(apiFetchMock.mock.calls.some((c) => c[0] === '/api/v1/projects/p1/extractions/staging')).toBe(
        true,
      ),
    );
    expect(screen.queryByTestId('extract-pending-entry')).not.toBeInTheDocument();
  });

  it('契约3（N 口径）：2 个批次 → 入口渲染且角标 = 2（批次数，非 18+3=21 条目数）', async () => {
    batches = [batch('ext-2', 'timeline', 18), batch('ext-1', 'character', 3)];
    renderEntry();

    const entry = await screen.findByTestId('extract-pending-entry');
    expect(entry).toHaveTextContent('待确认提取');
    expect(entry).toHaveTextContent('2');
    expect(entry).not.toHaveTextContent('21');
  });

  it('契约4（跨进程存活）：store 清空（= 重开 App）+ 重新挂载 → 仍能列出该批次', async () => {
    batches = [batch('ext-2', 'timeline', 18)];
    const first = renderEntry();
    await screen.findByTestId('extract-pending-entry');
    first.unmount();

    // 进程内状态全丢（等价「关掉 App 后回来」）——批次只在服务端
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
    const user = userEvent.setup();
    renderEntry();
    await user.click(await screen.findByTestId('extract-pending-entry'));

    const panel = await screen.findByTestId('extract-pending-panel');
    const rows = within(panel).getAllByTestId('extract-pending-item');
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent('时间线');
    expect(rows[0]).toHaveTextContent('18');
  });

  it('契约5（N 同步下降）：面板「确认落库」→ POST confirm → 重拉 → 角标 2 → 1', async () => {
    batches = [batch('ext-2', 'timeline', 18), batch('ext-1', 'character', 3)];
    const user = userEvent.setup();
    renderEntry();
    await user.click(await screen.findByTestId('extract-pending-entry'));

    const panel = await screen.findByTestId('extract-pending-panel');
    await user.click(within(panel).getAllByTestId('extract-pending-confirm')[0]);

    await waitFor(() =>
      expect(
        apiFetchMock.mock.calls.some(
          (c) => c[0] === '/api/v1/projects/p1/extractions/staging/ext-2/confirm',
        ),
      ).toBe(true),
    );
    await waitFor(() => expect(useExtractStore.getState().pending).toHaveLength(1));
    expect(screen.getByTestId('extract-pending-entry')).toHaveTextContent('1');
  });

  it('契约6（N 同步下降）：面板「取消」→ POST cancel → 重拉 → 角标下降', async () => {
    batches = [batch('ext-2'), batch('ext-1')];
    const user = userEvent.setup();
    renderEntry();
    await user.click(await screen.findByTestId('extract-pending-entry'));

    const panel = await screen.findByTestId('extract-pending-panel');
    await user.click(within(panel).getAllByTestId('extract-pending-cancel')[0]);

    await waitFor(() =>
      expect(
        apiFetchMock.mock.calls.some(
          (c) => c[0] === '/api/v1/projects/p1/extractions/staging/ext-2/cancel',
        ),
      ).toBe(true),
    );
    // 取消 = 零物化：不得调 confirm
    expect(apiFetchMock.mock.calls.some((c) => String(c[0]).endsWith('/confirm'))).toBe(false);
    await waitFor(() => expect(useExtractStore.getState().pending).toHaveLength(1));
  });

  it('契约7（查看）：读单批（既有端点）→ 按 action 拆新增/更新 → 打开结果视图', async () => {
    batches = [batch('ext-2')];
    const user = userEvent.setup();
    renderEntry(true);
    await user.click(await screen.findByTestId('extract-pending-entry'));

    const panel = await screen.findByTestId('extract-pending-panel');
    await user.click(within(panel).getAllByTestId('extract-pending-view')[0]);

    await waitFor(() =>
      expect(
        apiFetchMock.mock.calls.some((c) => c[0] === '/api/v1/projects/p1/extractions/staging/ext-2'),
      ).toBe(true),
    );
    const result = await screen.findByTestId('ai-extract-result');
    expect(within(within(result).getByTestId('ai-extract-created')).getAllByTestId('ai-extract-created-item')).toHaveLength(1);
    expect(within(within(result).getByTestId('ai-extract-updated')).getAllByTestId('ai-extract-updated-item')).toHaveLength(1);
  });
});
