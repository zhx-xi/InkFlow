/**
 * #1301 时间线缺时间轴渲染（spec↔实现漂移）——组件级契约。
 *
 * 【spec 依据（4 处）】
 * - specs/f12-timeline/spec.md:621  「事件时间线（世界内时间轴）｜排序键 time_value｜
 *   (time_value ASC NULLS LAST, narrative_position ASC)」
 * - specs/f12-timeline/spec.md:702  「事件时间线（世界内时间轴）：time_value 升序；时间未知排末尾」
 * - specs/f43-setting-library-gui/spec.md:773「图例：tl-legend（「点=叙事顺序 · 时间轴=世界内时间」）」
 * - specs/f19-gui/timeline.md:34     同上图例文案
 *
 * 【漂移】实现（TimelineView.tsx）只有平铺 <ul>，无任何轴线/节点/刻度元素；
 * 图例文案却在说「时间轴」→ spec 要求存在、实现未交付。
 *
 * 【本批契约：双序「主轴 + 副标记」映射（用户 #1301 原文）】
 * | 序     | 主轴（tl-axis-main-<id>）  | 副标记（tl-axis-sub-<id>） |
 * |--------|----------------------------|----------------------------|
 * | 世界序 | 世界内时间（time_display） | 章节序号（narrative_position） |
 * | 叙事序 | 章节序号（narrative_position） | 世界内时间（time_display） |
 *
 * 【testid 清单（GREEN 必须提供）】
 * - tl-axis            时间轴容器（轴线本体；竖向时间轴惯例）
 * - tl-axis-node-<id>  每个事件一个轴节点（<id> = 事件 id）
 * - tl-axis-main-<id>  该节点主轴文本（随序切换互换）
 * - tl-axis-sub-<id>   该节点副标记文本（随序切换互换）
 *
 * 【保留不破】timeline-toolbar / tl-view-narrative / tl-view-world / tl-check-all /
 * tl-check-one-<id> / tl-legend / library-list 行为不变。
 *
 * 【RED 预期】tl-axis* 全部不存在 → 4 个 it FAIL（element-missing）；
 * 零 SyntaxError / ReferenceError / TypeError / Transform failed。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TimelineView, type TimelineEventDTO } from './TimelineView';
import { apiFetch } from '../api/client';
import { useThemeStore } from '../stores/theme';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

/**
 * Seed 事件（与 library-p4.test.tsx 同形，双序可严格区分）：
 * - 世界序（time_value 升序、未知末尾）：evC(100) → evA(300) → evB(未知)
 * - 叙事序（narrative_position 升序）：evB(1) → evC(2) → evA(3)
 */
const evA: TimelineEventDTO = {
  id: 'evA', title: '甲 登基', time_value: 300, time_unit: 'year',
  time_display: '300 年', narrative_position: 3, timeline_flag: false,
};
const evB: TimelineEventDTO = {
  id: 'evB', title: '乙 失踪', time_value: null, time_unit: null,
  time_display: '', narrative_position: 1, timeline_flag: false,
};
const evC: TimelineEventDTO = {
  id: 'evC', title: '丙 初现', time_value: 100, time_unit: 'year',
  time_display: '100 年', narrative_position: 2, timeline_flag: false,
};

function renderView() {
  return render(
    <TimelineView projectId="p1" eventTimeline={[evC, evA, evB]} narrativeOrder={[evB, evC, evA]} />,
  );
}

beforeEach(() => {
  apiFetchMock.mockReset();
  apiFetchMock.mockImplementation(async () => ({ checked: 0, skipped: 0, consistent: true, conflicts: [] }));
  useThemeStore.setState({ lang: 'zh' });
});

