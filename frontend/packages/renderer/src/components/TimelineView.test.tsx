/**
 * #1301 时间线时间轴渲染 —— 组件级契约。
 *
 * 【spec 依据】
 * - specs/f12-timeline/spec.md:621/702「事件时间线（世界内时间轴）」排序键 time_value
 * - specs/f43-setting-library-gui/spec.md:773「图例 tl-legend」
 * - specs/f19-gui/timeline.md（#1323 后：章分组容器 + 真实章节标题）
 *
 * 【#1323 语义升级（本文件 A2/A3/A4 改写）】
 * 旧契约把副标记写成 `narrative_position` 拼的「第 N 章」。该字段是**单一线性序号**
 * （domain/models/timeline.py:158；specs/f12-timeline/spec.md:91 明确不携带章节语义）
 * → DB 实测 215 条只有 34 个不同位置值，同一「第 7 章」重复 10 次。
 * 现契约：
 * - 主轴（tl-axis-main-<id>）= 世界内时间（两序一致，时间才是有信息量的那一维）
 * - 副标记（tl-axis-sub-<id>）**不再渲染章号**（章节信息由章分组 header 承载）
 * 章分组契约见 TimelineView.grouping.test.tsx（B1-B6）。
 *
 * 【testid 契约】
 * - tl-axis            分组容器（轴线本体）
 * - library-list       单一列表容器（**全页恰好一个**，不再重复渲染）
 * - tl-axis-node-<id>  每个事件一个节点（每个事件恰好一次）
 * - tl-axis-main-<id>  主轴文本
 * - tl-group-<chapterId> / tl-group-title-<chapterId>  章分组与其 header
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
  source_chapter_id: 'c11',
};
const evB: TimelineEventDTO = {
  id: 'evB', title: '乙 失踪', time_value: null, time_unit: null,
  time_display: '', narrative_position: 1, timeline_flag: false,
  source_chapter_id: null,
};
const evC: TimelineEventDTO = {
  id: 'evC', title: '丙 初现', time_value: 100, time_unit: 'year',
  time_display: '100 年', narrative_position: 2, timeline_flag: false,
  source_chapter_id: 'c12',
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

  it('A2 主轴 = 世界内时间（time_display），两序一致；副标记不承载章号', async () => {
    renderView();
    const user = userEvent.setup();
    await user.click(screen.getByTestId('tl-view-world'));
    // 主轴：世界内时间
    await waitFor(() => expect(screen.getByTestId('tl-axis-main-evC')).toHaveTextContent('100 年'));
    expect(screen.getByTestId('tl-axis-main-evA')).toHaveTextContent('300 年');
    // #1323 语义升级：副标记不再输出 narrative_position 拼成的章号
    expect(screen.queryByTestId('tl-axis-sub-evC')).not.toBeInTheDocument();
    expect(screen.queryByTestId('tl-axis-sub-evA')).not.toBeInTheDocument();
  });

  it('A3 叙事序主轴同样是世界内时间（反向断言：主轴绝不出章号）', async () => {
    renderView();
    const user = userEvent.setup();
    // 默认即叙事序
    expect(screen.getByTestId('tl-view-narrative')).toHaveAttribute('aria-pressed', 'true');
    await waitFor(() => expect(screen.getByTestId('tl-axis-main-evC')).toHaveTextContent('100 年'));
    expect(screen.getByTestId('tl-axis-main-evA')).toHaveTextContent('300 年');
    // 反向断言：主轴绝不含「第{n}章」形式的伪章号
    const mains = screen.getAllByTestId(/^tl-axis-main-/).map((el) => el.textContent ?? '').join('|');
    expect(mains).not.toMatch(/第\s*[0-9]+\s*章/);
    // 切序后主轴仍是世界内时间（不再主/副互换）
    await user.click(screen.getByTestId('tl-view-world'));
    await waitFor(() => expect(screen.getByTestId('tl-axis-main-evC')).toHaveTextContent('100 年'));
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
    // #1323：每事件恰好一个节点（单一容器，不再重复渲染）
    expect(screen.getAllByTestId(/^tl-axis-node-/)).toHaveLength(3);
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
