/**
 * #1353 世界序「纪元轴族 + 轴选择器」—— 组件级契约（TimelineView）。
 * 【#1541 更新】世界序渲染形态由「上下堆叠泳道卡片」（#1467）改为「单块多竖轴刻度带」：
 *   本文件断言轴选择器 / 单轴 1 竖轴 / 事件不丢；刻度带本体契约见 `TimelineView.band-1541.test.tsx`。
 *
 * 【spec 依据】specs/f12-timeline/spec.md §2.1（三列）+ §2.8（E1/E2 承载 + 默认轴 E5）+ ADR-065
 *            + specs/f19-gui/timeline.md §1.1（世界序刻度带）/ §2 轴选择器行 / §3 N11-N13 / N15。
 *
 * 【契约（GREEN 必须提供）】
 * - 轴选择器**只属世界序**，且**仅当轴族 ≥ 2 条**时出现（`tl-axis-picker`）
 * - chips：`tl-axis-chip-<key>`（key = 轴名 或默认轴哨兵 `__none__`），`aria-pressed` = 勾选态；
 *   **默认只勾选主力轴**（事件数最多的轴）
 * - 勾选后：每条选中历 = 刻度带里**一条竖轴**（`tl-band-spine-<key>` + `tl-band-head-<key>`）
 * - 至少保留一条轴（取消最后一条 → 无效）
 * - **单轴**（轴族 == 1 条默认轴）：无选择器，但仍是 **1 条竖轴刻度带**（#1541 取代 v1.2 平铺）
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TimelineView, type TimelineEventDTO } from './TimelineView';
import { apiFetch } from '../api/client';
import { useThemeStore } from '../stores/theme';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const QY = '示例历';
const XJ = '示例仙历';
const DEFAULT_KEY = '__none__';

/** 事件（世界序顺序按数组序传入）：示例历×2 / 默认轴×1 / 示例仙历×1 */
const e1: TimelineEventDTO = {
  id: 'e1', title: '事件甲', time_value: 3, time_unit: '年', time_display: '示例历 3 年',
  narrative_position: 1, source_chapter_id: 'c11', era: QY, era_value: 3,
};
const e4: TimelineEventDTO = {
  id: 'e4', title: '事件丁（无纪元）', time_value: 1, time_unit: '年', time_display: '示例历 1 年',
  narrative_position: 2, source_chapter_id: null,
};
const e3: TimelineEventDTO = {
  id: 'e3', title: '事件丙', time_value: 1024, time_unit: '年', time_display: '',
  narrative_position: 3, source_chapter_id: null, era: XJ, era_value: 1024,
};
const e2: TimelineEventDTO = {
  id: 'e2', title: '事件乙', time_value: 9, time_unit: '年', time_display: '示例历 9 年',
  narrative_position: 4, source_chapter_id: 'c12', era: QY, era_value: 9,
};

const ERA_EVENTS = [e1, e4, e3, e2];

/** 无纪元数据（轴族只有默认轴）—— 单轴刻度带用 */
const PLAIN_EVENTS: TimelineEventDTO[] = [
  { id: 'p1', title: '无纪元甲', time_value: 10, time_unit: '年', time_display: '10 年', narrative_position: 1 },
  { id: 'p2', title: '无纪元乙', time_value: 20, time_unit: '年', time_display: '20 年', narrative_position: 2 },
];

function renderView(events: TimelineEventDTO[] = ERA_EVENTS) {
  return render(
    <TimelineView
      projectId="p1"
      eventTimeline={events}
      narrativeOrder={events}
      chapterTitles={{ c11: '第十一章 事件乙', c12: '第十二章 夜访地点乙' }}
      chapterOrder={['c11', 'c12']}
    />,
  );
}

async function switchToWorld() {
  await userEvent.setup().click(screen.getByTestId('tl-view-world'));
}

function nodeIds(): string[] {
  return screen
    .getAllByTestId(/^tl-axis-node-/)
    .map((el) => el.getAttribute('data-testid')!.replace('tl-axis-node-', ''));
}

function spineIds(): string[] {
  return screen
    .queryAllByTestId(/^tl-band-spine-/)
    .map((el) => el.getAttribute('data-testid')!.replace('tl-band-spine-', ''));
}

