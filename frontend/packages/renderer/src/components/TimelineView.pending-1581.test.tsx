/**
 * #1581 世界序「未知区退役 → 待确认区」—— TimelineView 契约（RED）。
 *
 * 【spec 依据】specs/f19-gui/timeline.md §2（待确认区行）/ §3 N17；specs/f12-timeline/spec.md §2.9
 *
 * 【契约（GREEN 必须提供）】
 * - **零未知**：世界序**不渲染** `tl-band-unknown` / `tl-band-unknown-head` / `tl-band-unknown-list`
 * - **待确认区**（`tl-pend`）渲染于刻度带下方；条数 = 正式表未定事件 ∪ 暂存项（`GET .../extractions/staging`）
 * - 每行：原文时间（`tl-pend-raw-<key>`）+ 事件 + 来源 + 未定原因（`tl-pend-reason-<key>`）
 *   + 时间输入（`tl-pend-time-<key>`）+ 确认（`tl-pend-confirm-<key>`，**未填时间时 disabled**）
 *   + 丢弃（`tl-pend-discard-<key>`）
 * - 存量未定事件：确认 → `PATCH /api/v1/timeline/events/{id}`（带 time_value/time_unit）；
 *   丢弃 → `DELETE /api/v1/timeline/events/{id}`
 * - 暂存项：确认 → `POST .../extractions/staging/{batch_id}/items/{item_id}/confirm`；
 *   丢弃 → `DELETE .../extractions/staging/{batch_id}/items/{item_id}`
 *
 * 【RED 预期】`tl-pend` 不存在、`tl-band-unknown*` 仍渲染 → FAIL。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TimelineView, type TimelineEventDTO } from './TimelineView';
import { apiFetch } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

function events(): TimelineEventDTO[] {
  return [
    { id: 'e1', title: '已定事件甲', time_value: 10, time_unit: '日', narrative_position: 1 },
    { id: 'e2', title: '已定事件乙', time_value: 20, time_unit: '日', narrative_position: 2 },
    // 存量未定（time_value 为空）—— 应落待确认区、不进刻度带
    {
      id: 'e3',
      title: '未定事件甲',
      time_value: null,
      time_unit: '',
      time_display: '那年冬天',
      narrative_position: 3,
      source_chapter_id: 'c1',
    },
    {
      id: 'e4',
      title: '未定事件乙',
      time_value: null,
      time_unit: '',
      time_display: '',
      narrative_position: 4,
      source_chapter_id: null,
    },
  ];
}

/** 默认 apiFetch 桩：暂存批次列表为空（未定来源全部来自正式表） */
function stubEmptyStaging() {
  apiFetchMock.mockImplementation(async (url: string) => {
    if (String(url).endsWith('/extractions/staging')) return { batches: [] };
    return {};
  });
}

async function renderWorld() {
  render(
    <TimelineView
      projectId="p1"
      eventTimeline={events()}
      narrativeOrder={[]}
      chapterTitles={{ c1: '第一章' }}
    />,
  );
  await userEvent.click(screen.getByTestId('tl-view-world'));
}

describe('#1581 零未知 + 待确认区', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
    stubEmptyStaging();
  });

  it('世界序不渲染任何「未知」区块（零未知）', async () => {
    await renderWorld();

    expect(screen.queryByTestId('tl-band-unknown')).toBeNull();
    expect(screen.queryByTestId('tl-band-unknown-head')).toBeNull();
    expect(screen.queryByTestId('tl-band-unknown-list')).toBeNull();
  });

  it('待确认区渲染于刻度带下方，条数 = 正式表未定事件', async () => {
    await renderWorld();

    expect(await screen.findByTestId('tl-pend')).toBeTruthy();
    expect(screen.getByTestId('tl-pend-count').textContent).toContain('2');
    expect(screen.getByTestId('tl-pend-raw-ev-e3').textContent).toContain('那年冬天');
    expect(screen.getByTestId('tl-pend-reason-ev-e3').textContent?.trim()).not.toBe('');
  });

  it('未填时间时「确认」禁用；补时间后可点并 PATCH 正式事件', async () => {
    await renderWorld();

    const confirm = await screen.findByTestId('tl-pend-confirm-ev-e3');
    expect(confirm).toBeDisabled();

    await userEvent.type(screen.getByTestId('tl-pend-time-ev-e3'), '12');
    expect(screen.getByTestId('tl-pend-confirm-ev-e3')).toBeEnabled();

    await userEvent.click(screen.getByTestId('tl-pend-confirm-ev-e3'));

    await waitFor(() => {
      const call = apiFetchMock.mock.calls.find(
        ([url, init]) => String(url).includes('/api/v1/timeline/events/e3') && init?.method === 'PATCH',
      );
      expect(call).toBeTruthy();
      expect((call![1]!.body as Record<string, unknown>).time_value).toBe(12);
    });
  });

  it('丢弃 → DELETE 该正式事件，正式表零新增', async () => {
    await renderWorld();

    await userEvent.click(await screen.findByTestId('tl-pend-discard-ev-e4'));

    await waitFor(() => {
      const call = apiFetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).includes('/api/v1/timeline/events/e4') && init?.method === 'DELETE',
      );
      expect(call).toBeTruthy();
    });
  });

  it('暂存项出现在待确认区；确认走条目级端点', async () => {
    apiFetchMock.mockImplementation(async (url: string) => {
      const u = String(url);
      if (u.endsWith('/extractions/staging')) {
        return { batches: [{ batch_id: 'ext-1', type: 'timeline', created_at: 'x', item_count: 1 }] };
      }
      if (u.includes('/extractions/staging/ext-1') && !u.includes('/items/')) {
        return {
          batch_id: 'ext-1',
          items: [
            {
              id: 7,
              entity_type: 'timeline_event',
              action: 'create',
              name: '暂存未定',
              payload: {
                title: '暂存未定',
                time_display: '过了两天',
                time_value: null,
                time_unit: '',
                parse_reason: '相对时间，需作者锚定',
              },
            },
          ],
        };
      }
      return {};
    });

    await renderWorld();

    expect(await screen.findByTestId('tl-pend-row-st-7')).toBeTruthy();
    expect(screen.getByTestId('tl-pend-reason-st-7').textContent).toContain('相对时间');

    await userEvent.type(screen.getByTestId('tl-pend-time-st-7'), '5');
    await userEvent.click(screen.getByTestId('tl-pend-confirm-st-7'));

    await waitFor(() => {
      const call = apiFetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).includes('/extractions/staging/ext-1/items/7/confirm') &&
          init?.method === 'POST',
      );
      expect(call).toBeTruthy();
    });
  });
});
