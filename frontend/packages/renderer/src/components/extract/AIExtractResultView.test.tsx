/**
 * #1532 / #1546「AI 提取」结果视图 + 最小化 RED 契约。
 *
 * 【契约（父侧定稿）】
 * - 提交一律带 `stage: true`（两段式：产物只进暂存区，确认前正式表零变更）
 * - 成功后对话框切**结果视图**：
 *   `ai-extract-result` 容器 + `ai-extract-created`（`ai-extract-created-item` × N）
 *   + `ai-extract-updated`（`ai-extract-updated-item` × M）
 * - 「确认落库」(`ai-extract-confirm`) → `POST /api/v1/projects/{pid}/extractions/staging/{batch}/confirm`
 *   → 调 onClose + ok toast
 * - 「取消」(`ai-extract-cancel`) → `POST .../staging/{batch}/cancel` → 调 onClose
 * - 「最小化」(`ai-extract-min`) → 对话框收起 + `ai-extract-float` 浮窗；点浮窗 → 恢复对话框
 *
 * 【RED 预期失败形态】结果视图 testid 不存在（当前仅 toast）→ element-missing。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AIExtractDialog } from './AIExtractDialog';
import { apiFetch } from '../../api/client';
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

beforeEach(() => {
  apiFetchMock.mockReset();
  useToastStore.setState({ toasts: [] });
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path.startsWith('/api/v1/projects/p1/chapters')) return { ...CHAPTERS_RESP };
    if (path === '/api/v1/projects/p1/volumes') return { ...VOLUMES_RESP };
    if (path.startsWith('/api/v1/projects/p1/extractions/runs')) return { ...RUNS_RESP };
    if (path === '/api/v1/extract' && init?.method === 'POST') return { ...STAGE_ENVELOPE };
    return { ok: true };
  });
});

async function runExtract(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('radio', { name: '角色' }));
  await user.click(await screen.findByRole('radio', { name: '全文' }));
  await user.click(await screen.findByTestId('ai-extract-run'));
}

function renderDialog(onClose = () => {}) {
  return render(<AIExtractDialog open onClose={onClose} projectId="p1" />);
}

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
    const onClose = vi.fn();
    renderDialog(onClose);
    await runExtract(user);
    await user.click(await screen.findByTestId('ai-extract-confirm'));

    await waitFor(() => {
      const call = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/projects/p1/extractions/staging/ext-1/confirm',
      );
      expect(call).toBeDefined();
    });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('契约4（取消）：调 cancel 端点 + 关框（零确认调用）', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderDialog(onClose);
    await runExtract(user);
    await user.click(await screen.findByTestId('ai-extract-cancel'));

    await waitFor(() => {
      const call = apiFetchMock.mock.calls.find(
        (c) => c[0] === '/api/v1/projects/p1/extractions/staging/ext-1/cancel',
      );
      expect(call).toBeDefined();
    });
    expect(
      apiFetchMock.mock.calls.some((c) => String(c[0]).endsWith('/confirm')),
    ).toBe(false);
    await waitFor(() => expect(onClose).toHaveBeenCalled());
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
    ] as const) {
      const key = `extract.${k}`;
      expect(extractZh[key], `${key} zh`).toBeTruthy();
      expect(extractEn[key], `${key} en`).toBeTruthy();
    }
  });
});
