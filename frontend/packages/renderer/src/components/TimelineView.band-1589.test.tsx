/**
 * #1589 / ADR-068：刻度标签**历法换算显示**（前端只拼文案，不做日历数学）。
 *
 * 【契约（GREEN 必须提供）】
 * - 事件带 `calendar_date`（后端换算结果）→ 刻度标签显示 `X 年 Y 月 Z 日` 形态；
 * - **粒度按本页相邻刻度自适应**：取「相邻标签互不相同」的**最粗**粒度（y → ym → ymd）；
 * - `cycle` + `era_cycle_label` → 前插「N 劫」；`epoch_label` → 「开元 9 年」；
 * - **无 `calendar_date` ⇒ 回落「N 日」整数**（亚日小数同日归整，不再出现 `0.79 日`）。
 *
 * 【RED 预期】`timeline-calendar-label` 不存在 / 标签仍是 `2920 日` → 本文件 FAIL。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TimelineView, type TimelineEventDTO } from './TimelineView';
import { formatCalendarDate, formatTickLabel, pickGranularity } from './timeline-calendar-label';
import { apiFetch } from '../api/client';
import { useThemeStore } from '../stores/theme';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const QY = '示例历';

/** 带后端换算结果的事件（`calendar_date` 由 API 下发，前端不做日历数学） */
function ev(id: string, calendarDate: Record<string, unknown> | null, timeValue: number) {
  return {
    id,
    title: `事件 ${id}`,
    era: QY,
    era_value: timeValue,
    era_scale: 1,
    time_value: timeValue,
    time_unit: '日',
    narrative_position: Number(id.replace(/[^0-9]/g, '')) || 1,
    calendar_date: calendarDate,
  } as unknown as TimelineEventDTO;
}

async function renderWorld(events: TimelineEventDTO[]) {
  render(
    <TimelineView
      projectId="p1"
      eventTimeline={events}
      narrativeOrder={events}
      chapterTitles={{}}
      chapterOrder={[]}
    />,
  );
  await userEvent.setup().click(screen.getByTestId('tl-view-world'));
}

const tickLabels = (): string[] =>
  screen.queryAllByTestId(/^tl-band-tick-/).map((n) => n.textContent ?? '');

beforeEach(() => {
  apiFetchMock.mockReset();
  apiFetchMock.mockImplementation(async () => ({ checked: 0, skipped: 0, consistent: true, conflicts: [] }));
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('#1589 历法标签（纯函数）', () => {
  it('P1 粒度自适应：同一年内相邻刻度互不相同 → ym；跨年 → y；同年同月 → ymd', () => {
    const a = { year: 9, month: 2, day: 9 };
    const b = { year: 9, month: 4, day: 20 };
    const c = { year: 10, month: 1, day: 1 };
    expect(pickGranularity([a, c])).toBe('y');
    expect(pickGranularity([a, b])).toBe('ym');
    expect(pickGranularity([a, { ...a, day: 17 }])).toBe('ymd');
  });

  it('P2 文案：年月日 / 年号 / 纪元周期前插（纯数据，不硬编码）', () => {
    expect(formatCalendarDate({ year: 9, month: 2, day: 9 }, 'ymd')).toBe('9 年 2 月 9 日');
    expect(formatCalendarDate({ year: 9, month: 2, day: 9 }, 'ym')).toBe('9 年 2 月');
    expect(formatCalendarDate({ year: 9, month: 2, day: 9 }, 'y')).toBe('9 年');
    expect(formatCalendarDate({ year: 9, month: 2, day: 9, epoch_label: '开元' }, 'y')).toBe('开元 9 年');
    expect(
      formatCalendarDate({ year: 250, month: 1, day: 1, cycle: 3, era_cycle_label: '劫' }, 'y'),
    ).toBe('3 劫 250 年');
  });

  it('P3 无历法回落「N 日」整数（同日归整，不出现亚日小数）', () => {
    expect(formatTickLabel({ value: 0.79, unit: '日', calendarDate: null }, 'ymd')).toBe('0 日');
    expect(formatTickLabel({ value: 3.27, unit: '日', calendarDate: null }, 'ymd')).toBe('3 日');
    expect(formatTickLabel({ value: 2920, unit: '日', calendarDate: null }, 'ymd')).toBe('2920 日');
    expect(formatTickLabel({ value: 12, unit: '', calendarDate: null }, 'ymd')).toBe('12');
  });
});

describe('#1589 刻度带标签（组件级）', () => {
  it('C1 配历法的轴：标签按换算结果显示，且粒度随本页刻度间距变化', async () => {
    const dates = [
      { year: 9, month: 2, day: 9 },
      { year: 9, month: 4, day: 20 },
    ];
    await renderWorld([ev('e1', dates[0], 2920), ev('e2', dates[1], 3000)]);

    expect(tickLabels()).toContain('9 年 2 月');
    expect(tickLabels()).toContain('9 年 4 月');
  });

  it('C2 未配历法的轴：回落「N 日」整数（N1/N8 零回归；`0.79 日` 不再出现）', async () => {
    await renderWorld([ev('e1', null, 0.79), ev('e2', null, 3.27), ev('e3', null, 2920)]);

    expect(tickLabels()).toContain('2920 日');
    expect(tickLabels().some((l) => l.includes('0.79'))).toBe(false);
    expect(tickLabels()).toContain('0 日');
  });

  it('C3 双轴各按自己历法：同一「日数」在两轴得出不同年（N6 / D1）', async () => {
    const qy = ev('e1', { year: 9, month: 2, day: 9 }, 2920);
    const xj = { ...ev('x1', { year: 4, month: 1, day: 1 }, 2920), era: '示例仙历' };
    await renderWorld([qy, xj] as TimelineEventDTO[]);
    // 轴族 ≥ 2 → 默认只勾选主力轴；勾上第二条轴才渲染它的刻度（#1353 既有语义）
    await userEvent.setup().click(screen.getByTestId('tl-axis-chip-示例仙历'));

    expect(tickLabels()).toContain('9 年');
    expect(tickLabels()).toContain('4 年');
  });

  it('C4 纪元周期生效：标签前插「N 劫」（N5；纪元名来自轴数据，前端不硬编码）', async () => {
    await renderWorld([
      ev('e1', { year: 250, month: 1, day: 1, cycle: 3, era_cycle_label: '劫' }, 89700),
    ]);

    expect(tickLabels()).toContain('3 劫 250 年');
  });
});
