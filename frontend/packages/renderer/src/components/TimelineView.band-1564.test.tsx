/**
 * #1564 + #1565 世界序刻度带 v2 —— 组件级契约（TimelineView）。
 *
 * 【spec 依据】specs/f19-gui/timeline.md §1.1（世界序刻度带 v2）/ §2（刻度带 + 分页 + 未知区行）/ §3 N16
 *
 * 【契约（GREEN 必须提供）】
 * - `tl-band` 容器：**底色 = 页面底色 token**（`bg-bg`，**不是** `bg-surface`）+ 保留 `rounded-lg` / `border-line`
 *   （#1565；两主题目视证据见 design/GUI/timeline/timeline-world-band{,-night}.png）
 * - **unknown 只计一次**：252 事件（12 有值 + 240 未知）下画布高度受限（#1541 旧公式 = 13,924px）；
 *   未知区表头 `tl-band-unknown-head` 显示总数，列表限高（`BAND_UNK_MAX`）
 * - **不定高**：每刻度一行，行高 ∝ 该刻度事件数 → 行参考线 `tl-band-rowguide` 间距异构
 * - **分页按刻度**：`tl-band-pager` / `tl-band-pageinfo`（第 x / y 页 · 每页 N 刻度 · 共 M 刻度）；
 *   `tl-band-page-prev` / `tl-band-page-next` 首末页禁用；翻页后**刻度集合变化**
 * - **时间主轴**：`tl-band-main` + `tl-band-mainnode-<i>`（数 = 本页刻度行数）
 * - **既有不回归**：来源章胶囊 / 单事件检查 / 一致性检查 / 按章·按类型筛选 / 事件行悬停态
 * - **负例**：更早形态 `tl-lane-*` / `tl-timenode-*` 不出现；刻度带不渲染 `tl-axis-main-<id>`
 *
 * 【RED 预期】`tl-band-pager` / `tl-band-main` / `tl-band-rowguide` 不存在；`tl-band` 仍是 `bg-surface`；
 * 画布高度 = 13,924px → C1-C5 FAIL。
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

const QY_VALUES = [17, 121, 217, 217, 258, 314, 402, 517, 517];
const XJ_VALUES = [1024, 2048, 3072, 4096, 5120, 6144, 7168, 8192];

function qyEvents(): TimelineEventDTO[] {
  return QY_VALUES.map((v, i) => ({
    id: `q${i + 1}`,
    title: `示例历事件 ${i + 1}`,
    era: QY,
    era_value: v,
    era_scale: 1,
    time_value: v,
    time_unit: '年',
    narrative_position: i + 1,
    source_chapter_id: i % 2 === 0 ? 'c11' : 'c12',
  }));
}

function xjEvents(): TimelineEventDTO[] {
  return XJ_VALUES.map((v, i) => ({
    id: `x${i + 1}`,
    title: `示例仙界事件 ${i + 1}`,
    era: XJ,
    era_value: v,
    era_scale: 10,
    time_value: v,
    time_unit: '年',
    narrative_position: 20 + i,
    source_chapter_id: null,
  }));
}

/** 有历但轴内值缺失 → 归「未知」（仍属该历，参与轴过滤） */
function unknownEvents(): TimelineEventDTO[] {
  return ['一', '二', '三'].map((c, i) => ({
    id: `u${i + 1}`,
    title: `有历但时间待考的记录${c}`,
    era: QY,
    era_value: null,
    time_value: null,
    narrative_position: 40 + i,
  }));
}

/** 多历：QY 9 事件（7 刻度，217/517 各双事件）+ XJ 8 事件（8 刻度，scale 10）+ 3 未知 → 15 刻度 */
const MULTI: TimelineEventDTO[] = [...qyEvents(), ...xjEvents(), ...unknownEvents()];

/** 252 事件量级：单默认轴 = 12 有值（11 刻度，含 1 个离群值）+ 240 未知 */
const DENSE: TimelineEventDTO[] = [
  ...[17, 121, 217, 217, 258, 314, 402, 517, 1024, 2048, 3072, 1000000].map((v, i) => ({
    id: `dv${i + 1}`,
    title: `有值事件 ${i + 1}`,
    time_value: v,
    time_unit: '年',
    time_display: `示例历 ${v} 年`,
    narrative_position: i + 1,
  })),
  ...Array.from({ length: 240 }, (_, i) => ({
    id: `dn${i + 1}`,
    title: `提取事件 ${i + 1}（无时间表达）`,
    narrative_position: 100 + i,
  })),
];

