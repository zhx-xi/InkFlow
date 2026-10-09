/**
 * #1541 世界序多历共存「单块多竖轴刻度带」—— 组件级契约（TimelineView）。
 *
 * 【spec 依据】specs/f19-gui/timeline.md §1.1（世界序刻度带）/ §2 刻度带行 / §3 N15
 *            + specs/f12-timeline/spec.md §2.8 E11（`to_global = era_value / era_scale`，ADR-065）。
 *
 * 【契约（GREEN 必须提供）】
 * - 世界序 = **单个块** `tl-band`：**无** `tl-lane-*` / `tl-timenode-*`（#1467 泳道形态废止）
 * - 每选中历：列头 `tl-band-head-<key>`（历名 + 计数）+ 竖轴 `tl-band-spine-<key>`
 *   + 刻度点 `tl-band-node-<key>-<i>` + 刻度标签 `tl-band-tick-<key>-<i>`（本地值）
 * - 事件行 `tl-axis-node-<id>` 以**历色连线** `tl-band-link-<id>` 指回本历竖轴
 * - 刻度纵向位置 = `to_global`（流速不同 ⇒ 疏密不同）；**同刻度只出现一次**
 * - 时间未知事件归轴底「未知」区（`tl-band-unknown`），不破坏结构
 * - 单轴（`era` 全空）= **1 条竖轴**（#1527 目标：不再平铺）；事件行**不渲染** `tl-axis-main-<id>`
 * - 既有行为不回归：轴选择器（轴族 ≥2）/ 来源章胶囊 / 单事件检查 / 一致性检查 / 筛选
 *
 * 【RED 预期】`tl-band*` 不存在 / 仍渲染 `tl-lane-*` / 单轴仍平铺 → B1-B9 FAIL。
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
const DK = '__none__';

/** 多历：QY×3（17 / 217 / 217）+ XJ×2（1024 / 4096，scale 10）+ 默认轴未知时间×1 */
const e1: TimelineEventDTO = { id: 'e1', title: '事件一', era: QY, era_value: 17, era_scale: 1, time_value: 17, time_unit: '年', time_display: '示例历 17 年', narrative_position: 1, source_chapter_id: 'c11' };
const e2: TimelineEventDTO = { id: 'e2', title: '事件二', era: QY, era_value: 217, era_scale: 1, time_value: 217, time_unit: '年', time_display: '示例历 217 年', narrative_position: 2, source_chapter_id: 'c12' };
const e3: TimelineEventDTO = { id: 'e3', title: '事件三', era: QY, era_value: 217, era_scale: 1, time_value: 217, time_unit: '年', time_display: '示例历 217 年', narrative_position: 3, source_chapter_id: 'c12' };
const e4: TimelineEventDTO = { id: 'e4', title: '事件四', era: XJ, era_value: 1024, era_scale: 10, time_value: 1024, time_unit: '年', time_display: '示例仙历 1024 年', narrative_position: 4 };
const e5: TimelineEventDTO = { id: 'e5', title: '事件五', era: XJ, era_value: 4096, era_scale: 10, time_value: 4096, time_unit: '年', time_display: '示例仙历 4096 年', narrative_position: 5 };
const e6: TimelineEventDTO = { id: 'e6', title: '事件六（无时间）', narrative_position: 6 };

