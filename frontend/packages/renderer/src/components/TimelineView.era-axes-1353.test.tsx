/**
 * #1353 世界序「纪元轴族 + 轴选择器」—— 组件级契约（TimelineView）。
 *
 * 【spec 依据】specs/f12-timeline/spec.md §2.1（三列）+ §2.8（E1/E2 承载 + 默认轴 E5）+ ADR-065
 *            + specs/f19-gui/timeline.md §1.1（世界序 = 纪元轴族）/ §2 轴选择器行 / §3 N11-N13。
 *
 * 【v1.4 变更（#1410）】事件 DTO 的纪元字段由 `extra.era` / `extra.era_value` 迁到
 * **顶层正式列** `era` / `era_value`（与后端同 PR，消除中间态漂移）。
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
import { render, screen, within } from '@testing-library/react';
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

  it('T2 切世界序 → 选择器出现 + 3 chips，默认只勾选主力轴（示例历）', async () => {
    renderView();
    await switchToWorld();

    expect(screen.getByTestId('tl-axis-picker')).toBeTruthy();
    expect(screen.getAllByTestId(/^tl-axis-chip-/)).toHaveLength(3);
    // 默认只显示主角/主力轴（事件数最多 = 示例历）
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

  it('T5 组内时间刻度：无 time_display 的纪元事件 → 「轴内值 + 单位」（#1467：不再重复轴名）', async () => {
    renderView();
    await switchToWorld();
    await userEvent.setup().click(screen.getByTestId(`tl-axis-chip-${XJ}`));

    // #1467：刻度文案落在时间节点行（= era_value + time_unit），事件行不再渲染 tl-axis-main
    expect(screen.getByTestId(`tl-tick-${XJ}-0`).textContent?.trim()).toBe('1024年');
    const lane = screen.getByTestId(`tl-lane-${XJ}`);
    // 反向断言：旧形态「轴名 + 轴内值」不再出现；事件行无 tl-axis-main
    expect(lane.textContent).not.toContain(`${XJ} 1024`);
    expect(within(lane).queryAllByTestId(/^tl-axis-main-/)).toHaveLength(0);
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

/* ══════════════════════════════════════════════════════════════════════════
 * #1467 组头只显示一次轴名 + 组内时间刻度树状分层
 *
 * 【spec 依据】specs/f19-gui/timeline.md §1.1（世界序·纪元轴族）/ §2 时间节点行 / §3 N12-N14。
 * 【需求（issue #1467 四项）】① 轴名做组头只出现一次；② 组内各行显示时间刻度（不再重复轴名）；
 * ③ 树状层级：同一年/月的刻度收进同一时间节点、事件行缩进一级；④ 既有行为不回归。
 * 【硬边界】不做跨轴换算（`era_scale` 不参与渲染；换算归 #1411）。
 *
 * 【testid 契约（GREEN 必须提供）】
 * - tl-lanehead-<key>        组头（轴名 + 「N 个事件」；轴名在该泳道内**只出现一次**）
 * - tl-timenode-<key>-<i>    时间节点（第 i 个刻度；同刻度事件收进同一节点）
 * - tl-tick-<key>-<i>        时间刻度文案（time_display → 「轴内值 + 单位」→ 「未知」）
 * - 事件行保持 tl-axis-node-<id>；泳道内**不再渲染 tl-axis-main-<id>**
 *
 * 【RED 预期】tl-timenode-* 不存在 / 轴名仍逐行重复 → G1-G5 FAIL；零 SyntaxError / TypeError。
 * ══════════════════════════════════════════════════════════════════════════ */
const EQ = '示例界 · 示例历';

/** 同轴 4 事件：17 / 217 / 217 / 1024（末条无 `time_display` → 回退「轴内值 + 单位」） */
const gA: TimelineEventDTO = {
  id: 'gA', title: '事件甲', era: EQ, era_value: 17, time_value: 17, time_unit: '年',
  time_display: '示例历 17 年', narrative_position: 1, source_chapter_id: 'c11',
};
const gB: TimelineEventDTO = {
  id: 'gB', title: '事件乙', era: EQ, era_value: 217, era_scale: 1, time_value: 217, time_unit: '年',
  time_display: '示例历 217 年', narrative_position: 2, source_chapter_id: 'c12',
};
const gC: TimelineEventDTO = {
  id: 'gC', title: '事件丙', era: EQ, era_value: 217, era_scale: 12, time_value: 217, time_unit: '年',
  time_display: '示例历 217 年', narrative_position: 3, source_chapter_id: 'c12',
};
const gD: TimelineEventDTO = {
  id: 'gD', title: '事件丁', era: EQ, era_value: 1024, time_value: 1024, time_unit: '年',
  time_display: '', narrative_position: 4, source_chapter_id: null,
};
const GROUP_EVENTS = [gA, gB, gC, gD];
/** 第二条纪元轴事件（守「轴选择器 ≥2 条才出现」） */
const gE: TimelineEventDTO = {
  id: 'gE', title: '事件戊', era: XJ, era_value: 3, time_value: 3, time_unit: '年',
  time_display: '示例仙历 3 年', narrative_position: 5, source_chapter_id: null,
};