function renderView(events: TimelineEventDTO[]) {
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

const bandHeight = (): number => parseFloat((screen.getByTestId('tl-band') as HTMLElement).style.height);
const guideTops = (): number[] =>
  screen.getAllByTestId('tl-band-rowguide').map((n) => parseFloat((n as HTMLElement).style.top));

beforeEach(() => {
  apiFetchMock.mockReset();
  apiFetchMock.mockImplementation(async () => ({ checked: 0, skipped: 0, consistent: true, conflicts: [] }));
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('#1564 世界序刻度带 v2（组件级）', () => {
  it('C1 unknown 只计一次：252 事件（12 有值 + 240 未知）画布高度受限（旧公式 = 13,924px）', async () => {
    renderView(DENSE);
    await switchToWorld();

    expect(bandHeight()).toBeGreaterThan(200);
    expect(bandHeight()).toBeLessThan(900);
    expect(screen.getByTestId('tl-band-unknown-head')).toHaveTextContent('240');
  });

  it('C2 不定高：同一轴内不同刻度行高不同（行参考线间距异构）', async () => {
    renderView(MULTI);
    await switchToWorld();

    const tops = guideTops();
    expect(tops.length).toBeGreaterThan(1);
    const diffs = tops.slice(1).map((t, i) => t - tops[i]);
    expect(new Set(diffs).size).toBeGreaterThan(1);
  });

  it('C3 分页按刻度：每页 8 刻度；翻页后刻度集合变化；首末页禁用态', async () => {
    renderView(MULTI);
    await switchToWorld();
    await userEvent.setup().click(screen.getByTestId(`tl-axis-chip-${XJ}`));

    expect(screen.getByTestId('tl-band-pageinfo')).toHaveTextContent('第 1 / 2 页 · 每页 8 刻度 · 共 15 刻度');
    expect(screen.getByTestId('tl-band-page-prev')).toBeDisabled();
    expect(screen.getByTestId(`tl-band-tick-${QY}-0`)).toHaveTextContent('17 年');
    expect(screen.queryByText('517 年')).toBeNull();

    await userEvent.setup().click(screen.getByTestId('tl-band-page-next'));

    expect(screen.getByTestId('tl-band-pageinfo')).toHaveTextContent('第 2 / 2 页 · 每页 8 刻度 · 共 15 刻度');
    expect(screen.getByTestId('tl-band-page-next')).toBeDisabled();
    expect(screen.getByTestId(`tl-band-tick-${QY}-0`)).toHaveTextContent('402 年');
    expect(screen.getByText('517 年')).toBeInTheDocument();
    expect(screen.queryByText('17 年')).toBeNull();
  });

  it('C4 时间主轴可见：tl-band-main + 主轴刻度点数 = 本页刻度行数（据此定位）', async () => {
    renderView(MULTI);
    await switchToWorld();
    await userEvent.setup().click(screen.getByTestId(`tl-axis-chip-${XJ}`));

    expect(screen.getByTestId('tl-band-main')).toBeInTheDocument();
    expect(screen.getAllByTestId(/^tl-band-mainnode-/)).toHaveLength(8);
    expect(screen.getAllByTestId('tl-band-rowguide')).toHaveLength(8);
  });

  it('C5 离群值不压扁：加入 1 个极大值后，页内其它行 top 逐行不变', async () => {
    const base = [17, 121, 217, 258, 314].map((v, i) => ({
      id: `o${i + 1}`,
      title: `正常刻度事件 ${i + 1}`,
      time_value: v,
      time_unit: '年',
      narrative_position: i + 1,
    }));
    const withOutlier: TimelineEventDTO[] = [
      ...base,
      { id: 'big', title: '离群值事件', time_value: 1000000, time_unit: '年', narrative_position: 9 },
    ];

    const { unmount } = renderView(base);
    await switchToWorld();
    const before = guideTops();
    unmount();

    renderView(withOutlier);
    await switchToWorld();
    const after = guideTops();

    expect(before).toHaveLength(5);
    expect(after).toHaveLength(6);
    expect(after.slice(0, 5)).toEqual(before);
  });

  it('C6 底色（#1565）：容器底色 = 页面底色 token（bg-bg），且保留边框/圆角', async () => {
    renderView(MULTI);
    await switchToWorld();

    for (const theme of ['paper', 'night'] as const) {
      useThemeStore.setState({ theme, bg: 'default', lang: 'zh' });
      const cls = screen.getByTestId('tl-band').className;
      expect(cls).toContain('bg-bg');
      expect(cls).not.toContain('bg-surface');
    }
    const cls = screen.getByTestId('tl-band').className;
    expect(cls).toContain('rounded-lg');
    expect(cls).toContain('border-line');
  });

  it('C7 既有不回归：来源章胶囊 / 单事件检查 / 一致性检查 / 筛选 / 事件行悬停态', async () => {
    renderView(MULTI);
    await switchToWorld();

    expect(screen.getByTestId('tl-src-q1')).toBeInTheDocument();
    expect(screen.getByTestId('tl-check-one-q1')).toBeInTheDocument();
    expect(screen.getByTestId('tl-check-all')).toBeInTheDocument();
    expect(screen.getByTestId('tl-filter-chapter')).toBeInTheDocument();
    expect(screen.getByTestId('tl-filter-type')).toBeInTheDocument();
    expect(screen.getByTestId('tl-axis-node-q1').className).toContain('hover:bg-surface-2');
  });

  it('C8 负例：不出现更早形态（tl-lane-* / tl-timenode-*）；刻度带不渲染 tl-axis-main-<id>', async () => {
    renderView(MULTI);
    await switchToWorld();

    expect(screen.queryAllByTestId(/^tl-lane-/)).toHaveLength(0);
    expect(screen.queryAllByTestId(/^tl-timenode-/)).toHaveLength(0);
    expect(screen.queryAllByTestId(/^tl-axis-main-/)).toHaveLength(0);
  });
});