const ERA_EVENTS = [e1, e2, e3, e4, e5, e6];
/** 单轴：era 全空（#1527 场景） */
const PLAIN_EVENTS: TimelineEventDTO[] = [
  { id: 'p1', title: '单轴甲', time_value: 10, time_unit: '年', time_display: '10 年', narrative_position: 1 },
  { id: 'p2', title: '单轴乙', time_value: 20, time_unit: '年', time_display: '20 年', narrative_position: 2 },
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

const left = (id: string) => (screen.getByTestId(id) as HTMLElement).style.left;
const top = (id: string) => parseFloat((screen.getByTestId(id) as HTMLElement).style.top);

beforeEach(() => {
  apiFetchMock.mockReset();
  apiFetchMock.mockImplementation(async () => ({ checked: 0, skipped: 0, consistent: true, conflicts: [] }));
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('#1541 世界序「单块刻度带」', () => {
  it('B1 单块：仅 1 个 tl-band；无泳道卡片（tl-lane-*）/ 无 tl-timenode-*', async () => {
    renderView();
    await switchToWorld();

    expect(screen.getByTestId('tl-band')).toBeInTheDocument();
    expect(screen.queryAllByTestId(/^tl-lane-/)).toHaveLength(0);
    expect(screen.queryAllByTestId(/^tl-timenode-/)).toHaveLength(0);
  });

  it('B2 每选中历一条竖轴 + 列头（含计数）；事件行只属选中历', async () => {
    renderView();
    await switchToWorld();

    // 默认只勾选主力轴（QY，3 个事件）
    expect(screen.getByTestId(`tl-band-spine-${QY}`)).toBeInTheDocument();
    expect(screen.queryByTestId(`tl-band-spine-${XJ}`)).toBeNull();
    expect(screen.getByTestId(`tl-band-head-${QY}`)).toHaveTextContent(QY);
    expect(screen.getByTestId(`tl-band-head-${QY}`)).toHaveTextContent('3');

    // 勾上第二历 → 两条竖轴、两侧事件
    await userEvent.setup().click(screen.getByTestId(`tl-axis-chip-${XJ}`));
    expect(screen.getByTestId(`tl-band-spine-${XJ}`)).toBeInTheDocument();
    expect(screen.getByTestId(`tl-band-head-${XJ}`)).toHaveTextContent(XJ);
    expect(screen.getAllByTestId(/^tl-axis-node-/)).toHaveLength(5); // QY 3 + XJ 2
  });

  it('B3 刻度纵向按 to_global：XJ(1024/scale10 → g=102.4) 落在 QY 的 g=17 与 g=217 之间', async () => {
    renderView();
    await switchToWorld();
    await userEvent.setup().click(screen.getByTestId(`tl-axis-chip-${XJ}`));

    // QY 刻度（去重后 2 个：17 / 217）；XJ 刻度（去重后 2 个：102.4 / 409.6）
    expect(screen.queryByTestId(`tl-band-tick-${QY}-0`)).toBeInTheDocument();
    expect(screen.getByTestId(`tl-band-tick-${QY}-1`)).toHaveTextContent('217');
    expect(screen.getByTestId(`tl-band-tick-${XJ}-0`)).toHaveTextContent('1024');

    const qy0 = top(`tl-band-node-${QY}-0`);
    const qy1 = top(`tl-band-node-${QY}-1`);
    const xj0 = top(`tl-band-node-${XJ}-0`);
    expect(qy0).toBeLessThan(xj0);
    expect(xj0).toBeLessThan(qy1);
  });

  it('B4 同刻度只出现一次；同刻度事件行顺次错开（不重叠）', async () => {
    renderView();
    await switchToWorld();

    // QY 有 3 个事件但只有 2 个刻度
    expect(screen.queryAllByTestId(new RegExp(`^tl-band-tick-${QY}-`))).toHaveLength(2);
    expect(screen.queryAllByTestId(new RegExp(`^tl-band-node-${QY}-`))).toHaveLength(2);

    const r2 = top('tl-axis-node-e2');
    const r3 = top('tl-axis-node-e3');
    expect(Math.abs(r2 - r3)).toBeGreaterThanOrEqual(12); // 错开
  });

  it('B5 连线指回本历竖轴（tl-band-link-<id> 的 left == 本历 spine 的 left）', async () => {
    renderView();
    await switchToWorld();
    await userEvent.setup().click(screen.getByTestId(`tl-axis-chip-${XJ}`));

    expect(left('tl-band-link-e1')).toBe(left(`tl-band-spine-${QY}`));
    expect(left('tl-band-link-e4')).toBe(left(`tl-band-spine-${XJ}`));
    expect(left('tl-band-link-e1')).not.toBe(left('tl-band-link-e4'));
  });

  it('B6 单轴（era 全空）= 1 条竖轴刻度带；不再平铺（无 tl-axis-main）', async () => {
    renderView(PLAIN_EVENTS);
    await switchToWorld();

    expect(screen.getByTestId('tl-band')).toBeInTheDocument();
    expect(screen.queryAllByTestId(/^tl-band-spine-/)).toHaveLength(1);
    expect(screen.queryAllByTestId(/^tl-band-spine-/) /* 单轴哨兵为默认轴 */).toHaveLength(1);
    expect(screen.getByTestId(`tl-band-spine-${DK}`)).toBeInTheDocument();
    expect(screen.queryAllByTestId(/^tl-band-tick-/).length).toBeGreaterThan(0);
    expect(screen.queryAllByTestId(/^tl-axis-main-/)).toHaveLength(0);
    expect(screen.getAllByTestId(/^tl-axis-node-/)).toHaveLength(2);
    // 无选择器（轴族只有 1 条）
    expect(screen.queryByTestId('tl-axis-picker')).toBeNull();
  });

  it('B7 时间未知事件归轴底「未知」区，不破坏结构、不丢失', async () => {
    renderView();
    await switchToWorld();
    await userEvent.setup().click(screen.getByTestId(`tl-axis-chip-${DK}`)); // 展开默认轴（e6 在此）

    expect(screen.getByTestId('tl-band-unknown')).toBeInTheDocument();
    expect(screen.getByTestId('tl-axis-node-e6')).toBeInTheDocument();
    // 未知事件不产生刻度
    expect(screen.queryAllByTestId(new RegExp(`^tl-band-tick-${DK}-`))).toHaveLength(0);
  });

  it('B8 既有行为不回归：轴选择器 / 来源章胶囊 / 单事件检查 / 一致性检查 / 筛选', async () => {
    renderView();
    await switchToWorld();

    expect(screen.getByTestId('tl-axis-picker')).toBeInTheDocument();
    expect(screen.getAllByTestId(/^tl-axis-chip-/)).toHaveLength(3);
    expect(screen.getByTestId('tl-check-all')).toBeInTheDocument();
    expect(screen.getByTestId('tl-check-one-e1')).toBeInTheDocument();
    expect(screen.getByTestId('tl-src-e1')).toHaveTextContent('第十一章 事件乙');
    expect(screen.getByTestId('tl-filter-chapter')).toBeInTheDocument();
    expect(screen.getByTestId('tl-filter-type')).toBeInTheDocument();
  });

  it('B9 叙事序不受影响（章刻度仍在，无 tl-band）', () => {
    renderView();
    expect(screen.getByTestId('tl-chtick-c11')).toBeInTheDocument();
    expect(screen.queryByTestId('tl-band')).toBeNull();
  });
});