beforeEach(() => {
  apiFetchMock.mockReset();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('#1353 轴选择器（世界序专属；≥2 条轴才出现）', () => {
  it('T1 叙事序不渲染选择器与刻度带（轴选择器只属世界序）', () => {
    renderView();

    expect(screen.queryByTestId('tl-axis-picker')).toBeNull();
    expect(screen.queryByTestId('tl-band')).toBeNull();
    expect(screen.queryAllByTestId(/^tl-band-spine-/)).toHaveLength(0);
  });

  it('T2 切世界序 → 选择器出现 + 3 chips，默认只勾选主力轴（示例历）→ 1 条竖轴', async () => {
    renderView();
    await switchToWorld();

    expect(screen.getByTestId('tl-axis-picker')).toBeTruthy();
    expect(screen.getAllByTestId(/^tl-axis-chip-/)).toHaveLength(3);
    expect(screen.getByTestId(`tl-axis-chip-${QY}`).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByTestId(`tl-axis-chip-${DEFAULT_KEY}`).getAttribute('aria-pressed')).toBe('false');
    expect(screen.getByTestId(`tl-axis-chip-${XJ}`).getAttribute('aria-pressed')).toBe('false');
    expect(spineIds()).toEqual([QY]);
    expect(screen.queryByTestId(`tl-band-spine-${XJ}`)).toBeNull();
  });

  it('T3 勾选第二条轴 → 两条竖轴（各历事件落各自轴，不重复）', async () => {
    renderView();
    await switchToWorld();

    await userEvent.setup().click(screen.getByTestId(`tl-axis-chip-${XJ}`));

    expect(spineIds()).toEqual([QY, XJ]);
    expect(nodeIds().sort()).toEqual(['e1', 'e2', 'e3']);
  });

  it('T4 至少保留一条轴：取消唯一勾选的轴 → 保持勾选（不出现空视图）', async () => {
    renderView();
    await switchToWorld();

    await userEvent.setup().click(screen.getByTestId(`tl-axis-chip-${QY}`));

    expect(screen.getByTestId(`tl-axis-chip-${QY}`).getAttribute('aria-pressed')).toBe('true');
    expect(spineIds()).toEqual([QY]);
  });

  it('T5 刻度标签 = 本地时间值（回退链不含轴名）；事件行不渲染 tl-axis-main', async () => {
    renderView();
    await switchToWorld();
    await userEvent.setup().click(screen.getByTestId(`tl-axis-chip-${XJ}`));

    expect(screen.getByTestId(`tl-band-tick-${XJ}-0`).textContent).toContain('1024');
    // 反向断言：旧形态「轴名 + 轴内值」不再出现；事件行无 tl-axis-main
    expect(screen.queryAllByTestId(/^tl-axis-main-/)).toHaveLength(0);
  });

  it('T6 默认轴（R6-4）可被选中并渲染为一条竖轴 —— 事件不丢失', async () => {
    renderView();
    await switchToWorld();

    await userEvent.setup().click(screen.getByTestId(`tl-axis-chip-${DEFAULT_KEY}`));

    expect(spineIds()).toEqual([QY, DEFAULT_KEY]);
    expect(screen.getByTestId('tl-axis-node-e4')).toBeInTheDocument();
  });
});

describe('#1541 单轴（无纪元数据）= 1 条竖轴刻度带（取代 v1.2 平铺）', () => {
  it('T7 轴族只有默认轴 → 无选择器、1 条竖轴、事件各渲染一次', async () => {
    renderView(PLAIN_EVENTS);
    await switchToWorld();

    expect(screen.queryByTestId('tl-axis-picker')).toBeNull();
    expect(spineIds()).toEqual([DEFAULT_KEY]);
    expect(screen.getByTestId('tl-axis')).toBeTruthy();
    expect(nodeIds()).toEqual(['p1', 'p2']);
  });

  it('T8 每个事件恰好渲染一次（选中全部轴时无重复节点）', async () => {
    renderView();
    await switchToWorld();
    const user = userEvent.setup();
    await user.click(screen.getByTestId(`tl-axis-chip-${DEFAULT_KEY}`));
    await user.click(screen.getByTestId(`tl-axis-chip-${XJ}`));

    const ids = nodeIds();
    expect(ids).toHaveLength(ERA_EVENTS.length);
    expect(new Set(ids).size).toBe(ERA_EVENTS.length);
  });
});

describe('#1541 取代 #1467 泳道形态（反向断言）', () => {
  it('T9 世界序不再渲染 tl-lane-* / tl-timenode-*（上下堆叠卡片废止）', async () => {
    renderView();
    await switchToWorld();
    await userEvent.setup().click(screen.getByTestId(`tl-axis-chip-${XJ}`));

    expect(screen.queryAllByTestId(/^tl-lane-/)).toHaveLength(0);
    expect(screen.queryAllByTestId(/^tl-timenode-/)).toHaveLength(0);
    expect(screen.getByTestId('tl-band')).toBeInTheDocument();
  });
});
