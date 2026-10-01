/**
 * #1353 世界序「纪元轴族 + 轴选择器」—— 组件级契约（TimelineView）。
 *
 * 【spec 依据】specs/f12-timeline/spec.md §2.8（承载键 + 默认轴 E5）
 *            + specs/f19-gui/timeline.md §1.1（世界序 = 纪元轴族）/ §2 轴选择器行 / §3 N11-N13。
 *
 * 【契约（GREEN 必须提供）】
 * - 轴选择器**只属世界序**，且**仅当轴族 ≥ 2 条**时出现（`tl-axis-picker`）
 * - chips：`tl-axis-chip-<key>`（key = 轴名 或默认轴哨兵 `__none__`），
 *   `aria-pressed` 表示勾选态；**默认只勾选主力轴**（事件数最多的轴）
 * - 勾选后：世界序按选中轴**分组渲染泳道** `tl-lane-<key>`（轴内按 era_value 升序、
 *   缺失排末尾），泳道头含轴名 + 「N 个事件」；至少保留一条轴（取消最后一条 → 无效）
 * - 标签回退链：`time_display` 原样 → （无 time_display 时）`轴名 + 轴内值` → 「未知」
 * - **反例守护（R6-4 / spec v1.2 行为零变化）**：无纪元数据的项目（轴族 == 1 条默认轴）
 *   世界序**无选择器、无泳道**，事件按传入顺序平铺，且每个事件恰好渲染一次
 *
 * 【RED 预期】选择器 / 泳道 testid 不存在 → element-missing FAIL；
 * 零 SyntaxError / ReferenceError / TypeError。
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

const QY = '青元历';
const XJ = '仙历';
const DEFAULT_KEY = '__none__';

/** 事件（世界序顺序按数组序传入）：青元历×2 / 默认轴×1 / 仙历×1 */
const e1: TimelineEventDTO = {
  id: 'e1', title: '事件甲', time_value: 3, time_unit: '年', time_display: '青元历 3 年',
  narrative_position: 1, source_chapter_id: 'c11', extra: { era: QY, era_value: 3 },
};
const e4: TimelineEventDTO = {
  id: 'e4', title: '事件丁（无纪元）', time_value: 1, time_unit: '年', time_display: '青元历 1 年',
  narrative_position: 2, source_chapter_id: null, extra: {},
};
const e3: TimelineEventDTO = {
  id: 'e3', title: '事件丙', time_value: 1024, time_unit: '年', time_display: '',
  narrative_position: 3, source_chapter_id: null, extra: { era: XJ, era_value: 1024 },
};
const e2: TimelineEventDTO = {
  id: 'e2', title: '事件乙', time_value: 9, time_unit: '年', time_display: '青元历 9 年',
  narrative_position: 4, source_chapter_id: 'c12', extra: { era: QY, era_value: 9 },
};

const ERA_EVENTS = [e1, e4, e3, e2];

/** 无纪元数据（轴族只有默认轴）—— 反例守护用 */
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
      chapterTitles={{ c11: '第十一章 剑心为何物', c12: '第十二章 夜访剑冢' }}
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

function laneIds(key: string): string[] {
  const lane = screen.getByTestId(`tl-lane-${key}`);
  return Array.from(lane.querySelectorAll('[data-testid^="tl-axis-node-"]')).map((n) =>
    n.getAttribute('data-testid')!.replace('tl-axis-node-', ''),
  );
}

beforeEach(() => {
  apiFetchMock.mockReset();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('#1353 轴选择器（世界序专属；≥2 条轴才出现）', () => {
  it('T1 叙事序不渲染选择器与泳道（轴选择器只属世界序）', () => {
    renderView();

    expect(screen.queryByTestId('tl-axis-picker')).toBeNull();
    expect(screen.queryAllByTestId(/^tl-lane-/)).toHaveLength(0);
  });

  it('T2 切世界序 → 选择器出现 + 3 chips，默认只勾选主力轴（青元历）', async () => {
    renderView();
    await switchToWorld();

    expect(screen.getByTestId('tl-axis-picker')).toBeTruthy();
    expect(screen.getAllByTestId(/^tl-axis-chip-/)).toHaveLength(3);
    // 默认只显示主角/主力轴（事件数最多 = 青元历）
    expect(screen.getByTestId(`tl-axis-chip-${QY}`).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByTestId(`tl-axis-chip-${DEFAULT_KEY}`).getAttribute('aria-pressed')).toBe('false');
    expect(screen.getByTestId(`tl-axis-chip-${XJ}`).getAttribute('aria-pressed')).toBe('false');
    // 只渲染选中轴的泳道；轴内按 era_value 升序
    expect(screen.getAllByTestId(/^tl-lane-/)).toHaveLength(1);
    expect(laneIds(QY)).toEqual(['e1', 'e2']);
    expect(screen.queryByTestId(`tl-lane-${XJ}`)).toBeNull();
  });

  it('T3 勾选第二条轴 → 多泳道分组渲染（各轴事件落各自泳道，不重复）', async () => {
    renderView();
    await switchToWorld();

    await userEvent.setup().click(screen.getByTestId(`tl-axis-chip-${XJ}`));

    expect(screen.getAllByTestId(/^tl-lane-/)).toHaveLength(2);
    expect(laneIds(QY)).toEqual(['e1', 'e2']);
    expect(laneIds(XJ)).toEqual(['e3']);
    expect(nodeIds().sort()).toEqual(['e1', 'e2', 'e3']);
  });

  it('T4 至少保留一条轴：取消唯一勾选的轴 → 保持勾选（不出现空视图）', async () => {
    renderView();
    await switchToWorld();

    await userEvent.setup().click(screen.getByTestId(`tl-axis-chip-${QY}`));

    expect(screen.getByTestId(`tl-axis-chip-${QY}`).getAttribute('aria-pressed')).toBe('true');
    expect(laneIds(QY)).toEqual(['e1', 'e2']);
  });

  it('T5 标签回退：无 time_display 的纪元事件 → 「轴名 + 轴内值」', async () => {
    renderView();
    await switchToWorld();
    await userEvent.setup().click(screen.getByTestId(`tl-axis-chip-${XJ}`));

    expect(screen.getByTestId('tl-axis-main-e3').textContent?.trim()).toBe(`${XJ} 1024`);
  });

  it('T6 默认轴（R6-4）可被选中并渲染为一条泳道 —— 事件不丢失', async () => {
    renderView();
    await switchToWorld();

    await userEvent.setup().click(screen.getByTestId(`tl-axis-chip-${DEFAULT_KEY}`));

    expect(laneIds(DEFAULT_KEY)).toEqual(['e4']);
  });
});

describe('#1353 反例守护：无纪元数据（单轴）行为零变化', () => {
  it('T7 轴族只有默认轴 → 无选择器、无泳道、事件平铺且各渲染一次', async () => {
    renderView(PLAIN_EVENTS);
    await switchToWorld();

    expect(screen.queryByTestId('tl-axis-picker')).toBeNull();
    expect(screen.queryAllByTestId(/^tl-lane-/)).toHaveLength(0);
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