describe('#1301 时间线时间轴渲染（spec f12:621/702 · f43:773 · f19:34）', () => {
  it('A1 时间轴元素存在：渲染后有 tl-axis 容器 + 每个事件一个 tl-axis-node-<id>', async () => {
    renderView();
    expect(screen.getByTestId('tl-axis')).toBeInTheDocument();
    expect(screen.getByTestId('tl-axis-node-evA')).toBeInTheDocument();
    expect(screen.getByTestId('tl-axis-node-evB')).toBeInTheDocument();
    expect(screen.getByTestId('tl-axis-node-evC')).toBeInTheDocument();
  });

  it('A2 世界序：主轴 = 世界内时间（time_display），副标记 = 章节序号（narrative_position）', async () => {
    renderView();
    const user = userEvent.setup();
    await user.click(screen.getByTestId('tl-view-world'));
    // 主轴：世界内时间
    await waitFor(() => expect(screen.getByTestId('tl-axis-main-evC')).toHaveTextContent('100 年'));
    expect(screen.getByTestId('tl-axis-main-evA')).toHaveTextContent('300 年');
    // 副标记：章节序号（narrative_position）——evC=2 / evA=3
    expect(screen.getByTestId('tl-axis-sub-evC')).toHaveTextContent('2');
    expect(screen.getByTestId('tl-axis-sub-evA')).toHaveTextContent('3');
  });

  it('A3 叙事序主/副互换（反向断言）：主轴 = 章节序号，副标记 = 世界内时间', async () => {
    renderView();
    const user = userEvent.setup();
    // 默认即叙事序
    expect(screen.getByTestId('tl-view-narrative')).toHaveAttribute('aria-pressed', 'true');
    // 主轴：章节序号（narrative_position）——evB=1 / evC=2 / evA=3
    await waitFor(() => expect(screen.getByTestId('tl-axis-main-evB')).toHaveTextContent('1'));
    expect(screen.getByTestId('tl-axis-main-evC')).toHaveTextContent('2');
    expect(screen.getByTestId('tl-axis-main-evA')).toHaveTextContent('3');
    // 副标记：世界内时间（time_display）
    expect(screen.getByTestId('tl-axis-sub-evC')).toHaveTextContent('100 年');
    expect(screen.getByTestId('tl-axis-sub-evA')).toHaveTextContent('300 年');
    // ⚠️ 反向断言：叙事序下主轴绝不再是世界内时间
    expect(screen.getByTestId('tl-axis-main-evC')).not.toHaveTextContent('100 年');
    // 切到世界序后主轴/副标记互换（同一节点文本反转）
    await user.click(screen.getByTestId('tl-view-world'));
    await waitFor(() => expect(screen.getByTestId('tl-axis-main-evC')).toHaveTextContent('100 年'));
    expect(screen.getByTestId('tl-axis-sub-evC')).toHaveTextContent('2');
  });

  it('A4 时间未知事件（time_value=null）在轴上用「未知」占位，不消失', async () => {
    renderView();
    const user = userEvent.setup();
    await user.click(screen.getByTestId('tl-view-world'));
    const node = await screen.findByTestId('tl-axis-node-evB');
    expect(node).toBeInTheDocument();
    // 主轴无 time_display → 回退未知占位（i18n lib.tlTimeUnknown）
    expect(screen.getByTestId('tl-axis-main-evB')).toHaveTextContent('未知');
  });

  it('A5 既有行为不破：双序 chips / tl-check-all / tl-check-one-<id> / tl-legend 仍存在可用', async () => {
    renderView();
    expect(screen.getByTestId('timeline-toolbar')).toBeInTheDocument();
    expect(screen.getByTestId('tl-view-narrative')).toBeInTheDocument();
    expect(screen.getByTestId('tl-view-world')).toBeInTheDocument();
    expect(screen.getByTestId('tl-check-all')).toBeInTheDocument();
    expect(screen.getByTestId('tl-legend')).toHaveTextContent('点=叙事顺序 · 时间轴=世界内时间');
    expect(screen.getByTestId('tl-check-one-evA')).toBeInTheDocument();
    expect(screen.getByTestId('library-list')).toBeInTheDocument();
    // 轴节点顺序随序切换（世界序：evC → evA → evB）
    const user = userEvent.setup();
    await user.click(screen.getByTestId('tl-view-world'));
    await waitFor(() => {
      const ids = screen
        .getAllByTestId(/^tl-axis-node-/)
        .map((el) => el.getAttribute('data-testid')!.replace('tl-axis-node-', ''));
      expect(ids).toEqual(['evC', 'evA', 'evB']);
    });
  });
});