function renderGrouped(events: TimelineEventDTO[] = GROUP_EVENTS) {
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

function idsWithin(testId: string): string[] {
  return within(screen.getByTestId(testId))
    .getAllByTestId(/^tl-axis-node-/)
    .map((el) => el.getAttribute('data-testid')!.replace('tl-axis-node-', ''));
}

describe('#1467 组头只显示一次轴名 + 组内时间刻度树状分层', () => {
  it('G1 轴名做组头只出现一次（组内事件行不再重复轴名）', async () => {
    renderGrouped();
    await switchToWorld();

    const lane = screen.getByTestId(`tl-lane-${EQ}`);
    // 反向断言：旧实现逐行重复轴名 → 出现次数 == 事件数；新形态 == 1
    expect((lane.textContent ?? '').split(EQ).length - 1).toBe(1);
    expect(screen.getByTestId(`tl-lanehead-${EQ}`)).toHaveTextContent(EQ);
    for (const id of ['gA', 'gB', 'gC', 'gD']) {
      expect(screen.getByTestId(`tl-axis-node-${id}`).textContent ?? '').not.toContain(EQ);
    }
  });

  it('G2 组内各行显示时间刻度（time_display 原样 / 回退「轴内值 + 单位」）；事件行不渲染 tl-axis-main', async () => {
    renderGrouped();
    await switchToWorld();

    expect(screen.getByTestId(`tl-tick-${EQ}-0`).textContent?.trim()).toBe('示例历 17 年');
    expect(screen.getByTestId(`tl-tick-${EQ}-1`).textContent?.trim()).toBe('示例历 217 年');
    expect(screen.getByTestId(`tl-tick-${EQ}-2`).textContent?.trim()).toBe('1024年');
    expect(within(screen.getByTestId(`tl-lane-${EQ}`)).queryAllByTestId(/^tl-axis-main-/)).toHaveLength(0);
  });

  it('G3 树状层级：同刻度事件收进同一时间节点（17 / 217×2 / 1024 = 3 节点），事件各一次', async () => {
    renderGrouped();
    await switchToWorld();

    const lane = screen.getByTestId(`tl-lane-${EQ}`);
    expect(within(lane).getAllByTestId(/^tl-timenode-/)).toHaveLength(3);
    expect(idsWithin(`tl-timenode-${EQ}-0`)).toEqual(['gA']);
    expect(idsWithin(`tl-timenode-${EQ}-1`)).toEqual(['gB', 'gC']);
    expect(idsWithin(`tl-timenode-${EQ}-2`)).toEqual(['gD']);
    // 同刻度计数（只有一个事件的节点不显示计数）
    expect(screen.getByTestId(`tl-timenode-${EQ}-1`)).toHaveTextContent('2 个事件');
    expect(screen.getByTestId(`tl-timenode-${EQ}-0`)).not.toHaveTextContent('个事件');
    // 每个事件恰好渲染一次（4 条，无重复）
    const all = within(lane).getAllByTestId(/^tl-axis-node-/).map((el) => el.getAttribute('data-testid'));
    expect(all).toHaveLength(4);
    expect(new Set(all).size).toBe(4);
  });

  it('G4 既有行为不回归：轴选择器（轴族 ≥2）/ 来源章胶囊 / 单事件检查 / 一致性检查', async () => {
    renderGrouped([...GROUP_EVENTS, gE]);
    await switchToWorld();

    expect(screen.getByTestId('tl-axis-picker')).toBeInTheDocument();
    expect(screen.getAllByTestId(/^tl-axis-chip-/)).toHaveLength(2);
    expect(screen.getByTestId('tl-check-all')).toBeInTheDocument();
    expect(screen.getByTestId('tl-check-one-gA')).toBeInTheDocument();
    expect(screen.getByTestId('tl-src-gA')).toHaveTextContent('第十一章 事件乙');
    expect(screen.getByTestId('tl-src-gD')).toHaveTextContent('未分章');
  });

  it('G5 轴族仅 1 条真实纪元轴 → 不渲染选择器，但仍渲染泳道组头（轴名不丢）', async () => {
    renderGrouped();
    await switchToWorld();

    expect(screen.queryByTestId('tl-axis-picker')).toBeNull();
    expect(screen.getByTestId(`tl-lane-${EQ}`)).toBeInTheDocument();
    expect(screen.getByTestId(`tl-lanehead-${EQ}`)).toHaveTextContent(EQ);
    expect(idsWithin(`tl-lane-${EQ}`)).toEqual(['gA', 'gB', 'gC', 'gD']);
  });
});
